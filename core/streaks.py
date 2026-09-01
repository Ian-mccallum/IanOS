"""Bending gym streak: a weekly rest-day allowance so a miss never resets to
zero (SPEC-v34, superseding SPEC-v6-the-corner.md section 1).

The philosophy (see docs/SPEC-v6-the-corner.md, docs/SPEC-v34-weekly-rest-days.md):
distractible brains rage-quit unbroken chains. So the chain forgives. Ian gets a fixed
number of rest days that refills every calendar week (Sunday-start, this app's
convention) regardless of what happened the week before; miss a tracked day and
the nightly run spends one of that week's rest days automatically if any remain,
the streak SURVIVES and the tone is "you sat one out, champions do", never
failure. Only when the week's rest days are used up does a miss become a reset.

SPEC-v34 replaced the older mechanic, which required 5 CONSECUTIVE confirmed
weekdays to bank one stool (cap 2). That rule never actually forgave anything
for genuinely irregular attendance: a real confirm history with gaps (e.g.
2026-07-28, 08-06, 08-21, 08-24 -- never two days in a row) never reached 5
consecutive confirms, so the bank stayed at 0 forever and every miss was a
hard reset. The weekly allowance below fixes that by refilling on a calendar
clock instead of being earned through perfection.

Truth is derivable: we store events, not tallies. `streak_events(date, kind)`
records every past tracked day as 'confirm' (mirrored from
health_daily.gym_confirmed), 'grace' (a rest day spent for a miss), or 'reset'
(missed with that week's rest days already used up). The nightly `apply_grace`
is the ONLY writer of grace/reset and is idempotent.

This module does pure date/event math, it never imports db (db imports it).
Callers (core/db.py's `gym_streak_state` / `apply_gym_grace`) read
`db.gym_prefs(conn)` once and pass `track_days_per_week`/`rest_days_per_week`
through as parameters; this module must never read prefs itself.
"""

from __future__ import annotations

from datetime import date, timedelta

EVENT_KINDS = ("confirm", "grace", "reset")


def _is_tracked_day(d: date, track_days_per_week: int) -> bool:
    """5-day mode: Mon-Fri only, exactly as before. 7-day mode: every day."""
    if track_days_per_week == 7:
        return True
    return d.weekday() < 5


def _sunday_of(d: date) -> date:
    """Start of `d`'s week under this app's Sunday-start convention. Mirrors
    db.sunday_of()'s math exactly (weekday(): Mon=0..Sun=6), reimplemented
    locally because this module may never import db."""
    days_since_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sunday)


def sync_confirms(conn, commit: bool = True) -> None:
    """Mirror health_daily.gym_confirmed into 'confirm' events (idempotent)."""
    rows = conn.execute("SELECT date FROM health_daily WHERE gym_confirmed = 1").fetchall()
    for (d,) in rows:
        conn.execute(
            "INSERT INTO streak_events (date, kind) VALUES (?, 'confirm') "
            "ON CONFLICT(date) DO UPDATE SET kind='confirm'",
            (d,),
        )
    if commit:
        conn.commit()


def compute(conn, today: date | None = None, *, track_days_per_week: int = 5,
            rest_days_per_week: int = 2) -> dict:
    """Replay all events up to `today` -> {streak, stools, graced_dates,
    last_event}. Bounded (a semester is ~100 tracked days).

    `stools` is no longer a banked/earned count -- it is "rest days left in
    the CURRENT week as of `today`": rest_days_per_week minus however many
    'grace' events fall within today's week (that week's Sunday through
    today), clamped to >= 0. It is always freshly derived from event dates,
    never carried state, so it naturally refills at the week boundary with no
    extra column and no reset-of-a-tally logic.
    """
    today = today or date.today()
    rows = conn.execute(
        "SELECT date, kind FROM streak_events ORDER BY date"
    ).fetchall()

    current_week = _sunday_of(today)
    streak = 0
    graced: list[str] = []
    graces_this_week = 0
    last = None
    for r in rows:
        d = date.fromisoformat(r["date"])
        if d > today:
            continue
        kind = r["kind"]
        if kind == "confirm":
            streak += 1
        elif kind == "grace":
            streak += 1              # the chain holds
            graced.append(r["date"])
            if _sunday_of(d) == current_week:
                graces_this_week += 1
        elif kind == "reset":
            # A reset still zeroes the running streak and the displayed
            # graced dates for it, exactly as before. It does NOT zero
            # graces_this_week: that count is derived purely from which
            # week a 'grace' event's own date falls in, not from anything
            # carried across a reset.
            streak = 0
            graced = []
        last = r["date"]
    return {
        "streak": streak,
        "stools": max(0, rest_days_per_week - graces_this_week),
        "graced_dates": graced,
        "last_event": last,
    }


def apply_grace(conn, today: date | None = None, *, track_days_per_week: int = 5,
                 rest_days_per_week: int = 2) -> dict:
    """Nightly step (pure Python, NOT an LLM decision): for every past tracked
    day with no event, insert 'grace' if this week's rest-day allowance is not
    yet used up, else 'reset'. Idempotent: a day that already has an event is
    left alone. An untracked day (e.g. a weekend in 5-day mode) never gets any
    event at all. Returns what it applied."""
    today = today or date.today()
    sync_confirms(conn)

    first_iso = conn.execute("SELECT MIN(date) FROM streak_events").fetchone()[0]
    if not first_iso:
        return {"applied": []}

    have = {row[0] for row in conn.execute("SELECT date FROM streak_events").fetchall()}
    yesterday = today - timedelta(days=1)
    applied: list[tuple[str, str]] = []

    cur = date.fromisoformat(first_iso)
    while cur <= yesterday:
        iso = cur.isoformat()
        if _is_tracked_day(cur, track_days_per_week) and iso not in have:
            # Count 'grace' events already on record strictly before this
            # date but within THIS SAME WEEK (that week's Sunday up to, not
            # including, this date). Query the live connection rather than a
            # Python running tally so a grace inserted earlier in this same
            # walk-forward loop (an earlier miss, same week) is already
            # counted for a later miss in the same week.
            week_start_iso = _sunday_of(cur).isoformat()
            graces_this_week = conn.execute(
                "SELECT COUNT(*) FROM streak_events WHERE kind='grace' "
                "AND date >= ? AND date < ?",
                (week_start_iso, iso),
            ).fetchone()[0]
            kind = "grace" if graces_this_week < rest_days_per_week else "reset"
            conn.execute("INSERT INTO streak_events (date, kind) VALUES (?, ?)", (iso, kind))
            have.add(iso)
            applied.append((iso, kind))
        cur += timedelta(days=1)

    conn.commit()
    return {"applied": applied}


def last_grace_or_reset(conn, within_days: int = 3) -> tuple[str, str] | None:
    """Most recent grace/reset event in the window, for Rocky's wake note."""
    cutoff = (date.today() - timedelta(days=within_days)).isoformat()
    row = conn.execute(
        "SELECT date, kind FROM streak_events WHERE kind IN ('grace','reset') "
        "AND date >= ? ORDER BY date DESC LIMIT 1",
        (cutoff,),
    ).fetchone()
    return (row["date"], row["kind"]) if row else None
