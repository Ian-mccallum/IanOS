"""SPEC-v38 §2: core/learning.py's schema, topic/session CRUD, and the
streak mechanic mirrored from core/streaks.py (Law B1: a separate table,
never a shared row or code path with the gym streak)."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main  # noqa: E402
from core import db, learning  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _topic(conn, name="python", status="active", origin="user") -> int:
    learning.ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES (?, ?, ?)",
        (name, status, origin),
    )
    conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------ schema

def test_ensure_schema_creates_three_tables(conn):
    # Arrange/Act: connect, then ensure the learning schema.
    # Assert: exactly the three learning_* tables exist.
    learning.ensure_schema(conn)
    names = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'learning_%'"
        ).fetchall()
    }
    assert names == {"learning_topics", "learning_sessions", "learning_streak_events"}


# ------------------------------------------------------------------- topics

def test_active_topics_excludes_clarifying_and_archived(conn):
    # Arrange: one topic of each status.
    # Act: read active topics.
    # Assert: only the active one comes back.
    active_id = _topic(conn, "python", "active")
    _topic(conn, "ai", "clarifying")
    _topic(conn, "old habit", "archived")
    rows = learning.active_topics(conn)
    assert [r["id"] for r in rows] == [active_id]


def test_active_topics_computes_last_featured_date_via_join(conn):
    # Arrange: an active topic featured on two dates.
    # Act: read active topics.
    # Assert: last_featured_date is the max session date, not stored on the row.
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-01", topic_id, "rep one")
    learning.create_or_replace_session(conn, "2026-09-03", topic_id, "rep two")
    rows = learning.active_topics(conn)
    assert rows[0]["last_featured_date"] == "2026-09-03"


def test_active_topic_with_no_sessions_has_null_last_featured_date(conn):
    # Arrange: an active topic that has never been featured.
    # Act: read active topics.
    # Assert: last_featured_date is None (NULL sorts first for selection).
    _topic(conn)
    rows = learning.active_topics(conn)
    assert rows[0]["last_featured_date"] is None


def test_clarifying_topics_returns_only_clarifying(conn):
    # Arrange: a clarifying topic and an active one.
    # Act/Assert: clarifying_topics surfaces only the clarifying row.
    clarifying_id = _topic(conn, "ai", "clarifying")
    _topic(conn, "python", "active")
    rows = learning.clarifying_topics(conn)
    assert [r["id"] for r in rows] == [clarifying_id]


# ----------------------------------------------------------------- sessions

def test_create_or_replace_session_is_idempotent_per_date(conn):
    # Arrange: a topic.
    # Act: write a session for one date twice, second time with new content.
    # Assert: one row, carrying the second write's task_prompt.
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "first draft")
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "second draft")
    rows = conn.execute("SELECT * FROM learning_sessions WHERE date = '2026-09-05'").fetchall()
    assert len(rows) == 1
    assert rows[0]["task_prompt"] == "second draft"


def test_confirm_session_creates_row_when_none_exists(conn):
    # Arrange: a topic, no session row for today.
    # Act: confirm today with an explicit topic_id.
    # Assert: a completed, self-directed (empty task_prompt) row exists.
    topic_id = _topic(conn)
    row = learning.confirm_session(conn, "2026-09-05", topic_id=topic_id, note="did a rep")
    assert row["status"] == "completed"
    assert row["task_prompt"] == ""
    assert row["agent_note"] == "did a rep"


def test_confirm_session_without_topic_id_and_no_row_raises(conn):
    # Arrange: nothing for today.
    # Act/Assert: confirming with no topic_id raises rather than guessing one.
    with pytest.raises(ValueError):
        learning.confirm_session(conn, "2026-09-05")


def test_confirm_session_marks_existing_row_completed(conn):
    # Arrange: a generated, still-open session row.
    # Act: confirm it.
    # Assert: it flips to completed and keeps its original task_prompt.
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "walk one case")
    row = learning.confirm_session(conn, "2026-09-05")
    assert row["status"] == "completed"
    assert row["task_prompt"] == "walk one case"


def test_unconfirm_session_reopens_and_clears_confirm_event(conn):
    # Arrange: a confirmed session.
    # Act: unconfirm it.
    # Assert: it reopens and its confirm streak event is gone.
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "walk one case")
    learning.confirm_session(conn, "2026-09-05")
    row = learning.unconfirm_session(conn, "2026-09-05")
    assert row["status"] == "open"
    assert row["completed_at"] is None
    events = conn.execute("SELECT * FROM learning_streak_events").fetchall()
    assert len(events) == 0


def test_confirmed_session_count_only_counts_completed(conn):
    # Arrange: one completed session and one still-open session for a topic.
    # Act/Assert: the count reflects only the completed one.
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-01", topic_id, "rep one")
    learning.confirm_session(conn, "2026-09-01")
    learning.create_or_replace_session(conn, "2026-09-02", topic_id, "rep two")
    assert learning.confirmed_session_count(conn, topic_id) == 1


# -------------------------------------------------------------------- streak

def test_compute_credits_confirm_and_grace_days(conn):
    # Arrange: a confirm, then a grace event the next day.
    # Act: compute the streak.
    # Assert: both count toward the chain.
    learning.ensure_schema(conn)
    conn.execute("INSERT INTO learning_streak_events (date, kind) VALUES ('2026-09-01', 'confirm')")
    conn.execute("INSERT INTO learning_streak_events (date, kind) VALUES ('2026-09-02', 'grace')")
    conn.commit()
    state = learning.compute(conn, date(2026, 9, 2))
    assert state["streak"] == 2
    assert "2026-09-02" in state["graced_dates"]


def test_compute_reset_zeroes_the_streak(conn):
    # Arrange: a confirm, then a reset.
    # Act: compute the streak.
    # Assert: the reset zeroes the chain and clears graced_dates.
    learning.ensure_schema(conn)
    conn.execute("INSERT INTO learning_streak_events (date, kind) VALUES ('2026-09-01', 'confirm')")
    conn.execute("INSERT INTO learning_streak_events (date, kind) VALUES ('2026-09-02', 'reset')")
    conn.commit()
    state = learning.compute(conn, date(2026, 9, 2))
    assert state["streak"] == 0
    assert state["graced_dates"] == []


def test_apply_grace_spends_rest_days_then_resets(conn):
    # Arrange: a confirm on Monday, nothing since (every day is tracked, no
    # weekday exception, unlike the gym's 5-day mode).
    # Act: apply grace up through the third missed day.
    # Assert: the first two misses grace (2 rest days/week), the third resets.
    mon = date(2026, 8, 3)  # a Monday
    learning.ensure_schema(conn)
    conn.execute(
        "INSERT INTO learning_streak_events (date, kind) VALUES (?, 'confirm')",
        (mon.isoformat(),),
    )
    conn.commit()
    fri = mon + timedelta(days=4)
    result = learning.apply_grace(conn, today=fri)
    applied = dict(result["applied"])
    tue = mon + timedelta(days=1)
    wed = mon + timedelta(days=2)
    thu = mon + timedelta(days=3)
    assert applied[tue.isoformat()] == "grace"
    assert applied[wed.isoformat()] == "grace"
    assert applied[thu.isoformat()] == "reset"


def test_apply_grace_is_idempotent(conn):
    # Arrange: a confirm several days back.
    # Act: apply grace twice for the same "today".
    # Assert: the second call inserts no further rows.
    mon = date(2026, 8, 3)
    learning.ensure_schema(conn)
    conn.execute(
        "INSERT INTO learning_streak_events (date, kind) VALUES (?, 'confirm')",
        (mon.isoformat(),),
    )
    conn.commit()
    today = mon + timedelta(days=5)
    learning.apply_grace(conn, today=today)
    before = conn.execute("SELECT COUNT(*) AS n FROM learning_streak_events").fetchone()["n"]
    learning.apply_grace(conn, today=today)
    after = conn.execute("SELECT COUNT(*) AS n FROM learning_streak_events").fetchone()["n"]
    assert before == after


def test_learning_streak_never_touches_gym_events(conn):
    # Arrange: a confirmed learning session and a confirmed gym day.
    # Act: read both streak tables.
    # Assert: each table only ever holds its own rows (Law B1: a mirror is a
    # copy, never a shared row).
    topic_id = _topic(conn)
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "walk one case")
    learning.confirm_session(conn, "2026-09-05")
    db.confirm_gym(conn, day="2026-09-05")
    learning_dates = {r["date"] for r in conn.execute("SELECT date FROM learning_streak_events").fetchall()}
    gym_dates = {r["date"] for r in conn.execute("SELECT date FROM streak_events").fetchall()}
    assert learning_dates == {"2026-09-05"}
    assert gym_dates == {"2026-09-05"}
    # Confirming learning must not have written a gym event or vice versa --
    # each table holds exactly one row, for its own domain, not two.
    assert conn.execute("SELECT COUNT(*) AS n FROM learning_streak_events").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM streak_events").fetchone()["n"] == 1


# --------------------------------------------------------------- SPEC-v38 §5.5

def test_learning_session_date_unique(conn):
    # Arrange: a topic and a first written task for tomorrow.
    # Act: write a second task for the same date.
    # Assert: still one row, now carrying the second write's content.
    learning.ensure_schema(conn)
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('python', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "first draft")
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "second draft")
    rows = conn.execute("SELECT * FROM learning_sessions WHERE date = '2026-09-05'").fetchall()
    assert len(rows) == 1
    assert rows[0]["task_prompt"] == "second draft"


def test_skip_stale_sessions_marks_only_old_open_rows(conn):
    # Arrange: an old open row, an old completed row, and today's open row.
    # Act: skip stale sessions as of today.
    # Assert: only the old open row flips to skipped.
    learning.ensure_schema(conn)
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('ai', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-09-01", topic_id, "old open")
    learning.confirm_session(conn, "2026-08-31", topic_id=topic_id)
    learning.create_or_replace_session(conn, "2026-09-03", topic_id, "today")
    changed = learning.skip_stale_sessions(conn, "2026-09-03")
    assert changed == 1
    assert learning.get_session(conn, "2026-09-01")["status"] == "skipped"
    assert learning.get_session(conn, "2026-08-31")["status"] == "completed"
    assert learning.get_session(conn, "2026-09-03")["status"] == "open"


# ------------------------------------------------------ dashboard surface
# A topic stuck in 'clarifying' (an onboarding thread that never called
# chat_write_learning_profile) used to be invisible: active_topics()'s
# hard status='active' filter meant api/main.py::_learning_state never
# looked for it anywhere. This is the exact scenario the real
# data/ianos.db surfaced (topic "Ai", id=1, created 2026-09-09) -- verified
# read-only against that file before this fix, never touched here.

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_clarifying_topic_is_visible_but_never_counted_active(client):
    # Arrange: one clarifying topic (an abandoned onboarding thread, the
    # real-world "Ai" scenario) and one genuinely active topic.
    # Act: hit /api/state, which composes _learning_state.
    # Assert: the clarifying topic appears under 'clarifying' and ONLY
    # there -- never under 'topics', which stays the active-only list.
    conn = db.connect()
    _topic(conn, "Ai", "clarifying")
    active_id = _topic(conn, "python", "active")
    conn.close()

    learning_state = client.get("/api/state").json()["learning"]

    assert [t["name"] for t in learning_state["topics"]] == ["python"]
    assert learning_state["topics"][0]["id"] == active_id
    assert [t["name"] for t in learning_state["clarifying"]] == ["Ai"]
    # A clarifying entry carries no confirmed_count -- it never earned a
    # session, so the dashboard has nothing to feed a GrowthMark with.
    assert "confirmed_count" not in learning_state["clarifying"][0]


def test_no_clarifying_topics_yields_empty_list_not_missing_key(client):
    # Arrange: an active topic only, no clarifying ones.
    # Act: hit /api/state.
    # Assert: 'clarifying' is present and empty, never absent -- the
    # dashboard can render on the key's presence alone.
    conn = db.connect()
    _topic(conn, "python", "active")
    conn.close()
    learning_state = client.get("/api/state").json()["learning"]
    assert learning_state["clarifying"] == []
