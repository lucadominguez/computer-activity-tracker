"""Checkpointed recording using the existing focus/afk SQLite schema."""

import math
import os
import sqlite3
from pathlib import Path


class CaptureSession:
    def __init__(self, path, idle_timeout=180, max_gap=5):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=5)
        if os.name != "nt":
            self.path.chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS focus (id INTEGER PRIMARY KEY, title TEXT,
                app TEXT, started_at REAL, ended_at REAL, key_count INTEGER);
            CREATE TABLE IF NOT EXISTS afk (id INTEGER PRIMARY KEY, state TEXT,
                started_at REAL, ended_at REAL);
            CREATE INDEX IF NOT EXISTS focus_end ON focus(ended_at);
            CREATE INDEX IF NOT EXISTS afk_end ON afk(ended_at);
        """)
        self.db.commit()
        self.idle_timeout = idle_timeout
        self.max_gap = max_gap
        self.paused = False
        self.current = None
        self.last = None

    def _checkpoint(self, now):
        if self.current is None:
            return
        item = self.current
        end = max(item["start"], now)
        if item["kind"] == "focus":
            self.db.execute(
                "UPDATE focus SET ended_at=?, key_count=? WHERE id=?", (end, item["keys"], item["id"])
            )
        else:
            self.db.execute("UPDATE afk SET ended_at=? WHERE id=?", (end, item["id"]))
        self.db.commit()

    def _end(self, now):
        self._checkpoint(now)
        self.current = None

    def sample(self, now, context, idle, keys=0):
        if self.paused:
            return
        if not all(math.isfinite(v) for v in (now, idle)) or idle < 0:
            raise ValueError("Invalid capture clock or idle sample.")
        if self.last is not None and (now < self.last or now - self.last > self.max_gap):
            self._end(self.last)
        event_kind = "afk" if idle >= self.idle_timeout else ("focus" if context else None)
        identity = (event_kind, context if event_kind == "focus" else None)
        current_identity = None if self.current is None else self.current["identity"]
        boundary = now
        if self.current and event_kind == "afk" and self.current["kind"] != "afk":
            boundary = max(self.current["start"], self.last or now, now - idle + self.idle_timeout)
        if identity != current_identity:
            self._end(boundary)
            if event_kind:
                if event_kind == "focus":
                    cursor = self.db.execute(
                        "INSERT INTO focus(title,app,started_at,ended_at,key_count) VALUES (?,?,?,?,0)",
                        (context[0], context[1], boundary, now),
                    )
                else:
                    cursor = self.db.execute(
                        "INSERT INTO afk(state,started_at,ended_at) VALUES ('afk',?,?)", (boundary, now)
                    )
                self.current = {
                    "identity": identity,
                    "kind": event_kind,
                    "id": cursor.lastrowid,
                    "start": boundary,
                    "keys": 0,
                }
        if self.current and event_kind == "focus":
            self.current["keys"] += max(0, int(keys))
        self._checkpoint(now)
        self.last = now

    def pause(self, now):
        end = min(now, self.last) if self.last is not None and now - self.last > self.max_gap else now
        self._end(end)
        self.paused = True

    def resume(self):
        self.paused = False
        self.last = None

    def close(self, now):
        self.pause(now)
        self.db.close()
