"""Import a user-downloaded Canvas Calendar ``.ics`` snapshot into School.

This is deliberately a local file import, not a Canvas API client.  It never
accepts a Canvas password, personal access token, or calendar-feed URL.  The
parser excludes event descriptions and URLs before this importer sees a record.

Usage:
    .venv/bin/python ingest/import_canvas_calendar.py /path/to/calendarfeed.ics
    .venv/bin/python ingest/import_canvas_calendar.py calendarfeed.ics --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, school
from ingest.canvas_ics import CanvasICSParseError, parse_canvas_ics


DEFAULT_INVENTORY = Path(__file__).resolve().parent.parent / "data" / "fall_2026_school_seed.json"
_TRAILING_CALENDAR_LABEL = re.compile(r"\s*\[[^\[\]]{1,160}\]\s*$")


def _kind(summary: str, is_deadline: bool) -> str:
    text = summary.casefold()
    # Canvas sometimes represents an attendance-bearing class as a 23:59
    # zero-duration event.  The title is a better signal than that synthetic
    # deadline time; it should read as a class in the School queue rather than
    # masquerade as a homework assignment.
    if re.search(r"\b(?:class|office hours|guest speaker|panel|meeting)\b", text):
        return "class"
    if "exam" in text or "midterm" in text or "final" in text:
        return "exam"
    if "quiz" in text:
        return "quiz"
    if "discussion" in text:
        return "discussion"
    if "lab" in text:
        return "lab"
    if "lecture" in text:
        return "lecture"
    if not is_deadline:
        return "event"
    return "assignment"


def _iso(day: str, clock: str | None) -> str:
    return f"{day}T{clock}" if clock else day


def records_for_school(events: list[dict]) -> list[dict]:
    """Map parser output to the narrow School importer contract."""
    records: list[dict] = []
    for event in events:
        title = _TRAILING_CALENDAR_LABEL.sub("", event["summary"]).strip()
        records.append({
            "external_id": event["event_id"],
            "course_label": event.get("course_label"),
            "title": title or "Canvas event",
            "kind": _kind(title, bool(event.get("is_deadline"))),
            # Canvas date-times were already converted to America/Chicago by
            # the parser. Never retain UTC values or feed metadata here.
            "due_at": _iso(event["date"], event.get("start_time")),
            "start_at": _iso(event["date"], event.get("start_time")),
            "end_at": _iso(event["end_date"], event.get("end_time")),
            "all_day": bool(event.get("is_all_day")),
            "location": event.get("location") or "",
        })
    return records


def preview(path: str | Path, inventory_path: str | Path = DEFAULT_INVENTORY) -> dict:
    """Return only import counts, suitable for a privacy-safe dry run."""
    events = parse_canvas_ics(path)
    # Use a throwaway DB connection only for matching aliases. No source bytes,
    # event descriptions, or URLs enter SQLite during a dry run.
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Inventory seeding also projects verified meetings to the shared calendar
    # when it exists. Build the normal schema in this throwaway database so a
    # dry run exercises the same matching path without touching Ian's data.
    conn.executescript(db.SCHEMA)
    db.run_migrations(conn)
    school.seed_inventory_file(conn, inventory_path)
    accepted = 0
    for record in records_for_school(events):
        if school._resolve_course_code(conn, record.get("course_label")):  # noqa: SLF001 - same module boundary
            accepted += 1
    conn.close()
    return {"events": len(events), "recognized": accepted, "ignored": len(events) - accepted}


def import_file(path: str | Path, inventory_path: str | Path = DEFAULT_INVENTORY) -> dict:
    events = parse_canvas_ics(path)
    conn = db.connect()
    try:
        seed = school.seed_inventory_file(conn, inventory_path)
        report = school.import_canvas_items(conn, records_for_school(events))
    finally:
        conn.close()
    return {**report, **seed, "events": len(events)}


def seed_only(inventory_path: str | Path = DEFAULT_INVENTORY) -> dict:
    """Reload the syllabus inventory alone, with no Canvas snapshot.

    The `syllabus` provider's items come from `known_major_dates` in the
    inventory file, and `seed_inventory` archives any syllabus item the file
    no longer lists. So the file is the only correct place to add a deadline
    the Canvas feed never carried (ANTH 210 is asynchronous; its weekly module
    deadlines are on the module page, not in the .ics), and this is how that
    edit reaches the database without waiting for a new .ics export.

    It touches the `syllabus` and `school_schedule` providers only. Canvas
    items are not read, rewritten, or archived here.
    """
    conn = db.connect()
    try:
        return school.seed_inventory_file(conn, inventory_path)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a local Canvas calendar .ics snapshot")
    parser.add_argument("file", type=Path, nargs="?",
                        help="Downloaded Canvas calendar .ics file")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--dry-run", action="store_true", help="Validate and count without writing")
    parser.add_argument("--seed-only", action="store_true",
                        help="Reload the syllabus inventory without a Canvas .ics file")
    args = parser.parse_args()
    if args.seed_only:
        if not args.inventory.is_file():
            sys.exit("School inventory file was not found.")
        try:
            report = seed_only(args.inventory)
        except ValueError as exc:
            sys.exit(f"School inventory could not be loaded: {exc}")
        print(
            f"Syllabus inventory reloaded: {report['courses']} courses, "
            f"{report['syllabus_items']} syllabus items, "
            f"{report['scheduled_meetings']} verified class meetings projected"
        )
        return
    if args.file is None:
        sys.exit(
            "Give a Canvas .ics file, or use --seed-only to reload just the syllabus inventory:\n"
            "  make import-canvas FILE=/absolute/path/to/calendarfeed.ics\n"
            "  make sync-syllabus"
        )
    if not args.file.is_file():
        sys.exit(
            f"Canvas calendar file was not found: {args.file}\n"
            "Download the .ics export locally, then run:\n"
            "  make import-canvas FILE=/absolute/path/to/calendarfeed.ics"
        )
    if not args.inventory.is_file():
        sys.exit("School inventory file was not found.")
    try:
        report = preview(args.file, args.inventory) if args.dry_run else import_file(args.file, args.inventory)
    except CanvasICSParseError as exc:
        sys.exit(str(exc))
    except ValueError as exc:
        sys.exit(f"School inventory could not be loaded: {exc}")
    if args.dry_run:
        print(f"dry-run Canvas calendar: {report['events']} events, {report['recognized']} recognized, {report['ignored']} ignored")
    else:
        print(
            f"Canvas calendar imported: {report['imported']} items, {report['ignored']} ignored, "
            f"{report['archived']} archived, {report['courses']} courses seeded, "
            f"{report['scheduled_meetings']} verified class meetings projected"
        )


if __name__ == "__main__":
    main()
