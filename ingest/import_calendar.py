"""Google Calendar .ics import."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db

WORK_KW = ("clockwork", "demo", "call", "audit", "client", "sales", "meeting")
HEALTH_KW = ("gym", "workout", "run", "doctor", "therapy", "health")


def _parse_dt(raw: str) -> tuple[str, str | None]:
    raw = raw.strip()
    if len(raw) == 8:  # YYYYMMDD
        d = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
        return d, None
    if "T" in raw:
        dpart, tpart = raw.split("T", 1)
        d = f"{dpart[:4]}-{dpart[4:6]}-{dpart[6:8]}"
        t = f"{tpart[:2]}:{tpart[2:4]}"
        return d, t
    return raw[:10], None


def _duration_min(start: str, end: str) -> int | None:
    try:
        fmt = "%Y%m%dT%H%M%S"
        s = datetime.strptime(start.replace("Z", "")[:15], fmt)
        e = datetime.strptime(end.replace("Z", "")[:15], fmt)
        return max(0, int((e - s).total_seconds() / 60))
    except ValueError:
        return None


def _categorize(summary: str) -> str:
    low = summary.lower()
    if any(k in low for k in WORK_KW):
        return "work"
    if any(k in low for k in HEALTH_KW):
        return "health"
    return "personal"


def parse_ics(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    events = []
    for block in re.findall(r"BEGIN:VEVENT.*?END:VEVENT", text, re.DOTALL):
        def field(name: str) -> str | None:
            m = re.search(rf"^{name}[;:](.+)$", block, re.MULTILINE)
            return m.group(1).split(":")[-1].strip() if m else None
        summary = (field("SUMMARY") or "event").replace("\\,", ",")
        dtstart = field("DTSTART") or ""
        dtend = field("DTEND") or dtstart
        date_s, start_t = _parse_dt(dtstart)
        _, end_t = _parse_dt(dtend)
        dur = _duration_min(dtstart, dtend) if dtend else 60
        h = hashlib.sha256(f"{date_s}|{start_t}|{summary}".encode()).hexdigest()[:20]
        events.append({
            "date": date_s,
            "start_time": start_t,
            "end_time": end_t,
            "summary": summary,
            "category": _categorize(summary),
            "duration_min": dur,
            "hash": h,
        })
    return events


def main() -> None:
    ap = argparse.ArgumentParser(description="Import Google Calendar .ics")
    ap.add_argument("file", type=Path)
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no such file: {args.file}")
    events = parse_ics(args.file)
    conn = db.connect()
    for ev in events:
        db.upsert_calendar_event(conn, **ev)
    conn.commit()
    db.update_ingest_log(conn, "calendar", len(events), args.file.name)
    print(f"Imported {len(events)} calendar events from {args.file.name}")
    conn.close()


if __name__ == "__main__":
    main()
