"""A single worker owns SQLite and native input; HTTP actions use a queue."""

import json
import os
import queue
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from .capture import CaptureSession


class Controller:
    def __init__(self, data_dir, idle_timeout=180, poll_interval=1, backend_factory=None):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "activity.sqlite3"
        self.settings_path = self.data_dir / "settings.json"
        self.idle_timeout = idle_timeout
        self.poll_interval = poll_interval
        self.backend_factory = backend_factory
        self._state = {
            "state": "starting",
            "message": "Starting local recording.",
            "last_sample": None,
            "database": str(self.db_path),
            "idle_timeout": idle_timeout,
        }
        self._lock = threading.Lock()
        self._commands = queue.Queue(maxsize=16)
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="activity-capture", daemon=True)
        self._source = None
        from .memory_capture import MemoryRecorder

        self.memory = MemoryRecorder(self.data_dir / "passage", lambda: self.status()["state"] == "recording")
        self._memory_closed = False

    def status(self):
        with self._lock:
            return dict(self._state)

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def start(self):
        self._thread.start()
        if not self._ready.wait(10):
            self._stop.set()
            raise RuntimeError("Recording startup timed out.")
        self.memory.start()

    def _settings(self, paused):
        tmp = self.settings_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump({"paused": paused}, stream)
        os.replace(tmp, self.settings_path)

    def _connect(self):
        if self.backend_factory is None:
            from .backends import native_backend

            factory = native_backend
        else:
            factory = self.backend_factory
        self._source = factory()
        self._source.start()
        self._update(state="recording", message="Recording on this computer. Nothing is uploaded.")

    def _disconnect(self):
        if self._source:
            try:
                self._source.stop()
            finally:
                self._source = None

    def _sample(self, session):
        if self._source is not None:
            context, idle, keys = self._source.sample()
            now = time.time()
            session.sample(now, context, idle, keys)
            self._update(last_sample=now)

    def _failure(self, exc):
        self._disconnect()
        # Only our explicitly user-facing backend errors may enter the UI.
        message = (
            str(exc)
            if getattr(exc, "user_facing", False)
            else f"Recording stopped ({type(exc).__name__}). Check local permissions and restart recording."
        )
        self._update(state="error", message=message)

    def _run(self):
        session = None
        try:
            session = CaptureSession(self.db_path, self.idle_timeout, max(5, self.poll_interval * 3))
            paused = False
            if self.settings_path.exists():
                # A damaged preference file fails closed, never silently resumes capture.
                try:
                    config = json.loads(self.settings_path.read_text(encoding="utf-8"))
                    paused = config.get("paused", True) is not False
                except (ValueError, AttributeError, OSError):
                    paused = True
            if paused:
                session.pause(time.time())
                self._update(state="paused", message="Recording paused. Your history is still available.")
            else:
                try:
                    self._connect()
                    self._sample(session)
                except Exception as exc:
                    self._failure(exc)
            self._ready.set()
            while not self._stop.is_set():
                try:
                    action, future = self._commands.get(timeout=self.poll_interval)
                except queue.Empty:
                    action, future = None, None
                try:
                    if action == "pause":
                        try:
                            self._sample(session)
                        except Exception:
                            pass  # An unreadable desktop must not prevent a privacy pause.
                        self._disconnect()
                        session.pause(time.time())
                        self._settings(True)
                        self._update(
                            state="paused", message="Recording paused. Your history is still available."
                        )
                    elif action == "resume":
                        if self._source is None:
                            session.resume()
                            self._connect()
                            self._sample(session)
                        self._settings(False)
                    elif action is not None:
                        raise ValueError("Unknown recording command.")
                    elif self._source is not None:
                        self._sample(session)
                    if future:
                        future.set_result(self.status())
                except ValueError as exc:
                    if future:
                        future.set_exception(exc)
                    else:
                        self._failure(exc)
                except Exception as exc:
                    self._failure(exc)
                    if future:
                        future.set_exception(RuntimeError(self.status()["message"]))
        except Exception as exc:
            self._failure(exc)
        finally:
            self._ready.set()
            try:
                if session:
                    try:
                        self._sample(session)
                    except Exception:
                        pass  # Preserve the last good checkpoint when the desktop is gone.
                    finally:
                        self._disconnect()
                        session.close(time.time())
            finally:
                if self._stop.is_set():
                    self._update(
                        state="stopped", message="Tracker stopped. Relaunch the app to record again."
                    )

    def command(self, action):
        if action not in ("pause", "resume"):
            raise ValueError("Unknown recording command.")
        if not self._thread.is_alive() or self._stop.is_set():
            raise RuntimeError("Recording worker is stopped. Relaunch the app.")
        if action == "pause":
            self.memory.invalidate()
        future = Future()
        self._commands.put((action, future), timeout=2)
        return future.result(timeout=10)

    def close(self):
        self._stop.set()
        if not self._memory_closed:
            self.memory.close()
            self._memory_closed = True
        if self._thread.ident is not None:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise RuntimeError("Recording worker did not stop in time.")
