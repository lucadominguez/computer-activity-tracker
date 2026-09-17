"""Read-only, date-clipped reports over both existing collector schemas."""

import math
import sqlite3
from pathlib import Path

MAX_ROWS = 100000


def validate_range(start, end):
    start, end = float(start), float(end)
    if not all(map(math.isfinite, (start, end))) or not 0 < end - start <= 31 * 86400:
        raise ValueError("Choose a valid period of at most 31 days.")
    return start, end


def report(path, start, end, query="", kind="all", offset=0, limit=100, all_events=False):
    start, end = validate_range(start, end)
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Search must be at most 200 characters.")
    if kind not in ("all", "focus", "afk") or not 0 <= offset <= MAX_ROWS or not 1 <= limit <= 500:
        raise ValueError("Invalid timeline filter or page.")
    path = Path(path)
    events = []
    if path.exists():
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            rows = db.execute(
                """
                SELECT id, 'focus', title, app, started_at, ended_at, key_count
                FROM focus WHERE ended_at > ? AND started_at < ? AND ended_at > started_at
                UNION ALL
                SELECT id, 'afk', '', '', started_at, ended_at, 0
                FROM afk WHERE state = 'afk' AND ended_at > ? AND started_at < ?
                    AND ended_at > started_at
                LIMIT ?
            """,
                (start, end, start, end, MAX_ROWS + 1),
            ).fetchall()
        finally:
            db.close()
        if len(rows) > MAX_ROWS:
            raise ValueError("This period has too many events. Select a shorter period.")
        for row_id, event_kind, title, app, left, right, keys in rows:
            if not all(math.isfinite(v) for v in (left, right)):
                continue
            clipped_left, clipped_right = max(start, left), min(end, right)
            events.append(
                {
                    "id": f"{event_kind}:{row_id}",
                    "kind": event_kind,
                    "title": title or "(untitled)",
                    "app": app or "(unknown)",
                    "start": clipped_left,
                    "end": clipped_right,
                    "seconds": clipped_right - clipped_left,
                    "keys": max(0, keys or 0),
                    "clipped": clipped_left != left or clipped_right != right,
                }
            )
    apps = {}
    bins = [
        {"start": start + (end - start) * i / 24, "active_seconds": 0.0, "afk_seconds": 0.0}
        for i in range(24)
    ]
    active, afk, keys = 0.0, 0.0, 0
    for event in events:
        if event["kind"] == "focus":
            active += event["seconds"]
            keys += event["keys"]
            app = apps.setdefault(
                event["app"], {"app": event["app"], "seconds": 0.0, "keys": 0, "segments": 0}
            )
            app["seconds"] += event["seconds"]
            app["keys"] += event["keys"]
            app["segments"] += 1
        else:
            afk += event["seconds"]
        for bucket in bins:
            seconds = max(
                0,
                min(event["end"], bucket["start"] + (end - start) / 24)
                - max(event["start"], bucket["start"]),
            )
            bucket["active_seconds" if event["kind"] == "focus" else "afk_seconds"] += seconds
    query = query.casefold()
    matching = [
        e
        for e in events
        if (kind == "all" or e["kind"] == kind)
        and (not query or query in (e["app"] + " " + e["title"]).casefold())
    ]
    matching.sort(key=lambda e: (e["start"], e["id"]), reverse=True)
    return {
        "start": start,
        "end": end,
        "active_seconds": active,
        "afk_seconds": afk,
        "key_count": keys,
        "event_count": len(events),
        "apps": sorted(apps.values(), key=lambda app: (-app["seconds"], app["app"])),
        "bins": bins,
        "events": matching if all_events else matching[offset : offset + limit],
        "matching_count": len(matching),
        "offset": offset,
        "limit": limit,
        "has_more": not all_events and offset + limit < len(matching),
        "key_count_note": "Key counts belong to whole segments, including segments crossing the date boundary.",
    }
