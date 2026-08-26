#!/usr/bin/env python3
import os
import sqlite3
import tempfile
import unittest

from activity_core import ActivityEngine, ActivityStore


class ActivityEngineTests(unittest.TestCase):
    def test_focus_switch_persists_two_coalesced_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "activity.sqlite3")
            store = ActivityStore(path)
            engine = ActivityEngine(store, idle_timeout=180)

            engine.sample(100.0, ("Document A", "notepad.exe"), idle_seconds=0)
            engine.sample(102.0, ("Document A", "notepad.exe"), idle_seconds=0)
            engine.sample(105.0, ("Browser B", "msedge.exe"), idle_seconds=0)
            engine.close(109.0)

            rows = store.conn.execute(
                "SELECT title, app, started_at, ended_at FROM focus "
                "ORDER BY started_at"
            ).fetchall()
            store.close()

            self.assertEqual(
                [
                    ("Document A", "notepad.exe", 100.0, 105.0),
                    ("Browser B", "msedge.exe", 105.0, 109.0),
                ],
                rows,
            )

    def test_afk_closes_focus_and_suppresses_windows_until_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "activity.sqlite3")
            store = ActivityStore(path)
            engine = ActivityEngine(store, idle_timeout=180)

            engine.sample(100.0, ("Document A", "notepad.exe"), idle_seconds=0)
            engine.sample(105.0, ("Document A", "notepad.exe"), idle_seconds=181)
            engine.sample(110.0, ("Browser B", "msedge.exe"), idle_seconds=200)
            engine.sample(115.0, ("Browser B", "msedge.exe"), idle_seconds=0)
            engine.close(120.0)

            focus = store.conn.execute(
                "SELECT title, started_at, ended_at FROM focus ORDER BY started_at"
            ).fetchall()
            afk = store.conn.execute(
                "SELECT state, started_at, ended_at FROM afk ORDER BY started_at"
            ).fetchall()
            store.close()

            self.assertEqual(
                [("Document A", 100.0, 105.0), ("Browser B", 115.0, 120.0)],
                focus,
            )
            self.assertEqual([("afk", 105.0, 115.0)], afk)

    def test_key_events_count_without_storing_key_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "activity.sqlite3")
            store = ActivityStore(path)
            engine = ActivityEngine(store, idle_timeout=180)

            engine.sample(100.0, ("Document A", "notepad.exe"), idle_seconds=0)
            engine.record_key()
            engine.record_key()
            engine.close(104.0)

            row = store.conn.execute(
                "SELECT key_count FROM focus"
            ).fetchone()
            columns = {
                item[1] for item in store.conn.execute("PRAGMA table_info(focus)")
            }
            store.close()

            self.assertEqual((2,), row)
            self.assertNotIn("key_value", columns)
            self.assertNotIn("key", columns)

    def test_repeated_samples_checkpoint_the_open_focus_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "activity.sqlite3")
            store = ActivityStore(path)
            engine = ActivityEngine(store, idle_timeout=180)

            engine.sample(100.0, ("Document A", "notepad.exe"), idle_seconds=0)
            engine.sample(102.0, ("Document A", "notepad.exe"), idle_seconds=0)

            row = store.conn.execute(
                "SELECT title, started_at, ended_at FROM focus"
            ).fetchone()
            store.close()

            self.assertEqual(("Document A", 100.0, 102.0), row)


if __name__ == "__main__":
    unittest.main()
