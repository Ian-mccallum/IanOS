"""SPEC-v37 6.1: the situation block.

Law A8 -- a role file carries policy, the run carries facts. No date, quota,
deadline or dollar figure may live in agents/roles/*.md or agents/dossier.md;
current_situation() is the one place that injects them at run time, from the
tables Ian can edit, prepended to every nightly prompt.

This closes the dead APPROVE loop the SPEC-v37 audit found: every producer
was told "do not repeat a PENDING proposal" but was never shown the pending
list, so it could not obey the instruction. The "Open proposals" section
below is that fix; every role gets the real ledger now, not just the chief.

Season / Capacity (6.2) is derived from `school.current_season()`/
`term_bounds()` -- genuinely computed from `school_items` due dates, not a
hardcoded date the way `core/pillars.TERM_START_DATE` still is for the School
pillar's own display purposes (a separate, pre-existing constant this phase
does not touch).

Pure and cheap: no model calls, no writes, one read pass over goals,
proposals and agent_acts. `now` is always a parameter, never
datetime.now() internally, so callers (and tests) can pin the clock
(Law A12: a guardrail that cannot fail proves nothing).
"""

from __future__ import annotations

from datetime import date, datetime

from core import db, metrics, school

_MAX_DEADLINES = 3
_MAX_EXPIRED = 3
_MAX_ACTION_CHARS = 140


def _num(raw: object) -> float | None:
    """Leading numeric value from a goal target/current_value string. A quota
    range like '3-5' resolves to its lower bound, matching
    core.metrics.goal_status's own treatment of ranges."""
    text = str(raw or "").split("-")[0].replace(",", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


# A capacity estimate per season, in exactly one place. Before SPEC-v37
# this "~5 hrs/week" figure was hardcoded prose scattered across scout.md,
# watchdog.md and dossier.md, all going stale together the moment it changed
# (the same shape as the $150 burn cap before budget_categories). Ian can
# revise it here alone; nothing else should ever restate it.
_SEASON_CAPACITY = {
    "term": "~5 hrs/week for Clockwork this season",
    "break": "full push, no school collision this season",
}


def _season_lines(conn, today: date) -> list[str]:
    season = school.current_season(conn, today)
    bounds = school.term_bounds(conn)
    if season == "term" and bounds:
        start, end = date.fromisoformat(bounds[0]), date.fromisoformat(bounds[1])
        total_weeks = max(1, -(-(end - start).days // 7))
        week_num = min(total_weeks, max(1, (today - start).days // 7 + 1))
        season_line = (f"Season: TERM (week {week_num} of {total_weeks}; "
                        f"ends {end.strftime('%b %-d, %Y')})")
    else:
        season_line = f"Season: {season.upper()}"
    capacity_line = f"Capacity: {_SEASON_CAPACITY.get(season, 'unknown')}"
    return [season_line, capacity_line]


def _hero_line(conn) -> str:
    """Every goal with hero=1, across every domain (core/db.py's goals.hero
    column; clear_hero_in_domain scopes at most one per domain, and this
    install already runs two at once: a business and a finance hero). No
    dedicated single-hero resolver exists in core/metrics.py or
    core/pillars.py (pillars.py's hero pick is scoped to the btc pillar
    only), so this reads goals.hero directly per the task's own fallback."""
    heroes = [g for g in db.all_goals(conn) if g.get("hero")]
    if not heroes:
        return "Hero goal: none set"
    resolved = metrics.resolve_goal_actuals(conn, [dict(g) for g in heroes])
    parts = []
    for g in resolved:
        name = (g.get("name") or "goal").strip()
        unit = (g.get("unit") or "").strip()
        actual = g.get("actual")
        target_num = _num(g.get("target"))
        if unit == "$" and isinstance(actual, (int, float)) and target_num:
            text = f"${actual:,.2f} / ${target_num:,.0f}"
            if target_num:
                text += f" ({actual / target_num * 100:.0f}%)"
        else:
            label = g.get("actual_label") or g.get("current_value") or "-"
            target_text = str(g.get("target") or "").strip()
            tail = f"{target_text} {unit}".strip()
            text = f"{label} / {tail}" if tail else label
        parts.append(f"{name} {text}")
    return "Hero goal: " + " · ".join(parts)


def _deadline_candidates(conn, today: date) -> list[tuple[int, date, dict]]:
    """Real deadlines only: goals.kind == 'deadline', matching
    core/attention.py's _goal_candidates filter, not any goal that merely has
    a deadline column set (a quota's deadline means something else)."""
    out = []
    for g in db.all_goals(conn):
        if g.get("kind") != "deadline" or g.get("archived"):
            continue
        current = str(g.get("current_value") or "").strip().lower()
        if current in db.DONE_STATES:
            continue
        raw = str(g.get("deadline") or "").strip()
        if not raw:
            continue
        try:
            deadline = date.fromisoformat(raw)
        except ValueError:
            continue
        out.append(((deadline - today).days, deadline, g))
    return out


def _deadlines_line(conn, today: date) -> str:
    candidates = _deadline_candidates(conn, today)
    if not candidates:
        return "Nearest real deadlines: none"
    candidates.sort(key=lambda item: abs(item[0]))
    parts = []
    for days, deadline, g in candidates[:_MAX_DEADLINES]:
        name = (g.get("name") or "goal").strip()
        when = deadline.strftime("%b %-d")
        parts.append(f"{name} {when} ({days}d)")
    return "Nearest real deadlines: " + " · ".join(parts)


def _quotas_line(conn) -> str:
    """Quota goals, plainly (name + current vs target). No active/paused
    concept yet: that needs goals.season (6.2, Phase 3). Render every live
    quota rather than inventing one."""
    quotas = [g for g in db.all_goals(conn) if g.get("kind") == "quota"]
    if not quotas:
        return "Live quotas: none"
    resolved = metrics.resolve_goal_actuals(conn, [dict(g) for g in quotas])
    parts = []
    for g in resolved:
        name = (g.get("name") or "goal").strip()
        label = g.get("actual_label") or g.get("current_value") or "-"
        target = str(g.get("target") or "").strip()
        unit = (g.get("unit") or "").strip()
        target_text = f"{target} {unit}".strip()
        parts.append(f"{name}: {label} (target {target_text})" if target_text else f"{name}: {label}")
    return "Live quotas: " + " · ".join(parts)


def _expired_line(conn, today: date) -> str:
    hits = db.expired_undecided_goals(conn, today)
    if not hits:
        return "Expired, undecided: none"
    shown = hits[:_MAX_EXPIRED]
    parts = [f'goal {g["id"]} "{g["name"]}" -{g["days_past"]}d' for g in shown]
    text = " · ".join(parts)
    if len(hits) > _MAX_EXPIRED:
        text += f" (+{len(hits) - _MAX_EXPIRED} more)"
    return f"Expired, undecided: {text}"


def _tasks_line(conn, today) -> str:
    rows = db.tasks_today(conn, today.isoformat())
    on_command = sum(1 for r in rows if r["priority"])
    return f"Open tasks: {len(rows)} ({on_command} on Command)"


def _proposal_lines(conn) -> list[str]:
    """The dead-loop fix (6.1): every producer sees the same open-proposal
    ledger it is told not to duplicate, not just the chief."""
    pending = db.pending_proposals(conn)
    lines = [f"Open proposals: {len(pending)}"]
    if not pending:
        lines.append("  - none")
        return lines
    for p in pending:
        action = (p.get("action") or "").strip()
        if len(action) > _MAX_ACTION_CHARS:
            action = action[: _MAX_ACTION_CHARS - 3] + "..."
        lines.append(f"  - #{p['id']} ({p['role']}, {p['kind']}): {action}")
    return lines


def _act_lines(conn) -> list[str]:
    """Real act summaries, not a bare count (SPEC-v37 14): a Ring 1
    goal.archive in the last 24h needs to be nameable in the chief's Day
    Command ('Retired X, N days past. Undo if that was wrong.'), which needs
    the summary text, not just a number."""
    acts = db.recent_agent_acts(conn, hours=24)
    lines = [f"Ring 1 acts last 24h: {len(acts)}"]
    if not acts:
        lines.append("  - none")
        return lines
    for a in acts:
        summary = (a.get("summary") or "").strip()
        lines.append(f"  - [{a.get('act')}] {summary}")
    return lines


def current_situation(conn, now: datetime) -> str:
    """The one function prepended to every nightly prompt (both daily and
    weekly, every role including chief). Pure and cheap: reads goals,
    proposals and agent_acts once each, no model calls, no writes."""
    if now.tzinfo is not None:
        raise ValueError("current_situation now must be a timezone-naive local datetime")
    today = now.date()
    lines = [
        f"CURRENT SITUATION (computed, {today.isoformat()} {today.strftime('%A')})",
        *_season_lines(conn, today),
        _hero_line(conn),
        _deadlines_line(conn, today),
        _quotas_line(conn),
        _expired_line(conn, today),
        _tasks_line(conn, today),
    ]
    lines.extend(_proposal_lines(conn))
    lines.extend(_act_lines(conn))
    return "\n".join(lines)
