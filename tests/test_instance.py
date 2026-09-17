import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from activity_app.instance import InstanceLock

ROOT = Path(__file__).resolve().parents[1]


class InstanceTests(unittest.TestCase):
    def test_contending_process_can_reopen_without_reading_locked_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.lock"
            lock = InstanceLock(path)
            probe = [
                sys.executable,
                "-c",
                "from pathlib import Path; import sys; "
                "from activity_app.instance import InstanceLock; "
                "lock=InstanceLock(Path(sys.argv[1])); "
                "print(lock.acquire()); lock.close()",
                str(path),
            ]
            try:
                self.assertTrue(lock.acquire())
                second = subprocess.run(probe, cwd=ROOT, capture_output=True, text=True, timeout=5)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(second.stdout.strip(), "False")
            finally:
                lock.close()
            third = subprocess.run(probe, cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertEqual(third.returncode, 0, third.stderr)
            self.assertEqual(third.stdout.strip(), "True")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
