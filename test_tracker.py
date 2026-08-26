#!/usr/bin/env python3
import os
import sqlite3
import tempfile
import unittest

import computer_activity_tracker as tracker


class TrackerStorageTests(unittest.TestCase):
    def test_schema_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db = tracker.DB
            tracker.DB = os.path.join(tmp, "activity.sqlite3")
            try:
                first = tracker.Tracker()
                first.conn.close()
                second = tracker.Tracker()
                second.conn.close()
                with sqlite3.connect(tracker.DB) as conn:
                    versions = conn.execute(
                        "SELECT v FROM schema_version ORDER BY rowid"
                    ).fetchall()
                self.assertEqual([(1,)], versions)
            finally:
                tracker.DB = original_db

    def test_default_idle_timeout_is_three_minutes(self):
        self.assertEqual(180.0, tracker.IDLE_TIMEOUT)

    def test_input_events_increment_the_current_focus_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_db = tracker.DB
            tracker.DB = os.path.join(tmp, "activity.sqlite3")
            instance = None
            try:
                instance = tracker.Tracker()
                instance.on_focus("Editor", "editor-app")
                instance.on_event()
                instance.on_event()
                instance._close_focus(instance._focus[2] + 3.0)
                key_count = instance.conn.execute(
                    "SELECT key_count FROM focus"
                ).fetchone()[0]
                self.assertEqual(2, key_count)
            finally:
                if instance is not None:
                    instance.conn.close()
                tracker.DB = original_db


if __name__ == "__main__":
    unittest.main()
