"""Native adapters. Keys are counted on release; key identities are discarded."""

import os
import shutil
import subprocess
import sys
import threading


class BackendUnavailable(RuntimeError):
    user_facing = True


class KeyCounter:
    def __init__(self):
        self.lock = threading.Lock()
        self.count = 0

    def release(self, _key=None):
        with self.lock:
            self.count += 1

    def take(self):
        with self.lock:
            count, self.count = self.count, 0
            return count


class X11Backend:
    def __init__(self):
        self.display = None
        self.process = None
        self.reader = None
        self.counter = KeyCounter()

    def start(self):
        if not shutil.which("xinput"):
            raise BackendUnavailable("Install xinput to record keyboard counts on X11.")
        try:
            from Xlib import X, display

            self.display = display.Display()
            self.X = X
            self.root = self.display.screen().root
            if not self.display.has_extension("MIT-SCREEN-SAVER"):
                raise BackendUnavailable("This X server does not expose system idle time (MIT-SCREEN-SAVER).")
            self.active = self.display.intern_atom("_NET_ACTIVE_WINDOW")
            self.name = self.display.intern_atom("_NET_WM_NAME")
            self.process = subprocess.Popen(
                ["xinput", "test-xi2", "--root"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            self.reader = threading.Thread(target=self._read, daemon=True, name="aggregate-key-counter")
            self.reader.start()
            if self.process.poll() is not None:
                raise BackendUnavailable("xinput could not attach to this X11 session.")
        except ImportError as exc:
            self.stop()
            raise BackendUnavailable(
                "Install python-xlib from requirements.txt before recording on X11."
            ) from exc
        except Exception:
            self.stop()
            raise

    def _read(self):
        for line in self.process.stdout:
            if "(RawKeyRelease)" in line:
                self.counter.release()

    def sample(self):
        from Xlib import error

        if self.process.poll() is not None:
            raise BackendUnavailable("The X11 input monitor stopped. Restart recording.")
        context = None
        try:
            active = self.root.get_full_property(self.active, self.X.AnyPropertyType)
            if active is not None and len(active.value) and int(active.value[0]):
                window = self.display.create_resource_object("window", int(active.value[0]))
                title = window.get_full_property(self.name, self.X.AnyPropertyType)
                text = (
                    bytes(title.value).decode("utf-8", errors="replace")
                    if title is not None
                    else window.get_wm_name()
                )
                classes = window.get_wm_class() or ()
                context = (
                    (text or "(untitled)").strip()[:512],
                    (classes[-1] if classes else "(unknown)")[:128],
                )
        except (error.BadWindow, error.BadAccess):
            pass  # Windows may disappear between querying their ID and title.
        idle = self.root.screensaver_query_info().idle / 1000.0
        return context, idle, self.counter.take()

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            if self.reader:
                self.reader.join(timeout=3)
            if self.process.stdout:
                self.process.stdout.close()
            self.process = None
        if self.display is not None:
            self.display.close()
            self.display = None


class WindowsBackend:
    def __init__(self):
        self.handle = None
        self.listener = None
        self.counter = KeyCounter()

    def start(self):
        import ctypes
        from ctypes import wintypes

        from windows import windows_activity_tracker as native

        self.native = native
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        # HWND/HANDLE are pointer-sized on 64-bit Windows, not ctypes' default int.
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(native.LASTINPUTINFO)]
        user32.GetLastInputInfo.restype = wintypes.BOOL
        kernel32.GetTickCount.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self.handle, already_running = native.acquire_single_instance()
        if not self.handle:
            raise BackendUnavailable("Windows could not create the recording lock.")
        if already_running:
            self.stop()
            raise BackendUnavailable(
                "Another tracker is already recording. Stop the older collector, then start recording here."
            )
        try:
            from pynput import keyboard

            self.listener = keyboard.Listener(on_release=self.counter.release)
            self.listener.start()
            self.listener.wait()
        except Exception as exc:
            self.stop()
            raise BackendUnavailable(
                "Windows keyboard monitoring could not start. Run install.cmd from your desktop session."
            ) from exc

    def sample(self):
        if not self.listener.is_alive():
            raise BackendUnavailable("Windows keyboard monitoring stopped. Restart recording.")
        return self.native.foreground_context(), self.native.idle_seconds(), self.counter.take()

    def stop(self):
        if self.listener:
            self.listener.stop()
            self.listener.join(timeout=3)
            self.listener = None
        if self.handle:
            self.native.release_single_instance(self.handle)
            self.handle = None


def native_backend(platform=None):
    platform = platform or sys.platform
    if platform == "win32":
        return WindowsBackend()
    if platform.startswith("linux"):
        if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
            raise BackendUnavailable(
                "Wayland capture is not supported. Sign into an X11 session, or browse existing history here."
            )
        if not os.environ.get("DISPLAY"):
            raise BackendUnavailable(
                "No X11 desktop is attached. Launch from your graphical desktop to record activity."
            )
        return X11Backend()
    raise BackendUnavailable(
        "Recording supports Windows and Linux X11 only. Existing history remains readable."
    )
