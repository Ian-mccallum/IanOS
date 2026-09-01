"""Tests for gym streak and pillar API fields."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main
from core import db, pillars


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_api.db")
    db.connect().close()
    return TestClient(main.app)


def test_gym_confirm_and_streak(conn):
    today = date.today()
    if today.weekday() >= 5:
        pytest.skip("weekend: default 5-day tracking uses weekdays")
    db.confirm_gym(conn)
    state = db.gym_streak_state(conn)
    assert state["confirmed_today"] is True
    assert state["streak"] >= 1
    assert state["weekdays_this_week"] >= 1
    assert state["is_tracked_day"] is True
    assert "is_weekday" not in state
    assert "toward_next_stool" not in state
    assert state["stools"] == 2   # default rest_days_per_week, none spent yet


def test_gym_streak_week_calendar(conn):
    state = db.gym_streak_state(conn)
    assert len(state["week"]) == 5   # default track_days_per_week
    assert "streak" in state

    db.set_gym_prefs(conn, track_days_per_week=7)
    state7 = db.gym_streak_state(conn)
    assert len(state7["week"]) == 7


def test_pillars_in_state_shape(conn):
    focus = db.current_focus(conn)
    goals = []
    fin = {"portfolio": None}
    gym = db.gym_streak_state(conn)
    partner = db.all_partner_tasks(conn)
    p = pillars.compute_pillars(conn, goals, focus, partner, fin, gym)
    assert "btc" in p
    assert p["btc"]["label"] == "Beat the Clock"
    assert "life" in p
    snap = pillars.school_snapshot(conn)
    assert snap["move_in_date"] == "2026-08-19"
    assert snap["term_start_date"] == "2026-08-24"
    assert snap["term_active"] is True
    assert p["school"]["detail"] == "term active"


def test_term_active_is_a_window_that_can_actually_close(monkeypatch):
    """`term_active` used to be `today >= TERM_START_DATE` with no end date.

    That is a one-way latch: once true it could never go false again, so the
    School pillar would have read "term active" through winter break and every
    year after. Pin both edges, because a test against the real clock passes
    forever and can never catch this.
    """
    import datetime as _dt

    def freeze(iso):
        real = _dt.date

        class _Frozen(real):
            @classmethod
            def today(cls):
                return real.fromisoformat(iso)

        monkeypatch.setattr(pillars, "date", _Frozen)

    for iso, expected in [
        ("2026-08-23", False),   # day before instruction starts
        ("2026-08-24", True),    # first day of instruction
        ("2026-12-09", True),    # last day of instruction
        ("2026-12-10", False),   # winter break: the latch has to release
        ("2027-06-01", False),   # next summer, the bug's real symptom
    ]:
        freeze(iso)
        conn = db.connect()
        try:
            assert pillars.school_snapshot(conn)["term_active"] is expected, (
                f"term_active should be {expected} on {iso}"
            )
        finally:
            conn.close()


# ------------------------------------------------------ gym_prefs (SPEC-v34)

def test_gym_prefs_seeds_sane_defaults_on_first_read(conn):
    """The schema's own INSERT OR IGNORE seeds the singleton row at table
    creation, so the very first read (no prior write) must already return
    the documented defaults: 5 tracked days/week, 2 rest days/week."""
    prefs = db.gym_prefs(conn)
    assert prefs["track_days_per_week"] == 5
    assert prefs["rest_days_per_week"] == 2


def test_set_gym_prefs_rejects_invalid_values(conn):
    with pytest.raises(ValueError):
        db.set_gym_prefs(conn, track_days_per_week=6)
    with pytest.raises(ValueError):
        db.set_gym_prefs(conn, rest_days_per_week=7)
    with pytest.raises(ValueError):
        db.set_gym_prefs(conn, rest_days_per_week=-1)
    # A rejected write must not have partially applied.
    prefs = db.gym_prefs(conn)
    assert prefs["track_days_per_week"] == 5
    assert prefs["rest_days_per_week"] == 2


def test_set_gym_prefs_accepts_valid_values(conn):
    prefs = db.set_gym_prefs(conn, track_days_per_week=7, rest_days_per_week=0)
    assert prefs["track_days_per_week"] == 7
    assert prefs["rest_days_per_week"] == 0


def test_patch_gym_prefs_rejects_invalid_track_days(client):
    response = client.patch("/api/gym/prefs", json={"track_days_per_week": 6})
    assert response.status_code == 422


@pytest.mark.parametrize("track_days", [5, 7])
def test_patch_gym_prefs_accepts_5_or_7(client, track_days):
    response = client.patch("/api/gym/prefs", json={"track_days_per_week": track_days})
    assert response.status_code == 200
    assert response.json()["track_days_per_week"] == track_days
