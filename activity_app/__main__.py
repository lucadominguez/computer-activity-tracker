"""Launch the local dashboard and recorder, or reopen an existing instance."""

import argparse
import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import __version__
from .controller import Controller
from .instance import InstanceLock
from .web import AppServer


def default_data_dir():
    if os.environ.get("CCA_HOME"):
        return Path(os.environ["CCA_HOME"]).expanduser()
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            / "ComputerActivityTracker"
        )
    legacy = Path(__file__).resolve().parents[1] / "data"
    if (legacy / "activity.sqlite3").exists():
        return legacy
    return (
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "computer-activity-tracker"
    )


def open_dashboard(url):
    if sys.platform == "win32":
        for env, relative in [
            ("ProgramFiles", "Google/Chrome/Application/chrome.exe"),
            ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
        ]:
            base = os.environ.get(env)
            browser = Path(base) / relative if base else None
            if browser and browser.is_file():
                try:
                    subprocess.Popen(
                        [str(browser), "--app=" + url],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                except OSError:
                    pass
    webbrowser.open(url)


def reopen(runtime, open_browser):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            info = json.loads(runtime.read_text(encoding="utf-8"))
            url = urlsplit(info["launch_url"])
            if (
                url.scheme != "http"
                or url.hostname != "127.0.0.1"
                or not url.port
                or url.path != "/"
                or len(url.fragment) != 43
            ):
                raise ValueError("Invalid local runtime URL.")
            origin = f"http://127.0.0.1:{url.port}"
            with urlopen(
                Request(origin + "/api/status", headers={"Cookie": "tracker_session=" + url.fragment}),
                timeout=2,
            ) as response:
                json.load(response)
            if open_browser:
                open_dashboard(info["launch_url"])
            print("Opened the existing local tracker instance.")
            return 0
        except (OSError, ValueError, KeyError):
            time.sleep(0.1)
    raise RuntimeError(
        "Another instance holds this database but is not responding. Close that tracker before relaunching; your history has not been changed."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Computer Activity Tracker: local dashboard and recording. Closing the browser does not stop recording; use Quit tracker in the app."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Run without opening a browser; runtime.json contains the private local launch URL.",
    )
    parser.add_argument("--port", type=int, default=0, help="Loopback port; default selects an unused port.")
    parser.add_argument(
        "--idle-timeout", type=float, default=180, help="Seconds without input before AFK (default 180)."
    )
    parser.add_argument(
        "--poll-interval", type=float, default=1, help="Capture interval in seconds (0.1 to 10)."
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.idle_timeout) or not 1 <= args.idle_timeout <= 86400:
        parser.error("--idle-timeout must be between 1 and 86400 seconds.")
    if not math.isfinite(args.poll_interval) or not 0.1 <= args.poll_interval <= 10:
        parser.error("--poll-interval must be between 0.1 and 10 seconds.")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    data_dir = args.data_dir.expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = InstanceLock(data_dir / "app.lock")
    runtime = data_dir / "runtime.json"
    controller = server = None
    try:
        if not lock.acquire():
            return reopen(runtime, not args.no_browser)
        controller = Controller(data_dir, args.idle_timeout, args.poll_interval)
        server = AppServer(controller, args.port)
        controller.start()
        tmp = runtime.with_suffix(".tmp")
        # Create the capability file with private permissions, not chmod-after-exposure.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "launch_url": server.launch_url}, stream)
        os.replace(tmp, runtime)

        def stop(*_args):
            threading.Thread(target=server.shutdown, daemon=True).start()

        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        if not args.no_browser:
            open_dashboard(server.launch_url)
        print(f"Local dashboard on {server.origin}. Use Quit tracker to stop recording.", flush=True)
        server.serve_forever(poll_interval=0.1)
        return 0
    finally:
        try:
            if controller:
                controller.close()
            if server:
                server.server_close()
            if lock.held:
                runtime.unlink(missing_ok=True)
        finally:
            lock.close()


def entrypoint():
    try:
        return main()
    except (OSError, RuntimeError) as exc:
        message = str(exc)
        if os.name == "nt" and sys.stderr is None:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Computer Activity Tracker could not start", 0x10)
        else:
            print("Tracker could not start: " + message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
