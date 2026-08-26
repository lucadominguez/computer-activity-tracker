#!/usr/bin/env python3
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class WindowsEntryTests(unittest.TestCase):
    def test_self_test_exercises_the_full_storage_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(os.path.dirname(__file__), "windows_activity_tracker.py")
            result = subprocess.run(
                [sys.executable, script, "--self-test", "--data-dir", tmp],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("SELF-TEST PASS", result.stdout)
            connection = sqlite3.connect(os.path.join(tmp, "activity.sqlite3"))
            try:
                focus = connection.execute(
                    "SELECT title, app, key_count FROM focus ORDER BY started_at"
                ).fetchall()
                afk = connection.execute(
                    "SELECT state FROM afk ORDER BY started_at"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(
                [("SelfTest Editor", "notepad.exe", 2),
                 ("SelfTest Browser", "msedge.exe", 0)],
                focus,
            )
            self.assertEqual([("afk",)], afk)


if __name__ == "__main__":
    unittest.main()
