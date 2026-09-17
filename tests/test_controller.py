import importlib.util
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


class InputSource:
    def __init__(self):
        self.stopped = False

    def start(self):
        pass

    def sample(self):
        return ("Test editor", "editor"), 0.0, 1

    def stop(self):
        self.stopped = True


class ControllerTests(unittest.TestCase):
    def test_pause_still_detaches_when_native_sampling_fails(self):
        from activity_app.controller import Controller

        class BrokenSource(InputSource):
            fail = False

            def sample(self):
                if self.fail:
                    raise RuntimeError("Native desktop became unavailable")
                return super().sample()

        with tempfile.TemporaryDirectory() as tmp:
            source = BrokenSource()
            controller = Controller(Path(tmp), backend_factory=lambda: source, poll_interval=1)
            controller.start()
            try:
                source.fail = True
                self.assertEqual(controller.command("pause")["state"], "paused")
                self.assertTrue(source.stopped)
            finally:
                controller.close()

    def test_pause_detaches_capture_and_survives_restart(self):
        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.controller"), "Recording controller is missing"
        )
        from activity_app.controller import Controller

        with tempfile.TemporaryDirectory() as tmp:
            sources = []

            def factory():
                source = InputSource()
                sources.append(source)
                return source

            controller = Controller(Path(tmp), backend_factory=factory, poll_interval=0.03)
            controller.start()
            try:
                self.assertEqual(controller.status()["state"], "recording")
                controller.command("pause")
                self.assertTrue(sources[0].stopped)
                self.assertEqual(controller.status()["state"], "paused")
                with sqlite3.connect(Path(tmp) / "activity.sqlite3") as db:
                    before = db.execute("SELECT * FROM focus").fetchall()
                    time.sleep(0.1)
                    self.assertEqual(before, db.execute("SELECT * FROM focus").fetchall())
                db.close()
            finally:
                controller.close()
            restarted = Controller(Path(tmp), backend_factory=factory, poll_interval=0.03)
            restarted.start()
            try:
                self.assertEqual(restarted.status()["state"], "paused")
                self.assertEqual(len(sources), 1)
                self.assertEqual(restarted.command("resume")["state"], "recording")
                self.assertEqual(len(sources), 2)
                with self.assertRaises(ValueError):
                    restarted.command("delete-everything")
            finally:
                restarted.close()
            self.assertTrue(all(source.stopped for source in sources))


if __name__ == "__main__":
    unittest.main()
