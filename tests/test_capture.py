import sqlite3
import tempfile
import unittest
from pathlib import Path


class CaptureTests(unittest.TestCase):
    def test_checkpoint_pause_resume_and_sleep_do_not_invent_time(self):
        from activity_app.capture import CaptureSession

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.sqlite3"
            session = CaptureSession(path, idle_timeout=3, max_gap=5)
            session.sample(100, ("Editor", "editor"), 0, 2)
            session.sample(102, ("Editor", "editor"), 0, 1)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT ended_at,key_count FROM focus").fetchone(), (102, 3))
            db.close()
            session.sample(104, ("Editor", "editor"), 4, 0)
            session.sample(106, ("Editor", "editor"), 6, 0)
            session.pause(107)
            session.sample(110, ("DO NOT RECORD", "secret"), 0, 99)
            session.resume()
            session.sample(112, ("Browser", "browser"), 0, 2)
            session.sample(114, ("Browser", "browser"), 0, 0)
            session.sample(999, ("After sleep", "browser"), 0, 0)
            session.close(1000)
            with sqlite3.connect(path) as db:
                rows = db.execute("SELECT title,started_at,ended_at,key_count FROM focus").fetchall()
                self.assertEqual([r[0] for r in rows], ["Editor", "Browser", "After sleep"])
                self.assertEqual(rows[1][1:3], (112, 114))
                self.assertEqual(rows[2][1:3], (999, 1000))
                self.assertEqual(db.execute("SELECT started_at,ended_at FROM afk").fetchone(), (103, 107))
            db.close()


if __name__ == "__main__":
    unittest.main()
