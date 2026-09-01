"""SPEC-v37 §4: tiered agency, Ring 1.

Ring 1 acts apply immediately, no approval, and every one is receipted and
undoable (Law A5: the receipt and the act share one transaction, and the
write helper raises rather than proceeding if the receipt insert fails). The
list is closed -- the ten rows of §4.2's table, expanded to the 13 dotted
act strings in RING1_ACTS (plan_block and partner_task each cover a few) -- and
adding one needs a spec amendment, a reversibility proof, and a test (§13
non-goals).

This module is pure orchestration: validate the act's own bound, perform the
write through a core.db helper (called with commit=False so nothing lands
until the receipt does), capture what undo needs in `inverse_json`, and
record the receipt. Raw table I/O lives in core.db, the same layering
core.streaks and core.plan already use for pure logic over db's writes.

Law A4: the ring is a property of the act, not the agent -- RING1_GRANTS
below is the only place role eligibility is decided, and every apply_*
function checks it before touching anything.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from core import db

MAX_SNOOZE_DAYS = 7


class ActError(Exception):
    """A Ring 1 act's own bound was violated. Not a system failure -- the
    caller (a tool wrapper) is expected to turn this into a denial the model
    can read and adapt to, never a crash."""


RING1_ACTS = (
    "plan_block.create", "plan_block.move", "plan_block.delete",
    "note.create",
    "partner_task.create", "partner_task.complete",
    "gym.confirm",
    "activity.log",
    "goal.rebaseline", "goal.archive",
    "transaction.recategorize",
    "fact.flag_unverified",
    "attention.snooze",
)

# SPEC-v37 §4.4. "fact.flag_unverified" is granted to every role and is
# deliberately absent from these per-role sets; ring1_allowed() adds it back
# in one place rather than repeating it ten times.
RING1_GRANTS: dict[str, frozenset[str]] = {
    "steward": frozenset(RING1_ACTS),
    "watchdog": frozenset({"goal.rebaseline", "goal.archive", "attention.snooze"}),
    "cfo": frozenset({"transaction.recategorize"}),
    "scout": frozenset({"activity.log"}),
    "coach": frozenset({"gym.confirm"}),
    "physician": frozenset(),
    "lovebird": frozenset({"partner_task.create"}),
    "wealth": frozenset(),
    "counsel": frozenset(),
    "chief": frozenset(),
}


def ring1_allowed(role: str, act: str) -> bool:
    if act == "fact.flag_unverified":
        return True
    return act in RING1_GRANTS.get(role, frozenset())


def _require(role: str, act: str) -> None:
    if not ring1_allowed(role, act):
        raise ActError(f"{role} may not apply {act}")


def _apply(conn, *, role: str, act: str, plane: str, thread_id: int | None,
           target_kind: str, target_id, summary: str, inverse: dict, write) -> dict:
    """Law A5. `write()` performs the act's own conn.execute calls with
    commit=False and returns the resulting row. Everything -- the write, the
    receipt, the ian-visible memo -- commits together or not at all.

    `target_id` may be a callable taking the write's result, for a
    create-act whose id doesn't exist until after write() runs."""
    if plane not in ("nightly", "consult"):
        raise ActError(f"unknown plane: {plane}")
    try:
        result = write()
        resolved_id = target_id(result) if callable(target_id) else target_id
        act_id = db.insert_agent_act(
            conn, role=role, act=act, plane=plane, thread_id=thread_id,
            target_kind=target_kind, target_id=str(resolved_id), summary=summary,
            inverse=inverse,
        )
        db.add_memo(conn, role, act, summary, priority=1, commit=False)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.commit()
    return {"act_id": act_id, "result": result}


# ------------------------------------------------------------- plan_block

def plan_block_create(conn, *, role: str, plane: str, thread_id: int | None,
                       date_: str, start_time: str, end_time: str, title: str,
                       goal_id: int | None = None) -> dict:
    _require(role, "plan_block.create")
    if date_ < db.today():
        raise ActError("plan_block.create: date must be today or later")
    _validate_block_times(start_time, end_time)
    return _apply(
        conn, role=role, act="plan_block.create", plane=plane, thread_id=thread_id,
        target_kind="plan_block", target_id=lambda result: result["id"],
        summary=f'{role} scheduled "{title}" on {date_} {start_time}-{end_time}.',
        inverse={"act": "plan_block.create"},
        write=lambda: db.create_plan_block(
            conn, date_, start_time, end_time, title, goal_id, commit=False),
    )


def plan_block_move(conn, *, role: str, plane: str, thread_id: int | None,
                     block_id: int, date_: str, start_time: str, end_time: str) -> dict:
    _require(role, "plan_block.move")
    before = db.get_plan_block(conn, block_id)
    if before is None:
        raise ActError("plan_block.move: block not found")
    if date_ < db.today():
        raise ActError("plan_block.move: date must be today or later")
    _validate_block_times(start_time, end_time)
    return _apply(
        conn, role=role, act="plan_block.move", plane=plane, thread_id=thread_id,
        target_kind="plan_block", target_id=block_id,
        summary=f'{role} moved "{before["title"]}" to {date_} {start_time}-{end_time}.',
        inverse={
            "act": "plan_block.move", "block_id": block_id,
            "date": before["date"], "start_time": before["start_time"],
            "end_time": before["end_time"],
        },
        write=lambda: db.update_plan_block(
            conn, block_id, date=date_, start_time=start_time, end_time=end_time,
            commit=False),
    )


def plan_block_delete(conn, *, role: str, plane: str, thread_id: int | None,
                       block_id: int) -> dict:
    _require(role, "plan_block.delete")
    before = db.get_plan_block(conn, block_id)
    if before is None:
        raise ActError("plan_block.delete: block not found")
    return _apply(
        conn, role=role, act="plan_block.delete", plane=plane, thread_id=thread_id,
        target_kind="plan_block", target_id=block_id,
        summary=f'{role} deleted "{before["title"]}" ({before["date"]}).',
        inverse={"act": "plan_block.delete", "row": before},
        write=lambda: db.delete_plan_block(conn, block_id, commit=False),
    )


def _validate_block_times(start_time: str, end_time: str) -> None:
    for t in (start_time, end_time):
        if not (isinstance(t, str) and len(t) == 5 and t[2] == ":"
                and t[:2].isdigit() and t[3:].isdigit()):
            raise ActError("plan_block times must be HH:MM")
    if end_time <= start_time:
        raise ActError("plan_block end_time must be after start_time")


# ------------------------------------------------------------------ note

def note_create(conn, *, role: str, plane: str, thread_id: int | None,
                 body: str, domain: str | None = None,
                 folder_id: int | None = None) -> dict:
    _require(role, "note.create")
    return _apply(
        conn, role=role, act="note.create", plane=plane, thread_id=thread_id,
        target_kind="note", target_id=lambda result: result["id"],
        summary=f"{role} added a note.",
        inverse={"act": "note.create"},
        write=lambda: db.create_note(conn, body=body, domain=domain,
                                      folder_id=folder_id, commit=False),
    )


# ------------------------------------------------------------ partner_task

def partner_task_create(conn, *, role: str, plane: str, thread_id: int | None,
                       title: str, notes: str = "",
                       parent_id: int | None = None) -> dict:
    _require(role, "partner_task.create")
    return _apply(
        conn, role=role, act="partner_task.create", plane=plane, thread_id=thread_id,
        target_kind="partner_task", target_id=lambda result: result["id"],
        summary=f'{role} added "{title}" for Partner.',
        inverse={"act": "partner_task.create"},
        write=lambda: db.add_partner_task(conn, title, notes, parent_id, commit=False),
    )


def partner_task_complete(conn, *, role: str, plane: str, thread_id: int | None,
                         task_id: int) -> dict:
    _require(role, "partner_task.complete")
    before = db.get_partner_task(conn, task_id)
    if before is None:
        raise ActError("partner_task.complete: task not found")
    was_done = bool(before.get("done"))
    return _apply(
        conn, role=role, act="partner_task.complete", plane=plane, thread_id=thread_id,
        target_kind="partner_task", target_id=task_id,
        summary=f'{role} marked "{before["title"]}" done for Partner.',
        inverse={"act": "partner_task.complete", "task_id": task_id, "was_done": was_done},
        write=lambda: db.update_partner_task(conn, task_id, done=True, commit=False),
    )


# --------------------------------------------------------------- gym.confirm

def gym_confirm(conn, *, role: str, plane: str, thread_id: int | None) -> dict:
    """Today only; never writes grace or reset (SPEC-v37 §4.2). `confirm_gym`/
    `unconfirm_gym` already only ever touch `gym_confirmed` and the mirrored
    'confirm' streak event, so today's date is the only restriction to add."""
    _require(role, "gym.confirm")
    today = db.today()
    return _apply(
        conn, role=role, act="gym.confirm", plane=plane, thread_id=thread_id,
        target_kind="gym", target_id=today,
        summary=f"{role} confirmed today's workout.",
        inverse={"act": "gym.confirm", "day": today},
        write=lambda: db.confirm_gym(conn, today, commit=False),
    )


# -------------------------------------------------------------- activity.log

def activity_log(conn, *, role: str, plane: str, thread_id: int | None,
                  audit_calls: int = 0, follow_ups: int = 0, demos: int = 0,
                  conversations: int = 0) -> dict:
    """Increments only (SPEC-v37 §4.2): every field must be >= 0. The
    inverse is the exact negative delta through the same `log_activity`
    accumulator, not a separate code path."""
    _require(role, "activity.log")
    for n in (audit_calls, follow_ups, demos, conversations):
        if n < 0:
            raise ActError("activity.log only increments (no negative deltas)")
    if not any((audit_calls, follow_ups, demos, conversations)):
        raise ActError("activity.log needs at least one nonzero field")
    today = db.today()
    parts = []
    if audit_calls:
        parts.append(f"{audit_calls} audit call(s)")
    if follow_ups:
        parts.append(f"{follow_ups} follow-up(s)")
    if demos:
        parts.append(f"{demos} demo(s)")
    if conversations:
        parts.append(f"{conversations} conversation(s)")
    return _apply(
        conn, role=role, act="activity.log", plane=plane, thread_id=thread_id,
        target_kind="activity", target_id=today,
        summary=f"{role} logged {', '.join(parts)}.",
        inverse={
            "act": "activity.log", "day": today,
            "audit_calls": audit_calls, "follow_ups": follow_ups,
            "demos": demos, "conversations": conversations,
        },
        write=lambda: db.log_activity(
            conn, today, audit_calls=audit_calls, follow_ups=follow_ups,
            demos=demos, conversations=conversations, commit=False),
    )


# ------------------------------------------------------------------- goal

def goal_rebaseline(conn, *, role: str, plane: str, thread_id: int | None,
                     goal_id: int, target: str | None = None,
                     deadline: str | None = None) -> dict:
    _require(role, "goal.rebaseline")
    before = db.get_goal(conn, goal_id)
    if before is None:
        raise ActError("goal.rebaseline: goal not found")
    if target is None and deadline is None:
        raise ActError("goal.rebaseline needs a target or a deadline")
    bits = []
    if target is not None:
        bits.append(f"target {before['target']} -> {target}")
    if deadline is not None:
        bits.append(f"deadline {before.get('deadline') or 'none'} -> {deadline}")
    return _apply(
        conn, role=role, act="goal.rebaseline", plane=plane, thread_id=thread_id,
        target_kind="goal", target_id=goal_id,
        summary=f'{role} rebaselined "{before["name"]}": {", ".join(bits)}.',
        inverse={
            "act": "goal.rebaseline", "goal_id": goal_id,
            "target": before["target"], "deadline": before.get("deadline"),
        },
        # deadline is omitted (not passed as None) when unset: db.rebaseline_goal
        # treats an explicit deadline=None as "clear it", which this forward
        # act never does -- only undo needs that, to restore a goal that had
        # no deadline before the rebaseline.
        write=lambda: db.rebaseline_goal(
            conn, goal_id, commit=False,
            **({"target": target} if target is not None else {}),
            **({"deadline": deadline} if deadline is not None else {}),
        ),
    )


def goal_archive(conn, *, role: str, plane: str, thread_id: int | None,
                  goal_id: int, now: date | None = None) -> dict:
    """Deadline > 14 days past and no unarchived goal depends on it
    (SPEC-v37 §4.2)."""
    _require(role, "goal.archive")
    before = db.get_goal(conn, goal_id)
    if before is None:
        raise ActError("goal.archive: goal not found")
    if before.get("archived"):
        raise ActError("goal.archive: already archived")
    deadline = before.get("deadline")
    if not deadline:
        raise ActError("goal.archive: goal has no deadline")
    today = now or date.today()
    days_past = (today - date.fromisoformat(deadline)).days
    if days_past <= 14:
        raise ActError("goal.archive: deadline must be more than 14 days past")
    if db.goal_has_unarchived_dependent(conn, goal_id):
        raise ActError("goal.archive: another goal still depends on this one")
    return _apply(
        conn, role=role, act="goal.archive", plane=plane, thread_id=thread_id,
        target_kind="goal", target_id=goal_id,
        summary=f'{role} archived "{before["name"]}", {days_past}d past deadline.',
        inverse={"act": "goal.archive", "goal_id": goal_id},
        write=lambda: db.archive_goal(conn, goal_id, archived=True, commit=False),
    )


# ----------------------------------------------------- transaction.recategorize

def transaction_recategorize(conn, *, role: str, plane: str, thread_id: int | None,
                              transaction_id: int, category: str) -> dict:
    _require(role, "transaction.recategorize")
    before = db.get_transaction(conn, transaction_id)
    if before is None:
        raise ActError("transaction.recategorize: transaction not found")
    return _apply(
        conn, role=role, act="transaction.recategorize", plane=plane, thread_id=thread_id,
        target_kind="transaction", target_id=transaction_id,
        summary=(f'{role} recategorized "{before["description"]}": '
                 f'{before["category"] or "(none)"} -> {category}.'),
        inverse={
            "act": "transaction.recategorize", "transaction_id": transaction_id,
            "category": before["category"],
        },
        write=lambda: db.recategorize_transaction(conn, transaction_id, category,
                                                    commit=False),
    )


# ------------------------------------------------------- fact.flag_unverified

def fact_flag_unverified(conn, *, role: str, plane: str, thread_id: int | None,
                          fact_id: int) -> dict:
    """Sets verified=0; can never set it to 1 (SPEC-v37 §4.2) -- there is no
    `verified` argument here at all, only a fact to flag."""
    _require(role, "fact.flag_unverified")
    before = db.get_fact(conn, fact_id)
    if before is None:
        raise ActError("fact.flag_unverified: fact not found")
    was_verified = bool(before.get("verified"))
    return _apply(
        conn, role=role, act="fact.flag_unverified", plane=plane, thread_id=thread_id,
        target_kind="fact", target_id=fact_id,
        summary=f'{role} flagged "{before["topic"]}" as unverified.',
        inverse={"act": "fact.flag_unverified", "fact_id": fact_id,
                 "was_verified": was_verified},
        write=lambda: db.set_fact_verified(conn, fact_id, 0, commit=False),
    )


# ----------------------------------------------------------- attention.snooze

def attention_snooze(conn, *, role: str, plane: str, thread_id: int | None,
                      item_key: str, label: str = "", days: int = 3,
                      now: datetime | None = None) -> dict:
    """Max 7 days, one item (SPEC-v37 §4.2). A fresh snooze on an
    already-snoozed key replaces it (attention_snoozes is keyed on item_key),
    so this act is one item at a time by construction."""
    _require(role, "attention.snooze")
    days = int(days)
    if not (0 < days <= MAX_SNOOZE_DAYS):
        raise ActError(f"attention.snooze: days must be 1-{MAX_SNOOZE_DAYS}")
    if not item_key:
        raise ActError("attention.snooze: item_key is required")
    now = now or datetime.now()
    prior = conn.execute(
        "SELECT snoozed_until FROM attention_snoozes WHERE item_key = ?", (item_key,)
    ).fetchone()
    prior_until = prior[0] if prior else None
    until = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    return _apply(
        conn, role=role, act="attention.snooze", plane=plane, thread_id=thread_id,
        target_kind="attention_item", target_id=item_key,
        summary=f'{role} snoozed "{label or item_key}" for {days}d.',
        inverse={"act": "attention.snooze", "item_key": item_key, "prior_until": prior_until},
        write=lambda: db.set_attention_snooze(conn, item_key, until, commit=False),
    )


# ---------------------------------------------------------------------- undo

_UNDO_HANDLERS = {}


def _undo(act):
    def register(fn):
        _UNDO_HANDLERS[act] = fn
        return fn
    return register


@_undo("plan_block.create")
def _undo_plan_block_create(conn, receipt: dict, inverse: dict) -> None:
    db.delete_plan_block(conn, int(receipt["target_id"]), commit=False)


@_undo("plan_block.move")
def _undo_plan_block_move(conn, receipt: dict, inverse: dict) -> None:
    db.update_plan_block(
        conn, inverse["block_id"], date=inverse["date"],
        start_time=inverse["start_time"], end_time=inverse["end_time"], commit=False,
    )


@_undo("plan_block.delete")
def _undo_plan_block_delete(conn, receipt: dict, inverse: dict) -> None:
    db.restore_plan_block(conn, inverse["row"], commit=False)


@_undo("note.create")
def _undo_note_create(conn, receipt: dict, inverse: dict) -> None:
    db.delete_note(conn, int(receipt["target_id"]), commit=False)


@_undo("partner_task.create")
def _undo_partner_task_create(conn, receipt: dict, inverse: dict) -> None:
    db.archive_partner_task(conn, int(receipt["target_id"]),
                           f"ring1-undo-{receipt['id']}", commit=False)


@_undo("partner_task.complete")
def _undo_partner_task_complete(conn, receipt: dict, inverse: dict) -> None:
    db.update_partner_task(conn, inverse["task_id"], done=inverse["was_done"], commit=False)


@_undo("gym.confirm")
def _undo_gym_confirm(conn, receipt: dict, inverse: dict) -> None:
    db.unconfirm_gym(conn, inverse["day"], commit=False)


@_undo("activity.log")
def _undo_activity_log(conn, receipt: dict, inverse: dict) -> None:
    db.log_activity(
        conn, inverse["day"],
        audit_calls=-inverse["audit_calls"], follow_ups=-inverse["follow_ups"],
        demos=-inverse["demos"], conversations=-inverse["conversations"], commit=False,
    )


@_undo("goal.rebaseline")
def _undo_goal_rebaseline(conn, receipt: dict, inverse: dict) -> None:
    db.rebaseline_goal(conn, inverse["goal_id"], target=inverse["target"],
                        deadline=inverse["deadline"], commit=False)


@_undo("goal.archive")
def _undo_goal_archive(conn, receipt: dict, inverse: dict) -> None:
    db.archive_goal(conn, inverse["goal_id"], archived=False, commit=False)


@_undo("transaction.recategorize")
def _undo_transaction_recategorize(conn, receipt: dict, inverse: dict) -> None:
    db.recategorize_transaction(conn, inverse["transaction_id"], inverse["category"],
                                 commit=False)


@_undo("fact.flag_unverified")
def _undo_fact_flag_unverified(conn, receipt: dict, inverse: dict) -> None:
    db.set_fact_verified(conn, inverse["fact_id"], 1 if inverse["was_verified"] else 0,
                          commit=False)


@_undo("attention.snooze")
def _undo_attention_snooze(conn, receipt: dict, inverse: dict) -> None:
    if inverse.get("prior_until"):
        db.set_attention_snooze(conn, inverse["item_key"], inverse["prior_until"], commit=False)
    else:
        db.clear_attention_snooze(conn, inverse["item_key"], commit=False)


def undo_act(conn, act_id: int) -> dict:
    """Applies inverse_json through the same write path that made the
    change (Law A5's undo half), then stamps undone_at. Available forever;
    calling it twice on an already-undone act is a no-op error, not a
    second reversal."""
    receipt = db.get_agent_act(conn, act_id)
    if receipt is None:
        raise ActError("act not found")
    if receipt.get("undone_at"):
        raise ActError("act already undone")
    handler = _UNDO_HANDLERS.get(receipt["act"])
    if handler is None:
        raise ActError(f"no undo handler for {receipt['act']}")
    inverse = json.loads(receipt["inverse_json"])
    try:
        handler(conn, receipt, inverse)
        db.mark_act_undone(conn, act_id, commit=False)
        db.add_memo(conn, "ian", "undo", f"Undid: {receipt['summary']}", commit=False)
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    conn.commit()
    return db.get_agent_act(conn, act_id)
