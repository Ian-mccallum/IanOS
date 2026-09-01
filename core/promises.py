"""The promise clock (SPEC-v18).

beatyourclock.com prints a commitment on /demo: "Ian confirms one of your
windows within 24 hours", and the contact autoresponse makes the same one.
This module is the deterministic half of keeping it: pure functions over
(rows, now), no clock of their own, no network, no model. Detection is
Python, the same law the dispatcher runs on; only narration is ever an LLM.

The design idea it serves: an alert at t=0 arrives when Ian is least able to
act and least needs to. The only alert carrying information he does not
already have is "you have not handled this and the promise expires soon".
That fires rarely, which is exactly what keeps it worth looking at.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

PROMISE_HOURS = 24          # what the site literally promises the visitor
LEAD_HOURS = 4              # alert this far before the promise expires
QUIET_START = 21            # no push from 21:00 ...
QUIET_END = 8               # ... until 08:00 local

_LOCAL_FMT = "%Y-%m-%d %H:%M:%S"


def parse_received(raw: str) -> datetime | None:
    """Site timestamps are UTC ISO ('2026-08-13T21:32:58.537Z'); everything
    else in this DB is naive local. Return an AWARE UTC datetime, or None."""
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    # A site record without an offset is still UTC by contract.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def promised_by(received_utc: str, hours: int = PROMISE_HOURS) -> str | None:
    """The deadline, in NAIVE LOCAL time to match its neighbours in the table.

    This conversion is the trap on this seam: adding 24h to the UTC string and
    storing it as-is puts every deadline five or six hours off in Central, and
    nothing looks wrong until an alert fires at the wrong time of day.
    """
    dt = parse_received(received_utc)
    if dt is None:
        return None
    local = (dt + timedelta(hours=hours)).astimezone()
    return local.strftime(_LOCAL_FMT)


def _parse_local(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    for fmt in (_LOCAL_FMT, "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def in_quiet_hours(now: datetime, start: int = QUIET_START, end: int = QUIET_END) -> bool:
    """21:00-08:00 local. Waking him is a worse failure than a late alert, and
    an alert he silences at 3am teaches him to silence all of them."""
    h = now.hour
    return h >= start or h < end


def due_for_alert(rows, now: datetime, lead_hours: int = LEAD_HOURS,
                  quiet: bool = True) -> list[dict]:
    """Which pending requests deserve a push right now.

    Pure over (rows, now) so tests drive it with no clock and no network.
    A row qualifies when it is still unhandled, has never been alerted on
    (fire-once, or a 15-minute job pushes 16 times an hour), and its promise
    expires within lead_hours. Already-expired promises still qualify: the
    alert is late but he would rather know.
    """
    if quiet and in_quiet_hours(now):
        return []
    cutoff = now + timedelta(hours=lead_hours)
    due = []
    for row in rows:
        r = dict(row)
        if r.get("status") != "new" or r.get("alerted_at"):
            continue
        deadline = _parse_local(r.get("promised_by") or "")
        if deadline is None or deadline > cutoff:
            continue
        r["_deadline"] = deadline
        due.append(r)
    due.sort(key=lambda r: r["_deadline"])
    return due


def alert_text(due: list[dict]) -> tuple[str, str]:
    """(title, body) for core.push. Name and time ONLY: the ntfy topic is
    world-readable, so the consent record, the message body and the phone
    number never cross this line (the SPEC-v17 wall extends here)."""
    parts = []
    for r in due[:4]:
        who = (r.get("company") or r.get("name") or r.get("email") or "someone").strip()
        when = r["_deadline"].strftime("%-I:%M %p") if r.get("_deadline") else ""
        parts.append(f"{who} by {when}" if when else who)
    if len(due) > 4:
        parts.append(f"+{len(due) - 4} more")
    n = len(due)
    title = "ianOS: promise expiring" if n == 1 else f"ianOS: {n} promises expiring"
    return title, " · ".join(parts)
