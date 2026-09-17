"""Encrypted moment payloads and media; searchable plaintext exists only in RAM.

The SQLite envelope exposes timestamps, IDs and sizes, not titles or OCR. The
legacy activity database is separate and unchanged. This is not full SQLCipher.
"""

import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .vault import Vault


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid moment identifier.")
    return value


class MemoryStore:
    def __init__(self, root):
        self.root = Path(root)
        self.vault = Vault(root)
        self.lock = threading.RLock()
        self.media = self.root / "media"
        self.media.mkdir(exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.root / "moments.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""CREATE TABLE IF NOT EXISTS moments
            (id TEXT PRIMARY KEY, ts REAL NOT NULL, payload BLOB NOT NULL, size INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS moments_time ON moments(ts);
            CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, ts REAL, payload BLOB);""")
        self.index = sqlite3.connect(":memory:", check_same_thread=False)
        self.index.execute("CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED, title, app, text, url)")
        self.items = {}
        for mid, payload in self.db.execute("SELECT id,payload FROM moments ORDER BY ts"):
            self._index(json.loads(self.vault.open(payload, mid)))

    def _index(self, item):
        self.items[item["id"]] = item
        self.index.execute(
            "INSERT INTO search VALUES (?,?,?,?,?)",
            tuple(item.get(k, "") for k in ("id", "title", "app", "text", "url")),
        )
        self.index.commit()

    def add(self, item, image):
        mid = uuid.uuid4().hex
        data = {key: str(item.get(key, ""))[:100000] for key in ("title", "app", "text", "url")}
        data.update(id=mid, ts=float(item["ts"]))
        if not math.isfinite(data["ts"]) or len(image) > 32 * 1024 * 1024:
            raise ValueError("Invalid moment.")
        payload = self.vault.seal(json.dumps(data).encode(), mid)
        media = self.vault.seal(image, mid + ":image")
        target = self.media / (mid + ".bin")
        with self.lock:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(media)
                with self.db:
                    self.db.execute(
                        "INSERT INTO moments VALUES (?,?,?,?)", (mid, data["ts"], payload, len(media))
                    )
            except Exception:
                target.unlink(missing_ok=True)
                raise
            self._index(data)
        return dict(data)

    def get(self, mid):
        with self.lock:
            return dict(self.items[identifier(mid)])

    def image(self, mid):
        mid = identifier(mid)
        with self.lock:
            if mid not in self.items:
                raise KeyError(mid)
            return self.vault.open((self.media / (mid + ".bin")).read_bytes(), mid + ":image")

    def search(self, query="", app="", start=0, end=32503680000, offset=0, limit=80):
        if (
            not isinstance(query, str)
            or len(query) > 500
            or not isinstance(app, str)
            or len(app) > 200
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start >= end
            or not 0 <= offset <= 1000000
            or not 1 <= limit <= 5000
        ):
            raise ValueError("Invalid search bounds.")
        with self.lock:
            ids = None
            words = re.findall(r"\w+", query, re.UNICODE)[:40]
            if words:
                phrase = " AND ".join('"' + word + '"*' for word in words)
                ids = {
                    r[0] for r in self.index.execute("SELECT id FROM search WHERE search MATCH ?", (phrase,))
                }
            rows = [
                r
                for r in self.items.values()
                if start <= r["ts"] < end and (not app or r["app"] == app) and (ids is None or r["id"] in ids)
            ]
            rows.sort(key=lambda r: (r["ts"], r["id"]), reverse=True)
            result = [{**r, "text": r["text"][:400]} for r in rows[offset : offset + limit]]
            return {
                "items": result,
                "total": len(rows),
                "offset": offset,
                "has_more": offset + limit < len(rows),
                "apps": sorted({r["app"] for r in self.items.values()}),
                "count": len(self.items),
                "bytes": self.db.execute("SELECT coalesce(sum(size),0) FROM moments").fetchone()[0],
            }

    def sessions(self, start=0, end=32503680000):
        if not math.isfinite(start) or not math.isfinite(end) or start >= end:
            raise ValueError("Invalid session range.")
        with self.lock:
            rows = sorted((r for r in self.items.values() if start <= r["ts"] < end), key=lambda r: r["ts"])
            groups = []
            for row in rows:
                if not groups or row["app"] != groups[-1]["app"] or row["ts"] - groups[-1]["end"] > 300:
                    groups.append(
                        {
                            **row,
                            "text": row["text"][:400],
                            "start": row["ts"],
                            "end": row["ts"],
                            "moments": 0,
                            "ids": [],
                        }
                    )
                group = groups[-1]
                group.update(id=row["id"], title=row["title"], end=row["ts"], ts=row["ts"])
                group["moments"] += 1
                group["ids"] = (group["ids"] + [row["id"]])[-20:]
            groups.reverse()
            return {"items": groups[:500], "total": len(groups), "has_more": len(groups) > 500}

    def handoff(self, ids):
        if not isinstance(ids, list) or not 1 <= len(ids) <= 20:
            raise ValueError("Choose between 1 and 20 moments.")
        with self.lock:
            items = [self.get(mid) for mid in dict.fromkeys(ids)]
            text = "\n\n".join(
                f"[{r['id']}] {r['app']} | {r['title']} | {r['ts']}\n{r['text']}" for r in items
            )
            text = text.encode("utf-8")[:20000].decode("utf-8", "ignore")
            receipt = {
                "id": uuid.uuid4().hex,
                "ts": time.time(),
                "action": "Context handoff",
                "client": "Local app",
                "sources": len(items),
                "bytes": len(text.encode()),
                "moment_ids": [r["id"] for r in items],
            }
            # Commit before returning any text to the browser/clipboard.
            with self.db:
                self.db.execute(
                    "INSERT INTO receipts VALUES (?,?,?)",
                    (
                        receipt["id"],
                        receipt["ts"],
                        self.vault.seal(json.dumps(receipt).encode(), "receipt:" + receipt["id"]),
                    ),
                )
            return {"text": text, "receipt": receipt}

    def receipts(self):
        with self.lock:
            result = []
            for rid, blob in self.db.execute("SELECT id,payload FROM receipts ORDER BY ts DESC LIMIT 500"):
                receipt = json.loads(self.vault.open(blob, "receipt:" + rid))
                receipt["scope"] = []
                for mid in receipt.get("moment_ids", []):
                    moment = self.items.get(mid)
                    receipt["scope"].append(
                        {
                            "id": mid,
                            "title": moment["title"] if moment else "Deleted moment",
                            "app": moment["app"] if moment else "",
                            "excerpt": moment["text"][:180] if moment else "",
                            "deleted": moment is None,
                        }
                    )
                result.append(receipt)
            return result

    def delete(self, mid):
        mid = identifier(mid)
        with self.lock:
            if mid not in self.items:
                raise KeyError(mid)
            with self.db:
                self.db.execute("DELETE FROM moments WHERE id=?", (mid,))
            self.index.execute("DELETE FROM search WHERE id=?", (mid,))
            self.index.commit()
            del self.items[mid]
            (self.media / (mid + ".bin")).unlink(missing_ok=True)

    def prune(self, days=30, max_bytes=2 * 1024**3, now=None):
        now = time.time() if now is None else now
        with self.lock:
            rows = list(self.db.execute("SELECT id,ts,size FROM moments ORDER BY ts"))
            total = sum(row[2] for row in rows)
            for mid, ts, size in rows:
                if ts < now - days * 86400 or total > max_bytes:
                    self.delete(mid)
                    total -= size

    def close(self):
        with self.lock:
            self.index.close()
            self.db.close()
