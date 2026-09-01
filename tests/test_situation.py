"""SPEC-v37 §6.1 / §12: the situation block prepended to every nightly
prompt, and the fix for the dead APPROVE loop (producers were told not to
repeat a PENDING proposal but were never shown the pending list)."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import acts, db, school, situation  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed_goal(conn, name="Sign Clockwork client #1", deadline=None, archived=0,
               kind="goal", target="1", domain="business"):
    cur = conn.execute(
        "INSERT INTO goals (name, kind, target, deadline, domain, archived) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, kind, target, deadline, domain, archived),
    )
    conn.commit()
    return cur.lastrowid


FROZEN_NOW = datetime(2026, 8, 31, 9, 0, 0)


def _seed_school_items(conn, due_dates: list[str]) -> None:
    school.ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO school_courses (code, name) VALUES ('FIN199', 'Intro Finance')"
    )
    for i, due in enumerate(due_dates):
        conn.execute(
            """INSERT INTO school_items
                   (course_code, provider, external_item_id, kind, title, due_at)
               VALUES ('FIN199', 'canvas', ?, 'assignment', 'HW', ?)""",
            (f"item-{i}", due),
        )
    conn.commit()


def test_producers_see_pending_ledger(conn):
    """Law A8's fix: every producer's prompt carries the real open-proposal
    ledger, not just the chief's. Checked against two different roles that
    have no special-cased branch in build_user_prompt, so the assertion is
    about the shared situation block, not role-specific plumbing."""
    action = "Rebaseline the LLC filing deadline to next month"
    db.add_proposal(conn, "watchdog", action, "blocked on a state filing delay", "task")

    for role in ("cfo", "wealth"):
        prompt = runner.build_user_prompt(role, "daily", conn, now=FROZEN_NOW)
        assert action in prompt, f"{role} did not see the pending proposal ledger"
        assert "Open proposals: 1" in prompt


def test_producers_see_no_open_proposals_explicitly(conn):
    """The absence case still says so in words, it never just omits the
    section (a model cannot infer silence means zero)."""
    prompt = runner.build_user_prompt("cfo", "daily", conn, now=FROZEN_NOW)
    assert "Open proposals: 0" in prompt
    assert "  - none" in prompt


def test_current_situation_shows_expired_goal(conn):
    """A goal past core.db.expired_undecided_goals' 14-day window appears
    with its real days_past, not a rounded or reworded figure."""
    today = FROZEN_NOW.date()
    old_enough = (today - timedelta(days=20)).isoformat()
    _seed_goal(conn, name="Sign Clockwork client #1", deadline=old_enough,
              kind="deadline")

    block = situation.current_situation(conn, FROZEN_NOW)
    assert 'goal' in block
    assert '"Sign Clockwork client #1" -20d' in block


def test_current_situation_shows_recent_ring1_act_summary(conn):
    """A count alone can't feed the chief's 'Retired X, N days past. Undo if
    that was wrong.' announcement (SPEC-v37 §14); the real summary text
    must be in the block."""
    out = acts.note_create(conn, role="steward", plane="nightly", thread_id=None,
                           body="call Fidelity about the transfer")
    act_row = db.get_agent_act(conn, out["act_id"])

    block = situation.current_situation(conn, FROZEN_NOW)
    assert "Ring 1 acts last 24h: 1" in block
    assert act_row["summary"] in block


def test_current_situation_no_acts_says_zero(conn):
    block = situation.current_situation(conn, FROZEN_NOW)
    assert "Ring 1 acts last 24h: 0" in block


def test_season_and_capacity_derived_from_school_items(conn):
    """SPEC-v37 §6.2: Season/Capacity is genuinely computed from school_items
    due dates (school.term_bounds), not a hardcoded date. Pin both edges of
    the window (Law A12) so this can actually fail."""
    _seed_school_items(conn, ["2026-08-24T23:59:00", "2026-12-09T23:59:00"])

    inside = situation.current_situation(conn, datetime(2026, 9, 15, 9, 0, 0))
    assert "Season: TERM" in inside
    assert "Capacity: ~5 hrs/week for Clockwork this season" in inside

    on_end_edge = situation.current_situation(conn, datetime(2026, 12, 9, 9, 0, 0))
    assert "Season: TERM" in on_end_edge

    after_end = situation.current_situation(conn, datetime(2026, 12, 10, 9, 0, 0))
    assert "Season: BREAK" in after_end
    assert "Capacity: full push, no school collision this season" in after_end


def test_season_with_no_school_data_is_break(conn):
    """No school data at all (never imported) reads as BREAK, the safer
    default for anything gated `seasons: term`."""
    block = situation.current_situation(conn, FROZEN_NOW)
    assert "Season: BREAK" in block


def test_current_situation_header_has_computed_date_and_weekday(conn):
    block = situation.current_situation(conn, FROZEN_NOW)
    first_line = block.splitlines()[0]
    assert "2026-08-31" in first_line
    assert "Monday" in first_line


def test_current_situation_rejects_aware_datetime(conn):
    from datetime import timezone
    with pytest.raises(ValueError):
        situation.current_situation(conn, FROZEN_NOW.replace(tzinfo=timezone.utc))
