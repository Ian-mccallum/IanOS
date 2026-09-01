"""Safety and normalization tests for the read-only Canvas ICS parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.canvas_ics import parse_canvas_ics


def _feed(tmp_path, content: str):
    path = tmp_path / "calendarfeed.ics"
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def test_timezone_aware_events_are_converted_and_secrets_are_not_returned(tmp_path):
    path = _feed(
        tmp_path,
        """
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:fin-panel@example.test
DTSTART:20260902T210000Z
DTEND:20260902T215000Z
SUMMARY:FIN 180 (fa26): Leadership Panel
LOCATION:Main Auditorium
DESCRIPTION:Private assignment details. Feed secret: should-never-leave-parser
URL:https://canvas.example.test/calendar?feed_secret=should-never-leave-parser
END:VEVENT
END:VCALENDAR
""",
    )

    [event] = parse_canvas_ics(path)

    assert event["uid"] == "fin-panel@example.test"
    assert event["recurrence_id"] is None
    assert event["date"] == "2026-09-02"
    assert event["start_time"] == "16:00"  # UTC -> CDT in September
    assert event["end_time"] == "16:50"
    assert event["duration_min"] == 50
    assert event["location"] == "Main Auditorium"
    assert event["course_label"] == "FIN 180 (fa26)"
    assert event["category"] == "school"
    assert event["timezone"] == "America/Chicago"
    assert "description" not in event and "url" not in event
    assert "should-never-leave-parser" not in json.dumps(event)


def test_all_day_deadline_uses_no_clock_time_and_an_inclusive_end_date(tmp_path):
    path = _feed(
        tmp_path,
        """
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:stat-homework@example.test
DTSTART;VALUE=DATE:20260831
DTEND;VALUE=DATE:20260901
SUMMARY:STAT 120: Homework 1 due
DESCRIPTION:This must not be returned.
URL:https://canvas.example.test/secret
END:VEVENT
END:VCALENDAR
""",
    )

    [event] = parse_canvas_ics(path)

    assert event["date"] == "2026-08-31"
    assert event["end_date"] == "2026-08-31"  # RFC 5545 DTEND is exclusive
    assert event["start_time"] is None and event["end_time"] is None
    assert event["duration_min"] is None
    assert event["is_all_day"] is True
    assert event["is_deadline"] is True
    assert event["course_label"] == "STAT 120"


def test_recurrence_id_is_centralized_and_part_of_the_stable_identity(tmp_path):
    path = _feed(
        tmp_path,
        """
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:stat-series@example.test
RECURRENCE-ID:20260904T150000Z
DTSTART:20260904T150000Z
DTEND:20260904T155000Z
SUMMARY:CS/IS/STAT 120 (fa26): Lecture
LOCATION:Main Auditorium
END:VEVENT
BEGIN:VEVENT
UID:stat-series@example.test
DTSTART:20260907T150000Z
DTEND:20260907T155000Z
SUMMARY:CS/IS/STAT 120 (fa26): Lecture
LOCATION:Main Auditorium
END:VEVENT
END:VCALENDAR
""",
    )

    events = parse_canvas_ics(path)
    recurring, master = events

    assert recurring["recurrence_id"] == "2026-09-04T10:00:00-05:00"
    assert recurring["event_id"] != master["event_id"]
    assert recurring["uid"] == master["uid"] == "stat-series@example.test"
    assert recurring["course_label"] == "CS/IS/STAT 120 (fa26)"


def test_trailing_canvas_calendar_label_beats_an_ambiguous_assignment_title(tmp_path):
    path = _feed(
        tmp_path,
        """
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:bus-checkpoint@example.test
DTSTART:20260828T045900Z
DTEND:20260828T045900Z
SUMMARY:Checkpoint 1 [bus_120_120268_263096]
DESCRIPTION:Not part of the record.
END:VEVENT
END:VCALENDAR
""",
    )

    [event] = parse_canvas_ics(path)

    assert event["course_label"] == "bus_120_120268_263096"


def test_events_without_a_uid_are_skipped_instead_of_receiving_an_unstable_hash(tmp_path):
    path = _feed(
        tmp_path,
        """
BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260901T235500
DTEND:20260901T235500
SUMMARY:BUS 120: Checkpoint
END:VEVENT
END:VCALENDAR
""",
    )

    assert parse_canvas_ics(path) == []
