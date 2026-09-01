"""Day-plan pure functions (SPEC-v7). No network, no LLM, no stored derivations.

The plan_blocks table stores only two statuses: 'planned' | 'done'. Everything
else a human cares about, whether a block has "sailed" (its end passed while
still planned), where the next free slot is, whether the day is overpacked, is
COMPUTED here from rows + the clock. Store events, derive meaning.

Times are "HH:MM" 24h strings; dates are ISO "YYYY-MM-DD". Both compare
correctly as plain strings, which keeps this module dependency-light.
"""

from __future__ import annotations

import re
from datetime import date as _date

from core import db, partner

DAY_START_MIN = 6 * 60      # 06:00, nothing is suggested before this
DAY_END_MIN = 23 * 60       # 23:00, default bottom of the rendered ribbon
LATEST_START_MIN = 22 * 60  # 22:00, a suggested start never lands past here
STEP_MIN = 15               # all plan times snap to a 15-minute grid

# suggestion durations (minutes)
_DUR_DEEP = 90
_DUR_CALLS = 60
_DUR_GYM = 60
_DUR_PARTNER = 45
MAX_SUGGESTIONS = 4
AUDIT_CALL_QUOTA = 20


# ---------------------------------------------------------------- time helpers

def _to_min(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(mins: int) -> str:
    mins = max(0, min(mins, 24 * 60 - 1))
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _round_up(mins: int, step: int = STEP_MIN) -> int:
    return ((mins + step - 1) // step) * step


# ---------------------------------------------------------------- derivations

def is_sailed(block: dict, today: str, now_hhmm: str) -> bool:
    """A block has sailed if it's still 'planned' and its end is in the past.

    Zero-shame framing lives in the UI; this is only the boolean. 'done' blocks
    never sail (a thing you did can't be late)."""
    if block.get("status") != "planned":
        return False
    d = block.get("date", "")
    if d < today:
        return True
    return d == today and (block.get("end_time") or "") <= now_hhmm


def overpack_warning(blocks: list[dict]) -> str | None:
    """Gentle planning-fallacy insurance: too many blocks or too many hours
    planned for one day. Counts 'planned' blocks only (done work isn't a load)."""
    planned = [b for b in blocks if b.get("status") == "planned"]
    total_min = sum(_to_min(b["end_time"]) - _to_min(b["start_time"]) for b in planned)
    if len(planned) > 5 or total_min > 6 * 60:
        return "That's a lot for one day. Champions pick 3."
    return None


def next_free_slot(blocks: list[dict], commitments: list[dict],
                   duration_min: int, now_hhmm: str) -> tuple[str, str]:
    """Earliest 15-min-aligned start >= max(now, 06:00) whose [start, start+dur)
    overlaps no existing block and no timed commitment. If the day is too packed
    to fit before 22:00, fall back to just after the last occupied minute, then
    clamp the start to 22:00."""
    occupied: list[tuple[int, int]] = []
    for b in blocks:
        occupied.append((_to_min(b["start_time"]), _to_min(b["end_time"])))
    for c in commitments:
        if c.get("start_time") and c.get("end_time"):
            occupied.append((_to_min(c["start_time"]), _to_min(c["end_time"])))

    def clashes(start: int) -> bool:
        end = start + duration_min
        return any(start < occ_end and occ_start < end for occ_start, occ_end in occupied)

    cand = _round_up(max(_to_min(now_hhmm), DAY_START_MIN))
    while cand <= LATEST_START_MIN:
        if not clashes(cand):
            return _to_hhmm(cand), _to_hhmm(cand + duration_min)
        cand += STEP_MIN

    last_end = max((occ_end for _, occ_end in occupied), default=cand)
    start = min(_round_up(last_end), LATEST_START_MIN)
    return _to_hhmm(start), _to_hhmm(start + duration_min)


# ---------------------------------------------------------------- ribbon bounds

def day_bounds(blocks: list[dict], commitments: list[dict]) -> tuple[int, int]:
    """The window the ribbon must render, in minutes (SPEC-v15 L21).

    Defaults to 06:00-23:00, and WIDENS to contain anything the day actually
    holds. The API accepts any 15-minute-aligned time in 00:00-23:59, so a
    fixed window silently clipped an early flight or a 23:30 block: it saved,
    returned 200, and rendered off-grid. Snapped out to whole hours so the
    hour rules stay aligned."""
    lo, hi = DAY_START_MIN, DAY_END_MIN
    for b in blocks:
        lo = min(lo, _to_min(b["start_time"]))
        hi = max(hi, _to_min(b["end_time"]))
    for c in commitments:
        if c.get("start_time"):
            lo = min(lo, _to_min(c["start_time"]))
        if c.get("end_time"):
            hi = max(hi, _to_min(c["end_time"]))
    lo = (lo // 60) * 60
    hi = -(-hi // 60) * 60                      # ceil to the hour
    return max(0, lo), min(24 * 60, hi)


# ---------------------------------------------------------------- quick add

_DUR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\.?$", re.I)
_RANGE_RE = re.compile(
    r"(?:@|at|from)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*"
    r"(?:-|to|until|till)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\.?$", re.I)
_AT_RE = re.compile(r"(?:@|at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\.?$", re.I)
_TRAIL_JUNK = re.compile(r"[\s,;:@-]*(?:\b(?:at|from|on)\b)?[\s,;:@-]*$", re.I)


def _resolve_hour(h: int, minute: int, meridiem: str | None, now_min: int) -> int | None:
    """One clock reading to minutes-since-midnight.

    A bare hour is ambiguous (7 could be 07:00 or 19:00). The rule is the
    NEAREST FUTURE reading, falling back to the later one when both have
    passed. Typing "gym 7" at 06:00 means this morning; typing it at 09:00
    cannot, so it means tonight."""
    if not (0 <= h <= 23 and 0 <= minute <= 59):
        return None
    if meridiem:
        h = h % 12 + (12 if meridiem.lower() == "pm" else 0)
        return h * 60 + minute
    if h == 0 or h > 12:                         # already unambiguous 24h
        return h * 60 + minute
    cands = [12 * 60 + minute, minute] if h == 12 else [h * 60 + minute, (h + 12) * 60 + minute]
    future = [c for c in cands if c >= now_min]
    return min(future) if future else max(cands)


def _strip(text: str, m: re.Match) -> str:
    return _TRAIL_JUNK.sub("", text[:m.start()]).strip()


def parse_quick_add(text: str, now_hhmm: str = "09:00",
                    blocks: list[dict] | None = None,
                    commitments: list[dict] | None = None,
                    default_min: int = 60) -> dict | None:
    """Parse "gym 7" / "deep work 2h @ 9" / "partner dinner 6-8" into a block.

    DETERMINISTIC, and never calls a model. This follows The Line's
    `call_card()`: a model in the interaction path costs money per keystroke
    and adds latency at the exact moment Ian needs none. Returns
    {title, start_time, end_time} or None when there is no usable title.

    Known trade-off: a bare trailing integer is read as a time, so
    "read chapter 5" plans 05:00/17:00 rather than titling a block "chapter 5".
    That is the cost of making "gym 7" work, which is the common case. Anything
    with an explicit time ("read chapter 5 at 8") is unambiguous."""
    raw = (text or "").strip()
    if not raw:
        return None
    # A lone time fragment ("7", "9pm", "12-1") is not a plan. Without this a
    # bare hour becomes a block literally titled "7". Requires a leading digit
    # so ordinary words made of the same letters ("map") are untouched.
    if re.fullmatch(r"[\s@]*(?:at|from)?[\s@]*\d[\d:apm\s.-]*", raw, re.I):
        return None
    now_min = _to_min(now_hhmm)
    blocks = blocks or []
    commitments = commitments or []
    start = end = None

    m = _RANGE_RE.search(raw)
    if m:
        h1, m1, mer1, h2, m2, mer2 = m.groups()
        s = _resolve_hour(int(h1), int(m1 or 0), mer1, now_min)
        if s is not None:
            e = (_resolve_hour(int(h2), int(m2 or 0), mer2, now_min) if mer2
                 else int(h2) % 12 * 60 + int(m2 or 0) + (s // 720) * 720)
            # An end that lands before the start means it wrapped a 12h period.
            while e is not None and e <= s:
                e += 12 * 60
            if e is not None and e < 24 * 60:
                start, end, raw = s, e, _strip(raw, m)

    if start is None:
        dur = None
        for _ in range(2):                       # "2h at 9" and "at 9 2h" both
            md = _DUR_RE.search(raw)
            if md and dur is None:
                n, unit = float(md.group(1)), md.group(2).lower()
                dur = int(n * 60) if unit.startswith(("h",)) else int(n)
                raw = _strip(raw, md)
                continue
            ma = _AT_RE.search(raw)
            if ma and start is None and _strip(raw, ma):
                s = _resolve_hour(int(ma.group(1)), int(ma.group(2) or 0),
                                  ma.group(3), now_min)
                if s is not None:
                    start = s
                    raw = _strip(raw, ma)
                    continue
            break
        dur = dur or default_min
        if start is None:
            start = _to_min(next_free_slot(blocks, commitments, dur, now_hhmm)[0])
        end = start + dur

    title = raw.strip()
    if not title or start is None or end is None or end <= start:
        return None
    end = min(end, 24 * 60 - 1)
    return {"title": title, "start_time": _to_hhmm(start), "end_time": _to_hhmm(end)}


# ---------------------------------------------------------------- suggestions

def suggest_blocks(conn, date: str) -> list[dict]:
    """Up to MAX_SUGGESTIONS one-tap chips for planning `date`, in fixed priority
    order. Each: {key, title, duration_min, goal_id}. Deterministic, reads the
    DB, calls no model. See SPEC-v7 §1 for the rule table."""
    out: list[dict] = []

    # 1. a brief exists for this day → block time for the Day Command
    if conn.execute("SELECT 1 FROM briefs WHERE date = ? LIMIT 1", (date,)).fetchone():
        out.append({"key": "command", "title": "Day Command",
                    "duration_min": _DUR_DEEP, "goal_id": None})

    # 2. a hero business goal exists → deep-work block on it
    hero = conn.execute(
        "SELECT id, name FROM goals WHERE hero = 1 AND domain = 'business' LIMIT 1"
    ).fetchone()
    if hero:
        out.append({"key": "hero", "title": f"Deep work: {hero['name']}",
                    "duration_min": _DUR_DEEP, "goal_id": hero["id"]})

    # 3. under the daily audit-call quota → a call block
    row = conn.execute("SELECT audit_calls FROM activity WHERE date = ?", (date,)).fetchone()
    if (row["audit_calls"] if row else 0) < AUDIT_CALL_QUOTA:
        out.append({"key": "calls", "title": "Call block",
                    "duration_min": _DUR_CALLS, "goal_id": None})

    # 4. a weekday with no gym confirm yet → a gym block
    if _is_weekday(date) and not _gym_confirmed(conn, date):
        out.append({"key": "gym", "title": "Gym",
                    "duration_min": _DUR_GYM, "goal_id": None})

    # 5. open tasks for Partner → protect relationship time
    if partner.open_count(db.all_partner_tasks(conn)):
        out.append({"key": "partner", "title": "Partner time",
                    "duration_min": _DUR_PARTNER, "goal_id": None})

    return out[:MAX_SUGGESTIONS]


def _is_weekday(date: str) -> bool:
    try:
        return _date.fromisoformat(date).weekday() < 5
    except ValueError:
        return False


def _gym_confirmed(conn, date: str) -> bool:
    row = conn.execute(
        "SELECT gym_confirmed FROM health_daily WHERE date = ?", (date,)
    ).fetchone()
    return bool(row and row["gym_confirmed"])


# ---------------------------------------------------------------- agent signal

def plan_adherence_7d(conn, today: str) -> dict:
    """{'planned': n, 'done': n} over the last 7 days (inclusive). AGENT-ONLY : 
    never rendered in the UI (SPEC-v7 bans block completion stats on the page)."""
    rows = conn.execute(
        """SELECT status, COUNT(*) AS n FROM plan_blocks
           WHERE date >= date(?, '-6 days') AND date <= ?
           GROUP BY status""",
        (today, today),
    ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {"planned": counts.get("planned", 0), "done": counts.get("done", 0)}
