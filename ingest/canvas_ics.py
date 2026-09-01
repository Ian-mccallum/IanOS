"""Safe, read-only parser for Canvas calendar ``.ics`` exports.

This module deliberately does *not* write to ianOS's database.  It turns the
small, useful part of a Canvas calendar feed into structured event dictionaries
which a separate, reviewed importer can consume later.

The feed URL is a bearer secret and Canvas event descriptions can contain
private assignment details.  Accordingly, this parser only exposes the fields
documented in :func:`parse_canvas_ics`; it never returns DESCRIPTION, URL,
X-ALT-DESC, calendar metadata, or the source bytes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from icalendar import Calendar


CENTRAL_TIMEZONE = ZoneInfo("America/Chicago")
CENTRAL_TIMEZONE_NAME = "America/Chicago"
MAX_ICS_BYTES = 10 * 1024 * 1024
MAX_EVENTS = 5_000

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
_COURSE_CODE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:(?:[A-Za-z]{2,10}/)+[A-Za-z]{2,10}|[A-Za-z]{2,10})"
    r"\s*\d{2,4}(?:[A-Za-z0-9-]*)?"
    r"(?![A-Za-z0-9])"
)
_TERM_SUFFIX = re.compile(r"\s*\((?:fa|sp|su|wi)\s*\d{2,4}\)", re.IGNORECASE)
_BRACKET_LABEL = re.compile(r"\[([^\[\]]{1,160})\]\s*$")
_DEADLINE_WORDS = re.compile(
    r"\b(?:due|deadline|submit(?:ted|ting|sion)?|assignment|homework|"
    r"quiz|checkpoint|orientation|application activity)\b",
    re.IGNORECASE,
)
_GENERIC_LABEL_WORDS = {
    "activity",
    "assignment",
    "deadline",
    "discussion",
    "due",
    "exam",
    "homework",
    "lecture",
    "quiz",
    "review",
    "submission",
}


class CanvasICSParseError(ValueError):
    """Raised when a feed cannot safely be treated as a Canvas calendar."""


def _clean_text(value: Any, *, limit: int) -> str | None:
    """Return compact plain text without passing arbitrary control data through."""
    if value is None:
        return None
    cleaned = _CONTROL_CHARS.sub(" ", str(value))
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit] or None


def _temporal_value(component: Any, key: str) -> date | datetime | None:
    """Read one iCalendar date or date-time property without exposing other data."""
    prop = component.get(key)
    value = getattr(prop, "dt", None)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value
    return None


def _to_central(value: datetime) -> datetime:
    """Normalize an iCalendar date-time into the local UIUC timezone.

    Canvas feeds normally provide a timezone-aware value.  A naive date-time
    is interpreted as Canvas/UIUC local time rather than the host machine's
    timezone, keeping the import deterministic.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TIMEZONE)
    return value.astimezone(CENTRAL_TIMEZONE)


def _time_string(value: datetime | None) -> str | None:
    return value.strftime("%H:%M") if value is not None else None


def _recurrence_key(value: date | datetime | None) -> str | None:
    """Produce an occurrence identifier in Central time for recurrence upserts."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _to_central(value).isoformat(timespec="seconds")
    return value.isoformat()


def _event_id(uid: str, recurrence_id: str | None) -> str:
    """Return a stable opaque ID; source UID remains available separately."""
    occurrence = recurrence_id or "__master__"
    digest = hashlib.sha256(f"{uid}\x1f{occurrence}".encode("utf-8")).hexdigest()
    return f"canvas:{digest[:32]}"


def _course_label(summary: str) -> str | None:
    """Extract the most useful course-shaped label from a Canvas event summary."""
    # Canvas's export often places its stable course calendar identifier in a
    # trailing bracket, e.g. ``Checkpoint 1 [bus_120_...]``. Prefer it to the
    # human-facing assignment title, which might begin "Week 1" and otherwise
    # cannot be mapped to a course safely.
    bracket = _BRACKET_LABEL.search(summary)
    if bracket:
        return _clean_text(bracket.group(1), limit=160)
    match = _COURSE_CODE.search(summary)
    if match:
        label = match.group(0)
        suffix = _TERM_SUFFIX.match(summary, match.end())
        if suffix:
            label += suffix.group(0)
        return _clean_text(label, limit=160)

    # Some Canvas calendars use a title rather than a subject/catalog code,
    # e.g. ``Forensic Science: Week 1 Quiz``.  Keep a plausible prefix while
    # avoiding labels such as simply ``Quiz due``.
    prefix = re.split(r"\s(?:-|—)\s|:\s*", summary, maxsplit=1)[0].strip(" []")
    words = {word.lower() for word in re.findall(r"[A-Za-z]+", prefix)}
    if prefix and len(prefix) <= 160 and words and not words.issubset(_GENERIC_LABEL_WORDS):
        return _clean_text(prefix, limit=160)
    return None


def _is_deadline(
    summary: str,
    *,
    is_all_day: bool,
    start_time: str | None,
    duration_min: int | None,
) -> bool:
    """Use conservative, inspectable heuristics for Canvas due-date events."""
    if _DEADLINE_WORDS.search(summary):
        return True
    if is_all_day:
        return False
    # Canvas commonly represents an untitled due date as a zero-duration event
    # late in the evening.  Do not classify ordinary timed meetings this way.
    if duration_min in (0, None) and start_time:
        hour, minute = (int(part) for part in start_time.split(":"))
        return time(hour, minute) >= time(20, 0)
    return False


def _record_from_event(component: Any) -> dict[str, Any] | None:
    """Create one safe normalized record, or skip an event without a stable UID."""
    uid = _clean_text(component.get("UID"), limit=512)
    start = _temporal_value(component, "DTSTART")
    if not uid or start is None:
        # Without a UID, a later importer cannot perform an idempotent update.
        # Skipping is safer than inventing an unstable identifier from contents.
        return None

    summary = _clean_text(component.get("SUMMARY"), limit=500) or "Canvas event"
    location = _clean_text(component.get("LOCATION"), limit=300)
    recurrence_id = _recurrence_key(_temporal_value(component, "RECURRENCE-ID"))

    is_all_day = isinstance(start, date) and not isinstance(start, datetime)
    end = _temporal_value(component, "DTEND")

    if is_all_day:
        start_date = start.isoformat()
        # RFC 5545 all-day DTEND is exclusive.  Return a display-friendly,
        # inclusive end date, so a one-day item has matching date/end_date.
        if isinstance(end, date) and not isinstance(end, datetime) and end > start:
            end_date = (end - timedelta(days=1)).isoformat()
        else:
            end_date = start_date
        start_dt = end_dt = None
        duration_min = None
    else:
        start_dt = _to_central(start)
        end_dt = _to_central(end) if isinstance(end, datetime) else None
        start_date = start_dt.date().isoformat()
        end_date = (end_dt.date().isoformat() if end_dt is not None else start_date)
        if end_dt is None:
            duration_min = None
        else:
            duration_min = max(
                0,
                int((end_dt.astimezone(timezone.utc) - start_dt.astimezone(timezone.utc)).total_seconds() / 60),
            )

    start_time = _time_string(start_dt)
    end_time = _time_string(end_dt)
    return {
        # Identity fields are deliberately based only on UID + recurrence,
        # never mutable text such as the event title or an access URL.
        "source": "canvas_ics",
        "event_id": _event_id(uid, recurrence_id),
        "uid": uid,
        "recurrence_id": recurrence_id,
        # Event fields allowed to leave this module.
        "summary": summary,
        "location": location,
        "course_label": _course_label(summary),
        "category": "school",
        "date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "duration_min": duration_min,
        "is_all_day": is_all_day,
        "is_deadline": _is_deadline(
            summary,
            is_all_day=is_all_day,
            start_time=start_time,
            duration_min=duration_min,
        ),
        "timezone": CENTRAL_TIMEZONE_NAME,
    }


def parse_canvas_ics(path: str | Path) -> list[dict[str, Any]]:
    """Parse a Canvas ``.ics`` export into safe, database-independent records.

    The returned dictionaries contain only:

    ``event_id``, ``uid``, ``recurrence_id``, ``summary``, ``location``,
    ``course_label``, ``category``, ``date``, ``end_date``, ``start_time``,
    ``end_time``, ``duration_min``, ``is_all_day``, ``is_deadline``, and
    ``timezone`` (plus the fixed ``source`` marker).  In particular, no event
    descriptions, event URLs, calendar-feed URL, HTML, or raw source text is
    returned.

    Times with a timezone are converted to ``America/Chicago``.  Date-only
    events retain no clock time; their ``end_date`` is inclusive.  Components
    without both a UID and DTSTART are skipped, because they cannot be safely
    and idempotently imported later.
    """
    source = Path(path)
    size = source.stat().st_size
    if size > MAX_ICS_BYTES:
        raise CanvasICSParseError("Calendar export is too large to import safely.")

    try:
        calendar = Calendar.from_ical(source.read_bytes())
    except Exception as exc:  # icalendar has several parser-specific errors.
        raise CanvasICSParseError("Calendar export could not be parsed.") from exc

    components = list(calendar.walk("VEVENT"))
    if len(components) > MAX_EVENTS:
        raise CanvasICSParseError("Calendar export has too many events to import safely.")

    records = [record for component in components if (record := _record_from_event(component))]
    # A stable sort keeps dry-run previews and later importer behavior repeatable.
    return sorted(records, key=lambda record: (record["date"], record["start_time"] or "", record["event_id"]))
