# SPEC v21: the attention compiler

Status: **proposed**. Depends on SPEC-v20 for operational truth. Extends the
Command surface without creating a new task list.

## 0. Purpose

ianOS already knows about callbacks, promises, goals, plan blocks, proposals,
gym, Partner, and stale data. Each surface currently chooses its own priority.
That is how a routine counter can occupy Command while a real commitment
expires elsewhere.

`core/attention.py` answers one narrow question:

> Given ianOS truth at this local time, what deserves attention next, and why?

It is a derived view. It stores nothing, owns no source data, and never asks a
model to decide what is urgent. A resolved source record disappears from the
result automatically. The compiler becomes the common ordering for Command,
the chief's constrained context, and only the alert flows that already own a
durable fire-once receipt.

## 1. Laws

1. **One compiler, no shadow backlog.** Existing source tables remain the
   truth. Do not add an `attention` table, a generic task table, event bus, or
   a second ranking implementation in React.
2. **Detection and ranking are deterministic.** Every time-dependent function
   receives `now`. No model call or hidden wall clock decides the order.
3. **Hard commitments beat helpful routines.** A breached promise, callback,
   or deadline outranks gym, a normal call run, Partner, and a generic follow-up.
4. **Every item is explainable and actionable.** It has a stable key, a
   visible factual reason, a destination, and a constrained interaction type.
5. **Permission filtering preserves order.** An agent sees only the compiler
   candidates whose underlying sources it could already read. Filtering never
   gives the agent a new privacy capability or reranks the survivors.
6. **Attention does not become notification spam.** The compiler never owns
   push delivery or alert state. Source-specific writers retain that job.
7. **The phone gets one job.** Command shows one primary action above the
   375x667 fold and at most three secondary signals. No percentage, shame
   copy, or red personal-routine treatment.

## 2. Existing paths to compose

| Need | Existing source to extend |
|---|---|
| deadlines and current goal state | `metrics.resolve_goal_actuals()` |
| next call / callbacks | `leads.call_queue()` and pipeline data |
| proposals | `db.pending_proposals()` |
| plan | `db.plan_blocks_for_date()` and `plan.is_sailed()` |
| gym | `db.gym_streak_state()` |
| Partner | `core.partner.actionable_tasks()` from SPEC-v22, otherwise current flat read temporarily |
| freshness | `metrics.stale_data_domains()` and SPEC-v20 health projection |
| promise timing | `core.promises` and active inbound read path |
| current aggregate | `GET /api/state` |
| current Command renderer | `dashboard/src/components/ActionStack.jsx` |
| chief context | `agents/runner.py:build_user_prompt()` |

The compiler may add a small pure module, but it must compose these paths.
Before SPEC-v22 lands, it uses the existing first unfinished Partner task as a
temporary adapter. Once `core.partner.py` exists, that adapter is deleted.

## 3. Candidate contract

Use immutable dataclasses or equivalent typed dictionaries in
`core/attention.py`:

```python
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

@dataclass(frozen=True)
class AttentionResult:
    generated_at: datetime
    next: Candidate | None
    ranked: tuple[Candidate, ...]
```

Allowed interaction types are an enum, never an arbitrary HTTP instruction:

- `navigate`
- `proposal_decision`
- `gym_confirm`
- `activity_increment` (an allowlisted activity field only)

Primary functions:

```python
def collect_candidates(conn, now, *, preloaded=None) -> list[Candidate]
def rank_candidates(candidates, now) -> list[Candidate]
def compile_attention(conn, now, *, preloaded=None) -> AttentionResult
def public_projection(result, limit=4) -> dict
def agent_projection(result, role) -> list[dict]
def push_projection(candidate) -> tuple[str, str] | None
```

`rank_candidates` is pure over candidates plus an explicit time. Collection is
the only database-facing layer. Compilation writes nothing.

## 4. Candidate collection

Phase 1 collects only these existing sources:

| Candidate | Eligibility | Route / interaction |
|---|---|---|
| Expiring inbound promise | BTC, still new, `promised_by` exists | `btc` / navigate |
| Callback or call run | due callback regardless of quota, or callable lead while quota remains | `btc` / navigate |
| Current or next plan block | planned item today, current or upcoming | `plan` / navigate |
| Goal deadline | incomplete deadline inside the configured window | pillar route / navigate |
| Proposal decision | pending proposal | `inbox` / proposal_decision |
| Gym | weekday, not confirmed | `body` / gym_confirm |
| Partner action | first actionable leaf | `partner` / navigate |
| Stale source | existing source exceeds its threshold | `more` / navigate |
| Follow-up capture | current activity rules only, low-priority fallback | Command / activity_increment |

The promise collector must use an active-promise read path that is independent
of `alerted_at`. A prior push is not proof that the request was handled.

Due callbacks use one explicit `leads.due_callbacks()` read path that ignores
the daily call quota. `leads.call_queue()` remains the routine-call source and
may be quota-limited. A promised callback must not disappear because today's
normal call run is already full.

Goal routes are mapped by existing pillar: `business -> btc`, `health -> body`,
`finance -> money`, `school -> school`, and `personal -> life`. Do not route
generic deadlines to `goals`, which currently redirects to Beat the Clock.

Labels name a real object when the source has one: `Call Riverbend Locksmith`,
not `Work on business`. Reasons are short facts such as `callback promised for
Aug 14`. Public attention does not expose consent, phone numbers, message
bodies, journal data, or a raw finance error. A public promise item may say
`Confirm a booking before 2:00 PM` rather than expose unnecessary contact data.

## 5. Ranking law

Rank using this lexicographic tuple, lower first:

```python
(
    candidate.band,
    candidate.due_at or datetime.max,
    routine_session_order(candidate, now),
    candidate.source_order,
    candidate.stable_order,
    candidate.key,
)
```

All `Candidate.due_at` values are timezone-naive local datetimes, matching the
database's established local-time convention. Each collector converts at its
boundary; `datetime.max` is therefore the same representation. Mixing aware
UTC with naïve local values is a ranking error and gets a direct unit test.

| Band | Meaning | Examples |
|---|---|---|
| 0 | breached commitment | expired promise, overdue callback, past incomplete deadline |
| 1 | due now or soon | promise inside four hours, callback due today, current plan block, deadline inside seven days, proposal older than one day |
| 2 | routine next action | gym, normal call run, new proposal, Partner leaf, follow-up |
| 3 | maintenance | stale data source |

Routine order preserves the existing product behavior only within band 2:

| Session | Order |
|---|---|
| morning | gym, call, follow-up, proposal, Partner |
| evening | proposal, Partner, call, follow-up, gym |

Earlier due time wins inside a band. Then older commitments/proposals, source
order, and stable source key settle ties. Identical data and `now` must produce
byte-for-byte equivalent public output. Duplicate candidate keys fail loudly
in tests.

## 6. API and state flow

`GET /api/state` compiles once after it has already calculated goals, gym,
Partner tasks, and the lead queue. Pass these in a `preloaded` object rather than
asking the database the same questions again. Refactor `_leads_summary()` so
the state route supplies one precomputed queue.

Add only the compact projection:

```json
"attention": {
  "next": {
    "key": "lead:418",
    "kind": "call_run",
    "label": "Call Riverbend Locksmith",
    "reason": "callback promised for Aug 14",
    "route": "btc",
    "interaction": {"type": "navigate", "ref_id": 418},
    "due_at": "2026-08-14T08:00:00",
    "urgency": "due"
  },
  "items": [{}, {}, {}]
}
```

`next` is the first ranked public candidate. `items` contains at most the next
three **secondary** candidates and never repeats `next`. State returns no full
internal queue and no raw evidence. Four records are the hard maximum. The
compiler itself remains framework-free and knows nothing about FastAPI or
React.

## 7. Command experience

Refactor the whole Command surface, not only `ActionStack.jsx`:

- The Order card's `ord-go` primary CTA takes `state.attention.next`; remove
  local `resolveExecute()` priority.
- Remove the `/api/day` `nextBlock` fetch and its Plan-first priority rule.
- Replace `allSignals` and `SIGNAL_RANK` with the compiler's secondary
  `attention.items`.
- `ActionStack.jsx` becomes a presentational renderer for the secondary items,
  not a ranker.

The evening Journal shutdown nudge remains an intentional exception: it is a
once-per-local-day habit close after 21:00, displayed below attention as a
secondary optional nudge. It never replaces `attention.next`, enters the
compiler queue, or gains a push.

The Order card and Action Stack may render the interaction enum through
existing handlers (`onDecide`, `onGymConfirm`, navigation, allowlisted activity
bump, refresh) and retain busy/pending state. They may not call
`sessionKind()` to rank, find the first unfinished Partner task, or independently
choose proposal/gym/call priority.

On mobile, the Day Command sentence and `attention.next` must fit above the
fold at 375x667. The remaining signals are disclosure or short rows, not a
second dashboard. A one-release fallback to existing props is allowed while
the API rollout reaches installed PWAs; tests then make attention canonical.

When `fetchState()` reports a service-worker-cached snapshot, label attention
as last-synced truth. Cached navigation is harmless and receipt-backed gym or
activity capture may queue. Nonqueueable actions, especially proposal
decisions, are disabled or omitted until a fresh API response arrives; an old
compiled order must not make a stale decision look live.

## 8. Chief and push boundaries

Add a small compiler digest to the chief's normal prompt:

```text
=== DETERMINISTIC ATTENTION ORDER ===
1. [due] Call Riverbend Locksmith: callback promised for Aug 14
2. [decision] Decide proposal #31: waiting 2 days
3. [routine] Confirm gym: weekday not confirmed
```

Rules:

- Filter in compiler order and only when the source is already readable under
  the chief's code-level permissions.
- Inbound rows, Partner task text, journal content, consent, and phone/message
  fields are excluded in v1. The chief does not gain a new read path through a
  summary.
- The chief prompt asks it to anchor a normal Day Command on candidate one.
  Tradeoff hints can shape timing or wording but do not silently replace the
  deterministic ranked action.

`core.attention` never sends. The existing BTC loader remains owner of its
promise alert and `db.mark_alerted()` fire-once state. It may use a separately
allowlisted push projection for copy and ordering, while retaining quiet hours
in `core.promises`. SPEC-v20's finance health source remains owner of finance
alerts. No generic gym, Partner, Plan, proposal, or stale-data push is added.

## 9. Tests and performance gates

Unit tests:

- Fixed rows and fixed `now` yield stable order; the machine clock cannot
  affect it.
- Each band outranks the next; earlier due time wins within a band.
- Morning/evening routine order matches the existing product.
- Completed, archived, handled, future-ineligible, or resolved rows disappear.
- Compilation leaves `conn.total_changes` unchanged.
- Public, agent, and push projections expose only their allowlisted fields.

Integration tests:

- `/api/state.attention.next` is the top public candidate.
- Command renders it without local reranking.
- Chief projection maintains relative order after privacy filtering.
- A promise may appear on Command but never in the chief digest.
- Existing promise push still fires once and respects quiet hours.
- Due callbacks remain visible after the daily routine quota is full.
- Goal deadlines route to the correct existing pillar.
- Cached state labels its age and cannot execute a nonqueueable decision.
- Consent, message, phone, email, journal body, and media metadata never enter
  an agent or push projection.
- State returns at most four attention records.
- Compilation remains fast against the 1,958-lead fixture.

## 10. Delivery order and non-goals

1. Candidate contract, ranking tests, and privacy-projection tests.
2. Pure ranking and collectors using existing read paths.
3. One state compilation and compact API projection.
4. ActionStack renderer conversion.
5. Filtered chief digest and wall tests.
6. Existing promise-push integration only.

No schema migration is needed. This spec does not build a notification center,
generic urgency prose, a task database, or a model-driven prioritizer.
