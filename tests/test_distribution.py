"""Static launcher contract, not a substitute for an on-device install test."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_shortcut_opens_visible_app_from_the_checkout_location(self):
        shortcut = (ROOT / "windows/create_shortcut.ps1").read_text()
        self.assertIn("activity_tracker.py", shortcut)
        self.assertIn("$PSScriptRoot", shortcut)
        self.assertNotIn("--forever", shortcut)
        self.assertTrue((ROOT / "install.cmd").is_file())
        self.assertTrue((ROOT / "launch.cmd").is_file())
        self.assertTrue((ROOT / "pyproject.toml").is_file())


if __name__ == "__main__":
    unittest.main()
