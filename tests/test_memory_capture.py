import importlib.util
import tempfile
import unittest

from PIL import Image


class MemoryCaptureTests(unittest.TestCase):
    def test_context_turning_private_during_ocr_drops_the_frame(self):
        from activity_app.memory_capture import MemoryRecorder

        class Desktop:
            private = False

            def context(self):
                return {"title": "Notes", "app": "Notepad", "private": self.private}

            def image(self, context):
                return Image.new("RGB", (640, 480), "white")

            def text(self, image):
                self.private = True
                return "must not persist"

        with tempfile.TemporaryDirectory() as tmp:
            recorder = MemoryRecorder(tmp, lambda: True, source_factory=Desktop)
            try:
                recorder.configure({"enabled": True})
                recorder.capture_once()
                self.assertEqual(recorder.store.search()["total"], 0)
            finally:
                recorder.close()

    def test_real_image_path_change_detection_and_privacy_controls(self):
        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.memory_capture"),
            "Screenshot/OCR capture with privacy controls is missing",
        )
        from activity_app.memory_capture import MemoryRecorder

        class Desktop:
            title = "Verification notes"
            color = "white"
            captures = 0

            def context(self):
                return {"title": self.title, "app": "Notepad", "idle": 0, "private": False}

            def image(self, context):
                self.captures += 1
                return Image.new("RGB", (640, 480), self.color)

            def text(self, image):
                return "orchid river verification phrase"

        with tempfile.TemporaryDirectory() as tmp:
            desktop = Desktop()
            recorder = MemoryRecorder(tmp, lambda: True, source_factory=lambda: desktop)
            recorder.capture_once()
            self.assertEqual(desktop.captures, 0, "Screenshot capture must require opt-in")
            recorder.configure({"enabled": True})
            recorder.capture_once()
            recorder.capture_once()
            self.assertEqual(recorder.store.search(query="orchid")["total"], 1)
            desktop.color = "blue"
            recorder.capture_once()
            self.assertEqual(recorder.store.search()["total"], 2)
            desktop.title = "127.0.0.1_/"  # Chrome app-mode title on Windows, not document.title.
            recorder.capture_once()
            self.assertEqual(desktop.captures, 3, "The local app must never capture itself")
            desktop.title = "Verification notes"
            recorder.configure({"exclude_apps": ["Notepad"]})
            recorder.capture_once()
            self.assertEqual(desktop.captures, 3, "Exclusions must run before screenshot acquisition")
            recorder.configure({"enabled": False, "exclude_apps": []})
            recorder.capture_once()
            self.assertEqual(desktop.captures, 3)
            recorder.close()
