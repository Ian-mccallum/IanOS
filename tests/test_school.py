"""Local School data layer: safe Canvas snapshot ingestion and projections."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, plan, school  # noqa: E402
from agents import runner  # noqa: E402
from api import main  # noqa: E402
from ingest.import_canvas_calendar import records_for_school  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(main, "SCHOOL_ASSETS_DIR", tmp_path / "school-assets")
    db.connect().close()
    return TestClient(main.app)


def _inventory():
    return {
        "courses": [
            {
                "course_id": "stat-120",
                "code": "STAT 120",
                "name": "Data Science Discovery",
                "credits": 4,
                "cross_listings": ["CS/IS/STAT 120 (fa26)"],
                "meetings": [{"kind": "lecture", "days": ["MO"], "start_local": "09:00"}],
                "grading": {"categories": [{"name": "Homework", "weight_percent": 15}]},
                "key_policy_flags": {"ai_policy": {"status": "unknown"}},
                "known_major_dates": [
                    {"label": "Midterm 1", "date": "2026-09-23", "time_local": "09:00"}
                ],
            },
            {
                "course_id": "bus-120",
                "code": "BUS 120",
                "name": "Professional Responsibility and Business",
                "credits": 3,
                "meetings": [],
                "grading": {"categories": []},
                "key_policy_flags": {},
            },
        ]
    }


def _canvas_item(item_id: str, title: str = "HW 1", course_label: str = "CS/IS/STAT 120 (fa26)"):
    return {
        "external_id": item_id,
        "course_label": course_label,
        "title": title,
        "kind": "assignment",
        "due_at": "2026-08-26T23:59",
        "start_at": "2026-08-26T23:59",
        "end_at": "2026-08-26T23:59",
        "all_day": False,
        "location": "",
    }


def _freeze_school_today(monkeypatch, value: date = date(2026, 8, 24)):
    """Keep fixed-semester fixtures meaningful after their calendar week passes."""
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return value

    monkeypatch.setattr(school, "date", FrozenDate)


def _schedule_inventory():
    return {
        "calendar_projection": {
            "instruction_start": "2026-08-24",
            "instruction_end": "2026-09-08",
            "excluded_dates": ["2026-09-07"],
        },
        "courses": [
            {
                "course_id": "stat-120",
                "code": "STAT 120",
                "name": "Data Science Discovery",
                "credits": 4,
                "meetings": [
                    {
                        "kind": "lecture",
                        "days": ["MO"],
                        "start_local": "09:00",
                        "end_local": "09:50",
                        "location": "Main Auditorium",
                    }
                ],
                "known_major_dates": [{"label": "Midterm 1", "date": "2026-08-26"}],
            },
            {
                "course_id": "bus-120",
                "code": "BUS 120",
                "name": "Professional Responsibility and Business",
                "credits": 3,
                "meetings": [
                    {
                        "kind": "lecture",
                        "days": ["TU"],
                        "start_local": "16:00",
                        "end_local": "16:50",
                        "location": "Zoom",
                    }
                ],
            },
        ],
    }


def test_canvas_snapshot_is_normalized_and_projected_to_the_shared_planner(conn, monkeypatch):
    # Arrange: only safe, local course metadata exists before an import.
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _inventory())

    # Act: bring in the one Canvas-derived due time.
    report = school.import_canvas_items(conn, [_canvas_item("canvas:hw-1")])
    snapshot = school.dashboard_snapshot(conn, days=30)

    # Assert: it is mapped to a known course, shows in School, and appears as
    # a school commitment for Plan. Raw Canvas identity/source fields do not
    # leave the School projection.
    assert report == {"imported": 1, "ignored": 0, "archived": 0}
    assert snapshot["summary"]["course_count"] == 2
    item = next(item for item in snapshot["upcoming"] if item["title"] == "HW 1")
    assert item["course_code"] == "STAT 120"
    assert item["due_at"] == "2026-08-26T23:59"
    assert "external_item_id" not in item and "provider" not in item
    event = conn.execute(
        "SELECT * FROM calendar_events WHERE summary='STAT 120 · HW 1'"
    ).fetchone()
    assert event["date"] == "2026-08-26"
    assert event["start_time"] == "23:59"
    assert event["summary"] == "STAT 120 · HW 1"


def test_verified_meetings_and_syllabus_milestones_project_to_shared_plan(conn):
    # Arrange: the syllabus supplies both recurring meetings and a date-only
    # major milestone; Plan is still the sole shared calendar.
    school.seed_inventory(conn, _schedule_inventory())

    # Act: read the same commitment rows Plan uses to find free time.
    monday = db.calendar_for_date(conn, "2026-08-24")
    wednesday = db.calendar_for_date(conn, "2026-08-26")

    # Assert: the verified class blocks time, while the milestone stays an
    # all-day deadline signal rather than becoming a midnight appointment.
    assert len(monday) == 1
    assert {key: monday[0][key] for key in (
        "date", "start_time", "end_time", "summary", "category", "duration_min",
    )} == {
        "date": "2026-08-24",
        "start_time": "09:00",
        "end_time": "09:50",
        "summary": "STAT 120 · Lecture · Main Auditorium",
        "category": "school",
        "duration_min": 50,
    }
    assert plan.next_free_slot([], monday, 60, "08:30") == ("10:00", "11:00")
    assert [(item["summary"], item["start_time"], item["end_time"])
            for item in wednesday] == [("STAT 120 · Midterm 1", None, None)]


def test_verified_schedule_skips_uiuc_no_class_dates_and_respects_course_window(conn):
    # Arrange: the root calendar excludes Labor Day, while a short course has
    # its own term window.
    inventory = _schedule_inventory()
    inventory["courses"][1]["term_dates"] = {
        "start_date": "2026-08-24", "end_date": "2026-08-28",
    }

    # Act.
    school.seed_inventory(conn, inventory)

    # Assert: Monday classes appear only on instruction days, and the BUS
    # meeting ends with its course window instead of running all semester.
    stat_dates = [row["date"] for row in conn.execute(
        "SELECT date FROM calendar_events WHERE summary LIKE 'STAT 120 · Lecture%' ORDER BY date"
    )]
    bus_dates = [row["date"] for row in conn.execute(
        "SELECT date FROM calendar_events WHERE summary LIKE 'BUS 120 · Lecture%' ORDER BY date"
    )]
    assert stat_dates == ["2026-08-24", "2026-08-31"]
    assert bus_dates == ["2026-08-25"]


def test_verified_schedule_replaces_generic_canvas_class_shell_but_keeps_special_event(conn, monkeypatch):
    # Arrange: Canvas contains a broken 11:59 PM class shell and a genuine
    # one-off panel. The verified Tuesday meeting is the canonical schedule.
    inventory = _schedule_inventory()
    inventory["calendar_projection"]["instruction_end"] = "2026-08-25"
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 24)

    monkeypatch.setattr(school, "date", FixedDate)
    school.seed_inventory(conn, inventory)
    generic = {
        "external_id": "canvas:class-shell",
        "course_label": "bus-120",
        "title": "Week 1: Tuesday Class (Online)",
        "kind": "class",
        "due_at": "2026-08-25T23:59",
        "start_at": "2026-08-25T23:59",
        "end_at": "2026-08-25T23:59",
        "all_day": False,
        "location": "",
    }
    panel = {
        "external_id": "canvas:panel",
        "course_label": "bus-120",
        "title": "BUS 120 guest speaker panel",
        "kind": "class",
        "due_at": "2026-08-25T17:00",
        "start_at": "2026-08-25T17:00",
        "end_at": "2026-08-25T18:15",
        "all_day": False,
        "location": "Main Auditorium",
    }

    # Act.
    school.import_canvas_items(conn, [generic, panel])
    events = db.calendar_for_date(conn, "2026-08-25")

    # Assert: Plan gets the trustworthy 4:00–4:50 class and the panel, never
    # the unusable late-night duplicate.
    assert [(item["summary"], item["start_time"], item["end_time"], item["duration_min"])
            for item in events] == [
        ("BUS 120 · Lecture · Zoom", "16:00", "16:50", 50),
        ("BUS 120 · BUS 120 guest speaker panel", "17:00", "18:15", 75),
    ]
    queue = school.dashboard_snapshot(conn, days=20)["upcoming"]
    assert [item["title"] for item in queue if item["course_code"] == "BUS 120"] == [
        "BUS 120 guest speaker panel"
    ]


def test_new_canvas_snapshot_archives_removed_item_and_deletes_only_its_projection(conn):
    # Arrange: import an initial Canvas snapshot and an unrelated calendar event.
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item("canvas:old", "Old homework")])
    db.upsert_calendar_event(
        conn, date="2026-08-26", start_time="12:00", end_time="12:30",
        summary="Lunch", category="personal", duration_min=30, hash="unrelated-calendar-event",
    )
    conn.commit()

    # Act: Canvas stops listing the old item and lists a new one instead.
    report = school.import_canvas_items(conn, [_canvas_item("canvas:new", "New homework")])

    # Assert: the stale school projection is gone, but another calendar source
    # is untouched. This is the guard that keeps Canvas imports reversible.
    assert report["archived"] == 1
    events = [dict(row) for row in conn.execute(
        """SELECT summary, category FROM calendar_events
           WHERE summary != 'STAT 120 · Midterm 1' ORDER BY summary"""
    )]
    assert events == [
        {"summary": "Lunch", "category": "personal"},
        {"summary": "STAT 120 · New homework", "category": "school"},
    ]
    archived = conn.execute(
        "SELECT archived_at FROM school_items WHERE provider=? AND external_item_id=?",
        (school.CANVAS_PROVIDER, "canvas:old"),
    ).fetchone()
    assert archived["archived_at"] is not None


def test_unknown_canvas_course_is_ignored_without_erasing_a_valid_snapshot(conn):
    # Arrange: establish a valid school snapshot.
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item("canvas:kept")])

    # Act: an unrelated Canvas workshop appears in the next export.
    report = school.import_canvas_items(conn, [
        _canvas_item("canvas:kept"),
        _canvas_item("canvas:workshop", "ACE IT workshop", "vcstud_cc_open_249979"),
    ])

    # Assert: unrecognized calendars never pose as one of Ian's courses.
    assert report["imported"] == 1 and report["ignored"] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM school_items WHERE provider=? AND archived_at IS NULL",
        (school.CANVAS_PROVIDER,),
    ).fetchone()[0] == 1


def test_import_adapter_strips_calendar_identifier_and_preserves_safe_schedule_data():
    # Arrange: a normalized parser event with a trailing Canvas calendar label.
    event = {
        "event_id": "canvas:opaque-id",
        "course_label": "bus_120_120268_263096",
        "summary": "Checkpoint 1 [bus_120_120268_263096]",
        "date": "2026-08-27",
        "end_date": "2026-08-27",
        "start_time": "23:59",
        "end_time": "23:59",
        "is_all_day": False,
        "is_deadline": True,
        "location": None,
    }

    # Act.
    [record] = records_for_school([event])

    # Assert: display data stays clean, while the opaque identity remains only
    # in the local importer contract.
    assert record["title"] == "Checkpoint 1"
    assert record["course_label"] == "bus_120_120268_263096"
    assert record["due_at"] == "2026-08-27T23:59"
    assert record["kind"] == "assignment"


def test_canvas_attendance_class_is_not_mislabeled_as_homework():
    # Canvas often emits attendance-bearing class entries as a late-night
    # zero-duration event. The human-facing title wins over that export quirk.
    event = {
        "event_id": "canvas:opaque-class-id",
        "course_label": "bus_120_120268_263096",
        "summary": "Week 1: Friday Class (In-Person) | August 28 [bus_120_120268_263096]",
        "date": "2026-08-28",
        "end_date": "2026-08-28",
        "start_time": "23:59",
        "end_time": "23:59",
        "is_all_day": False,
        "is_deadline": True,
        "location": "",
    }

    [record] = records_for_school([event])

    assert record["title"] == "Week 1: Friday Class (In-Person) | August 28"
    assert record["kind"] == "class"


def test_only_watchdog_and_chief_receive_the_read_only_school_tool(conn, monkeypatch):
    """SPEC-v37 3.3: advisor (Dumbledore) merged into watchdog, which now
    owns the detailed course-level access advisor used to get. advisor
    itself is retired (active: false) and no longer receives it."""
    # Arrange: a minimal populated School database.
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item("canvas:agent")])

    # Act: each role attempts the same tool call.
    runner.RUN.update(role="watchdog", conn=conn, role_domains=["all"])
    watchdog = json.loads(asyncio.run(runner.read_school.handler({"days": 7}))["content"][0]["text"])
    runner.RUN.update(role="chief", conn=conn, role_domains=["business"])
    chief = json.loads(asyncio.run(runner.read_school.handler({"days": 7}))["content"][0]["text"])
    runner.RUN.update(role="cfo", conn=conn, role_domains=["finance"])
    denied = asyncio.run(runner.read_school.handler({"days": 7}))

    # Assert: Dumbledore receives course-level planning context, Fury gets
    # aggregates, and another specialist is blocked. Nobody receives Canvas
    # identity, URLs, assignment content, or a credential.
    assert watchdog["courses"][0]["code"] == "BUS 120"
    assert "policies" in watchdog["courses"][0]
    assert chief["workload_by_course"]["STAT 120"] == 1
    assert "courses" not in chief
    assert denied["is_error"] is True
    assert "read_school" not in runner.ALLOWLISTS["cfo"]
    assert "read_school" in runner.chat_allow(["school"], "chief")
    assert "read_school" not in runner.chat_allow([], "chief")
    assert "read_school" not in runner.chat_allow(["school"], "cfo")
    assert "external_item_id" not in json.dumps(watchdog)


def test_semester_import_does_not_make_generic_calendar_reads_unbounded(conn):
    # Arrange: a live feed can include the entire semester, but calendar-aware
    # agents should receive a usable window rather than hundreds of rows.
    today = date.today()
    events = [
        (today - timedelta(days=4), "past outside", 30),
        (today - timedelta(days=2), "past inside", 60),
        (today + timedelta(days=2), "future inside", 90),
        (today + timedelta(days=4), "future outside", 120),
    ]
    for index, (day, summary, duration) in enumerate(events):
        db.upsert_calendar_event(
            conn, date=day.isoformat(), start_time="09:00", end_time="10:00",
            summary=summary, category="school", duration_min=duration, hash=f"calendar-window-{index}",
        )
    conn.commit()

    # Act.
    window = db.recent_calendar(conn, days=3)
    completed_hours = db.calendar_hours_by_category(conn, days=3)

    # Assert: nearby upcoming work is visible, distant semester events are
    # not, and actual-hours metrics never count future commitments.
    assert [event["summary"] for event in window] == ["past inside", "future inside"]
    assert completed_hours == {"school": 1.0}


# ------------------------------------------------------- school note sessions

def _school_note_doc(text: str):
    return {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }],
    }


def test_school_note_launch_is_verified_idempotent_and_does_not_duplicate_plan(client):
    # Arrange: a verified Tuesday BUS meeting is the canonical launch target.
    conn = db.connect()
    school.seed_inventory(conn, _schedule_inventory())
    before_calendar = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    conn.close()

    launches = client.get("/api/school/note-sessions/today?date=2026-08-25")
    assert launches.status_code == 200
    [bus] = launches.json()["meetings"]
    assert {key: bus[key] for key in ("course_code", "kind", "start_at", "end_at")} == {
        "course_code": "BUS 120", "kind": "lecture",
        "start_at": "2026-08-25T16:00", "end_at": "2026-08-25T16:50",
    }
    assert "provider" not in bus and "external_item_id" not in bus

    # Act: laptop/phone double taps both open the exact same record.
    first = client.post("/api/school/note-sessions/open", json={"school_item_id": bus["school_item_id"]})
    second = client.post("/api/school/note-sessions/open", json={"school_item_id": bus["school_item_id"]})

    # Assert: there is one note tied to this one stable meeting and no new
    # calendar event or Plan projection was manufactured as a side effect.
    assert first.status_code == second.status_code == 200
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["session"]["id"] == second.json()["session"]["id"]
    session = first.json()["session"]
    assert session["session_type"] == "meeting"
    assert session["meeting"]["id"] == bus["school_item_id"]
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM school_note_sessions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == before_calendar
    conn.close()


def test_school_note_autosave_is_revision_safe_private_and_async_does_not_fake_a_meeting(client):
    # Arrange: the academic inventory includes one asynchronous course.
    inventory = _schedule_inventory()
    inventory["courses"].append({
        "course_id": "anth-210", "code": "ANTH 210", "name": "Forensic Science",
        "credits": 4, "meetings": [], "grading": {"categories": []},
    })
    conn = db.connect()
    school.seed_inventory(conn, inventory)
    bus_id = school.note_launches_for_date(conn, "2026-08-25")[0]["school_item_id"]
    conn.close()
    opened = client.post("/api/school/note-sessions/open", json={"school_item_id": bus_id}).json()["session"]

    # Act: one client saves, then an older client attempts to overwrite it.
    sentinel = "PRIVATE CLASS THOUGHT"
    saved = client.patch(
        f"/api/school/note-sessions/{opened['id']}",
        json={"document": _school_note_doc(sentinel), "expected_revision": opened["revision"]},
    )
    stale = client.patch(
        f"/api/school/note-sessions/{opened['id']}",
        json={"document": _school_note_doc("older tab"), "expected_revision": opened["revision"]},
    )
    async_open = client.post(
        "/api/school/courses/ANTH%20210/note-sessions",
        json={"session_type": "async", "session_date": "2026-08-25"},
    )
    async_again = client.post(
        "/api/school/courses/ANTH%20210/note-sessions",
        json={"session_type": "async", "session_date": "2026-08-26"},
    )

    # Assert: newest content wins, unknown/rich-JSON inputs are guarded, and
    # ANTH creates an on-demand workspace rather than a fabricated class slot.
    assert saved.status_code == 200
    assert saved.json()["revision"] == opened["revision"] + 1
    assert saved.json()["plain_text"] == sentinel
    assert stale.status_code == 409
    assert async_open.status_code == 200
    async_session = async_open.json()["session"]
    assert async_session["session_type"] == "async"
    assert async_session["session_date"] == "2026-08-24"
    assert async_session["meeting"] is None
    assert async_again.status_code == 200
    assert async_again.json()["created"] is False
    assert async_again.json()["session"]["id"] == async_session["id"]
    assert client.post(
        "/api/school/courses/BUS%20120/note-sessions",
        json={"session_type": "async", "session_date": "2026-08-25"},
    ).status_code == 422
    assert client.post(
        "/api/school/courses/ANTH%20210/note-sessions",
        json={"session_type": "study", "session_date": "2026-08-25"},
    ).status_code == 422
    assert client.patch(
        f"/api/school/note-sessions/{opened['id']}",
        json={"document": {"type": "doc", "content": [{"type": "table"}]},
         "expected_revision": saved.json()["revision"]},
    ).status_code == 422

    # A School-note body belongs only to the dedicated session route. It never
    # joins the polling state or the existing School/Notes agent projections.
    timeline = client.get("/api/school/courses/BUS%20120/note-sessions").json()["sessions"]
    assert "document" not in timeline[0] and "plain_text" not in timeline[0]
    assert sentinel in client.get(f"/api/school/note-sessions/{opened['id']}").text
    assert sentinel not in client.get("/api/state").text
    conn = db.connect()
    assert sentinel not in json.dumps(school.agent_snapshot(conn, days=20))
    conn.close()


def test_schedule_correction_keeps_the_existing_daily_note_on_the_same_occurrence(conn):
    # Arrange: create a note before an instructor corrects the room/time.
    inventory = _schedule_inventory()
    school.seed_inventory(conn, inventory)
    original = school.note_launches_for_date(conn, "2026-08-25")[0]
    opened, created = school.open_note_session(conn, original["school_item_id"])
    assert created is True

    # Act: a verified schedule correction changes mutable display fields but
    # not the ordered weekly meeting identity.
    inventory["courses"][1]["meetings"][0].update({
        "start_local": "16:10", "end_local": "17:00", "location": "New Zoom room",
    })
    school.seed_inventory(conn, inventory)
    [corrected] = school.note_launches_for_date(conn, "2026-08-25")

    # Assert: the calendar occurrence was updated in place and the existing
    # daily note follows it. There is no parallel live BUS note for one class.
    assert corrected["school_item_id"] == original["school_item_id"]
    assert corrected["start_at"] == "2026-08-25T16:10"
    resumed, created_again = school.open_note_session(conn, corrected["school_item_id"])
    assert created_again is False
    assert resumed["id"] == opened["id"]
    assert resumed["meeting"]["location"] == "New Zoom room"
    assert conn.execute("SELECT COUNT(*) FROM school_note_sessions").fetchone()[0] == 1


def test_plan_only_marks_verified_school_commitments_as_note_launches(client):
    # Arrange: the same Plan day has one seeded class and one unrelated event.
    conn = db.connect()
    school.seed_inventory(conn, _schedule_inventory())
    db.upsert_calendar_event(
        conn, date="2026-08-25", start_time="12:00", end_time="12:30",
        summary="Lunch with a friend", category="personal", duration_min=30,
        hash="personal-calendar-event",
    )
    conn.commit()
    conn.close()

    # Act: Plan receives the generic commitments it normally renders.
    response = client.get("/api/day?date=2026-08-25")

    # Assert: only the server-resolved schedule projection gets the actionable
    # launch payload. A title or time collision in another calendar cannot
    # create a class note entry point in the browser.
    assert response.status_code == 200
    commitments = {item["summary"]: item for item in response.json()["commitments"]}
    bus = commitments["BUS 120 · Lecture · Zoom"]
    assert bus["school_note_launch"]["course_code"] == "BUS 120"
    assert bus["school_note_launch"]["calendar_event_id"] == bus["id"]
    assert "school_note_launch" not in commitments["Lunch with a friend"]


# -------------------------------------------------------- school file library

def _seed_school_assets(client):
    """Arrange a verified course and one real BUS daily note for asset tests."""
    conn = db.connect()
    school.seed_inventory(conn, _schedule_inventory())
    bus_item = school.note_launches_for_date(conn, "2026-08-25")[0]["school_item_id"]
    bus_session, _ = school.open_note_session(conn, bus_item)
    conn.close()
    return bus_session


def test_school_asset_upload_list_download_is_safe_and_private(client):
    # Arrange: a course-library PDF has a deliberately traversal-looking
    # client filename. Its bytes are a real-enough PDF header for the strict
    # declared-type check, not text that merely calls itself a PDF.
    _seed_school_assets(client)
    payload = b"%PDF-1.7\nprivate course material\n"

    # Act: upload, list, and download through the dedicated School routes.
    uploaded = client.post(
        "/api/school/courses/BUS%20120/assets",
        data={"category": "slides"},
        files={"file": ("../../PRIVATE-SLIDES-XYZ.pdf", payload, "application/pdf")},
    )
    assert uploaded.status_code == 200
    asset = uploaded.json()["asset"]
    listed = client.get("/api/school/courses/BUS%20120/assets")
    downloaded = client.get(f"/api/school/assets/{asset['id']}/download")

    # Assert: browser-facing metadata is useful but never leaks the opaque
    # token/storage key; downloads are forced attachments with private-cache
    # headers. The generic state/agent projection never sees the file either.
    assert uploaded.headers["cache-control"] == "no-store"
    assert asset == {
        "id": asset["id"], "course_code": "BUS 120", "session_id": None,
        "display_name": "PRIVATE-SLIDES-XYZ.pdf", "mime_type": "application/pdf",
        "file_type": "pdf", "extension": "pdf", "byte_size": len(payload),
        "category": "slides", "created_at": asset["created_at"], "updated_at": asset["updated_at"],
    }
    assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
    assert listed.json()["assets"] == [asset]
    conn = db.connect()
    stored = conn.execute(
        "SELECT token, storage_path FROM school_note_assets WHERE id=?", (asset["id"],)
    ).fetchone()
    agent_snapshot = school.agent_snapshot(conn, days=20)
    conn.close()
    public_json = json.dumps({"upload": uploaded.json(), "list": listed.json()})
    assert stored["token"] not in public_json and stored["storage_path"] not in public_json
    assert stored["token"] not in client.get("/api/state").text
    assert stored["storage_path"] not in client.get("/api/state").text
    assert "PRIVATE-SLIDES-XYZ.pdf" not in client.get("/api/state").text
    assert "PRIVATE-SLIDES-XYZ.pdf" not in json.dumps(agent_snapshot)
    assert downloaded.status_code == 200 and downloaded.content == payload
    assert downloaded.headers["content-type"].startswith("application/pdf")
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert "PRIVATE-SLIDES-XYZ.pdf" in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["x-content-type-options"] == "nosniff"


def test_school_asset_rejects_bad_extension_mime_magic_and_size_without_writes(client, monkeypatch):
    # Arrange: a seeded course and an intentionally tiny cap make each invalid
    # path deterministic. No upload is allowed to leave an orphaned server file.
    _seed_school_assets(client)
    assert school.school_asset_file_spec("slides.pdf", "")["mime_type"] == "application/pdf"

    # Act: lie about MIME, use an executable extension, lie about PDF magic,
    # and then exceed the 25 MB-style streaming cap (temporarily lowered here).
    bad_mime = client.post(
        "/api/school/courses/BUS%20120/assets",
        files={"file": ("slides.pdf", b"%PDF-1.7\n", "text/plain")},
    )
    bad_extension = client.post(
        "/api/school/courses/BUS%20120/assets",
        files={"file": ("slides.exe", b"MZ", "application/octet-stream")},
    )
    bad_magic = client.post(
        "/api/school/courses/BUS%20120/assets",
        files={"file": ("slides.pdf", b"MZ not a PDF", "application/pdf")},
    )
    monkeypatch.setattr(school, "_SCHOOL_ASSET_MAX_BYTES", 8)
    too_big = client.post(
        "/api/school/courses/BUS%20120/assets",
        files={"file": ("large.pdf", b"%PDF-1.7 enough bytes", "application/pdf")},
    )

    # Assert: all four guards reject before metadata is saved and no temporary
    # material remains in the distinct School storage tree.
    assert bad_mime.status_code == 422
    assert bad_extension.status_code == 422
    assert bad_magic.status_code == 422
    assert too_big.status_code == 413
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM school_note_assets").fetchone()[0] == 0
    conn.close()
    assert list(path for path in main.SCHOOL_ASSETS_DIR.rglob("*") if path.is_file()) == []


def test_school_asset_enforces_course_session_ownership_and_delete_cleans_bytes(client):
    # Arrange: BUS has a real daily note. STAT is a different course and must
    # never accept an upload filed against that BUS session id.
    bus_session = _seed_school_assets(client)
    content = b"%PDF-1.7\nweek one handout\n"

    # Act: try cross-course ownership first, then file against the correct
    # session and remove it through the asset id (never a path/token).
    cross_course = client.post(
        "/api/school/courses/STAT%20120/assets",
        data={"session_id": str(bus_session["id"])},
        files={"file": ("handout.pdf", content, "application/pdf")},
    )
    uploaded = client.post(
        "/api/school/courses/BUS%20120/assets",
        data={"session_id": str(bus_session["id"]), "category": "reading"},
        files={"file": ("handout.pdf", content, "application/pdf")},
    )
    assert uploaded.status_code == 200
    asset = uploaded.json()["asset"]
    conn = db.connect()
    storage_key = conn.execute(
        "SELECT storage_path FROM school_note_assets WHERE id=?", (asset["id"],)
    ).fetchone()["storage_path"]
    path = main.SCHOOL_ASSETS_DIR / storage_key
    conn.close()
    assert path.exists()
    deleted = client.delete(f"/api/school/assets/{asset['id']}")

    # Assert: mismatched ownership is rejected, the valid session association
    # is preserved, and deletion removes metadata plus its server file without
    # leaving a token/path in the response.
    assert cross_course.status_code == 422
    assert asset["session_id"] == bus_session["id"]
    assert deleted.status_code == 200
    assert deleted.headers["cache-control"] == "no-store"
    assert deleted.json() == {"ok": True, "id": asset["id"]}
    assert not path.exists()
    assert client.get("/api/school/courses/BUS%20120/assets").json() == {"assets": []}
    missing = client.get(f"/api/school/assets/{asset['id']}/download")
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM school_note_assets WHERE id=?", (asset["id"],)).fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------- school study aids

def _saved_study_session(client, text: str = "PRIVATE NOTE: correlation is not causation"):
    """Arrange one saved BUS session with server-derived plain text."""
    opened = _seed_school_assets(client)
    saved = client.patch(
        f"/api/school/note-sessions/{opened['id']}",
        json={"document": _school_note_doc(text), "expected_revision": opened["revision"]},
    )
    assert saved.status_code == 200
    return saved.json()


def _valid_summary_output():
    return {
        "kind": "summary",
        "title": "Association and causation",
        "summary": "Association alone does not establish a causal relationship.",
        "key_points": ["Look for confounders before inferring cause."],
        "review_questions": ["What additional evidence would support causation?"],
    }


def test_school_study_is_opt_in_revision_bound_and_private(client, monkeypatch):
    # Arrange: a real daily note is saved, but provider execution is held so
    # this API test can examine the durable state without an external request.
    session = _saved_study_session(client)
    monkeypatch.setattr(main, "_start_school_study_worker", lambda _artifact_id: None)
    conn = db.connect()
    before_calendar = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    conn.close()

    # Act: enable the one deliberate setting, request once from two taps, and
    # complete it through the data-layer worker boundary.
    prefs = client.get("/api/school/ai/settings")
    blocked = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "summary"},
    )
    enabled = client.patch("/api/school/ai/settings", json={"enabled": True})
    first = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "summary"},
    )
    second = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "summary"},
    )
    artifact = first.json()["artifact"]
    conn = db.connect()
    job = school.claim_school_study_artifact(conn, artifact["id"])
    completed = school.complete_school_study_artifact(conn, artifact["id"], _valid_summary_output())
    conn.close()
    listed = client.get(f"/api/school/note-sessions/{session['id']}/study-artifacts")
    accepted = client.post(f"/api/school/study-artifacts/{artifact['id']}/accept")
    edited = client.patch(
        f"/api/school/note-sessions/{session['id']}",
        json={"document": _school_note_doc("PRIVATE NOTE: a new saved thought"),
              "expected_revision": session["revision"]},
    )
    stale = client.post(f"/api/school/study-artifacts/{artifact['id']}/accept")

    # Assert: consent/no-store are explicit, one live request is idempotent,
    # the worker sees only the plain-text note, and an edit makes an old aid
    # unavailable rather than letting it be accepted as current.
    assert prefs.status_code == 200 and prefs.headers["cache-control"] == "no-store"
    assert prefs.json()["enabled"] is False
    assert blocked.status_code == 422 and blocked.headers["cache-control"] == "no-store"
    assert enabled.status_code == 200 and enabled.json()["enabled"] is True
    assert first.status_code == 202 and first.json()["created"] is True
    assert second.status_code == 200 and second.json() == {"artifact": artifact, "created": False}
    assert artifact["status"] == "QUEUED" and artifact["output"] is None
    assert set(job) == {"id", "kind", "source_note_revision", "model", "plain_text"}
    assert job["plain_text"] == "PRIVATE NOTE: correlation is not causation"
    assert completed["status"] == "DRAFT" and completed["output"] == _valid_summary_output()
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["artifacts"][0]["status"] == "DRAFT"
    assert accepted.json()["artifact"]["status"] == "ACCEPTED"
    assert edited.status_code == 200
    assert stale.status_code == 200 and stale.json()["artifact"]["status"] == "STALE"
    assert stale.json()["artifact"]["output"] is None
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0] == before_calendar
    assert "PRIVATE NOTE" not in json.dumps(school.agent_snapshot(conn, days=20))
    conn.close()
    state = client.get("/api/state").text
    assert "PRIVATE NOTE" not in state and "Association and causation" not in state


def test_school_study_worker_is_zero_tool_and_rejects_bad_model_shapes(client, monkeypatch):
    # Arrange: save a note, enable manual study mode, and stop the route from
    # spawning a real provider thread while this test substitutes a safe one.
    session = _saved_study_session(client, "PRIVATE WORKER NOTE: sampling variability")
    monkeypatch.setattr(main, "_start_school_study_worker", lambda _artifact_id: None)
    assert client.patch("/api/school/ai/settings", json={"enabled": True}).status_code == 200
    requested = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "flashcards"},
    ).json()["artifact"]
    seen = []

    async def good_reply(kind, note_plain_text, model):
        seen.append((kind, note_plain_text, model))
        return json.dumps({
            "kind": "flashcards",
            "cards": [{"front": "What varies?", "back": "A sample statistic across samples."}],
        })

    monkeypatch.setattr(main, "_school_study_model_reply", good_reply)

    # Act: run the isolated worker, then queue malformed practice output and
    # turn the mode off before a queued job can begin.
    main._run_school_study_worker(requested["id"])
    good = client.get(f"/api/school/note-sessions/{session['id']}/study-artifacts").json()["artifacts"][0]
    malformed = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "practice"},
    ).json()["artifact"]

    async def bad_reply(_kind, _note_plain_text, _model):
        return json.dumps({
            "kind": "practice",
            "questions": [{"question": "Q", "hint": "H", "skill": "S", "answer": "not allowed"}],
        })

    monkeypatch.setattr(main, "_school_study_model_reply", bad_reply)
    main._run_school_study_worker(malformed["id"])
    failed = next(item for item in client.get(
        f"/api/school/note-sessions/{session['id']}/study-artifacts"
    ).json()["artifacts"] if item["id"] == malformed["id"])
    queued = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "study_plan"},
    ).json()["artifact"]
    disabled = client.patch("/api/school/ai/settings", json={"enabled": False})
    main._run_school_study_worker(queued["id"])
    discarded = next(item for item in client.get(
        f"/api/school/note-sessions/{session['id']}/study-artifacts"
    ).json()["artifacts"] if item["id"] == queued["id"])

    # Assert: only private note text enters the worker, invalid JSON never
    # lands as an artifact, and disabling prevents queued/running work from
    # becoming visible even if a thread wakes up later.
    assert seen == [("flashcards", "PRIVATE WORKER NOTE: sampling variability", main.SCHOOL_STUDY_MODEL)]
    assert good["status"] == "DRAFT" and good["output"]["kind"] == "flashcards"
    assert failed["status"] == "FAILED" and failed["error_code"] == "invalid_reply"
    assert disabled.json()["enabled"] is False
    assert discarded["status"] == "DISCARDED" and discarded["output"] is None


def test_a_course_ai_policy_does_not_gate_study_tools(client, monkeypatch):
    """Ian, 2026-09-09: a syllabus AI policy no longer blocks his study aids.

    Study aids are built from his own notes for his own revision, and which
    course they came from is not the machine's call. Consent is still the
    gate, and it is the only one: this test exists to prove the course policy
    stopped mattering WITHOUT the consent wall quietly going with it.
    """
    # Arrange: the strictest possible policy on the course.
    session = _saved_study_session(client)
    monkeypatch.setattr(main, "_start_school_study_worker", lambda _artifact_id: None)
    conn = db.connect()
    conn.execute(
        "UPDATE school_courses SET policy_json=? WHERE code='BUS 120'",
        (json.dumps({"ai_policy": {"status": "prohibited"}}),),
    )
    conn.commit()
    conn.close()

    # Act 1: consent off. Still refused, and for the consent reason.
    assert client.patch("/api/school/ai/settings", json={"enabled": False}).status_code == 200
    denied = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "summary"},
    )
    assert denied.status_code == 422
    assert "study mode" in denied.json()["detail"]
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM school_study_artifacts").fetchone()[0] == 0
    conn.close()

    # Act 2: consent on. The prohibited course is now allowed through.
    assert client.patch("/api/school/ai/settings", json={"enabled": True}).status_code == 200
    allowed = client.post(
        f"/api/school/note-sessions/{session['id']}/study-artifacts", json={"kind": "summary"},
    )

    # Assert: queued, and the route still carries its private-cache header.
    assert allowed.status_code in (200, 201, 202), allowed.json()
    assert allowed.headers["cache-control"] == "no-store"
    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) FROM school_study_artifacts").fetchone()[0] == 1
    conn.close()


def test_school_study_model_request_has_no_mcp_or_builtin_tools(monkeypatch):
    # Arrange: replace the provider SDK surface with a tiny async fake. This
    # proves the request options themselves, without sending a note anywhere.
    from agents import runner

    captured = {}

    class FakeResult:
        is_error = False
        result = '{"kind":"summary","title":"T","summary":"S","key_points":["P"],"review_questions":[]}'

    def fake_options(**kwargs):
        captured["options"] = kwargs
        return kwargs

    async def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["query_options"] = options
        yield FakeResult()

    monkeypatch.setattr(runner, "ClaudeAgentOptions", fake_options)
    monkeypatch.setattr(runner, "ResultMessage", FakeResult)
    monkeypatch.setattr(runner, "query", fake_query)
    monkeypatch.setattr(runner, "find_cli", lambda: None)

    # Act.
    result = asyncio.run(main._school_study_model_reply("summary", "private note", main.SCHOOL_STUDY_MODEL))

    # Assert: the worker has no ianOS MCP server, no allowed/builtin tools, and
    # every registered ianOS tool is explicitly denied.
    options = captured["options"]
    assert result.startswith('{"kind":"summary"')
    assert options["mcp_servers"] == {}
    assert options["tools"] == [] and options["allowed_tools"] == []
    assert set(options["disallowed_tools"]) == {f"mcp__ianos__{name}" for name in runner.ALL_TOOLS}
    assert "UNTRUSTED_NOTE_TEXT_JSON" in captured["prompt"]


# --------------------------------------------------------- homework completion


def _seed_with_item(conn, item_id: str = "canvas:hw1"):
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item(item_id)])
    return conn.execute(
        "SELECT id FROM school_items WHERE external_item_id=?", (item_id,)
    ).fetchone()["id"]


def test_crossing_off_homework_survives_a_canvas_resync(conn):
    """The reason completion is its own table rather than a school_items column.

    `import_canvas_items` rewrites every row from the feed and
    `_archive_missing_items` archives whatever the feed drops, so a column on
    school_items would be erased the next time Canvas synced. Finishing your
    homework must outlive the importer that owns the assignment record.
    """
    row_id = _seed_with_item(conn)
    assert school.set_school_item_done(conn, row_id, True)["done"] is True

    # A full re-import of the same snapshot.
    school.import_canvas_items(conn, [_canvas_item("canvas:hw1")])
    still = school._item_row(
        conn.execute(school._SCHOOL_ITEM_SELECT + " WHERE i.id=?", (row_id,)).fetchone()
    )
    assert still["done"] is True, "a Canvas re-sync erased Ian's own completion"

    # Dropped from the feed (archived), then returning in a later snapshot.
    school.import_canvas_items(conn, [_canvas_item("canvas:other", title="HW 2")])
    school.import_canvas_items(conn, [_canvas_item("canvas:hw1")])
    returned = school._item_row(
        conn.execute(
            school._SCHOOL_ITEM_SELECT + " WHERE i.external_item_id='canvas:hw1'"
        ).fetchone()
    )
    assert returned["done"] is True, "archive-then-return lost the completion"


def test_completion_toggles_both_ways_and_is_idempotent(conn):
    row_id = _seed_with_item(conn)
    assert school.set_school_item_done(conn, row_id, True)["done"] is True
    # Marking done twice must not raise on the PRIMARY KEY.
    assert school.set_school_item_done(conn, row_id, True)["done"] is True
    assert school.set_school_item_done(conn, row_id, False)["done"] is False
    # Un-completing something already open is equally harmless.
    assert school.set_school_item_done(conn, row_id, False)["done"] is False


def test_finished_work_leaves_the_pressure_surfaces(conn, monkeypatch):
    """A queue that still counts finished work makes a workload feel unmovable."""
    _freeze_school_today(monkeypatch)
    row_id = _seed_with_item(conn)
    before = school.dashboard_snapshot(conn)
    assert before["summary"]["upcoming_count"] == 1
    assert before["summary"]["done_count"] == 0
    assert next(c for c in before["courses"] if c["code"] == "STAT 120")["upcoming_count"] == 1

    school.set_school_item_done(conn, row_id, True)
    after = school.dashboard_snapshot(conn)
    assert after["summary"]["upcoming_count"] == 0
    assert [item["id"] for item in after["upcoming"]] == []
    # ...but it stays visible and reversible rather than just vanishing.
    assert [item["id"] for item in after["just_done"]] == [row_id]
    assert after["summary"]["done_count"] == 1
    stat = next(c for c in after["courses"] if c["code"] == "STAT 120")
    assert stat["upcoming_count"] == 0 and stat["done_count"] == 1
    # "Next due" must move past finished work to the next genuinely open item
    # (here the seeded Midterm 1 milestone), never keep pointing at what is done.
    assert after["summary"]["next_due_at"] != before["summary"]["next_due_at"]
    assert after["summary"]["next_due_at"] == "2026-09-23T09:00"


def test_completion_never_reaches_agents_as_new_surface(conn):
    """agent_snapshot stays a narrow metadata projection (no completion leak)."""
    row_id = _seed_with_item(conn)
    school.set_school_item_done(conn, row_id, True)
    snap = school.agent_snapshot(conn)
    for item in snap["upcoming"]:
        assert set(item) == {"course_code", "kind", "title", "due_at", "all_day"}
    assert "just_done" not in snap


def test_done_endpoint_validates_and_reports_missing_coursework(client):
    conn = db.connect()
    try:
        row_id = _seed_with_item(conn)
    finally:
        conn.close()

    assert client.post(f"/api/school/items/{row_id}/done", json={"done": True}).status_code == 200
    body = client.post(f"/api/school/items/{row_id}/done", json={"done": False}).json()
    assert body["item"]["done"] is False
    # A real 404 for coursework that does not exist, not a silent no-op.
    assert client.post("/api/school/items/999999/done", json={"done": True}).status_code == 404
    # Closed body: no extra fields, and `done` must be a real boolean.
    assert client.post(f"/api/school/items/{row_id}/done",
                       json={"done": True, "grade": "A"}).status_code == 422
    assert client.post(f"/api/school/items/{row_id}/done", json={}).status_code == 422


def test_claiming_an_artifact_whose_note_vanished_does_not_strand_it(client):
    """The claim UPDATE commits status='RUNNING' before it reads the note.

    If the note was soft-deleted in between, the follow-up SELECT returns
    nothing and the worker treats the None as "no work". Without terminalizing
    here the row stays RUNNING forever, and because the one-live-artifact index
    counts RUNNING, that (session, revision, kind) slot stays blocked until an
    API restart happens to sweep it.
    """
    session = _saved_study_session(client)
    conn = db.connect()
    try:
        school.set_school_ai_enabled(conn, True)
        artifact, created = school.create_school_study_artifact(
            conn, session["id"], "summary", model="test-model",
        )
        assert created and artifact["status"] == "QUEUED"

        # The note disappears after queueing but before the worker claims it.
        school.close_note_session(conn, session["id"])
        conn.execute(
            "UPDATE school_note_sessions SET deleted_at=datetime('now') WHERE id=?",
            (session["id"],),
        )
        conn.commit()

        assert school.claim_school_study_artifact(conn, artifact["id"]) is None
        status = conn.execute(
            "SELECT status FROM school_study_artifacts WHERE id=?", (artifact["id"],)
        ).fetchone()["status"]
        assert status == "DISCARDED", f"artifact stranded in {status}"
    finally:
        conn.close()


def test_study_worker_model_is_pinned_and_never_read_from_the_artifact_row(monkeypatch):
    """A stored column must never choose the endpoint for private note text."""
    captured = {}

    class FakeResult:
        is_error = False
        result = '{"kind":"summary","title":"t","summary":"s","key_points":[],"review_questions":[]}'

    def fake_options(**kwargs):
        captured.update(kwargs)
        return kwargs

    async def fake_query(prompt, options):
        yield FakeResult()

    monkeypatch.setattr(runner, "ClaudeAgentOptions", fake_options)
    monkeypatch.setattr(runner, "ResultMessage", FakeResult)
    monkeypatch.setattr(runner, "query", fake_query)
    monkeypatch.setattr(runner, "find_cli", lambda: None)

    # Even handed an attacker-shaped model string from the artifact row.
    asyncio.run(main._school_study_model_reply("summary", "note", "evil/model-from-db"))
    assert captured["model"] == main.SCHOOL_STUDY_MODEL


def test_resaving_an_identical_title_is_a_no_op(client):
    """The document branch already skipped unchanged writes; title did not.

    Every mutation bumps `revision`, and every revision bump marks this note's
    ACCEPTED study aids STALE. So a title save that changed nothing quietly
    destroyed derived work. Both branches must agree on what "changed" means.
    """
    session = _saved_study_session(client)
    first = client.patch(
        f"/api/school/note-sessions/{session['id']}",
        json={"title": "Week 3 lecture", "expected_revision": session["revision"]},
    ).json()
    assert first["title"] == "Week 3 lecture"
    assert first["revision"] == session["revision"] + 1

    # Same title again: no change, so no new revision.
    second = client.patch(
        f"/api/school/note-sessions/{session['id']}",
        json={"title": "Week 3 lecture", "expected_revision": first["revision"]},
    ).json()
    assert second["revision"] == first["revision"], "a no-op title save bumped revision"

    # A genuine edit still counts.
    third = client.patch(
        f"/api/school/note-sessions/{session['id']}",
        json={"title": "Week 4 lecture", "expected_revision": second["revision"]},
    ).json()
    assert third["revision"] == second["revision"] + 1


def test_a_no_op_title_save_does_not_stale_an_accepted_study_aid(client, monkeypatch):
    """The user-visible consequence of the bug above."""
    session = _saved_study_session(client)
    conn = db.connect()
    try:
        school.set_school_ai_enabled(conn, True)
        artifact, _ = school.create_school_study_artifact(conn, session["id"], "summary")
        school.claim_school_study_artifact(conn, artifact["id"])
        school.complete_school_study_artifact(conn, artifact["id"], _valid_summary_output())
        accepted = school.accept_school_study_artifact(conn, artifact["id"])
        assert accepted["status"] == "ACCEPTED"
        title = school.school_note_session(conn, session["id"])["title"]

        # Re-save the exact same title, as an autosave settling would.
        school.update_note_session(
            conn, session["id"], title=title,
            expected_revision=school.school_note_session(conn, session["id"])["revision"],
        )
        status = conn.execute(
            "SELECT status FROM school_study_artifacts WHERE id=?", (artifact["id"],)
        ).fetchone()["status"]
        assert status == "ACCEPTED", f"a no-op title save STALEd an accepted aid ({status})"
    finally:
        conn.close()


def test_class_note_text_reaches_only_an_attended_watchdog_consult(conn, monkeypatch):
    """Law A1: the plane is a property of the run, never of the tool args.

    A nightly run (no `plane`) never sees note text, whatever it asks for;
    an attended consult (plane B) does, but only for watchdog and only with
    study mode on. The course's own AI policy stopped filtering this in
    2026-09; consent, role and plane are the gates that remain.
    """
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _schedule_inventory())
    stat_item = school.note_launches_for_date(conn, "2026-08-24")[0]["school_item_id"]
    stat, _ = school.open_note_session(conn, stat_item)
    school.update_note_session(
        conn, stat["id"], document=_school_note_doc("PRIVATE NOTE sample space"),
        expected_revision=stat["revision"],
    )
    bus_item = school.note_launches_for_date(conn, "2026-08-25")[0]["school_item_id"]
    bus, _ = school.open_note_session(conn, bus_item)
    school.update_note_session(
        conn, bus["id"], document=_school_note_doc("PRIVATE NOTE forbidden course"),
        expected_revision=bus["revision"],
    )
    conn.execute(
        "UPDATE school_courses SET policy_json=? WHERE code='BUS 120'",
        (json.dumps({"ai_policy": {"status": "prohibited"}}),),
    )
    conn.commit()

    def call(role, plane, **args):
        runner.RUN.update(role=role, conn=conn, role_domains=["all"])
        runner.RUN.pop("plane", None)
        if plane:
            runner.RUN["plane"] = plane
        return json.dumps(asyncio.run(runner.read_school.handler({"days": 7, **args})))

    # Consent off: an attended watchdog gets an explicit unavailable marker.
    school.set_school_ai_enabled(conn, False)
    off = call("watchdog", "B", notes=True)
    assert "PRIVATE NOTE" not in off and "notes_unavailable" in off

    school.set_school_ai_enabled(conn, True)
    # Nightly (no plane) never sees text, even when asked.
    nightly = call("watchdog", None, notes=True)
    assert "PRIVATE NOTE" not in nightly and "notes" not in json.loads(
        json.loads(nightly)["content"][0]["text"]
    )
    # Attended, but the wrong role (chief gets aggregates only).
    chief = call("chief", "B", notes=True)
    assert "PRIVATE NOTE" not in chief
    # Attended watchdog: every course's text. A course AI policy stopped
    # filtering this in 2026-09; consent, role and plane are the only gates.
    attended = json.loads(json.loads(call("watchdog", "B", notes=True))["content"][0]["text"])
    texts = sorted(n["text"] for n in attended["notes"])
    assert texts == ["PRIVATE NOTE forbidden course", "PRIVATE NOTE sample space"]
    assert all(set(n) == {"course_code", "session_date", "title", "text"} for n in attended["notes"])
    # Narrowed to one course, and an unknown course is an error, not a crash.
    only = json.loads(json.loads(call("watchdog", "B", notes=True, course="STAT 120"))["content"][0]["text"])
    assert [n["course_code"] for n in only["notes"]] == ["STAT 120"]
    unknown = json.loads(json.loads(call("watchdog", "B", notes=True, course="NOPE 1"))["content"][0]["text"])
    assert unknown["notes"] == [] and unknown["notes_error"]
    # The metadata snapshot itself is unchanged and still carries no text.
    plain = call("watchdog", "B")
    assert "PRIVATE NOTE" not in plain


# ------------------------------------------------- Ian's 2026-09-09 requests

def test_the_course_rail_is_ordered_by_the_next_class_not_the_alphabet(conn, monkeypatch):
    """Whatever meets soonest is first, and a course with no meetings is last.

    The rail used to be `ORDER BY code`, which put an asynchronous course
    ahead of the lecture starting in an hour.
    """
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _schedule_inventory())
    snapshot = school.dashboard_snapshot(conn)
    codes = [c["code"] for c in snapshot["courses"]]
    starts = [(c.get("next_meeting") or {}).get("start_at") for c in snapshot["courses"]]

    timed = [s for s in starts if s]
    assert timed == sorted(timed), f"courses are not in next-meeting order: {codes}"
    # Every course that meets comes before every course that does not.
    first_async = next((i for i, s in enumerate(starts) if not s), len(starts))
    assert all(s for s in starts[:first_async])
    assert not any(s for s in starts[first_async:])


def _note_with_text(conn, text):
    item = school.note_launches_for_date(conn, "2026-08-24")[0]["school_item_id"]
    session, _ = school.open_note_session(conn, item)
    school.update_note_session(
        conn, session["id"], document=_school_note_doc(text),
        expected_revision=session["revision"],
    )
    return session


def test_search_finds_a_word_past_the_preview_and_says_where(conn, monkeypatch):
    """Ian, 2026-09-09: search the whole notebook, not the card's preview.

    The card preview is the first 280 characters, so the old client-side
    filter could not see a word written later in the lecture at all.
    """
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _schedule_inventory())
    filler = "padding sentence about nothing in particular. " * 12
    session = _note_with_text(conn, f"{filler}consumer surplus is the gap")
    assert len(filler) > 280, "the fixture must push the term past the preview"

    hit = school.list_note_sessions(conn, session["course_code"], q="surplus")
    assert [row["id"] for row in hit] == [session["id"]]
    assert hit[0]["match_count"] == 1
    assert hit[0]["matches"][0]["match"] == "surplus"
    assert "consumer" in hit[0]["matches"][0]["before"]

    # Case-insensitive, and the snippet keeps the text as it was written.
    upper = school.list_note_sessions(conn, session["course_code"], q="SURPLUS")
    assert upper[0]["matches"][0]["match"] == "surplus"

    # A term that appears nowhere returns nothing rather than everything.
    assert school.list_note_sessions(conn, session["course_code"], q="zzzzz") == []


def test_a_typed_wildcard_searches_for_itself(conn, monkeypatch):
    """`%` is a LIKE wildcard. Unescaped, typing one returned every note in
    the course, which reads as a broken search rather than as SQL."""
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _schedule_inventory())
    session = _note_with_text(conn, "a note with no percent sign")
    assert school.list_note_sessions(conn, session["course_code"], q="%") == []
    assert school.list_note_sessions(conn, session["course_code"], q="_") == []


def test_every_match_carries_its_own_context(conn, monkeypatch):
    _freeze_school_today(monkeypatch)
    school.seed_inventory(conn, _schedule_inventory())
    session = _note_with_text(conn, "surplus early. " + ("filler. " * 30) + "surplus late.")
    row = school.list_note_sessions(conn, session["course_code"], q="surplus")[0]
    assert row["match_count"] == 2
    assert len(row["matches"]) == 2
    # Two hits far apart must not report the same sentence twice.
    assert row["matches"][0]["after"] != row["matches"][1]["after"]
    # The tail flag is what lets the UI show an ellipsis without guessing.
    assert row["matches"][0]["tail"] is True
