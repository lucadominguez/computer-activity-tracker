"""Passage adaptation: real encrypted persistence, retrieval and receipts."""

import tempfile
import unittest
from pathlib import Path


class MemoryStoreTests(unittest.TestCase):
    def test_sessions_split_on_app_change_and_long_gap(self):
        from activity_app.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(tmp)
            self.assertTrue(hasattr(store, "sessions"), "Session grouping is missing")
            for ts, app in [(100, "Notes"), (120, "Notes"), (140, "Browser"), (500, "Browser")]:
                store.add({"ts": ts, "title": "Test", "app": app, "text": "hello"}, b"image")
            result = store.sessions(start=0, end=1000)
            self.assertEqual([s["moments"] for s in result["items"]], [1, 1, 2])
            self.assertEqual(result["total"], 3)
            store.close()

    def test_encrypted_moment_survives_restart_and_handoff_is_receipted(self):
        import importlib.util

        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.memory_store"),
            "The encrypted screenshot/OCR store is missing",
        )
        from activity_app.memory_store import MemoryStore

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = MemoryStore(root)
            item = store.add(
                {
                    "title": "A private budget",
                    "app": "Notepad",
                    "text": "ultraviolet otter project",
                    "url": "",
                    "ts": 1000,
                },
                b"actual-image-bytes",
            )
            self.assertEqual(store.search(query="otter")["total"], 1)
            self.assertEqual(store.image(item["id"]), b"actual-image-bytes")
            handoff = store.handoff([item["id"]])
            self.assertIn("ultraviolet otter", handoff["text"])
            self.assertEqual(store.receipts()[0]["id"], handoff["receipt"]["id"])
            self.assertEqual(store.receipts()[0]["sources"], 1)
            self.assertEqual(store.receipts()[0]["scope"][0]["title"], "A private budget")
            self.assertIn("ultraviolet otter", store.receipts()[0]["scope"][0]["excerpt"])
            store.close()
            for file in root.rglob("*"):
                if file.is_file():
                    data = file.read_bytes()
                    self.assertNotIn(b"ultraviolet otter", data, file)
                    self.assertNotIn(b"actual-image-bytes", data, file)
                    self.assertNotIn(b"A private budget", data, file)
            reopened = MemoryStore(root)
            self.assertEqual(reopened.search(query="otter")["total"], 1)
            self.assertEqual(reopened.image(item["id"]), b"actual-image-bytes")
            reopened.delete(item["id"])
            scope = reopened.receipts()[0]["scope"][0]
            self.assertTrue(scope["deleted"])
            self.assertEqual(scope["excerpt"], "")
            reopened.close()


if __name__ == "__main__":
    unittest.main()
