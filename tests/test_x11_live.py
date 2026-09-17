"""Run only on an isolated X server: CCA_TEST_X11=1 xvfb-run -a ..."""

import os
import subprocess
import time
import unittest


@unittest.skipUnless(os.environ.get("CCA_TEST_X11") == "1", "requires an isolated X11 test session")
class X11LiveTests(unittest.TestCase):
    def test_native_window_idle_and_aggregate_keys(self):
        from activity_app.backends import X11Backend

        wm = subprocess.Popen(["openbox"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        term = subprocess.Popen(
            ["xterm", "-T", "Activity Tracker X11 verification"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        backend = X11Backend()
        try:
            window = None
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                found = subprocess.run(
                    ["xdotool", "search", "--name", "Activity Tracker X11 verification"],
                    capture_output=True,
                    text=True,
                )
                if found.returncode == 0 and found.stdout.strip():
                    window = found.stdout.splitlines()[0]
                    activated = subprocess.run(
                        ["xdotool", "windowactivate", "--sync", window], capture_output=True
                    )
                    if activated.returncode == 0:
                        break
                time.sleep(0.1)
            self.assertIsNotNone(window, "Test window never appeared")
            backend.start()
            subprocess.run(["xdotool", "key", "--clearmodifiers", "a", "b", "c"], check=True)
            count = 0
            for _ in range(20):
                context, idle, keys = backend.sample()
                count += keys
                if count >= 3:
                    break
                time.sleep(0.05)
            self.assertIn("Activity Tracker X11 verification", context[0])
            self.assertGreaterEqual(count, 3)
            self.assertLess(idle, 2)
            time.sleep(0.2)
            self.assertGreater(backend.sample()[1], idle)
        finally:
            backend.stop()
            for process in (term, wm):
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
