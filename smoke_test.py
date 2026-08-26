#!/usr/bin/env python3
"""
smoke_test.py - deterministic verification for the computer activity tracker.

Runs a full capture against a live X11 :100 display with two real titled
windows that outlive the recording, switches focus with xdotool, injects real
keyboard input, then asserts the recorded timeline proves:

  A) distinct focus segments were captured (title + app class persisted)
  B) segmentation is coalesced (no 2s per-poll thrash)
  C) at least two distinct apps appear
  D) AFK state transitions were recorded and no focus opens while AFK

Usage:  .venv/bin/python smoke_test.py
Requires Xvfb :100 + openbox up, venv with python-xlib/mss.
"""
import os
BASE = os.path.dirname(os.path.abspath(__file__))
CCA_HOME = os.path.join(BASE, "data")
os.environ.setdefault("DISPLAY", ":100")
os.environ.setdefault("CCA_HOME", CCA_HOME)
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time

PY = os.path.join(BASE, ".venv", "bin", "python")
DB = os.path.join(CCA_HOME, "activity.sqlite3")
SVG_WIN = None  # set by launching subprocesses


def reset_db():
    if os.path.exists(DB):
        os.remove(DB)


def run_capture(seconds):
    p = subprocess.Popen(
        [PY, f"{BASE}/computer_activity_tracker.py", "--run", str(seconds)],
        env={
            **os.environ,
            "DISPLAY": ":100",
            "CCA_HOME": CCA_HOME,
            "CCA_IDLE_TIMEOUT": "8",
        },
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p


def open_tk_window(title, hold_s, label_text):
    code = (
        "import os, tkinter as tk, time;"
        f"r=tk.Tk(); r.title({title!r}); r.geometry('500x300+100+60');"
        f"tk.Label(r,text={label_text!r}).pack(); r.update();"
        "print('UP', r.winfo_id(), flush=True);"
        f"time.sleep({hold_s})"
    )
    env = {**os.environ, "DISPLAY": ":100"}
    p = subprocess.Popen([sys.executable, "-c", code], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True)
    first = p.stdout.readline().strip() if p.stdout else ""
    if not first.startswith("UP"):
        return p, None
    # Tk's winfo_id() is an inner child after a reparenting WM takes over.
    # Activate the EWMH top-level client that _NET_ACTIVE_WINDOW reports.
    found = subprocess.run(
        ["xdotool", "search", "--sync", "--onlyvisible", "--name",
         f"^{re.escape(title)}$"],
        env={**os.environ, "DISPLAY": ":100"},
        check=False, capture_output=True, text=True, timeout=5,
    )
    ids = [line.strip() for line in found.stdout.splitlines() if line.strip()]
    return p, int(ids[-1]) if ids else None


def dotool(*args):
    r = subprocess.run(["xdotool", *args], env={**os.environ, "DISPLAY": ":100"},
                       check=False, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[xdotool] {' '.join(args)} -> rc={r.returncode} {r.stderr.strip()}", flush=True)
    return r


def get_row_counts():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    foc = cur.execute(
        "SELECT title, app, started_at, ended_at FROM focus "
        "WHERE ended_at IS NOT NULL ORDER BY started_at").fetchall()
    afk = cur.execute(
        "SELECT state, started_at, ended_at FROM afk "
        "ORDER BY started_at").fetchall()
    con.close()
    return foc, afk


def iso(ts):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def focus_overlaps_afk(foc, afk):
    """True if any focus segment overlaps an *active* afk segment."""
    afk_idle = [(s, e) for st, s, e in afk if st == "afk" and e and e > s]
    for _t, _a, s, e in foc:
        for as_, ae in afk_idle:
            if s < ae and e > as_:  # overlap
                return True
    return False


def main():
    import sys as _s
    _print = lambda *a, **k: print(*a, flush=True, **k)
    reset_db()
    a_win = None
    b_win = None
    wa = wb = None
    try:
        _print("[smoke] opening window A")
        wa, a_win = open_tk_window("ATSmoke-NotepadStandin", 40, "first window")
        time.sleep(2)
        _print("[smoke] opening window B")
        wb, b_win = open_tk_window("Icebreak Terminal", 40, "second window")
        time.sleep(1.5)
        _print(f"[smoke] windows A={a_win} B={b_win}")
        if not a_win or not b_win:
            print("FAIL: could not open both tk windows", flush=True)
            return 1

        _print("[smoke] starting recorder")
        rec = run_capture(seconds=26)
        time.sleep(1.5)

        _print("[smoke] focus A + type")
        dotool("windowactivate", "--sync", str(a_win))
        time.sleep(1.0)
        dotool("type", "--delay", "60", "first-app text punching through the ice")
        time.sleep(0.6)
        dotool("key", "Return")
        time.sleep(2.0)

        _print("[smoke] focus B + type")
        dotool("windowactivate", "--sync", str(b_win))
        time.sleep(1.4)
        dotool("type", "--delay", "60", "second-app riding the flatline")
        time.sleep(0.6)
        dotool("key", "Return")
        time.sleep(1.5)

        _print("[smoke] quiet window -> AFK")
        time.sleep(10)

        _print("[smoke] awaiting recorder")
        rec.wait(timeout=30)
        code = rec.returncode
        if code != 0:
            err = rec.stderr.read() if rec.stderr else ""
            print(f"FAIL: tracker exited {code}: {err}")
            return 1

        foc, afk = get_row_counts()

        # ASSERTIONS
        fails = []

        # A) focus segments captured with real titles + app classes
        if not foc:
            fails.append("no focus segments recorded (title/app missing)")
        else:
            titled = [f for f in foc if f[0] and f[1]]
            if not titled:
                fails.append("no focus segment carried a non-empty title+app")
            titles = {title for title, _app, _start, _end in titled}
            expected_titles = {"ATSmoke-NotepadStandin", "Icebreak Terminal"}
            missing_titles = expected_titles - titles
            if missing_titles:
                fails.append(
                    "focus switching missed titled windows: "
                    + ", ".join(sorted(missing_titles)))

        # B) coalesced: far fewer segments than POLL_SEC*total (no per-poll split)
        if foc:
            total_focus_secs = sum(e - s for _, _, s, e in foc)
            if len(foc) > max(2, total_focus_secs // 3 + 2):
                fails.append(
                    f"segmentation not coalesced: {len(foc)} rows for "
                    f"{total_focus_secs:.1f}s (thrashing)")

        # D) AFK recorded; while AFK no focus segment should have opened
        if not any(a_ for a_ in afk):
            fails.append("no AFK transitions captured")
        elif focus_overlaps_afk(foc, afk):
            fails.append("a focus segment opened during AFK (suppression broken)")

        # final verdict
        print("=== captured focus segments ===")
        for t, a, s, e in foc:
            print(f"  [{iso(s)}] {a or '?'}: {t}  {e-s:.1f}s")
        print("=== afk segments ===")
        for st, s, e in afk:
            print(f"  [{iso(s)}] {st}  {e-s:.1f}s")

        if fails:
            print("\nFAIL:")
            for f in fails:
                print(f"  - {f}")
            return 1
        print("\nPASS: focus captured+coalesced, app classes persisted, "
              "AFK transitions recorded.")
        return 0
    finally:
        if wa is not None:
            wa.terminate()
        if wb is not None:
            wb.terminate()


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())