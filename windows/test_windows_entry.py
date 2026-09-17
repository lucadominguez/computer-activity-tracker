import os
import subprocess
import sys
import tempfile
import unittest


class WindowsEntryTests(unittest.TestCase):
    def test_self_test_uses_disposable_storage_not_the_requested_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(os.path.dirname(__file__), "windows_activity_tracker.py")
            result = subprocess.run(
                [sys.executable, script, "--self-test", "--data-dir", tmp],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("SELF-TEST PASS focus=2 afk=1 key_counts=2", result.stdout)
            self.assertFalse(os.path.exists(os.path.join(tmp, "activity.sqlite3")))


if __name__ == "__main__":
    unittest.main()
