"""Shared Partner task semantics over the flat active task read model.

Partner intentionally supports one level only: a top-level outcome may have
steps, while a step can never have children.  This module owns the meaning of
"open" so every presentation surface agrees without storing derived state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TaskGroup:
    """One top-level outcome and its active steps, in stable id order."""

    parent: dict[str, Any]
    children: tuple[dict[str, Any], ...]


def _active_copy(row: Mapping[str, Any]) -> dict[str, Any] | None:
    copied = dict(row)
    if copied.get("deleted_at") is not None:
        return None
    copied["done"] = bool(copied.get("done"))
    return copied


def group_tasks(rows: Iterable[Mapping[str, Any]]) -> list[TaskGroup]:
    """Group a flat active read without mutating its input rows.

    Archived rows are ignored defensively so optimistic callers cannot count a
    row that has already been removed.  An orphan or a second level is a data
    integrity error rather than something this pure projection silently fixes.
    """

    active = [task for row in rows if (task := _active_copy(row)) is not None]
    parents = {
        int(task["id"]): task for task in active if task.get("parent_id") is None
    }
    children: dict[int, list[dict[str, Any]]] = {task_id: [] for task_id in parents}

    for task in active:
        parent_id = task.get("parent_id")
        if parent_id is None:
            continue
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Partner step has an invalid parent") from exc
        if parent_id not in parents:
            raise ValueError("Partner step has no active top-level parent")
        children[parent_id].append(task)

    return [
        TaskGroup(
            parent=parents[parent_id],
            children=tuple(sorted(children[parent_id], key=lambda task: int(task["id"]))),
        )
        for parent_id in sorted(parents)
    ]


def group_complete(parent: Mapping[str, Any], children: Iterable[Mapping[str, Any]]) -> bool:
    """A group is complete only when its outcome and every active step are done."""

    return bool(parent.get("done")) and all(bool(child.get("done")) for child in children)


def actionable_tasks(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the unfinished leaves that represent real next actions.

    Open steps suppress their parent outcome.  Once every active step is done,
    an unfinished parent becomes the remaining actionable outcome.
    """

    actionable: list[dict[str, Any]] = []
    for group in group_tasks(rows):
        open_children = [child for child in group.children if not child["done"]]
        if open_children:
            actionable.extend(open_children)
        elif not group.parent["done"]:
            actionable.append(group.parent)
    return actionable


def open_count(rows: Iterable[Mapping[str, Any]]) -> int:
    """Count actionable leaves, never raw unfinished database rows."""

    return len(actionable_tasks(rows))


def next_action(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Choose the first stable action by root id, then unfinished child id."""

    actions = actionable_tasks(rows)
    return actions[0] if actions else None


__all__ = [
    "TaskGroup",
    "actionable_tasks",
    "group_complete",
    "group_tasks",
    "next_action",
    "open_count",
]
