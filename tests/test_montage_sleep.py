"""Montage plumbing + sleep-aware day command hint."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, metrics
from agents import runner


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def test_sleep_debt_hint_fires_on_short_night(conn):
    db.upsert_health(conn, db.today(), sleep_hours=5.0, source="test")
    hints = metrics.compute_tradeoff_hints(conn)
    debt = [h for h in hints if h["rule"] == "sleep_debt"]
    assert debt and "after 10am" in debt[0]["hint"] and "no 7am" in debt[0]["hint"]


def test_no_sleep_debt_hint_when_rested(conn):
    for i in range(7):
        d = (date.today() - timedelta(days=i)).isoformat()
        db.upsert_health(conn, d, sleep_hours=8.0, source="test")
    hints = metrics.compute_tradeoff_hints(conn)
    assert not any(h["rule"] == "sleep_debt" for h in hints)


def test_coach_weekly_prompt_includes_montage_numbers(conn):
    db.upsert_health(conn, db.today(), workout="mma", workouts=1, source="test")
    db.set_health_ai_sharing(conn, True, "v35-health-ai-1")
    prompt = runner.build_user_prompt("coach", "weekly", conn)
    assert "SUNDAY MONTAGE" in prompt
    assert "Streak:" in prompt and "Workout mix" in prompt and "Garden:" in prompt


def test_coach_daily_prompt_has_no_montage(conn):
    prompt = runner.build_user_prompt("coach", "daily", conn)
    assert "SUNDAY MONTAGE" not in prompt


def test_latest_montage_helper(conn):
    db.add_memo(conn, "coach", "montage: Comeback Week", "Cold open. Numbers. Next opponent.")
    m = db.latest_montage(conn)
    assert m and m["title"] == "Comeback Week"


def test_physician_sleep_debt_reshapes_not_scolds(conn):
    db.upsert_health(conn, db.today(), sleep_hours=5.0, source="test")
    db.set_health_ai_sharing(conn, True, "v35-health-ai-1")
    prompt = runner.build_user_prompt("physician", "daily", conn)
    assert "SLEEP DEBT" in prompt and "never a lecture" in prompt
