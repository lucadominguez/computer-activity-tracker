"""Authenticated loopback-only UI. No remote resources, uploads or CORS."""

import json
import secrets
import sqlite3
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .exports import export_data
from .memory_api import MemoryRoutes
from .reporting import report

STATIC = {
    "/": ("passage.html", "text/html; charset=utf-8"),
    "/activity": ("index.html", "text/html; charset=utf-8"),
    "/passage.css": ("passage.css", "text/css; charset=utf-8"),
    "/passage.js": ("passage.js", "text/javascript; charset=utf-8"),
    "/passage-views.js": ("passage-views.js", "text/javascript; charset=utf-8"),
    "/passage-icon.svg": ("passage-icon.svg", "image/svg+xml"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, controller, port=0):
        self.controller = controller
        self.token = secrets.token_urlsafe(32)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.launch_url = self.origin + "/#" + self.token

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(MemoryRoutes, BaseHTTPRequestHandler):
    server_version = "ActivityTracker"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass  # Search strings, window titles and launch tokens must not enter logs.

    def send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def guard(self):
        host = self.headers.get_all("Host", [])
        origins = self.headers.get_all("Origin", [])
        if (
            host != [f"127.0.0.1:{self.server.server_port}"]
            or len(origins) > 1
            or (origins and origins[0] != self.server.origin)
        ):
            self.send(403, {"error": "Only the local app may access this endpoint."})
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send(403, {"error": "Cross-site requests are not allowed."})
            return False
        if len(self.path) > 8192:
            self.send(414, {"error": "Request is too long."})
            return False
        return True

    def authenticated(self):
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
            token = cookies["tracker_session"].value if "tracker_session" in cookies else ""
        except Exception:
            token = ""
        if not self.valid_token(token):
            self.send(401, {"error": "Open the app using its desktop shortcut or launch command."})
            return False
        return True

    def valid_token(self, token):
        return isinstance(token, str) and token.isascii() and secrets.compare_digest(token, self.server.token)

    def json_body(self):
        if self.headers.get_all("Content-Length") is None or len(self.headers.get_all("Content-Length")) != 1:
            raise ValueError("A single Content-Length header is required.")
        length = int(self.headers["Content-Length"])
        if not 0 < length <= 8192 or self.headers.get_content_type() != "application/json":
            raise ValueError("Send a JSON object of at most 8192 bytes.")
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("A JSON object is required.")
        return body

    def report_options(self):
        params = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=12)
        if any(len(values) != 1 for values in params.values()):
            raise ValueError("Duplicate query parameters are not supported.")
        return {
            "start": float(params.get("start", [""])[0]),
            "end": float(params.get("end", [""])[0]),
            "query": params.get("q", [""])[0],
            "kind": params.get("kind", ["all"])[0],
            "offset": int(params.get("offset", ["0"])[0]),
            "limit": int(params.get("limit", ["100"])[0]),
        }

    def do_GET(self):
        if not self.guard():
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/") and not self.authenticated():
            return
        try:
            if path == "/api/status":
                self.send(200, self.server.controller.status())
            elif path.startswith("/api/memory"):
                self.memory_get(path)
            elif path == "/api/report":
                self.send(200, report(self.server.controller.db_path, **self.report_options()))
            elif path in ("/api/export.csv", "/api/export.json"):
                filetype = path.rsplit(".", 1)[1]
                data = export_data(self.server.controller.db_path, filetype=filetype, **self.report_options())
                mime = "text/csv; charset=utf-8" if filetype == "csv" else "application/json; charset=utf-8"
                self.send(
                    200, data, mime, {"Content-Disposition": f'attachment; filename="activity.{filetype}"'}
                )
            elif path in STATIC:
                filename, mime = STATIC[path]
                source = Path(__file__).parent / "static" / filename
                if source.is_file():
                    self.send(200, source.read_bytes(), mime)
                else:
                    self.send(404, {"error": "Application assets are missing. Reinstall the app."})
            else:
                self.send(404, {"error": "Not found."})
        except KeyError:
            self.send(404, {"error": "Moment not found."})
        except (ValueError, UnicodeError):
            self.send(
                400,
                {
                    "error": "Invalid report options. Choose a valid period of at most 31 days and a valid page."
                },
            )
        except (OSError, sqlite3.Error):
            self.send(
                503,
                {
                    "error": "The activity database is unavailable. Nothing has been reset; check its path and permissions."
                },
            )

    def do_POST(self):
        if not self.guard():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/session":
                if not self.valid_token(self.json_body().get("token")):
                    self.send(401, {"error": "Launch the app again to open a current local session."})
                    return
                self.send(
                    200,
                    {"ok": True},
                    headers={
                        "Set-Cookie": f"tracker_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/"
                    },
                )
                return
            if not self.authenticated():
                return
            if self.headers.get("X-Tracker-Action") != "1":
                self.send(403, {"error": "This action requires the local app controls."})
                return
            if path.startswith("/api/memory/"):
                self.memory_post(path, self.json_body())
                return
            if path != "/api/control":
                self.send(404, {"error": "Not found."})
                return
            action = self.json_body().get("action")
            if action == "quit":
                self.server.controller.close()
                self.send(200, self.server.controller.status())
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.send(200, self.server.controller.command(action))
        except KeyError:
            self.send(404, {"error": "Moment not found."})
        except (ValueError, UnicodeError):
            self.send(400, {"error": "Invalid app command or JSON body."})
        except (OSError, RuntimeError, TimeoutError):
            self.send(503, {"error": "The action did not complete. Check recording status and retry."})
