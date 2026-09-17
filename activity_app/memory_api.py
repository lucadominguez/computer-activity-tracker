"""Memory endpoints inherit the existing authenticated loopback boundary."""

from urllib.parse import parse_qs, urlsplit

from . import inference


class MemoryRoutes:
    def memory_get(self, path):
        memory = self.server.controller.memory
        if path == "/api/memory":
            p = parse_qs(urlsplit(self.path).query, keep_blank_values=True, max_num_fields=10)
            if any(len(v) != 1 for v in p.values()) or set(p) - {
                "q",
                "app",
                "start",
                "end",
                "offset",
                "limit",
            }:
                raise ValueError("Invalid memory filters.")
            options = {
                "query": p.get("q", [""])[0],
                "app": p.get("app", [""])[0],
                "start": float(p.get("start", ["0"])[0]),
                "end": float(p.get("end", ["32503680000"])[0]),
                "offset": int(p.get("offset", ["0"])[0]),
                "limit": int(p.get("limit", ["80"])[0]),
            }
            result = memory.store.search(**options)
            self.send(
                200, {**result, "capture": memory.status(), "recorder": self.server.controller.status()}
            )
        elif path == "/api/memory/sessions":
            p = parse_qs(urlsplit(self.path).query, max_num_fields=2)
            if any(len(v) != 1 for v in p.values()) or set(p) - {"start", "end"}:
                raise ValueError("Invalid session range.")
            self.send(
                200,
                memory.store.sessions(
                    start=float(p.get("start", ["0"])[0]), end=float(p.get("end", ["32503680000"])[0])
                ),
            )
        elif path == "/api/memory/status":
            result = memory.store.search(limit=1)
            self.send(
                200,
                {
                    "capture": memory.status(),
                    "recorder": self.server.controller.status(),
                    "count": result["count"],
                    "bytes": result["bytes"],
                },
            )
        elif path == "/api/memory/access":
            self.send(200, {"items": memory.store.receipts()})
        elif path.startswith("/api/memory/image/"):
            self.send(200, memory.store.image(path.removeprefix("/api/memory/image/")), "image/webp")
        elif path.startswith("/api/memory/moment/"):
            self.send(200, memory.store.get(path.removeprefix("/api/memory/moment/")))
        else:
            self.send(404, {"error": "Not found."})

    def memory_post(self, path, body):
        memory = self.server.controller.memory
        if path == "/api/memory/settings":
            self.send(200, memory.configure(body))
        elif path == "/api/memory/handoff":
            self.send(200, memory.store.handoff(body.get("ids")))
        elif path == "/api/memory/infer":
            try:
                self.send(200, memory.infer(body.get("ids")))
            except inference.NotConfigured as exc:
                self.send(409, {"error": str(exc), "inference": "off"})
            except inference.InferenceError as exc:
                self.send(502, {"error": str(exc), "inference": "failed"})
        elif path == "/api/memory/delete":
            memory.store.delete(body.get("id"))
            self.send(200, {"ok": True})
        else:
            self.send(404, {"error": "Not found."})
