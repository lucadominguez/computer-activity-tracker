"""Isolated fixtures only. Never read or reset a user's activity database."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "activity.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE focus (id INTEGER PRIMARY KEY, title TEXT, app TEXT,
                    started_at REAL, ended_at REAL, key_count INTEGER);
                CREATE TABLE afk (id INTEGER PRIMARY KEY, state TEXT,
                    started_at REAL, ended_at REAL);
                INSERT INTO focus VALUES (1, 'Previous day', 'editor', 90, 120, 4);
                INSERT INTO focus VALUES (2, 'Résumé <script>', 'browser', 140, 180, 7);
                INSERT INTO focus VALUES (3, 'Tomorrow', 'editor', 210, 250, 0);
                INSERT INTO afk VALUES (1, 'active', 100, 130);
                INSERT INTO afk VALUES (2, 'afk', 180, 230);
            """)
        db.close()

    def test_existing_history_becomes_clipped_daily_overview(self):
        from activity_app.reporting import report

        before = self.path.read_bytes()
        data = report(self.path, 100, 200, limit=2)
        self.assertEqual(data["active_seconds"], 60)
        self.assertEqual(data["afk_seconds"], 20)
        self.assertEqual(data["key_count"], 11)
        self.assertEqual(data["event_count"], 3)
        self.assertEqual(data["apps"][0]["app"], "browser")
        self.assertEqual(data["apps"][0]["seconds"], 40)
        self.assertEqual(data["events"][0]["kind"], "afk")
        self.assertEqual(len(data["events"]), 2)
        self.assertTrue(data["has_more"])
        self.assertAlmostEqual(sum(b["active_seconds"] for b in data["bins"]), 60)
        self.assertEqual(before, self.path.read_bytes())
        self.assertIn("Résumé <script>", json.dumps(data, ensure_ascii=False))

    def test_full_csv_export_is_not_limited_to_the_visible_page(self):
        import csv
        import importlib.util
        import io

        self.assertIsNotNone(importlib.util.find_spec("activity_app.exports"), "Export pipeline is missing")
        from activity_app.exports import export_data

        with sqlite3.connect(self.path) as db:
            db.executemany(
                "INSERT INTO focus(title,app,started_at,ended_at,key_count) VALUES (?,?,?,?,?)",
                [('=HYPERLINK("evil")', "@app", 121, 122, 0)] * 510,
            )
        db.close()
        body = export_data(self.path, 100, 200, filetype="csv", query="HYPERLINK", limit=2)
        rows = list(csv.DictReader(io.StringIO(body.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 510)
        self.assertEqual(rows[0]["title"], '\'=HYPERLINK("evil")')
        self.assertEqual(rows[0]["app"], "'@app")
        payload = json.loads(export_data(self.path, 100, 200, filetype="json", query="HYPERLINK", limit=2))
        self.assertEqual(len(payload["events"]), 510)
        self.assertFalse(payload["has_more"])

    def test_literal_unicode_search_and_pagination(self):
        from activity_app.reporting import report

        self.assertEqual(report(self.path, 100, 200, query="RÉSUMÉ")["matching_count"], 1)
        self.assertEqual(report(self.path, 100, 200, query="%")["matching_count"], 0)
        self.assertEqual(report(self.path, 100, 200, query="' OR 1=1 --")["matching_count"], 0)
        self.assertEqual(report(self.path, 100, 200, kind="afk")["matching_count"], 1)
        self.assertEqual(len(report(self.path, 100, 200, offset=2, limit=2)["events"]), 1)
        for start, end in ((float("nan"), 200), (100, float("inf")), (200, 100), (0, 32 * 86400)):
            with self.assertRaises(ValueError):
                report(self.path, start, end)


if __name__ == "__main__":
    unittest.main()
