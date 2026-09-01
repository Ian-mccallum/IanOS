# SPEC v32: the live Order

Status: **shipped** (2026-08-25, branch `feat/v32-live-order`, six commits).
Extends SPEC-v21 (attention compiler). Touches the school subsystem read-only.
Supersedes nothing; it unstuck what v21 built.

## As built

All of Parts A-D landed. `unstick_order.py --apply` ran once against the real
DB: goals 7/8 archived, all 29 July proposals expired. Verified against a
real-data copy at each phase: the compiled Order went from "confirm LLC
status" (band 0, stuck since July) to naming an actual assignment
("BUS 120 - Checkpoint 1 due Aug 27") the same evening. `make sync-finance` +
`make schedule-finance` were also run live (unrelated staleness caught during
the same pass: Chase checking was 8 days stale, now scheduled daily 07:15).
Every part was adversarially verified by an independent agent against the
real DB (on disposable copies only) before merging; two rounds of that verify
step each caught a real gap (Part B: an unenforced 6-item cap and a 10-vs-14
day window mismatch; Part C/D: Canvas sync skipped the shared `ingest_log`
table, and `CommandPage.jsx`'s stale-dim logic had no test coverage) and both
were fixed and reverified before commit. No test anywhere in this spec makes
a real call to the Anthropic API. Final state: 838 backend tests passing (5
pre-existing skips), 65 dashboard tests, clean production build.

## 0. Why

On 2026-08-25 the Order has been "confirm LLC status" for a month. Compiling
the real attention queue against the live DB shows why:

```
0  band=0 goal_deadline  Obtain EIN from IRS        (deadline passed Jul 24)
1  band=0 goal_deadline  Twilio A2P 10DLC approved  (deadline passed Aug 7)
2-30 band=1 proposal_decision  x29, all July, oldest waiting 35 days
31+ band=2 partner / call / follow-up / gym
```

Four faults, each structural:

1. **A breached deadline is immortal.** Band 0 sorts by `due_at` ascending, so
   the *oldest* breach wins forever. The only exits are `DONE_STATES`, archive,
   or delete. There is no vocabulary for "pushed to the side."
2. **Archiving the parent promoted the children.** Goal 6 (File Illinois LLC)
   is archived; goals 7 (EIN) and 8 (A2P) depend on it and stayed active with
   July deadlines. The compiler never reads `depends_on_goal_id`, and
   `all_goals()` filters archived rows, so even the UI's BlockedBadge lost its
   parent and vanished.
3. **Proposal dedupe is byte-exact** (`add_proposal` matches on identical
   action+reasoning). A model rephrases nightly; watchdog filed "confirm LLC
   status" six times (#7, #10, #30, #35, #39, #45). 29 PENDING rows occupy
   band 1 ahead of everything real.
4. **School is invisible.** `school.dashboard_snapshot()` already reports 22
   open items and the next class meeting, `agent_snapshot()` is privacy-safe,
   `read_school` is allowlisted to advisor+chief — and `collect_candidates`
   has no school collector, `build_user_prompt` precomputes no school block,
   and the advisor's only tripwire (`uiuc:fall-move-in`) expired the week the
   semester started.

Meanwhile the BtC *inbound* half is genuinely live (launchd, 15 min, acking
correctly); the *calling* half surfaces at rank 32. And the Day Command
sentence is written once at 21:30 and frozen for 24 hours by design, so even a
fixed compiler leaves a stale sentence over a live button.

## 1. Decisions taken (2026-08-25, Ian)

| Question | Decision |
|---|---|
| Model for "pushed to the side" | **Archive EIN + A2P too.** No `deferred_until` column. Un-archiving is a manual act when the business push restarts. |
| The 29-proposal backlog | **Bulk-dismiss + 7-day auto-expire** (new `EXPIRED` status) + fuzzy dedupe so rephrasings collapse. |
| Canvas freshness | **Live feed.** `CANVAS_ICS_URL` in gitignored `.env` (the Plaid/SnapTrade precedent), pulled every ~6h through the existing validated importer. Amends SPEC's "local file only" stance while keeping its reason intact: the bearer URL never touches the repo, argv, logs, memos, or any agent surface. |
| Day Command staleness | **Haiku rewrite on top-key change** (client-triggered POST, cooldown, max 3/day) with a $0 deterministic UI fallback. |

## 2. Laws

1. **Band 0 is escapable only by an explicit act** — done, archived, or (for
   school) falling out of the 48-hour grace window. Never by silent decay. A
   breach that stops mattering is a decision Ian makes, not one the compiler
   makes for him.
2. **A blocked goal is never the hero.** If `depends_on_goal_id` points at a
   goal that is unmet *or archived*, the child collects at band 3 with reason
   `blocked by <parent name>`. The compiler must resolve parent names through
   a lookup that includes archived rows.
3. **No candidate class may be immortal.** School items enter the compiler
   only inside `[due-48h, due+14d]`. Proposals auto-expire at 7 days. This is
   the anti-LLC rule: nothing new may reproduce fault 1.
4. **Auto-expiry is not rejection.** `EXPIRED` is a distinct status.
   `role_stats()` (the roster's "you took 2 of 4" record) must exclude EXPIRED
   exactly as it excludes PENDING — undecided is not rejected, and a timeout
   is not a verdict on the agent.
5. **`GET /api/state` never triggers a model call.** The Day Command rewrite
   rides a client-fired POST with a server cooldown (the BtC-sync precedent:
   auto-fire on mount, 200-on-throttle, 501 when unconfigured).
6. **The Canvas feed URL is a bearer secret.** Env only, never argv. Failures
   persist closed error codes (`network`, `http_4xx`, `http_5xx`, `parse`),
   never a message that could embed the URL. A sentinel test greps the
   serialized `/api/state`, `ingest_log.notes`, memos, and school_sync_state
   for the URL and must find nothing.
7. **School surfaces stay shame-free.** Candidates carry due dates and titles,
   never counts-against-Ian. An item more than 48h past due leaves the
   compiler entirely (it stays on the School page). No streak, no percentage.
8. **Every window has two edges and a frozen clock in tests** (the
   `term_active` lesson). No collector may compare against the machine clock
   directly; everything receives `now`.

## 3. Part A — unstick (Day 0)

### A1. `scripts/unstick_order.py`
One-off, idempotent, dry-run by default, `--apply` to execute. Repoints
nothing; uses `db.connect()` on the real DB deliberately (this is an operator
script, documented as such at the top).

- Archive goals 7 (EIN) and 8 (A2P). Write one `ian` memo:
  `business chain (LLC→EIN→A2P) paused for the semester — archived, will
  restart deliberately` so agents learn the judgment instead of re-proposing.
- Expire every PENDING proposal older than 7 days (today: all 29) to
  `EXPIRED`, `decided_at = now`.
- Print counts either way.

### A2. Schema: `EXPIRED`
`proposals.status` has a CHECK (`PENDING/APPROVED/REJECTED`). SQLite cannot
alter a CHECK: this is a **table rebuild**, and the rebuild must carry every
ALTERed column (`attachment_type`, `attachment_json`, `urgency`, `due_at`,
`reversibility`, `evidence_json`) or it drops the one it was meant to keep —
the exact trap CLAUDE.md documents from the chat-model CHECK. Migration test
asserts all columns and existing rows survive.

### A3. Nightly auto-expiry
At the top of `run_sequence`, before dispatch: expire PENDING older than 7
days. Silent — no memo, no push (a timeout is not news). Expired rows appear
in the Inbox history stream like decisions do. The chief's
`stale proposals > 24h` wake trigger still works; it just can never
accumulate a month of rot again.

### A4. Fuzzy dedupe in `add_proposal`
Keep the byte-exact fast path, then: same `role` + `kind`, and token-set
Jaccard ≥ 0.6 between lowercased, punctuation-stripped `action` texts against
any PENDING row → return the existing id (`created=False`). Deterministic,
pure-Python, unit-tested with the six real LLC rephrasings as fixtures.
Numbers are tokens too, so "dispute $20" and "dispute $200" stay distinct.

### A5. Compiler guards
- `_goal_candidates` gains the Law-2 blocked-parent demotion. Parent names
  come from a new `db.goal_name_map(conn, include_archived=True)`; `/api/state`
  `_enrich_goals` uses the same map so `depends_on_name` (and the UI
  BlockedBadge) survive an archived parent.
- Proposal candidates cap at the **3 oldest** PENDING. The Inbox holds the
  rest; the Order is not a queue browser.

## 4. Part B — school enters the Order

### B1. Collector: `_school_candidates(items, now)`
Input is `dashboard_snapshot(conn)["upcoming"]` (already open-only, meeting-
shell-free, completion-aware, 14-day windowed) — passed via `preloaded`
key `school_items` from the snapshot `/api/state` computes anyway. Take the
nearest 6.

- key `school:{item_id}` (stable: `import_canvas_items` upserts on
  `UNIQUE(provider, external_item_id)`), kind `school_item`, route `school`,
  interaction navigate, label `BUS 120 · Checkpoint 1`, reason `due Thu 11:59
  PM`, evidence `(school_items, due_at, …)`.
- Bands: `now < due ≤ now+48h` → 1. `due ≤ now < due+48h` (still open) → 0
  with reason `was due <time> — cross it off or let it go`. Beyond +48h past
  due → **not collected** (Law 3/7). Otherwise → 2.
- `_SOURCE_ORDER`: append `"school": 10`, `"school_meeting": 11`.
- Routine order (band 2 only): morning keeps calls first and appends
  `school_item` after `partner_action`; evening puts `school_item` **first** —
  mornings are for dials, evenings are for homework.

### B2. Collector: `_school_meeting_candidate(meetings, now)`
From `preloaded["school_meetings"]` (`snapshot["next_meetings"]`): the single
next meeting **today** whose start is within 2h or currently running. Band 1,
`due_at = start_at`, key `schoolmeet:{item_id}`, label
`SPAN 210 lecture · Hall 149`, reason `starts 12:30`. Route `school`
(where the note-session launch already lives). None outside that window —
the Plan page owns the full day.

### B3. Agents
- `_school_lines(conn)` in `runner.py`: a code-computed block (the
  `_pipeline_lines` pattern) — open count, next due item with date, workload
  by course, exams inside 14 days called out. Appended to the **chief**'s
  prompt whenever school data exists, and to the **advisor**'s when it runs.
  The model never does the date math.
- Advisor gets a new tripwire `school_exam_within(7)` (any open
  `kind='exam'` item due inside 7 days) alongside the existing
  `dated_fact_within("uiuc:", 21)`. Not "any item due in 3 days" — during
  term that fires daily and turns a weekly agent into a nag.
- Rewrite `agents/roles/advisor.md` for in-semester duty: course load vs. the
  ~5 hrs/week Clockwork budget, exam weeks colliding with sales pushes,
  drop/add and registration *windows* as they actually occur — not
  "register for fall classes." Boundaries section unchanged (no coursework
  help; that wall also lives in code in `school_study`).

### B4. Chief digest
`agent_projection` already carries any candidate with the `chief` audience;
school candidates are metadata the chief may read (`read_school` is
allowlisted), so they ship with `chief=True`. The digest needs no change —
item 1 being `BUS 120 Checkpoint 1 due Thu` is the whole point.

## 5. Part C — Canvas goes live

### C1. `ingest/sync_canvas.py`
The only new writer path, and it writes nothing itself: it fetches
`CANVAS_ICS_URL` (env only), size-caps the body (5 MB), parses via the
existing `canvas_ics.py` (same fixed field list — never DESCRIPTION, never
event URLs), and hands records to the same
`import_canvas_items` + `_project_to_calendar` core that
`import_canvas_calendar.py` uses. Refactor that shared core out of the CLI
script so there is exactly one importer; the CLI keeps working for manual
snapshots.

- `record_ingest_attempt/success/failure` on the existing `canvas_ics`
  source; `school_sync_state.last_error` gets a closed code (Law 6).
- Transient failure: no memo (the btcsync precedent — a 6-hourly network job
  fails transiently and a memo per failure is the nag this product bans).

### C2. Schedule
`ops/com.ianos.canvassync.plist`, `StartInterval` 21600 (6h). `make
sync-canvas` runs once; `make schedule-canvas` installs and **refuses when
`CANVAS_ICS_URL` is unset** (exit 2, the backup precedent). `make
import-canvas FILE=…` remains for manual snapshots.

### C3. Staleness
When `CANVAS_ICS_URL` is configured and `school_sync_state.last_success` is
older than 24h, `_stale_candidates` grows a `stale:school` band-3 row
(`Refresh Canvas data`). Unconfigured installs get no candidate — no nag for
a mode you didn't choose.

## 6. Part D — the sentence goes live

### D1. Anchor
`briefs` gains two plain-ALTER columns (no CHECK, no rebuild):
`anchor_key TEXT NOT NULL DEFAULT ''` and
`command_refreshes INTEGER NOT NULL DEFAULT 0`. `write_brief` computes the
anchor **server-side** at compose time — `agent_projection(compile, "chief")[0].key`
— never trusts the model to report what it anchored on.

### D2. `POST /api/order/refresh`
Client-fired from CommandPage when today's brief exists and
`state.attention.next.key != state.brief.anchor_key`. Server re-checks the
inequality, then:

- Throttle: 90 min cooldown and `command_refreshes < 3` per brief row →
  otherwise `{ok, throttled}` with 200 (never an error toast).
- 501 when no auth token is configured (the plan-sync precedent).
- Runs one **tool-free** Haiku call, chief persona + `CHAT_LAW_LAYER`:
  inputs are the privacy-filtered chief attention digest, today's plan block
  times, and the old sentence. Output: one imperative sentence ≤ 120 chars,
  `strip_em_dashes` applied, execution-claim scan applied (an "I did X"
  sentence fails the call, the chat precedent).
- On success: update `day_command`, `anchor_key`, increment
  `command_refreshes`. `body` is untouched — the brief prose stays the
  nightly artifact.

### D3. $0 fallback
When the keys diverge and refresh is unavailable (501/502/throttled with a
still-stale key), the UI dims `ord-text` to secondary weight and the live
`ord-go` line takes hero treatment. Deterministic, no model, and it is also
the permanent behavior for cached/service-worker state (`attentionFresh`
already exists).

## 7. Tests

Frozen clocks everywhere; every window pinned at both edges (Law 8).

- **A:** rebuild migration carries all six proposal columns + existing rows;
  EXPIRED excluded from `role_stats` denominators; auto-expiry at exactly
  7d±1min; fuzzy dedupe collapses the six real LLC rephrasings, does not
  collapse different amounts; blocked-child demotes to band 3 with the
  archived parent's name; proposals cap at 3 in the compiler;
  `unstick_order.py --dry-run` writes nothing (`conn.total_changes == 0`).
- **B:** school item inside 48h → band 1; 47h59m past due → band 0; 48h01m
  past due → absent; completion (`school_item_completions`) removes the
  candidate; re-import (id-stable upsert) keeps the key; meeting candidate
  only within its 2h window; morning/evening routine order for
  `school_item`; `_school_lines` numbers match a fixture snapshot;
  `school_exam_within` fires on day 7, not day 8.
- **C:** Law-6 sentinel (URL grep across state JSON, ingest_log, memos,
  school_sync_state); failure writes a closed code and no memo; the shared
  importer core produces identical rows via CLI file and via sync;
  `schedule-canvas` refuses unconfigured; stale candidate appears at 24h
  configured, never unconfigured.
- **D:** `GET /api/state` performs zero model calls (Law 5); refresh is a
  no-op 200 when keys match; throttle math (90 min, 3/brief); anchor_key is
  server-computed even if the model asks otherwise; em-dash strip and
  120-char cap on the rewritten sentence; execution claim fails the refresh
  and leaves the old sentence standing; UI fallback dims on 501.
- **Integration:** with today's real-shaped fixture (archived chain, zero
  pending proposals, BUS 120 Checkpoint 1 due Thu), `attention.next` is the
  checkpoint — the acceptance test for the whole spec.

## 8. Delivery order

1. A2 rebuild + A3/A4 guards + tests (data layer first; invoke the `data`
   skill).
2. A5 compiler guards + A1 script; run `unstick_order.py --apply`.
3. B1/B2 collectors + preload wiring + B3 prompt block/tripwire/role file.
4. C1–C3 Canvas sync + schedule.
5. D1–D3 sentence liveness.

Each phase lands green on `make test` + `cd dashboard && npm test`
independently; 1–2 alone already changes tomorrow's Order.

## 9. Non-goals

- No `deferred_until` column, no snooze UI (decided against; archive is the
  vocabulary).
- No silent decay of breached deadlines (Law 1).
- No school streaks, percentages, or completion analytics; no grade
  ingestion; no coursework help (walls stay in `school_study`).
- No new agent, no new tab (School already has its surface).
- No push for school items or Day Command changes — the Order updates
  quietly; ntfy remains promises-only (SPEC-v18).
- The compiler stays read-only and framework-free; no attention table.
