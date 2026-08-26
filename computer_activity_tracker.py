#!/usr/bin/env python3
"""
computer_activity_tracker.py - real computer activity tracker (ActivityWatch-style).

Tracks what is actually happening on the X11 desktop: which window has focus
(window title + app class) and whether the user is present (AFK). Writes time
segments to SQLite. No cloud, no telemetry - all local.

Architecture:
  - Focus:     poll Xlib _NET_ACTIVE_WINDOW every POLL_SEC (needs a WM, e.g. openbox).
  - AFK:       stream `xinput test-xi2 --root` raw input events; any event resets
               the idle timer; after IDLE_TIMEOUT with no events -> away from keys.
               XTEST-synthesized input counts, so this is verifiable headless.
  - Storage:   SQLite at CCA_HOME/activity.sqlite3, focus + afk segment tables.

Usage:
  tracker.py --run 15               # record 15s then stop
  tracker.py --forever              # daemon
  tracker.py --report               # print timeline + per-app summary
  tracker.py --json                 # dump events as JSON
  tracker.py --reset                # clear the DB
"""
import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.abspath(os.path.expanduser(
    os.environ.get("CCA_HOME", os.path.join(BASE_DIR, "data"))
))
os.makedirs(HOME, exist_ok=True)
DB = os.path.join(HOME, "activity.sqlite3")
POLL_SEC = float(os.environ.get("CCA_POLL_SEC", "2"))
IDLE_TIMEOUT = float(os.environ.get("CCA_IDLE_TIMEOUT", "180"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS focus (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT, app TEXT, started_at REAL, ended_at REAL, key_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS afk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT, started_at REAL, ended_at REAL
);
"""


def iso(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


class FocusPoll(threading.Thread):
    """Polls the focused window title + app class via _NET_ACTIVE_WINDOW."""

    def __init__(self, cb):
        super().__init__(daemon=True)
        self.cb = cb
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            from Xlib import X
            from Xlib import display
            from Xlib import error
        except Exception as e:
            print(f"[focus] Xlib unavailable: {e}", file=sys.stderr)
            return
        try:
            disp = display.Display()  # own display, thread-safe
        except Exception as e:
            print(f"[focus] cannot open display: {e}", file=sys.stderr)
            return
        root = disp.screen().root
        net_active = disp.intern_atom("_NET_ACTIVE_WINDOW")
        net_wm_name = disp.intern_atom("_NET_WM_NAME")
        wm_class = disp.intern_atom("WM_CLASS")
        while not self._stop.is_set():
            try:
                wid = root.get_full_property(net_active, X.AnyPropertyType)
                title, klass = "", ""
                if wid is not None and len(wid.value):
                    w = disp.create_resource_object("window", wid.value[0])
                    try:
                        t = w.get_full_property(net_wm_name, X.AnyPropertyType)
                        if t is not None:
                            title = "".join(chr(b) for b in t.value if b != 0)[:48]
                    except (error.BadWindow, error.BadAccess):
                        title = ""
                    try:
                        c = w.get_full_property(wm_class, X.AnyPropertyType)
                        if c is not None:
                            klass = "".join(chr(b) for b in c.value if b != 0)[:24]
                    except (error.BadWindow, error.BadAccess):
                        klass = ""
                    if title:
                        self.cb(title, klass)
            except Exception:
                pass
            disp.sync()
            self._stop.wait(POLL_SEC)
        disp.close()


class IdleStream(threading.Thread):
    """Streams xinput raw XI2 events; calls on_event() on any real input."""

    def __init__(self, on_event):
        super().__init__(daemon=True)
        self.on_event = on_event
        self._stop = threading.Event()
        self.child = None

    def stop(self):
        self._stop.set()
        if self.child is not None:  # release XI2 selection BEFORE we die
            try:
                self.child.terminate()
            except Exception:
                pass

    def run(self):
        try:
            self.child = subprocess.Popen(
                ["xinput", "test-xi2", "--root"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                bufsize=1, universal_newlines=True,
            )
            for line in self.child.stdout:
                if self._stop.is_set():
                    break
                if "RawKeyRelease" in line:
                    self.on_event(True)
                elif "RawButtonPress" in line or "RawButtonRelease" in line:
                    self.on_event(False)
        except Exception as e:
            if not self._stop.is_set():
                print(f"[idle] xinput stream error: {e}", file=sys.stderr)
        finally:
            if self.child is not None:
                try:
                    self.child.wait(timeout=2)
                except Exception:
                    pass


class Tracker:
    def __init__(self):
        self.conn = sqlite3.connect(DB, check_same_thread=False)
        self.conn.executescript(SCHEMA)
        # The original schema had no uniqueness constraint, so INSERT OR REPLACE
        # appended one row on every CLI invocation. Normalize old and new DBs.
        self.conn.execute("DELETE FROM schema_version")
        self.conn.execute("INSERT INTO schema_version (v) VALUES (1)")
        self.conn.commit()
        self._focus = None          # (title, app, started_at)
        self._focus_key_count = 0
        self._afk_seg = None        # (state, started_at)
        self._idle = time.time()
        self.state = "active"
        self.signal_stop = threading.Event()
        self.lock = threading.Lock()

    def on_event(self, is_key=True):
        with self.lock:
            self._idle = time.time()
            if is_key and self.state == "active" and self._focus is not None:
                self._focus_key_count += 1

    def on_focus(self, title, app):
        with self.lock:
            nowt = time.time()
            # while AFK, don't open new focus segments (user isn't active)
            if self.state == "afk":
                return
            # same window as current segment -> extend in place, no split
            if self._focus is not None and self._focus[0] == title and self._focus[1] == app:
                return
            if self._focus is not None:
                self._close_focus(nowt)
            if title:
                self._focus = (title, app, nowt)
                self._focus_key_count = 0
            else:
                self._focus = None
                self._focus_key_count = 0

    def _close_focus(self, end_tsc):
        title, app, start = self._focus
        if end_tsc - start >= 2.0:
            self.conn.execute(
                "INSERT INTO focus (title, app, started_at, ended_at, key_count)"
                " VALUES (?,?,?,?,?)",
                (title, app, start, end_tsc, self._focus_key_count))
            self.conn.commit()
        self._focus = None
        self._focus_key_count = 0

    def run(self, seconds=None):
        focus = FocusPoll(self.on_focus)
        idle = IdleStream(self.on_event)
        focus.start()
        idle.start()
        started = time.time()
        try:
            while not self.signal_stop.is_set():
                nowt = time.time()
                with self.lock:
                    idle_s = nowt - self._idle
                    new_state = "afk" if idle_s > IDLE_TIMEOUT else "active"
                    if new_state != self.state:
                        if self._focus is not None:
                            self._close_focus(nowt)
                        if self._afk_seg is not None:
                            self.conn.execute(
                                "INSERT INTO afk (state, started_at, ended_at) VALUES (?,?,?)",
                                (self._afk_seg[0], self._afk_seg[1], nowt))
                            self.conn.commit()
                        self._afk_seg = (new_state, nowt)
                        self.state = new_state
                if seconds is not None and nowt - started >= seconds:
                    break
                self.signal_stop.wait(1.0)
        finally:
            nowt = time.time()
            with self.lock:
                if self._focus is not None:
                    self._close_focus(nowt)
                if self._afk_seg is not None:
                    self.conn.execute(
                        "INSERT INTO afk (state, started_at, ended_at) VALUES (?,?,?)",
                        (self._afk_seg[0], self._afk_seg[1], nowt))
                    self.conn.commit()
                self._afk_seg = None
            focus.stop()
            idle.stop()
            self.conn.close()

    def report(self):
        c = self.conn.cursor()
        ev = []
        for tid, app, s, e, k in c.execute(
                "SELECT title, app, started_at, ended_at, key_count FROM focus"
                " WHERE ended_at IS NOT NULL ORDER BY started_at"):
            if e and e > s:
                ev.append((s, "FOC", " " + (app or "?") + "  " + (tid or "(no title)"), e - s, k))
        for st, s, e in c.execute(
                "SELECT state, started_at, ended_at FROM afk ORDER BY started_at"):
            if e and e > s:
                ev.append((s, st.upper(), "", e - s, 0))
        ev.sort()
        print("=== computer activity timeline ===")
        for ts, kind, label, dur, kcnt in ev:
            print(f"{iso(ts)}  {kind:<5} {label:<44} {dur:6.1f}s")
        print("\n=== active time per app ===")
        agg = {}
        for _tid, app, s, e, k in c.execute(
                "SELECT title, app, started_at, ended_at, key_count FROM focus"
                " WHERE ended_at IS NOT NULL"):
            if not (e and e > s):
                continue
            key = app or "(unknown)"
            agg.setdefault(key, [0.0, 0])
            agg[key][0] += e - s
            agg[key][1] += k
        for app, (secs, keys) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
            print(f"{app:<30} {secs:8.1f}s")

    def json_out(self):
        c = self.conn.cursor()
        out = {"focus": [], "afk": []}
        for tid, app, s, e, k in c.execute(
                "SELECT title, app, started_at, ended_at, key_count FROM focus"
                " WHERE ended_at IS NOT NULL ORDER BY started_at"):
            out["focus"].append({"title": tid, "app": app, "start": s, "end": e, "keys": k})
        for st, s, e in c.execute(
                "SELECT state, started_at, ended_at FROM afk ORDER BY started_at"):
            out["afk"].append({"state": st, "start": s, "end": e})
        print(json.dumps(out, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Computer activity tracker")
    ap.add_argument("--run", type=float, default=0.0, help="record N seconds then stop")
    ap.add_argument("--forever", action="store_true", help="daemon mode")
    ap.add_argument("--report", action="store_true", help="print timeline + summary")
    ap.add_argument("--json", action="store_true", help="dump events as JSON")
    ap.add_argument("--reset", action="store_true", help="clear the DB")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(DB):
            os.remove(DB)
        print("DB cleared.")
        return

    if args.report:
        t = Tracker()
        t.report()
        return
    if args.json:
        t = Tracker()
        t.json_out()
        return

    t = Tracker()

    def _stop(*_):
        t.signal_stop.set()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(f"Recording computer activity -> {DB} (idle>{IDLE_TIMEOUT}s = afk)")
    if args.forever:
        print("Daemon mode. Ctrl+C to stop gracefully.")
        t.run(None)
    else:
        n = args.run or 12
        print(f"Recording {n:.0f}s...")
        t.run(n)
        print("done")


if __name__ == "__main__":
    main()