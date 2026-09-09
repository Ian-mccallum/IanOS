"""Deterministic, read-only attention compiler (SPEC-v21).

This module derives one shared ordering from existing source records. It owns
no data, performs no writes, and deliberately keeps framework, network, and
model concerns outside the compiler boundary.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Any, Callable

from core import db, freshness, partner, leads, plan, school


class Interaction(str, Enum):
    NAVIGATE = "navigate"
    PROPOSAL_DECISION = "proposal_decision"
    GYM_CONFIRM = "gym_confirm"
    ACTIVITY_INCREMENT = "activity_increment"
    TASK_COMPLETE = "task_complete"


INTERACTIONS = frozenset(item.value for item in Interaction)
ACTIVITY_INCREMENT_FIELDS = frozenset({"audit_calls", "follow_ups"})

PROMISE_LEAD = timedelta(hours=4)
GOAL_WINDOW = timedelta(days=7)
PROPOSAL_SOON = timedelta(days=1)

_LOCAL_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)

_SOURCE_ORDER = {
    "promise": 0,
    "callback": 1,
    "plan": 2,
    "goal": 3,
    "proposal": 4,
    "gym": 5,
    "call": 6,
    "follow_up": 7,
    "partner": 8,
    "task": 9,
    "stale": 10,
    "school": 11,
    "school_meeting": 12,
}

_ROUTES = {
    "business": "btc",
    "health": "body",
    "finance": "money",
    "school": "school",
    "personal": "life",
}

_URGENCY = {
    0: "breached",
    1: "due",
    2: "routine",
    3: "maintenance",
}

_MISSING = object()


@dataclass(frozen=True)
class Evidence:
    source: str
    field: str
    value: str


@dataclass(frozen=True)
class Candidate:
    key: str
    kind: str
    label: str
    reason: str
    route: str
    interaction: str
    ref_id: int | str | None
    band: int
    due_at: datetime | None
    source_order: int
    stable_order: str
    evidence: tuple[Evidence, ...]
    audiences: frozenset[str]
    push_policy: str | None

    def __post_init__(self) -> None:
        if self.interaction not in INTERACTIONS:
            raise ValueError(f"unsupported interaction: {self.interaction}")
        if self.band not in _URGENCY:
            raise ValueError(f"attention band must be 0..3, got {self.band}")
        if self.due_at is not None and self.due_at.tzinfo is not None:
            raise ValueError("attention due_at must be a timezone-naive local datetime")
        if (
            self.interaction == Interaction.ACTIVITY_INCREMENT.value
            and self.ref_id not in ACTIVITY_INCREMENT_FIELDS
        ):
            raise ValueError(f"activity field is not allowlisted: {self.ref_id}")


@dataclass(frozen=True)
class AttentionResult:
    generated_at: datetime
    next: Candidate | None
    ranked: tuple[Candidate, ...]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is not None:
            raise ValueError("attention generated_at must be a timezone-naive local datetime")


def _parse_local(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is None else None
    text_value = str(value or "").strip()
    if not text_value:
        return None
    # Accept SQLite's established local timestamps, including optional
    # fractional seconds. An explicit offset is rejected instead of silently
    # mixing an aware instant into the naive-local ordering contract.
    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        parsed = None
    if parsed is not None:
        return parsed if parsed.tzinfo is None else None
    for fmt in _LOCAL_FORMATS:
        try:
            return datetime.strptime(text_value, fmt)
        except ValueError:
            continue
    return None


def _format_time(value: datetime) -> str:
    return value.strftime("%-I:%M %p")


def _format_day(value: datetime | date) -> str:
    return value.strftime("%b %-d")


def _preload(preloaded: dict[str, Any], key: str, loader: Callable[[], Any]) -> Any:
    value = preloaded.get(key, _MISSING)
    return loader() if value is _MISSING else value


def _candidate(
    *,
    key: str,
    kind: str,
    label: str,
    reason: str,
    route: str,
    interaction: Interaction,
    ref_id: int | str | None,
    band: int,
    due_at: datetime | None,
    source: str,
    stable_order: str,
    evidence: tuple[Evidence, ...],
    chief: bool = True,
    push_policy: str | None = None,
) -> Candidate:
    audiences = frozenset({"public", "chief"} if chief else {"public"})
    return Candidate(
        key=key,
        kind=kind,
        label=label,
        reason=reason,
        route=route,
        interaction=interaction.value,
        ref_id=ref_id,
        band=band,
        due_at=due_at,
        source_order=_SOURCE_ORDER[source],
        stable_order=stable_order,
        evidence=evidence,
        audiences=audiences,
        push_policy=push_policy,
    )


def _promise_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    out: list[Candidate] = []
    cutoff = now + PROMISE_LEAD
    for row in rows:
        if row.get("status") != "new" or row.get("source", "btc") != "btc":
            continue
        due_at = _parse_local(row.get("promised_by"))
        if due_at is None or due_at > cutoff:
            continue
        band = 0 if due_at < now else 1
        request_id = int(row["id"])
        out.append(_candidate(
            key=f"promise:{request_id}",
            kind="inbound_promise",
            label=f"Confirm a booking before {_format_time(due_at)}",
            reason=(
                f"response promise passed at {_format_time(due_at)}"
                if band == 0
                else f"response promised by {_format_time(due_at)}"
            ),
            route="btc",
            interaction=Interaction.NAVIGATE,
            ref_id=request_id,
            band=band,
            due_at=due_at,
            source="promise",
            stable_order=f"{due_at.isoformat()}:{request_id:012d}",
            evidence=(Evidence("inbound_requests", "promised_by", due_at.isoformat()),),
            chief=False,
            push_policy="promise_expiring",
        ))
    return out


def _callback_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    out: list[Candidate] = []
    today = now.date()
    for row in rows:
        if row.get("stage") in {"won", "lost", "parked"} or row.get("tier") == "D":
            continue
        due_at = _parse_local(row.get("next_touch"))
        if due_at is None or due_at.date() > today:
            continue
        lead_id = int(row["id"])
        overdue = due_at.date() < today
        name = str(row.get("business_name") or "lead").strip()
        out.append(_candidate(
            key=f"lead:{lead_id}",
            kind="callback",
            label=f"Call {name}",
            reason=f"callback promised for {_format_day(due_at)}",
            route="btc",
            interaction=Interaction.NAVIGATE,
            ref_id=lead_id,
            band=0 if overdue else 1,
            due_at=due_at,
            source="callback",
            stable_order=f"{due_at.date().isoformat()}:{lead_id:012d}",
            evidence=(Evidence("leads", "next_touch", due_at.date().isoformat()),),
        ))
    return out


def _plan_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    today = now.date().isoformat()
    eligible: list[tuple[datetime, datetime, dict]] = []
    for row in rows:
        if row.get("status") != "planned" or row.get("date") != today:
            continue
        start = _parse_local(f"{today} {row.get('start_time')}:00")
        end = _parse_local(f"{today} {row.get('end_time')}:00")
        if start is None or end is None or plan.is_sailed(row, today, now.strftime("%H:%M")):
            continue
        if end <= now:
            continue
        eligible.append((start, end, row))
    if not eligible:
        return []

    current = [item for item in eligible if item[0] <= now < item[1]]
    start, end, row = min(current or eligible, key=lambda item: (item[0], int(item[2]["id"])))
    block_id = int(row["id"])
    is_current = start <= now < end
    return [_candidate(
        key=f"plan:{block_id}",
        kind="plan_block",
        label=str(row.get("title") or "Planned block").strip(),
        reason=(
            f"current block until {_format_time(end)}"
            if is_current
            else f"scheduled for {_format_time(start)}"
        ),
        route="plan",
        interaction=Interaction.NAVIGATE,
        ref_id=block_id,
        band=1 if is_current else 2,
        due_at=start,
        source="plan",
        stable_order=f"{start.isoformat()}:{block_id:012d}",
        evidence=(
            Evidence("plan_blocks", "start_time", str(row.get("start_time") or "")),
            Evidence("plan_blocks", "end_time", str(row.get("end_time") or "")),
        ),
    )]


def _goal_candidates(rows: list[dict], now: datetime, goal_lookup: dict) -> list[Candidate]:
    out: list[Candidate] = []
    today = now.date()
    latest = today + GOAL_WINDOW
    for row in rows:
        if row.get("kind") != "deadline" or row.get("archived"):
            continue
        current = str(row.get("current_value") or "").strip().lower()
        if current in db.DONE_STATES:
            continue
        try:
            deadline = date.fromisoformat(str(row.get("deadline") or ""))
        except ValueError:
            continue
        if deadline > latest:
            continue
        due_at = datetime.combine(deadline, time.min)
        goal_id = int(row["id"])
        pid = row.get("depends_on_goal_id")
        parent = goal_lookup.get(int(pid)) if pid else None
        if parent is not None and (
            parent.get("archived")
            or str(parent.get("current_value") or "").strip().lower() not in db.DONE_STATES
        ):
            out.append(_candidate(
                key=f"goal:{goal_id}",
                kind="goal_deadline",
                label=str(row.get("name") or f"Deadline #{goal_id}").strip(),
                reason=f"blocked by {parent['name']}",
                route=_ROUTES.get(str(row.get("domain") or "business"), "life"),
                interaction=Interaction.NAVIGATE,
                ref_id=goal_id,
                band=3,
                due_at=None,
                source="goal",
                stable_order=f"{deadline.isoformat()}:{goal_id:012d}",
                evidence=(Evidence("goals", "deadline", deadline.isoformat()),),
            ))
            continue
        out.append(_candidate(
            key=f"goal:{goal_id}",
            kind="goal_deadline",
            label=str(row.get("name") or f"Deadline #{goal_id}").strip(),
            reason=(
                f"deadline passed {_format_day(deadline)}"
                if deadline < today
                else f"due {_format_day(deadline)}"
            ),
            route=_ROUTES.get(str(row.get("domain") or "business"), "life"),
            interaction=Interaction.NAVIGATE,
            ref_id=goal_id,
            band=0 if deadline < today else 1,
            due_at=due_at,
            source="goal",
            stable_order=f"{deadline.isoformat()}:{goal_id:012d}",
            evidence=(Evidence("goals", "deadline", deadline.isoformat()),),
        ))
    return out


def _proposal_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    out: list[Candidate] = []
    oldest_first = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or 0))[:3]
    for row in oldest_first:
        if row.get("status") != "PENDING":
            continue
        created = _parse_local(row.get("created_at"))
        proposal_id = int(row["id"])
        age = now - created if created is not None else timedelta(0)
        old = created is not None and age > PROPOSAL_SOON
        days = max(1, int(age.total_seconds() // 86400)) if old else 0
        out.append(_candidate(
            key=f"proposal:{proposal_id}",
            kind="proposal_decision",
            label=f"Decide proposal #{proposal_id}",
            reason=(
                f"waiting {days} day{'s' if days != 1 else ''}"
                if old
                else "new decision waiting"
            ),
            route="inbox",
            interaction=Interaction.PROPOSAL_DECISION,
            ref_id=proposal_id,
            band=1 if old else 2,
            # A fresh proposal is a routine decision and participates in the
            # morning/evening routine order. Once it ages into band 1, its
            # creation time becomes the commitment tie-breaker.
            due_at=created if old else None,
            source="proposal",
            stable_order=f"{created.isoformat() if created else ''}:{proposal_id:012d}",
            evidence=((Evidence("proposals", "created_at", created.isoformat()),) if created else ()),
        ))
    return out


def _gym_candidate(gym: dict, now: datetime) -> list[Candidate]:
    if now.weekday() >= 5 or bool(gym.get("confirmed_today")):
        return []
    return [_candidate(
        key=f"gym:{now.date().isoformat()}",
        kind="gym",
        label="Confirm gym",
        reason="weekday not confirmed",
        route="body",
        interaction=Interaction.GYM_CONFIRM,
        ref_id=None,
        band=2,
        due_at=None,
        source="gym",
        stable_order=now.date().isoformat(),
        evidence=(Evidence("health_daily", "gym_confirmed", "0"),),
    )]


def _call_candidate(rows: list[dict], callback_keys: set[str], activity: dict) -> list[Candidate]:
    if int(activity.get("audit_calls") or 0) >= leads.DAILY_QUOTA:
        return []
    for row in rows:
        if row.get("stage") in {"won", "lost", "parked", "demo"} or row.get("tier") == "D":
            continue
        lead_id = int(row["id"])
        key = f"lead:{lead_id}"
        if key in callback_keys:
            continue
        name = str(row.get("business_name") or "lead").strip()
        reason = str(row.get("queue_reason") or "next callable lead").strip()
        return [_candidate(
            key=key,
            kind="call_run",
            label=f"Call {name}",
            reason=reason,
            route="btc",
            interaction=Interaction.NAVIGATE,
            ref_id=lead_id,
            band=2,
            due_at=None,
            source="call",
            stable_order=f"{lead_id:012d}",
            evidence=(Evidence("leads", "queue_reason", reason),),
        )]
    return []


def _follow_up_candidate(activity: dict, now: datetime) -> list[Candidate]:
    done = int(activity.get("follow_ups") or 0)
    target = 10
    if done >= target:
        return []
    return [_candidate(
        key=f"activity:follow_ups:{now.date().isoformat()}",
        kind="follow_up_capture",
        label="Log a follow-up",
        reason=f"{done} of {target} captured today",
        route="command",
        interaction=Interaction.ACTIVITY_INCREMENT,
        ref_id="follow_ups",
        band=2,
        due_at=None,
        source="follow_up",
        stable_order=now.date().isoformat(),
        evidence=(Evidence("activity", "follow_ups", str(done)),),
    )]


def _partner_candidate(rows: list[dict]) -> list[Candidate]:
    row = partner.next_action(rows)
    if row is None:
        return []
    task_id = int(row["id"])
    return [_candidate(
        key=f"partner:{task_id}",
        kind="partner_action",
        label=f"For Partner: {str(row.get('title') or 'next thoughtful action').strip()}",
        reason="first unfinished Partner action",
        route="partner",
        interaction=Interaction.NAVIGATE,
        ref_id=task_id,
        band=2,
        due_at=None,
        source="partner",
        stable_order=f"{task_id:012d}",
        evidence=(Evidence("partner_tasks", "done", "0"),),
        chief=False,
    )]


def _task_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    """SPEC-v41 §4.4: a priority-1 task is a band-2 candidate, forever (a
    task rolled 14 days is still band 2, age never promotes it -- rolling is
    silent by design, §9)."""
    today = now.date()
    out = []
    for row in rows:
        if not row.get("priority"):
            continue
        due = row["due_date"]
        if due == today.isoformat():
            reason = "today"
        else:
            due_date = datetime.strptime(due, "%Y-%m-%d").date()
            reason = f"since {due_date.strftime('%a')}"
        out.append(_candidate(
            key=f"task:{row['id']}",
            kind="task",
            label=row["title"],
            reason=reason,
            route="life",
            interaction=Interaction.TASK_COMPLETE,
            ref_id=row["id"],
            band=2,
            due_at=None,
            source="task",
            stable_order=f"task:{due}:{row.get('position', 0):06d}:{row['id']:012d}",
            evidence=(Evidence("tasks", "priority", "1"),),
        ))
    return out


def _school_candidates(rows: list[dict], now: datetime) -> list[Candidate]:
    out: list[Candidate] = []
    grace_window = timedelta(hours=48)
    dated_rows = []
    for row in rows:
        due_at = _parse_local(row.get("due_at"))
        if due_at is None:
            continue
        dated_rows.append((due_at, row))
    # SPEC-v32 B1: "Take the nearest 6." Cap exposure to the 6 items
    # chronologically closest to now (past or future) so a long open-item
    # backlog can never crowd the Order; the per-item band logic below still
    # drops anything more than 48h past due.
    dated_rows.sort(key=lambda pair: abs((pair[0] - now).total_seconds()))
    for due_at, row in dated_rows[:6]:
        grace = due_at + grace_window
        if due_at > now + grace_window:
            band = 2
            reason = f"due {_format_day(due_at)}"
        elif now < due_at:
            band = 1
            reason = f"due {_format_time(due_at)}"
        elif now < grace:
            band = 0
            reason = f"was due {_format_time(due_at)} -- cross it off or let it go"
        else:
            # More than 48h past due: the School page still shows it, the
            # Order must not (SPEC-v32 Law 3/7).
            continue
        item_id = int(row["id"])
        out.append(_candidate(
            key=f"school:{item_id}",
            kind="school_item",
            label=f"{row.get('course_code')} - {row.get('title')}",
            reason=reason,
            route="school",
            interaction=Interaction.NAVIGATE,
            ref_id=item_id,
            band=band,
            due_at=due_at,
            source="school",
            stable_order=f"{due_at.isoformat()}:{item_id:012d}",
            evidence=(Evidence("school_items", "due_at", due_at.isoformat()),),
        ))
    return out


def _school_meeting_candidate(meetings: list[dict], now: datetime) -> list[Candidate]:
    today = now.date()
    for meeting in meetings:
        start = _parse_local(meeting.get("start_at"))
        end = _parse_local(meeting.get("end_at"))
        if start is None or start.date() != today:
            continue
        running = end is not None and start <= now < end
        starting_soon = now < start <= now + timedelta(hours=2)
        if not (running or starting_soon):
            continue
        item_id = int(meeting["school_item_id"])
        reason = (
            f"in progress until {_format_time(end)}"
            if running
            else f"starts {_format_time(start)}"
        )
        label = f"{meeting.get('course_code')} {meeting.get('kind')} - {meeting.get('location') or meeting.get('course_name')}"
        return [_candidate(
            key=f"schoolmeet:{item_id}",
            kind="school_meeting",
            label=label,
            reason=reason,
            route="school",
            interaction=Interaction.NAVIGATE,
            ref_id=item_id,
            band=1,
            due_at=start,
            source="school_meeting",
            stable_order=f"{start.isoformat()}:{item_id:012d}",
            evidence=(Evidence("school_calendar_projection", "start_at", start.isoformat()),),
        )]
    return []


def _stale_candidates(domains: list[str]) -> list[Candidate]:
    out: list[Candidate] = []
    labels = {"health": "health", "personal": "calendar", "finance": "finance", "school": "Canvas"}
    for domain in sorted({str(item) for item in domains}):
        label = labels.get(domain, domain)
        out.append(_candidate(
            key=f"stale:{domain}",
            kind="stale_source",
            label=f"Refresh {label} data",
            reason=f"{label} source is past its freshness window",
            route="more",
            interaction=Interaction.NAVIGATE,
            ref_id=domain,
            band=3,
            due_at=None,
            source="stale",
            stable_order=domain,
            evidence=(Evidence("ingest_log", "domain", domain),),
        ))
    return out


def _fallback_gym(conn, now: datetime) -> dict:
    row = conn.execute(
        "SELECT gym_confirmed FROM health_daily WHERE date=?", (now.date().isoformat(),)
    ).fetchone()
    return {"confirmed_today": bool(row and row["gym_confirmed"])}


def _source_age_hours(row: dict | None, now: datetime) -> float | None:
    if not row:
        return None
    then = _parse_local(row.get("last_success") or row.get("last_import"))
    if then is None:
        return None
    return max(0.0, (now - then).total_seconds() / 3600)


def _fallback_stale_domains(conn, now: datetime) -> list[str]:
    domains: list[str] = []
    for domain, source in (("health", "apple_health"), ("personal", "calendar")):
        age = _source_age_hours(db.ingest_status(conn, source), now)
        if age is None or age > freshness.STALE_AFTER_HOURS:
            domains.append(domain)

    finance_config = {
        "simplefin_chase": bool(os.environ.get("SIMPLEFIN_ACCESS_URL", "").strip()),
        "snaptrade_fidelity": all(
            os.environ.get(key, "").strip()
            for key in (
                "SNAPTRADE_CLIENT_ID",
                "SNAPTRADE_CONSUMER_KEY",
            )
        ),
        "plaid_chase": all(os.environ.get(key, "").strip() for key in ("PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ACCESS_TOKEN_CHASE")),
        "plaid_capital_one": all(os.environ.get(key, "").strip() for key in ("PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ACCESS_TOKEN_CAPITAL_ONE")),
    }
    statuses = {source: db.ingest_status(conn, source) for source in finance_config}
    finance_health = freshness.evaluate_sources(statuses, finance_config, now)
    if any(item["state"] == "stale" for item in finance_health.values()):
        domains.append("finance")
    if os.environ.get("CANVAS_ICS_URL", "").strip():
        age = _source_age_hours(school.sync_state(conn), now)
        if age is None or age > 24:
            domains.append("school")
    return domains


def collect_candidates(conn, now: datetime, *, preloaded=None) -> list[Candidate]:
    """Collect phase-one candidates using only existing source-of-truth rows.

    ``preloaded`` lets ``GET /api/state`` reuse reads it already performed. A
    missing key falls back to one read; a present empty value is authoritative.
    Accepted keys are ``goals``, ``gym``, ``partner_tasks``, ``tasks``,
    ``lead_queue``, ``due_callbacks``, ``plan_blocks``, ``pending_proposals``,
    ``stale_domains``, ``active_promises``, ``activity``, ``goal_lookup``,
    ``school_items``, ``school_meetings``, and ``snoozed_keys``.
    """
    if now.tzinfo is not None:
        raise ValueError("attention now must be a timezone-naive local datetime")
    loaded = preloaded or {}
    today = now.date().isoformat()

    promise_rows = _preload(loaded, "active_promises", lambda: db.active_promises(conn)) or []
    callback_rows = _preload(loaded, "due_callbacks", lambda: leads.due_callbacks(conn, today)) or []
    plan_rows = _preload(loaded, "plan_blocks", lambda: db.plan_blocks_for_date(conn, today)) or []
    goal_rows = _preload(loaded, "goals", lambda: db.all_goals(conn)) or []
    goal_lookup = _preload(loaded, "goal_lookup", lambda: db.goal_lookup_all(conn)) or {}
    proposal_rows = _preload(loaded, "pending_proposals", lambda: db.pending_proposals(conn)) or []
    gym = _preload(loaded, "gym", lambda: _fallback_gym(conn, now)) or {}
    queue = _preload(loaded, "lead_queue", lambda: leads.call_queue(conn, today)) or []
    activity = _preload(
        loaded,
        "activity",
        lambda: dict(conn.execute("SELECT * FROM activity WHERE date=?", (today,)).fetchone() or {}),
    ) or {}
    partner_rows = _preload(loaded, "partner_tasks", lambda: db.all_partner_tasks(conn)) or []
    task_rows = _preload(loaded, "tasks", lambda: db.tasks_today(conn, today)) or []
    stale_domains = _preload(
        loaded, "stale_domains", lambda: _fallback_stale_domains(conn, now)
    ) or []
    school_rows = _preload(
        loaded, "school_items", lambda: school.dashboard_snapshot(conn)["upcoming"]
    ) or []
    school_meeting_rows = _preload(
        loaded, "school_meetings", lambda: school.dashboard_snapshot(conn)["next_meetings"]
    ) or []
    snoozed_keys = _preload(loaded, "snoozed_keys", lambda: db.active_snooze_keys(conn)) or set()

    callbacks = _callback_candidates(callback_rows, now)
    candidates = [
        *_promise_candidates(promise_rows, now),
        *callbacks,
        *_plan_candidates(plan_rows, now),
        *_goal_candidates(goal_rows, now, goal_lookup),
        *_proposal_candidates(proposal_rows, now),
        *_gym_candidate(gym, now),
        *_call_candidate(queue, {item.key for item in callbacks}, activity),
        *_follow_up_candidate(activity, now),
        *_partner_candidate(partner_rows),
        *_task_candidates(task_rows, now),
        *_school_candidates(school_rows, now),
        *_school_meeting_candidate(school_meeting_rows, now),
        *_stale_candidates(stale_domains),
    ]
    # SPEC-v37 §4.2 Ring 1 `attention.snooze`: suppress an item from the
    # order entirely (not just demote it) for up to 7 days, one item.
    if snoozed_keys:
        candidates = [c for c in candidates if c.key not in snoozed_keys]
    return candidates


_MORNING_ROUTINE = {
    "gym": 0,
    "call_run": 1,
    "follow_up_capture": 2,
    "proposal_decision": 3,
    "partner_action": 4,
    "task": 5,
    "school_item": 6,
}
_EVENING_ROUTINE = {
    "school_item": 0,
    "proposal_decision": 1,
    "partner_action": 2,
    "task": 3,
    "call_run": 4,
    "follow_up_capture": 5,
    "gym": 6,
}


def routine_session_order(candidate: Candidate, now: datetime) -> int:
    if candidate.band != 2:
        return 0
    order = _MORNING_ROUTINE if now.hour < 12 else _EVENING_ROUTINE
    return order.get(candidate.kind, len(order) + 1)


def rank_candidates(candidates, now: datetime) -> list[Candidate]:
    """Pure lexicographic ordering from SPEC-v21, with duplicate-key guard."""
    if now.tzinfo is not None:
        raise ValueError("attention now must be a timezone-naive local datetime")
    items = list(candidates)
    keys = [item.key for item in items]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    if duplicates:
        raise ValueError(f"duplicate attention candidate key(s): {', '.join(duplicates)}")
    return sorted(items, key=lambda candidate: (
        candidate.band,
        candidate.due_at or datetime.max,
        routine_session_order(candidate, now),
        candidate.source_order,
        candidate.stable_order,
        candidate.key,
    ))


def compile_attention(conn, now: datetime, *, preloaded=None) -> AttentionResult:
    ranked = tuple(rank_candidates(collect_candidates(conn, now, preloaded=preloaded), now))
    return AttentionResult(generated_at=now, next=ranked[0] if ranked else None, ranked=ranked)


def _project(candidate: Candidate) -> dict:
    return {
        "key": candidate.key,
        "kind": candidate.kind,
        "label": candidate.label,
        "reason": candidate.reason,
        "route": candidate.route,
        "interaction": {"type": candidate.interaction, "ref_id": candidate.ref_id},
        "due_at": candidate.due_at.isoformat() if candidate.due_at else None,
        "urgency": _URGENCY[candidate.band],
    }


def public_projection(result: AttentionResult, limit=4) -> dict:
    """Return the compact public view: one primary plus up to three secondary."""
    total = max(0, min(4, int(limit)))
    visible = list(result.ranked[:total])
    return {
        "next": _project(visible[0]) if visible else None,
        "items": [_project(item) for item in visible[1:]],
    }


def agent_projection(result: AttentionResult, role) -> list[dict]:
    """Filter without reranking; only explicit role audiences survive."""
    role_name = str(role or "").strip().lower()
    return [
        {
            "key": item.key,
            "kind": item.kind,
            "label": item.label,
            "reason": item.reason,
            "route": item.route,
            "due_at": item.due_at.isoformat() if item.due_at else None,
            "urgency": _URGENCY[item.band],
        }
        for item in result.ranked
        if role_name in item.audiences
    ]


def push_projection(candidate: Candidate) -> tuple[str, str] | None:
    """Allowlisted copy only. Delivery and durable fire-once state stay outside."""
    if candidate.push_policy != "promise_expiring" or candidate.kind != "inbound_promise":
        return None
    when = _format_time(candidate.due_at) if candidate.due_at else "soon"
    return "ianOS: promise expiring", f"A booking confirmation is due by {when}."
