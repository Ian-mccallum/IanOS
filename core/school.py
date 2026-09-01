"""Private, local-only academic records for the School command center.

Canvas is an input, never an agent tool.  This module keeps only the small
academic projection the product needs: course metadata, due-time metadata, and
the planner projection.  It deliberately has no fields for Canvas credentials,
assignment bodies, submissions, messages, grades, or calendar-feed URLs.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import re
import secrets
import sqlite3
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Iterable

from core import db, school_study


ROOT = Path(__file__).resolve().parent.parent
TERM = "Fall 2026"
CANVAS_PROVIDER = "canvas_ics"
SCHEDULE_PROVIDER = "school_schedule"
_WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_CLOCK_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

# SPEC-v32 Part C: a closed set of codes safe to persist in
# `school_sync_state.last_error`. These exist for the pre-parse network path
# (ingest/sync_canvas.py) — a fetch-level failure never reaches
# `import_canvas_items`, which already records its own attempt/success/error
# once bytes are in hand. A raw exception string or the feed URL must never
# reach this column, so callers pass one of these codes, never exception text.
SYNC_ERROR_CODES = frozenset({"network", "timeout", "http_4xx", "http_5xx", "parse", "too_large"})


def record_sync_attempt(conn, provider: str = CANVAS_PROVIDER) -> None:
    conn.execute(
        """INSERT INTO school_sync_state (provider, last_attempt) VALUES (?, ?)
           ON CONFLICT(provider) DO UPDATE SET last_attempt=excluded.last_attempt""",
        (provider, db.now()),
    )
    conn.commit()


def record_sync_failure(conn, error_code: str, provider: str = CANVAS_PROVIDER) -> None:
    if error_code not in SYNC_ERROR_CODES:
        raise ValueError(f"unsafe sync error code: {error_code!r}")
    conn.execute(
        "UPDATE school_sync_state SET last_error=? WHERE provider=?",
        (error_code, provider),
    )
    conn.commit()


SCHOOL_SCHEMA = """
CREATE TABLE IF NOT EXISTS school_courses (
    code                  TEXT PRIMARY KEY,
    term                  TEXT NOT NULL DEFAULT '',
    name                  TEXT NOT NULL,
    section               TEXT NOT NULL DEFAULT '',
    instructor            TEXT NOT NULL DEFAULT '',
    credits               REAL,
    aliases_json          TEXT NOT NULL DEFAULT '[]',
    meetings_json         TEXT NOT NULL DEFAULT '[]',
    grade_categories_json TEXT NOT NULL DEFAULT '[]',
    policy_json           TEXT NOT NULL DEFAULT '{}',
    source_ref            TEXT NOT NULL DEFAULT '',
    updated_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS school_items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code       TEXT NOT NULL REFERENCES school_courses(code) ON UPDATE CASCADE,
    provider          TEXT NOT NULL,
    external_item_id  TEXT NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'assignment',
    title             TEXT NOT NULL,
    due_at            TEXT,
    start_at          TEXT,
    end_at            TEXT,
    all_day           INTEGER NOT NULL DEFAULT 0,
    location          TEXT NOT NULL DEFAULT '',
    source_updated_at TEXT,
    source_kind       TEXT NOT NULL DEFAULT '',
    archived_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(provider, external_item_id)
);
CREATE INDEX IF NOT EXISTS idx_school_items_due
    ON school_items(archived_at, due_at, course_code);

-- Finishing homework is Ian's fact about his own work, not Canvas's, so it is
-- deliberately NOT a column on school_items. That table is owned by the
-- importer: `import_canvas_items` rewrites every row from the feed and
-- `_archive_missing_items` archives whatever the feed drops, so a completion
-- stored there would be erased by the next sync. Keying on the stable
-- (provider, external_item_id) identity instead means crossing something off
-- survives re-import, archive, and un-archive, the same write-boundary split
-- CLAUDE.md documents for leads (scraped columns refresh, Ian's columns never
-- do) and that school_calendar_projection already uses.
CREATE TABLE IF NOT EXISTS school_item_completions (
    provider         TEXT NOT NULL,
    external_item_id TEXT NOT NULL,
    completed_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (provider, external_item_id)
);

CREATE TABLE IF NOT EXISTS school_sync_state (
    provider       TEXT PRIMARY KEY,
    last_attempt   TEXT,
    last_success   TEXT,
    last_error     TEXT NOT NULL DEFAULT '',
    item_count     INTEGER NOT NULL DEFAULT 0
);

-- The generic calendar remains the only calendar consumed by Plan.  This
-- mapping lets a fresh academic snapshot update or remove only its own
-- projection without touching iCloud, Google, or manually imported events.
CREATE TABLE IF NOT EXISTS school_calendar_projection (
    provider         TEXT NOT NULL,
    external_item_id TEXT NOT NULL,
    calendar_event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
    PRIMARY KEY(provider, external_item_id)
);

-- School notes deliberately live beside the academic domain rather than in
-- generic `notes`.  The general notes model is agent-readable and stores a
-- deliberately narrow Markdown dialect; class sessions need a private,
-- schedule-linked rich-document contract instead.
CREATE TABLE IF NOT EXISTS school_note_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code       TEXT NOT NULL
                      REFERENCES school_courses(code) ON UPDATE CASCADE,
    school_item_id    INTEGER
                      REFERENCES school_items(id) ON DELETE RESTRICT,
    session_type      TEXT NOT NULL
                      CHECK (session_type IN ('meeting', 'async', 'study')),
    session_date      TEXT NOT NULL,
    title             TEXT NOT NULL DEFAULT '',
    document_version  INTEGER NOT NULL DEFAULT 1,
    document_json     TEXT NOT NULL
                      DEFAULT '{"type":"doc","content":[{"type":"paragraph"}]}' ,
    plain_text        TEXT NOT NULL DEFAULT '',
    revision          INTEGER NOT NULL DEFAULT 1,
    closed_at         TEXT,
    deleted_at        TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    CHECK (
        (session_type = 'meeting' AND school_item_id IS NOT NULL)
        OR (session_type IN ('async', 'study') AND school_item_id IS NULL)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_school_note_one_live_meeting
    ON school_note_sessions(school_item_id)
    WHERE school_item_id IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_school_note_one_live_manual_day
    ON school_note_sessions(course_code, session_date, session_type)
    WHERE school_item_id IS NULL AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_school_note_course_timeline
    ON school_note_sessions(course_code, session_date DESC, id DESC)
    WHERE deleted_at IS NULL;

-- A separate, private library for files that belong to a School course or a
-- particular daily note.  It intentionally has no relationship to generic
-- `notes` attachments: those are agent-readable inline images and have a
-- different lifecycle. `storage_path` is a server-owned relative key below
-- data/school/, never a client path and never a public API field.
CREATE TABLE IF NOT EXISTS school_note_assets (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code            TEXT NOT NULL
                           REFERENCES school_courses(code) ON UPDATE CASCADE,
    school_note_session_id INTEGER
                           REFERENCES school_note_sessions(id) ON DELETE SET NULL,
    token                  TEXT NOT NULL UNIQUE,
    display_name           TEXT NOT NULL,
    mime_type              TEXT NOT NULL,
    file_type              TEXT NOT NULL,
    extension              TEXT NOT NULL,
    byte_size              INTEGER NOT NULL CHECK (byte_size >= 0),
    category               TEXT NOT NULL DEFAULT 'material',
    storage_path           TEXT NOT NULL UNIQUE,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at             TEXT
);
CREATE INDEX IF NOT EXISTS idx_school_note_assets_course
    ON school_note_assets(course_code, deleted_at, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_school_note_assets_session
    ON school_note_assets(school_note_session_id, deleted_at, id DESC);

-- One local consent setting controls whether a user-requested note may reach
-- the configured study-model worker. It is deliberately separate from course
-- metadata and does not store a model token, a prompt, or note text.
CREATE TABLE IF NOT EXISTS school_ai_settings (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    enabled       INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    consented_at  TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- A study aid is a derived, revision-bound artifact—not a second copy of a
-- note. `output_json` holds only the strict, source-free projection accepted
-- from core.school_study; prompts, raw model replies, file bytes, and Canvas
-- identifiers are intentionally absent.
CREATE TABLE IF NOT EXISTS school_study_artifacts (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code            TEXT NOT NULL
                           REFERENCES school_courses(code) ON UPDATE CASCADE,
    school_note_session_id INTEGER NOT NULL
                           REFERENCES school_note_sessions(id) ON DELETE CASCADE,
    kind                   TEXT NOT NULL
                           CHECK (kind IN ('summary', 'flashcards', 'practice', 'study_plan')),
    source_note_revision   INTEGER NOT NULL CHECK (source_note_revision >= 1),
    template_version       INTEGER NOT NULL DEFAULT 1,
    model                  TEXT NOT NULL DEFAULT '',
    status                 TEXT NOT NULL DEFAULT 'QUEUED'
                           CHECK (status IN ('QUEUED', 'RUNNING', 'DRAFT', 'ACCEPTED',
                                             'DISCARDED', 'STALE', 'FAILED')),
    output_json            TEXT,
    error_code             TEXT NOT NULL DEFAULT '',
    accepted_at            TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_school_study_artifacts_session
    ON school_study_artifacts(school_note_session_id, created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_school_study_one_live_artifact
    ON school_study_artifacts(school_note_session_id, source_note_revision, kind)
    WHERE status IN ('QUEUED', 'RUNNING', 'DRAFT', 'ACCEPTED');
"""


def ensure_schema(conn) -> None:
    """Create the isolated academic schema without changing shared migrations."""
    conn.executescript(SCHOOL_SCHEMA)


SEASONS = ("term", "break")


def term_bounds(conn) -> tuple[str, str] | None:
    """The live instruction window as (start, end) ISO dates, derived from
    `school_items` due dates (SPEC-v37 6.2) rather than a hardcoded date --
    the min/max due_at of every non-archived item is the best signal this
    table carries for when a term is actually running. None with no school
    data at all (never imported, or between imports).

    `school_items` lives in SCHOOL_SCHEMA, created lazily via ensure_schema()
    rather than at db.connect() time (core/school.py's own module docstring),
    so a DB that has never touched a School route may not have the table yet
    -- current_situation() calls this on every nightly prompt for every role,
    so this must degrade to "no data" rather than crash the whole run.
    """
    try:
        row = conn.execute(
            "SELECT MIN(due_at), MAX(due_at) FROM school_items "
            "WHERE archived_at IS NULL AND due_at IS NOT NULL"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row or not row[0] or not row[1]:
        return None
    return row[0][:10], row[1][:10]


def current_season(conn, today: date) -> str:
    """'term' if `today` falls inside the live instruction window, else
    'break'. Genuinely derived, not a latch that can only ever go one way
    (Law A9's sibling: `pillars.term_active`'s old start-only bug is exactly
    the shape this must not repeat) -- no school data at all reads as
    'break', the safer default for a role gated `seasons: term`."""
    bounds = term_bounds(conn)
    if bounds is None:
        return "break"
    start, end = bounds
    try:
        return "term" if date.fromisoformat(start) <= today <= date.fromisoformat(end) else "break"
    except ValueError:
        return "break"


class SchoolNoteValidationError(ValueError):
    """A user-facing School-note input failed a local validation rule."""


class SchoolNoteNotFoundError(LookupError):
    """A requested School-note record or launch target does not exist."""


class SchoolNoteConflictError(RuntimeError):
    """A stale editor tried to replace a newer School-note document."""


class SchoolAssetValidationError(ValueError):
    """A School library file did not pass the private-file contract."""


class SchoolAssetNotFoundError(LookupError):
    """A requested private School library file does not exist."""


class SchoolStudyValidationError(ValueError):
    """An opt-in study request did not satisfy the private School contract."""


class SchoolStudyNotFoundError(LookupError):
    """A requested private School study artifact does not exist."""


_NOTE_SESSION_TYPES = frozenset({"meeting", "async", "study"})
_NOTE_DOCUMENT_VERSION = 1
_NOTE_DOCUMENT_MAX_BYTES = 512 * 1024
_NOTE_DOCUMENT_MAX_DEPTH = 32
_NOTE_DOCUMENT_MAX_NODES = 4000
_NOTE_PLAIN_TEXT_MAX = 80 * 1024
_EMPTY_NOTE_DOCUMENT = {"type": "doc", "content": [{"type": "paragraph"}]}
_NOTE_ALLOWED_NODES = frozenset({
    "doc", "paragraph", "text", "heading", "bulletList", "orderedList",
    "listItem", "taskList", "taskItem", "blockquote", "codeBlock",
    "hardBreak", "horizontalRule",
})
_NOTE_ALLOWED_MARKS = frozenset({"bold", "italic", "strike", "code"})


def _empty_note_document() -> dict:
    """Return a fresh document object, never the mutable module constant."""
    return json.loads(json.dumps(_EMPTY_NOTE_DOCUMENT))


def _document_text(value: object, *, depth: int = 0, state: dict | None = None) -> list[str]:
    """Validate a compact ProseMirror/Tiptap-shaped document and collect text.

    The editor is the primary schema wall, but API callers can bypass a browser.
    This small recursive gate prevents malformed/deep/unbounded JSON from being
    stored and gives search a server-derived text projection.  It intentionally
    does not accept raw HTML or external media URLs because School assets will
    get their own tokenized route in a later phase.
    """
    if state is None:
        state = {"nodes": 0}
    if depth > _NOTE_DOCUMENT_MAX_DEPTH:
        raise SchoolNoteValidationError("note document is nested too deeply")
    if not isinstance(value, dict):
        raise SchoolNoteValidationError("note document contains an invalid node")
    node_type = value.get("type")
    if not isinstance(node_type, str) or not node_type or len(node_type) > 64:
        raise SchoolNoteValidationError("note document contains an invalid node type")
    if node_type not in _NOTE_ALLOWED_NODES:
        raise SchoolNoteValidationError("note document uses an unsupported block")
    state["nodes"] += 1
    if state["nodes"] > _NOTE_DOCUMENT_MAX_NODES:
        raise SchoolNoteValidationError("note document has too many nodes")

    text: list[str] = []
    if "text" in value:
        node_text = value.get("text")
        if not isinstance(node_text, str):
            raise SchoolNoteValidationError("note document contains invalid text")
        text.append(node_text)

    attrs = value.get("attrs")
    if attrs is not None and not isinstance(attrs, dict):
        raise SchoolNoteValidationError("note document contains invalid attributes")
    if isinstance(attrs, dict):
        if node_type == "heading":
            if set(attrs) - {"level"} or attrs.get("level") not in {1, 2, 3, 4, 5, 6}:
                raise SchoolNoteValidationError("note heading is invalid")
        elif node_type == "taskItem":
            if set(attrs) - {"checked"} or not isinstance(attrs.get("checked"), bool):
                raise SchoolNoteValidationError("note checklist item is invalid")
        elif node_type == "codeBlock":
            language = attrs.get("language")
            if set(attrs) - {"language"} or (language is not None and not isinstance(language, str)):
                raise SchoolNoteValidationError("note code block is invalid")
        elif attrs:
            raise SchoolNoteValidationError("note document contains unsupported attributes")

    marks = value.get("marks", [])
    if marks is None:
        marks = []
    if not isinstance(marks, list):
        raise SchoolNoteValidationError("note document contains invalid formatting")
    for mark in marks:
        if not isinstance(mark, dict) or mark.get("type") not in _NOTE_ALLOWED_MARKS:
            raise SchoolNoteValidationError("note document contains unsupported formatting")
        if mark.get("attrs") not in (None, {}):
            raise SchoolNoteValidationError("note document contains invalid formatting")

    content = value.get("content", [])
    if content is None:
        content = []
    if not isinstance(content, list):
        raise SchoolNoteValidationError("note document contains invalid content")
    for child in content:
        text.extend(_document_text(child, depth=depth + 1, state=state))
        if isinstance(child, dict) and child.get("type") in {
            "paragraph", "heading", "blockquote", "listItem", "taskItem", "codeBlock",
        }:
            text.append("\n")
    return text


def _normalize_note_document(value: object | None) -> tuple[str, str]:
    """Return compact JSON plus a safe, derived plain-text search projection."""
    document = _empty_note_document() if value is None else value
    if not isinstance(document, dict) or document.get("type") != "doc":
        raise SchoolNoteValidationError("note document must have a doc root")
    try:
        encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise SchoolNoteValidationError("note document must be JSON") from exc
    if len(encoded.encode("utf-8")) > _NOTE_DOCUMENT_MAX_BYTES:
        raise SchoolNoteValidationError("note document is too large")
    text = "".join(_document_text(document)).strip()
    if len(text) > _NOTE_PLAIN_TEXT_MAX:
        raise SchoolNoteValidationError("note text is too large")
    return encoded, text


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _compact_json(value, fallback) -> str:
    if not isinstance(value, type(fallback)):
        value = fallback
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _clean_text(value: object, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def _local_iso(value: object) -> str | None:
    """Accept a local ISO date/time only, never convert a timezone here."""
    raw = _clean_text(value, 40)
    if not raw:
        return None
    # ``datetime.fromisoformat('2026-08-26')`` quietly creates midnight. For
    # syllabus milestones that would turn a date-only signal into a false
    # timed appointment, so preserve a pure ISO date before parsing datetimes.
    if "T" not in raw and " " not in raw:
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(raw).isoformat()
        except ValueError:
            return None
    # The importer has already converted Canvas values to Chicago local time.
    return parsed.replace(tzinfo=None).isoformat(timespec="minutes")


def _iso_date(value: object) -> date | None:
    """Return a calendar date from the small, local seed format only."""
    raw = _clean_text(value, 16)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _valid_clock(value: object) -> str | None:
    clock = _clean_text(value, 5)
    return clock if _CLOCK_RE.fullmatch(clock) else None


_SCHOOL_NOTE_SELECT = """
    SELECT n.*, c.name AS course_name,
           i.id AS meeting_id, i.kind AS meeting_kind, i.title AS meeting_title,
           i.start_at AS meeting_start_at, i.end_at AS meeting_end_at,
           i.location AS meeting_location
      FROM school_note_sessions n
      JOIN school_courses c ON c.code=n.course_code
      LEFT JOIN school_items i ON i.id=n.school_item_id
"""


def _school_note_row(row, *, include_document: bool = False) -> dict:
    """Expose a private School-note projection without provider/source fields."""
    data = dict(row)
    result = {
        "id": data["id"],
        "course_code": data["course_code"],
        "course_name": data["course_name"],
        "session_type": data["session_type"],
        "session_date": data["session_date"],
        "title": data["title"],
        "document_version": data["document_version"],
        "revision": data["revision"],
        "closed_at": data["closed_at"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
        "preview": data.get("plain_text", "")[:280],
        "meeting": None,
    }
    if data.get("meeting_id") is not None:
        result["meeting"] = {
            "id": data["meeting_id"],
            "kind": data["meeting_kind"],
            "title": data["meeting_title"],
            "start_at": data["meeting_start_at"],
            "end_at": data["meeting_end_at"],
            "location": data["meeting_location"],
        }
    if include_document:
        try:
            document = json.loads(data["document_json"])
        except (TypeError, ValueError):
            # A corrupt local row should not crash the School screen. The
            # table is private and only this module writes it, so callers can
            # still repair the safe empty document with their next autosave.
            document = _empty_note_document()
        result["document"] = document
        result["plain_text"] = data.get("plain_text", "")
    return result


def _school_note_session(conn, session_id: int, *, include_document: bool = False,
                         include_deleted: bool = False) -> dict | None:
    where = "n.id=?" if include_deleted else "n.id=? AND n.deleted_at IS NULL"
    row = conn.execute(_SCHOOL_NOTE_SELECT + f" WHERE {where}", (int(session_id),)).fetchone()
    return _school_note_row(row, include_document=include_document) if row else None


def _ensure_school_course(conn, course_code: object) -> dict:
    code = _clean_text(course_code, 32)
    row = conn.execute("SELECT code, name FROM school_courses WHERE code=?", (code,)).fetchone()
    if row is None:
        raise SchoolNoteNotFoundError("course not found")
    return dict(row)


def _school_note_title(course_code: str, session_type: str, session_date: str,
                       meeting_kind: str | None = None) -> str:
    try:
        display_date = date.fromisoformat(session_date).strftime("%a, %b %-d")
    except ValueError:
        display_date = session_date
    label = (meeting_kind if session_type == "meeting" else session_type).replace("_", " ").title()
    return f"{course_code} · {label} · {display_date}"


def _school_note_launch_row(row) -> dict:
    """Safe, meeting-only launch payload shared by School and Plan."""
    data = dict(row)
    return {
        "school_item_id": data["school_item_id"],
        "calendar_event_id": data.get("calendar_event_id"),
        "course_code": data["course_code"],
        "course_name": data["course_name"],
        "kind": data["kind"],
        "title": data["title"],
        "start_at": data["start_at"],
        "end_at": data["end_at"],
        "location": data["location"],
        "existing_session_id": data.get("existing_session_id"),
        "closed_at": data.get("closed_at"),
    }


def note_launches_for_date(conn, session_date: object) -> list[dict]:
    """Verified live meetings on one local date, never Canvas shells/items."""
    ensure_schema(conn)
    parsed = _iso_date(session_date)
    if parsed is None:
        raise SchoolNoteValidationError("date must be YYYY-MM-DD")
    rows = conn.execute(
        """SELECT i.id AS school_item_id, i.course_code, c.name AS course_name,
                  i.kind, i.title, i.start_at, i.end_at, i.location,
                  p.calendar_event_id, n.id AS existing_session_id, n.closed_at
             FROM school_items i
             JOIN school_courses c ON c.code=i.course_code
             LEFT JOIN school_calendar_projection p
                    ON p.provider=i.provider AND p.external_item_id=i.external_item_id
             LEFT JOIN school_note_sessions n
                    ON n.school_item_id=i.id AND n.deleted_at IS NULL
            WHERE i.provider=? AND i.archived_at IS NULL
              AND substr(i.start_at, 1, 10)=?
            ORDER BY i.start_at, i.course_code, i.id""",
        (SCHEDULE_PROVIDER, parsed.isoformat()),
    ).fetchall()
    return [_school_note_launch_row(row) for row in rows]


def next_note_launches(conn, *, from_date: object | None = None, limit: int = 24) -> list[dict]:
    """Small forward-looking schedule projection for the School command center."""
    ensure_schema(conn)
    parsed = _iso_date(from_date) if from_date is not None else date.today()
    if parsed is None:
        raise SchoolNoteValidationError("date must be YYYY-MM-DD")
    safe_limit = max(1, min(int(limit), 60))
    rows = conn.execute(
        """SELECT i.id AS school_item_id, i.course_code, c.name AS course_name,
                  i.kind, i.title, i.start_at, i.end_at, i.location,
                  p.calendar_event_id, n.id AS existing_session_id, n.closed_at
             FROM school_items i
             JOIN school_courses c ON c.code=i.course_code
             LEFT JOIN school_calendar_projection p
                    ON p.provider=i.provider AND p.external_item_id=i.external_item_id
             LEFT JOIN school_note_sessions n
                    ON n.school_item_id=i.id AND n.deleted_at IS NULL
            WHERE i.provider=? AND i.archived_at IS NULL
              AND i.start_at >= ?
            ORDER BY i.start_at, i.course_code, i.id
            LIMIT ?""",
        (SCHEDULE_PROVIDER, f"{parsed.isoformat()}T00:00", safe_limit),
    ).fetchall()
    return [_school_note_launch_row(row) for row in rows]


def note_launches_for_calendar_events(conn, calendar_event_ids: Iterable[object]) -> dict[int, dict]:
    """Resolve Plan commitment ids to verified School-note launch metadata.

    Plan owns generic calendar events and must not parse titles or reconstruct
    weekly recurrences in the browser.  This server-side bridge exposes only
    actual schedule projections, never Canvas shells or opaque provider ids.
    """
    ensure_schema(conn)
    ids: list[int] = []
    for value in calendar_event_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in ids:
            ids.append(parsed)
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""SELECT i.id AS school_item_id, i.course_code, c.name AS course_name,
                   i.kind, i.title, i.start_at, i.end_at, i.location,
                   p.calendar_event_id, n.id AS existing_session_id, n.closed_at
              FROM school_calendar_projection p
              JOIN school_items i
                    ON i.provider=p.provider AND i.external_item_id=p.external_item_id
              JOIN school_courses c ON c.code=i.course_code
              LEFT JOIN school_note_sessions n
                    ON n.school_item_id=i.id AND n.deleted_at IS NULL
             WHERE p.provider=? AND i.provider=? AND i.archived_at IS NULL
               AND p.calendar_event_id IN ({placeholders})""",
        (SCHEDULE_PROVIDER, SCHEDULE_PROVIDER, *ids),
    ).fetchall()
    return {
        int(row["calendar_event_id"]): _school_note_launch_row(row)
        for row in rows
    }


def open_note_session(conn, school_item_id: int) -> tuple[dict, bool]:
    """Idempotently open the one note attached to a verified meeting occurrence."""
    ensure_schema(conn)
    try:
        item_id = int(school_item_id)
    except (TypeError, ValueError) as exc:
        raise SchoolNoteValidationError("school_item_id must be an integer") from exc
    row = conn.execute(
        """SELECT i.*, c.code AS course_code
             FROM school_items i JOIN school_courses c ON c.code=i.course_code
            WHERE i.id=? AND i.provider=? AND i.archived_at IS NULL""",
        (item_id, SCHEDULE_PROVIDER),
    ).fetchone()
    if row is None:
        raise SchoolNoteNotFoundError("verified class meeting not found")
    item = dict(row)
    session_date = _iso_date(item.get("start_at"))
    if session_date is None or not _valid_clock((item.get("start_at") or "")[11:16]):
        raise SchoolNoteValidationError("class meeting has no usable local time")

    existing = _school_note_session_for_meeting(conn, item_id)
    if existing is not None:
        return existing, False

    title = _school_note_title(item["course_code"], "meeting", session_date.isoformat(), item.get("kind"))
    document_json, plain_text = _normalize_note_document(None)
    # The partial unique index is the real duplicate-tap guard. INSERT OR
    # IGNORE makes concurrent laptop/phone opens resolve to the same session.
    inserted = conn.execute(
        """INSERT OR IGNORE INTO school_note_sessions
               (course_code, school_item_id, session_type, session_date, title,
                document_version, document_json, plain_text)
            VALUES (?,?,?,?,?,?,?,?)""",
        (item["course_code"], item_id, "meeting", session_date.isoformat(), title,
         _NOTE_DOCUMENT_VERSION, document_json, plain_text),
    )
    conn.commit()
    session = _school_note_session_for_meeting(conn, item_id)
    if session is None:
        raise SchoolNoteNotFoundError("could not open class note")
    # A phone and laptop can both reach this point after the first SELECT.
    # The partial unique index chooses the winner; report accurately whether
    # this caller made the row rather than treating every race as a new note.
    return session, inserted.rowcount == 1


def _school_note_session_for_meeting(conn, school_item_id: int) -> dict | None:
    row = conn.execute(
        _SCHOOL_NOTE_SELECT + " WHERE n.school_item_id=? AND n.deleted_at IS NULL",
        (int(school_item_id),),
    ).fetchone()
    return _school_note_row(row, include_document=True) if row else None


def open_manual_note_session(conn, course_code: object, session_type: object,
                             session_date: object | None = None) -> tuple[dict, bool]:
    """Open one weekly async workspace, never a fake class meeting."""
    ensure_schema(conn)
    course = _ensure_school_course(conn, course_code)
    kind = _clean_text(session_type, 16).casefold()
    if kind != "async":
        raise SchoolNoteValidationError("session_type must be async")
    meetings = _json(conn.execute(
        "SELECT meetings_json FROM school_courses WHERE code=?", (course["code"],)
    ).fetchone()[0], [])
    if any(isinstance(meeting, dict) and meeting.get("days") for meeting in meetings):
        raise SchoolNoteValidationError("scheduled courses need a verified class meeting")
    parsed = _iso_date(session_date) if session_date is not None else date.today()
    if parsed is None:
        raise SchoolNoteValidationError("date must be YYYY-MM-DD")
    # ANTH is accelerated but asynchronous: its meaningful daily-note unit is
    # a week of work, not an invented nightly class. A client cannot produce
    # seven duplicate workspaces by changing only the supplied date.
    parsed -= timedelta(days=parsed.weekday())
    existing_row = conn.execute(
        _SCHOOL_NOTE_SELECT
        + " WHERE n.course_code=? AND n.session_type=? AND n.session_date=? AND n.deleted_at IS NULL",
        (course["code"], kind, parsed.isoformat()),
    ).fetchone()
    if existing_row:
        return _school_note_row(existing_row, include_document=True), False
    document_json, plain_text = _normalize_note_document(None)
    title = _school_note_title(course["code"], kind, parsed.isoformat())
    inserted = conn.execute(
        """INSERT OR IGNORE INTO school_note_sessions
               (course_code, school_item_id, session_type, session_date, title,
                document_version, document_json, plain_text)
            VALUES (?,?,?,?,?,?,?,?)""",
        (course["code"], None, kind, parsed.isoformat(), title,
         _NOTE_DOCUMENT_VERSION, document_json, plain_text),
    )
    conn.commit()
    row = conn.execute(
        _SCHOOL_NOTE_SELECT
        + " WHERE n.course_code=? AND n.session_type=? AND n.session_date=? AND n.deleted_at IS NULL",
        (course["code"], kind, parsed.isoformat()),
    ).fetchone()
    if row is None:
        raise SchoolNoteNotFoundError("could not open course workspace")
    return _school_note_row(row, include_document=True), inserted.rowcount == 1


def school_note_session(conn, session_id: int, *, include_document: bool = True) -> dict | None:
    ensure_schema(conn)
    return _school_note_session(conn, session_id, include_document=include_document)


def list_note_sessions(conn, course_code: object, *, q: object = "", limit: int = 160) -> list[dict]:
    """Return one course's timeline cards, intentionally without full docs."""
    ensure_schema(conn)
    course = _ensure_school_course(conn, course_code)
    query = _clean_text(q, 160)
    safe_limit = max(1, min(int(limit), 250))
    where = ["n.course_code=?", "n.deleted_at IS NULL"]
    params: list[object] = [course["code"]]
    if query:
        where.append("(n.title LIKE ? OR n.plain_text LIKE ?)")
        params.extend([f"%{query}%", f"%{query}%"])
    rows = conn.execute(
        _SCHOOL_NOTE_SELECT
        + f" WHERE {' AND '.join(where)} ORDER BY n.session_date DESC, n.id DESC LIMIT ?",
        (*params, safe_limit),
    ).fetchall()
    return [_school_note_row(row, include_document=False) for row in rows]


_SCHOOL_NOTE_UNSET = object()


def update_note_session(conn, session_id: int, *, document=_SCHOOL_NOTE_UNSET,
                        title=_SCHOOL_NOTE_UNSET, expected_revision: int | None = None) -> dict:
    """Autosave one School document with explicit stale-write protection."""
    ensure_schema(conn)
    row = conn.execute(
        _SCHOOL_NOTE_SELECT + " WHERE n.id=? AND n.deleted_at IS NULL", (int(session_id),)
    ).fetchone()
    if row is None:
        raise SchoolNoteNotFoundError("class note not found")
    current = dict(row)
    if expected_revision is None:
        raise SchoolNoteValidationError("expected_revision is required when saving a note")
    if int(expected_revision) != int(current["revision"]):
        raise SchoolNoteConflictError("this note changed elsewhere; reload before saving")

    fields: dict[str, object] = {}
    if title is not _SCHOOL_NOTE_UNSET:
        clean_title = _clean_text(title, 180)
        if not clean_title:
            raise SchoolNoteValidationError("note title cannot be empty")
        # Only a real change counts, exactly as the document branch below
        # already does. Without this, re-sending an identical title still bumps
        # `revision` and therefore marks every ACCEPTED study aid for this note
        # STALE, so a no-op save quietly destroyed derived work.
        if clean_title != current["title"]:
            fields["title"] = clean_title
    if document is not _SCHOOL_NOTE_UNSET:
        encoded, plain_text = _normalize_note_document(document)
        if encoded != current["document_json"]:
            fields["document_json"] = encoded
            fields["plain_text"] = plain_text
    if fields:
        # Every mutation gets a new revision, including a future title-only
        # edit. The UPDATE itself is a compare-and-swap: reading revision 1
        # and later writing without this WHERE clause would let two devices
        # both claim revision 2 and silently lose one document.
        fields["revision"] = int(current["revision"]) + 1
        assigns = ", ".join(f"{column}=?" for column in fields)
        cursor = conn.execute(
            f"""UPDATE school_note_sessions SET {assigns}, updated_at=datetime('now', 'localtime')
                WHERE id=? AND deleted_at IS NULL AND revision=?""",
            (*fields.values(), int(session_id), int(expected_revision)),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            raise SchoolNoteConflictError("this note changed elsewhere; reload before saving")
        # Artifacts carry the exact note revision that produced them. Every
        # mutation gets a revision (including a title change), so invalidate
        # every prior-revision aid in the same transaction rather than let a
        # UI present it as current after an edit or a racing worker response.
        _stale_school_study_artifacts_for_note(
            conn, int(session_id), int(fields["revision"]),
        )
        conn.commit()
    saved = _school_note_session(conn, session_id, include_document=True)
    if saved is None:
        raise SchoolNoteNotFoundError("class note not found")
    return saved


def close_note_session(conn, session_id: int) -> dict:
    """Mark a class note wrapped without generating any AI output or plan work."""
    ensure_schema(conn)
    if _school_note_session(conn, session_id, include_document=False) is None:
        raise SchoolNoteNotFoundError("class note not found")
    conn.execute(
        """UPDATE school_note_sessions
              SET closed_at=COALESCE(closed_at, datetime('now', 'localtime')),
                  updated_at=datetime('now', 'localtime')
            WHERE id=? AND deleted_at IS NULL""",
        (int(session_id),),
    )
    conn.commit()
    saved = _school_note_session(conn, session_id, include_document=True)
    if saved is None:
        raise SchoolNoteNotFoundError("class note not found")
    return saved


# -------------------------------------------------------- private study aids
# Study artifacts are explicitly requested, generated outside this data layer,
# and always tied to the exact saved note revision used as their source. This
# module stores no prompt, model transcript, Canvas material, or file content.

_SCHOOL_STUDY_TEMPLATE_VERSION = 1
_SCHOOL_STUDY_LIVE_STATUSES = frozenset({"QUEUED", "RUNNING", "DRAFT", "ACCEPTED"})
_SCHOOL_STUDY_VISIBLE_OUTPUT_STATUSES = frozenset({"DRAFT", "ACCEPTED"})
_SCHOOL_STUDY_DISCARDABLE_STATUSES = frozenset({"DRAFT", "ACCEPTED", "STALE", "FAILED"})
_SCHOOL_STUDY_SAFE_ERROR_CODES = frozenset({"runner_error", "invalid_reply"})


def _school_study_artifact_id(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchoolStudyValidationError("study artifact id must be an integer") from exc
    if parsed < 1:
        raise SchoolStudyValidationError("study artifact id must be positive")
    return parsed


def _school_study_kind(value: object) -> str:
    kind = _clean_text(value, 32)
    if kind not in school_study.STUDY_KINDS:
        raise SchoolStudyValidationError("unknown study aid kind")
    return kind


def _school_course_blocks_study(conn, course_code: str) -> bool:
    """Keep an explicit course-level prohibition server-enforced, not UI-only."""
    row = conn.execute(
        "SELECT policy_json FROM school_courses WHERE code=?", (course_code,)
    ).fetchone()
    policy = _json(row["policy_json"], {}) if row is not None else {}
    ai_policy = policy.get("ai_policy") if isinstance(policy, dict) else {}
    return isinstance(ai_policy, dict) and ai_policy.get("status") == "prohibited"


def _school_ai_settings_row(row) -> dict:
    data = dict(row) if row is not None else {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "consented_at": data.get("consented_at"),
        "updated_at": data.get("updated_at"),
    }


def school_ai_settings(conn) -> dict:
    """Return only the local study-mode consent projection."""
    ensure_schema(conn)
    row = conn.execute("SELECT * FROM school_ai_settings WHERE id=1").fetchone()
    return _school_ai_settings_row(row)


def set_school_ai_enabled(conn, enabled: object) -> dict:
    """Enable/disable future explicit study requests without touching notes.

    Turning it off prevents queued work from starting and prevents a currently
    running worker from saving its reply. We do not delete already accepted or
    draft aids: they are Ian's existing derived work, not credentials.
    """
    ensure_schema(conn)
    if not isinstance(enabled, bool):
        raise SchoolStudyValidationError("enabled must be true or false")
    conn.execute(
        """INSERT INTO school_ai_settings (id, enabled, consented_at)
           VALUES (1, ?, CASE WHEN ? THEN datetime('now', 'localtime') ELSE NULL END)
           ON CONFLICT(id) DO UPDATE SET
               enabled=excluded.enabled,
               consented_at=CASE WHEN excluded.enabled=1
                                 THEN COALESCE(school_ai_settings.consented_at, datetime('now', 'localtime'))
                                 ELSE school_ai_settings.consented_at END,
               updated_at=datetime('now', 'localtime')""",
        (int(enabled), int(enabled)),
    )
    if not enabled:
        # A request already sent to the provider cannot be recalled, but it
        # cannot become a visible/saved result after study mode is disabled.
        conn.execute(
            """UPDATE school_study_artifacts
                  SET status='DISCARDED', updated_at=datetime('now', 'localtime')
                WHERE status IN ('QUEUED', 'RUNNING')"""
        )
    conn.commit()
    return school_ai_settings(conn)


def _school_study_artifact_row(row) -> dict:
    """Return a source-free browser projection of a study artifact."""
    data = dict(row)
    status = str(data.get("status") or "").upper()
    output = None
    if status in _SCHOOL_STUDY_VISIBLE_OUTPUT_STATUSES and data.get("output_json"):
        try:
            parsed = json.loads(data["output_json"])
            output = parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            output = None
    return {
        "id": data["id"],
        "course_code": data["course_code"],
        "session_id": data["school_note_session_id"],
        "kind": data["kind"],
        "source_note_revision": data["source_note_revision"],
        "template_version": data["template_version"],
        "status": status,
        "output": output,
        "error_code": data["error_code"] if status == "FAILED" else "",
        "accepted_at": data["accepted_at"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _school_study_artifact_db_row(conn, artifact_id: object):
    return conn.execute(
        "SELECT * FROM school_study_artifacts WHERE id=?",
        (_school_study_artifact_id(artifact_id),),
    ).fetchone()


def _stale_school_study_artifacts_for_note(conn, session_id: int, revision: int) -> None:
    """Label prior-revision results without modifying the source note itself."""
    conn.execute(
        """UPDATE school_study_artifacts
              SET status='STALE', updated_at=datetime('now', 'localtime')
            WHERE school_note_session_id=? AND source_note_revision<>?
              AND status IN ('QUEUED', 'RUNNING', 'DRAFT', 'ACCEPTED')""",
        (int(session_id), int(revision)),
    )


def create_school_study_artifact(conn, session_id: object, kind: object, *, model: str = "") -> tuple[dict, bool]:
    """Queue an aid from one saved note revision, deduping live double-taps."""
    ensure_schema(conn)
    if not school_ai_settings(conn)["enabled"]:
        raise SchoolStudyValidationError("enable study mode before requesting a study aid")
    parsed_id = _school_study_artifact_id(session_id)
    clean_kind = _school_study_kind(kind)
    session = _school_note_session(conn, parsed_id, include_document=True)
    if session is None:
        raise SchoolNoteNotFoundError("class note not found")
    if _school_course_blocks_study(conn, session["course_code"]):
        raise SchoolStudyValidationError("study tools are not permitted for this course")
    # The plain-text projection is server-derived during autosave. A blank
    # document is not useful model context and must never become a filler prompt.
    if not str(session.get("plain_text") or "").strip():
        raise SchoolStudyValidationError("add saved note text before requesting a study aid")
    clean_model = _clean_text(model, 120)
    try:
        cursor = conn.execute(
            """INSERT INTO school_study_artifacts
                   (course_code, school_note_session_id, kind, source_note_revision,
                    template_version, model, status)
               VALUES (?,?,?,?,?,?, 'QUEUED')""",
            (
                session["course_code"], parsed_id, clean_kind, int(session["revision"]),
                _SCHOOL_STUDY_TEMPLATE_VERSION, clean_model,
            ),
        )
    except sqlite3.IntegrityError as exc:
        # The partial unique index is intentional idempotency for a second
        # browser/device tap. It never converts a persistence error into a
        # mysterious new request.
        if "idx_school_study_one_live_artifact" not in str(exc) and "UNIQUE constraint failed" not in str(exc):
            raise
        row = conn.execute(
            """SELECT * FROM school_study_artifacts
                 WHERE school_note_session_id=? AND source_note_revision=? AND kind=?
                   AND status IN ('QUEUED', 'RUNNING', 'DRAFT', 'ACCEPTED')
                 ORDER BY id DESC LIMIT 1""",
            (parsed_id, int(session["revision"]), clean_kind),
        ).fetchone()
        if row is None:
            raise
        return _school_study_artifact_row(row), False
    conn.commit()
    row = _school_study_artifact_db_row(conn, cursor.lastrowid)
    if row is None:
        raise SchoolStudyNotFoundError("could not create study aid")
    return _school_study_artifact_row(row), True


def list_school_study_artifacts(conn, session_id: object, *, limit: int = 60) -> list[dict]:
    """List source-free study aid history for exactly one private note."""
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(session_id)
    if _school_note_session(conn, parsed_id, include_document=False) is None:
        raise SchoolNoteNotFoundError("class note not found")
    safe_limit = max(1, min(int(limit), 100))
    rows = conn.execute(
        """SELECT * FROM school_study_artifacts
             WHERE school_note_session_id=?
             ORDER BY created_at DESC, id DESC LIMIT ?""",
        (parsed_id, safe_limit),
    ).fetchall()
    return [_school_study_artifact_row(row) for row in rows]


def claim_school_study_artifact(conn, artifact_id: object) -> dict | None:
    """Atomically claim one queued artifact and return minimal worker input.

    The returned note text is private worker input only. It must never be
    passed into a browser projection, agent tool, log, or exception message.
    """
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(artifact_id)
    cursor = conn.execute(
        """UPDATE school_study_artifacts
              SET status='RUNNING', updated_at=datetime('now', 'localtime')
            WHERE id=? AND status='QUEUED'
              AND EXISTS (SELECT 1 FROM school_ai_settings WHERE id=1 AND enabled=1)""",
        (parsed_id,),
    )
    if cursor.rowcount != 1:
        conn.commit()
        return None
    row = conn.execute(
        """SELECT a.id, a.kind, a.school_note_session_id, a.source_note_revision, a.model,
                  n.plain_text, n.revision AS current_note_revision
             FROM school_study_artifacts a
             JOIN school_note_sessions n ON n.id=a.school_note_session_id
            WHERE a.id=? AND n.deleted_at IS NULL""",
        (parsed_id,),
    ).fetchone()
    conn.commit()
    if row is None:
        # The note was soft-deleted between queueing and claiming. The UPDATE
        # above already committed status='RUNNING', so returning here without
        # a terminal status would strand the row: the worker takes the None as
        # "nothing to do" and never touches it again, and because the
        # one-live-artifact index counts RUNNING, that (session, revision,
        # kind) slot stays blocked until an API restart sweeps it. Terminalize
        # it here instead of relying on recovery at boot.
        conn.execute(
            """UPDATE school_study_artifacts
                  SET status='DISCARDED', updated_at=datetime('now', 'localtime')
                WHERE id=? AND status='RUNNING'""",
            (parsed_id,),
        )
        conn.commit()
        return None
    if int(row["current_note_revision"]) != int(row["source_note_revision"]):
        _stale_school_study_artifacts_for_note(
            conn, int(row["school_note_session_id"]), int(row["current_note_revision"]),
        )
        conn.commit()
        return None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "source_note_revision": row["source_note_revision"],
        "model": row["model"],
        "plain_text": row["plain_text"],
    }


def complete_school_study_artifact(conn, artifact_id: object, output: dict) -> dict | None:
    """Save one validated worker output only if its source note still matches."""
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(artifact_id)
    row = conn.execute(
        """SELECT a.*, n.revision AS current_note_revision
             FROM school_study_artifacts a
             JOIN school_note_sessions n ON n.id=a.school_note_session_id
            WHERE a.id=? AND n.deleted_at IS NULL""",
        (parsed_id,),
    ).fetchone()
    if row is None:
        return None
    data = dict(row)
    if data["status"] != "RUNNING":
        return _school_study_artifact_row(row)
    if int(data["current_note_revision"]) != int(data["source_note_revision"]):
        _stale_school_study_artifacts_for_note(
            conn, int(data["school_note_session_id"]), int(data["current_note_revision"]),
        )
        conn.commit()
        refreshed = _school_study_artifact_db_row(conn, parsed_id)
        return _school_study_artifact_row(refreshed) if refreshed is not None else None
    if not school_ai_settings(conn)["enabled"]:
        conn.execute(
            """UPDATE school_study_artifacts
                  SET status='DISCARDED', updated_at=datetime('now', 'localtime')
                WHERE id=? AND status='RUNNING'""",
            (parsed_id,),
        )
        conn.commit()
        refreshed = _school_study_artifact_db_row(conn, parsed_id)
        return _school_study_artifact_row(refreshed) if refreshed is not None else None
    # The worker normally validates before it reaches this method, but the
    # persistence wall validates again so no internal caller can store a raw
    # model reply, an answer key, or an unexpected JSON field.
    validated = school_study.normalize_study_output(str(data["kind"]), output)
    encoded = _compact_json(validated, {})
    cursor = conn.execute(
        """UPDATE school_study_artifacts
              SET status='DRAFT', output_json=?, error_code='',
                  updated_at=datetime('now', 'localtime')
            WHERE id=? AND status='RUNNING'""",
        (encoded, parsed_id),
    )
    conn.commit()
    if cursor.rowcount != 1:
        return None
    refreshed = _school_study_artifact_db_row(conn, parsed_id)
    return _school_study_artifact_row(refreshed) if refreshed is not None else None


def fail_school_study_artifact(conn, artifact_id: object, error_code: object) -> dict | None:
    """Terminalize a worker failure with a closed, non-sensitive error code."""
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(artifact_id)
    code = _clean_text(error_code, 48)
    if code not in _SCHOOL_STUDY_SAFE_ERROR_CODES:
        code = "runner_error"
    conn.execute(
        """UPDATE school_study_artifacts
              SET status='FAILED', error_code=?, updated_at=datetime('now', 'localtime')
            WHERE id=? AND status='RUNNING'""",
        (code, parsed_id),
    )
    conn.commit()
    row = _school_study_artifact_db_row(conn, parsed_id)
    return _school_study_artifact_row(row) if row is not None else None


def accept_school_study_artifact(conn, artifact_id: object) -> dict:
    """Keep a draft only while it still belongs to the current note revision."""
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(artifact_id)
    row = conn.execute(
        """SELECT a.*, n.revision AS current_note_revision
             FROM school_study_artifacts a
             JOIN school_note_sessions n ON n.id=a.school_note_session_id
            WHERE a.id=? AND n.deleted_at IS NULL""",
        (parsed_id,),
    ).fetchone()
    if row is None:
        raise SchoolStudyNotFoundError("study aid not found")
    data = dict(row)
    if data["status"] == "DRAFT" and int(data["current_note_revision"]) == int(data["source_note_revision"]):
        conn.execute(
            """UPDATE school_study_artifacts
                  SET status='ACCEPTED', accepted_at=datetime('now', 'localtime'),
                      updated_at=datetime('now', 'localtime')
                WHERE id=? AND status='DRAFT'""",
            (parsed_id,),
        )
        conn.commit()
    elif data["status"] == "DRAFT":
        _stale_school_study_artifacts_for_note(
            conn, int(data["school_note_session_id"]), int(data["current_note_revision"]),
        )
        conn.commit()
    refreshed = _school_study_artifact_db_row(conn, parsed_id)
    if refreshed is None:
        raise SchoolStudyNotFoundError("study aid not found")
    return _school_study_artifact_row(refreshed)


def discard_school_study_artifact(conn, artifact_id: object) -> dict:
    """Discard a derived aid without ever modifying its source note or Plan."""
    ensure_schema(conn)
    parsed_id = _school_study_artifact_id(artifact_id)
    row = _school_study_artifact_db_row(conn, parsed_id)
    if row is None:
        raise SchoolStudyNotFoundError("study aid not found")
    if row["status"] in _SCHOOL_STUDY_DISCARDABLE_STATUSES:
        conn.execute(
            """UPDATE school_study_artifacts
                  SET status='DISCARDED', output_json=NULL, error_code='',
                      updated_at=datetime('now', 'localtime')
                WHERE id=?""",
            (parsed_id,),
        )
        conn.commit()
    refreshed = _school_study_artifact_db_row(conn, parsed_id)
    if refreshed is None:
        raise SchoolStudyNotFoundError("study aid not found")
    return _school_study_artifact_row(refreshed)


def recover_school_study_artifacts(conn) -> int:
    """Fail interrupted local workers rather than replaying note text on boot."""
    ensure_schema(conn)
    cursor = conn.execute(
        """UPDATE school_study_artifacts
              SET status='FAILED', error_code='runner_error',
                  updated_at=datetime('now', 'localtime')
            WHERE status IN ('QUEUED', 'RUNNING')"""
    )
    conn.commit()
    return max(0, int(cursor.rowcount))


# ------------------------------------------------------ private school assets
# School materials are deliberately a separate library from generic Notes'
# inline images.  A course can hold a file (syllabus, slides, reading) without
# attaching it to any one note session, while a daily note may optionally own a
# narrower file.  Neither the raw storage key nor the opaque token crosses a
# public projection.

_SCHOOL_ASSET_MAX_BYTES = 25 * 1024 * 1024
_SCHOOL_ASSET_TOKEN_MINT_TRIES = 12
_SCHOOL_ASSET_NAME_MAX = 180
_SCHOOL_ASSET_STORAGE_KEY_MAX = 320
_SCHOOL_ASSET_CATEGORIES = frozenset({
    "material", "syllabus", "slides", "reading", "assignment", "reference", "other",
})

# Extension and MIME must agree.  SVG, HTML, executables, archive bundles, and
# macro-enabled Office extensions are intentionally absent.  A forced download
# still gets `nosniff` at the route layer, but the narrow allowlist makes a
# misleading content type insufficient to store an arbitrary program here.
_SCHOOL_ASSET_SPECS = {
    "pdf": {
        "mime_type": "application/pdf",
        "mime_types": frozenset({"application/pdf"}),
        "file_type": "pdf",
    },
    "jpg": {
        "mime_type": "image/jpeg",
        "mime_types": frozenset({"image/jpeg"}),
        "file_type": "image",
    },
    "jpeg": {
        "mime_type": "image/jpeg",
        "mime_types": frozenset({"image/jpeg"}),
        "file_type": "image",
    },
    "png": {
        "mime_type": "image/png",
        "mime_types": frozenset({"image/png"}),
        "file_type": "image",
    },
    "gif": {
        "mime_type": "image/gif",
        "mime_types": frozenset({"image/gif"}),
        "file_type": "image",
    },
    "webp": {
        "mime_type": "image/webp",
        "mime_types": frozenset({"image/webp"}),
        "file_type": "image",
    },
    "heic": {
        "mime_type": "image/heic",
        "mime_types": frozenset({"image/heic", "image/heif"}),
        "file_type": "image",
    },
    "heif": {
        "mime_type": "image/heif",
        "mime_types": frozenset({"image/heif", "image/heic"}),
        "file_type": "image",
    },
    "bmp": {
        "mime_type": "image/bmp",
        "mime_types": frozenset({"image/bmp"}),
        "file_type": "image",
    },
    "tif": {
        "mime_type": "image/tiff",
        "mime_types": frozenset({"image/tiff"}),
        "file_type": "image",
    },
    "tiff": {
        "mime_type": "image/tiff",
        "mime_types": frozenset({"image/tiff"}),
        "file_type": "image",
    },
    "doc": {
        "mime_type": "application/msword",
        "mime_types": frozenset({"application/msword"}),
        "file_type": "document",
    },
    "docx": {
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "mime_types": frozenset({
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }),
        "file_type": "document",
    },
    "ppt": {
        "mime_type": "application/vnd.ms-powerpoint",
        "mime_types": frozenset({"application/vnd.ms-powerpoint"}),
        "file_type": "presentation",
    },
    "pptx": {
        "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "mime_types": frozenset({
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }),
        "file_type": "presentation",
    },
    "xls": {
        "mime_type": "application/vnd.ms-excel",
        "mime_types": frozenset({"application/vnd.ms-excel"}),
        "file_type": "spreadsheet",
    },
    "xlsx": {
        "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "mime_types": frozenset({
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
        "file_type": "spreadsheet",
    },
    "txt": {
        "mime_type": "text/plain",
        "mime_types": frozenset({"text/plain"}),
        "file_type": "text",
    },
    "md": {
        "mime_type": "text/markdown",
        "mime_types": frozenset({"text/markdown", "text/x-markdown"}),
        "file_type": "text",
    },
    "markdown": {
        "mime_type": "text/markdown",
        "mime_types": frozenset({"text/markdown", "text/x-markdown"}),
        "file_type": "text",
    },
}

_SCHOOL_ASSET_OLE_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SCHOOL_ASSET_OOXML_MARKERS = {
    "docx": "word/document.xml",
    "pptx": "ppt/presentation.xml",
    "xlsx": "xl/workbook.xml",
}


def _school_asset_id(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchoolAssetValidationError("school file id must be an integer") from exc
    if parsed < 1:
        raise SchoolAssetValidationError("school file id must be positive")
    return parsed


def _school_asset_display_and_extension(filename: object) -> tuple[str, str]:
    """Sanitize a client label into display-only text plus a real extension.

    The label is never used to form a filesystem path.  Splitting both slash
    variants means a Windows-looking traversal string cannot become a stored
    directory on macOS/Linux, and stripping controls keeps Content-Disposition
    headers safe when the filename later becomes a download suggestion.
    """
    raw = str(filename or "").replace("\x00", "")
    base = re.split(r"[\\\\/]+", raw)[-1]
    base = "".join(char for char in base if char.isprintable())
    base = re.sub(r"\s+", " ", base).strip()
    if not base or base in {".", ".."} or "." not in base:
        raise SchoolAssetValidationError("file needs a supported extension")
    stem, _, extension = base.rpartition(".")
    stem = stem.strip(" .")
    extension = extension.strip().lower()
    if not stem or not re.fullmatch(r"[a-z0-9]{1,12}", extension):
        raise SchoolAssetValidationError("file needs a supported extension")
    if extension not in _SCHOOL_ASSET_SPECS:
        raise SchoolAssetValidationError("unsupported school file type")
    # The extension is relevant to the user, so preserve it in the label while
    # bounding the only free-form part.  The original client filename is never
    # persisted elsewhere.
    display_name = f"{stem[:_SCHOOL_ASSET_NAME_MAX - len(extension) - 1]}.{extension}"
    if len(display_name) > _SCHOOL_ASSET_NAME_MAX:
        display_name = display_name[:_SCHOOL_ASSET_NAME_MAX]
    return display_name, extension


def school_asset_file_spec(filename: object, mime_type: object) -> dict:
    """Validate the client declaration before streaming anything to disk."""
    display_name, extension = _school_asset_display_and_extension(filename)
    declared_mime = _clean_text(mime_type, 160).split(";", 1)[0].casefold()
    spec = _SCHOOL_ASSET_SPECS[extension]
    # iOS/share-sheet uploads often omit the MIME declaration entirely.  An
    # empty declaration is therefore resolved from the trusted extension and
    # then verified against bytes below; a nonempty MIME must still match
    # exactly, so `text/html` cannot ride in as `slides.pdf`.
    if declared_mime and declared_mime not in spec["mime_types"]:
        raise SchoolAssetValidationError("file MIME type does not match its extension")
    return {
        "display_name": display_name,
        "extension": extension,
        "mime_type": spec["mime_type"],
        "file_type": spec["file_type"],
    }


def _school_asset_category(value: object | None) -> str:
    category = _clean_text(value or "material", 32).casefold()
    if category not in _SCHOOL_ASSET_CATEGORIES:
        raise SchoolAssetValidationError("unknown school file category")
    return category


def _school_asset_storage_key(value: object, extension: str) -> str:
    """Allow only a server-minted, relative key beneath the asset root."""
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or len(raw) > _SCHOOL_ASSET_STORAGE_KEY_MAX:
        raise SchoolAssetValidationError("invalid school file storage key")
    path = PurePosixPath(raw)
    parts = path.parts
    if path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        raise SchoolAssetValidationError("invalid school file storage key")
    if len(parts) != 3 or not re.fullmatch(r"\d{4}", parts[0]) or not re.fullmatch(r"\d{2}", parts[1]):
        raise SchoolAssetValidationError("invalid school file storage key")
    filename = parts[-1]
    if not re.fullmatch(r"[a-f0-9]{32}\.[a-z0-9]{1,12}", filename):
        raise SchoolAssetValidationError("invalid school file storage key")
    if filename.rsplit(".", 1)[-1] != extension:
        raise SchoolAssetValidationError("school file storage type does not match")
    return path.as_posix()


def _school_asset_session_for_course(conn, course_code: str, session_id: object | None) -> int | None:
    if session_id is None:
        return None
    try:
        parsed = int(session_id)
    except (TypeError, ValueError) as exc:
        raise SchoolAssetValidationError("session_id must be an integer") from exc
    if parsed < 1:
        raise SchoolAssetValidationError("session_id must be positive")
    row = conn.execute(
        """SELECT id, course_code FROM school_note_sessions
             WHERE id=? AND deleted_at IS NULL""",
        (parsed,),
    ).fetchone()
    if row is None:
        raise SchoolAssetNotFoundError("class note not found")
    if row["course_code"] != course_code:
        raise SchoolAssetValidationError("note session does not belong to this course")
    return parsed


def validate_school_asset_target(conn, course_code: object, *, session_id: object | None = None) -> dict:
    """Preflight ownership before an upload creates a server file."""
    ensure_schema(conn)
    course = _ensure_school_course(conn, course_code)
    return {
        "course_code": course["code"],
        "session_id": _school_asset_session_for_course(conn, course["code"], session_id),
    }


def _school_asset_row(row) -> dict:
    """The only asset projection callers may return to the browser.

    In particular, token and storage_path remain database implementation
    details.  There is no token download endpoint: asset id resolves its path
    server-side, so neither opaque key needs browser lifetime management.
    """
    data = dict(row)
    return {
        "id": data["id"],
        "course_code": data["course_code"],
        "session_id": data["school_note_session_id"],
        "display_name": data["display_name"],
        "mime_type": data["mime_type"],
        "file_type": data["file_type"],
        "extension": data["extension"],
        "byte_size": data["byte_size"],
        "category": data["category"],
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }


def _school_asset_db_row(conn, asset_id: object, *, include_deleted: bool = False):
    parsed = _school_asset_id(asset_id)
    where = "id=?" if include_deleted else "id=? AND deleted_at IS NULL"
    return conn.execute(
        f"SELECT * FROM school_note_assets WHERE {where}", (parsed,)
    ).fetchone()


def school_asset(conn, asset_id: object) -> dict | None:
    """Return safe public metadata for one live School file."""
    ensure_schema(conn)
    row = _school_asset_db_row(conn, asset_id)
    return _school_asset_row(row) if row is not None else None


def list_school_assets(conn, course_code: object, *, session_id: object | None = None,
                       limit: int = 250) -> list[dict]:
    """List a course's private library without any storage handles."""
    target = validate_school_asset_target(conn, course_code, session_id=session_id)
    safe_limit = max(1, min(int(limit), 500))
    params: list[object] = [target["course_code"]]
    where = ["course_code=?", "deleted_at IS NULL"]
    if target["session_id"] is not None:
        where.append("school_note_session_id=?")
        params.append(target["session_id"])
    rows = conn.execute(
        "SELECT * FROM school_note_assets WHERE " + " AND ".join(where)
        + " ORDER BY created_at DESC, id DESC LIMIT ?",
        (*params, safe_limit),
    ).fetchall()
    return [_school_asset_row(row) for row in rows]


def create_school_asset(conn, course_code: object, *, session_id: object | None,
                        display_name: object, mime_type: object, file_type: object,
                        extension: object, byte_size: object, category: object | None,
                        storage_path: object) -> dict:
    """Persist metadata only after the API has safely written/validated bytes.

    The route owns the filesystem stream; this service owns relational
    ownership, public projection, token minting, and a second metadata check
    so another caller cannot smuggle an arbitrary storage path or MIME row.
    """
    target = validate_school_asset_target(conn, course_code, session_id=session_id)
    spec = school_asset_file_spec(display_name, mime_type)
    if _clean_text(extension, 12).casefold() != spec["extension"]:
        raise SchoolAssetValidationError("school file extension is invalid")
    if _clean_text(file_type, 32).casefold() != spec["file_type"]:
        raise SchoolAssetValidationError("school file type is invalid")
    try:
        size = int(byte_size)
    except (TypeError, ValueError) as exc:
        raise SchoolAssetValidationError("school file size is invalid") from exc
    if size < 1 or size > _SCHOOL_ASSET_MAX_BYTES:
        raise SchoolAssetValidationError("school file size is invalid")
    storage_key = _school_asset_storage_key(storage_path, spec["extension"])
    clean_category = _school_asset_category(category)

    for _ in range(_SCHOOL_ASSET_TOKEN_MINT_TRIES):
        token = secrets.token_hex(16)
        try:
            cursor = conn.execute(
                """INSERT INTO school_note_assets
                       (course_code, school_note_session_id, token, display_name,
                        mime_type, file_type, extension, byte_size, category, storage_path)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    target["course_code"], target["session_id"], token,
                    spec["display_name"], spec["mime_type"], spec["file_type"],
                    spec["extension"], size, clean_category, storage_key,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "school_note_assets.token" not in str(exc):
                raise
            continue
        conn.commit()
        row = _school_asset_db_row(conn, cursor.lastrowid)
        if row is None:
            raise SchoolAssetNotFoundError("could not save school file")
        return _school_asset_row(row)
    raise RuntimeError("could not mint a unique school file token")


def school_asset_download_row(conn, asset_id: object) -> dict | None:
    """Private route-only lookup containing the server storage key.

    Do not use this in a JSON response.  It exists specifically so download
    and deletion resolve storage only from the database, never a URL value.
    """
    ensure_schema(conn)
    row = _school_asset_db_row(conn, asset_id)
    return dict(row) if row is not None else None


def delete_school_asset(conn, asset_id: object) -> str:
    """Delete live metadata and return only the internal storage key to route code."""
    ensure_schema(conn)
    row = _school_asset_db_row(conn, asset_id)
    if row is None:
        raise SchoolAssetNotFoundError("school file not found")
    storage_key = str(row["storage_path"])
    cursor = conn.execute(
        "DELETE FROM school_note_assets WHERE id=? AND deleted_at IS NULL",
        (int(row["id"]),),
    )
    if cursor.rowcount != 1:
        conn.rollback()
        raise SchoolAssetNotFoundError("school file not found")
    conn.commit()
    return storage_key


def _school_asset_is_text_safe(path: Path) -> bool:
    """Accept UTF-8 text/Markdown only; do not parse or extract it for AI."""
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                text = decoder.decode(chunk)
                if any(ord(char) < 32 and char not in "\t\n\r\f" for char in text):
                    return False
            trailing = decoder.decode(b"", final=True)
            return not any(ord(char) < 32 and char not in "\t\n\r\f" for char in trailing)
    except (OSError, UnicodeDecodeError):
        return False


def school_asset_content_is_safe(path: Path, spec: dict) -> bool:
    """Verify stored bytes agree with the allowlisted declared material type.

    This is intentionally a shallow type gate, not document parsing or text
    extraction. It prevents a renamed executable/plain payload from being
    accepted as a PDF/image/Office file while keeping this phase completely
    free of AI ingestion and document-content side effects.
    """
    extension = spec.get("extension") if isinstance(spec, dict) else None
    if extension not in _SCHOOL_ASSET_SPECS:
        return False
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
    except OSError:
        return False
    if extension == "pdf":
        return header.startswith(b"%PDF-")
    if extension in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == "gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if extension == "webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if extension in {"heic", "heif"}:
        brands = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        return len(header) >= 12 and header[4:8] == b"ftyp" and header[8:12] in brands
    if extension == "bmp":
        return header.startswith(b"BM")
    if extension in {"tif", "tiff"}:
        return header.startswith((b"II*\x00", b"MM\x00*"))
    if extension in {"doc", "ppt", "xls"}:
        return header.startswith(_SCHOOL_ASSET_OLE_HEADER)
    if extension in _SCHOOL_ASSET_OOXML_MARKERS:
        if not header.startswith(b"PK"):
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                infos = archive.infolist()
                if len(infos) > 10_000:
                    return False
                return _SCHOOL_ASSET_OOXML_MARKERS[extension] in {
                    info.filename for info in infos
                }
        except (OSError, zipfile.BadZipFile):
            return False
    if extension in {"txt", "md", "markdown"}:
        return _school_asset_is_text_safe(path)
    return False


def _has_shared_calendar(conn) -> bool:
    """Allow isolated metadata previews to run without initializing ianOS DB."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calendar_events'"
    ).fetchone()
    return row is not None


def _course_row(row) -> dict:
    course = dict(row)
    course["aliases"] = _json(course.pop("aliases_json", "[]"), [])
    course["meetings"] = _json(course.pop("meetings_json", "[]"), [])
    course["grade_categories"] = _json(course.pop("grade_categories_json", "[]"), [])
    course["policies"] = _json(course.pop("policy_json", "{}"), {})
    course.pop("source_ref", None)
    return course


# Coursework rows always carry Ian's own completion state alongside the
# provider's fields. LEFT JOIN, because most items are simply not done yet.
_SCHOOL_ITEM_SELECT = """
SELECT i.*, c.meetings_json, done.completed_at AS completed_at
  FROM school_items i
  JOIN school_courses c ON c.code=i.course_code
  LEFT JOIN school_item_completions done
         ON done.provider=i.provider AND done.external_item_id=i.external_item_id
"""


def _item_row(row) -> dict:
    item = dict(row)
    # Ian's completion is a first-class field on every coursework projection so
    # no surface has to re-derive "is this finished" from a second query.
    completed_at = item.pop("completed_at", None)
    item["completed_at"] = completed_at
    item["done"] = completed_at is not None
    # The browser/agents never need the local provider key. Keep provenance as
    # a one-word source label rather than a private calendar URL or filesystem
    # location.
    item["source"] = item.pop("source_kind", "") or item.pop("provider", "")
    item.pop("provider", None)
    item.pop("external_item_id", None)
    item.pop("source_updated_at", None)
    item.pop("archived_at", None)
    item.pop("created_at", None)
    item.pop("updated_at", None)
    return item


class SchoolItemNotFoundError(LookupError):
    """A requested coursework item does not exist."""


def _school_item_id(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SchoolNoteValidationError("coursework id must be an integer") from exc
    if parsed < 1:
        raise SchoolNoteValidationError("coursework id must be positive")
    return parsed


def set_school_item_done(conn, item_id: object, done: object) -> dict:
    """Cross one coursework item off, or put it back. Idempotent either way.

    Writes only to school_item_completions, never to school_items, so the next
    Canvas sync cannot undo Ian's own record of having finished something.
    """
    ensure_schema(conn)
    if not isinstance(done, bool):
        raise SchoolNoteValidationError("done must be true or false")
    parsed_id = _school_item_id(item_id)
    row = conn.execute(
        """SELECT i.*, c.meetings_json FROM school_items i
             JOIN school_courses c ON c.code=i.course_code
            WHERE i.id=?""",
        (parsed_id,),
    ).fetchone()
    if row is None:
        raise SchoolItemNotFoundError("coursework item not found")
    if done:
        conn.execute(
            """INSERT INTO school_item_completions (provider, external_item_id)
               VALUES (?, ?) ON CONFLICT(provider, external_item_id) DO NOTHING""",
            (row["provider"], row["external_item_id"]),
        )
    else:
        conn.execute(
            "DELETE FROM school_item_completions WHERE provider=? AND external_item_id=?",
            (row["provider"], row["external_item_id"]),
        )
    conn.commit()
    return _item_row(conn.execute(
        _SCHOOL_ITEM_SELECT + " WHERE i.id=?", (parsed_id,),
    ).fetchone())


def _course_aliases(course: dict) -> set[str]:
    values = {course.get("code", "")}
    values.update(course.get("aliases") or [])
    return {_clean_text(value).casefold() for value in values if _clean_text(value)}


def _resolve_course_code(conn, label: object) -> str | None:
    target = _clean_text(label).casefold()
    if not target:
        return None
    for row in conn.execute("SELECT code, aliases_json FROM school_courses"):
        aliases = [row["code"], *_json(row["aliases_json"], [])]
        normalized_target = re.sub(r"[^a-z0-9]", "", target)
        normalized_aliases = {
            re.sub(r"[^a-z0-9]", "", _clean_text(alias).casefold())
            for alias in aliases if _clean_text(alias)
        }
        if (target in {_clean_text(alias).casefold() for alias in aliases}
                or any(alias and (alias in normalized_target or normalized_target in alias)
                       for alias in normalized_aliases)):
            return row["code"]
    return None


def seed_inventory(conn, inventory: dict) -> dict:
    """Upsert user-verified course metadata and syllabus milestone metadata.

    ``inventory`` is intentionally a small curated file, not a source of full
    course material. It is safe to rerun when a syllabus changes.
    """
    ensure_schema(conn)
    courses = inventory.get("courses") if isinstance(inventory, dict) else None
    if not isinstance(courses, list):
        raise ValueError("school inventory must contain a courses array")
    course_count = 0
    item_count = 0
    syllabus_ids: set[str] = set()
    for raw in courses:
        if not isinstance(raw, dict):
            continue
        code = _clean_text(raw.get("code"), 32)
        name = _clean_text(raw.get("name"), 120)
        if not code or not name:
            continue
        aliases = [_clean_text(alias, 120) for alias in raw.get("aliases", [])
                   if _clean_text(alias, 120)]
        aliases.extend(
            _clean_text(alias, 120) for alias in raw.get("canvas_aliases", [])
            if _clean_text(alias, 120)
        )
        aliases.extend(
            _clean_text(alias, 120) for alias in raw.get("cross_listings", [])
            if _clean_text(alias, 120)
        )
        course_id = _clean_text(raw.get("course_id"), 64)
        if course_id:
            aliases.extend((course_id, course_id.replace("-", "_")))
        if code not in aliases:
            aliases.insert(0, code)
        # The user-facing seed retains structured sections/staff/grading. The
        # persistent projection flattens only the fields each screen needs,
        # while keeping the full policy/grading object as local JSON.
        sections = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
        section = _clean_text(raw.get("section"), 80)
        if not section:
            section = " · ".join(
                _clean_text(value.get("section"), 24)
                for value in sections.values() if isinstance(value, dict)
                and _clean_text(value.get("section"), 24)
            )
        staff = raw.get("instructional_staff") if isinstance(raw.get("instructional_staff"), list) else []
        instructor = _clean_text(raw.get("instructor"), 120)
        if not instructor:
            instructor = ", ".join(
                _clean_text(person.get("name"), 80)
                for person in staff if isinstance(person, dict)
                and _clean_text(person.get("name"), 80)
            )
        grading = raw.get("grading") if isinstance(raw.get("grading"), dict) else {}
        categories = raw.get("grade_categories")
        if not isinstance(categories, list):
            categories = grading.get("categories", [])
        policies = raw.get("policies") if isinstance(raw.get("policies"), dict) else {}
        if not policies:
            policies = raw.get("key_policy_flags") if isinstance(raw.get("key_policy_flags"), dict) else {}
        if grading:
            policies = {**policies, "target_cutoffs": grading.get("target_cutoffs", {}),
                        "total_points": grading.get("total_points")}
        conn.execute(
            """INSERT INTO school_courses
               (code, term, name, section, instructor, credits, aliases_json,
                meetings_json, grade_categories_json, policy_json, source_ref)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                 term=excluded.term, name=excluded.name, section=excluded.section,
                 instructor=excluded.instructor, credits=excluded.credits,
                 aliases_json=excluded.aliases_json, meetings_json=excluded.meetings_json,
                 grade_categories_json=excluded.grade_categories_json,
                 policy_json=excluded.policy_json, source_ref=excluded.source_ref,
                 updated_at=datetime('now', 'localtime')""",
            (
                code,
                _clean_text(raw.get("term") or TERM, 32),
                name,
                section,
                instructor,
                raw.get("credits"),
                _compact_json(aliases, []),
                _compact_json(raw.get("meetings", []), []),
                _compact_json(categories, []),
                _compact_json(policies, {}),
                Path(str(raw.get("source_ref") or raw.get("source_path") or "")).name,
            ),
        )
        course_count += 1
        milestones = raw.get("key_dates") if isinstance(raw.get("key_dates"), list) else []
        if not milestones:
            milestones = raw.get("known_major_dates") if isinstance(raw.get("known_major_dates"), list) else []
        for position, milestone in enumerate(milestones):
            if not isinstance(milestone, dict):
                continue
            title = _clean_text(milestone.get("title") or milestone.get("label"), 240)
            raw_date = milestone.get("due_at") or milestone.get("date") or milestone.get("start_date")
            if raw_date and milestone.get("time_local") and "T" not in str(raw_date):
                raw_date = f"{raw_date}T{milestone['time_local']}"
            due_at = _local_iso(raw_date)
            if not title or not due_at:
                continue
            external_id = _clean_text(milestone.get("id"), 120) or f"milestone-{position}"
            item_id = f"{code}:{external_id}"
            all_day = bool(milestone.get("all_day", "T" not in due_at))
            # Timed milestones are deadline dots, not invented work blocks.
            # Giving them a zero-length end keeps Plan's visual treatment
            # consistent with Canvas assignment deadlines.
            deadline_at = due_at if not all_day and "T" in due_at else None
            _upsert_item(
                conn,
                course_code=code,
                provider="syllabus",
                external_item_id=item_id,
                kind=_clean_text(milestone.get("kind") or "milestone", 32),
                title=title,
                due_at=due_at,
                start_at=deadline_at,
                end_at=deadline_at,
                # A date-only syllabus entry is a deadline signal, not a
                # midnight appointment in Plan.
                all_day=all_day,
                location="",
                source_updated_at=None,
                source_kind="syllabus",
            )
            syllabus_ids.add(item_id)
            item_count += 1
    _archive_missing_items(conn, "syllabus", syllabus_ids)
    scheduled_count = _seed_verified_meetings(conn, inventory, courses)
    if _has_shared_calendar(conn):
        _project_to_calendar(conn, "syllabus")
        _project_to_calendar(conn, SCHEDULE_PROVIDER)
    conn.commit()
    return {
        "courses": course_count,
        "syllabus_items": item_count,
        "scheduled_meetings": scheduled_count,
    }


def seed_inventory_file(conn, path: str | Path) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return seed_inventory(conn, raw)


def _upsert_item(conn, *, course_code: str, provider: str, external_item_id: str,
                 kind: str, title: str, due_at: str | None, start_at: str | None,
                 end_at: str | None, all_day: bool, location: str,
                 source_updated_at: str | None, source_kind: str) -> None:
    conn.execute(
        """INSERT INTO school_items
           (course_code, provider, external_item_id, kind, title, due_at, start_at,
            end_at, all_day, location, source_updated_at, source_kind)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(provider, external_item_id) DO UPDATE SET
             course_code=excluded.course_code, kind=excluded.kind, title=excluded.title,
             due_at=excluded.due_at, start_at=excluded.start_at, end_at=excluded.end_at,
             all_day=excluded.all_day, location=excluded.location,
             source_updated_at=excluded.source_updated_at, source_kind=excluded.source_kind,
             archived_at=NULL, updated_at=datetime('now', 'localtime')""",
        (course_code, provider, external_item_id, kind or "assignment", title,
         due_at, start_at, end_at, int(all_day), location, source_updated_at,
         source_kind),
    )


def _archive_missing_items(conn, provider: str, accepted_ids: set[str]) -> int:
    """Archive only records owned by a refreshed local provider snapshot."""
    now = db.now()
    if accepted_ids:
        placeholders = ",".join("?" for _ in accepted_ids)
        cursor = conn.execute(
            f"""UPDATE school_items SET archived_at=?
                WHERE provider=? AND archived_at IS NULL
                  AND external_item_id NOT IN ({placeholders})""",
            (now, provider, *sorted(accepted_ids)),
        )
    else:
        cursor = conn.execute(
            "UPDATE school_items SET archived_at=? WHERE provider=? AND archived_at IS NULL",
            (now, provider),
        )
    return max(0, cursor.rowcount)


def _meeting_title(kind: str, location: str) -> str:
    label = (kind or "class").replace("_", " ").title()
    return f"{label} · {location}" if location else label


def _seed_verified_meetings(conn, inventory: dict, courses: list[object]) -> int:
    """Materialize the user-confirmed recurring class schedule for Plan.

    Canvas exports are excellent for assignment deadlines, but some of their
    attendance-shell entries have zero duration or a synthetic 11:59 PM time.
    The course meetings in the user-verified inventory are therefore the
    canonical schedule projection.  A stable occurrence key makes reseeding
    safe when a syllabus correction changes one meeting.
    """
    config = inventory.get("calendar_projection") if isinstance(inventory, dict) else None
    if not isinstance(config, dict):
        return 0
    default_start = _iso_date(config.get("instruction_start") or config.get("start_date"))
    default_end = _iso_date(config.get("instruction_end") or config.get("end_date"))
    if not default_start or not default_end or default_end < default_start:
        return 0
    excluded_dates = {
        parsed.isoformat()
        for value in config.get("excluded_dates", []) if isinstance(value, str)
        if (parsed := _iso_date(value))
    }
    accepted: set[str] = set()
    count = 0
    for raw in courses:
        if not isinstance(raw, dict):
            continue
        code = _clean_text(raw.get("code"), 32)
        if not code:
            continue
        term_dates = raw.get("term_dates") if isinstance(raw.get("term_dates"), dict) else {}
        start = _iso_date(term_dates.get("start_date")) or default_start
        end = _iso_date(term_dates.get("end_date")) or default_end
        if end < start:
            continue
        course_excluded = {
            parsed.isoformat()
            for value in raw.get("excluded_dates", []) if isinstance(value, str)
            if (parsed := _iso_date(value))
        }
        meetings = raw.get("meetings") if isinstance(raw.get("meetings"), list) else []
        for meeting_index, raw_meeting in enumerate(meetings):
            if not isinstance(raw_meeting, dict):
                continue
            days = tuple(
                day for day in (_clean_text(value, 2).upper() for value in raw_meeting.get("days", []))
                if day in _WEEKDAY_CODES
            )
            start_local = _valid_clock(raw_meeting.get("start_local"))
            end_local = _valid_clock(raw_meeting.get("end_local"))
            if not days or not start_local or not end_local or end_local <= start_local:
                # Asynchronous courses intentionally produce no fake meetings.
                continue
            kind = _clean_text(raw_meeting.get("kind") or "class", 32)
            location = _clean_text(raw_meeting.get("location"), 120)
            # The occurrence identity is deliberately independent of room,
            # time, and kind. Those can be corrected after a note exists; an
            # explicit source key wins, with a stable source-order fallback
            # for the handwritten local inventory.
            meeting_key = _clean_text(
                raw_meeting.get("id") or raw_meeting.get("meeting_id") or raw_meeting.get("key"),
                64,
            ) or f"slot-{meeting_index + 1}"
            cursor = start
            while cursor <= end:
                if (
                    _WEEKDAY_CODES[cursor.weekday()] in days
                    and cursor.isoformat() not in excluded_dates
                    and cursor.isoformat() not in course_excluded
                ):
                    occurrence_id = f"{code}:meeting:{meeting_key}:{cursor.isoformat()}"
                    _upsert_item(
                        conn,
                        course_code=code,
                        provider=SCHEDULE_PROVIDER,
                        external_item_id=occurrence_id,
                        kind=kind,
                        title=_meeting_title(kind, location),
                        due_at=f"{cursor.isoformat()}T{start_local}",
                        start_at=f"{cursor.isoformat()}T{start_local}",
                        end_at=f"{cursor.isoformat()}T{end_local}",
                        all_day=False,
                        location=location,
                        source_updated_at=None,
                        source_kind="Verified schedule",
                    )
                    accepted.add(occurrence_id)
                    count += 1
                cursor += timedelta(days=1)
    _archive_missing_items(conn, SCHEDULE_PROVIDER, accepted)
    return count


def import_canvas_items(conn, records: Iterable[dict]) -> dict:
    """Replace the Canvas calendar snapshot with sanitized parsed records.

    Unknown calendar labels are excluded instead of silently becoming part of
    the school portal. This keeps an unrelated Canvas workshop or a malformed
    feed from being presented as one of Ian's graded courses.
    """
    ensure_schema(conn)
    now = db.now()
    conn.execute(
        """INSERT INTO school_sync_state (provider, last_attempt)
           VALUES (?, ?) ON CONFLICT(provider) DO UPDATE SET
           last_attempt=excluded.last_attempt, last_error=''""",
        (CANVAS_PROVIDER, now),
    )
    accepted: set[str] = set()
    ignored = 0
    for raw in records:
        if not isinstance(raw, dict):
            ignored += 1
            continue
        external_id = _clean_text(raw.get("external_id"), 200)
        course_code = _resolve_course_code(conn, raw.get("course_label"))
        title = _clean_text(raw.get("title"), 240)
        due_at = _local_iso(raw.get("due_at"))
        if not external_id or not course_code or not title or not due_at:
            ignored += 1
            continue
        _upsert_item(
            conn,
            course_code=course_code,
            provider=CANVAS_PROVIDER,
            external_item_id=external_id,
            kind=_clean_text(raw.get("kind") or "assignment", 32),
            title=title,
            due_at=due_at,
            start_at=_local_iso(raw.get("start_at")),
            end_at=_local_iso(raw.get("end_at")),
            all_day=bool(raw.get("all_day")),
            location=_clean_text(raw.get("location"), 120),
            source_updated_at=_local_iso(raw.get("source_updated_at")),
            source_kind="Canvas calendar",
        )
        accepted.add(external_id)
    if accepted:
        placeholders = ",".join("?" for _ in accepted)
        conn.execute(
            f"""UPDATE school_items SET archived_at=?
                WHERE provider=? AND archived_at IS NULL
                  AND external_item_id NOT IN ({placeholders})""",
            (now, CANVAS_PROVIDER, *sorted(accepted)),
        )
    else:
        # An empty/bad file must never erase the prior successful snapshot.
        conn.execute(
            "UPDATE school_sync_state SET last_error=? WHERE provider=?",
            ("no recognized course items", CANVAS_PROVIDER),
        )
        conn.commit()
        return {"imported": 0, "ignored": ignored, "archived": 0}
    archived = conn.execute(
        "SELECT COUNT(*) FROM school_items WHERE provider=? AND archived_at=?",
        (CANVAS_PROVIDER, now),
    ).fetchone()[0]
    _project_to_calendar(conn, CANVAS_PROVIDER)
    conn.execute(
        """UPDATE school_sync_state
           SET last_success=?, last_error='', item_count=? WHERE provider=?""",
        (now, len(accepted), CANVAS_PROVIDER),
    )
    conn.commit()
    return {"imported": len(accepted), "ignored": ignored, "archived": archived}


def _time_parts(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    parsed = _local_iso(value)
    if not parsed:
        return None, None
    if "T" not in parsed:
        return parsed, None
    return parsed[:10], parsed[11:16]


def _is_canvas_schedule_shell(item: dict) -> bool:
    """Whether a Canvas event duplicates a verified recurring meeting.

    Canvas gives us assignment due dates, but regular attendance entries can
    be emitted at their real time, as an all-purpose ``event``, or at 11:59 PM
    as a synthetic deadline.  Keep genuine one-off events (for example the
    FIN leadership panel) while letting the confirmed meeting schedule own the
    normal class slot.
    """
    if item.get("provider") != CANVAS_PROVIDER or item.get("kind") not in {"class", "event"}:
        return False
    day, start = _time_parts(item.get("start_at") or item.get("due_at"))
    parsed_day = _iso_date(day)
    if not parsed_day:
        return False
    same_day_meetings = [
        meeting for meeting in _json(item.get("meetings_json"), [])
        if isinstance(meeting, dict)
        and _WEEKDAY_CODES[parsed_day.weekday()] in {
            _clean_text(value, 2).upper() for value in meeting.get("days", [])
        }
    ]
    if not same_day_meetings:
        return False
    if any(start == _valid_clock(meeting.get("start_local")) for meeting in same_day_meetings):
        return True
    title = _clean_text(item.get("title")).casefold()
    special_event_words = ("guest speaker", "panel", "workshop", "exam", "review")
    # Only a plainly labelled class is allowed to override its broken Canvas
    # timestamp. This preserves named special events on a regular class day.
    return (
        item.get("kind") == "class"
        and "class" in title
        and not any(word in title for word in special_event_words)
    )


def _calendar_fields(item: dict) -> tuple[str, str | None, str | None, int | None] | None:
    """Return a single-day Plan commitment from an academic item."""
    due_at = item.get("due_at")
    if item.get("all_day"):
        day, _ = _time_parts(due_at)
        return (day, None, None, None) if day else None
    day, start = _time_parts(item.get("start_at") or due_at)
    end_day, end = _time_parts(item.get("end_at"))
    if not day:
        return None
    # Generic calendar_events has one date field, so do not silently make an
    # overnight item look shorter than it is. The current school inventory has
    # only same-day events.
    if end_day and end_day != day:
        end = None
    duration = None
    if start and end and end > start:
        start_hour, start_min = map(int, start.split(":"))
        end_hour, end_min = map(int, end.split(":"))
        duration = (end_hour * 60 + end_min) - (start_hour * 60 + start_min)
    return day, start, end, duration


def _project_to_calendar(conn, provider: str) -> None:
    """Keep Plan conflict-aware while retaining school_items as canonical."""
    rows = conn.execute(
        """SELECT i.*, c.code, c.meetings_json
           FROM school_items i JOIN school_courses c ON c.code=i.course_code
           WHERE i.provider=? AND i.archived_at IS NULL AND i.due_at IS NOT NULL""",
        (provider,),
    ).fetchall()
    eligible = [dict(row) for row in rows]
    if provider == CANVAS_PROVIDER:
        eligible = [item for item in eligible if not _is_canvas_schedule_shell(item)]
    eligible_ids = {item["external_item_id"] for item in eligible}
    mapped = conn.execute(
        """SELECT external_item_id, calendar_event_id
           FROM school_calendar_projection WHERE provider=?""",
        (provider,),
    ).fetchall()
    for mapping in mapped:
        if mapping["external_item_id"] not in eligible_ids:
            conn.execute("DELETE FROM calendar_events WHERE id=?", (mapping["calendar_event_id"],))
            conn.execute(
                "DELETE FROM school_calendar_projection WHERE provider=? AND external_item_id=?",
                (provider, mapping["external_item_id"]),
            )
    for item in eligible:
        fields = _calendar_fields(item)
        if not fields:
            continue
        day, start, end, duration = fields
        summary = f"{item['course_code']} · {item['title']}"
        h = hashlib.sha256(
            f"school|{provider}|{item['external_item_id']}".encode()
        ).hexdigest()[:20]
        existing = conn.execute("SELECT id FROM calendar_events WHERE hash=?", (h,)).fetchone()
        if existing:
            conn.execute(
                """UPDATE calendar_events SET date=?, start_time=?, end_time=?, summary=?,
                   category='school', duration_min=? WHERE id=?""",
                (day, start, end, summary, duration, existing["id"]),
            )
            event_id = existing["id"]
        else:
            db.upsert_calendar_event(
                conn, date=day, start_time=start, end_time=end, summary=summary,
                category="school", duration_min=duration, hash=h,
            )
            event_id = conn.execute("SELECT id FROM calendar_events WHERE hash=?", (h,)).fetchone()[0]
        conn.execute(
            """INSERT INTO school_calendar_projection(provider, external_item_id, calendar_event_id)
               VALUES (?,?,?) ON CONFLICT(provider, external_item_id)
               DO UPDATE SET calendar_event_id=excluded.calendar_event_id""",
            (provider, item["external_item_id"], event_id),
        )


def sync_state(conn) -> dict:
    row = conn.execute("SELECT * FROM school_sync_state WHERE provider=?", (CANVAS_PROVIDER,)).fetchone()
    if not row:
        return {"connected": False, "last_success": None, "item_count": 0}
    state = dict(row)
    return {
        "connected": bool(state.get("last_success")),
        "last_success": state.get("last_success"),
        "item_count": state.get("item_count", 0),
        "last_error": state.get("last_error", ""),
    }


def dashboard_snapshot(conn, days: int = 14) -> dict:
    """Safe data projection for the dashboard, without source secrets."""
    ensure_schema(conn)
    today = date.today().isoformat()
    courses = [_course_row(row) for row in conn.execute(
        "SELECT * FROM school_courses WHERE term=? ORDER BY code", (TERM,)
    )]
    item_rows = conn.execute(
        _SCHOOL_ITEM_SELECT
        + """WHERE i.archived_at IS NULL AND i.due_at IS NOT NULL
                   AND substr(i.due_at, 1, 10)>=?
             ORDER BY due_at, course_code, title LIMIT 100""",
        (today,),
    ).fetchall()
    # The rhythm panel owns recurring class meetings. Keeping them out of the
    # assignment queue prevents 100+ repeated class entries from burying the
    # actionable Canvas work; the exact meetings still block Plan.
    action_rows = [
        row for row in item_rows
        if row["provider"] != SCHEDULE_PROVIDER and not _is_canvas_schedule_shell(dict(row))
    ]
    items = [_item_row(row) for row in action_rows]
    # Finished work leaves the pressure surfaces. Every queue, count and
    # "next due" below reflects what is actually LEFT, because a list that
    # still counts things Ian already did is the thing that makes a workload
    # feel unmovable (PRODUCT.md: no surface may manufacture shame).
    open_items = [item for item in items if not item["done"]]
    window_end = date.fromordinal(date.fromisoformat(today).toordinal() + max(1, days)).isoformat()
    in_window = (lambda item: (item.get("due_at") or "")[:10] <= window_end)
    upcoming = [item for item in open_items if in_window(item)]
    # Crossing something off should stay visible and reversible for a moment
    # rather than vanishing, so the act reads as progress instead of deletion.
    just_done = sorted(
        (item for item in items if item["done"] and in_window(item)),
        key=lambda item: item["completed_at"] or "", reverse=True,
    )[:12]
    by_course: dict[str, list[dict]] = {}
    for item in open_items:
        by_course.setdefault(item["course_code"], []).append(item)
    for course in courses:
        course_items = by_course.get(course["code"], [])
        course["next_due_at"] = course_items[0]["due_at"] if course_items else None
        course["upcoming_count"] = sum(1 for item in course_items if in_window(item))
        course["done_count"] = sum(
            1 for item in items
            if item["course_code"] == course["code"] and item["done"] and in_window(item)
        )
    # The calendar projection remains Plan's source of truth, but School needs
    # a tiny, verified meeting projection so it can launch the right daily
    # note without re-deriving a recurrence in React. No document content,
    # source ids, Canvas URLs, or provider metadata leaves this boundary.
    next_meetings = next_note_launches(conn, from_date=today, limit=30)
    meetings_by_course: dict[str, list[dict]] = {}
    for meeting in next_meetings:
        meetings_by_course.setdefault(meeting["course_code"], []).append(meeting)
    for course in courses:
        course["next_meeting"] = (meetings_by_course.get(course["code"]) or [None])[0]
    return {
        "term": TERM,
        "today": today,
        "courses": courses,
        "upcoming": upcoming,
        "just_done": just_done,
        "next_meetings": next_meetings,
        "sync": sync_state(conn),
        "summary": {
            "course_count": len(courses),
            "upcoming_count": len(upcoming),
            "done_count": len(just_done),
            "next_due_at": open_items[0]["due_at"] if open_items else None,
        },
    }


def agent_snapshot(conn, days: int = 10, aggregate: bool = False) -> dict:
    """Narrow agent view. It contains no material beyond course/deadline metadata."""
    snap = dashboard_snapshot(conn, days=days)
    if aggregate:
        counts: dict[str, int] = {}
        for item in snap["upcoming"]:
            counts[item["course_code"]] = counts.get(item["course_code"], 0) + 1
        return {
            "term": snap["term"],
            "today": snap["today"],
            "upcoming_count": snap["summary"]["upcoming_count"],
            "next_due_at": snap["summary"]["next_due_at"],
            "workload_by_course": counts,
            "upcoming": [
                {key: item[key] for key in ("course_code", "kind", "title", "due_at")}
                for item in snap["upcoming"]
            ],
        }
    return {
        "term": snap["term"],
        "today": snap["today"],
        "courses": [
            {key: course[key] for key in ("code", "name", "instructor", "credits", "meetings",
                                            "grade_categories", "policies", "next_due_at", "upcoming_count")}
            for course in snap["courses"]
        ],
        "upcoming": [
            {key: item[key] for key in ("course_code", "kind", "title", "due_at", "all_day")}
            for item in snap["upcoming"]
        ],
    }
