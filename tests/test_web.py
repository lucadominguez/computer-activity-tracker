import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path

from test_controller import InputSource

from activity_app.controller import Controller


class WebTests(unittest.TestCase):
    def test_authenticated_browser_can_read_and_pause_but_other_sites_cannot(self):
        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.web"), "Local application server is missing"
        )
        from activity_app.web import AppServer

        with tempfile.TemporaryDirectory() as tmp:
            controller = Controller(Path(tmp), backend_factory=InputSource, poll_interval=0.02)
            controller.start()
            server = AppServer(controller, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            def request(method, path, body=None, headers=None):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                conn.request(method, path, body=body, headers=headers or {})
                response = conn.getresponse()
                result = response.status, dict(response.getheaders()), response.read()
                conn.close()
                return result

            try:
                self.assertEqual(request("GET", "/api/status")[0], 401)
                self.assertEqual(request("GET", "/activity.sqlite3")[0], 404)
                self.assertEqual(request("GET", "/", headers={"Host": "evil.example"})[0], 403)
                code, headers, _ = request(
                    "POST",
                    "/api/session",
                    json.dumps({"token": server.token}),
                    {"Content-Type": "application/json", "Origin": server.origin},
                )
                self.assertEqual(code, 200)
                self.assertIn("HttpOnly", headers["Set-Cookie"])
                self.assertIn("SameSite=Strict", headers["Set-Cookie"])
                auth = {"Cookie": headers["Set-Cookie"].split(";")[0]}
                code, headers, payload = request("GET", "/api/status", headers=auth)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(payload)["state"], "recording")
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                code, _, payload = request("GET", "/api/report?start=1&end=10", headers=auth)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(payload)["events"], [])
                for extra in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                    self.assertEqual(request("GET", "/api/status", headers={**auth, **extra})[0], 403)
                self.assertEqual(request("POST", "/api/control", '{"action":"pause"}', auth)[0], 403)
                control = {
                    **auth,
                    "Content-Type": "application/json",
                    "X-Tracker-Action": "1",
                    "Origin": server.origin,
                }
                code, _, payload = request("POST", "/api/control", '{"action":"pause"}', control)
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(payload)["state"], "paused")
                self.assertEqual(request("GET", "/api/report?start=nan&end=10", headers=auth)[0], 400)
                self.assertEqual(request("GET", "/api/report?start=1&end=10&offset=-1", headers=auth)[0], 400)
                self.assertEqual(request("POST", "/api/control", "[]", control)[0], 400)
                self.assertEqual(request("GET", "/api/memory")[0], 401)
                self.assertEqual(request("GET", "/api/memory?start=nan", headers=auth)[0], 400)
                code, _, payload = request("GET", "/api/memory", headers=auth)
                self.assertEqual(code, 200, "Encrypted memory API is missing")
                self.assertEqual(json.loads(payload)["total"], 0)
                item = controller.memory.store.add(
                    {"title": "Private OCR note", "app": "Notepad", "text": "orchid 987", "ts": 5},
                    b"local-webp-image",
                )
                image_path = "/api/memory/image/" + item["id"]
                self.assertEqual(request("GET", image_path)[0], 401)
                self.assertEqual(request("GET", image_path, headers=auth)[2], b"local-webp-image")
                code, _, payload = request(
                    "POST", "/api/memory/handoff", json.dumps({"ids": [item["id"]]}), control
                )
                self.assertEqual(code, 200)
                self.assertIn("orchid 987", json.loads(payload)["text"])
                self.assertEqual(len(controller.memory.store.receipts()), 1)
                self.assertEqual(
                    request("POST", "/api/memory/settings", '{"enabled":"false"}', control)[0], 400
                )
                self.assertEqual(request("GET", "/api/memory?start=0&start=1", headers=auth)[0], 400)
                self.assertEqual(request("GET", "/api/control?action=quit", headers=auth)[0], 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                controller.close()


if __name__ == "__main__":
    unittest.main()
