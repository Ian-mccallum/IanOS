"""Deterministic goal actual resolution. Single source of truth for API + agents."""

from __future__ import annotations

import os
from datetime import date, datetime

from core import db, freshness, health, school

STALE_HOURS = 48
DONE_STATES = db.DONE_STATES


def _parse_num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except (ValueError, TypeError):
        return None


def _days_remaining(deadline: str | None) -> int | None:
    if not deadline:
        return None
    return (date.fromisoformat(deadline) - date.today()).days


def _prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1 if m == 1 else y}-{12 if m == 1 else m - 1:02d}"


def _hours_since(ts: str | None) -> float:
    if not ts:
        return float("inf")
    then = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    return (datetime.now() - then).total_seconds() / 3600


def _is_school_stale(conn) -> bool:
    if not os.environ.get("CANVAS_ICS_URL", "").strip():
        return False  # unconfigured installs get no candidate
    return _hours_since(school.sync_state(conn).get("last_success")) > 24


def _is_stale(conn, source: str) -> bool:
    row = db.ingest_status(conn, source)
    return row is None or _hours_since(row.get("last_import")) > STALE_HOURS


# ----------------------------------------------------------------- resolvers

def _burn_this_month(conn, goal=None) -> tuple[float, str]:
    this_month = db.today()[:7]
    burns = {b["month"]: b["burn"] for b in db.burn_by_month(conn, 3)}
    val = burns.get(this_month, 0.0)
    return val, f"${val:.2f} this month"


def _audit_calls_today(conn, goal=None) -> tuple[float, str]:
    acts = db.recent_activity(conn, 7)
    today_row = next((r for r in acts if r["date"] == db.today()), None)
    a7 = sum(r["audit_calls"] for r in acts)
    today = (today_row or {}).get("audit_calls", 0)
    return float(today), f"{today} today · {a7} last 7d"


def _follow_ups_today(conn, goal=None) -> tuple[float, str]:
    acts = db.recent_activity(conn, 7)
    today_row = next((r for r in acts if r["date"] == db.today()), None)
    a7 = sum(r["follow_ups"] for r in acts)
    today = (today_row or {}).get("follow_ups", 0)
    return float(today), f"{today} today · {a7} last 7d"


def _demos_last_7d(conn, goal=None) -> tuple[float, str]:
    acts = db.recent_activity(conn, 7)
    total = sum(r["demos"] for r in acts)
    return float(total), f"{total} last 7d"


def _sleep_avg_7d(conn, goal=None) -> tuple[float | None, str]:
    rows = db.recent_health(conn, 7)
    vals = [r["sleep_hours"] for r in rows if r.get("sleep_hours") is not None]
    if not vals:
        return None, "no data"
    avg = round(sum(vals) / len(vals), 1)
    return avg, f"{avg}h avg last 7d"


def _sleep_last_night(conn, goal=None) -> tuple[float | None, str]:
    rows = db.recent_health(conn, 2)
    for r in rows:
        if r.get("sleep_hours") is not None:
            return r["sleep_hours"], f"{r['sleep_hours']}h"
    return None, "no data"


def _steps_today(conn, goal=None) -> tuple[float | None, str]:
    row = db.health_today(conn)
    if row and row.get("steps") is not None:
        return float(row["steps"]), f"{row['steps']:,} steps"
    return None, "no data"


def _workouts_this_week(conn, goal=None) -> tuple[float, str]:
    rows = db.recent_health(conn, 7)
    total = sum(r.get("workouts") or 0 for r in rows)
    return float(total), f"{total} last 7d"


def _energy_today(conn, goal=None) -> tuple[float | None, str]:
    row = db.health_today(conn)
    if row and row.get("energy") is not None:
        return float(row["energy"]), f"{row['energy']}/5"
    return None, "no data"


def _portfolio_value(conn, goal=None) -> tuple[float | None, str]:
    snap = db.portfolio_snapshot(conn)
    if not snap:
        return None, "no data"
    return snap["total_value"], f"${snap['total_value']:,.2f}"


def _checking_balance(conn, goal=None) -> tuple[float | None, str]:
    chk = db.checking_balance(conn)
    if not chk or chk.get("balance") is None:
        return None, "no data, add SIMPLEFIN_ACCESS_URL or run make sync-chase"
    return float(chk["balance"]), f"${chk['balance']:,.2f}"


def _work_hours_week(conn, goal=None) -> tuple[float, str]:
    hours = db.calendar_hours_by_category(conn, 7)
    val = hours.get("work", 0.0)
    return val, f"{val}h work last 7d"


def _clients_signed(conn, goal=None) -> tuple[float, str]:
    for g in db.all_goals(conn):
        if g.get("metric_key") == "clients_signed" or (g.get("name") or "").startswith("Sign Clockwork"):
            v = _parse_num(g.get("current_value", "0")) or 0
            return v, str(int(v))
    return 0.0, "0"


def _gym_weekdays_this_week(conn, goal=None) -> tuple[float, str]:
    state = db.gym_streak_state(conn)
    done = state["weekdays_this_week"]
    elapsed = max(state["weekdays_elapsed"], 1)
    return float(done), f"{done}/{elapsed} weekdays"


def _tasks_done_this_week(conn, goal=None) -> tuple[float, str]:
    n = db.tasks_done_this_week(conn, date.today().isoformat())
    return (n, f"{n} this week")


def _tasks_done_for_goal(conn, goal=None) -> tuple[float, str]:
    """Deliberately never returns the literal string "no data", even at zero
    steps: goal_status() treats actual_label == "no data" as NO DATA, and a
    Life goal must never render that pill (SPEC-v41 §5.1, §5.3)."""
    if goal is None:
        return (0, "no steps yet")
    done, total = db.tasks_done_for_goal(conn, goal["id"])
    if total == 0:
        return (0, "no steps yet")
    return (done, f"{done} of {total} steps")


METRIC_RESOLVERS = {
    "burn_this_month": _burn_this_month,
    "audit_calls_today": _audit_calls_today,
    "follow_ups_today": _follow_ups_today,
    "demos_last_7d": _demos_last_7d,
    "sleep_avg_7d": _sleep_avg_7d,
    "sleep_last_night": _sleep_last_night,
    "steps_today": _steps_today,
    "workouts_this_week": _workouts_this_week,
    "gym_weekdays_this_week": _gym_weekdays_this_week,
    "energy_today": _energy_today,
    "portfolio_value": _portfolio_value,
    "checking_balance": _checking_balance,
    "work_hours_week": _work_hours_week,
    "clients_signed": _clients_signed,
    "tasks_done_this_week": _tasks_done_this_week,
    "tasks_done_for_goal": _tasks_done_for_goal,
}


def goal_status(goal: dict) -> str:
    kind = goal.get("kind", "goal")
    actual = goal.get("actual")
    target_raw = goal.get("target", "")
    days = goal.get("days_remaining")

    if goal.get("actual_label") == "no data" or (
        goal.get("metric_key") and actual is None and kind != "deadline"
    ):
        return "NO DATA"

    if kind == "deadline":
        cv = (goal.get("current_value") or "").lower().strip()
        if cv in DONE_STATES or cv in ("auto-renew on", "renewed"):
            return "ON TRACK"
        if days is None:
            return "ON TRACK"
        if days < 0:
            return "OFF TRACK"
        if days < 7:
            return "OFF TRACK"
        if days < 14:
            return "AT RISK"
        return "ON TRACK"

    if kind == "quota":
        target = _parse_num(str(target_raw).split("-")[0]) or 1
        act = float(actual or 0)
        if act >= target:
            return "ON TRACK"
        if act >= target * 0.5:
            return "AT RISK"
        return "OFF TRACK"

    # goal
    name_low = goal.get("name", "").lower()
    if "burn" in name_low:
        act = float(actual or 0)
        cap = _parse_num(target_raw) or 150
        if act <= cap:
            return "ON TRACK"
        if act <= cap * 1.2:
            return "AT RISK"
        return "OFF TRACK"

    target = _parse_num(target_raw)
    if target is None:
        return "ON TRACK" if goal.get("current_value") else "NO DATA"
    act = float(actual or 0)
    if act >= target:
        return "ON TRACK"
    if days is not None and days < 14 and act < target * 0.5:
        return "OFF TRACK"
    if act >= target * 0.5:
        return "AT RISK"
    return "OFF TRACK"


def resolve_goal_actuals(conn, goals: list[dict] | None = None) -> list[dict]:
    goals = goals if goals is not None else db.all_goals(conn)
    for g in goals:
        g["days_remaining"] = _days_remaining(g.get("deadline"))
        key = g.get("metric_key")
        if key and key in METRIC_RESOLVERS:
            g["actual"], g["actual_label"] = METRIC_RESOLVERS[key](conn, g)
        else:
            g["actual"] = g.get("current_value")
            g["actual_label"] = g.get("current_value") or "-"
        g["status"] = goal_status(g)
    return goals


def domain_status(goals: list[dict], domain: str) -> str:
    domain_goals = [g for g in goals if g.get("domain") == domain]
    if not domain_goals:
        return "NO DATA"
    order = {"OFF TRACK": 0, "AT RISK": 1, "NO DATA": 2, "ON TRACK": 3}
    return min((g.get("status", "NO DATA") for g in domain_goals), key=lambda s: order.get(s, 2))


def goals_by_domain(goals: list[dict]) -> dict[str, list[dict]]:
    out = {d: [] for d in db.DOMAINS}
    for g in goals:
        out.setdefault(g.get("domain", "business"), []).append(g)
    return out


FINANCE_SOURCES = (
    "simplefin_chase", "snaptrade_fidelity", "plaid_chase", "plaid_capital_one",
)


def _finance_configuration() -> dict[str, bool]:
    plaid_app = all(os.environ.get(key, "").strip() for key in ("PLAID_CLIENT_ID", "PLAID_SECRET"))
    return {
        "simplefin_chase": bool(os.environ.get("SIMPLEFIN_ACCESS_URL", "").strip()),
        "snaptrade_fidelity": all(
            os.environ.get(key, "").strip()
            for key in (
                "SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
            )
        ),
        "plaid_chase": plaid_app and bool(os.environ.get("PLAID_ACCESS_TOKEN_CHASE", "").strip()),
        "plaid_capital_one": plaid_app and bool(os.environ.get("PLAID_ACCESS_TOKEN_CAPITAL_ONE", "").strip()),
    }


def finance_freshness(conn, *, configured: dict[str, bool] | None = None,
                      now: datetime | None = None) -> dict[str, dict]:
    """The one finance freshness result shared by API and stale domains."""
    supplied = configured if configured is not None else _finance_configuration()
    source_config = {source: bool(supplied.get(source, False)) for source in FINANCE_SOURCES}
    statuses = {source: db.ingest_status(conn, source) for source in FINANCE_SOURCES}
    return freshness.evaluate_sources(statuses, source_config, now or datetime.now())


def stale_data_domains(conn, *, finance_configured: dict[str, bool] | None = None,
                       now: datetime | None = None,
                       finance_health: dict[str, dict] | None = None) -> list[str]:
    stale = []
    # A configured v35 source owns health freshness. An unconfigured Health
    # surface is not a stale sync, and the legacy CSV source remains a
    # compatibility fallback until a source-aware snapshot exists.
    health_state = health.health_status(conn, now_value=now)
    if health_state.get("configured"):
        if health_state.get("state") in {"late", "needs_review"}:
            stale.append("health")
    elif db.ingest_status(conn, "apple_health") is not None and _is_stale(conn, "apple_health"):
        stale.append("health")
    if _is_stale(conn, "calendar"):
        stale.append("personal")
    finance_sources = finance_health if finance_health is not None else finance_freshness(
        conn, configured=finance_configured, now=now,
    )
    if any(source["state"] == "stale" for source in finance_sources.values()):
        stale.append("finance")
    if _is_school_stale(conn):
        stale.append("school")
    return stale


def compute_tradeoff_hints(conn) -> list[dict]:
    hints = []
    sleep_avg, _ = _sleep_avg_7d(conn)
    sleep_last, _ = _sleep_last_night(conn)
    # Sleep-aware day command: reshape tomorrow, never scold yesterday.
    if (sleep_last is not None and sleep_last < 6) or (sleep_avg is not None and sleep_avg < 6.5):
        detail = f"last night {sleep_last}h" if sleep_last is not None else f"7-day avg {sleep_avg}h"
        hints.append({
            "rule": "sleep_debt",
            "hint": f"Sleep debt ({detail}). Day command: demanding work after 10am, "
                    f"gym in the afternoon, no 7am commitments. Adapt, don't scold.",
            "severity": "warn",
        })
    calls_7d = sum(r["audit_calls"] for r in db.recent_activity(conn, 7))
    if sleep_avg is not None and sleep_avg < 6.5 and calls_7d < 98:
        hints.append({
            "rule": "sleep_calls",
            "hint": f"Sleep avg {sleep_avg}h + calls at {calls_7d}/140 (70% quota), cross-domain drag",
            "severity": "warn",
        })
    burn, _ = _burn_this_month(conn)
    if burn > 150:
        personal_h = db.calendar_hours_by_category(conn, 7).get("personal", 0)
        if personal_h > 20:
            hints.append({
                "rule": "burn_personal",
                "hint": f"Burn ${burn:.0f}/mo over cap while {personal_h}h personal calendar, check discretionary spend",
                "severity": "warn",
            })
    for g in db.all_goals(conn):
        if g.get("kind") == "deadline" and g.get("deadline"):
            days = _days_remaining(g["deadline"])
            cv = (g.get("current_value") or "").lower()
            if days is not None and days < 7 and cv not in DONE_STATES:
                hints.append({
                    "rule": "deadline_chain",
                    "hint": f"{g['name']} T-{days}d, blocks downstream goals",
                    "severity": "crit" if days < 3 else "warn",
                })
    work_h = db.calendar_hours_by_category(conn, 7).get("work", 0)
    demos, _ = _demos_last_7d(conn)
    if work_h > 50 and demos < 3:
        hints.append({
            "rule": "work_vs_sell",
            "hint": f"{work_h}h worked but only {int(demos)} demos, building over selling",
            "severity": "warn",
        })
    chk = db.checking_balance(conn)
    if chk and chk.get("balance") is not None and chk["balance"] < 500 and burn > 120:
        hints.append({
            "rule": "runway",
            "hint": f"Checking at ${chk['balance']:,.0f} with burn ${burn:.0f}/mo, runway risk",
            "severity": "crit",
        })
    return hints


def finance_state(conn, *, configured: dict[str, bool] | None = None,
                  now: datetime | None = None) -> dict:
    source_health = finance_freshness(conn, configured=configured, now=now)
    snap = db.portfolio_snapshot(conn)
    chk = db.checking_balance(conn)
    portfolio = None
    if snap:
        portfolio_state = source_health["snaptrade_fidelity"]["state"]
        portfolio = {
            **snap,
            "stale": portfolio_state == "stale",
            "freshness": portfolio_state,
        }
    # SPEC-v37 §8.4: freshness for the source that actually produced this
    # balance, not a hardcoded 'simplefin_chase' -- that source was replaced
    # by Plaid and is now permanently 'disabled', so the old hardcode made
    # every checking balance read as stale-by-a-disabled-source regardless
    # of how current the real (Plaid) sync actually was.
    checking_source = chk.get("source") if chk else None
    checking_state = source_health.get(checking_source, {}).get("state", "unknown")
    checking = {
        "balance": chk["balance"] if chk else None,
        "as_of": chk["as_of"] if chk else None,
        "stale": checking_state == "stale",
        "freshness": checking_state,
    }
    return {"portfolio": portfolio, "checking": checking, "sources": source_health}
