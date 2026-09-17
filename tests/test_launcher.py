import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_second_launch_reuses_instance_and_quit_releases_it(self):
        help_result = subprocess.run(
            [sys.executable, "-m", "activity_app", "--help"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            command = [
                sys.executable,
                "-m",
                "activity_app",
                "--data-dir",
                tmp,
                "--no-browser",
                "--poll-interval",
                ".1",
            ]
            env = dict(os.environ)
            env.pop("DISPLAY", None)
            env.pop("WAYLAND_DISPLAY", None)
            process = subprocess.Popen(
                command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            runtime = Path(tmp) / "runtime.json"
            try:
                deadline = time.monotonic() + 8
                while not runtime.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(runtime.exists(), "Launcher did not publish its local runtime")
                info = json.loads(runtime.read_text())
                second = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=8)
                self.assertEqual(second.returncode, 0, second.stderr)
                # Windows venv launchers may supervise a child interpreter.
                # The advertised recorder PID must stay stable, not equal the shim PID.
                self.assertEqual(json.loads(runtime.read_text())["pid"], info["pid"])
                self.assertIn("existing local tracker instance", second.stdout)
                origin, token = info["launch_url"].split("/#")
                self.assertNotIn(token, second.stdout)
                request = Request(
                    origin + "/api/control",
                    data=b'{"action":"quit"}',
                    headers={
                        "Cookie": "tracker_session=" + token,
                        "X-Tracker-Action": "1",
                        "Content-Type": "application/json",
                        "Origin": origin,
                    },
                )
                with urlopen(request, timeout=5) as response:
                    self.assertEqual(json.load(response)["state"], "stopped")
                self.assertEqual(process.wait(timeout=8), 0)
                self.assertFalse(runtime.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=8)
                process.communicate(timeout=3)


if __name__ == "__main__":
    unittest.main()
