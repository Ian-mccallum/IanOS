"""Legacy general Notes copy safely into private School sessions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, school  # noqa: E402
from scripts import import_legacy_school_note as legacy  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    school.ensure_schema(connection)
    connection.execute(
        "INSERT INTO school_courses (code, term, name) VALUES (?,?,?)",
        ("STAT 120", "fall-2026", "Data Science Discovery"),
    )
    connection.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at,
                start_at, end_at, location)
            VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "STAT 120", "school_schedule", "stat-120:lecture:2026-08-24",
            "lecture", "Lecture", "2026-08-24T09:00", "2026-08-24T09:00",
            "2026-08-24T09:50", "Main Auditorium",
        ),
    )
    connection.commit()
    yield connection
    connection.close()


def _source_note(conn, body="STAT 120 8/24\n\n**Index:** unique row id\n\nOffice hours"):
    return db.create_note(conn, body=body)


def test_dry_run_reports_the_copy_without_writing(conn):
    # Arrange: a legacy note exists and the verified lecture has no session.
    note = _source_note(conn)
    before = db.note(conn, note["id"])

    # Act: use the default planning mode.
    report = legacy.run(
        conn, note_id=note["id"], course_code="STAT 120",
        session_date="2026-08-24", apply=False,
    )

    # Assert: the target is valid, but neither note system changed.
    assert report == {
        "status": "ready", "source_note_id": note["id"], "session_id": None,
        "characters": len("Index: unique row id\n\nOffice hours"), "apply": False,
    }
    assert conn.execute("SELECT COUNT(*) FROM school_note_sessions").fetchone()[0] == 0
    assert db.note(conn, note["id"]) == before


def test_apply_preserves_bold_copies_once_and_leaves_the_source(conn):
    # Arrange: bold legacy text is stored in the agent-readable Notes table.
    note = _source_note(conn)
    source_before = db.note(conn, note["id"])

    # Act: copy it twice to exercise the idempotency boundary.
    first = legacy.run(
        conn, note_id=note["id"], course_code="STAT 120",
        session_date="2026-08-24", apply=True,
    )
    second = legacy.run(
        conn, note_id=note["id"], course_code="STAT 120",
        session_date="2026-08-24", apply=True,
    )

    # Assert: one private session exists, formatting survived, and the source
    # row is byte-for-byte unchanged.
    assert first["status"] == "imported" and first["created_session"] is True
    assert second["status"] == "already_imported"
    assert second["session_id"] == first["session_id"]
    assert conn.execute("SELECT COUNT(*) FROM school_note_sessions").fetchone()[0] == 1
    session = school.school_note_session(conn, first["session_id"], include_document=True)
    assert session["plain_text"] == "Index: unique row id\n\nOffice hours"
    first_text = session["document"]["content"][0]["content"][0]
    assert first_text == {
        "type": "text", "text": "Index:", "marks": [{"type": "bold"}],
    }
    assert db.note(conn, note["id"]) == source_before


def test_existing_school_work_is_never_overwritten(conn):
    # Arrange: the verified School session already contains different work.
    note = _source_note(conn)
    meeting_id = conn.execute("SELECT id FROM school_items").fetchone()[0]
    session, _ = school.open_note_session(conn, meeting_id)
    school.update_note_session(
        conn,
        session["id"],
        document={"type": "doc", "content": [{
            "type": "paragraph", "content": [{"type": "text", "text": "Current School work"}],
        }]},
        expected_revision=session["revision"],
    )

    # Act / Assert: the tool refuses instead of appending or replacing text.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="different text"):
        legacy.run(
            conn, note_id=note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=True,
        )
    saved = school.school_note_session(conn, session["id"], include_document=True)
    assert saved["plain_text"] == "Current School work"


def test_images_and_mismatched_courses_require_manual_review(conn):
    # Arrange: one source has an attachment token and one has no course match.
    image_note = _source_note(conn, "STAT 120\n![board](note-image:abc123)")
    other_note = db.create_note(conn, body="ECON 110\nScarcity")

    # Act / Assert: neither ambiguous source can cross the privacy boundary.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="images"):
        legacy.run(
            conn, note_id=image_note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=True,
        )
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="does not name"):
        legacy.run(
            conn, note_id=other_note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=True,
        )
    assert conn.execute("SELECT COUNT(*) FROM school_note_sessions").fetchone()[0] == 0


def test_substantive_first_line_stays_in_the_import(conn):
    # Arrange: general Notes derives its title from the first text line, but
    # that line is content, not a "STAT 120 8/24" heading.
    note = _source_note(conn, "STAT 120 explains the sample space\n\nSecond fact")

    # Act: copy the note into its verified lecture.
    report = legacy.run(
        conn, note_id=note["id"], course_code="STAT 120",
        session_date="2026-08-24", apply=True,
    )

    # Assert: only narrowly recognized course/date headers disappear.
    session = school.school_note_session(conn, report["session_id"], include_document=True)
    assert session["plain_text"] == "STAT 120 explains the sample space\n\nSecond fact"


def test_course_match_requires_a_token_boundary(conn):
    # Arrange: a longer code must not qualify as a shorter target course.
    note = _source_note(conn, "STAT 1200\nA different class")

    # Act / Assert: the operator must review this mismatch manually.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="does not name"):
        legacy.run(
            conn, note_id=note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=False,
        )


def test_multiple_meetings_require_an_explicit_verified_item(conn):
    # Arrange: this course has a lecture and discussion on the same date.
    first_id = conn.execute("SELECT id FROM school_items").fetchone()[0]
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at,
                start_at, end_at, location)
            VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            "STAT 120", school.SCHEDULE_PROVIDER, "stat-120:discussion:2026-08-24",
            "discussion", "Discussion", "2026-08-24T14:00", "2026-08-24T14:00",
            "2026-08-24T14:50", "Science Center",
        ),
    )
    conn.commit()
    note = _source_note(conn)

    # Act / Assert: date alone cannot choose one class occurrence at random.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="multiple verified"):
        legacy.run(
            conn, note_id=note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=False,
        )
    report = legacy.run(
        conn, note_id=note["id"], course_code="STAT 120",
        session_date="2026-08-24", school_item_id=first_id, apply=False,
    )
    assert report["status"] == "ready"


def test_interleaved_school_edit_is_never_overwritten(conn, monkeypatch):
    # Arrange: another device writes after the initial empty-session check.
    note = _source_note(conn)
    real_open = school.open_note_session

    def open_then_edit(connection, school_item_id):
        opened, created = real_open(connection, school_item_id)
        saved = school.update_note_session(
            connection,
            opened["id"],
            document={"type": "doc", "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "Other device work"}],
            }]},
            expected_revision=opened["revision"],
        )
        return saved, created

    monkeypatch.setattr(legacy.school, "open_note_session", open_then_edit)

    # Act / Assert: the post-open check refuses the interleaved note rather
    # than treating its new revision as permission to replace it.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="different text"):
        legacy.run(
            conn, note_id=note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=True,
        )
    [saved] = conn.execute("SELECT plain_text FROM school_note_sessions").fetchall()
    assert saved["plain_text"] == "Other device work"


def test_same_text_with_different_school_formatting_requires_review(conn):
    # Arrange: matching words alone are not proof that the same document was
    # imported; replacing a heading with a paragraph would lose structure.
    note = _source_note(conn, "STAT 120 8/24\n\nIndex")
    meeting_id = conn.execute("SELECT id FROM school_items").fetchone()[0]
    session, _ = school.open_note_session(conn, meeting_id)
    school.update_note_session(
        conn,
        session["id"],
        document={"type": "doc", "content": [{
            "type": "heading", "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Index"}],
        }]},
        expected_revision=session["revision"],
    )

    # Act / Assert: document structure is part of idempotency evidence.
    with pytest.raises(legacy.LegacySchoolNoteImportError, match="different formatting"):
        legacy.run(
            conn, note_id=note["id"], course_code="STAT 120",
            session_date="2026-08-24", apply=True,
        )
