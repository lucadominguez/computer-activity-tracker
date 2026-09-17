"""Focused-window capture and local OCR. Platform imports stay inside adapters."""

import asyncio
import io
import os
import shutil
import subprocess

from PIL import ImageGrab


class ScreenSource:
    def __init__(self):
        self.display = None
        self.automation = None
        self.automation_context = None
        self.loop = None
        self.engine = None

    def context(self):
        if os.name == "nt":
            return self._windows_context()
        if not os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
            raise RuntimeError("Screenshot capture requires an X11 desktop.")
        from Xlib import X, display

        if self.display is None:
            self.display = display.Display()
        root = self.display.screen().root
        prop = root.get_full_property(self.display.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
        if prop is None or not len(prop.value) or not int(prop.value[0]):
            return {"private": True}
        win = self.display.create_resource_object("window", int(prop.value[0]))
        geom = win.get_geometry()
        pos = root.translate_coords(win, 0, 0)
        title = win.get_full_property(self.display.intern_atom("_NET_WM_NAME"), X.AnyPropertyType)
        return {
            "title": bytes(title.value).decode("utf-8", "replace") if title else win.get_wm_name() or "",
            "app": (win.get_wm_class() or ["Unknown"])[-1],
            "private": False,
            "idle": root.screensaver_query_info().idle / 1000,
            "bbox": (pos.x, pos.y, pos.x + geom.width, pos.y + geom.height),
        }

    def _windows_context(self):
        import ctypes
        from ctypes import wintypes

        from windows import windows_activity_tracker as native

        user = ctypes.WinDLL("user32", use_last_error=True)
        user.GetForegroundWindow.restype = wintypes.HWND
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user.GetWindowRect.restype = wintypes.BOOL
        user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user.OpenInputDesktop.restype = wintypes.HANDLE
        user.GetUserObjectInformationW.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user.CloseDesktop.argtypes = [wintypes.HANDLE]
        desktop = user.OpenInputDesktop(0, False, 1)
        if not desktop:
            return {"private": True}
        try:
            name, needed = ctypes.create_unicode_buffer(100), wintypes.DWORD()
            if not user.GetUserObjectInformationW(
                desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)
            ):
                return {"private": True}
            if name.value.casefold() != "default":
                return {"private": True}
        finally:
            user.CloseDesktop(desktop)
        try:
            user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
            user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            pass
        hwnd = user.GetForegroundWindow()
        if not hwnd:
            return {"private": True}
        if self.automation is None:
            import uiautomation as auto

            self.automation = auto
            self.automation_context = auto.UIAutomationInitializerInThread()
            self.automation_context.__enter__()
        focus = self.automation.GetFocusedControl()
        # UIA failure is fail-closed, rather than silently missing a password field.
        if focus is None or focus.IsPassword:
            return {"private": True}
        context = native.foreground_context()
        if not context:
            return {"private": True}
        title, app = context
        rect = wintypes.RECT()
        if (
            not user.GetWindowRect(hwnd, ctypes.byref(rect))
            or rect.right <= rect.left
            or rect.bottom <= rect.top
        ):
            return {"private": True}
        return {
            "title": title,
            "app": app,
            "private": False,
            "idle": native.idle_seconds(),
            "hwnd": int(hwnd),
            "bbox": (rect.left, rect.top, rect.right, rect.bottom),
        }

    def image(self, context):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            user = ctypes.WinDLL("user32")
            user.GetForegroundWindow.restype = wintypes.HWND
            if user.GetForegroundWindow() != context["hwnd"]:
                raise RuntimeError("Window changed before capture.")
            # PrintWindow returns black frames for GPU-composited Chromium windows.
            # Read the visible desktop pixels inside the verified foreground rectangle.
            image = ImageGrab.grab(bbox=context["bbox"], all_screens=True)
            if user.GetForegroundWindow() != context["hwnd"]:
                raise RuntimeError("Window changed during capture.")
            return image
        return ImageGrab.grab(bbox=context["bbox"])

    def text(self, image):
        buf = io.BytesIO()
        image.save(buf, "PNG")
        if os.name != "nt":
            if not shutil.which("tesseract"):
                raise RuntimeError("Install Tesseract for local Linux OCR.")
            result = subprocess.run(
                ["tesseract", "stdin", "stdout", "--psm", "11"],
                input=buf.getvalue(),
                capture_output=True,
                timeout=12,
                check=True,
            )
            return result.stdout.decode("utf-8", "replace").strip()
        if self.loop is None:
            self.loop = asyncio.new_event_loop()
        return self.loop.run_until_complete(asyncio.wait_for(self._windows_text(buf.getvalue()), 12))

    async def _windows_text(self, data):
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

        if self.engine is None:
            self.engine = OcrEngine.try_create_from_user_profile_languages()
            if self.engine is None:
                raise RuntimeError("Install a Windows OCR language in Language settings.")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        bitmap = None
        try:
            writer.write_bytes(data)
            await writer.store_async()
            stream.seek(0)
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_converted_async(
                BitmapPixelFormat.BGRA8, BitmapAlphaMode.IGNORE
            )
            result = await self.engine.recognize_async(bitmap)
            return "\n".join(line.text for line in result.lines)
        finally:
            if bitmap is not None:
                bitmap.close()
            writer.detach_stream()
            writer.close()
            stream.close()

    def close(self):
        if self.display:
            self.display.close()
        if self.loop:
            self.loop.close()
        if self.automation_context:
            self.automation_context.__exit__(None, None, None)
