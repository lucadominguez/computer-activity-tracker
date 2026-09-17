"""Real X11-to-SQLite-to-browser acceptance. Uses a temporary database only."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("CCA_TEST_BROWSER") == "1", "requires isolated X11 and Playwright")
class BrowserAcceptance(unittest.TestCase):
    def test_visible_app_real_recording_controls_history_exports_and_layout(self):
        self.assertTrue(
            (ROOT / "activity_app/static/index.html").exists(), "Visible dashboard has not been built"
        )
        from playwright.sync_api import expect, sync_playwright

        with tempfile.TemporaryDirectory(prefix="tracker-browser-") as tmp:
            data = Path(tmp)
            wm = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            term = subprocess.Popen(
                ["xterm", "-T", "Tracker browser acceptance"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            app = None
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    found = subprocess.run(
                        ["xdotool", "search", "--name", "Tracker browser acceptance"],
                        text=True,
                        capture_output=True,
                    )
                    if found.returncode == 0:
                        activated = subprocess.run(
                            ["xdotool", "windowactivate", "--sync", found.stdout.splitlines()[0]],
                            capture_output=True,
                        )
                        if activated.returncode == 0:
                            break
                    time.sleep(0.1)
                app = subprocess.Popen(
                    [
                        os.environ.get("CCA_TEST_APP_PYTHON", sys.executable),
                        "-m",
                        "activity_app",
                        "--no-browser",
                        "--data-dir",
                        tmp,
                        "--poll-interval",
                        ".1",
                        "--idle-timeout",
                        "2",
                    ],
                    cwd=tmp if os.environ.get("CCA_TEST_APP_PYTHON") else ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                runtime = data / "runtime.json"
                deadline = time.monotonic() + 10
                while not runtime.exists() and app.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(runtime.exists(), "Application did not start")
                launch = json.loads(runtime.read_text())["launch_url"]
                subprocess.run(["xdotool", "key", "--clearmodifiers", "a", "b", "c"], check=True)
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1000},
                        device_scale_factor=1,
                        timezone_id="America/New_York",
                    )
                    errors = []
                    console_errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on(
                        "console",
                        lambda message: (
                            console_errors.append(message.text) if message.type == "error" else None
                        ),
                    )
                    external = []
                    page.on(
                        "request",
                        lambda req: (
                            external.append(req.url)
                            if not req.url.startswith(("http://127.0.0.1:", "blob:", "data:"))
                            else None
                        ),
                    )
                    page.goto(launch.replace("/#", "/activity#"))
                    page.wait_for_function(
                        "typeof bounds === 'function' && document.querySelector('#day').value"
                    )
                    day_lengths = page.evaluate(
                        "() => {const day=document.querySelector('#day'); const original=day.value; const lengths=['2026-03-08','2026-11-01'].map(value => {day.value=value; const range=bounds(); return range.end-range.start;}); day.value=original; return lengths;}"
                    )
                    self.assertEqual(day_lengths, [23 * 3600, 25 * 3600])
                    expect(page.get_by_role("heading", name="Day overview")).to_be_visible()
                    expect(page.locator("#recording-state")).to_have_text("Recording")
                    expect(page.locator("#event-total")).not_to_have_text("0", timeout=10000)
                    page.get_by_role("link", name="Timeline", exact=True).click()
                    expect(page.locator("#timeline-body")).to_contain_text(
                        "Tracker browser acceptance", timeout=10000
                    )
                    page.get_by_label("Search window titles or apps").fill("no-such-app-93482")
                    expect(page.locator("#timeline-empty")).to_be_visible()
                    page.get_by_label("Search window titles or apps").fill("Tracker browser acceptance")
                    expect(page.locator("#timeline-body")).to_contain_text("Tracker browser acceptance")
                    with page.expect_download() as download_info:
                        page.get_by_role("button", name="Export", exact=True).click()
                    download = download_info.value
                    self.assertTrue(download.suggested_filename.endswith(".csv"))
                    self.assertIn(
                        "Tracker browser acceptance", Path(download.path()).read_text(encoding="utf-8-sig")
                    )
                    page.get_by_role("button", name="Pause recording", exact=True).click()
                    expect(page.locator("#recording-state")).to_have_text("Paused")
                    page.get_by_role("button", name="Resume recording", exact=True).click()
                    expect(page.locator("#recording-state")).to_have_text("Recording")
                    page.get_by_role("link", name="Overview", exact=True).click()
                    page.get_by_role("button", name="Previous day", exact=True).click()
                    expect(page.locator("#overview-empty")).to_be_visible()
                    expect(page.locator("#chart-caption")).to_contain_text("Tallest interval: 0s")
                    page.get_by_role("button", name="Today", exact=True).click()
                    expect(page.locator("#overview-empty")).to_be_hidden()
                    evidence = Path(os.environ.get("CCA_EVIDENCE_DIR", tmp))
                    evidence.mkdir(parents=True, exist_ok=True)
                    for width in (320, 768, 1024, 1440):
                        page.set_viewport_size({"width": width, "height": 1000})
                        self.assertFalse(
                            page.evaluate("document.documentElement.scrollWidth > innerWidth"),
                            f"Horizontal page overflow at {width}px",
                        )
                        nav_sizes = page.locator("nav a").evaluate_all(
                            "(items) => items.map(item => item.getBoundingClientRect().height)"
                        )
                        self.assertEqual(
                            len(set(nav_sizes)),
                            1,
                            f"Navigation items wrap unevenly at {width}px: {nav_sizes}",
                        )
                        text_lines = page.locator("nav a").evaluate_all(
                            "items => items.map(link => {const text=[...link.childNodes].find(n => n.nodeType === 3 && n.textContent.trim()); const range=document.createRange(); range.selectNode(text); return range.getClientRects().length;})"
                        )
                        self.assertTrue(
                            all(n == 1 for n in text_lines),
                            f"Navigation label wrapping at {width}px: {text_lines}",
                        )
                        if os.environ.get("CCA_AXE_JS"):
                            page.evaluate(Path(os.environ["CCA_AXE_JS"]).read_text(encoding="utf-8"))
                            violations = page.evaluate(
                                "async () => (await axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa']}})).violations.map(v => ({id:v.id, impact:v.impact, nodes:v.nodes.map(n => n.target)}))"
                            )
                            self.assertEqual(violations, [], f"Accessibility violations at {width}px")
                        page.screenshot(path=str(evidence / f"dashboard-{width}.png"), full_page=True)
                    page.get_by_role("link", name="Overview", exact=True).focus()
                    page.keyboard.press("/")
                    expect(page.get_by_label("Search window titles or apps")).to_be_focused()
                    # Pagination/XSS fixtures are added only AFTER real-capture screenshots.
                    page.get_by_role("button", name="Pause recording", exact=True).click()
                    expect(page.locator("#recording-state")).to_have_text("Paused")
                    import sqlite3

                    epoch = page.evaluate("bounds().start") + 1
                    with sqlite3.connect(data / "activity.sqlite3") as db:
                        db.executemany(
                            "INSERT INTO focus(title,app,started_at,ended_at,key_count) VALUES (?,?,?,?,?)",
                            [
                                (f"QA fixture {i}", "Test fixture app", epoch, epoch + 0.1, 0)
                                for i in range(510)
                            ],
                        )
                        unsafe = 'QA fixture unsafe <img src=x onerror="window.__titleExecuted=1">'
                        db.execute(
                            "INSERT INTO focus(title,app,started_at,ended_at,key_count) VALUES (?,?,?,?,?)",
                            (unsafe, "Test fixture app", epoch + 1, epoch + 2, 0),
                        )
                    db.close()
                    page.get_by_label("Search window titles or apps").fill("QA fixture")
                    expect(page.locator("#page-range")).to_have_text("1 to 100 of 511")
                    page.get_by_role("button", name="Next", exact=True).click()
                    expect(page.locator("#page-range")).to_have_text("101 to 200 of 511")
                    page.get_by_label("Search window titles or apps").fill("QA fixture unsafe")
                    expect(page.locator("#timeline-body")).to_contain_text(unsafe)
                    self.assertEqual(page.locator("#timeline-body img").count(), 0)
                    self.assertIsNone(page.evaluate("window.__titleExecuted"))
                    page.get_by_label("Export format").select_option("json")
                    with page.expect_download() as json_download:
                        page.get_by_role("button", name="Export", exact=True).click()
                    payload = json.loads(Path(json_download.value.path()).read_text())
                    self.assertEqual(payload["events"][0]["title"], unsafe)
                    self.assertEqual(len(payload["events"]), 1)
                    if os.environ.get("CCA_AXE_JS"):
                        self.assertEqual(
                            page.evaluate("async () => (await axe.run()).violations.map(v => v.id)"), []
                        )
                    page.get_by_role("link", name="Privacy & data", exact=True).click()
                    expect(page.locator("#database-path")).to_contain_text(tmp)
                    page.get_by_role("button", name="Quit tracker", exact=True).click()
                    expect(page.get_by_role("dialog")).to_be_visible()
                    page.get_by_role("button", name="Stop and quit", exact=True).click()
                    expect(page.locator("#recording-state")).to_have_text("Stopped")
                    self.assertEqual(app.wait(timeout=10), 0)
                    self.assertFalse(runtime.exists())
                    self.assertEqual(errors, [])
                    self.assertEqual(console_errors, [])
                    self.assertEqual(external, [])
                    browser.close()
            finally:
                for process in (app, term, wm):
                    if process is not None:
                        if process.poll() is None:
                            process.terminate()
                        process.wait(timeout=10)
                if app is not None:
                    stdout, stderr = app.communicate(timeout=3)
                    if stderr:
                        print("APP STDERR:", stderr)


if __name__ == "__main__":
    unittest.main()
