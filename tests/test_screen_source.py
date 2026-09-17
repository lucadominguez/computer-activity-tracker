import importlib.util
import os
import shutil
import unittest

from PIL import Image, ImageDraw, ImageFont


class NativeOCRTests(unittest.TestCase):
    def test_windows_capture_reads_composited_pixels_not_printwindow(self):
        import ctypes
        from unittest.mock import MagicMock, patch

        from activity_app.screen_source import ScreenSource

        source = ScreenSource()
        native = MagicMock()
        native.GetForegroundWindow.return_value = 101
        try:
            with (
                patch("activity_app.screen_source.os.name", "nt"),
                patch.object(ctypes, "WinDLL", return_value=native, create=True),
                patch("activity_app.screen_source.ImageGrab.grab") as grab,
            ):
                source.image({"hwnd": 101, "bbox": (10, 20, 810, 620)})
                grab.assert_called_once_with(bbox=(10, 20, 810, 620), all_screens=True)
        finally:
            source.close()

    @unittest.skipUnless(os.name == "nt" or shutil.which("tesseract"), "Requires on-device OCR")
    def test_native_engine_reads_an_actual_rendered_image(self):
        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.screen_source"), "Native screenshot/OCR adapter missing"
        )
        from activity_app.screen_source import ScreenSource

        image = Image.new("RGB", (1000, 200), "white")
        font_path = (
            "C:/Windows/Fonts/arial.ttf"
            if os.name == "nt"
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        ImageDraw.Draw(image).text(
            (30, 50), "ORCHID RIVER 4729", font=ImageFont.truetype(font_path, 55), fill="black"
        )
        source = ScreenSource()
        try:
            text = source.text(image)
            self.assertIn("ORCHID", text.upper())
            self.assertIn("4729", text)
        finally:
            source.close()
