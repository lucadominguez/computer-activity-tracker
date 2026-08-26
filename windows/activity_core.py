#!/usr/bin/env python3
import sqlite3


class ActivityStore:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS focus (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                app TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL,
                key_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS afk (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                state TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def start_focus(self, title, app, started_at):
        cursor = self.conn.execute(
            "INSERT INTO focus "
            "(title, app, started_at, ended_at, key_count) VALUES (?,?,?,?,?)",
            (title, app, started_at, started_at, 0),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_focus(self, row_id, ended_at, key_count):
        self.conn.execute(
            "UPDATE focus SET ended_at=?, key_count=? WHERE id=?",
            (ended_at, key_count, row_id),
        )
        self.conn.commit()

    def add_afk(self, started_at, ended_at):
        self.conn.execute(
            "INSERT INTO afk (state, started_at, ended_at) VALUES (?,?,?)",
            ("afk", started_at, ended_at),
        )
        self.conn.commit()


class ActivityEngine:
    def __init__(self, store, idle_timeout=180):
        self.store = store
        self.idle_timeout = idle_timeout
        self.focus = None
        self.afk_started = None

    def _close_focus(self, now):
        if self.focus is None:
            return
        _title, _app, _started_at, key_count, row_id = self.focus
        self.store.update_focus(row_id, now, key_count)
        self.focus = None

    def sample(self, now, context, idle_seconds):
        is_afk = idle_seconds >= self.idle_timeout
        if is_afk:
            if self.afk_started is None:
                self._close_focus(now)
                self.afk_started = now
            return
        if self.afk_started is not None:
            self.store.add_afk(self.afk_started, now)
            self.afk_started = None
        if context == (self.focus[:2] if self.focus else None):
            self.store.update_focus(self.focus[4], now, self.focus[3])
            return
        self._close_focus(now)
        if context is not None:
            title, app = context
            row_id = self.store.start_focus(title, app, now)
            self.focus = (title, app, now, 0, row_id)

    def record_key(self):
        if self.focus is None:
            return
        title, app, started_at, key_count, row_id = self.focus
        self.focus = (title, app, started_at, key_count + 1, row_id)

    def close(self, now):
        self._close_focus(now)
        if self.afk_started is not None:
            self.store.add_afk(self.afk_started, now)
            self.afk_started = None
