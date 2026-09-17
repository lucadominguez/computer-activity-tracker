"""Opt-in screenshot/OCR worker. No network except explicit context inference."""

import hashlib
import io
import json
import threading
import time
from pathlib import Path

from . import inference
from .memory_store import MemoryStore

DEFAULTS = {
    "enabled": False,
    "interval": 3,
    "days": 30,
    "max_gb": 2,
    "exclude_apps": ["1password", "bitwarden", "keepass", "lastpass", "credentialui"],
    "exclude_titles": ["password", "sign in", "log in", "incognito", "inprivate", "private browsing"],
    "inference_enabled": False,
    "inference_base_url": "",
    "inference_model": "",
    "inference_key": "",
}
SECRET_FIELDS = ("inference_key",)


class MemoryRecorder:
    def __init__(self, root, active, source_factory=None):
        self.store = MemoryStore(root)
        self.active = active
        self.source_factory = source_factory
        self.source = None
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="passage-moments")
        self.path = Path(root) / "preferences.bin"
        self.settings = {**DEFAULTS}
        self.state = "off"
        self.message = "Screenshots and OCR are off until you enable them."
        self.generation = 0
        self.last_hash = None
        self.last_saved = None
        if self.path.exists():
            try:
                self.settings = self.validate(
                    json.loads(self.store.vault.open(self.path.read_bytes(), "settings"))
                )
            except Exception:
                self.settings = {**DEFAULTS}
                self.state = "error"
                self.message = "Capture settings could not be read. Screenshots remain off."

    @staticmethod
    def validate(changes):
        if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
            raise ValueError("Invalid privacy settings.")
        result = {**DEFAULTS, **changes}
        if type(result["enabled"]) is not bool:
            raise ValueError("Enabled must be a boolean.")
        for field, lo, hi in [("interval", 1, 30), ("days", 1, 90), ("max_gb", 1, 20)]:
            if type(result[field]) is not int or not lo <= result[field] <= hi:
                raise ValueError("Invalid capture or retention setting.")
        for key in ("exclude_apps", "exclude_titles"):
            values = result[key]
            if (
                not isinstance(values, list)
                or len(values) > 50
                or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in values)
            ):
                raise ValueError("Invalid exclusions.")
        if type(result["inference_enabled"]) is not bool:
            raise ValueError("Inference must be enabled or disabled.")
        for field, limit in (("inference_base_url", 200), ("inference_model", 120)):
            if not isinstance(result[field], str) or len(result[field]) > limit:
                raise ValueError("Invalid inference setting.")
        if not isinstance(result["inference_key"], str) or len(result["inference_key"]) > 400:
            raise ValueError("Invalid inference credential.")
        return result

    def secrets(self):
        """Secret settings, never returned by an API response or written to a log."""
        with self.lock:
            return {field: self.settings.get(field, "") for field in SECRET_FIELDS}

    def public_settings(self):
        with self.lock:
            visible = {k: v for k, v in self.settings.items() if k not in SECRET_FIELDS}
            visible["inference_key_set"] = bool(self.settings.get("inference_key"))
            return visible

    def configure(self, changes):
        with self.lock:
            changes = dict(changes)
            clear_key = changes.pop("inference_key_clear", False)
            if type(clear_key) is not bool:
                raise ValueError("Invalid inference credential change.")
            updated = self.validate({**self.settings, **changes})
            if clear_key:
                updated["inference_key"] = ""
            encoded = self.store.vault.seal(json.dumps(updated).encode(), "settings")
            temp = self.path.with_suffix(".tmp")
            temp.write_bytes(encoded)
            temp.replace(self.path)
            self.settings = updated
            self.generation += 1
            self.last_hash = None
            self.state = "ready" if updated["enabled"] else "off"
            self.message = (
                "Waiting for an eligible window." if updated["enabled"] else "Screenshots and OCR are off."
            )
        return self.status()

    def infer(self, ids):
        """Infer what the chosen moments were about. Runs only when the UI asks."""
        with self.lock:
            settings = dict(self.settings)
        if not settings["inference_enabled"]:
            raise inference.NotConfigured(
                "Context inference is off. Enable it in Settings and add a model endpoint."
            )
        items = self.store.context_items(ids, expand=True, limit=inference.MAX_MOMENTS)
        started = time.time()
        result = inference.infer(
            items,
            url=settings["inference_base_url"],
            model=settings["inference_model"],
            key=settings["inference_key"],
        )
        receipt = self.store.commit_receipt(
            "Context inference",
            "Local model call",
            items,
            result["characters"],
            {
                "format": "inferred context",
                "model": result["model"],
                "endpoint": result["endpoint"],
                "duration_ms": int((time.time() - started) * 1000),
                "context": result["context"],
            },
        )
        return {
            **result,
            "receipt": receipt,
            "sources": [
                {"id": row["id"], "title": row["title"], "app": row["app"], "ts": row["ts"]}
                for row in items
            ],
        }

    def status(self):
        with self.lock:
            state = self.state
            if self.settings["enabled"] and not self.active():
                state = "paused"
            return {
                "state": state,
                "message": self.message,
                "settings": self.public_settings(),
                "last_saved": self.last_saved,
                "engine": "On-device OCR",
            }

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.last_hash = None

    def start(self):
        self.thread.start()

    def capture_once(self):
        with self.lock:
            settings = dict(self.settings)
            generation = self.generation
        if not settings["enabled"] or not self.active() or self.stop_event.is_set():
            return
        if self.source is None:
            if self.source_factory:
                self.source = self.source_factory()
            else:
                from .screen_source import ScreenSource

                self.source = ScreenSource()
        context = self.source.context()
        title, app = context.get("title", ""), context.get("app", "")
        if (
            context.get("private", True)
            or context.get("idle", 0) > 180
            or title.startswith(("Passage for Windows", "127.0.0.1_/"))
            or any(s.lower() in app.lower() for s in settings["exclude_apps"])
            or any(s.lower() in title.lower() for s in settings["exclude_titles"])
        ):
            with self.lock:
                self.state, self.message = (
                    "private",
                    "This window is excluded, private, or idle. Nothing is saved.",
                )
                self.last_hash = None
            return
        image = self.source.image(context).convert("RGB")
        image.thumbnail((2000, 1600))
        preview = image.resize((320, 200)).convert("RGB")
        digest = hashlib.sha256(preview.tobytes() + (title + app).encode()).digest()
        if digest == self.last_hash:
            with self.lock:
                self.state, self.message = "remembering", "Screen unchanged. No duplicate saved."
            return
        text = self.source.text(image)
        after = self.source.context()
        if (
            after.get("private", True)
            or after.get("idle", 0) > 180
            or after.get("title", "") != title
            or after.get("app", "") != app
            or after.get("hwnd") != context.get("hwnd")
        ):
            with self.lock:
                self.state, self.message = "private", "Window changed during OCR. Frame discarded."
                self.last_hash = None
            return
        output = io.BytesIO()
        image.save(output, "WEBP", quality=85, method=3)
        with self.lock:
            if (
                generation != self.generation
                or not self.settings["enabled"]
                or not self.active()
                or self.stop_event.is_set()
            ):
                return  # A pause/setting change while OCR ran invalidates this frame.
            now = time.time()
            self.store.add({**context, "text": text, "ts": now}, output.getvalue())
            self.last_hash, self.last_saved = digest, now
            self.state, self.message = (
                "remembering",
                "Saving changed windows. Screenshots and text stay local.",
            )
            self.store.prune(days=settings["days"], max_bytes=settings["max_gb"] * 1024**3)

    def _run(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.capture_once()
                except Exception as exc:
                    with self.lock:
                        self.state = "error"
                        self.message = f"Capture stopped for this window ({type(exc).__name__}). Check OCR and desktop permissions."
                self.stop_event.wait(self.settings["interval"])
        finally:
            if self.source is not None and hasattr(self.source, "close"):
                self.source.close()

    def close(self):
        self.stop_event.set()
        self.invalidate()
        if self.thread.ident is not None:
            self.thread.join(timeout=15)
            if self.thread.is_alive():
                raise RuntimeError("Screenshot worker did not stop; vault remains open for safe shutdown.")
        self.store.close()
