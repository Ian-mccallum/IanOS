"""Copy one legacy general note into its verified School class session.

This is an additive operator tool for notes written before the School notebook
existed. It never edits or deletes the source row in ``notes``. The target must
be a real scheduled meeting for the supplied course and date, and an existing
non-empty School document is never overwritten.

Usage:
    .venv/bin/python scripts/import_legacy_school_note.py \
        --note-id 14 --course "STAT 120" --date 2026-08-24
    .venv/bin/python scripts/import_legacy_school_note.py \
        --note-id 14 --course "STAT 120" --date 2026-08-24 --apply

When one course has more than one verified class meeting on a date, select
the exact occurrence explicitly:
    .venv/bin/python scripts/import_legacy_school_note.py \
        --note-id 14 --course "STAT 120" --date 2026-08-24 \
        --school-item-id 1790 --apply

The default is a dry run. Repeating ``--apply`` is a no-op once the same text
is present in the target session.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, school  # noqa: E402


class LegacySchoolNoteImportError(ValueError):
    """The requested copy is ambiguous or would overwrite School work."""


_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")


def _inline_content(line: str) -> list[dict]:
    """Preserve the legacy Notes dialect's bold spans inside one paragraph."""
    content: list[dict] = []
    cursor = 0
    for match in _BOLD_RE.finditer(line):
        if match.start() > cursor:
            content.append({"type": "text", "text": line[cursor:match.start()]})
        content.append({
            "type": "text",
            "text": match.group(1),
            "marks": [{"type": "bold"}],
        })
        cursor = match.end()
    if cursor < len(line):
        content.append({"type": "text", "text": line[cursor:]})
    return content


def _is_course_date_heading(line: str, title: str, course_code: str) -> bool:
    """Only remove a title line when it is clearly a course/date heading."""
    if line.strip().casefold() != str(title or "").strip().casefold():
        return False
    match = re.fullmatch(
        rf"{re.escape(course_code)}\s*(?:[-:]\s*)?(?:(?:\d{{1,2}}[/-]\d{{1,2}}(?:[/-]\d{{2,4}})?)|(?:\d{{4}}-\d{{2}}-\d{{2}}))?",
        line.strip(),
        flags=re.IGNORECASE,
    )
    return match is not None


def legacy_note_document(title: str, body: str, *, course_code: str = "") -> dict:
    """Convert a plain legacy note to the School document's safe node subset.

    A first line is omitted only when it is a recognized course/date heading
    which repeats the stored title. A substantive first line stays intact.
    Blank lines remain blank paragraphs, so the user's grouping survives.
    General-note image tokens are refused by ``run`` rather than copied as
    meaningless text into the private School document.
    """
    lines = str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first_text = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_text is not None and _is_course_date_heading(lines[first_text], title, course_code):
        lines.pop(first_text)
        if first_text < len(lines) and not lines[first_text].strip():
            lines.pop(first_text)

    blocks: list[dict] = []
    for line in lines:
        content = _inline_content(line)
        block = {"type": "paragraph"}
        if content:
            block["content"] = content
        blocks.append(block)
    while len(blocks) > 1 and blocks[-1] == {"type": "paragraph"}:
        blocks.pop()
    return {"type": "doc", "content": blocks or [{"type": "paragraph"}]}


def _target_meeting(conn, course_code: str, session_date: str, school_item_id: int | None = None):
    """Return one verified meeting, never silently choose among real classes."""
    clauses = [
        "course_code=?", "provider=?", "substr(start_at, 1, 10)=?",
        "kind IN ('lecture', 'discussion', 'lab', 'seminar')", "archived_at IS NULL",
    ]
    params: list[object] = [course_code, school.SCHEDULE_PROVIDER, session_date]
    if school_item_id is not None:
        clauses.append("id=?")
        params.append(int(school_item_id))
    rows = conn.execute(
        f"""SELECT id, kind, start_at
              FROM school_items
             WHERE {' AND '.join(clauses)}
             ORDER BY start_at, id""",
        params,
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise LegacySchoolNoteImportError(
            "multiple verified class meetings match; pass --school-item-id"
        )
    return rows[0]


def _note_mentions_course(note: dict, course_code: str) -> bool:
    haystack = f"{note.get('title', '')}\n{note.get('body', '')}"
    return re.search(
        rf"(?<![A-Z0-9]){re.escape(course_code)}(?![A-Z0-9])",
        haystack,
        flags=re.IGNORECASE,
    ) is not None


def _existing_import_report(existing, *, expected_document: str, expected_text: str,
                            note_id: int, apply: bool) -> dict | None:
    if existing is None or not str(existing["plain_text"] or "").strip():
        return None
    if existing["document_json"] == expected_document:
        return {
            "status": "already_imported",
            "source_note_id": int(note_id),
            "session_id": int(existing["id"]),
            "characters": len(expected_text),
            "apply": apply,
        }
    if existing["plain_text"] == expected_text:
        raise LegacySchoolNoteImportError(
            "target School session has matching text but different formatting"
        )
    raise LegacySchoolNoteImportError("target School session already has different text")


def run(conn, *, note_id: int, course_code: str, session_date: str, apply: bool,
        school_item_id: int | None = None) -> dict:
    """Plan or perform one safe, idempotent legacy-note copy."""
    note = db.note(conn, int(note_id))
    if note is None or note.get("deleted_at") is not None:
        raise LegacySchoolNoteImportError("source note not found")
    course_code = " ".join(str(course_code or "").split()).upper()
    if not course_code:
        raise LegacySchoolNoteImportError("course is required")
    if not _note_mentions_course(note, course_code):
        raise LegacySchoolNoteImportError("source note does not name the target course")
    if "note-image:" in str(note.get("body") or ""):
        raise LegacySchoolNoteImportError("source note has images; copy it manually so no image is lost")

    meeting = _target_meeting(conn, course_code, session_date, school_item_id)
    if meeting is None:
        raise LegacySchoolNoteImportError("no verified class meeting matches that course and date")

    document = legacy_note_document(
        note.get("title", ""), note.get("body", ""), course_code=course_code,
    )
    expected_document, expected_text = school._normalize_note_document(document)
    if not expected_text:
        raise LegacySchoolNoteImportError("source note has no text to copy")
    existing = conn.execute(
        """SELECT id, document_json, plain_text FROM school_note_sessions
            WHERE school_item_id=? AND deleted_at IS NULL""",
        (meeting["id"],),
    ).fetchone()
    report = _existing_import_report(
        existing,
        expected_document=expected_document,
        expected_text=expected_text,
        note_id=note_id,
        apply=apply,
    )
    if report is not None:
        return report

    if not apply:
        return {
            "status": "ready",
            "source_note_id": int(note_id),
            "session_id": int(existing["id"]) if existing else None,
            "characters": len(expected_text),
            "apply": False,
        }

    session, created = school.open_note_session(conn, int(meeting["id"]))
    opened_document, _ = school._normalize_note_document(session["document"])
    report = _existing_import_report(
        {"id": session["id"], "document_json": opened_document, "plain_text": session["plain_text"]},
        expected_document=expected_document,
        expected_text=expected_text,
        note_id=note_id,
        apply=apply,
    )
    if report is not None:
        return report
    try:
        saved = school.update_note_session(
            conn,
            session["id"],
            document=document,
            expected_revision=session["revision"],
        )
    except school.SchoolNoteConflictError as exc:
        raise LegacySchoolNoteImportError(
            "target School session changed during import; review it manually"
        ) from exc
    return {
        "status": "imported",
        "source_note_id": int(note_id),
        "session_id": int(saved["id"]),
        "characters": len(saved["plain_text"]),
        "created_session": created,
        "apply": True,
    }


def _print_report(report: dict) -> None:
    mode = "APPLY" if report["apply"] else "DRY RUN"
    print(f"legacy School note import: {mode}")
    print(f"status: {report['status']}")
    print(f"source note: {report['source_note_id']}")
    print(f"School session: {report['session_id'] or 'new'}")
    print(f"characters: {report['characters']}")
    if not report["apply"]:
        print("Nothing was written. Re-run with --apply to copy the note.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a general note into a verified School session")
    parser.add_argument("--note-id", type=int, required=True)
    parser.add_argument("--course", required=True)
    parser.add_argument("--date", required=True, help="class date, YYYY-MM-DD")
    parser.add_argument("--school-item-id", type=int, help="required when the course has multiple meetings that day")
    parser.add_argument("--apply", action="store_true", help="copy the note (default: dry run)")
    args = parser.parse_args()

    conn = db.connect()
    try:
        report = run(
            conn,
            note_id=args.note_id,
            course_code=args.course,
            session_date=args.date,
            apply=args.apply,
            school_item_id=args.school_item_id,
        )
    finally:
        conn.close()
    _print_report(report)


if __name__ == "__main__":
    main()
