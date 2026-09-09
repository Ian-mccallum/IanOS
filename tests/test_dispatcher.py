"""Dispatcher: cadence tiers + tripwires decide who runs, deterministically."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, roles, school
from agents import runner


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def meta(name, tier="daily", day="", active=True, seasons=None):
    return {"name": name, "tier": tier, "day": day, "active": active,
            "seasons": seasons or []}


# A known Wednesday and Sunday for deterministic weekday tests.
WED = date(2026, 7, 15)
SUN = date(2026, 7, 19)


def test_daily_always_runs(conn):
    run, _ = runner.should_run(meta("scout", "daily"), conn, WED, force=False)
    assert run is True


def test_inactive_never_runs(conn):
    run, reason = runner.should_run(meta("scout", "daily", active=False), conn, WED, force=False)
    assert run is False and reason == "inactive"


def _seed_term(conn, start_iso: str, end_iso: str) -> None:
    school.ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO school_courses (code, name) VALUES ('FIN199', 'Intro Finance')"
    )
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at)
           VALUES ('FIN199', 'canvas', 'season-start', 'assignment', 'HW', ?)""",
        (start_iso + "T23:59:00",),
    )
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at)
           VALUES ('FIN199', 'canvas', 'season-end', 'assignment', 'HW', ?)""",
        (end_iso + "T23:59:00",),
    )
    conn.commit()


def test_out_of_season_role_is_skipped(conn):
    """SPEC-v37 6.2: a role gated `seasons:` is skipped, deterministically,
    when the live term (from school_items) says otherwise -- even a daily
    role, since the gate applies before the tier dispatch."""
    _seed_term(conn, "2026-08-24", "2026-12-09")
    break_day = date(2026, 12, 20)
    run, reason = runner.should_run(
        meta("scout", "daily", seasons=["term"]), conn, break_day, force=False,
    )
    assert run is False
    assert reason == "out of season (break)"


def test_in_season_role_runs(conn):
    _seed_term(conn, "2026-08-24", "2026-12-09")
    term_day = date(2026, 9, 15)
    run, reason = runner.should_run(
        meta("scout", "daily", seasons=["term"]), conn, term_day, force=False,
    )
    assert run is True


def test_a_role_with_no_seasons_frontmatter_is_unaffected(conn):
    """Absent seasons: is every season -- backward compatible for every role
    file that predates SPEC-v37 6.2."""
    _seed_term(conn, "2026-08-24", "2026-12-09")
    break_day = date(2026, 12, 20)
    run, _ = runner.should_run(meta("scout", "daily"), conn, break_day, force=False)
    assert run is True


def test_force_bypasses_the_season_gate(conn):
    _seed_term(conn, "2026-08-24", "2026-12-09")
    break_day = date(2026, 12, 20)
    run, reason = runner.should_run(
        meta("scout", "daily", seasons=["term"]), conn, break_day, force=True,
    )
    assert run is True and reason == "forced"


def test_force_overrides_everything(conn):
    run, reason = runner.should_run(meta("lovebird", "weekly", "sat"), conn, WED, force=True)
    assert run is True and reason == "forced"


def test_weekly_runs_on_its_day(conn):
    run, _ = runner.should_run(meta("advisor", "weekly", "wed"), conn, WED, force=False)
    assert run is True
    run2, _ = runner.should_run(meta("steward", "weekly", "sun"), conn, SUN, force=False)
    assert run2 is True


def test_weekly_skips_off_day_without_tripwire(conn):
    run, reason = runner.should_run(meta("publicist", "weekly", "mon"), conn, WED, force=False)
    assert run is False
    assert "weekly" in reason


def test_weekly_plus_tripwire_fires_off_day(conn):
    # lovebird is weekly(sat) + partner tripwire. Tripwires evaluate against the
    # real today, so the fact must be dated relative to today (not the fixed WED
    # used only for the weekly-day check).
    db.upsert_fact(conn, "personal", "partner:anniversary", "x", kind="date",
                   date=(date.today() + timedelta(days=5)).isoformat())
    run, reason = runner.should_run(meta("lovebird", "weekly", "sat"), conn, WED, force=False)
    assert run is True
    assert "tripwire" in reason


def test_tripwire_tier_fires_only_when_hit(conn):
    # counsel is tripwire on pending documents.
    run, _ = runner.should_run(meta("counsel", "tripwire"), conn, WED, force=False)
    assert run is False
    conn.execute("INSERT INTO documents (name, status) VALUES ('lease','pending')")
    conn.commit()
    run2, reason = runner.should_run(meta("counsel", "tripwire"), conn, WED, force=False)
    assert run2 is True and "pending" in reason


def test_dated_fact_within_boundary(conn):
    db.upsert_fact(conn, "college", "uiuc:near", "x", kind="date",
                   date=(date.today() + timedelta(days=5)).isoformat())
    db.upsert_fact(conn, "college", "uiuc:far", "y", kind="date",
                   date=(date.today() + timedelta(days=30)).isoformat())
    fire14 = runner.dated_fact_within("uiuc:", 14)
    fire3 = runner.dated_fact_within("uiuc:", 3)
    assert fire14(conn, date.today()) is not None       # 5d within 14
    assert fire3(conn, date.today()) is None             # 5d outside 3


def test_no_workout_streak(conn):
    today = date.today()
    # gap: rows exist in last 14d, but none in last 3 days have a workout
    db.upsert_health(conn, (today - timedelta(days=6)).isoformat(), workout="lift", workouts=1)
    db.upsert_health(conn, (today - timedelta(days=1)).isoformat(), sleep_hours=7.0)
    fire = runner.no_workout_streak(3)
    assert fire(conn, today) is not None
    # recent workout clears it
    db.upsert_health(conn, today.isoformat(), workout="mma", workouts=1)
    assert fire(conn, today) is None


def test_no_workout_streak_ignores_empty_health(conn):
    # No health rows at all → physician's lane, coach stays quiet.
    fire = runner.no_workout_streak(3)
    assert fire(conn, date.today()) is None


def _seed_exam(conn, due_at: str):
    school.ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO school_courses (code, term, name) VALUES ('BUS101', 'fall', 'Intro')"
    )
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at)
           VALUES ('BUS101', 'canvas', 'exam-1', 'exam', 'Checkpoint 1', ?)""",
        (due_at,),
    )
    conn.commit()


def test_school_exam_within_boundary(conn):
    fire = runner.school_exam_within(7)
    # 3 days out: inside the 7-day window.
    _seed_exam(conn, (WED + timedelta(days=3)).isoformat() + "T10:00:00")
    reason = fire(conn, WED)
    assert reason is not None
    assert "exam" in reason
    conn.execute("DELETE FROM school_items")
    conn.commit()
    # 8 days out: outside the 7-day window.
    _seed_exam(conn, (WED + timedelta(days=8)).isoformat() + "T10:00:00")
    assert fire(conn, WED) is None


def test_school_exam_within_fires_on_day_7_not_day_8(conn):
    # Every window has two edges (SPEC-v32 Law 8): day 7 is inside the
    # inclusive 7-day boundary, day 8 is not.
    fire = runner.school_exam_within(7)
    _seed_exam(conn, (WED + timedelta(days=7)).isoformat() + "T10:00:00")
    reason = fire(conn, WED)
    assert reason is not None
    assert "exam" in reason
    conn.execute("DELETE FROM school_items")
    conn.commit()
    _seed_exam(conn, (WED + timedelta(days=8)).isoformat() + "T10:00:00")
    assert fire(conn, WED) is None


def test_watchdog_tripwire_fires_on_school_exam(conn):
    """SPEC-v37 3.3: advisor's school_exam_within(7) tripwire moved onto
    watchdog with the merge; advisor is retired and checked no further."""
    _seed_exam(conn, (WED + timedelta(days=3)).isoformat() + "T10:00:00")
    reason = runner._fired_tripwire("watchdog", conn, WED)
    assert reason is not None
    assert "exam" in reason


def test_school_lines_matches_fixture_snapshot(conn):
    school.ensure_schema(conn)
    conn.execute(
        "INSERT OR IGNORE INTO school_courses (code, term, name) VALUES ('BUS101', 'fall', 'Intro')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO school_courses (code, term, name) VALUES ('SCAN251', 'fall', 'Scanning')"
    )
    today = date.today()
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at)
           VALUES ('BUS101', 'canvas', 'hw-1', 'assignment', 'Checkpoint 1', ?)""",
        ((today + timedelta(days=2)).isoformat() + "T23:59:00",),
    )
    conn.execute(
        """INSERT INTO school_items
               (course_code, provider, external_item_id, kind, title, due_at)
           VALUES ('SCAN251', 'canvas', 'exam-1', 'exam', 'Midterm', ?)""",
        ((today + timedelta(days=5)).isoformat() + "T10:00:00",),
    )
    conn.commit()

    # Independently compute the same fixture through agent_snapshot (the
    # source _school_lines is built from) and assert the rendered line's
    # numbers agree with it exactly, rather than hardcoding expectations.
    snap = school.agent_snapshot(conn, days=14, aggregate=True)
    assert snap["upcoming_count"] == 2

    text = runner._school_lines(conn)
    assert f"Open items next 14d: {snap['upcoming_count']} - next due: {snap['next_due_at']}" in text
    assert f"Workload by course: {snap['workload_by_course']}" in text
    assert "Exams inside the window: SCAN251" in text


def test_backup_startup_check_writes_memo_when_never_backed_up(conn, tmp_path, monkeypatch):
    """launchd has been exiting 126 on scripts/backup.sh (TCC blocking bash
    under Desktop), so the script's own fail_memo never fires. This watcher
    runs from runner.py, invoked by launchd through python directly, so it
    keeps firing even while that path stays broken (SPEC-v37 §8.9)."""
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    runner.backup_startup_check(conn, now=datetime(2026, 8, 31, 21, 30))
    memos = conn.execute("SELECT * FROM memos WHERE from_role='system'").fetchall()
    assert len(memos) == 1
    assert "backup" in memos[0]["topic"].lower()
    assert "never" in memos[0]["body"].lower()


def test_backup_startup_check_silent_when_recent(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "data" / "backup").mkdir(parents=True)
    (tmp_path / "data" / "backup" / "last_success").write_text("2026-08-31 06:00:00")
    runner.backup_startup_check(conn, now=datetime(2026, 8, 31, 21, 30))
    assert conn.execute("SELECT COUNT(*) n FROM memos WHERE from_role='system'").fetchone()["n"] == 0


def test_backup_startup_check_fires_past_48_hours(conn, tmp_path, monkeypatch):
    """Pin both edges (Law A12): 47h59m stays silent, 48h01m fires."""
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "data" / "backup").mkdir(parents=True)
    (tmp_path / "data" / "backup" / "last_success").write_text("2026-08-29 21:29:00")
    runner.backup_startup_check(conn, now=datetime(2026, 8, 31, 21, 28, 0))
    assert conn.execute("SELECT COUNT(*) n FROM memos WHERE from_role='system'").fetchone()["n"] == 0

    (tmp_path / "data" / "backup" / "last_success").write_text("2026-08-29 21:29:00")
    runner.backup_startup_check(conn, now=datetime(2026, 8, 31, 21, 30, 0))
    assert conn.execute("SELECT COUNT(*) n FROM memos WHERE from_role='system'").fetchone()["n"] == 1


def test_infra_alert_reads_status_file(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "infra_status.json").write_text('{"railway": {"status": "down"}}')
    fire = runner.infra_status_alert()
    assert fire(conn, date.today()) is not None
    (tmp_path / "data" / "infra_status.json").write_text('{"railway": {"status": "up"}}')
    assert fire(conn, date.today()) is None


# ------------------------------------------------- SPEC-v37 §8.6: dispatcher line

def test_dispatch_summary_line_buckets_woke_off_and_out_of_season():
    plan = [
        ("chief", {}, True, "daily"),
        ("cfo", {}, True, "daily"),
        ("scout", {}, True, "daily"),
        ("physician", {}, False, "health sharing off"),
        ("coach", {}, False, "health sharing off"),
        ("watchdog", {}, False, "out of season (break)"),
        ("lovebird", {}, False, "out of season (term)"),
        ("wealth", {}, False, "out of season (term)"),
        ("counsel", {}, False, "no tripwire"),
        ("steward", {}, False, "inactive"),
    ]
    assert runner._dispatch_summary_line(plan) == "3 of 10 woke; 3 off; 3 out of season."


def test_dispatch_summary_line_leaves_normal_not_due_skips_uncounted():
    """A weekly role simply not being due tonight, or a tripwire that never
    fired, is the common case most nights -- not something this inert line
    needs to explain every time, so the three numbers do not have to sum to
    the roster size."""
    plan = [
        ("chief", {}, True, "daily"),
        ("wealth", {}, False, "weekly (runs mon)"),
        ("counsel", {}, False, "no tripwire"),
    ]
    assert runner._dispatch_summary_line(plan) == "1 of 3 woke; 0 off; 0 out of season."


# ------------------------------------------------------------- SPEC-v38 §1.4

def test_tutor_runs_daily(conn):
    # Arrange: a daily tutor role meta on an ordinary Wednesday.
    # Act: ask the dispatcher whether it should run tonight.
    # Assert: it runs, for the same reason every other daily role runs.
    run, reason = runner.should_run(meta("tutor", "daily"), conn, WED, force=False)
    assert run is True
    assert reason == "daily"


def test_tutor_in_sequence():
    # Arrange/Act: read the canonical nightly sequence.
    # Assert: tutor is in it, after watchdog and before counsel.
    assert "tutor" in roles.SEQUENCE
    assert roles.SEQUENCE.index("tutor") == roles.SEQUENCE.index("watchdog") + 1
    assert roles.SEQUENCE.index("tutor") < roles.SEQUENCE.index("counsel")
