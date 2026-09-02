# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What ianOS is

A local-first, single-user "personal life operating system" for **Ian McCallum** : 
a founder (Clockwork) and incoming finance + data-science student at
UIUC Gies. The whole product is engineered against friction: one **Day Command** sentence instead of a backlog, a gym streak that
*forgives misses* instead of resetting to zero, deterministic dispatch so nothing
nags without cause, and `Cmd+K` to jump anywhere. When making product/UX
decisions, optimize for *low activation energy and no shame*, not feature count.

Three cooperating parts, one SQLite file:

1. **Agent runner** (`agents/`). 10 pop-culture-named AI agents run nightly on a
   shared memo "blackboard" and compose a daily brief (SPEC-v37 retired five:
   advisor merged into watchdog, archivist became a nightly function, family/
   infra/publicist are inactive). Ian is CEO; agents READ, MEMO, and PROPOSE
   for anything hard to reverse (**nothing there executes without a human
   APPROVE**), plus a closed list of *reversible* Ring 1 acts (SPEC-v37 §4)
   that apply immediately, receipted and undoable.
2. **Dashboard** (`dashboard/` + `api/`): a Vite/React mission control over a
   FastAPI localhost API. Six life "pillars" plus a Command home.
3. **Ingest** (`ingest/`). CSV / SimpleFIN / SnapTrade / connector loaders that
   are the *only* writers for their data sources.

## Commands

```bash
make setup          # venv + pip deps + dashboard npm install + seed demo data
make dev            # API :8787 + dashboard :5173 together (scripts/dev.sh); open http://localhost:5173
make api            # API only (uvicorn --reload)
make ui             # dashboard only (vite)
make run            # run the nightly agent sequence NOW (needs auth, see below)
make run-weekly     # force the chief's Sunday deep brief (uses Sonnet)
make plan           # DRY RUN: print who the dispatcher would wake tonight, $0.00, no model calls
make seed           # reseed demo data
make import-leads   # load leads/enriched.csv into The Line (safe to re-run)
make import-canvas FILE=/abs/path.ics   # import a downloaded Canvas .ics snapshot
                    # local file only: never a feed URL, token, or password.
                    # add --dry-run via the script for a counts-only preview
make export-leads   # write leads back to CSV with real call history
make prep           # read the next 5 calls + scripts before dialing
make backtest       # did Fit/Pain/Reach predict who answers? (reports only)
make test           # pytest tests/ -q
make icons          # regenerate PWA icons + logo-lockup from ianOS.jpg / logo.png
make phone          # production build + launchd serve for the iPhone PWA
make phone-status   # is the phone server up?
make phone-off      # stop launchd serve / leave tailnet
make sync-btc       # pull demo bookings + contact messages from beatyourclock.com
make sync-personal  # pull messages from ianmccallum.com (never creates a lead)
make sync-inbound   # pull every configured inbound seam once
make schedule-inbound # run every configured inbound seam every 15 min (SPEC-v20)
make backup         # encrypted restic snapshot to the repo in .env (SPEC-v16)
make backup-status  # last success + recent snapshots
make backup-verify  # deep proof: re-read all data + test-restore + integrity_check
make restore        # restore latest (or SNAPSHOT=<id>) into a NEW folder, never in place
make schedule-backup# nightly 21:45 backup via launchd (refuses if unconfigured)
make clean          # delete data/ianos.db (and -wal/-shm)
make export-public  # rebuild + commit the scrubbed public mirror in ../ianOS-public (SPEC-v39)
```

Run a single test:

```bash
.venv/bin/python -m pytest tests/test_dispatcher.py -q
.venv/bin/python -m pytest tests/test_dispatcher.py::test_name -q
```

There is **no linter/formatter config**. `make test` is Python-only (pytest), and
the dashboard has a Node test suite: run `cd dashboard && npm test`, then
`npm run build`. Mobile/static UI laws also live in `tests/test_mobile_ui.py`.

Agent runs need auth (one-time). Put ONE of these in `ianOS/.env` (gitignored):
`CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...` (subscription token via
`./bin/claude setup-token`) or `ANTHROPIC_API_KEY=sk-ant-...`. Without it,
`make run` logs an auth-failure memo from "system" and the seeded brief stays up.

## Architecture: the load-bearing ideas

### Roles are data, the runner is code (`agents/`, `core/roles.py`)

There is **ONE runner** (`agents/runner.py`) and **N role files**
(`agents/roles/<id>.md`). Each role file is markdown with `---` frontmatter
(`role`, `codename`, `persona`, `tier`, `day`, `domains`, `active`). The filename
stem / `role:` id is a **foreign key** in the memos/proposals/facts history and
**must never change**; codename + persona are display-only. `core/roles.py`
parses frontmatter and owns the canonical nightly `SEQUENCE` (producers →
synthesizers → `chief` last).

**Adding an agent = 3 edits** (README "Adding a new agent"): write
`agents/roles/<name>.md`, add `ALLOWLISTS["<name>"]` in `runner.py`, add the id to
`SEQUENCE` in `core/roles.py` (+ a `TRIPWIRES` entry if `tier: tripwire`).

### Guardrails live in code, not prompts (`agents/runner.py`)

This is the security model, do not weaken it by moving rules into prose:

- **Zero built-in tools.** Agents get `tools=[]`; the only tools that exist are the
  in-process MCP `ianos` server (`SERVER`). Each role has a hard-coded tool
  **allowlist** (`ALLOWLISTS`); everything else is in `disallowed_tools`.
- **Only `cfo` creates `money` proposals** (`NO_MONEY_PROPOSALS`, blocked inside
  `create_proposal`). **`wealth` never proposes trades** (`TRADE_VERBS` regex).
  **Only `chief` writes briefs / focus.**
- **Every number must trace to a table row.** Read-tools return raw rows *plus*
  code-computed aggregates; date math for `watchdog`/`physician`/`steward`/`chief`
  is precomputed in Python in `build_user_prompt`, not left to the model.
- **A role crash becomes a `system` memo and the sequence continues**, one agent
  failing never aborts the night.
- **Idempotency everywhere:** briefs are `UNIQUE(date, kind)` (re-running a day
  replaces, never duplicates); duplicate PENDING proposals are collapsed.
- **A proposal pile is bounded, not infinite (SPEC-v32).** Exact-match dedupe
  could not see a rephrasing, so 29 July proposals reached attention band 1 and
  pinned the Order to the LLC chain for a month. Two guards now: `add_proposal`
  also collapses near-duplicates (`proposal_similarity`, Jaccard over the
  opening clause, vetoed by a differing leading verb or number, skipped
  entirely when a draft attachment or evidence set carries content beyond
  `action`), and the nightly sweeps PENDING older than
  `PROPOSAL_EXPIRY_DAYS` to **`EXPIRED`** before it decides the slate, so an
  abandoned proposal cannot wake the chief. Tune dedupe toward FALSE
  NEGATIVES: a missed duplicate expires, a wrong merge silently discards a
  proposal Ian never sees. **`EXPIRED` is a timeout, never a verdict** :
  `role_stats` buckets it away from the ratio the roster divides by, and
  `recent_decisions` excludes it because `App.jsx` renders every non-APPROVED
  row there as "Rejected". `make plan` stays inert and models the sweep
  instead of running it.
- **Proposal attachments are inert.** `create_proposal` accepts only closed,
  versioned plain-text draft shapes. Money drafts are blocked, evidence references
  are server-resolved against records the role may read, and approval never sends.

### Tiered agency: three rings (SPEC-v37 §4)

> **Law A4 — The ring is a property of the act, not of the agent.** Reversibility
> is decided in code, per act type, never by a model describing its own intent.

- **Ring 0 — Read.** Unchanged: domain-scoped, wall-enforced `read_*` tools.
- **Ring 1 — Reversible acts** (`core/acts.py`). A closed list of 13 `act_*`
  tools (`plan_block.create/move/delete`, `note.create`, `partner_task.create/
  complete`, `gym.confirm`, `activity.log`, `goal.rebaseline`, `goal.archive`,
  `transaction.recategorize`, `fact.flag_unverified`, `attention.snooze`) apply
  **immediately, no approval**, each one **receipted** into `agent_acts`
  (`_apply()`'s shared transaction: the act's write and its receipt commit
  together or not at all) and **undoable** (`undo_act`, one inverse handler per
  act type). `RING1_GRANTS` in `core/acts.py` decides which role gets which
  act; `fact.flag_unverified` is universal. **Never Ring 1, for any role, in
  any plane:** money movement, sending anything, lead stage/touch, journal,
  health values, school completions, proposal decisions, `verified=1`,
  `focus`, `brief`. The Command page's Receipts strip shows the last 24h with
  a one-tap Undo per row.
- **Ring 2 — Propose.** `create_proposal` as before, now with two more kinds
  the roster was missing a verb for: `goal_change` (target/deadline/retirement
  of a goal not yet Ring-1-archivable) and `quota_rebaseline` (a whole quota
  set moved for a season).

**Every producer sees the open-proposal ledger it's told not to duplicate.**
`core/situation.py::current_situation(conn, now)` is prepended to every
nightly prompt (daily and weekly, every role): season/capacity, hero goal,
nearest real deadlines, live quotas, expired-undecided goals, the full open
proposal list, and Ring 1 acts from the last 24h — all precomputed in Python,
never left to the model. This is what closed the dead APPROVE loop the
SPEC-v37 audit found (every producer was told not to repeat a PENDING
proposal but was never shown one).

**Seasons** (SPEC-v37 §6.2, mechanism only, not yet applied to any role file):
`goals.season` (default `'always'`) and a role file's optional `seasons:`
frontmatter gate `should_run()` with a `"out of season (<season>)"` skip
reason. `core/school.py::current_season()`/`term_bounds()` compute TERM vs
BREAK from real `school_items` due dates (guarded against the table not
existing yet), never a hardcoded date.

### The consult surface: two planes (SPEC-v37 §2, §7 — supersedes SPEC-v23/v25/v26)

> **Law A1 — Capability follows attendance.** An agent running while nobody
> is watching gets the minimum (Plane A). An agent running because Ian typed
> a message, on a screen he is looking at, gets the maximum the machine can
> safely offer (Plane B). Two different programs, and the code says so.

The old Ask sheet, inspect mode, and hand-rolled rooms (SPEC-v23) are
**deleted** (`run_interactive_role`, `/api/agent-invocations`,
`/api/agent-commands`, `/api/agent-rooms`, `AskAgentSheet.jsx` are gone).
Roster "Ask X" and record-level Inspect now open a chat thread directly,
seeded with a client-built question Ian reviews before sending — inspect
was always context, not a mode.

- **Plane A (nightly) is unchanged.** `tools=[]`, the in-process `ianos` MCP
  server is the only tool source, per-role `ALLOWLISTS`, no filesystem, no
  Bash, no connectors, no web.
- **Plane B (consult) is real Claude Code**, attended, bounded to one turn:
  `Read`, `Grep`, `Glob`, `Bash` (sandboxed), `WebSearch`, `Skill` alongside
  the `ianos` MCP server, gated by three new capability chips (Files on by
  default, Workspace, Shell — Mail/Calendar/Drive from the spec's own table
  are deliberately unbuilt: no precedent in this codebase for wiring a live
  connector MCP server into a non-interactively-spawned CLI subprocess).
  `agents/consult_gate.py`'s `make_consult_gate()`/`make_consult_pretooluse_hook()`
  are the ONE decision function wired as both `can_use_tool` and a
  `PreToolUse` hook (**Law A2 — one gate, in code**: a capability wall with
  one implementation is a capability wall with one bug). It denies connector
  write tools by bare name (`CONNECTOR_WRITE_TOOLS`), secret paths (`.env`,
  `data/journal/`, `data/school/`, `data/ianos.db*` — **Law A3: the database
  is never a file**, every read still goes through an `ianos` MCP tool), and
  any write outside `data/consult/` (gitignored, restic-backed).
- **Chat replies are prose, not JSON.** A turn may end with one optional
  `<verdict>{"verdict":..,"next_action":..}</verdict>` block the UI renders as
  a card; missing/malformed is stripped, never fatal. An **execution claim
  still fails the turn**.
- **The system prompt is three layers**, composed by `chat_system_prompt()`:
  PERSONA (per role) → `CHAT_VOICE_LAYER` (universal register matching, the
  not-a-yes-man duty) → `CHAT_LAW_LAYER` (universal walls, appended last,
  outranks the persona). Fury's character lives in `runner.py`; every other
  agent's lives in a `## Chat` section in its role file, stripped by
  `nightly_role_prompt()` so a memo writer never sees it.
- **Live state earns "you see the whole board."** `_live_state_lines()`
  (SPEC-v37 §7.5) reuses `core/situation.py` for hero goal/deadlines/quotas/
  proposals/acts/season, plus the Order (`core/attention.py`), gym, and
  `db.net_worth()`/burn-vs-cap — one implementation, not a second one that
  can drift. Still read-only: **never call `gym_streak_state()`** there.
- **Native session continuity** (SPEC-v37 §7.4): `chat_threads.sdk_session_id`
  + `ClaudeAgentOptions(resume=session_id, fork_session=False)` on every turn
  after the first. Falls back to a quoted-history rebuild (12 turns, 4,000
  chars, **both sides** — the old cache only ever quoted the agent's own
  replies) only when a resumed attempt raises before completing, never on an
  ordinary turn failure.
- **Fury convenes real subagents** (SPEC-v37 §3.6, replaces the hand-rolled
  sequential-Haiku rooms path): `ClaudeAgentOptions.agents`, up to 3, built
  by `_convened_agent_definitions()` — health roles are excluded **before**
  the child agent is ever built (never filtered from a text block after the
  fact), each child's tools are `interactive_allow(role)` intersected with
  the parent thread's own already-granted set. A `SubagentStop` hook plus
  `get_subagent_messages()` build the `specialists[]` attribution list.
- **One agent per thread.** `chat_threads.role`; creating a thread closes
  only the previous thread for *that* role. `chat_allow(chips, role)` is
  role-aware: a chip never widens an agent past its own interactive
  allowlist. Unknown/inactive role is 422.
- **Four plan models** (`haiku, sonnet, opus, fable`) and four effort levels
  (`low, medium, high, max`, default `high`), both closed enums per thread.
  `xhigh` is deliberately absent. Widening the model CHECK needs a table
  rebuild; a rebuild must carry every ALTERed column or it drops the one it
  was meant to preserve (`_migrate_chat_threads_v26` carries `sdk_session_id`
  forward for exactly this reason).
- **The composer is one pill** (SPEC-v27): `+` opens Context (sources), the
  model chip opens Reasoning (model, effort, agent, specialists, and the new
  Capability row). Sources are filtered by role via `chat_sources_for()`.
- **Web search is the one source that leaves the Mac.** A built-in, not an
  MCP tool, riding `chat_builtins()`. Off by default per thread, `WebFetch`
  never granted.
- **No cooldowns.** Refusal is 409 while a turn on that thread is
  QUEUED/RUNNING, plus the shared `AgentExecutionGate`. Chat prunes at 30 days.
- **Chat writes no memos, facts, briefs, or focus.** The six-domain
  instant-write exception (`chat_write_allow`, SPEC-v29) still stands, plus
  one new member: `chat_write_learning_profile` does not exist yet (that's
  SPEC-v38, not shipped). File in Inbox records an inert `task` proposal as
  `role='ian'`. Nothing from chat enters `/api/state`.
- **Anti-slop is enforced in code**: `strip_em_dashes()` rewrites em/en
  dashes in every reply and now in every brief (`write_brief`, SPEC-v37 §8.3).
- **UI: the portal dock** (`dashboard/src/components/AgentChat.jsx`). One
  mount in `App.jsx`, still (**Law A10 — position is a portal, lifecycle is a
  mount**: the thread must survive a tab switch). `CommandPage.jsx` renders
  `<div id="consult-dock-slot">`; `AgentChat` `createPortal`s into it when
  Command is active, or renders its own fixed re-entry pill/panel otherwise.
  Three states, held in `sessionStorage` only (never a route): **dock**
  (inline under the Order), **expanded** (desktop: grows inline via the
  portal target, page scrolls behind, no backdrop; mobile: a Sheet at
  85dvh), **full screen** (a real modal takeover both platforms). Roster
  "Ask X" and record Inspect both go through one `consultRequest` hand-off
  in `App.jsx` (`{role, seedText, view}`), never a second seeding path.
- **The persona is tested.** `tests/test_chat_persona.py` asserts layer
  order, roster coverage, and the nightly/daytime split always; live
  behavioural probes run under `IANOS_PERSONA_EVAL=1`.

### The dispatcher: determinism for detection, LLM only for narration

`should_run()` in `runner.py` decides run/skip for each role each night in **pure
Python, it never calls a model**, so a skipped agent costs **$0.00**. Tiers:
`daily` always runs; `weekly` runs on its `day:` OR when a **tripwire** fires;
`tripwire` runs only on its condition; a `seasons:`-bearing role additionally
needs `core/school.py::current_season()` to be one of them (SPEC-v37 §6.2,
mechanism built, not yet applied to any role file). Tripwires (`TRIPWIRES`)
are things like "a `partner:` dated fact within 14 days", "no workout logged in
3 days", "a document pending review", "a goal 14+ days past deadline with no
verdict" (SPEC-v37 §6.3). `make plan` prints tonight's slate for free. The
`chief` only composes a brief if the night actually produced something, and
now also receives a code-computed dispatcher summary ("5 of 10 woke; 2 off; 3
out of season") stored on `briefs.dispatch_summary`, never mixed into the
brief's own prose `body` (SPEC-v37 §8.6).

### Memory: the ledger and the index (SPEC-v37 §5)

> **Law A6 — Retrieval informs, the ledger asserts.** A search result can
> surface a memory; it can never by itself become a fact a model repeats as
> true.

The **archivist role is retired** (`active: false`); Samwell Tarly's weekly
distillation became a pure function, `core/ledger.py::distill(conn, today)`,
called once at the end of `run_sequence`. Five deterministic extractors
promote memo/calendar/school/proposal/goal chatter into `verified=1` facts
(never through the model-facing evidence gate — direct `db.upsert_fact` calls
with real provenance already established elsewhere): calendar birthdays/
anniversaries, school exams, account identities (never balances), APPROVED/
REJECTED proposal decisions (never EXPIRED — a timeout is not a verdict),
completed deadline goals. `distill()` also finally calls the pre-existing
`db.compact_memos()`, wired into a run for the first time.

**The ledger is hardened.** `upsert_fact`'s `verified` default flipped `1→0`:
a fact is unconfirmed until Ian says otherwise or a ledger extractor promotes
it, never merely because it was written. `write_fact` now requires a
resolvable `evidence` reference (goal/fact/document/memo, the same
server-side resolution `create_proposal` already did) — an agent can no
longer assert a fact with nothing behind it. `write_memo` at priority ≥2
requires at least one read this run (`RUN["reads_this_run"]`): a memo urgent
enough to matter must be grounded in something the agent actually looked at.

**The index (Stage 1, FTS5-only; vectors are a separate, unbuilt follow-on).**
`core/memory_index.py::sync_memory_index(conn)` does a full DELETE+re-INSERT
of the `memory_fts` virtual table from an explicit, exhaustive
`SOURCE_TABLES` allowlist (`memos, briefs, notes, facts,
school_note_sessions, proposals`) — a table not named there is invisible to
the indexer forever, `journal_entries`/`health_daily`/`school_note_assets`/
`leads` included, satisfied by construction. Runs once per nightly sequence,
so a search reflects last night's state. `search_memory` (a new tool, granted
to every active role) is BM25+recency-blended, FTS5-escaped
(`_fts5_escape_query`), domain-scoped **only** when the source table is
`facts` (mirroring `read_facts` exactly), and every result carries
`"grounding": "recall_only"` — Law A6, enforced in the payload shape itself.

### Facts store = domain-scoped long-term memory (RAG)

`facts` table: durable, namespaced (`partner:*`, `uiuc:*`, `family:*`, `content:*`,
`training:*`, `market:*`). `read_facts` is **code-scoped to the agent's own
domains**, an agent literally cannot request another domain's memory. Topic
namespaces route to a home domain via `NAMESPACE_DOMAINS` /
`domain_for_topic()` in `core/db.py`. Specialists write only into their own
domain. Facts from connectors and seed placeholders are born **`verified=0`**,
agents don't trust them until Ian confirms on the Memory page.

### Models & cost

`claude-haiku-4-5` for every nightly role run; `claude-sonnet-5` for the chief's
weekly deep brief **and** for a chat thread's own model setting (default
Sonnet, four plan models available per thread). Fury's convened subagents
(SPEC-v37 §3.6) are always Haiku at low effort, regardless of the parent
thread's own model. `HAIKU`/`SONNET` constants in `runner.py`. Target < $5/mo,
the dispatcher (free skips) is what makes that hold, plus real SDK-enforced
ceilings now: `max_budget_usd` per nightly role, per turn in Plane B. A role
file may override with a `model:` frontmatter key. Chat cannot invent a third
model string.

### Data layer (`core/`)

**Invoke the `data` skill (`.claude/skills/data/`) before any schema, ingest,
loader, backup, or privacy-wall work**: it is the data-law equivalent of `osui`,
carrying the write-boundary table, the idempotency and single-read-path rules,
and the traps that have shipped here.

- `core/db.py`, the whole SQLite schema (`SCHEMA` string, tables created on
  `connect()`), migrations, and all query helpers. No ORM. Key tables:
  `transactions, holdings, activity, health_daily, calendar_events,
  focus_allocations, memos, proposals, briefs, goals, facts, content_log,
  partner_tasks, streak_events, documents, ingest_log, plan_blocks, plan_tombstones,
  journal_entries, notes, leads, lead_touches, call_runs, agent_invocations,
  chat_prefs, chat_threads, agent_acts, attention_snoozes, memory_fts`. Chat
  turns are `agent_invocations` rows (`mode='chat'`, `invocation_kind='chat_turn'
  |'chat_child'`) with `thread_id`. `agent_acts` is the Ring 1 receipt ledger
  (SPEC-v37 §4.5); `chat_threads.sdk_session_id` backs native session resume
  and `briefs.dispatch_summary`/`briefs.governs_date` are code-computed,
  never model-written.
- `core/acts.py`, the closed Ring 1 act list (SPEC-v37 §4): `RING1_ACTS`,
  `RING1_GRANTS`, `_apply()` (the shared receipt-plus-write transaction), one
  handler per act, `_UNDO_HANDLERS`/`undo_act`.
- `core/ledger.py`, the archivist-as-a-function (SPEC-v37 §5.3): `distill()`
  and its five fact-promotion extractors, plus the `compact_memos()` call.
- `core/memory_index.py`, the FTS5 memory index (SPEC-v37 §5.4):
  `sync_memory_index()`, `SOURCE_TABLES`, one `_rows_<table>` indexer per
  source.
- `core/situation.py`, the nightly situation block (SPEC-v37 §6.1):
  `current_situation(conn, now)`, prepended to every producer's prompt.
- `agents/consult_gate.py`, the Plane B runtime capability wall (SPEC-v37
  §2.2-2.6): `make_consult_gate()`/`make_consult_pretooluse_hook()`,
  `CONNECTOR_WRITE_TOOLS`, the `data/consult/` workspace constants.
- `core/metrics.py`, turns goals into live status. A goal's `metric_key` maps to
  a resolver in `METRIC_RESOLVERS` (e.g. `burn_this_month`, `audit_calls_today`,
  `gym_weekdays_this_week`) that computes its actual from tables;
  `resolve_goal_actuals()` + `goal_status()` produce ON/OFF TRACK / AT RISK / NO
  DATA. Also `compute_tradeoff_hints`, `stale_data_domains`, `finance_state`
  (checking freshness now traces to the source that actually produced the
  balance, `db.checking_balance()`'s own `source` field, never a hardcoded
  one — SPEC-v37 §8.4). `db.net_worth()` is the one net-worth computation
  every caller shares (assets minus credit/loan balances across every linked
  account); `db.cash_position()` is a rolling 30-day net flow over the linked
  account set (`account_key != ''`), not a sum since the first import ever.
- `core/pillars.py`, presentation layer that groups goals into the six dashboard
  pillars (`btc, body, partner, school, life, money`). Note the domain→pillar
  mapping is NOT 1:1: `personal` splits into **partner** vs **life** by a `#partner`
  note tag / name match (`is_partner_goal`).
- `core/streaks.py`, the "bending" gym streak. Stores **events, not tallies**
  (`streak_events(date, kind)` where kind ∈ `confirm|grace|reset`). The nightly run
  is the ONLY writer of `grace`/`reset` and is idempotent; missing a weekday spends
  a banked "stool" so the streak survives (see `docs/SPEC-v6-the-corner.md`).
- `core/plan.py`, pure day-plan derivations (SPEC-v7): `is_sailed`, `suggest_blocks`
  (fixed-priority, capped at 4), `next_free_slot`, `plan_adherence_7d`. Two stored
  block statuses (`planned|done`); "sailed"/"moved" are computed, never stored.
- `core/journal.py`, pure journal derivations (SPEC-v8): `journal_day` (a 04:00
  cutoff attributes after-midnight entries to yesterday), `journal_stats`
  (unbreakable rolling count: no streak), `agent_signal` (counts only, never text
  or media), `on_this_day`.

### Dashboard (`dashboard/`, `api/`)

- `api/main.py`. FastAPI, CORS locked to the configured dashboard origins.
  `GET /api/state` is the one fat endpoint the SPA polls every 15s; the rest are
  goal/fact/activity/wellness/partner-task/proposal mutations plus
  read-only invocation/room endpoints, the SPEC-v26 `/api/chat/*` thread
  surface (`Cache-Control: no-store`), and `POST /api/agents/run` (spawns
  `runner.py` as a subprocess, 300s cooldown + shared in-process gate). Vite
  proxies `/api` → `:8787` (`dashboard/vite.config.js`).
- React 18 + `motion`, **no router**: pages are hash-based (`usePage` in
  `App.jsx`, `PAGES` array). Pages in `dashboard/src/pages/`, shared bits in
  `components/` (`CommandPalette` = Cmd+K, `PillarStrip`, `ActionStack`, goal
  wizard under `components/goals/`). `lib/api.js` wraps fetch. When a mutation
  writes back, the API also drops a memo from `"ian"` so agents learn his judgment.

### Ingest is the write boundary (`ingest/`)

Loaders are the **only** writers for their sources and enforce rules in code:

- **Money is sacred.** Only bank CSV (`import_csv.py`) / SimpleFIN
  (`sync_chase.py`) / SnapTrade (`sync_fidelity.py`) may write `transactions` /
  `holdings`. `import_csv.py` auto-categorizes via `KEYWORD_CATEGORIES`; burn-cap
  categories are `BUSINESS_CATEGORIES` in `core/db.py`.
- **Connector sync** (`ingest/from_connector.py`) is the single writer on the
  Claude-connector seam. A Claude *session* (with Gmail/Calendar/Drive connectors)
  READS and emits strict JSON; this loader validates/dedupes/writes into exactly
  `calendar_events, facts, documents, memos, ingest_log`: **never `transactions`**,
  connector facts always `verified=0`, notes pinned to priority 1, fully
  idempotent. Driven by the `/sync-gmail`, `/sync-calendar`, `/sync-drive` slash
  commands in `.claude/commands/`: those are **READ-ONLY pledges**; never send,
  reply to, label, or delete anything in Ian's connected accounts.

### Plan (SPEC-v7): day calendar + iCloud two-way sync

A full-stack feature on the same app, isolated by clear boundaries:
- **Data:** `plan_blocks` (ianOS intentions, two statuses, optional `goal_id`) +
  `plan_tombstones` (delete-safety). Pure logic in `core/plan.py`.
- **API:** `GET /api/day` merges editable blocks with read-only `calendar_events`
  commitments + suggestions + overpack; `POST/PATCH/DELETE /api/plan/blocks`;
  `POST /api/plan/sync` (lock + 120s cooldown, 200-on-throttle, 501 when
  unconfigured). Memos on create/delete only, not edits.
- **UI:** `dashboard/src/pages/PlanPage.jsx`, time-ribbon canvas with now-line,
  one-tap create (Start+End pickers on a 15-min grid, presets 30m-4h; any length is
  valid, the API only requires `end > start`), and **wilt-not-die** sailed
  styling. `lib/plan.js` mirrors the
  Python time math. Design law: `--crit` red is banned here; a past unfinished
  block softens, never reddens; no completion % is ever shown.
- **iCloud sync** (`ingest/sync_icloud.py`) is the write boundary to CalDAV. The
  engine runs on a tiny calendar interface so it unit-tests against a `FakeCalendar`
  with no network; only `connect()`/`ICloudCalendar` touch `caldav` (lazy import, so
  tests need neither the library nor creds). **ianOS writes only to a dedicated
  "ianOS Plan" calendar**; all other iCloud calendars are read-only commitments.
  Conflict rule: **remote (phone) wins**. A synced block's local delete leaves a
  tombstone so the next pull removes it remotely instead of re-importing it. iCloud
  host-sharding (`pXX-caldav.icloud.com`) is survived by degrading gracefully per
  calendar. Never `event_by_uid` for deletes, find the event in the listing.
- **Agent visibility:** `read_calendar` returns `plan_blocks_7d` +
  `plan_adherence_7d`; the steward reads plan-vs-done as a task-**initiation** signal
  (never "try harder"); the chief references real block times in the Day Command.

### Journal (SPEC-v8 + v11): private nightly reflection + photo memory

A full-stack feature whose defining property is that agents **never** see its
contents, phone/LAN access is allowed with the same token as the rest of the
API (SPEC-v11 overturned laptop-only):
- **Data:** `journal_entries` (body + one `media_path`/`media_kind` + `shared`);
  media files live under `data/journal/YYYY/MM/` (gitignored). Pure logic in
  `core/journal.py`.
- **API:** CRUD under `/api/journal`, streamed media upload (512 MB cap, extension
  whitelist, served by entry-id only, no path traversal), day/month browse
  helpers, and `POST /api/journal/{id}/share` (text → a `from_role='ian'` memo;
  media never shared).
- **The privacy wall (do not weaken):** `/api/state` excludes all journal data;
  the runner adds **no** journal tool, agents get only the precomputed
  `agent_signal` line (a boolean + counts). A test asserts each.
- **UI:** one `JournalPage` surface (SPEC-v11): blank composer at top, look-back
  below (phone day cards / laptop photo days / Photos grid). `#shutdown`
  redirects here. Design law: blank & promptless, zero shame (no `--crit`, no
  streak that can break), the exhale is the reward.
- **Agent visibility:** physician + chief get one `agent_signal` line ("closed the
  day N of 7"), never the words. Shared entries arrive as ordinary `ian` memos.

### The Line (SPEC-v9): lead pipeline + the call loop

Clockwork's cold-call surface. Ian has ~1,300 callable leads and ~19 weekdays
before school, so at 20 calls/day he reaches under a third of them: **the
feature is the ordering guarantee, not the tracking.**

- **Data:** `leads` (one row per business, `phone_norm` UNIQUE) + `lead_touches`
  (events, not tallies: the `streak_events` precedent) + `call_runs` (one
  bounded calling session). Pure logic in `core/leads.py`.
  **Gotcha:** `phone_norm` holds the normalized 10-digit phone for 96.6% of rows
  and a `x<sha256[:15]>` hash of name+address for the ~64 phoneless ones
  (`lead_key()` in the importer). It must never be left NULL. SQLite permits
  unlimited NULLs in a UNIQUE column, so nulls duplicate on every re-import.
- **Ingest:** `ingest/import_leads.py` is the **only** bulk writer. It imports
  `leads/enriched.csv` only, the four `tier_*.csv` files are a *partition* of
  it (A+B+C+D = 1,958), reproducible with a `WHERE`, so importing them
  separately would just duplicate. **On re-import only scraped/scored columns
  refresh** (`LEAD_SCRAPED_COLS` in `core/db.py`); `stage/attempts/last_touch/
  next_touch/notes` are Ian's and survive, the scraper will run again and must
  never wipe his call history. Rows with no phone, a non-IL address, or a
  `JUNK_NAMES` match (KeyMe/Minute Key kiosks, Johnstone Supply) import as
  `parked` and never enter the queue.
- **Scoring is NOT ianOS's job.** `leads/enrich_prospects.py` computes
  Fit/Pain/Reach (`Total = Fit+Pain+Reach`, exactly) and assigns tiers, where
  **D is a disqualification, not a low score**. ianOS imports that verbatim and
  never recomputes it.
- **The queue** (`call_queue`) is deterministic Python in six bands: promised
  callbacks → warm → tier A → tier B → second pass → tier C. Tier D and `parked`
  never appear. Capped at the remaining daily quota so it empties instead of
  looming. Market priority is **date-aware**: north (Naperville-Aurora) outranks
  south (Champaign-Bloomington) until `MOVE_IN_DATE`, then flips.
- **The script writes itself.** `call_card()` composes ask-for / open / hook /
  ask / objections from the row: **deterministic templating, never a model
  call** (a model in the call path would cost money per dial and add latency at
  the exact second Ian needs none). Hook priority is strongest-evidence-first;
  `miss_signal` + `claims_247` is the top hook. **`quote_is_readable()` gates
  every quote**, the scraper's sweep also catches accusations ("rude",
  "harassing", "legal department") and reviews where the *customer* admits they
  were the unreachable one. Ian reads these words aloud to a stranger, so an
  unsafe quote is suppressed and the hook falls through to softer evidence
  rather than risk the call. 4 of the 86 real quotes are suppressed today.
  `_clean_quote()` also trims the scraper's mid-word cut off **both** ends : 
  ~10% of quotes end mid-word, and "every com" is unsayable.
- **API:** `/api/leads/queue` returns leads with their composed `call_card` so
  the brief is on screen the instant the card mounts. `POST /api/leads/{id}/touch`
  writes the touch, the stage move, and the `activity` bump in one transaction : 
  which is why **no goal or metric in the repo changed**: `audit_calls_today`,
  `follow_ups_today` and `demos_last_7d` still resolve, now off real events, and
  `activity.conversations` came alive. `DELETE /api/leads/touches/{id}` is the
  undo and reverses all three writes.
- **UI:** `dashboard/src/components/TheLine.jsx`: three beats (brief → live →
  card) inside a `call-mode` class on `.app-shell` that mirrors `shutdown-mode`
  exactly (same 0.22 dim; one dimming scale in the product, not two). Design
  law: `--crit` is banned; no percentage, streak, or lifetime counter; a rested
  lead softens like a sailed plan block. **`heat` is earned by dialing, never by
  outcome**, a no-answer warms the run exactly as much as a booked demo,
  because Ian controls the dial and not the pickup. `tests/test_leads.py`
  asserts this; if it ever fails the feature has become a shame machine.
- **The list** (`LeadList.jsx`) is collapsed by default and is a **look-up
  surface, not a work surface**, unlike the queue it shows everything including
  `parked` and tier D. `db._lead_filter()` is shared by `list_leads` and
  `count_leads` so the pager total can never drift from the rows.
- **Round-trip:** `ingest/export_leads.py` writes the `leads` table back into
  the enricher's own column shape with the call-log columns (`Call 1 Date`,
  `Answered?`, `Outcome`, …) filled from real touches, plus six additive
  `ianOS *` columns. That closes the loop `enrich_prospects.py` was always
  shaped for: scrape → enrich → dial → export → re-enrich.
- **Back-test** (`leads.backtest` + `make backtest`): contact/demo rates by tier
  and by Fit/Pain/Reach band, plus a `separation` table showing which component
  actually distinguishes leads Ian reached from ones he didn't. It **reports and
  never mutates a tier** (a test asserts this), it is **gated**, nothing below
  30 dialed leads, "preliminary" below 100, and it is terminal-only, because a
  win-rate chart cannot change the next call and the dashboard bans conversion
  analytics.
- **Agent visibility:** `read_pipeline` is allowlisted to `scout` + `chief` only
  and enforced a second time inside the tool (`PIPELINE_READERS`). It is
  **read-only, and no writing counterpart exists**, no agent may set a stage,
  log a touch, or open a run. `build_user_prompt` precomputes the pipeline block
  in Python (`_pipeline_lines`) so the model never does the date or coverage
  math, and **run/heat data is deliberately withheld**, agents see dials and
  outcomes, never "he stopped after 4" (the steward's plan-adherence precedent:
  initiation signal, never "try harder"). The chief is told to name a real
  business in the Day Command.

### osUI (SPEC-v10): mobile-first, and Notes

The dashboard is now authored at 375px first; desktop is the enhancement.
**Invoke the `osui` skill (`.claude/skills/osui/`) before any interface work** : 
it carries the law, the traps that have actually shipped here, and the
verification order. `docs/SPEC-v10-osui.md` holds the reasoning. The four that
bite hardest:

- **The installed PWA is a different runtime than a Safari tab** (L9). Standalone
  reports real `env(safe-area-inset-*)` where a tab reports 0, so a `padding`
  shorthand that drops the insets looks perfect in the browser and renders under
  the notch on the phone. Never verify mobile work in a tab alone.
- **Never `100vh`**. Safari's is the viewport with the URL bar hidden. `100dvh`,
  with `vh` first as the fallback. The mobile bar's height is `--nav-h`, in one
  place, reserved by the shell and occupied by the bar.
- **The mobile tab bar may only be hidden by a `min-width` query.** A bare
  `.nav-mobile { display: none }` after the breakpoint block wins on source
  order and leaves the phone with no navigation at all. This shipped once.
- **Zero-value pixels are a bug** (L3): a subtitle restating the tab, a metric
  reading `0`, a strip duplicating the nav. Delete, don't shrink.

**Navigation** is five fixed tabs (`Command · Plan · BtC · Partner · More`) plus a
horizontal swipe through the pillar ring in `lib/swipe.js`. The swipe leaves the
outer 24px to iOS's own back gesture, judges its axis once on the first 12px so
a scroll can never become a navigation mid-gesture, and skips any touch starting
inside an element that owns horizontal gestures itself: a sideways scroller, or
anything marked `data-swipe-own` (a goal row). It is disabled in the committed
modes. Everything outside the five tabs lives in the More sheet, and **a page
with a lit tab drops its own title while a page behind More keeps it.**
`#chat` (Fury) is behind More on purpose; it does not earn a sixth tab.

`notes` is Ian's own writing surface, deliberately **not** `journal_entries`.
The journal's defining property is that no agent ever sees it; notes are read by
`chief` + `archivist` via `read_notes`, which is **read-only with no writing
counterpart** (the `read_pipeline` precedent, enforced in `NOTE_READERS` as well
as the allowlists). Sharing one table would put a single boolean between Ian's
private reflections and a model. Deletes are soft, so Undo restores the row.

### The Sheet primitive and the layout measure (SPEC-v29)

**One overlay component.** `dashboard/src/components/Sheet.jsx` replaced five
hand-rolled implementations that disagreed on the basics (two had no Escape,
one had no focus trap, one rendered a class whose CSS had been renamed away).
Every overlay goes through it: portal, `useFocusTrap`, Escape, backdrop-tap,
internal scroll, and a 44px dismiss. Variant follows **content weight**, not
which spec shipped it: phone is always a bottom sheet; desktop is a popover for
a small closed choice set and a centered dialog for real reading weight.
`CommandPalette` is deliberately excluded, it is a different primitive.
Sheet also toggles `body.sheet-open`, which explicitly hides the mobile tab bar
while any sheet is open. That is **not** redundant with z-index: the panel
animates its own opacity on open, so for ~200ms it is genuinely translucent and
the nav bar underneath showed through.

**Chat is shell chrome, not a page.** `AgentChat` mounts once in `App.jsx`
beside `Nav` and the toast stack. A routed `#chat` page would unmount on every
tab switch under the same hash-conditional scheme every page uses, which is the
bug that lost the thread; there is nothing to unmount if it was never in a
page's lifecycle. `#chat` folds to `#home` and there is no `ChatPage.jsx`.
SPEC-v37 §7.1 extended this with a portal (see "The consult surface" above,
**Law A10**): the one mount now `createPortal`s into `CommandPage`'s dock
slot when Command is active, DOM position only, lifecycle unchanged.

**Layout measure.** `--content-w` (920px) is a *prose* measure and only prose
should use it. Record lists and grids use `--content-w-wide` (1440px) at
`min-width: 901px`. `.page-stack` is both a page root and a nested container,
so capping it at the prose measure pinned every goal panel to 920px no matter
how wide its page was; it now takes the wide measure and a nested stack simply
fills its parent. Measured target: **zero dead gutter on a 1512px laptop**.

### Money personalization (SPEC-v30)

`money_prefs` is one singleton row (the `chat_prefs` precedent) holding
`hero_metric`, `hero_goal_id`, and a single `widgets_json` array carrying order
*and* visibility together, so the two can never desync. **Only one hero card
renders at a time** and the amber wash is exclusive to it: net worth and burn
previously shared byte-identical styling, which is why the page had no focal
point. Per-account `color`/`icon` live on `financial_accounts` but are
**deliberately absent from `upsert_financial_accounts`'s `ON CONFLICT` set**,
so a provider sync can never wipe them. `budget_categories` + `budget_rules`
replaced a `$150` literal that existed in three places (a Python set, the
frontend's `burnLevel` default, and a hardcoded `burnCap`); the active cap now
flows through `/api/state`, and a rule only ever matches transactions whose
`category` is empty, so a personal keyword can never poach a business txn.
The CFO/wealth/chief can now actually see the account set: `read_accounts`
(SPEC-v37 §8.4) returns every linked account plus `db.net_worth()`, and the
Money hero has its own refresh control (`POST /api/money/refresh`, sharing a
120s cooldown with the chat `refresh_money` workflow) since the sync
endpoints used to fire only right after connecting an account.

**Goals are archived, never deleted, from the UI.** `goals.archived` is filtered
inside `all_goals()`, which is the single read path for `/api/state`, metrics,
pillars and the agents' `read_goals` : so retiring a goal removes it from the
dashboard *and* the nightly run in one place. Any new goal query must go through
`all_goals()` or repeat that filter. Undo restores the same row on purpose:
metrics resolve off goal ids, so a re-created goal is not a restore.

**The roster** (`#roster`, under More) shows the 10 active agents with their
glyph, codename, cadence and track record. `db.role_stats()` derives that
from existing `proposals` + `memos` rows : no new table, no new writes. The
record is the *agent's* ("you took 2 of 4"), never a score on Ian; pending
proposals are excluded, because undecided is not rejected. A health-gated
role (physician, coach) shows `"off, health sharing"` instead of a stale
`last_seen` when consent is off (SPEC-v37 §8.6, `health_sharing_off` computed
server-side in `_roster()`), rather than reading as merely asleep. Agent
colour and glyph live in `dashboard/src/lib/agents.js` only : App.jsx used to
keep a second copy of the colour table, and two tables drift.

### Lock screen (SPEC-v12) + brand icons

Client-side privacy curtain before any `/api/state` poll. Not network auth.

- **UI:** `LockScreen.jsx` + `lib/lock.js`. Huge logo, America/Chicago 12-hour
  clock + date, Face ID (WebAuthn platform) or password `ianos`.
- **Session:** unlocked in `sessionStorage`; re-locks after ≥15min backgrounded
  (`BG_RELOCK_MS` in `lib/lock.js`; was 90s through SPEC-v12, widened after it
  proved a false-alarm generator on a brief app switch); cold open always
  locked. `--crit` banned on this surface.
- **HTTPS required for Face ID.** Tailscale `https://` install (see
  `docs/PHONE.md`). LAN HTTP → password only.
- **Brand sources:** `dashboard/public/ianOS.jpg` (app icon) and `logo.png`
  (site mark). `make icons` / `scripts/make_icons.py` writes `icons/*.png` +
  `logo-lockup.png`. Desktop nav: lockup, then a full-width "Jump" ⌘K row.
- **iOS icon refresh:** delete home-screen icon and Add to Home Screen again;
  iOS does not update artwork in place.

### Impeccable passes (SPEC-v13 mobile, SPEC-v14 desktop)

Two systematic audit-then-fix passes over the whole dashboard, run via the
`impeccable` skill's methodology (fan out audit-dimension agents, verify each
finding against source and a live browser, fix, re-verify). Read these before
touching UI code they cover; they're the most current record of what "done"
looks like on each surface.

- **SPEC-v13** covered the phone: a crash-on-every-memo bug (`ROLE_COLORS`),
  toasts/undo hidden behind the tab bar, the 16px mobile-first form-control
  rule (osUI L10) so iOS stops zoom-jacking on focus, a shared semantic
  z-index scale (osUI L11, `--z-*` tokens in `styles.css`), and a
  session-survives-relock resume flow for The Line's call runs.
- **SPEC-v14** did the same for the `@media (min-width: 901px)` desktop
  enhancement layer (osUI L1): keyboard focus traps (`lib/useFocusTrap.js`)
  and WCAG contrast fixes, per-page desktop grids for Money/Memory/Roster/Inbox
  instead of a stretched phone column (osUI L16, `--content-w-wide`), and
  removing two SaaS-template drifts (Money/Partner hero gradients) the
  `impeccable` skill's absolute-bans list exists to catch.
- **The recurring trap this pass surfaced**: a fix landing on a mobile-only
  selector (`.nav-mobile`, etc.) does not reach the desktop equivalent, and
  vice versa. SPEC-v13's nav tab-tint fix (unselected muted, active accent)
  shipped mobile-only; SPEC-v14 found the identical untinted-icon bug still
  live on the desktop rail. When a state-carrying visual bug is fixed on one
  input surface, check the other before calling it done.

### School: Canvas, class notes, and study aids (`core/school.py`)

The academic domain is deliberately **its own schema and its own module**, not
new columns on the shared tables. `core/school.py` owns `SCHOOL_SCHEMA` and
creates it via `ensure_schema(conn)` rather than `core/db.py`'s migrations, so
the academic term can be reshaped without touching money, leads, or journal.

- **Canvas has two paths in: a manual snapshot, or an optional live pull.**
  `make import-canvas FILE=…` runs `ingest/import_canvas_calendar.py` over a
  downloaded `.ics`. `ingest/canvas_ics.py` parses it and returns **only** a
  fixed field list: never DESCRIPTION, never event URLs, never the feed URL
  (which is a bearer secret). `--dry-run` counts against an in-memory DB and
  touches nothing. Setting `CANVAS_ICS_URL` in `.env` additionally enables a
  scheduled live pull (`ingest/sync_canvas.py`, `make sync-canvas` /
  `make schedule-canvas`, SPEC-v32 Part C) that fetches that same feed on a
  6-hour cadence and hands the bytes to the identical importer core. Either
  way, the feed URL itself never appears in code, argv, logs, or any
  agent-visible surface: only the parsed, sanitized records ever reach the
  database.
- **`school_items` belongs to the importer.** `import_canvas_items` rewrites
  every row from the snapshot and `_archive_missing_items` archives whatever
  the feed dropped. **Never store a human judgment on that table**: the next
  sync erases it. This is the same write-boundary split as `LEAD_SCRAPED_COLS`.
- **Crossing homework off therefore lives in `school_item_completions`**, keyed
  on the stable `(provider, external_item_id)`, so a completion survives
  re-import, archive, and archive-then-return (tested). Finished work leaves
  `upcoming` and every count, and appears in `just_done` so the act is visible
  and reversible instead of a deletion. Counts are plain totals that only go
  up: no streak, no percentage, nothing that can keep score against Ian.
- **Plan stays the one calendar.** `school_calendar_projection` maps academic
  items to `calendar_events` so a fresh snapshot updates or removes *only* its
  own projection, never an iCloud or manual event.
- **Class notes are not `notes`.** `school_note_sessions` holds a versioned
  ProseMirror-shaped document with `expected_revision` compare-and-swap on
  every save. `notes` is a narrow agent-readable Markdown dialect; a class
  session needs private rich structure, so they share nothing.
  **The editor's node/mark set must stay a subset of `_NOTE_ALLOWED_NODES` /
  `_NOTE_ALLOWED_MARKS`.** It did not once: StarterKit silently bundles
  Underline (Mod-u) and Link (`autolink`), the server 422'd the document, and
  because the mark stayed in the editor *every later autosave failed too*:
  one reflex keystroke made a note permanently unsaveable mid-lecture. The set
  lives in `dashboard/src/components/school-notes/schema.js` and
  `dashboard/tests/school-note-schema.test.mjs` diffs it against the Python
  allowlist. Do not add a Tiptap extension without extending both.
- **Study aids are opt-in, consent-gated, and revision-bound.**
  `school_ai_settings` is one local consent row; `create_school_study_artifact`
  refuses without it, `claim_school_study_artifact` re-checks it inside the
  claiming UPDATE, and `complete_school_study_artifact` refuses to save if
  consent was withdrawn while the model ran. A course whose `policy_json` says
  `ai_policy.status == "prohibited"` is blocked server-side, not in the UI.
  The worker gets `tools=[]`, every ianOS tool explicitly disallowed, and note
  text as untrusted data; failures persist only a closed error code, never an
  SDK message (which can quote note content). Any edit bumps `revision` and
  marks prior-revision aids `STALE`.
- **Private course files** live in `school_note_assets` under `data/school/`
  (gitignored, claimed by `scripts/backup.sh`). Extension + declared MIME +
  **actual magic bytes** must agree, storage keys are server-minted and never
  client input, downloads are always `attachment` with `nosniff`, and neither
  the token nor the storage path appears in any JSON projection.
- **Agents see metadata only.** `agent_snapshot` projects course/deadline
  fields; note documents, plain text, study output, and files never cross it.

### Phone PWA ops

Operator manual: `docs/PHONE.md`. `make phone` regenerates icons, builds
`dashboard/dist`, serves via launchd + Tailscale. Manifest `start_url` embeds
the LAN token once.

### BtC inbound (SPEC-v17)

Demo bookings + contact messages from beatyourclock.com, pulled (never
pushed: ianOS is never public and the Mac sleeps). The site holds records in
Vercel KV behind `api/ianos-inbox` (bearer token); `ingest/sync_btc.py` is the
ONLY writer on this seam: validates, matches the lead **phone-first then email
then hashed key** (so `phone_norm` is never NULL), INSERT OR IGNORE by
`request_id`, commits, then acks. **The consent column is walled** (journal
precedent): never in `/api/state`, memos, or any agent tool; a sentinel test
asserts it. Inbound never touches tier/fit/pain/reach. Confirming a window is
one tap through `_touch_and_advance` (`demo`/`booked` + `next_touch`), so
`demos_last_7d` and band 0 just work. UI: `InboundStack` above The Line,
wilts after 24h, never reddens. `.env`: `BTC_SYNC_URL` + `BTC_SYNC_TOKEN`;
the dashboard auto-fires `POST /api/btc/sync` (120s cooldown, 501 when
unconfigured). Site half lives in the btc repo (`api/_ianos-store.js`,
`api/ianos-inbox.js`); demo window values are `YYYY-MM-DD|id|label`.

### Personal inbound + bot verification (SPEC-v19)

ianmccallum.com gained a contact form on the same seam, and both sites gained
Cloudflare Turnstile. **The load-bearing rule: a personal inquiry NEVER
becomes a `leads` row.** `leads` is Clockwork's scored, tiered call queue and
SPEC-v9's whole promise is its ordering guarantee; a recruiter or press email
entering it corrupts that invisibly, one row at a time. So
`inbound_requests.source` is `'btc' | 'personal'` (defaulting to `btc`), and
personal rows get no lead, **no `promised_by`** (that site makes no public
24-hour promise, so nothing may be late on it), and land on the **Inbox**
page rather than the BtC tab. One loader serves both via `SEAMS` in
`sync_btc.py` (`make sync-personal`, or `make sync-inbound` for every complete
seam). **Turnstile fails OPEN on any service
error and closed only on an explicit bot verdict** (`api/_turnstile.js`,
mirrored in both site repos): this repo already learned that a failed submit
is what gets an A2P campaign rejected, and spam is cheaper than a lost lead.
A rejected bot gets the same success shape a human does. Every piece is
optional: no site key renders no widget, no secret skips verification.

### Inbound alerts (SPEC-v18)

**Good news arrives quietly, a promise about to break arrives loudly.** The
site emails on every submission (`NOTIFY_TO` env var, config not source, after
14 months of notifications landing at an address Ian never read); ianOS pushes
only when a promise is about to expire unhandled. `ops/com.ianos.btcsync.plist`
runs `sync_btc.py --all-configured` every 15 min (`make schedule-inbound`,
with `make schedule-btc` retained as an alias; it refuses when no complete
seam is configured or a seam is partial, no failure memo by design: a 15-min network job fails
transiently and a memo per failure is the nag this product bans).
`core/promises.py` is the pure clock: `promised_by` is **stored** naive-local
converted from the site's UTC `received_at` (mixing them shifts every deadline
~5h in Central, there is a test for exactly that), `alerted_at` is the
fire-once guard, and 21:00-08:00 is silent. The push carries **name and time
only**: the SPEC-v17 consent wall extends here, and the ntfy topic is
world-readable. Detection is deterministic Python, never a model.

### Backups (SPEC-v16)

`scripts/backup.sh` is the engine (run/status/verify subcommands), restic +
Backblaze B2, client-side encrypted, nightly 21:45 via
`ops/com.ianos.backup.plist`. Operator manual: `docs/BACKUP.md`. The laws that
bite: the DB is snapshotted with `VACUUM INTO`, never file-copied (WAL);
restore (`scripts/restore.sh`) never writes into the live tree; restic carries
only non-git state (staged DB, `data/journal/`, `data/documents/`,
`data/consult/` — SPEC-v37 §2.4, the consult workspace, D9 claimed it the same
phase it was created — `leads/*.csv`, `.env`), git backs up code; a failed
scheduled run writes a
`system` memo (the role-crash precedent), never fails silently; unconfigured
is exit 2 + a scheduling refusal, the plan-sync 501 precedent. The engine is
bash + restic + sqlite3 only, so it moves to the Linux Framework laptop with a
10-line systemd timer (in BACKUP.md). `tests/test_backup.py` asserts the laws
against a local throwaway repo, skipped when restic is absent.

### Two repos: the private one and the public mirror (SPEC-v39)

The private repo is `Ian-mccallum/ianOS-private` (renamed from `ianOS` on
2026-09-01). The public `Ian-mccallum/ianOS` is a **scrubbed mirror carrying none of the
private history** (one commit per publish), regenerated from the private
repo by `make export-public`
(`scripts/export_public.py` plus templates in `scripts/public_export/`, both
private and never exported). Nothing is developed in the mirror: a fix lands
in the private repo, then the mirror is rebuilt and pushed from
`../ianOS-public`. **Never flip the private repo public and never push its
history anywhere public**: that history holds a server log with tailnet
addresses and the real class schedule. If you are reading this inside the
mirror, you are looking at a snapshot; open an issue rather than a PR.

- **Committed means exportable.** The export reads a private commit (HEAD
  by default), never the working tree, so uncommitted edits, untracked files
  and gitignored paths cannot leak, and anything committed can.
  A new personal string in a tracked file (a name, a balance, a room, a
  credential, a home path) needs a substitution rule or a path exclusion in
  the export script **before it is committed**; the leak check only knows
  the strings it has been taught. Specs that quote live numbers (SPEC-v37
  does) get scrubbed before they are committed.
- **Identifiers differ in the mirror.** The partner pillar, table, page and
  fact namespace are `partner` there; a few example businesses and owners in
  specs and tests are fictional; the six real course codes and two rooms are
  replaced; `agents/dossier.md` and `data/fall_2026_school_seed.json` are
  samples; the mirror's lock password is `ianos`. When triaging a public
  issue, translate back before grepping the private repo.
- **The public README is a template** (`scripts/public_export/README.md`),
  and the private `README.md` becomes `docs/MANUAL.md` in the mirror. Edit
  the template, never the mirror.
- **A rule that fires zero times is a finding, not noise.** The export
  prints them, because a rephrased or line-wrapped sentence silently stops
  being redacted otherwise.

The full law, the substitution map and the publish procedure live in
`docs/SPEC-v39-public-mirror.md` (private, excluded from the mirror).

## Conventions & gotchas

- Every executable module does `sys.path.insert(0, ROOT)` then imports `core.*`.
  Always run via `.venv/bin/python` from the repo root (the Makefile does this).
- `data/ianos.db` and `.env` are gitignored; `make clean` + `make seed` gives a
  fresh demo DB. Don't commit the DB.
- **`db.connect()` hardcodes `DB_PATH`.** A scratch script that means to use a
  throwaway database and forgets to `monkeypatch.setattr(db, "DB_PATH", …)`
  writes into Ian's **real** data instead. This has happened repeatedly. Tests
  use the `conn`/`client` fixtures; ad-hoc scripts must repoint `db.DB_PATH`
  before the first `connect()`.
- **An editor and its server validator are one contract.** Any surface that
  stores a structured document (Notes' Markdown dialect, School's ProseMirror
  JSON) can produce exactly what its extension set allows, and the server
  rejects everything outside its allowlist with a 422 the autosave cannot
  recover from. When adding an editor extension, extend the server allowlist
  and the parity test in the same commit, or the feature ships a
  one-keystroke data-loss bug.
- **A guardrail test that passes against the real clock proves nothing.**
  `term_active` was `today >= START` with no end date, so it could never go
  false and its test could never fail. Freeze the clock and pin both edges of
  any window.
- Domains are inconsistent by design across layers: the `goals` table CHECK allows
  `business|health|personal|finance` (+`school` added later), while **facts** use
  `business|finance|health|personal|college|legal`. `college` vs `school` both
  appear; check `DOMAINS` vs `FACT_DOMAINS` in `core/db.py` before assuming.
- Ian-facing tone is blunt: numbers first, verdict, next action (`SHARED_RULES` in
  `runner.py`). Persona is seasoning, not content; if voice fights clarity,
  clarity wins.
- **Anti-slop:** no em dashes, no marketing fluff. See `docs/ANTI-SLOP.md` and
  `PRODUCT.md` Voice. UI empty values use ASCII `-`.
- `docs/SPEC-v39-public-mirror.md` (private, never exported) is the public
  mirror's law: how `make export-public` scrubs the private repo into
  `Ian-mccallum/ianOS`, the substitution map, and what must never be tracked.
- Specs live at the root (`SPEC-LIFE-OS.md`, `SPEC-IPHONE.md`) and in `docs/`
  (`SPEC-v2`…`v14`). `docs/SPEC-v10-osui.md` is mobile UI law;
  `docs/SPEC-v11-journal-delight.md` is Journal; `docs/SPEC-v12-lock-screen.md`
  is the PWA Face ID / password lock; `docs/SPEC-v13-impeccable-mobile.md` and
  `docs/SPEC-v14-impeccable-web.md` are the mobile and desktop audit-and-fix
  passes (see "Impeccable passes" above). `docs/SPEC-v15-plan-calendar.md` is
  the Plan calendar rework for phone + desktop (read its defect ledger and its
  "As built" section before touching `PlanPage.jsx`).
  `docs/SPEC-v16-backup.md` is the encrypted off-site backup and
  `docs/BACKUP.md` its operator manual. `docs/SPEC-v17-btc-inbound.md` is the
  beatyourclock.com demo/contact pull-sync (both repos) and
  `docs/SPEC-v18-inbound-alerts.md` the promise clock that alerts on it, and
  `docs/SPEC-v19-personal-inbound.md` the ianmccallum.com seam + Turnstile.
  `docs/SPEC-v23-interactive-agents.md` is the Ask sheet, rooms, and
  invocation cache — **its whole interactive surface was deleted by
  SPEC-v37 §7.3**, read it only for archaeology, never as current behavior;
  `docs/SPEC-v24-money-foundation.md` is the account registry and inspect
  (inspect survives, now as a seeded chat message, not its own mode);
  `docs/SPEC-v25-day-chat.md` is daytime Fury chat
  (superseded in stance by `docs/SPEC-v26-agent-chat.md`, which made chat the
  Command surface; read v26 first, then SPEC-v37 §7 for the portal-dock
  rework)
  (read its "As built" section before touching `run_chat_turn`).
  `docs/SPEC-v27-composer.md` is the one-pill composer.
  `docs/SPEC-v28-transformation.md` is the third impeccable audit and
  `docs/SPEC-v29-design-system.md` the plan that answers it (Command reverts
  to the grid, one Sheet primitive, chat becomes shell chrome, chat's
  six-domain instant-write exception): **read v29 before touching any overlay,
  `Sheet.jsx`, or `App.jsx`'s mount points.**
  `docs/SPEC-v30-money-personalization.md` is the Money redesign plus
  `money_prefs` / per-account colour / `budget_categories`, and
  `docs/SPEC-v31-notes-reimagined.md` is Notes with folders, inline images and
  a constrained Markdown grammar (read its "What implementation will need to
  get right" list first). `docs/SPEC-v37-agent-rebuild.md` is the audit and
  rebuild this file's own "Tiered agency" / "The consult surface" / "Memory:
  the ledger and the index" sections describe: Ring 1/Ring 2, the archivist
  becoming `core/ledger.py`, the FTS5 memory index, the two-plane consult
  surface and `agents/consult_gate.py`, the roster retirement down to 10, and
  the money/health hardening in §8. Shipped in six phases, each its own
  commit; read its §11 for the phase boundaries and §12 for the laws each
  phase's tests assert. `docs/SPEC-v38-learning.md` is a drafted, **not yet
  built** spec for a "Learning" pillar (personal topics like case interviews,
  Python, AI — deliberately not school coursework); read it before starting
  that work, it is not implied by anything above. `docs/PHONE.md` is
  phone install + icons. `docs/MANUAL.md` is the operator manual; `GOALS.md` is the goals guide.
