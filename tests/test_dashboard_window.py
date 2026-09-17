import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class DashboardWindowTests(unittest.TestCase):
    def test_windows_opens_app_window_not_a_normal_browser_tab(self):
        from activity_app.__main__ import open_dashboard

        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "Google/Chrome/Application/chrome.exe"
            binary.parent.mkdir(parents=True)
            binary.touch()
            with (
                patch("activity_app.__main__.sys.platform", "win32"),
                patch.dict("os.environ", {"ProgramFiles": tmp}),
                patch("subprocess.Popen") as launch,
            ):
                open_dashboard("http://127.0.0.1:43127/#test-only")
                self.assertEqual(
                    launch.call_args.args[0], [str(binary), "--app=http://127.0.0.1:43127/#test-only"]
                )
