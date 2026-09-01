# SPEC v22: Partner one-level steps

Status: **proposed**. Depends on SPEC-v20 mutation receipts. Feeds SPEC-v21
through a single Partner semantics module.

## 0. Purpose

Partner is deliberately not a project manager. It is a private, light list of
things Ian wants to do for his girlfriend. Some outcomes need a few concrete
steps, and flattening them loses the plan. Arbitrary nesting would turn the
page into a productivity system it should never become.

This spec adds exactly one child level. It makes deletion reversible, keeps the
page intimate on a phone, and defines one shared meaning for "what is still
open" so Partner, Command, Plan, pills, and badges never disagree.

## 1. Product and data laws

1. **One level only.** A top-level outcome may have steps. A step cannot have
   children. There is no drag ordering, dependency graph, reparenting, or
   general project hierarchy.
2. **Steps describe work, parents describe outcomes.** Completing a parent
   never completes a step. Completing all steps never silently completes the
   parent.
3. **No hard delete.** A removal soft-archives the target, and a parent
   removal atomically archives its active subtree. Undo restores the same ids.
4. **One semantics module.** No component counts `done=0` on its own.
   `core.partner` defines actionable leaves and every consumer uses it.
5. **No agent writes.** Agents have no Partner task tool. The API is the only
   writer, and every mutation is protected by SPEC-v20's receipt boundary.
6. **Offline does not pretend.** A pending parent has no canonical server id,
   so it cannot accept a step until it syncs. Archive then Undo remains FIFO
   with stable mutation ids.
7. **The list stays kind.** No percentage, streak, scolding, red personal
   routine state, cramped hierarchy control, or desktop-first layout.

## 2. Prerequisite: receipts before steps

Do not ship this schema or UI before SPEC-v20 Phase A covers every existing
queueable write:

- Partner create, patch, archive, and restore
- gym confirmation
- activity increments and notes
- wellness writes

The prerequisite is load-bearing. The old queue gives its random id no server
meaning and creates it too late to cover an ambiguous first response. A
lost response can duplicate a top-level task, a step, or an Ian memo. It can
also move a before-midnight activity capture to the replay day. The v20
mutation id, atomic receipt, captured effective date, and single-flight flush
are required before offline child creation, archive, or Undo is credible.

## 3. Schema and migration

Extend `partner_tasks` in `core/db.py` through the existing idempotent migration
path:

```sql
parent_id        INTEGER REFERENCES partner_tasks(id),
deleted_at       TEXT,
deleted_batch_id TEXT
```

Add an index over active hierarchy queries:

```sql
CREATE INDEX IF NOT EXISTS idx_partner_active_parent_done
    ON partner_tasks(parent_id, deleted_at, done, id);
```

Existing rows remain top-level (`parent_id IS NULL`) and active. The seed
routine must continue to count all historical rows, including archived ones,
so deleting the seed defaults never causes them to reappear.

`all_partner_tasks(conn)` becomes the one active read path and filters
`deleted_at IS NULL` unless an explicit archive path asks otherwise. It
continues to return a flat list with boolean `done`, preserving the current
state contract. Its active order is group-first,
`ORDER BY COALESCE(parent_id, id), CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id`,
not raw `done ASC`; a checked parent must remain adjacent to an unfinished
child. The UI groups by `parent_id`; it does not require a separate nested data
source.

`deleted_batch_id` is essential. `deleted_at` alone cannot distinguish a child
deleted before its parent from a child archived as part of the parent removal.
Undo restores exactly the rows stamped in one removal batch and never revives
an earlier deletion.

## 4. Hierarchy validation

These rules belong in a transaction-safe DB helper, API validation, and tests.
A SQLite trigger may be added as defense in depth, never as the only guard.

- A parent has `parent_id IS NULL`.
- A step points to one active top-level parent.
- A step cannot receive children.
- A row that has active children cannot become a step.
- `parent_id` is written only at creation and is immutable.
- A row cannot parent itself.
- A missing or archived parent yields 404.
- A child-of-child attempt, self-parent, or other one-level violation yields
  409.

No migration API silently repairs bad hierarchy input. Reject it with a useful
error, preserve existing state, and leave no receipt for a validation failure.

## 5. Completion and action semantics

Add `core/partner.py`, a small pure module over flat active task rows:

```python
def group_tasks(rows) -> list[TaskGroup]
def actionable_tasks(rows) -> list[dict]
def open_count(rows) -> int
def next_action(rows) -> dict | None
def group_complete(parent, children) -> bool
```

Definitions:

- A standalone unfinished top-level task is one actionable leaf.
- An unfinished child is one actionable leaf.
- An unfinished parent whose active children are all done is one actionable
  leaf, because the outcome itself remains to finish.
- A parent with one or more unfinished children is not separately counted.
- A group is visually complete only when its parent and every active child are
  complete.

`next_action()` is stable: process groups by their root parent/standalone id
ascending. Within a group, return the lowest-id unfinished child first; if no
active child is unfinished and the parent is unfinished, return the parent
outcome. This gives Command a predictable next task without inventing priority
or drag ordering.

Consequences:

- Parent done plus an unfinished child remains open and counts the child.
- All children done plus an unfinished parent remains open and counts the
  parent.
- Parent and all children done moves together to Done and counts zero.
- Deleting the final active child returns a parent to standalone semantics.

Use this module in `core/pillars.py`, Plan's Partner suggestion, SPEC-v21's
attention collector, API summary generation, the Nav badge, and Partner page
copy. No consumer may count rows ad hoc.

## 6. API contract

### Create a top-level task or step

`POST /api/partner-tasks` gains an optional `parent_id`:

```json
{
  "title": "Plan the date",
  "notes": "",
  "parent_id": null
}
```

For a step, `parent_id` is a live top-level task id. This route is mutation-id
protected and sends the same captured receipt data as all queueable actions.

### Update

`PATCH /api/partner-tasks/{id}` continues to accept only `title`, `notes`, and
the explicit desired `done` value. It rejects `parent_id` rather than silently
ignoring it. Explicit desired values make retries idempotent; do not introduce
a toggle endpoint. PATCH selects active rows only. A stale queued patch after
archive returns 404/terminal conflict and never edits hidden state that could
later return changed.

### Archive

Keep `DELETE /api/partner-tasks/{id}` for compatibility but change its meaning:

- Deleting a child stamps that active row only.
- Deleting a parent stamps the parent and its active children in one
  transaction.
- The deletion's mutation id is the `deleted_batch_id`. Older already archived
  children retain their older batch and are not restamped.
- The archive, one explanatory Ian memo, and mutation receipt commit together.
- A new archive request against an already archived row returns 404. Repeating
  the same mutation id returns its stored receipt instead.

Return:

```json
{
  "ok": true,
  "archive_batch_id": "uuid",
  "archived_ids": [8, 9, 10]
}
```

### Restore

Add a deliberate restore endpoint:

```http
POST /api/partner-tasks/archive/{batch_id}/restore
```

It clears `deleted_at` and `deleted_batch_id` only for rows in that batch,
returns the restored rows, and has its own mutation receipt. Repeating a
restore request returns the stored replay response. The UI exposes Undo for at
least five seconds; the server keeps the operation reversible rather than
using a fragile timing-based hard delete.

A child-only batch can restore only when its parent is active. If its parent is
still archived, return 409 and leave the child hidden. This prevents a restored
active orphan after an earlier child archive followed by parent archive.

## 7. State and downstream contract

`/api/state.partner_tasks` remains a flat active list for backward compatibility.
Add a compact shared summary:

```json
"partner_summary": {
  "open_count": 3,
  "next_task_id": 14
}
```

Consumers change as follows:

| Consumer | Required change |
|---|---|
| Pillars | use `core.partner.open_count()` |
| Plan suggestions | offer Partner time only when actionable leaves exist |
| Command | render SPEC-v21 attention, never `tasks.find(!done)` |
| Nav badge | use `partner_summary.open_count` |
| Partner subtitle | use actionable count, never raw unfinished row count |

The first deployment may retain the existing state array and add the summary.
Do not introduce a second serialized hierarchy that can drift from the flat
source rows.

The Python module is authoritative. For optimistic React state, add a small
`dashboard/src/lib/partner.js` mirror with the same grouping/count/next rules and
one shared JSON fixture suite exercised by both Python and Node tests. This is
the existing Plan-style dual-implementation contract, not a second source of
truth. Until a pending mutation reconciles, Nav and subtitle may retain the
last server `partner_summary` rather than show an untested local count.

## 8. Partner experience

Keep the existing Partner page and visual vocabulary. No new tab, no modal
wizard, and no hierarchy selector in the top-level form.

### Creation

`Add something for Partner` keeps creating top-level outcomes. A group gets a
compact `Add step` control only when expanded. Tapping it reveals one inline
title field and focuses it. Notes remain available through the existing edit
flow, not in the fast add-step path.

### Group rendering

- A top-level task with steps is one group card.
- Its header contains the parent completion control, title, and disclosure.
- The disclosure summary says `2 steps left`, never a percentage.
- Open steps appear first. Done steps within an open group may collapse behind
  `2 done`.
- A checked parent with an unfinished step stays in the open section and makes
  the remaining step visible.
- A visually complete group moves to the existing Done section.

### Editing, archive, and offline state

Refactor the current `TaskRow` so parent and child share editing behavior.
There is no new horizontal gesture in v1: Partner already lives near gesture
surfaces, and another swipe would need explicit `data-swipe-own` arbitration.
Delete remains a safe, reversible tap with clear scope copy, for example
`Removed task and 3 steps`, followed by Undo.

A queued top-level task displays pending state and cannot accept a child:
`Sync to add steps`. After reconciliation with the canonical server row, the
group becomes available. Offline archive followed by Undo queues in order;
FIFO replay plus stable mutation ids ensures the same subtree returns.

### Accessibility and mobile gates

- Parent disclosure has `aria-expanded` and `aria-controls`.
- Completion labels distinguish `Mark outcome done` from `Mark step done`.
- DOM order follows visual order.
- Add step, completion, edit, archive, and Undo have 44x44 hit targets.
- New rows expand from their parent within 200ms only when motion is allowed.
- `prefers-reduced-motion` removes translations and celebratory effects.
- At 375x667, the next open task is visible without horizontal scroll.
- The existing shell keeps safe-area ownership; no local magic bar heights or
  nested glass/backdrop layers are added.

## 9. Test matrix

### Migration and hierarchy

- Existing rows migrate as active top-level tasks, and the migration reruns
  safely.
- Valid child creation succeeds; child-of-child, self-parent, missing parent,
  archived parent, and PATCH reparenting fail.
- Active reads hide archived rows; seed defaults do not reappear.
- PATCH/repeated archive target active rows only; an old queued PATCH cannot
  change a hidden archived row.

### Semantics

- An unfinished standalone counts one.
- Parent with two unfinished children counts two, not three.
- Parent done plus one open child counts one.
- All children done plus parent open counts one.
- A fully done group counts zero.
- Removing the final child restores standalone-parent behavior.
- `next_action()` chooses root-group id order, then unfinished child id order,
  then parent outcome after its children.
- Group order keeps a checked parent adjacent to unfinished children rather
  than sorting on the parent's raw `done` flag.
- Command, Nav, Pillar, Plan, and Partner subtitle agree on count and next task.

### Archive, receipt, and offline

- Child archive affects only that child.
- Parent archive affects its active subtree atomically and leaves a previously
  archived child untouched.
- Restore returns only the specified batch with original ids, timestamps,
  done state, and links intact.
- Child-only restore fails until its archived parent is restored, preventing an
  active orphan.
- Replaying create, update, archive, or restore produces one domain effect and
  one memo.
- A lost POST response followed by replay creates one task.
- An offline archive followed by Undo restores the same rows in FIFO order.
- A pending parent refuses step creation until canonical sync.

### UI

- Open groups default to a useful disclosure state; a done parent never hides
  an unfinished child.
- Add step focuses its field; Undo restores the local rows.
- All controls have accessible names and 44px hit areas.
- No horizontal overflow at 320, 375, 390, or 430px; reduced-motion mode has
  no nonessential translation.
- `npm run build`, Partner/API tests, offline queue tests, attention tests, and
  `tests/test_mobile_ui.py` pass.

## 10. Delivery order and non-goals

1. Finish SPEC-v20 receipts, captured dates, and single-flight replay.
2. Add schema, migration, and pure `core.partner` semantics with exhaustive
   tests.
3. Refactor Partner writers into atomic mutation-protected transactions.
4. Add creation, archive, restore, and state summary APIs.
5. Move Pillar, Plan, Nav, and attention consumers onto shared semantics.
6. Build grouped mobile UI and reconcile offline states.

This spec deliberately excludes arbitrary nesting, drag sort, timelines,
agent-created tasks, hard delete, and a new project-management page.
