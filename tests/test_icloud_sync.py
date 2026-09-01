"""iCloud two-way sync engine (SPEC-v7 Phase C) against an in-memory calendar.
No network, no caldav install, no credentials. FakeCalendar is the seam."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db  # noqa: E402
from ingest import sync_icloud as ic  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _connect(plan, others=None):
    return lambda: (plan, others or [])


def _uid(conn, block_id):
    return conn.execute("SELECT caldav_uid FROM plan_blocks WHERE id=?", (block_id,)).fetchone()[0]


def _age_last_sync(conn, block_id):
    """Push synced_at into the past so a fresh edit reads as unambiguously newer."""
    conn.execute("UPDATE plan_blocks SET synced_at=datetime('now','localtime','-1 hour') WHERE id=?",
                 (block_id,))
    conn.commit()


# ---------------------------------------------------------------- push

def test_new_local_block_pushed(conn):
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Call block")
    rep = ic.sync(conn, _connect(plan))
    assert rep["pushed_new"] == 1
    row = db.get_plan_block(conn, b["id"])
    assert row["caldav_uid"] and row["caldav_etag"]
    evs = plan.events_in(db.today(), db.today())
    assert len(evs) == 1 and evs[0]["summary"] == "Call block"


def test_local_edit_pushed(conn):
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Call block")
    ic.sync(conn, _connect(plan))
    db.update_plan_block(conn, b["id"], title="Deep work")  # bumps updated_at to now
    _age_last_sync(conn, b["id"])
    rep = ic.sync(conn, _connect(plan))
    assert rep["pushed_dirty"] == 1
    assert plan.events_in(db.today(), db.today())[0]["summary"] == "Deep work"


def test_done_prefix_pushed(conn):
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Gym")
    ic.sync(conn, _connect(plan))
    db.update_plan_block(conn, b["id"], status="done")
    _age_last_sync(conn, b["id"])
    ic.sync(conn, _connect(plan))
    assert plan.events_in(db.today(), db.today())[0]["summary"] == "✓ Gym"


# ---------------------------------------------------------------- pull

def test_phone_created_block_imported(conn):
    plan = ic.FakeCalendar()
    plan.phone_put("uid-phone", "Gym", db.today(), "07:00", "08:00")
    rep = ic.sync(conn, _connect(plan))
    assert rep["pulled_new"] == 1
    row = conn.execute("SELECT * FROM plan_blocks WHERE caldav_uid='uid-phone'").fetchone()
    assert row["title"] == "Gym" and row["status"] == "planned" and row["start_time"] == "07:00"


def test_phone_created_done_prefix_parsed(conn):
    plan = ic.FakeCalendar()
    plan.phone_put("uid-x", "✓ Ship it", db.today(), "11:00", "12:00")
    ic.sync(conn, _connect(plan))
    row = conn.execute("SELECT * FROM plan_blocks WHERE caldav_uid='uid-x'").fetchone()
    assert row["title"] == "Ship it" and row["status"] == "done"


def test_phone_edit_remote_wins(conn):
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Gym")
    ic.sync(conn, _connect(plan))
    plan.phone_put(_uid(conn, b["id"]), "✓ Gym", db.today(), "07:00", "08:00")  # new etag
    rep = ic.sync(conn, _connect(plan))
    assert rep["pulled_updated"] == 1
    row = db.get_plan_block(conn, b["id"])
    assert row["status"] == "done" and row["title"] == "Gym" and row["start_time"] == "07:00"


def test_phone_delete_removes_local(conn):
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Gym")
    ic.sync(conn, _connect(plan))
    plan.phone_delete(_uid(conn, b["id"]))
    rep = ic.sync(conn, _connect(plan))
    assert rep["deleted_local"] == 1
    assert db.get_plan_block(conn, b["id"]) is None


def test_local_delete_no_resurrection(conn):
    """The classic two-way trap: a local delete must not reappear on the next pull."""
    plan = ic.FakeCalendar()
    b = db.create_plan_block(conn, db.today(), "09:00", "10:00", "Gym")
    ic.sync(conn, _connect(plan))
    uid = _uid(conn, b["id"])
    db.delete_plan_block(conn, b["id"])          # leaves a tombstone
    rep = ic.sync(conn, _connect(plan))
    assert rep["deleted_remote"] == 1
    assert uid not in plan._events
    assert conn.execute("SELECT COUNT(*) FROM plan_tombstones").fetchone()[0] == 0
    ic.sync(conn, _connect(plan))                # second pass must not resurrect
    assert conn.execute(
        "SELECT COUNT(*) FROM plan_blocks WHERE caldav_uid=?", (uid,)).fetchone()[0] == 0


def test_recurring_event_skipped(conn):
    plan = ic.FakeCalendar()
    plan.phone_put("uid-rrule", "Standup", db.today(), "09:00", "09:15", recurring=True)
    rep = ic.sync(conn, _connect(plan))
    assert rep["skipped_recurring"] >= 1
    assert conn.execute("SELECT COUNT(*) FROM plan_blocks").fetchone()[0] == 0


def test_all_day_event_skipped(conn):
    plan = ic.FakeCalendar()
    plan.phone_put("uid-allday", "Holiday", db.today(), None, None)
    ic.sync(conn, _connect(plan))
    assert conn.execute("SELECT COUNT(*) FROM plan_blocks").fetchone()[0] == 0


# ---------------------------------------------------------------- round trips

def test_full_roundtrip_stable(conn):
    """Push then immediately pull in the same sync must not double-update."""
    plan = ic.FakeCalendar()
    db.create_plan_block(conn, db.today(), "09:00", "10:00", "Call block")
    rep = ic.sync(conn, _connect(plan))
    assert rep["pushed_new"] == 1 and rep["pulled_updated"] == 0 and rep["pulled_new"] == 0
    # a no-op second sync changes nothing
    rep2 = ic.sync(conn, _connect(plan))
    assert rep2 == {"pushed_new": 0, "pushed_dirty": 0, "deleted_remote": 0,
                    "pulled_new": 0, "pulled_updated": 0, "deleted_local": 0,
                    "skipped_recurring": 0, "commitments": 0}


# ---------------------------------------------------------------- commitments

def test_commitments_upsert_idempotent(conn):
    others = ic.FakeCalendar()
    others.phone_put("c1", "Dentist", db.today(), "14:00", "15:00")
    ic.sync(conn, lambda: (ic.FakeCalendar(), [others]))
    n1 = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    ic.sync(conn, lambda: (ic.FakeCalendar(), [others]))
    n2 = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
    assert n1 == 1 and n2 == 1


def test_commitments_never_become_blocks(conn):
    others = ic.FakeCalendar()
    others.phone_put("c1", "Dentist", db.today(), "14:00", "15:00")
    ic.sync(conn, lambda: (ic.FakeCalendar(), [others]))
    assert conn.execute("SELECT COUNT(*) FROM plan_blocks").fetchone()[0] == 0
