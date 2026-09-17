"""Infer context through the real UI, against a local OpenAI-compatible stub."""

import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from test_controller import InputSource
from test_inference import CONTEXT, Stub, answer

from activity_app.controller import Controller
from activity_app.web import AppServer


@unittest.skipUnless(os.environ.get("CCA_TEST_BROWSER") == "1", "requires Playwright")
class InferBrowserTests(unittest.TestCase):
    def test_ui_inference_off_state_result_and_receipt(self):
        from playwright.sync_api import expect, sync_playwright

        from activity_app.screen_source import ScreenSource

        with tempfile.TemporaryDirectory() as tmp:
            controller = Controller(tmp, backend_factory=InputSource, poll_interval=0.02)
            controller.start()
            server = AppServer(controller)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            stub = Stub([answer])
            try:
                image = Image.new("RGB", (1200, 700), "#f7f7fa")
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
                draw.text((45, 50), "LOCAL OCR VERIFICATION", fill="#252539", font=font)
                draw.text((45, 140), "Orchid river research notes", fill="#252539", font=font)
                draw.text((45, 230), "Sensor order quotes from two suppliers.", fill="#252539", font=font)
                source = ScreenSource()
                text = source.text(image)
                source.close()
                self.assertIn("Orchid", text)
                out = io.BytesIO()
                image.save(out, "WEBP")
                now = time.time()
                ids = [
                    controller.memory.store.add(
                        {
                            "title": "Local OCR verification",
                            "app": "Verification Notes",
                            "text": text,
                            "ts": now - index * 30,
                        },
                        out.getvalue(),
                    )["id"]
                    for index in range(3)
                ]
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    page = browser.new_page(viewport={"width": 1292, "height": 872})
                    errors, external = [], []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    page.on(
                        "request",
                        lambda r: external.append(r.url) if not r.url.startswith(server.origin) else None,
                    )
                    page.goto(server.launch_url)
                    expect(page.locator(".moment-card")).to_have_count(3)

                    # Off by default: the dialog says so, and nothing is sent.
                    page.get_by_role("button", name="Infer context", exact=True).click()
                    expect(page.locator("#infer-body")).to_contain_text("Inference is off")
                    expect(page.get_by_role("button", name="Open Settings")).to_be_visible()
                    self.assertEqual(stub.calls, [])
                    page.get_by_role("button", name="Close inferred context", exact=True).click()

                    # Enable through the real settings form.
                    page.locator("#settings-open").click()
                    page.locator("#settings-dialog").wait_for(state="visible")
                    dialog_box = page.locator("#settings-dialog").bounding_box()
                    self.assertLessEqual(
                        dialog_box["y"] + dialog_box["height"],
                        872 + 1,
                        "the settings dialog must fit the viewport, not push its actions off-screen",
                    )
                    save = page.locator("#settings-form button[type=submit]")
                    save.scroll_into_view_if_needed()
                    save_box = save.bounding_box()
                    self.assertLessEqual(
                        save_box["y"] + save_box["height"], 872 + 1, "Save settings must be reachable"
                    )
                    page.locator("#infer-enabled").check()
                    page.locator("#infer-url").fill(stub.url)
                    page.locator("#infer-model").fill("stub-model")
                    page.locator("#infer-key").fill("sk-browser-secret")
                    page.get_by_role("button", name="Save settings", exact=True).click()
                    expect(page.locator("#settings-dialog")).to_be_hidden()
                    page.locator("#settings-open").click()
                    page.locator("#infer-enabled").uncheck()
                    page.locator("#infer-enabled").check()
                    expect(page.locator("#infer-key-state")).to_contain_text("A key is stored")
                    page.get_by_role("button", name="Close settings", exact=True).click()

                    page.get_by_role("button", name="Infer context", exact=True).click()
                    body = page.locator("#infer-body")
                    expect(body).to_contain_text(CONTEXT["summary"])
                    expect(body).to_contain_text(CONTEXT["activity"])
                    expect(body.locator(".confidence")).to_have_text("medium confidence")
                    expect(body).to_contain_text("Read from 3 saved moments")
                    expect(page.locator("#infer-status")).to_contain_text("Receipt committed in Access History")
                    self.assertTrue(page.locator("#infer-text").input_value().startswith("Summary: "))
                    self.assertEqual(len(stub.calls), 1)
                    sent = stub.calls[0]
                    self.assertEqual(sent["path"], "/v1/chat/completions")
                    self.assertEqual(sent["headers"]["Authorization"], "Bearer sk-browser-secret")
                    self.assertIn("Orchid river", str(sent["body"]))
                    self.assertNotIn("sk-browser-secret", str(sent["body"]))
                    if os.environ.get("CCA_AXE_JS"):
                        page.evaluate(Path(os.environ["CCA_AXE_JS"]).read_text())
                        violations = page.evaluate(
                            "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations.map(x=>({id:x.id,nodes:x.nodes.map(n=>n.target)}))"
                        )
                        self.assertEqual(violations, [], str(violations))
                    evidence = Path(os.environ.get("CCA_EVIDENCE_DIR", tmp))
                    evidence.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(evidence / "inferred-context.png"))
                    for width in (320, 768, 1292):
                        page.set_viewport_size({"width": width, "height": 872})
                        self.assertFalse(
                            page.evaluate("document.documentElement.scrollWidth>innerWidth"), str(width)
                        )
                    page.get_by_role("button", name="Close inferred context", exact=True).click()

                    # The receipt names the endpoint and keeps the inferred text.
                    page.get_by_role("link", name="Access History", exact=True).click()
                    receipt = page.locator("#access-list .receipt").first
                    expect(receipt).to_contain_text("Context inference")
                    expect(receipt).to_contain_text("Local model call")
                    expect(receipt).to_contain_text(
                        "127.0.0.1:%d" % stub.server.server_port
                    )
                    expect(receipt.locator(".receipt-preview")).to_contain_text(CONTEXT["summary"])
                    expect(receipt).to_contain_text("Copy inferred context")
                    page.get_by_role("link", name="Recall", exact=True).click()
                    expect(page.locator("#detail-text")).to_contain_text("Orchid")
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    self.assertTrue(
                        set(controller.memory.store.receipts()[0]["moment_ids"]).issubset(set(ids))
                    )
                    self.assertNotIn(
                        "sk-browser-secret",
                        str(controller.status()) + str(controller.memory.status()),
                    )
                    browser.close()
            finally:
                stub.close()
                server.shutdown()
                server.server_close()
                worker.join(5)
                controller.close()


if __name__ == "__main__":
    unittest.main()