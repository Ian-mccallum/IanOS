# SPEC v37: The Agent Rebuild

**Status:** QUEUED. No implementation is authorized by this document alone.

**Date:** 2026-08-31
**Owner:** Ian
**Audience:** Ian and the implementing agent
**Decision:** Rebuild the agentic layer around three ideas it currently lacks:
**two execution planes** separated by whether Ian is watching, **one memory
ledger** where retrieval may inform but never assert, and **ten agents whose
mandates are computed at run time instead of frozen in markdown**. Agents gain
a middle ring of reversible, receipted authority so the APPROVE loop stops
being the only verb they have.

---

## 0. Executive decision

The 2026-08-31 audit found a system with intact walls and no grip on reality:
870 tests green, every privacy boundary holding, and underneath it three loops
that had closed on themselves.

- **Role prompts froze in July.** `scout.md` still says "Quotas through Aug 9
  … ~19 weekdays left". The models correctly detect the mandate expired and
  have nothing to replace it with.
- **The APPROVE loop died 27 days ago.** Zero PENDING proposals since Aug 4.
  Producers are told "do not repeat a PENDING proposal" and are never shown the
  pending list. No agent has a verb for "this goal is obsolete."
- **Memory became a flywheel.** 17 facts, 6 fabricated placeholders marked
  `verified=1`, and an archivist that launders model prose into trusted
  history. A priority-3 siren has fired for nine days about goals that were
  archived out of the goals table.

Everything else — the "stale" chip that renders 22 hours a day, the Ask sheet
nobody uses, the CFO that can see one of nine accounts — is either downstream
of those three or an ordinary defect.

This spec fixes all of it, and makes the specific structural changes Ian chose:

| Decision | Choice |
|---|---|
| Roster | Ten agents, renamed and merged; nine specialists plus Fury |
| Memory | Typed ledger for assertion + local semantic index for recall |
| Agency | Tiered: reversible acts apply and are receipted; the rest proposes |
| Execution | Local Claude Code on the subscription, with real capability |
| Surface | Consult lives inline on Command, expandable to full screen |

---

## 1. What this supersedes

| Document | Status after v37 |
|---|---|
| SPEC-v23 (interactive agents) | **Superseded.** Ask, inspect and rooms retire. `run_interactive_role` is deleted. |
| SPEC-v25 (day chat) | Already superseded by v26. Remains historical. |
| SPEC-v26 (agent chat) | **Amended.** Chat survives and becomes the only consult surface. Its hand-rolled prior-turn window is replaced by native session resume (§7.4). Fury is no longer the default agent. |
| SPEC-v27 (composer) | **Kept.** The one-pill composer stands; it gains a capability chip (§2.5). |
| SPEC-v29 (chat as shell chrome) | **Amended.** The single-mount lifecycle is kept and correct; the DOM position moves inline via a portal (§7.1). |
| SPEC-v32 Part D (live Order) | **Fixed, not replaced.** Its gate was structurally unreachable (§8.2). |
| SPEC-v35 (health privacy wall) | **Kept, unchanged.** Consent gains a UI prompt (§8.6); the wall itself is not touched. |
| SPEC-v9 (The Line) | **Kept, unchanged.** The pipeline remains read-only to every agent in every plane. Ian owns every stage, touch and run. |

Role file **ids never change** — they are foreign keys in `memos`, `proposals`
and `facts`. Every rename in §3 changes `codename:` only. Every retirement sets
`active: false` and leaves the file and its history in place.

---

## 2. Two planes

This is the load-bearing new idea, and it is what makes "real Claude Code
power" safe to grant.

Today there is one capability model for every agent execution, tuned for the
riskiest case: unattended nightly runs. That is why the consult surface is
crippled — it inherited a threat model that does not apply to it.

> **Law A1 — Capability follows attendance.**
> An agent running while nobody is watching gets the minimum. An agent running
> because Ian typed a message, on a screen he is looking at, gets the maximum
> the machine can safely offer. These are two different programs, and the code
> says so.

### 2.1 Plane A — Nightly (unattended)

**Unchanged from today. Do not weaken it.**

- `tools=[]`. The in-process `ianos` MCP server is the only tool source.
- Per-role `ALLOWLISTS`; everything else in `disallowed_tools`.
- `setting_sources=[]`, `strict_mcp_config=True`.
- No filesystem, no Bash, no connectors, no web.
- `max_budget_usd` per role as a hard ceiling (new; see §9.3).
- Writes go to the blackboard and to Ring 1/Ring 2 (§4).

Rationale: a nightly run has no human in the loop, no way to ask, and produces
output that enters the shared memo board other agents read. It is the one place
where a bad tool call compounds silently.

### 2.2 Plane B — Consult (attended)

Ian opened a thread. He is on the screen. The run is bounded by a single turn.

- Real Claude Code: `Read`, `Grep`, `Glob`, `Bash`, `WebSearch`, `Skill`, and
  the `ianos` MCP server alongside them.
- `Write`/`Edit` are granted **only** inside the consult workspace (§2.4).
- Connected MCP servers (Gmail, Calendar, Drive) available **read-only**,
  by explicit tool name (§2.6).
- `sandbox=SandboxSettings(enabled=True, network=...)` for Bash.
- `add_dirs` scoped; `setting_sources=[]` retained so the agent can never
  inherit Ian's own permissive `~/.claude/settings.json`.
- `can_use_tool` — an async Python callback — is the single runtime gate.

### 2.3 The gate is Python, not prose

> **Law A2 — One gate, in code.**
> Every Plane B tool call passes through `consult_gate()` in
> `agents/consult_gate.py` before it executes. Prompt text is never the
> boundary. A tool that is not explicitly allowed is denied, and the denial
> reason is returned to the model so it can adapt.

```python
# agents/consult_gate.py
async def consult_gate(tool_name, tool_input, ctx) -> PermissionResultAllow | PermissionResultDeny:
    """Runtime capability wall for Plane B. Deny by default."""
    if tool_name in CONNECTOR_WRITE_TOOLS:            # send, trash, label, delete
        return deny("ianOS never writes to your accounts.")
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return _path_gate(tool_input)                  # workspace only
    if tool_name == "Read":
        return _read_gate(tool_input)                  # secrets + private stores blocked
    if tool_name == "Bash":
        return _bash_gate(tool_input)                  # denylist + sandbox
    if tool_name.startswith("mcp__ianos__"):
        return _ianos_gate(tool_name, ctx)             # existing role allowlist, unchanged
    return deny(f"{tool_name} is not available in a consult.")
```

Wired as `ClaudeAgentOptions(can_use_tool=consult_gate, ...)`, with a
`PreToolUse` hook carrying the same predicate as a second layer, because a
capability wall with one implementation is a capability wall with one bug.

### 2.4 The consult workspace

```
data/consult/              # gitignored, restic-backed, the ONLY writable path
  scratch/                 # agent working files, pruned at 14 days
  out/                     # things Ian asked for: a CSV, a draft, a chart
```

`add_dirs = [ROOT, ROOT/"data"/"consult"]`. Read is repo-wide; write is
`data/consult/**` only.

### 2.5 Read denials (absolute, both planes)

`_read_gate` denies, by path prefix, regardless of who asks:

| Path | Why |
|---|---|
| `.env`, `.env.*` | Live credentials: Plaid, SnapTrade, iCloud, restic, B2, push, OAuth |
| `data/journal/**` | SPEC-v8/v11 privacy wall. Agents have never seen the journal and never will. |
| `data/school/**` | SPEC-v36 private course files |
| `data/ianos.db*` | The database is reachable **only** through `ianos` MCP tools, so every write boundary, domain scope and privacy wall in `core/db.py` still applies. A raw file read would route around all of them. |
| `~` outside `add_dirs` | Everything else on the Mac |

> **Law A3 — The database is never a file.**
> No plane, no agent, no skill may open `data/ianos.db` as a file. Every read
> goes through an `ianos` MCP tool, because that is where domain scoping,
> the health wall, the journal wall and the pipeline read-only rule live.

### 2.6 Connectors are read-only, by name

The `.claude/commands/` sync commands already carry a READ-ONLY pledge. v37
makes it enforceable rather than promised:

```python
CONNECTOR_WRITE_TOOLS = frozenset({
    # Gmail
    "send_message", "reply", "forward", "create_draft", "update_draft",
    "trash_message", "trash_thread", "untrash_message", "untrash_thread",
    "label_message", "label_thread", "unlabel_message", "unlabel_thread",
    "update_message_labels", "create_label", "update_label", "delete_label",
    "mark_message_spam", "mark_thread_spam",
    "unmark_message_spam", "unmark_thread_spam",
    "apply_sensitive_message_label", "apply_sensitive_thread_label",
    # Drive
    "create_file", "update_file", "copy_file", "trash_file",
    "share_file", "get_file_permissions",
})
```

Matched on the tool's bare name after the `mcp__<server>__` prefix, so a
reconnected server with a new id cannot smuggle a writer through. New connector
tools are denied by default: the allowlist is `*_get_*`, `*_list_*`,
`*_search_*`, `read_*` and nothing else.

### 2.7 Capability chips

Plane B capability is per-thread and visible, extending SPEC-v27's composer.
The model chip's Reasoning sheet gains a **Capability** row:

| Chip | Grants | Default |
|---|---|---|
| Files | `Read`, `Grep`, `Glob` over the repo | on |
| Workspace | `Write`, `Edit` into `data/consult/out` | off |
| Shell | `Bash`, sandboxed, denylisted | off |
| Mail | Gmail read tools | off |
| Calendar | Calendar read tools | off |
| Drive | Drive read tools | off |
| Web | `WebSearch` (existing) | off |

A chip that is off means its tools are in `disallowed_tools`, not merely absent
— the existing `chat_allow` discipline, extended to built-ins.

---

## 3. The roster: ten agents

### 3.1 The ten

| id (never changes) | Codename | Owns | Tier | Plane |
|---|---|---|---|---|
| `steward` | **Alfred** | Life admin, plan, notes, family dates. **The default agent.** | daily | A + B |
| `scout` | Dwight Schrute | Clockwork pipeline, The Line | daily | A + B |
| `cfo` | Jordan Belfort | Cash, burn, accounts, runway | daily | A + B |
| `wealth` | **Rockefeller** | Portfolio, holdings, long-horizon money | weekly (fri) | A + B |
| `watchdog` | **Dumbledore** | School **and** every dated obligation | daily | A + B |
| `physician` | Dr. House | Health data, sleep, energy | daily | A + B |
| `coach` | Rocky | Training, the gym streak, the montage | weekly (sun) | A + B |
| `lovebird` | **Cupid** | Partner | weekly (sat) | A + B |
| `counsel` | Harvey Specter | Documents, legal process | tripwire | A + B |
| `chief` | Nick Fury | **All-hands only.** Composes the brief; convened for cross-domain calls. | daily (brief) | A + B |

### 3.2 Renames

Display only. `codename:` in frontmatter, plus `ROLE_GLYPHS`/`ROLE_COLORS`
entries in `dashboard/src/lib/agents.js`.

- `wealth`: Bobby Axelrod → **Rockefeller**
- `lovebird`: Hitch → **Cupid**
- `watchdog`: Hermione Granger → **Dumbledore**

### 3.3 The merge

`advisor` (Dumbledore, college, weekly/wed) folds into `watchdog`, which keeps
its id and its 70 memos and 31 proposals of history.

1. `agents/roles/watchdog.md` — `codename: Dumbledore`, `domains: all`, tier
   stays `daily`. Rewrite the body per §6: the wise mentor who owns both the
   degree and the legal chain, and never misses a date.
2. Add `read_school` to `ALLOWLISTS["watchdog"]`.
3. Move `advisor`'s tripwires (`dated_fact_within("uiuc:", 21)`,
   `school_exam_within(7)`) onto `watchdog`.
4. `agents/roles/advisor.md` — `active: false`. **Do not delete the file.**
   `load_role("advisor")` must keep resolving so its 16 memos and 10 proposals
   still render with a codename on the Memory page and the Roster.

### 3.4 Retirements

`active: false`, files retained, history intact, no successor agent.

| Retired | Codename | Its data |
|---|---|---|
| `archivist` | Samwell Tarly | Its job moves into code (§5.3). This is the point: memory should never have been a model's job. |
| `family` | Uncle Iroh | Family dates → **Alfred**, with the 10-day tripwire moved onto `steward`. |
| `publicist` | Don Draper | `content_log` retained, unread. Revive as a goal when Ian publishes again. |
| `infra` | Scotty | `infra_status.json` retained, unread. When Clockwork has a production service, that is monitoring, not an agent. |

Retired roles drop out of `SEQUENCE` in `core/roles.py`. `all_roles()` still
loads them so the Roster can show them as retired rather than vanishing — an
agent that disappears takes its track record with it.

### 3.5 Alfred is the default

- `chat_prefs.default_role` becomes `steward` (was `chief`).
- The Command consult dock opens on Alfred.
- Cmd+K "ask an agent" with no name routes to Alfred.
- Fury is reachable by name, and by an **All-hands** action (§3.6).

Alfred's role file is the butler: no domain expertise, total situational
awareness, and the widest hands in the roster. He is who you talk to when you
do not want to think about which agent to talk to.

### 3.6 Fury convenes, using real subagents

The hand-rolled "rooms" feature (sequential Haiku children plus a tool-free
synthesis) is retired. Its idea was right; its implementation predated the SDK
support. Fury's all-hands uses `ClaudeAgentOptions.agents`:

```python
agents={
    role: AgentDefinition(
        description=INTERACTIVE_MISSIONS[role],
        prompt=chat_system_prompt(role),          # full persona + law layers
        tools=[f"mcp__ianos__{t}" for t in sorted(interactive_allow(role, conn))],
        model=HAIKU, effort="low", maxTurns=4,
    )
    for role in convened
}
```

Fury runs on Sonnet at the thread's effort, delegates in parallel, and
synthesizes. Attribution and disagreement stay visible in the transcript, which
is what made rooms worth having.

---

## 4. Tiered agency: three rings

> **Law A4 — The ring is a property of the act, not of the agent.**
> Reversibility is decided in code, per act type, and never by a model
> describing its own intent.

### 4.1 Ring 0 — Read

Unchanged. Domain-scoped, wall-enforced.

### 4.2 Ring 1 — Reversible acts

Applied immediately, no approval, **every one receipted and undoable**.

The list is closed and lives in `core/acts.py`:

| Act | Bound enforced in code |
|---|---|
| `plan_block.create` / `.move` / `.delete` | Today or later; `end > start` |
| `note.create` | Markdown dialect validated as today |
| `partner_task.create` / `.complete` | — |
| `gym.confirm` | Today only; never writes `grace` or `reset` |
| `activity.log` | Increments only |
| `goal.rebaseline` | Existing goal; target or deadline only; never `domain`, never `hero` |
| `goal.archive` | Deadline **> 14 days past** and no unarchived goal depends on it |
| `transaction.recategorize` | Category only; never amount, date or account |
| `fact.flag_unverified` | Sets `verified=0`; can never set it to 1 |
| `attention.snooze` | Max 7 days, one item |

**Never Ring 1, in any plane, for any agent:** moving money, sending anything,
lead stage or touch (SPEC-v9), journal, health values, school completions,
proposal decisions, `verified=1`, `focus`, `brief`.

### 4.3 Ring 2 — Propose

Everything else. `create_proposal` as today, plus two new kinds that give the
system the verb it was missing:

- `goal_change` — target, deadline, or retirement of a goal that is *not* yet
  eligible for Ring 1 archival.
- `quota_rebaseline` — a whole quota set moved for a season.

### 4.4 Ring 1 by role

| Role | Ring 1 grants |
|---|---|
| `steward` (Alfred) | **All of them.** The butler acts. |
| `watchdog` | `goal.rebaseline`, `goal.archive`, `attention.snooze` |
| `cfo` | `transaction.recategorize` |
| `scout` | `activity.log` |
| `coach` | `gym.confirm` |
| `physician` | none — analysis only, SPEC-v35 unchanged |
| `lovebird` | `partner_task.create` |
| `wealth`, `counsel`, `chief` | none |
| every role | `fact.flag_unverified` |

### 4.5 Receipts

```sql
CREATE TABLE agent_acts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role         TEXT NOT NULL,
    act          TEXT NOT NULL,              -- 'goal.archive'
    plane        TEXT NOT NULL CHECK (plane IN ('nightly','consult')),
    thread_id    INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    target_kind  TEXT NOT NULL,              -- 'goal'
    target_id    TEXT NOT NULL,
    summary      TEXT NOT NULL,              -- one Ian-facing sentence
    inverse_json TEXT NOT NULL,              -- everything undo needs
    undone_at    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX idx_agent_acts_created ON agent_acts(created_at DESC);
```

- `POST /api/acts/{id}/undo` applies `inverse_json` through the same code path
  that made the change, and stamps `undone_at`. Undo is available forever; the
  UI surfaces the last 24 hours.
- Command shows a **Receipts** strip when acts exist in the last 24h:
  *"Dumbledore archived 'Audit calls per day' — 22 days past deadline. Undo."*
- Every act also writes an `ian`-visible memo, so the blackboard records it.

> **Law A5 — An act Ian cannot see did not happen.**
> A Ring 1 act with no receipt row is a bug, and the write helper raises rather
> than proceeding if the receipt insert fails. Receipt and act share one
> transaction.

---

## 5. Memory: the ledger and the index

### 5.1 The problem being fixed

`facts` is simultaneously the assertion store and the recall store, is written
by a model, is born `verified=1`, and is read as ground truth. Six of its 17
rows are fabricated. A P3 siren has run on it for nine days.

> **Law A6 — Retrieval informs; the ledger asserts.**
> An agent may *read* anything the index returns. An agent may only *claim*
> something that traces to a ledger row or to a live tool read in this run.
> The two stores are separate tables with separate write paths, and only one of
> them is writable by a model.

### 5.2 The ledger

`facts` stays, hardened:

1. **`upsert_fact(..., verified: int = 0)`.** Flip the default. This alone
   would have prevented six fabricated dates from arming two tripwires.
2. `write_fact` requires `source_memo_ids` (already true) **and** at least one
   `evidence` reference resolvable against a real row — the same server-side
   resolution `create_proposal` already does for proposal evidence.
3. `read_facts` output carries `verified` prominently, and `SHARED_RULES`
   gains: *an unverified fact may be mentioned, but may never justify a
   priority 2 or 3 memo, a proposal, or a Ring 1 act.*
4. Enforced in code, not prose: `write_memo` rejects `priority >= 2` unless the
   run recorded a ledger citation or a live tool read.
5. **No more `domain='all'` facts.** The archivist was the only writer that
   could, and it is retired. Existing `all` rows are migrated to their
   `domain_for_topic()` home.
6. Migration: the six `SEEDED PLACEHOLDER` rows are set `verified=0` and
   surfaced on the Memory page as *"Needs your answer"*. A fabricated verified
   date is worse than no date.

### 5.3 The archivist becomes a function

Distillation moves from a weekly Haiku run to `core/ledger.py`, called at the
end of every nightly sequence:

- Promote a fact **only** when a deterministic extractor recognizes it: a date
  from `calendar_events` or `school_items`, a balance from
  `financial_accounts`, a decision from a `decide_proposal` memo, a completed
  goal. Pattern-matched in Python, never inferred by a model.
- Everything else stays a memo and remains searchable via §5.4 — recall,
  not fact.

This is the flywheel's actual fix: **no model may write history.**

### 5.4 The index

Two stages, both local, both $0. Verified on this machine: SQLite 3.50.4 with
FTS5 compiled in; `enable_load_extension` unavailable, so no `sqlite-vec`.

**Stage 1 — Lexical (ships first, zero new dependencies).**

```sql
CREATE VIRTUAL TABLE memory_fts USING fts5(
    body, topic, kind UNINDEXED, source_table UNINDEXED,
    source_id UNINDEXED, occurred_at UNINDEXED,
    tokenize = 'porter unicode61'
);
```

Populated from `memos`, `briefs`, `notes`, `facts`, `school_note_sessions`
(plain-text projection), `proposals`. BM25-ranked, recency-decayed, scoped by
domain exactly as `read_facts` is.

**Stage 2 — Semantic (an enhancement, behind a capability check).**

- `model2vec` static embeddings (pure numpy + tokenizers; **no torch**, which
  has no reliable Python 3.14 wheels). ~30 MB, on-device.
- Vectors stored as `BLOB` in `memory_vectors(chunk_id, dim, vec)`; cosine
  brute-forced in numpy. At the real corpus size — ~1,400 memos, ~10k chunks
  after everything — a 10k x 256 matmul is single-digit milliseconds.
- Guarded exactly like `caldav` in `sync_icloud.py`: lazy import, and if the
  model or numpy is unavailable, `search_memory()` returns Stage 1 results and
  logs one line. **The feature must work with Stage 1 alone.**

**The tool.**

```python
@tool("search_memory",
      "Search ianOS history for context. Results are RECALL, not fact: "
      "they may inform your thinking and may never ground a claim.",
      {"query": str, "days": int, "limit": int})
```

Every result carries `source_table`, `source_id`, `occurred_at`, and an
explicit `"grounding": "recall_only"` marker. Granted to all ten roles in both
planes.

### 5.5 Never indexed

> **Law A7 — The index inherits every wall.**

| Never indexed | Authority |
|---|---|
| `journal_entries`, `data/journal/**` | SPEC-v8 / v11 |
| `health_daily`, `health_insights`, health-role memos | SPEC-v35 |
| `school_note_assets`, `data/school/**` | SPEC-v36 |
| `.env`, any credential | — |
| `leads` beyond name and stage | SPEC-v9 |

A sentinel test asserts each, mirroring `tests/test_journal.py`'s existing
privacy assertions. The indexer takes an explicit table allowlist; a new table
is invisible to it until someone adds it deliberately.

---

## 6. No dates in prompts

> **Law A8 — A role file carries policy. The run carries facts.**
> No date, quota, deadline or dollar figure may appear in `agents/roles/*.md`
> or `agents/dossier.md`. They are injected at run time from the tables Ian
> can edit.

### 6.1 The situation block

One function, `core/situation.py::current_situation(conn, now)`, prepended to
every prompt in both planes:

```
CURRENT SITUATION (computed, 2026-08-31 Monday)
Season: TERM (week 2 of 16; UIUC fall, ends 2026-12-17)
Capacity: ~5 hrs/week for Clockwork this season
Hero goal: Portfolio net worth $2,115.16 / $15,000 (14%)
Nearest real deadlines: FIN 180 panel Sep 2 (2d) · SPAN 210 AM&MP 1 Sep 2 (2d)
Live quotas: none active this season (audit/follow-up/demo paused 2026-08-31)
Expired, undecided: goal 1 "Sign Clockwork client #1" -16d
Open proposals: 0 · Ring 1 acts last 24h: 0
```

The last two lines are the fix for the dead loop: every producer now sees the
proposal ledger it is told to check, not just the chief.

### 6.2 Seasons

`goals` gains `season TEXT NOT NULL DEFAULT 'always'` (`always|term|break`).
Role frontmatter gains `seasons: term,break`. The dispatcher skips an
out-of-season role with reason `"out of season (term)"` — deterministic Python,
$0, same shape as the existing tripwires.

Season is derived from `school_items` term bounds, not hardcoded. It is what
would have caught the whole R1 failure on Aug 24 by itself.

### 6.3 Expired goals wake someone

New dispatcher tripwire on `watchdog`:

```python
def expired_goal_needing_verdict(days: int = 14):
    """A goal whose deadline lapsed and which nobody has ruled on."""
```

Fires at 14 days. Dumbledore then either archives it (Ring 1, if it qualifies
under §4.2) or proposes a `goal_change` (Ring 2). Either way it stops being a
permanently red number.

> **Law A9 — No goal stays overdue and undecided.**
> An unarchived goal more than 14 days past its deadline is a bug in the
> system, not a failure of Ian's. `tests/test_goals.py` asserts the tripwire
> fires with a frozen clock at both edges of the window.

### 6.4 The test that catches this class of bug

```python
def test_no_expired_dates_in_prompts():
    """A role file or the dossier naming a date in the past is a defect."""
```

Scans `agents/roles/*.md` and `agents/dossier.md` for ISO dates and
month-day strings, with the clock frozen so the assertion can actually fail.
This is the guard the audit's largest finding had no equivalent of.

---

## 7. The consult surface

### 7.1 Where it lives

Chat leaves the shell overlay and becomes part of the Command page, without
losing the single-mount lifecycle SPEC-v29 moved it for.

**The mechanism:** `AgentChat` keeps its one mount in `App.jsx`. `CommandPage`
renders `<div ref={dockRef} className="consult-dock-slot" />`, and `AgentChat`
`createPortal`s its panel into that node when it exists. Lifecycle stays in the
shell; DOM position is inline. When Command is not the active page, the portal
target is absent and the panel renders into its own fixed container.

> **Law A10 — Position is a portal; lifecycle is a mount.**
> The thread must survive a tab switch. Any change that re-parents `AgentChat`
> into a page's conditional render re-introduces the exact bug v29 fixed.

### 7.2 Three states

| State | Desktop | Mobile |
|---|---|---|
| **Dock** (default) | Inline under the Order, in the Command grid. Composer plus last exchange. Does not take over. | Inline card under the Order; tapping the composer expands. |
| **Expanded** | Column grows to `--content-w`; page scrolls behind. | Bottom sheet at 85dvh via the `Sheet` primitive. |
| **Full screen** | `#consult` overlays the shell; Escape returns. | Full-height; the tab bar hides via `body.sheet-open`. |

State is per-session in `sessionStorage`, never a route, so a reload lands on
Command with the thread intact.

### 7.3 What the dock replaces

The Ask sheet, inspect mode and rooms are deleted:

- `agents/runner.py`: `run_interactive_role`, `_interactive_system_prompt`,
  `_interactive_user_prompt`, `INTERACTIVE_MISSIONS`, `INTERACTIVE_SHARED_RULES`,
  `run_room_synthesis`
- `api/main.py`: `/api/agent-invocations`, `/api/agent-commands`,
  `/api/agent-rooms`
- `dashboard/src/components/AskAgentSheet.jsx`, `lib/agentInvocations.js`

`agent_invocations` the **table** stays — chat rides on it. Roster "Ask
Dwight" opens a chat thread. Inspect survives as a *seeded first message*:
opening a consult from an account or a lead prefills the precomputed record
context. It was always context, not a mode.

### 7.4 Real conversation memory

Today `_prior_turn_prompt_rows` returns only the agent's own replies —
**Ian's questions are never in the history** — truncated to 400 characters
each, 1,600 total, from 12 rows the DB fetched and 4 the prompt used.

Replace the whole mechanism with the SDK's native session continuity:

- Store `chat_threads.sdk_session_id`.
- First turn: capture the session id from the SDK.
- Later turns: `ClaudeAgentOptions(resume=session_id, fork_session=False)`.

The model gets the actual conversation, both sides, with the SDK managing
compaction. `CHAT_PRIOR_*` constants and `_chat_prior_block` are deleted.
Fallback: if resume fails, rebuild from stored turns **including the user
side**, at 12 turns and 4,000 characters.

### 7.5 Live state that earns the persona

Fury's persona claims "You see the whole board" and `_live_state_lines` hands
over five lines. Widen it — pure Python, cheap, and it is what makes an agent
feel present:

Day Command and whether it is still the live anchor · today's Order plus the
next three items · hero goal and status · nearest three deadlines with days
remaining · school items due this week · gym state · checking, net worth,
burn against the active cap · open proposals · Ring 1 acts in the last 24h ·
season and capacity.

Still read-only. `gym_streak_state()` remains forbidden here — it writes.

---

## 8. Runner and ops hardening

### 8.1 Get the runner out of the web process

Today `/api/agents/run` calls `subprocess.run` on a daemon thread inside
uvicorn, `check=False`, output uncaptured. When uvicorn restarted at 10:11 on
Aug 31 it killed the chief mid-run: four memos, $0.32 spent, no brief, no
error, no memo, and a dashboard still showing the previous day.

```python
subprocess.Popen(
    [sys.executable, str(ROOT/"agents"/"runner.py")],
    cwd=str(ROOT), start_new_session=True,          # survives a server restart
    stdout=log_fh, stderr=subprocess.STDOUT,        # data/nightly.log
)
```

Poll for exit in the thread; on non-zero, write a `system` memo — the
role-crash precedent. `run_started`/`run_finished` land in `agent_acts` so
Command can show *"Agents running… 4 of 10"* instead of a hopeful toast.

### 8.2 The brief is for the day it governs

A brief written at 21:30 is *tomorrow's*. Stamping it with the night it ran
makes `briefIsToday` false from midnight to 21:30, so the amber **stale** chip
renders essentially every waking hour — and gates SPEC-v32's live rewrite,
which has fired **zero times across all 24 briefs**.

- `briefs.governs_date` (new) = the day the Day Command is for.
- `briefIsToday` compares `governs_date`. The stale chip appears only when the
  brief genuinely predates today.
- `/api/order/refresh` drops the `kind === 'daily'` gate, which also made every
  Monday dead because Sunday writes a weekly.

### 8.3 The voice law reaches the brief

`strip_em_dashes()` runs on chat replies only. Ten of 24 Day Commands contain
an em dash. Apply it inside `write_brief` to both `body` and `day_command`, and
assert it in `tests/test_briefs.py`.

### 8.4 Money the CFO can actually see

`financial_accounts` appears nowhere in `runner.py`. The CFO sees checking and
nothing else — not $375.10 savings, neither credit card, no limits, no net
worth — and computes runway from `SUM(amount)` over every transaction since
May, seeded demo rows included. It produced "~$81 months of runway" on
two small balances.

1. **`read_accounts`** — institution, name, type, mask, balance, limit,
   `as_of`, plus computed net worth. Allowlisted to `cfo`, `wealth`, `chief`;
   added to the chat `money` chip.
2. `cash_position` becomes a rolling 30-day net flow over the real account set.
3. `finance_state` takes checking freshness from the source that produced the
   balance, not from `simplefin_chase` — replaced by Plaid and permanently
   `disabled`, so the label is meaningless today.
4. **A refresh control on the Money hero**, wired to the existing per-item sync
   endpoints with a 120s cooldown. Today the sync endpoint is only ever called
   right after connecting an account, so a number that looks old at 4pm cannot
   be pulled. Show `as_of` beside the number.
5. Delete the `source='seed'` holdings row (2026-07-21, $7,420) — a cliff to
   $1,742 in any history view.
6. A finance source that fails writes a `system` memo, so the Aug 30 SnapTrade
   `failed (protocol)` drop-out (4 of 9 accounts snapshotted) is visible.

### 8.5 Number discipline

`write_memo` gains a numeric check: a figure formatted as currency or as a
multiple that the run did not record via `_record_chat_number` is flagged.
Ships as a warning line in `nightly.log`; promoted to rejection once the
false-positive rate is known. Guardrails belong in code, and this is the one
the audit found missing.

### 8.6 Health consent has a front door

`health_ai_prefs` is empty, so `physician` and `coach` have been skipped every
night since Aug 26 with `"health sharing off"` and nothing has ever asked. The
wall is right; the silence is not.

- Body page: a one-time card explaining exactly what leaves the Mac and what
  does not, with Turn on / Not now. `PATCH /api/health/ai-consent` exists.
- The Roster shows *"off — health sharing"* on both cards rather than a stale
  "spoke 6 days ago".
- The brief gains an inert dispatcher line: *"5 of 10 woke; 2 off; 3 out of
  season."*

### 8.7 Archivist's dead instruction

`build_user_prompt` tells the archivist *"Memo count > 100: run compact_memos"*
(count: 1,335) while `agent_allowlist` strips the tool and the tool returns an
error unconditionally. With the archivist retired, delete the instruction, and
move compaction into `core/ledger.py` where it can run in code.

### 8.8 Roster arithmetic

`role_stats` does `s["made"] += r["n"]` across every status, so `made` includes
EXPIRED — the exact leak its own docstring says it prevents. Watchdog reads
"31 proposed" when 13 simply lapsed. Sum `approved + rejected + pending` only.

### 8.9 Backups

launchd has been exiting 126 since at least Aug 25:
`/bin/bash: scripts/backup.sh: Operation not permitted` — macOS TCC blocking
launchd from the Desktop folder. SPEC-v16's failure memo cannot fire because
the script never starts. Move the repo off `~/Desktop`, or grant Full Disk
Access to `/bin/bash`. Add a `startup_check()` that writes a `system` memo when
the last successful backup is more than 48 hours old — a scheduled job that can
fail before it runs needs a watcher that is not itself the job.

---

## 9. Execution and cost

### 9.1 Subscription only, and enforced

> **Law A11 — ianOS runs on Ian's Claude subscription, through the local CLI.**
> `CLAUDE_CODE_OAUTH_TOKEN` via `find_cli()`. If it is absent, the run fails
> with a `system` memo. `ANTHROPIC_API_KEY` is **explicitly unset** in the
> options `env` for every run, so no code path can silently fall back to
> metered billing.

### 9.2 Stop printing dollars

`agent_invocations.cost_usd` is an SDK estimate, not a charge, and showing it
per turn makes a subscription look metered. Keep the column for budget
enforcement; remove it from every rendered surface.

### 9.3 Real ceilings

Estimates were never the guardrail. Use the SDK's:

- Plane A: `max_budget_usd` per role, `task_budget` for the sequence.
- Plane B: `max_budget_usd` per turn.
- Exceeded is a clean, logged failure, not a silent overrun.

### 9.4 Models and effort

| Plane | Role | Model | Effort |
|---|---|---|---|
| A | producers | Haiku | low |
| A | chief, daily brief | Haiku | medium |
| A | chief, Sunday deep brief | Sonnet | high |
| B | Alfred and specialists | thread setting, default Sonnet | thread setting, default high |
| B | Fury all-hands | Sonnet parent, Haiku subagents | high / low |

`xhigh` stays deliberately absent — it falls back silently on most models
(SPEC-v26).

---

## 10. Schema changes

```sql
-- Ring 1 receipts (§4.5)
CREATE TABLE agent_acts (...);                    -- as above

-- Season model (§6.2)
ALTER TABLE goals ADD COLUMN season TEXT NOT NULL DEFAULT 'always';

-- Brief semantics (§8.2)
ALTER TABLE briefs ADD COLUMN governs_date TEXT NOT NULL DEFAULT '';

-- Native session continuity (§7.4)
ALTER TABLE chat_threads ADD COLUMN sdk_session_id TEXT NOT NULL DEFAULT '';

-- Default agent (§3.5)
ALTER TABLE chat_prefs ADD COLUMN default_role TEXT NOT NULL DEFAULT 'steward';

-- Memory index (§5.4)
CREATE VIRTUAL TABLE memory_fts USING fts5(...);  -- as above
CREATE TABLE memory_chunks  (id INTEGER PRIMARY KEY, source_table TEXT NOT NULL,
                             source_id TEXT NOT NULL, chunk_index INTEGER NOT NULL,
                             body TEXT NOT NULL, occurred_at TEXT,
                             UNIQUE(source_table, source_id, chunk_index));
CREATE TABLE memory_vectors (chunk_id INTEGER PRIMARY KEY
                               REFERENCES memory_chunks(id) ON DELETE CASCADE,
                             dim INTEGER NOT NULL, vec BLOB NOT NULL);
```

`chat_threads` has a `CHECK` on `model`. SQLite cannot `ALTER` a constraint, so
any widening needs a table rebuild — and **a rebuild must carry every ALTERed
column** or it drops the one it was meant to preserve (SPEC-v26's recorded
trap). Adding `sdk_session_id` needs no rebuild; do not combine it with one.

Backups: `agent_acts` and `memory_*` live in `data/ianos.db`, already claimed
by `scripts/backup.sh` via `VACUUM INTO`. `data/consult/out/` is new and must be
added to the restic include list.

---

## 11. Phases

Each phase ships independently and leaves the system working.

### Phase 1 — Stop the bleeding (~1 day)
§8.1 runner out of the web process · §8.2 brief date semantics and the stale
chip · §8.3 em dashes in briefs · §8.8 roster arithmetic · §8.9 backups.
**After Phase 1:** the Order stops lying about its own freshness, a run cannot
die silently, and the backup is real.

### Phase 2 — Give the agents a verb (~2 days)
§4 all three rings, `core/acts.py`, `agent_acts`, undo endpoint, Receipts strip
· §6.1 situation block including the proposal ledger for every producer ·
§6.3 expired-goal tripwire · §4.3 the two new proposal kinds.
**After Phase 2:** the APPROVE loop is alive and the four expired goals get a
verdict this week.

### Phase 3 — The roster (~2 days)
§3 renames, the Dumbledore merge, four retirements, Alfred as default ·
§6 date-free role files, seasons, `test_no_expired_dates_in_prompts`.
**After Phase 3:** ten agents with mandates computed from tables.

### Phase 4 — Memory (~3 days)
§5.2 ledger hardening and the `verified=0` migration · §5.3 archivist becomes
`core/ledger.py` · §5.4 Stage 1 FTS5 and `search_memory` · §5.5 privacy
sentinels. Stage 2 vectors are a separate, optional follow-on.
**After Phase 4:** the flywheel is broken and agents can find their own history.

### Phase 5 — The consult surface (~3 days)
§2 the two planes, `consult_gate`, capability chips · §7.1 the portal dock ·
§7.2 three states · §7.3 delete Ask, inspect, rooms · §7.4 native session
resume · §7.5 wide live state · §3.6 Fury via SDK subagents.
**After Phase 5:** one consult surface, on Command, that remembers and can act.

### Phase 6 — Money and health (~1 day)
§8.4 `read_accounts`, refresh control, freshness source, seed row ·
§8.6 health consent card and the dispatcher line.

**Order matters.** Phase 2 before Phase 3: give the agents the verb before you
rewrite what they are told to do, or the new prompts inherit the old
helplessness. Phase 4 before Phase 5: Plane B is far more useful with a
searchable history behind it.

---

## 12. Laws this spec asserts in tests

The audit's finding was that 870 tests proved every wall held and none proved
any claim was true. These close that gap.

| Test | Asserts |
|---|---|
| `test_no_expired_dates_in_prompts` | No role file or dossier names a past date. Clock frozen. (§6.4) |
| `test_expired_goal_wakes_watchdog` | The 14-day tripwire fires; both window edges pinned. (§6.3) |
| `test_producers_see_pending_ledger` | Every producer's prompt contains the open-proposal list. (§6.1) |
| `test_ring1_act_writes_receipt` | An act with a failed receipt insert rolls back entirely. (§4.5) |
| `test_ring1_act_is_reversible` | Every act type's inverse restores the prior row exactly. (§4.2) |
| `test_ring1_cannot_touch_forbidden` | No act path reaches money, leads, journal, health or `verified=1`. (§4.2) |
| `test_consult_gate_denies_connector_writes` | Every name in `CONNECTOR_WRITE_TOOLS` is denied. (§2.6) |
| `test_consult_gate_denies_secret_reads` | `.env`, journal, school assets and the DB file are unreadable. (§2.5) |
| `test_consult_gate_write_is_workspace_only` | `Write`/`Edit` outside `data/consult/` is denied. (§2.4) |
| `test_plane_a_has_no_builtin_tools` | Nightly options carry `tools=[]` and `setting_sources=[]`. (§2.1) |
| `test_index_excludes_private_stores` | Journal, health and school assets never enter `memory_fts`. (§5.5) |
| `test_search_memory_marks_recall_only` | Every result carries `grounding: "recall_only"`. (§5.4) |
| `test_unverified_fact_cannot_ground_p3` | A P2/P3 memo without a ledger citation is rejected. (§5.2) |
| `test_fact_default_is_unverified` | `upsert_fact` defaults to `verified=0`. (§5.2) |
| `test_brief_has_no_em_dash` | `write_brief` strips them from body and day command. (§8.3) |
| `test_brief_governs_date` | A 21:30 brief governs tomorrow; the stale chip stays off. (§8.2) |
| `test_no_api_key_fallback` | `ANTHROPIC_API_KEY` is unset in options `env`. (§9.1) |
| `test_retired_roles_still_load` | `load_role` resolves every retired id so history renders. (§3.4) |

> **Law A12 — A guardrail test that cannot fail proves nothing.**
> Freeze the clock and pin both edges of every window. `term_active` was
> `today >= START` with no end date, so it could never go false and its test
> could never fail. That is the shape of the bug this spec exists to prevent.

---

## 13. Non-goals

- **The Line stays read-only.** No agent in any plane sets a stage, logs a
  touch or opens a run. SPEC-v9's ordering guarantee is the feature.
- **No agent sends anything.** Not mail, not messages, not a demo confirmation.
  Plane B reads connectors; it never writes to them.
- **The journal wall does not move.** No tool, no index, no plane.
- **Health stays behind SPEC-v35.** v37 adds a consent prompt and nothing else.
- **No cloud vector database, no embeddings API, no paid retrieval.** Ian is
  pre-revenue. Everything in §5 runs on the Mac at $0.
- **The dashboard does not gain conversion analytics.** A win-rate chart cannot
  change the next call.
- **Ring 1 does not grow by convenience.** New acts require a spec amendment,
  a reversibility proof, and a test.

---

## 14. Open question for Ian

**Should Ring 1 archival of an expired goal be silent or announced?**

§4.2 lets Dumbledore archive a goal 14+ days past its deadline, receipted and
undoable. Two defensible designs:

- **Silent and receipted** — it just happens; the Receipts strip records it;
  Ian notices only if he looks. Lowest friction, closest to "no shame."
- **Announced in the brief** — *"I retired 'Audit calls per day', 22 days past.
  Undo if that was wrong."* One line, once. More honest, slightly more nagging.

This spec assumes **announced**, because an agent quietly deleting a goal Ian
set is the one Ring 1 act that could feel like a betrayal rather than a
service. Say the word and it becomes silent.
