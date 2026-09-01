"""Weekly rest-day streak (SPEC-v34): grace holds the chain, reset starts a
new round, and the rest-day allowance refills every calendar week instead of
being earned through a run of consecutive confirms."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, streaks


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _confirm(conn, d: date):
    conn.execute(
        "INSERT INTO streak_events (date, kind) VALUES (?, 'confirm') "
        "ON CONFLICT(date) DO UPDATE SET kind='confirm'",
        (d.isoformat(),),
    )
    conn.commit()


def _event(conn, d: date, kind: str):
    conn.execute(
        "INSERT INTO streak_events (date, kind) VALUES (?, ?) "
        "ON CONFLICT(date) DO UPDATE SET kind=excluded.kind",
        (d.isoformat(), kind),
    )
    conn.commit()


# A fixed Sunday so week-boundary math is deterministic (this app's week
# starts Sunday, see db.sunday_of()).
SUN = date(2026, 8, 2)     # Sunday
MON = date(2026, 8, 3)     # Monday, same week as SUN


def wd(n):                 # nth weekday from MON (skips weekends), 5-day mode helper
    d = MON
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


# --------------------------------------------------------------- core rule

def test_two_misses_in_one_week_both_grace_default_allowance(conn):
    # Confirm Monday, miss Tuesday and Wednesday, "today" = Thursday.
    _confirm(conn, MON)
    thu = MON + timedelta(days=3)
    result = streaks.apply_grace(conn, today=thu, track_days_per_week=5, rest_days_per_week=2)
    applied = dict(result["applied"])
    tue = MON + timedelta(days=1)
    wed = MON + timedelta(days=2)
    assert applied[tue.isoformat()] == "grace"
    assert applied[wed.isoformat()] == "grace"

    s = streaks.compute(conn, thu, track_days_per_week=5, rest_days_per_week=2)
    assert s["streak"] == 3          # confirm + grace + grace, chain holds
    assert s["stools"] == 0          # both rest days spent this week


def test_third_miss_in_same_week_resets(conn):
    _confirm(conn, MON)
    fri = MON + timedelta(days=4)
    result = streaks.apply_grace(conn, today=fri, track_days_per_week=5, rest_days_per_week=2)
    applied = dict(result["applied"])
    tue = MON + timedelta(days=1)
    wed = MON + timedelta(days=2)
    thu = MON + timedelta(days=3)
    assert applied[tue.isoformat()] == "grace"
    assert applied[wed.isoformat()] == "grace"
    assert applied[thu.isoformat()] == "reset"     # allowance used up

    s = streaks.compute(conn, fri, track_days_per_week=5, rest_days_per_week=2)
    assert s["streak"] == 0


def test_weekly_allowance_resets_at_week_boundary(conn):
    # Seed a reset on the Monday of week 1 (allowance already exhausted that
    # week by two prior grace events earlier the same week).
    _event(conn, SUN, "grace")
    _event(conn, SUN + timedelta(days=1), "grace")  # Monday
    _event(conn, SUN + timedelta(days=2), "reset")  # Tuesday: 3rd miss, resets

    # A miss later THE SAME week (Wednesday) must still be judged against
    # that week's already-partially-used allowance (2 graces already spent,
    # both grace and reset events land in the same week window) -> reset.
    wed_same_week = SUN + timedelta(days=3)
    result = streaks.apply_grace(
        conn, today=wed_same_week + timedelta(days=1),
        track_days_per_week=5, rest_days_per_week=2,
    )
    applied = dict(result["applied"])
    assert applied[wed_same_week.isoformat()] == "reset"

    # A miss the FOLLOWING week starts a fresh count of 0 used -> grace.
    # Confirm Monday and Tuesday of week 2 so the only miss in that week by
    # the time we reach Wednesday is Wednesday itself (isolating the "fresh
    # week" claim from any earlier miss in the same week consuming the
    # allowance first).
    next_sunday = SUN + timedelta(days=7)
    next_monday = next_sunday + timedelta(days=1)
    next_tuesday = next_sunday + timedelta(days=2)
    next_week_miss = next_sunday + timedelta(days=3)   # a Wednesday, next week
    _confirm(conn, next_monday)
    _confirm(conn, next_tuesday)
    result2 = streaks.apply_grace(
        conn, today=next_week_miss + timedelta(days=1),
        track_days_per_week=5, rest_days_per_week=2,
    )
    applied2 = dict(result2["applied"])
    assert applied2[next_week_miss.isoformat()] == "grace"


def test_seven_day_mode_saturday_grants_grace_like_a_weekday_would(conn):
    # Confirm every tracked day up to Friday so the ONLY miss of the week by
    # the time Saturday comes around is Saturday itself: this isolates
    # "first miss of the week, allowance available" for a direct comparison
    # against a midweek day in the same circumstances.
    for i in range(5):     # Mon..Fri confirmed
        _confirm(conn, MON + timedelta(days=i))
    sat = MON + timedelta(days=5)
    sun_next = MON + timedelta(days=6)
    result = streaks.apply_grace(
        conn, today=sun_next, track_days_per_week=7, rest_days_per_week=2,
    )
    applied = dict(result["applied"])
    # Saturday DID get an event at all (the point of 7-day mode: it is a
    # trackable day, unlike 5-day mode), and being the week's first miss
    # with the full allowance still available, it graces exactly like a
    # first-miss Wednesday would under the same settings (see
    # test_two_misses_in_one_week_both_grace_default_allowance).
    assert applied[sat.isoformat()] == "grace"


def test_five_day_mode_never_events_a_weekend(conn):
    _confirm(conn, wd(0))
    sat = MON + timedelta(days=5)      # Saturday
    sun = MON + timedelta(days=6)      # Sunday
    next_mon = MON + timedelta(days=7)
    result = streaks.apply_grace(
        conn, today=next_mon, track_days_per_week=5, rest_days_per_week=2,
    )
    applied_dates = {a[0] for a in result["applied"]}
    assert sat.isoformat() not in applied_dates
    assert sun.isoformat() not in applied_dates
    have = {row[0] for row in conn.execute("SELECT date FROM streak_events").fetchall()}
    assert sat.isoformat() not in have
    assert sun.isoformat() not in have


def test_zero_rest_days_resets_every_miss_without_crashing(conn):
    _confirm(conn, MON)
    tue = MON + timedelta(days=1)
    wed = MON + timedelta(days=2)
    result = streaks.apply_grace(
        conn, today=wed + timedelta(days=1), track_days_per_week=5, rest_days_per_week=0,
    )
    applied = dict(result["applied"])
    assert applied[tue.isoformat()] == "reset"
    assert applied[wed.isoformat()] == "reset"
    s = streaks.compute(conn, wed, track_days_per_week=5, rest_days_per_week=0)
    assert s["stools"] == 0


def test_apply_grace_idempotent(conn):
    _confirm(conn, MON)
    today = MON + timedelta(days=4)
    streaks.apply_grace(conn, today=today, track_days_per_week=5, rest_days_per_week=2)
    before = conn.execute("SELECT COUNT(*) FROM streak_events").fetchone()[0]
    streaks.apply_grace(conn, today=today, track_days_per_week=5, rest_days_per_week=2)
    after = conn.execute("SELECT COUNT(*) FROM streak_events").fetchone()[0]
    assert before == after


def test_confirm_gym_mirrors_event_and_backfill(conn):
    db.confirm_gym(conn, day=wd(0).isoformat())
    ev = conn.execute("SELECT kind FROM streak_events WHERE date=?", (wd(0).isoformat(),)).fetchone()
    assert ev["kind"] == "confirm"
    state = db.gym_streak_state(conn)
    assert "stools" in state and "graced_dates" in state
    assert "toward_next_stool" not in state


# ----------------------------------------------------- the regression test

def test_ians_real_sparse_history_now_produces_at_least_one_grace(conn):
    """The bug SPEC-v34 exists to fix: Ian's real streak_events confirms
    (2026-07-28, 08-06, 08-21, 08-24 -- never two days in a row) never
    accumulated 5 consecutive confirmed weekdays under the OLD mechanic, so
    the bank stayed at 0 forever and every miss since was a hard reset, zero
    grace events, ever. Replaying that exact history through the NEW default
    settings (5 tracked days/week, 2 rest days/week) must produce at least
    one 'grace' event, proving the streak now actually forgives irregular
    attendance instead of behaving like a plain reset-on-any-miss counter."""
    real_confirms = ["2026-07-28", "2026-08-06", "2026-08-21", "2026-08-24"]
    for iso in real_confirms:
        _confirm(conn, date.fromisoformat(iso))

    today = date(2026, 8, 25)   # the day after the last real confirm
    result = streaks.apply_grace(
        conn, today=today, track_days_per_week=5, rest_days_per_week=2,
    )
    kinds_applied = {kind for _, kind in result["applied"]}
    assert "grace" in kinds_applied, (
        "expected at least one 'grace' event from Ian's real sparse "
        f"attendance under the new default settings, got: {result['applied']}"
    )
