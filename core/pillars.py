"""Life pillar summaries for Ian's dashboard, presentation layer over goals/facts."""

from __future__ import annotations

from datetime import date, timedelta

from core import db, partner, metrics

PILLAR_ORDER = ("btc", "body", "partner", "school", "life", "money")

PILLAR_META = {
    "btc": {"label": "Beat the Clock", "icon": "◆", "domains": ("business",)},
    "body": {"label": "Body", "icon": "◉", "domains": ("health",)},
    "partner": {"label": "Partner", "icon": "♥", "domains": ("personal",)},
    "school": {"label": "School", "icon": "△", "domains": ("school", "college")},
    "life": {"label": "Life", "icon": "○", "domains": ("personal",)},
    "money": {"label": "Money", "icon": "$", "domains": ("finance",)},
}

MOVE_IN_DATE = "2026-08-19"
# The instruction window, mirroring `calendar_projection.instruction_start` /
# `instruction_end` in data/fall_2026_school_seed.json. Both ends matter: with
# only a start date `term_active` was a one-way latch that could never clear,
# so the School pillar would have read "term active" through winter break and
# every following year. A term the pillar can leave is the whole point.
TERM_START_DATE = "2026-08-24"
TERM_END_DATE = "2026-12-09"


def is_partner_goal(goal: dict) -> bool:
    notes = (goal.get("notes") or "").lower()
    name = (goal.get("name") or "").lower()
    return "#partner" in notes or "partner" in name


def goals_for_pillar(goals: list[dict], pillar: str) -> list[dict]:
    if pillar == "btc":
        return [g for g in goals if g.get("domain") == "business"]
    if pillar == "body":
        return [g for g in goals if g.get("domain") == "health"]
    if pillar == "money":
        return [g for g in goals if g.get("domain") == "finance"]
    if pillar == "school":
        return [g for g in goals if g.get("domain") == "school"]
    if pillar == "partner":
        return [g for g in goals if g.get("domain") == "personal" and is_partner_goal(g)]
    if pillar == "life":
        return [g for g in goals if g.get("domain") == "personal" and not is_partner_goal(g)]
    return []


def pillar_status(goals: list[dict]) -> str:
    if not goals:
        return "NO DATA"
    order = {"OFF TRACK": 0, "AT RISK": 1, "NO DATA": 2, "ON TRACK": 3}
    return min((g.get("status") or "NO DATA" for g in goals), key=lambda s: order.get(s, 2))


def attention_count(goals: list[dict]) -> int:
    return sum(1 for g in goals if g.get("status") in ("OFF TRACK", "AT RISK", "NO DATA")
                and not g.get("hero"))


def days_until(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return (date.fromisoformat(iso) - date.today()).days
    except ValueError:
        return None


def school_snapshot(conn) -> dict:
    facts = db.list_facts(conn)
    uiuc = [f for f in facts if (f.get("topic") or "").startswith("uiuc:") and f.get("date")]
    move_in = next((f for f in uiuc if "move-in" in f.get("topic", "")), None)
    if move_in is None:
        move_in = {"topic": "uiuc:fall-move-in", "date": MOVE_IN_DATE, "body": "UIUC move-in"}
    today = date.today()
    term_active = (date.fromisoformat(TERM_START_DATE) <= today
                   <= date.fromisoformat(TERM_END_DATE))
    nearest = move_in
    for f in uiuc:
        d = days_until(f.get("date"))
        if d is not None and d >= 0:
            if nearest is move_in or days_until(nearest.get("date")) is None:
                nearest = f
            elif d < (days_until(nearest.get("date")) or 9999):
                nearest = f
    nd = days_until(nearest.get("date"))
    label = (nearest.get("topic") or "").split(":", 1)[-1].replace("-", " ")
    # Move-in is historical once the semester begins. The school pillar should
    # never display a negative countdown as its primary status.
    if term_active and (nd is None or nd < 0):
        nearest = {"topic": "uiuc:fall-term", "date": TERM_START_DATE,
                   "body": "Fall term is active"}
        nd = 0
        label = "fall term"
    return {
        "next_label": label,
        "next_date": nearest.get("date"),
        "days_until": nd,
        "move_in_date": MOVE_IN_DATE,
        "move_in_days": days_until(MOVE_IN_DATE),
        "term_start_date": TERM_START_DATE,
        "term_end_date": TERM_END_DATE,
        "term_active": term_active,
        "facts": uiuc,
    }


def compute_pillars(conn, goals: list[dict], focus: dict, partner_tasks: list[dict],
                    fin: dict, gym: dict) -> dict:
    focused_domains = set(focus.get("domains") or ["business"])
    out = {}
    for pid in PILLAR_ORDER:
        meta = PILLAR_META[pid]
        pg = goals_for_pillar(goals, pid)
        st = pillar_status(pg) if pg else "NO DATA"
        att = attention_count(pg)
        off_focus = not any(d in focused_domains for d in meta["domains"]) and pid != "btc"

        hero = None
        detail = ""
        if pid == "btc":
            hero = next((g for g in pg if g.get("hero")), None) or next(
                (g for g in pg if "client" in (g.get("name") or "").lower()), None)
            if hero:
                detail = f"{hero.get('actual_label') or hero.get('actual', '-')}"
            elif att:
                detail = f"{att} need attention"
            else:
                detail = "on track"
        elif pid == "body":
            detail = f"{gym.get('streak', 0)}d streak"
            if gym.get("confirmed_today"):
                detail += " · today ✓"
        elif pid == "partner":
            open_n = partner.open_count(partner_tasks)
            detail = f"{open_n} open" if open_n else "all done"
            # Open relationship intentions are context, never a scolding state.
            st = "ON TRACK"
        elif pid == "school":
            snap = school_snapshot(conn)
            nd = snap.get("days_until")
            if snap.get("term_active"):
                detail = "term active"
            elif nd is not None:
                detail = f"{nd}d to semester"
            else:
                detail = "set dates"
        elif pid == "life":
            detail = f"{att} need attention" if att else "on track"
        elif pid == "money":
            port = (fin or {}).get("portfolio")
            if port:
                detail = f"${port.get('total_value', 0):,.0f}"
            else:
                detail = "on track" if st == "ON TRACK" else status_label(st)

        out[pid] = {
            "id": pid,
            "label": meta["label"],
            "icon": meta["icon"],
            "status": st,
            "attention_count": att,
            "detail": detail,
            "off_focus": off_focus and st not in ("OFF TRACK",),
            "hero": hero,
        }
    return out


def status_label(s: str) -> str:
    return {
        "ON TRACK": "on track",
        "AT RISK": "at risk",
        "OFF TRACK": "off track",
        "NO DATA": "no data",
    }.get(s, s)
