"""Explicit local downloads. Spreadsheet formulas in titles are neutralized."""

import csv
import io
import json
from datetime import datetime, timezone

from .reporting import report


def safe_cell(text):
    text = str(text)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def export_data(path, start, end, filetype="csv", **options):
    if filetype not in ("csv", "json"):
        raise ValueError("Unsupported export format.")
    data = report(path, start, end, **{**options, "offset": 0, "all_events": True})
    if filetype == "json":
        return json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(
        ["kind", "app", "title", "start_utc", "end_utc", "seconds", "key_releases", "clipped_to_range"]
    )
    for event in data["events"]:
        writer.writerow(
            [
                event["kind"],
                safe_cell(event["app"]),
                safe_cell(event["title"]),
                datetime.fromtimestamp(event["start"], timezone.utc).isoformat(),
                datetime.fromtimestamp(event["end"], timezone.utc).isoformat(),
                round(event["seconds"], 3),
                event["keys"],
                event["clipped"],
            ]
        )
    return stream.getvalue().encode("utf-8-sig")
