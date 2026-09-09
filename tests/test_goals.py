"""SPEC-v37 §6.3 / Law A9: an unarchived goal more than 14 days past its
deadline is a bug in the system, not a failure of Ian's. The tripwire that
catches it must actually be able to fail -- pinned at both edges of the
window, not just proven true on one illustrative example (Law A12)."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from agents import runner  # noqa: E402
from api import main  # noqa: E402
from core import db, metrics  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed_goal(conn, name="Sign Clockwork client #1", deadline=None, archived=0):
    cur = conn.execute(
        "INSERT INTO goals (name, target, deadline, domain, archived) VALUES (?, '1', ?, 'business', ?)",
        (name, deadline, archived),
    )
    conn.commit()
    return cur.lastrowid


def test_expired_goal_wakes_watchdog(conn):
    """The audit's own example, at both edges of the 14-day window."""
    today = date(2026, 8, 31)

    exactly_14 = (today - timedelta(days=14)).isoformat()
    _seed_goal(conn, deadline=exactly_14)
    assert runner._fired_tripwire("watchdog", conn, today) is None

    just_over = (today - timedelta(days=15)).isoformat()
    conn.execute("DELETE FROM goals")
    conn.commit()
    _seed_goal(conn, deadline=just_over)
    reason = runner._fired_tripwire("watchdog", conn, today)
    assert reason is not None
    assert "Sign Clockwork client #1" in reason
    assert "15d" in reason


def test_expired_undecided_goals_excludes_archived_and_recent(conn):
    today = date(2026, 8, 31)
    old_enough = (today - timedelta(days=20)).isoformat()
    recent = (today - timedelta(days=3)).isoformat()
    no_deadline_id = _seed_goal(conn, name="no deadline", deadline=None)
    _seed_goal(conn, name="recent", deadline=recent)
    _seed_goal(conn, name="archived old", deadline=old_enough, archived=1)
    live_id = _seed_goal(conn, name="live overdue", deadline=old_enough)

    hits = db.expired_undecided_goals(conn, today)
    assert [h["id"] for h in hits] == [live_id]
    assert no_deadline_id not in [h["id"] for h in hits]


def test_expired_undecided_goals_orders_most_overdue_first(conn):
    today = date(2026, 8, 31)
    a = _seed_goal(conn, name="20 days", deadline=(today - timedelta(days=20)).isoformat())
    b = _seed_goal(conn, name="40 days", deadline=(today - timedelta(days=40)).isoformat())
    hits = db.expired_undecided_goals(conn, today)
    assert [h["id"] for h in hits] == [b, a]


def test_watchdog_runs_regardless_since_it_is_daily_tier(conn):
    """The tripwire doesn't gate watchdog's run/skip decision -- watchdog is
    tier: daily and always runs -- it only supplies the wake reason."""
    from core.roles import load_role
    meta = load_role("watchdog")
    assert meta["tier"] == "daily"
    run, reason = runner.should_run(meta, conn, date(2026, 8, 31), force=False)
    assert run is True
    assert reason == "daily"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_life_goal_never_no_data(conn):
    db.create_goal(conn, name="Join AKPSI", kind="deadline", domain="personal", target="")
    db.create_goal(conn, name="Read books", kind="quota", domain="personal", target="12",
                    unit="books", metric_key="tasks_done_this_week")
    row = db.create_goal(conn, name="Landyut steps", kind="goal", domain="personal",
                          target="3", unit="steps", metric_key="tasks_done_for_goal")
    goals = metrics.resolve_goal_actuals(conn, db.all_goals(conn))
    for g in goals:
        assert g["status"] in ("ON TRACK", "AT RISK", "OFF TRACK")


def test_metric_key_validated(client):
    r = client.post("/api/goals", json={"name": "x", "metric_key": "not_a_real_key"})
    assert r.status_code == 422


def test_one_goal_insert():
    api_src = (Path(__file__).resolve().parent.parent / "api" / "main.py").read_text()
    runner_src = (Path(__file__).resolve().parent.parent / "agents" / "runner.py").read_text()
    db_src = (Path(__file__).resolve().parent.parent / "core" / "db.py").read_text()
    assert "INSERT INTO goals" not in api_src
    assert "INSERT INTO goals" not in runner_src
    assert "INSERT INTO goals" in db_src


def test_goal_patch_writes_memo_on_target_or_deadline_change(client, conn):
    r = client.post("/api/goals", json={"name": "Read books", "target": "10"})
    goal_id = r.json()["id"]
    before = conn.execute("SELECT COUNT(*) n FROM memos").fetchone()["n"]
    client.patch(f"/api/goals/{goal_id}", json={"target": "12"})
    after = conn.execute("SELECT COUNT(*) n FROM memos").fetchone()["n"]
    assert after == before + 1
