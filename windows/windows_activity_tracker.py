#!/usr/bin/env python3
"""Windows-native foreground activity and AFK tracker.

Stores focused window title, process name, segment duration, aggregate key
release counts, and AFK intervals in local SQLite. Raw key values are discarded.
"""
import argparse
import ctypes
import json
import logging
import os
import signal
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from activity_core import ActivityEngine, ActivityStore

ERROR_ALREADY_EXISTS = 183
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MUTEX_NAME = "Local\\ComputerActivityTracker"


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def default_data_dir():
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "ComputerActivityTracker")
    return os.path.join(BASE_DIR, "data")


def database_path(data_dir):
    return os.path.join(data_dir, "activity.sqlite3")


def _process_name(pid):
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return "pid-{}".format(pid)
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            return os.path.basename(buffer.value) or "pid-{}".format(pid)
    finally:
        kernel32.CloseHandle(handle)
    return "pid-{}".format(pid)


def foreground_context():
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    title = title_buffer.value.strip() or "(untitled)"
    return title[:512], _process_name(pid.value)[:128]


def idle_seconds():
    if os.name != "nt":
        return 0.0
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    current = ctypes.windll.kernel32.GetTickCount()
    elapsed_ms = (int(current) - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed_ms / 1000.0


def acquire_single_instance():
    if os.name != "nt":
        return None, False
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return handle, kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def release_single_instance(handle):
    if handle and os.name == "nt":
        ctypes.windll.kernel32.CloseHandle(handle)


def configure_logging(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(data_dir, "tracker.log"),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def run_tracker(data_dir, poll_seconds, idle_timeout, run_seconds=None):
    if os.name != "nt":
        raise RuntimeError("Live tracking requires Windows")
    configure_logging(data_dir)
    mutex, already_running = acquire_single_instance()
    if already_running:
        logging.info("Start ignored because another tracker instance is running")
        release_single_instance(mutex)
        return 0

    store = ActivityStore(database_path(data_dir))
    engine = ActivityEngine(store, idle_timeout=idle_timeout)
    engine_lock = threading.Lock()
    stop_event = threading.Event()

    try:
        from pynput import keyboard
    except Exception as exc:
        store.close()
        release_single_instance(mutex)
        raise RuntimeError("pynput is required: {}".format(exc))

    def on_key_release(_key):
        with engine_lock:
            engine.record_key()

    listener = keyboard.Listener(on_release=on_key_release)

    def request_stop(*_args):
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    started = time.time()
    listener.start()
    logging.info(
        "Tracker started db=%s poll=%s idle_timeout=%s",
        database_path(data_dir),
        poll_seconds,
        idle_timeout,
    )
    try:
        while not stop_event.is_set():
            now = time.time()
            with engine_lock:
                engine.sample(now, foreground_context(), idle_seconds())
            if run_seconds is not None and now - started >= run_seconds:
                break
            stop_event.wait(poll_seconds)
    finally:
        now = time.time()
        with engine_lock:
            engine.close(now)
        listener.stop()
        listener.join(timeout=2)
        store.close()
        release_single_instance(mutex)
        logging.info("Tracker stopped")
    return 0


def self_test(data_dir):
    os.makedirs(data_dir, exist_ok=True)
    path = database_path(data_dir)
    if os.path.exists(path):
        os.remove(path)
    store = ActivityStore(path)
    engine = ActivityEngine(store, idle_timeout=180)
    engine.sample(100.0, ("SelfTest Editor", "notepad.exe"), 0)
    engine.record_key()
    engine.record_key()
    engine.sample(102.0, ("SelfTest Editor", "notepad.exe"), 0)
    engine.sample(105.0, ("SelfTest Editor", "notepad.exe"), 181)
    engine.sample(110.0, ("SelfTest Browser", "msedge.exe"), 0)
    engine.close(114.0)
    focus = store.conn.execute(
        "SELECT title, app, key_count FROM focus ORDER BY started_at"
    ).fetchall()
    afk = store.conn.execute(
        "SELECT state FROM afk ORDER BY started_at"
    ).fetchall()
    store.close()
    expected_focus = [
        ("SelfTest Editor", "notepad.exe", 2),
        ("SelfTest Browser", "msedge.exe", 0),
    ]
    if focus != expected_focus or afk != [("afk",)]:
        print("SELF-TEST FAIL focus={} afk={}".format(focus, afk), file=sys.stderr)
        return 1
    print("SELF-TEST PASS focus=2 afk=1 key_counts=2")
    return 0


def _load_rows(path):
    store = ActivityStore(path)
    focus = store.conn.execute(
        "SELECT title, app, started_at, ended_at, key_count FROM focus "
        "ORDER BY started_at"
    ).fetchall()
    afk = store.conn.execute(
        "SELECT state, started_at, ended_at FROM afk ORDER BY started_at"
    ).fetchall()
    store.close()
    return focus, afk


def print_report(path):
    focus, afk = _load_rows(path)
    events = []
    for title, app, start, end, keys in focus:
        events.append((start, "FOCUS", app, title, end - start, keys))
    for state, start, end in afk:
        events.append((start, state.upper(), "", "", end - start, 0))
    events.sort()
    print("=== computer activity timeline ===")
    for start, kind, app, title, duration, keys in events:
        stamp = datetime.fromtimestamp(start).strftime("%Y-%m-%d %H:%M:%S")
        print(
            "{} {:<5} {:<24} {:<48} {:7.1f}s keys={}".format(
                stamp, kind, app, title, duration, keys
            )
        )
    totals = {}
    for _title, app, start, end, keys in focus:
        duration, count = totals.get(app, (0.0, 0))
        totals[app] = (duration + end - start, count + keys)
    print("\n=== active time per app ===")
    for app, (duration, keys) in sorted(totals.items(), key=lambda item: -item[1][0]):
        print("{:<32} {:8.1f}s keys={}".format(app, duration, keys))


def print_json(path):
    focus, afk = _load_rows(path)
    payload = {
        "focus": [
            {
                "title": title,
                "app": app,
                "start": start,
                "end": end,
                "keys": keys,
            }
            for title, app, start, end, keys in focus
        ],
        "afk": [
            {"state": state, "start": start, "end": end}
            for state, start, end in afk
        ],
    }
    print(json.dumps(payload, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Windows computer activity tracker")
    parser.add_argument("--data-dir", default=default_data_dir())
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--idle-timeout", type=float, default=180.0)
    parser.add_argument("--run", type=float)
    parser.add_argument("--forever", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    data_dir = os.path.abspath(os.path.expanduser(args.data_dir))
    path = database_path(data_dir)

    if args.self_test:
        return self_test(data_dir)
    if args.reset:
        if os.path.exists(path):
            os.remove(path)
        print("DB cleared: {}".format(path))
        return 0
    if args.report:
        print_report(path)
        return 0
    if args.json:
        print_json(path)
        return 0
    return run_tracker(
        data_dir,
        poll_seconds=args.poll,
        idle_timeout=args.idle_timeout,
        run_seconds=args.run if args.run is not None else None,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        try:
            logging.exception("Tracker failed")
        except Exception:
            pass
        print("ERROR: {}".format(exc), file=sys.stderr)
        sys.exit(1)
