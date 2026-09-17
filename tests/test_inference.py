"""Context inference: opt-in, bounded, receipted, and never trusted as fact."""

import io
import json
import re
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from activity_app import inference
from activity_app.memory_capture import MemoryRecorder

CONTEXT = {
    "summary": "Comparing supplier quotes for the sensor order.",
    "activity": "Reading a spreadsheet of unit prices",
    "task": "Sensor procurement for the BrainBook build",
    "entities": ["BrainBook", "unit price", "supplier"],
    "open_loops": ["Two quotes have not answered"],
    "next_step": "Reply to the second supplier",
    "confidence": "medium",
    "evidence": ["caller-fills"],
}


def tiny_image(color="#f7f7fa"):
    out = io.BytesIO()
    Image.new("RGB", (64, 40), color).save(out, "PNG")
    return out.getvalue()


class Stub:
    """One OpenAI-compatible endpoint that records exactly what it received."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.calls.append({"path": self.path, "headers": dict(self.headers), "body": body})
                reply = outer.replies.pop(0) if outer.replies else {"choices": [{"message": {"content": "{}"}}]}
                status = 200
                if callable(reply):
                    reply = reply(body)
                if isinstance(reply, tuple):
                    status, reply = reply
                payload = json.dumps(reply).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d/v1" % self.server.server_port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def answer(body):
    """Reply with a valid context that cites a moment from the actual request."""
    ids = re.findall(r"\[([a-f0-9]{32})\]", body["messages"][1]["content"])
    return {"choices": [{"message": {"content": json.dumps({**CONTEXT, "evidence": ids[:1]})}}]}


class InferHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.recorder = MemoryRecorder(Path(self.tmp.name), lambda: True)
        self.calls = []
        self.stubs = []

    def tearDown(self):
        for stub in self.stubs:
            stub.close()
        self.recorder.close()
        self.tmp.cleanup()

    def stub(self, replies):
        server = Stub(replies)
        self.stubs.append(server)
        return server

    def seed(self, count=3, text="Orchid river research notes for the sensor order."):
        now = time.time()
        return [
            self.recorder.store.add(
                {
                    "title": "Local OCR verification %d" % index,
                    "app": "Verification Notes",
                    "text": text,
                    "ts": now - index * 30,
                },
                tiny_image(),
            )["id"]
            for index in range(count)
        ]

    def enable(self, url, key="sk-test-secret", model="stub-model"):
        self.recorder.configure(
            {
                "inference_enabled": True,
                "inference_base_url": url,
                "inference_model": model,
                "inference_key": key,
            }
        )


class InferenceTests(InferHarness):
    def test_off_by_default_and_never_calls_out(self):
        stub = self.stub([answer])
        ids = self.seed()
        status = self.recorder.status()
        self.assertIs(status["settings"]["inference_enabled"], False)
        self.assertIs(status["settings"]["inference_key_set"], False)
        # Search, status and settings reads must not reach a model.
        self.recorder.store.search(query="orchid")
        self.recorder.status()
        with self.assertRaises(inference.NotConfigured):
            self.recorder.infer(ids)
        self.assertEqual(stub.calls, [])

    def test_request_carries_text_only_and_receipts_the_call(self):
        stub = self.stub([answer])
        ids = self.seed()
        self.enable(stub.url)
        result = self.recorder.infer(ids)
        self.assertEqual(len(stub.calls), 1)
        call = stub.calls[0]
        self.assertEqual(call["path"], "/v1/chat/completions")
        self.assertEqual(call["headers"]["Authorization"], "Bearer sk-test-secret")
        self.assertEqual(call["body"]["model"], "stub-model")
        self.assertEqual(call["body"]["response_format"], {"type": "json_object"})
        sent = json.dumps(call["body"])
        self.assertIn("Orchid river", sent)
        self.assertIn("Verification Notes", sent)
        for absent in ("data:image", "media", ".bin", "vault.key", "base64"):
            self.assertNotIn(absent, sent)
        self.assertNotIn(tiny_image().hex(), sent)
        self.assertLessEqual(result["characters"], inference.MAX_PROMPT_CHARS + 400)
        self.assertEqual(result["context"]["confidence"], "medium")
        self.assertTrue(result["context"]["evidence"])
        receipt = self.recorder.store.receipts()
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt[0]["action"], "Context inference")
        self.assertEqual(receipt[0]["client"], "Local model call")
        self.assertEqual(receipt[0]["model"], "stub-model")
        self.assertEqual(receipt[0]["endpoint"], "127.0.0.1:%d" % stub.server.server_port)
        self.assertIn("supplier quotes", receipt[0]["context"]["summary"])
        self.assertEqual(receipt[0]["sources"], len(result["sources"]))
        self.assertTrue(all(source["ts"] for source in receipt[0]["scope"]))

    def test_key_is_stored_encrypted_and_never_returned(self):
        stub = self.stub([answer])
        ids = self.seed()
        self.enable(stub.url, key="sk-live-secret-value")
        self.recorder.infer(ids)
        visible = json.dumps(self.recorder.status())
        self.assertNotIn("sk-live-secret-value", visible)
        self.assertIs(self.recorder.status()["settings"]["inference_key_set"], True)
        self.assertNotIn(b"sk-live-secret-value", (self.recorder.path).read_bytes())
        self.assertEqual(self.recorder.store.receipts()[0].get("inference_key"), None)
        self.recorder.configure({"inference_key_clear": True})
        self.assertEqual(self.recorder.secrets()["inference_key"], "")

    def test_invalid_json_is_retried_once_then_refused(self):
        stub = self.stub(
            [
                {"choices": [{"message": {"content": "not json at all"}}]},
                {"choices": [{"message": {"content": json.dumps(CONTEXT)}}]},
            ]
        )
        ids = self.seed()
        self.enable(stub.url)
        result = self.recorder.infer(ids)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(len(stub.calls), 2)
        self.assertIn("JSON object only", stub.calls[1]["body"]["messages"][1]["content"])

    def test_persistent_garbage_fails_without_inventing_context(self):
        stub = self.stub([{"choices": [{"message": {"content": "nope"}}]}] * 2)
        ids = self.seed()
        self.enable(stub.url)
        with self.assertRaises(inference.SchemaError):
            self.recorder.infer(ids)
        self.assertEqual(self.recorder.store.receipts(), [])

    def test_null_content_is_retryable(self):
        stub = self.stub(
            [
                {"choices": [{"message": {"content": None}}]},
                answer,
            ]
        )
        ids = self.seed()
        self.enable(stub.url)
        result = self.recorder.infer(ids)
        self.assertEqual(result["attempts"], 2)

    def test_fenced_json_is_accepted_and_unknown_evidence_dropped(self):
        stub = self.stub(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "content": "```json\n"
                                + json.dumps(
                                    {
                                        **CONTEXT,
                                        "evidence": ["deadbeef" * 4, "not-an-id"],
                                        "confidence": "certain",
                                    }
                                )
                                + "\n```"
                            }
                        }
                    ]
                }
            ]
        )
        ids = self.seed()
        self.enable(stub.url)
        context = self.recorder.infer(ids)["context"]
        self.assertEqual(context["evidence"], [])
        self.assertTrue(context["unsourced"])
        self.assertEqual(context["confidence"], "low")

    def test_transport_failure_is_reported_not_guessed(self):
        ids = self.seed()
        self.enable("http://127.0.0.1:9/v1")
        with self.assertRaises(inference.InferenceError):
            self.recorder.infer(ids)
        self.assertEqual(self.recorder.store.receipts(), [])

    def test_prompt_is_capped_and_keeps_the_newest_moments(self):
        ids = self.seed(count=8, text="Filler line about the sensor order. " * 200)
        items = self.recorder.store.context_items(ids, expand=False, limit=20)
        block = inference.moment_block(items)
        self.assertLessEqual(len(block), inference.MAX_PROMPT_CHARS)
        # Newest moments survive the cap; the oldest are dropped, not summarised.
        self.assertIn(ids[0], block)
        self.assertNotIn(ids[-1], block)

    def test_only_chosen_and_neighbouring_moments_are_sent(self):
        ids = self.seed(count=3)
        now = time.time()
        self.recorder.store.add(
            {"title": "Unrelated chat", "app": "Chat", "text": "lunch plans", "ts": now - 4000},
            tiny_image(),
        )
        items = self.recorder.store.context_items([ids[1]])
        self.assertIn(ids[1], [item["id"] for item in items])
        self.assertTrue(all(item["app"] == "Verification Notes" for item in items))
        self.assertEqual(
            [item["id"] for item in self.recorder.store.context_items([ids[1]], expand=False)], [ids[1]]
        )

    def test_endpoint_rules_reject_untrusted_addresses(self):
        self.assertEqual(
            inference.endpoint("https://api.example.com/v1"), "https://api.example.com/v1/chat/completions"
        )
        self.assertEqual(
            inference.endpoint("http://127.0.0.1:8080/v1/chat/completions"),
            "http://127.0.0.1:8080/v1/chat/completions",
        )
        for bad in (
            "http://api.example.com/v1",
            "ftp://api.example.com",
            "https://user:pass@api.example.com/v1",
            "https://api.example.com/v1?key=1",
            "",
        ):
            with self.assertRaises(inference.NotConfigured, msg=bad):
                inference.endpoint(bad)

    def test_settings_validation_and_response_format_fallback(self):
        stub = self.stub(
            [
                (400, {"error": {"message": "unsupported parameter: response_format"}}),
                answer,
            ]
        )
        ids = self.seed()
        self.enable(stub.url)
        result = self.recorder.infer(ids)
        self.assertEqual(len(stub.calls), 2)
        self.assertNotIn("response_format", stub.calls[1]["body"])
        self.assertTrue(result["context"]["summary"])
        for bad in (
            {"inference_enabled": "yes"},
            {"inference_base_url": "x" * 300},
            {"inference_model": 5},
            {"inference_key": "k" * 500},
            {"unknown": 1},
        ):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.recorder.configure(bad)

    def test_reply_that_is_not_text_is_refused(self):
        for content in (None, "", "   ", 42, {"summary": "no"}):
            with self.assertRaises(inference.ShapeError, msg=repr(content)):
                inference.parse_reply(content, ["a" * 32])
        with self.assertRaises(inference.SchemaError):
            inference.parse_reply(json.dumps(["not", "an", "object"]), ["a" * 32])
        with self.assertRaises(inference.SchemaError):
            inference.parse_reply(json.dumps({"summary": 5}), ["a" * 32])


class InferenceHttpTests(InferHarness):
    """The loopback boundary, the off state, and the failure path over HTTP."""

    def setUp(self):
        super().setUp()
        from test_controller import InputSource

        from activity_app.controller import Controller
        from activity_app.web import AppServer

        self.recorder.close()
        self.controller = Controller(Path(self.tmp.name), backend_factory=InputSource, poll_interval=0.02)
        self.controller.start()
        self.recorder = self.controller.memory
        self.server = AppServer(self.controller, port=0)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(5)
        self.controller.close()
        for stub in self.stubs:
            stub.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, auth=True):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        headers = {"Content-Type": "application/json"}
        if auth:
            headers.update(self.auth)
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read() or b"{}")
        conn.close()
        return result

    def authenticate(self):
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        conn.request(
            "POST",
            "/api/session",
            json.dumps({"token": self.server.token}),
            {"Content-Type": "application/json", "Origin": self.server.origin},
        )
        response = conn.getresponse()
        cookie = dict(response.getheaders())["Set-Cookie"].split(";")[0]
        response.read()
        conn.close()
        self.auth = {"Cookie": cookie, "X-Tracker-Action": "1", "Origin": self.server.origin}

    def test_off_state_failure_and_success_over_http(self):
        self.authenticate()
        ids = self.seed()
        status, payload = self.request("POST", "/api/memory/infer", json.dumps({"ids": ids}))
        self.assertEqual(status, 409)
        self.assertEqual(payload["inference"], "off")
        self.authenticate()  # a rejected call must not disturb the session
        self.enable("http://127.0.0.1:9/v1")
        status, payload = self.request("POST", "/api/memory/infer", json.dumps({"ids": ids}))
        self.assertEqual(status, 502)
        self.assertEqual(payload["inference"], "failed")
        stub = self.stub([answer, answer])
        self.authenticate()
        self.enable(stub.url, key="sk-live-secret-value")
        status, payload = self.request("POST", "/api/memory/infer", json.dumps({"ids": ids}))
        self.assertEqual(status, 200)
        self.assertEqual(payload["context"]["activity"], CONTEXT["activity"])
        self.assertEqual(payload["receipt"]["action"], "Context inference")
        for path in ("/api/memory/status", "/api/memory?limit=5", "/api/memory/access"):
            status, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertNotIn("sk-live-secret-value", json.dumps(body))
        self.assertEqual(self.request("POST", "/api/memory/infer", json.dumps({"ids": ids}))[0], 200)

    def test_inference_cannot_be_reached_without_the_local_session(self):
        ids = self.seed()
        stub = self.stub([answer])
        self.enable(stub.url)
        self.assertEqual(
            self.request("POST", "/api/memory/infer", json.dumps({"ids": ids}), auth=False)[0], 401
        )
        self.authenticate()
        self.assertEqual(
            self.request(
                "POST",
                "/api/memory/infer",
                json.dumps({"ids": ids}),
                auth=False,
            )[0],
            401,
        )
        code, _ = self.request("POST", "/api/memory/infer", json.dumps({"ids": []}))
        self.assertEqual(code, 400)
        self.assertEqual(stub.calls, [])


if __name__ == "__main__":
    unittest.main()