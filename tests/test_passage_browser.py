"""Rendered Passage layout and controls, with an isolated real screenshot/OCR store."""

import io
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from test_controller import InputSource

from activity_app.controller import Controller
from activity_app.web import AppServer


@unittest.skipUnless(os.environ.get("CCA_TEST_BROWSER") == "1", "requires Playwright")
class PassageBrowserTests(unittest.TestCase):
    def test_reference_screens_retrieve_images_ocr_and_real_receipts(self):
        from playwright.sync_api import expect, sync_playwright

        from activity_app.screen_source import ScreenSource

        with tempfile.TemporaryDirectory() as tmp:
            controller = Controller(tmp, backend_factory=InputSource)
            controller.start()
            server = AppServer(controller)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
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
                    expect(page.get_by_role("link", name="Recall", exact=True)).to_be_visible()
                    expect(page.get_by_text("No saved moments yet", exact=True)).to_be_visible()
                    # Clearly labelled QA source, processed by the actual local OCR adapter.
                    image = Image.new("RGB", (1200, 700), "#f7f7fa")
                    draw = ImageDraw.Draw(image)
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 32)
                    draw.text((45, 50), "LOCAL OCR VERIFICATION", fill="#252539", font=font)
                    draw.text((45, 140), "Orchid river research notes", fill="#252539", font=font)
                    draw.text(
                        (45, 230), "Screen capture, retrieval and privacy checks.", fill="#252539", font=font
                    )
                    source = ScreenSource()
                    text = source.text(image)
                    source.close()
                    self.assertIn("Orchid", text)
                    out = io.BytesIO()
                    image.save(out, "WEBP")
                    now = time.time()
                    for i in range(3):
                        controller.memory.store.add(
                            {
                                "title": "Local OCR verification",
                                "app": "Verification Notes",
                                "text": text,
                                "ts": now - i * 30,
                            },
                            out.getvalue(),
                        )
                    page.reload()
                    page.get_by_label("Search saved words").fill("orchid")
                    expect(page.locator(".moment-card")).to_have_count(3)
                    expect(page.locator("#detail-text")).to_contain_text("Orchid")
                    page.get_by_role("button", name="Hand Off Context", exact=True).click()
                    expect(page.get_by_role("dialog")).to_be_visible()
                    expect(page.locator("#handoff-text")).to_have_value(re.compile("Orchid"))
                    page.get_by_role("button", name="Close handoff", exact=True).click()
                    evidence = Path(os.environ.get("CCA_EVIDENCE_DIR", tmp))
                    evidence.mkdir(parents=True, exist_ok=True)
                    for view in ("Recall", "Timeline", "Sessions", "Access History"):
                        page.get_by_role("link", name=view, exact=True).click()
                        if view == "Access History":
                            expect(page.locator("#access-list .receipt-preview").first).to_contain_text(
                                "Orchid"
                            )
                            page.locator("#access-list summary").first.click()
                            page.get_by_role("button", name="Open saved moment", exact=True).first.click()
                            expect(page.locator("#moment-detail")).to_contain_text("Orchid")
                            page.get_by_role("link", name="Access History", exact=True).click()
                        if view == "Timeline":
                            slider = page.get_by_label("Moment in timeline")
                            expect(slider).to_have_attribute("max", "2")
                            slider.focus()
                            slider.press("Home")
                            slider.press("ArrowRight")
                            expect(slider).to_have_value("1")
                            self.assertAlmostEqual(
                                slider.bounding_box()["y"],
                                page.locator("#activity-track").bounding_box()["y"],
                                delta=1,
                            )
                            self.assertGreaterEqual(
                                page.locator(".track-labels").bounding_box()["y"],
                                slider.bounding_box()["y"] + slider.bounding_box()["height"] + 8,
                                "Keyboard focus ring must not overlap timestamp labels",
                            )
                            expect(page.locator("#timeline-preview")).to_be_visible()
                        if view == "Access History":
                            expect(page.get_by_text("Context handoff", exact=True)).to_be_visible()
                        page.screenshot(path=str(evidence / (view.lower().replace(" ", "-") + ".png")))
                    page.get_by_role("link", name="Recall", exact=True).click()
                    for width in (320, 768, 1024, 1292, 1440):
                        page.set_viewport_size({"width": width, "height": 872})
                        for view in ("Recall", "Timeline", "Sessions", "Access History"):
                            page.get_by_role("link", name=view, exact=True).click()
                            self.assertFalse(
                                page.evaluate("document.documentElement.scrollWidth>innerWidth"),
                                str(width)
                                + str(
                                    page.evaluate(
                                        "[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().width && (e.getBoundingClientRect().right>innerWidth+1||e.getBoundingClientRect().left < -1)).slice(0,12).map(e=>[e.tagName,e.className,e.getBoundingClientRect().left,e.getBoundingClientRect().width])"
                                    )
                                ),
                            )
                            if os.environ.get("CCA_AXE_JS"):
                                page.evaluate(Path(os.environ["CCA_AXE_JS"]).read_text())
                                violations = page.evaluate(
                                    "async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations.map(x=>({id:x.id,nodes:x.nodes.map(n=>n.target)}))"
                                )
                                self.assertEqual(violations, [], str(width))
                            page.screenshot(
                                path=str(evidence / f"{view.lower().replace(chr(32), chr(45))}-{width}.png"),
                                full_page=True,
                            )
                    page.get_by_role("link", name="Recall", exact=True).click()
                    page.get_by_role("button", name="Delete moment", exact=True).click()
                    expect(page.locator("#confirm-dialog")).to_be_visible()
                    page.locator("#confirm-action").click()
                    expect(page.locator("#moment-list .moment-card")).to_have_count(2)
                    self.assertEqual(controller.memory.store.search()["total"], 2)
                    self.assertEqual(errors, [])
                    self.assertEqual(external, [])
                    browser.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(5)
                controller.close()
