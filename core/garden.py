"""The Garden: a living plant that grows from how Ian lives, and wilts (never
dies) when he drifts. Pure state derived from the last 14 days; zero input.

See docs/SPEC-v6-the-corner.md §2. Design law: NEVER a guilt object. The plant
cannot die (stage floor 1), mood recovers after any single alive day, and no
number or label is ever shown. Ian just walks past it and sees how he's living.
"""

from __future__ import annotations

from datetime import date, timedelta

from core import db

# An "alive day" = an intentional signal that Ian showed up for his body.
# Passive Apple Watch snapshots are informative, but they are not an action
# Ian chose to confirm.  The Garden therefore remains a gentle behavior cue,
# not a sensor-score proxy.
STAGE_THRESHOLDS = (0, 1, 3, 6, 9, 12)  # alive-days (of 14) → stage 0..5


def _alive_days(conn, days: int = 14) -> list[str]:
    """Dates in the window with a gym confirm or intentional manual check-in."""
    rows = db.recent_health(conn, days)
    alive = []
    for r in rows:
        if (r.get("gym_confirmed")
                or (r.get("workout") or "").strip()
                or r.get("energy") is not None):
            alive.append(r["date"])
    return alive


def _stage(alive_count: int) -> int:
    stage = 0
    for i, threshold in enumerate(STAGE_THRESHOLDS):
        if alive_count >= threshold:
            stage = i
    return max(1, stage)  # floor 1, the plant never dies


def garden_state(conn, today: date | None = None) -> dict:
    """{stage: 1..5, mood: thriving|steady|thirsty, spark: bool}."""
    today = today or date.today()
    alive = set(_alive_days(conn))
    stage = _stage(len(alive))

    # mood from the last 3 days, recovers after any single alive day
    last3 = [(today - timedelta(days=i)).isoformat() for i in range(3)]
    recent_alive = sum(1 for d in last3 if d in alive)
    if recent_alive >= 2:
        mood = "thriving"
    elif recent_alive == 1:
        mood = "steady"
    else:
        mood = "thirsty"

    # A spark is an intentional gym confirmation, never a passive step count.
    spark = _is_personal_best(conn, today)

    return {"stage": stage, "mood": mood, "spark": spark, "alive_days": len(alive)}


def _is_personal_best(conn, today: date) -> bool:
    today_iso = today.isoformat()
    row = db.health_for_day(conn, today_iso) or {}
    return bool(row.get("gym_confirmed"))
