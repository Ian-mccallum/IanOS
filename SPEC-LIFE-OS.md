# ianOS Life OS. Implementation Specification

**Version:** 1.1  
**Status:** Ready for implementation  
**Audience:** AI coder / implementer  
**Scope:** Transform ianOS from a Clockwork GTM command center into a full-life personal operating system while preserving every existing principle in `PRODUCT.md`.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [North Star & Non-Negotiables](#2-north-star--non-negotiables)
3. [Functional Requirements](#3-functional-requirements)
4. [System Architecture](#4-system-architecture)
5. [Data Model](#5-data-model)
6. [Domain Model](#6-domain-model)
7. [Goal Actuals Engine](#7-goal-actuals-engine)
8. [Agent System](#8-agent-system)
9. [Ingest Pipelines](#9-ingest-pipelines)
10. [Chief Brief & Day Command](#10-chief-brief--day-command)
11. [Focus Allocation](#11-focus-allocation)
12. [API Specification](#12-api-specification)
13. [Dashboard Specification](#13-dashboard-specification)
14. [Security & Privacy](#14-security--privacy)
15. [Implementation Phases](#15-implementation-phases)
16. [File Change Map](#16-file-change-map)
17. [Acceptance Criteria](#17-acceptance-criteria)
18. [Testing Strategy](#18-testing-strategy)
19. [Seed Data](#19-seed-data)
20. [Financial Integrations. Chase + Fidelity](#20-financial-integrations--chase--fidelity)

---

## 1. Executive Summary

### What we're building

ianOS becomes Ian's **personal operating system**: a local-first mission control that tracks goals across **business**, **health**, **personal**, and **finance** domains. AI agents run nightly, watch domain-specific goals, write to a shared blackboard, file proposals, and the chief composes a daily brief plus a **Day Command**, one sentence that orchestrates tomorrow.

Ian is CEO. Agents are staff. The dashboard is the boardroom. Nothing executes without Ian pressing APPROVE.

### What already exists (do not rebuild)

| Component | Location | Keep |
|-----------|----------|------|
| SQLite blackboard architecture | `core/db.py` | ✓ extend |
| Agent runner + MCP tools | `agents/runner.py` | ✓ extend |
| FastAPI dashboard API | `api/main.py` | ✓ extend |
| React mission-control UI | `dashboard/src/App.jsx` | ✓ refactor |
| Bank CSV ingest | `ingest/import_csv.py` | ✓ pattern-reuse |
| Activity CLI logging | `ingest/log_activity.py` | ✓ extend |
| Proposal approve/reject loop | `api/main.py`, `core/db.py` | ✓ extend |
| PRODUCT.md design principles | `PRODUCT.md` | ✓ sacred |

### The four rhythms

| Rhythm | Mechanism | Purpose |
|--------|-----------|---------|
| **Daily** | Brief + Day Command + proposals + quick-log + `make sync-finance` | Tactical, act today; cash + portfolio current |
| **Weekly** | Focus allocation (Sunday) + deep brief | Strategic: what domains matter this week |
| **Monthly** | CSV/batch ingest (health, calendar) | Deep scan, passive data refresh |
| **Fallback** | `make import` / `make import-fidelity` | Manual CSV when APIs fail |

---

## 2. North Star & Non-Negotiables

### North star

> Ian opens ianOS twice a day, knows exactly where his life stands, acts on the brief, and never maintains more than one tool.

### Non-negotiables (from PRODUCT.md, do not violate)

1. **Numbers are the interface.** Hero metrics first. Chrome serves data.
2. **Urgency is earned, not styled.** Red only when actually breached.
3. **Two-minute sessions.** Every daily action reachable without navigation.
4. **Agents are characters.** Consistent role colors and voice.
5. **Instrumentation, not decoration.** Motion/glow only for state change.
6. **Agents read, memo, propose. Never execute.** Human-in-the-loop only.
7. **Every number traces to a table row.** No LLM-estimated figures.
8. **Local-first.** SQLite on disk. No cloud. No auth (single user, localhost).
9. **AI cost target:** ≤$10/mo total (Haiku for domain agents, Sonnet for chief weekly + focus allocation only).
10. **Integration cost target:** ≤$2/mo for live financial sync (SimpleFIN $1.50 + SnapTrade $0).

### Kill criteria (built into chief's logic)

- If a domain has no data ingested/logged for 14+ days → chief flags `NO DATA, log it` for that domain's goals; never guesses.
- If brief read time would exceed ~3 minutes → chief compresses; weekly deep brief holds retrospectives.
- Business domain remains **default hero** during Clockwork GTM phase (Aug 2026 client deadline).

---

## 3. Functional Requirements

### FR-1: Multi-domain goals

- Goals belong to exactly one domain: `business` | `health` | `personal` | `finance`.
- Goals retain existing kinds: `goal` | `quota` | `deadline`.
- Goals can declare optional `metric_key` linking them to computed actuals (replaces hardcoded name matching in `goal_actuals()`).
- Goals can declare optional `depends_on_goal_id` for cross-domain dependency tracking.
- Goals can be marked `hero: true`, at most one hero per domain; business hero always visible in topbar.

### FR-2: Domain-specialized agents

Eight active agents in nightly sequence (order matters):

```
scout → cfo → physician → steward → watchdog → counsel → infra → archivist → chief
```

Each agent has a markdown role file, tool allowlist, and domain mandate. Inactive v2 stubs become active.

### FR-3: Passive ingest

- Apple Health export → `health_daily` table (sleep, steps, workouts).
- Google Calendar .ics export → `calendar_events` table (time allocation audit).
- Manual wellness log via dashboard quick-add and CLI.

### FR-3b: Live financial sync (Ian-specific)

Ian uses **Chase for checking** and **Fidelity for stocks**. ianOS syncs both via API:

| Institution | Account type | Integration | Cost |
|-------------|--------------|-------------|------|
| **Chase** | Checking (transactions, balance) | **SimpleFIN Bridge** | $1.50/mo |
| **Fidelity** | Brokerage (holdings, portfolio value) | **SnapTrade** (Fidelity Access OAuth) | $0 (free tier) |

- Chase transactions land in existing `transactions` table (`source = 'simplefin'`).
- Fidelity positions land in new `holdings` table (`source = 'snaptrade'`).
- CSV import remains as fallback for both (`make import`, `make import-fidelity`).
- Sync runs via `make sync-finance` (both) or individually; optional nightly pre-agent hook.
- Credentials live in `.env` only, never in SQLite, never committed.
- Agents read synced data via existing CFO tools, no agent network access to SimpleFIN/SnapTrade.

### FR-4: Cross-domain synthesis

- Chief brief includes a **Tradeoffs** section when cross-domain conflicts exist.
- Precomputed tradeoff hints injected into chief's run prompt (Python-derived, not LLM-guessed).

### FR-5: Weekly focus allocation

- `focus_allocations` table stores which domains + hero goals are active each week.
- Sunday weekly brief includes focus selection for the coming week.
- Weekdays: dashboard emphasizes focused domains; watchdog still monitors all deadlines.

### FR-6: Day Command

- `briefs` table gains `day_command TEXT` column.
- Chief writes one imperative sentence at top of brief.
- Dashboard renders Day Command as the first element above brief body, largest text on screen after hero metrics.

### FR-7: Expanded proposals

- Proposal `kind` expands: `money` | `task` | `legal` | `health` | `personal`.
- Domain-colored proposal tags in UI.
- Approval decisions continue writing memos to blackboard.

### FR-8: Dashboard domain zones

- Single page, no route navigation.
- Goals panel splits into collapsible domain zones.
- Quick-log expands: business activity + wellness one-tap (energy 1-5, sleep hours, workout yes/no).
- Agent lights show all 8 agents.

---

## 4. System Architecture

### High-level diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           IAN (human)                                   │
│         reads brief · approves proposals · quick-logs · edits goals     │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │   Dashboard (React/Vite)  │
                    │   localhost:5173          │
                    └─────────────┬─────────────┘
                                  │ GET /api/state (15s poll)
                                  │ POST decisions, goals, logs
                    ┌─────────────▼─────────────┐
                    │   API (FastAPI)           │
                    │   localhost:8787          │
                    └─────────────┬─────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
┌─────────▼─────────┐  ┌────────▼────────┐  ┌──────────▼──────────┐
│  core/db.py        │  │ agents/runner.py │  │ ingest/*.py         │
│  SQLite (WAL)      │  │ nightly sequence │  │ CSV, health, cal    │
│  data/ianos.db     │  │ Claude Agent SDK │  │ CLI quick-log       │
└────────────────────┘  └──────────────────┘  └─────────────────────┘
```

### Data flow principles

1. **Agents never call API.** They read/write SQLite via MCP tools only.
2. **API never triggers agents.** `make run` or launchd executes the sequence.
3. **Ingest scripts never call agents.** They write tables; agents read on next run.
4. **Actuals are computed in Python** (`core/metrics.py`), not by LLMs.
5. **Migrations run on connect.** `db.connect()` applies additive schema changes idempotently.

### New module: `core/metrics.py`

Centralize all goal actual resolution. Replace the hardcoded `if "burn" in name` logic in `api/main.py`. Both API and agent tools import from here.

```python
# core/metrics.py, responsibility
resolve_goal_actuals(conn, goals: list[dict]) -> list[dict]
compute_tradeoff_hints(conn) -> list[dict]
compute_focus_status(conn) -> dict
stale_data_domains(conn) -> list[str]
```

---

## 5. Data Model

### Migration strategy

Add `MIGRATIONS` list to `core/db.py`. Run after `SCHEMA` in `connect()`. Each migration is idempotent (`ALTER TABLE` guarded by column-exists check, or `CREATE TABLE IF NOT EXISTS`).

### 5.1 Modified tables

#### `goals`: add columns

```sql
ALTER TABLE goals ADD COLUMN domain TEXT NOT NULL DEFAULT 'business'
  CHECK (domain IN ('business', 'health', 'personal', 'finance'));
ALTER TABLE goals ADD COLUMN metric_key TEXT NOT NULL DEFAULT '';
ALTER TABLE goals ADD COLUMN depends_on_goal_id INTEGER REFERENCES goals(id);
ALTER TABLE goals ADD COLUMN hero INTEGER NOT NULL DEFAULT 0;  -- boolean 0/1
ALTER TABLE goals ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;  -- sort order within domain
```

**Backfill existing seed goals:**
- All current goals → `domain = 'business'`
- "Sign Clockwork client #1" → `hero = 1`, `metric_key = 'clients_signed'`
- "Monthly burn under cap" → `metric_key = 'burn_this_month'`
- "Audit calls per day" → `metric_key = 'audit_calls_today'`
- "Follow-ups per day" → `metric_key = 'follow_ups_today'`
- "Demos held per week" → `metric_key = 'demos_last_7d'`
- Deadline chain goals → `metric_key = ''` (use `current_value` + `deadline`)

#### `briefs`: add column

```sql
ALTER TABLE briefs ADD COLUMN day_command TEXT NOT NULL DEFAULT '';
```

#### `proposals`: expand kind CHECK

SQLite cannot alter CHECK constraints in place. Migration approach:

1. Create `proposals_new` with expanded kind.
2. Copy data.
3. Drop old, rename new.

```sql
-- kind expands to: money | task | legal | health | personal
```

### 5.2 New tables

#### `health_daily`

```sql
CREATE TABLE IF NOT EXISTS health_daily (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL UNIQUE,           -- YYYY-MM-DD
    sleep_hours  REAL,                           -- nullable
    steps        INTEGER,
    workouts     INTEGER NOT NULL DEFAULT 0,     -- count
    workout_mins INTEGER NOT NULL DEFAULT 0,
    energy       INTEGER CHECK (energy IS NULL OR (energy BETWEEN 1 AND 5)),
    weight_lbs   REAL,
    notes        TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'manual'  -- manual | apple_health
);
```

#### `calendar_events`

```sql
CREATE TABLE IF NOT EXISTS calendar_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,                   -- YYYY-MM-DD (event start date)
    start_time  TEXT,                            -- HH:MM or null for all-day
    end_time    TEXT,
    summary     TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',        -- work | health | personal | other
    duration_min INTEGER,
    hash        TEXT UNIQUE                      -- dedup for re-import
);
CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(date);
```

#### `focus_allocations`

```sql
CREATE TABLE IF NOT EXISTS focus_allocations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT NOT NULL UNIQUE,            -- YYYY-MM-DD (Sunday)
    domains     TEXT NOT NULL,                   -- JSON array: ["business","health"]
    goal_ids    TEXT NOT NULL DEFAULT '[]',      -- JSON array of goal IDs
    rationale   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

#### `ingest_log`

Track when each data source was last refreshed. Chief uses this for stale-data flags.

```sql
CREATE TABLE IF NOT EXISTS ingest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL UNIQUE,
    -- bank_csv | simplefin_chase | snaptrade_fidelity | fidelity_csv
    -- apple_health | calendar | manual
    last_import TEXT,                            -- datetime
    row_count   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT NOT NULL DEFAULT ''
);
```

#### `holdings` (Fidelity / brokerage positions)

```sql
CREATE TABLE IF NOT EXISTS holdings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account      TEXT NOT NULL DEFAULT 'fidelity',
    symbol       TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    quantity     REAL NOT NULL,
    cost_basis   REAL,                           -- total cost basis, nullable
    market_value REAL NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'USD',
    as_of_date   TEXT NOT NULL,                  -- YYYY-MM-DD snapshot date
    source       TEXT NOT NULL DEFAULT 'snaptrade',  -- snaptrade | csv
    hash         TEXT UNIQUE,                    -- dedup key
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_holdings_as_of ON holdings(as_of_date);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
```

#### `transactions`: add column

```sql
ALTER TABLE transactions ADD COLUMN source TEXT NOT NULL DEFAULT 'csv';
-- csv | simplefin
```

Dedup for SimpleFIN: extend hash to include `source` + SimpleFIN transaction id if provided; never duplicate CSV rows on re-sync.

### 5.3 Metric key registry

Define in `core/metrics.py` as `METRIC_RESOLVERS: dict[str, Callable]`:

| metric_key | Source table(s) | Computation |
|------------|-----------------|-------------|
| `clients_signed` | goals.current_value | Parse int from current_value |
| `burn_this_month` | transactions | `burn_by_month` current month |
| `audit_calls_today` | activity | today's audit_calls |
| `follow_ups_today` | activity | today's follow_ups |
| `demos_last_7d` | activity | sum demos last 7 days |
| `sleep_last_night` | health_daily | yesterday or today row sleep_hours |
| `sleep_avg_7d` | health_daily | avg sleep_hours last 7 rows |
| `steps_today` | health_daily | today's steps |
| `workouts_this_week` | health_daily | sum workouts last 7 days |
| `energy_today` | health_daily | today's energy 1-5 |
| `work_hours_week` | calendar_events | sum duration_min where category=work, last 7d |
| `deep_work_hours_week` | calendar_events | sum where category=work AND duration_min >= 60 |
| `personal_hours_week` | calendar_events | sum where category=personal, last 7d |
| `portfolio_value` | holdings | sum market_value for latest as_of_date |
| `portfolio_day_change` | holdings | compare latest vs prior as_of_date total |
| `checking_balance` | transactions | latest SimpleFIN balance snapshot stored in ingest_log notes or derived |
| *(fallback)* | goals.current_value | current_value as-is |

If `metric_key` is empty, fall back to `current_value` display (deadlines, status goals).

---

## 6. Domain Model

### Domain definitions

| Domain | Color token | Default hero | Primary agents | Primary ingest |
|--------|-------------|--------------|----------------|----------------|
| `business` | `--good` (green) | Client #1 | scout, cfo, infra | activity log, bank CSV |
| `health` | `--health` (new: teal `#2dd4bf`) | Sleep avg | physician | Apple Health CSV, wellness quick-log |
| `personal` | `--personal` (new: violet `#a78bfa`) |: | steward | calendar .ics, manual |
| `finance` | `--warn` (amber) | Portfolio value | cfo | SimpleFIN (Chase) + SnapTrade (Fidelity) |

Add CSS variables in `dashboard/src/styles.css`:

```css
:root {
  --health: #2dd4bf;
  --personal: #a78bfa;
}
```

### Domain zone hierarchy (dashboard)

Within Goals panel, render zones in this order:

1. **BUSINESS**, always expanded. Hero metric (client #1) + burn + quotas + business deadlines.
2. **HEALTH**: hero: sleep avg or steps (whichever goal has `hero=1`).
3. **PERSONAL**, steward-tracked goals + personal deadlines.
4. **FINANCE**: portfolio hero (total market value) + checking balance strip. Fed by SnapTrade + SimpleFIN.

Each zone header shows:
- Domain name + color bar
- Domain status chip: `ON TRACK` | `AT RISK` | `OFF TRACK` | `NO DATA`
- Collapse toggle (business zone cannot collapse)

Domain status = worst status among goals in that domain with data; `NO DATA` if all goals in domain lack actuals for 14+ days.

---

## 7. Goal Actuals Engine

### File: `core/metrics.py`

```python
"""Deterministic goal actual resolution. Single source of truth for API + agents."""

from __future__ import annotations
from datetime import date, timedelta
from core import db

STALE_DAYS = 14

def resolve_goal_actuals(conn, goals: list[dict] | None = None) -> list[dict]:
    """Attach actual, actual_label, days_remaining, status to each goal."""
    ...

def goal_status(goal: dict) -> str:
    """Return ON_TRACK | AT_RISK | OFF_TRACK | NO_DATA."""
    ...

def domain_status(goals: list[dict], domain: str) -> str:
    """Aggregate status for a domain zone header."""
    ...

def compute_tradeoff_hints(conn) -> list[dict]:
    """Python-derived cross-domain conflict signals for chief prompt injection."""
    ...

def stale_data_domains(conn) -> list[str]:
    """Domains with no ingest/log activity in STALE_DAYS."""
    ...
```

### Status logic (deterministic)

| Kind | ON_TRACK | AT_RISK | OFF_TRACK | NO_DATA |
|------|----------|---------|-----------|---------|
| `goal` (numeric target) | actual ≥ 80% of target OR ahead of pace | 50-80% or pace slipping | < 50% with deadline < 14d | no actual source |
| `quota` | today/period ≥ target | ≥ 50% of target | < 50% | no activity rows in 7d |
| `deadline` | current_value indicates done OR > 14d remaining | 7-14d remaining, not done | < 7d remaining, not done |: |
| `goal` (burn cap) | burn ≤ cap | burn ≤ cap * 1.2 | burn > cap * 1.2 | no transactions imported |

### Tradeoff hints (precomputed for chief)

Implement these rules in `compute_tradeoff_hints()`:

```python
# Rule 1: Sleep debt → sales slump
if sleep_avg_7d < 6.5 and audit_calls_7d < 70% of quota:
    hint = "Sleep avg {sleep}h + calls at {pct}% of quota, cross-domain drag"

# Rule 2: Burn over cap → personal spend pressure
if burn_this_month > 150 and personal_hours_week > 20:
    hint = "Burn over cap while personal calendar hours high, check discretionary spend"

# Rule 3: Deadline chain risk
if any deadline < 7d and current_value not in DONE_STATES:
    hint = "{name} T-{d}d blocks downstream goals"

# Rule 4: Work hours vs quota
if work_hours_week > 50 and demos_last_7d < 3:
    hint = "{work}h worked but only {demos} demos, building over selling"
```

Return list of `{"rule": str, "hint": str, "severity": "warn"|"crit"}`.

---

## 8. Agent System

### 8.1 Nightly sequence

```python
SEQUENCE = [
    "scout",      # business sales
    "cfo",        # finance + burn
    "physician",  # health (NEW)
    "steward",    # personal admin (NEW)
    "watchdog",   # all deadlines cross-domain
    "counsel",    # legal docs (ACTIVATE v2)
    "infra",      # Railway/hosting (ACTIVATE v2)
    "archivist",  # memo compaction (ACTIVATE v2)
    "chief",      # synthesis + brief + day command
]
```

### 8.2 Tool registry

Add these MCP tools to `agents/runner.py`:

| Tool | Args | Returns | Description |
|------|------|---------|-------------|
| `read_holdings` | `days: int` | holdings rows + portfolio totals | Fidelity positions, latest snapshot + history |
| `read_health` | `days: int` | health_daily rows + 7d aggregates | sleep avg, steps avg, workout count |
| `read_calendar` | `days: int` | calendar_events + category totals | hours by category last N days |
| `read_focus` |: | current week's focus allocation | domains + goal_ids + rationale |
| `write_focus` | `domains: list, goal_ids: list, rationale: str` | ok | chief only, Sundays or `--weekly` |
| `read_documents` | `limit: int` | document metadata rows | counsel only (see 8.5) |
| `read_infra_status` |: | infra snapshot | infra only (see 8.6) |
| `compact_memos` | `before_days: int` | compaction summary | archivist only |

Existing tools unchanged: `read_goals`, `read_transactions`, `read_activity`, `read_memos`, `write_memo`, `create_proposal`, `write_brief`.

**Modify `write_brief` tool** to accept optional `day_command: str`. Store in `briefs.day_command`.

**Modify `read_goals` tool** to return goals with `domain`, `metric_key`, `status` (via metrics.py).

### 8.3 Allowlists

```python
ALLOWLISTS = {
    "scout":     {"read_goals", "read_activity", "read_memos", "read_focus",
                  "write_memo", "create_proposal"},
    "cfo":       {"read_goals", "read_transactions", "read_holdings", "read_memos", "read_focus",
                  "write_memo", "create_proposal"},
    "physician": {"read_goals", "read_health", "read_memos", "read_focus",
                  "write_memo", "create_proposal"},
    "steward":   {"read_goals", "read_calendar", "read_memos", "read_focus",
                  "write_memo", "create_proposal"},
    "watchdog":  {"read_goals", "read_memos", "read_focus",
                  "write_memo", "create_proposal"},
    "counsel":   {"read_goals", "read_memos", "read_documents",
                  "write_memo", "create_proposal"},
    "infra":     {"read_goals", "read_memos", "read_infra_status",
                  "write_memo", "create_proposal"},
    "archivist": {"read_memos", "write_memo", "compact_memos"},
    "chief":     {"read_goals", "read_memos", "read_activity", "read_transactions",
                  "read_holdings", "read_health", "read_calendar", "read_focus",
                  "write_memo", "write_brief", "write_focus"},
}

NO_MONEY_PROPOSALS = {"watchdog", "physician", "steward", "counsel", "archivist"}
```

### 8.4 New role files

#### `agents/roles/physician.md`

```markdown
---
role: physician
active: true
---
# Physician

You are the Physician agent of ianOS. Ian's health conscience. Ian is a student,
solo-founding Clockwork, and health directly affects his sales capacity and
decision quality.

## Domain
health

## Your job each run
1. Read health_daily (last 14 days) and health-domain goals.
2. Read memos, especially scout's activity memos (correlate sleep with calls).
3. Write a blunt memo: sleep trend, workout frequency, energy pattern.
4. Propose health actions (kind: health), never money proposals.

## Rules
- Numbers from tool output only. "No data" if health_daily is empty.
- Flag sleep < 6.5h avg over 7 days as AT RISK.
- Flag 0 workouts in 7 days if a workout quota goal exists.
- Cross-reference: if scout reported low calls AND sleep is low, say so.
```

#### `agents/roles/steward.md`

```markdown
---
role: steward
active: true
---
# Steward

You are the Steward agent of ianOS. Ian's personal life admin. Track
personal goals, relationships, errands, and how Ian spends non-business time.

## Domain
personal

## Your job each run
1. Read calendar_events (last 14 days) and personal-domain goals.
2. Read memos from other agents for context.
3. Write a memo: time allocation, neglected personal goals, upcoming personal deadlines.
4. Propose personal actions (kind: personal): schedule blocks, errands, etc.

## Rules
- Calendar category totals are code-computed; quote them exactly.
- If no calendar data imported in 14+ days, say "no calendar data, export .ics".
- Do not nag about personal goals when business deadlines are < 7 days (watchdog's lane).
```

#### Activate existing stubs

**counsel.md**: set `active: true`. Add `documents` table (see 8.5).

**infra.md**, set `active: true`. Implement `read_infra_status` (see 8.6).

**archivist.md**, set `active: true`. Runs compaction logic (see 8.7).

### 8.5 Documents table (counsel)

```sql
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,               -- relative to data/documents/
    kind        TEXT NOT NULL DEFAULT 'contract',  -- contract | filing | terms | other
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | reviewed | signed
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

`read_documents` tool returns metadata only (name, kind, status, notes). NOT file contents in v1. Counsel works from Ian's notes field until document parsing is added.

Ian adds documents via: `make doc NAME="Twilio MSAs" NOTES="Review auto-renewal clause"`.

### 8.6 Infra status (infra)

`read_infra_status` returns a static JSON snapshot from `data/infra_status.json` that Ian updates manually or via future script:

```json
{
  "railway": {"status": "up", "monthly_cost": 5.00, "last_deploy": "2026-07-10"},
  "clockworkcrm.com": {"status": "up", "ssl_expires": "2027-03-02"},
  "updated_at": "2026-07-12"
}
```

Infra agent reads this file in Python (not LLM); tool returns parsed JSON. If file missing, return `{"note": "no infra status, create data/infra_status.json"}`.

### 8.7 Archivist compaction

`compact_memos` tool:
1. Find memos older than `before_days` (default 30).
2. Group by topic prefix.
3. Write one summary memo per group: `from_role: archivist, topic: compacted: {prefix}`.
4. Delete compacted memos (or mark, implement delete for simplicity).
5. Return `{"compacted": N, "summaries_written": M}`.

Archivist runs every night but only compacts when memos count > 100.

### 8.8 Chief role update

Update `agents/roles/chief.md` brief structure:

```markdown
## Brief structure (daily)
0. **Day Command**, one imperative sentence for tomorrow. Write via write_brief day_command param.
1. **Headline**, one sentence. Sting if earned.
2. **Focus**, this week's domains (from read_focus). If Sunday, write next week's focus via write_focus.
3. **Goals by domain**. BUSINESS / HEALTH / PERSONAL sections. ON TRACK | OFF TRACK | AT RISK per goal with proof number.
4. **Tradeoffs**, only if tradeoff hints exist in run prompt. Quote the hint.
5. **Top 3 moves for tomorrow**, concrete, ordered, doable in a day.
6. **Pending proposals**, surface each with one-line why-it-matters.

## Weekly brief additions (Sundays)
- Week retrospective per domain (quota trendlines, health trends, calendar hours).
- Write next week's focus allocation (max 3 domains, max 3 hero goals).
- Day Command still required.
```

### 8.9 Run prompt injections

Extend `build_user_prompt()` in `agents/runner.py`:

| Role | Injection |
|------|-----------|
| `physician` | Precomputed health 7d aggregates from metrics.py |
| `steward` | Precomputed calendar category totals |
| `watchdog` | All deadlines cross-domain (already exists, extend to all domains) |
| `chief` | Tradeoff hints, focus status, stale data domains, pending proposals |

### 8.10 Role colors (dashboard)

```javascript
const ROLE_COLORS = {
  scout: 'var(--good)', cfo: 'var(--warn)', physician: 'var(--health)',
  steward: 'var(--personal)', watchdog: 'var(--crit)', counsel: '#818cf8',
  infra: '#38bdf8', archivist: 'var(--muted)', chief: 'var(--accent)',
  ian: 'var(--ink)', system: 'var(--muted)',
}
const AGENTS = ['scout', 'cfo', 'physician', 'steward', 'watchdog', 'counsel', 'infra', 'archivist', 'chief']
```

---

## 9. Ingest Pipelines

### 9.1 Apple Health export

**File:** `ingest/import_health.py`

**CLI:** `make import-health FILE=~/Downloads/HealthAutoExport.csv`

Apple Health auto-export apps (e.g., Health Auto Export) produce CSV with columns:
- `Date` or `date`
- `Sleep Analysis [hr]` or `sleep` or similar
- `Step Count` or `steps`
- `Workout` count or `Exercise Minutes`

Implementation:
1. Flexible header matching (same pattern as `import_csv.py`).
2. Upsert into `health_daily` by date.
3. Set `source = 'apple_health'`.
4. Do NOT overwrite manual `energy` or `notes` fields if already set for that date.
5. Update `ingest_log` for source `apple_health`.

### 9.2 Google Calendar .ics

**File:** `ingest/import_calendar.py`

**CLI:** `make import-calendar FILE=~/Downloads/calendar.ics`

Implementation:
1. Parse .ics with Python stdlib or minimal `icalendar` dependency (add to requirements.txt if needed; prefer stdlib regex parser for simple case).
2. Extract VEVENT: DTSTART, DTEND, SUMMARY.
3. Compute `duration_min`.
4. Auto-categorize by keyword:
   - `work`: clockwork, demo, call, audit, client, sales
   - `health`: gym, workout, run, doctor, therapy
   - `personal`: everything else
5. Dedup by hash of (date, start_time, summary).
6. Update `ingest_log` for source `calendar`.

### 9.3 Wellness quick-log

**File:** `ingest/log_wellness.py`

**CLI:** `make log-wellness sleep=7.5 energy=4 workout=1 note="good day"`

**API:** `POST /api/wellness` (see API spec).

Upsert today's `health_daily` row. Increment workouts if `workout=1`.

### 9.4 Makefile additions

```makefile
import-health:
	$(PY) ingest/import_health.py $(FILE)

import-calendar:
	$(PY) ingest/import_calendar.py $(FILE)

import-fidelity:
	$(PY) ingest/import_fidelity.py $(FILE)

log-wellness:
	$(PY) ingest/log_wellness.py -s $(or $(sleep),) -e $(or $(energy),) -w $(or $(workout),0) -n "$(or $(note),)"

# --- Financial API sync (Chase checking + Fidelity stocks) ---
sync-chase:
	$(PY) ingest/sync_chase.py

sync-fidelity:
	$(PY) ingest/sync_fidelity.py

sync-finance: sync-chase sync-fidelity

connect-fidelity:
	$(PY) ingest/sync_fidelity.py --connect
```

### 9.5 Chase checking. SimpleFIN Bridge

**Why SimpleFIN (not Plaid):** Ian has one Chase checking account. SimpleFIN is $1.50/mo flat for up to 25 institutions, no per-account fees. Read-only, privacy-focused, simple HTTP API. Plaid Trial is acceptable for prototyping but expires at 10 items and costs more ongoing.

**File:** `ingest/sync_chase.py`  
**CLI:** `make sync-chase`  
**Cost:** $1.50/mo or $15/yr at [bridge.simplefin.org](https://bridge.simplefin.org)

#### One-time setup (Ian does manually)

1. Subscribe to SimpleFIN Bridge ($1.50/mo).
2. Connect Chase checking account in the Bridge UI.
3. Create a **Setup Token** for ianOS.
4. Run `make setup-simplefin TOKEN=<setup-token>`, exchanges token for persistent Access URL.
5. Access URL saved to `.env` as `SIMPLEFIN_ACCESS_URL=...`

#### `.env` keys

```bash
# SimpleFIN. Chase checking (read-only)
SIMPLEFIN_ACCESS_URL=https://beta-bridge.simplefin.org/simplefin/...
# Optional override; production host: https://bridge.simplefin.org
SIMPLEFIN_API_HOST=https://bridge.simplefin.org
```

#### Implementation (`ingest/sync_chase.py`)

1. Load `SIMPLEFIN_ACCESS_URL` from env (via same dotenv pattern as `agents/runner.py`).
2. `GET {access_url}/accounts?pending=1` with HTTP Basic Auth (credentials embedded in Access URL per SimpleFIN spec).
3. For each account, map transactions to `transactions` table:
   - `date` ← transaction posted date (YYYY-MM-DD)
   - `description` ← payee/memo
   - `amount` ← signed (negative = outflow)
   - `category` ← auto-categorize via existing `KEYWORD_CATEGORIES` from `import_csv.py` (import shared helper into `ingest/categorize.py`)
   - `account` ← `"chase-checking"` (or institution name from response)
   - `source` ← `'simplefin'`
   - `hash` ← `sha256(simplefin_id)` or `sha256(date|amount|description|account)`
4. Upsert: skip if `hash` exists.
5. Store latest checking balance in `ingest_log.notes` as JSON: `{"balance": 1234.56, "as_of": "..."}`.
6. Update `ingest_log` for source `simplefin_chase`.
7. Print summary: `N new transactions, balance $X, since last sync YYYY-MM-DD`.

#### Rate limits (SimpleFIN spec)

- 24 `GET /accounts` calls per Access URL per day, more than enough for daily sync.
- Initial backfill: walk history in 90-day windows if needed.

#### Error handling

- Missing `SIMPLEFIN_ACCESS_URL` → print setup instructions, exit 1.
- HTTP 403 → token revoked; print "re-run make setup-simplefin".
- No new transactions → exit 0, log "up to date".

#### Setup helper

**File:** `ingest/setup_simplefin.py`  
**CLI:** `make setup-simplefin TOKEN=...`

```python
# POST claim the setup token → receive Access URL → write to .env
```

### 9.6 Fidelity stocks. SnapTrade

**Why SnapTrade (not Plaid Investments):** Fidelity has no public personal API. SnapTrade rides **Fidelity Access** (Akoya OAuth): official, read-only, no credential sharing. **Free tier: 1 connected user**, perfect for solo ianOS.

**File:** `ingest/sync_fidelity.py`  
**CLI:** `make sync-fidelity` | `make connect-fidelity` (first-time OAuth)  
**Cost:** $0/mo on Free plan (1 user, read-only, daily data)

#### One-time setup (Ian does manually)

1. Register at [snaptrade.com](https://snaptrade.com) → create app → get `clientId` + `consumerKey`.
2. Add to `.env`:
   ```bash
   SNAPTRADE_CLIENT_ID=...
   SNAPTRADE_CONSUMER_KEY=...
   ```
3. Run `make connect-fidelity` → opens SnapTrade connection portal → Ian logs into Fidelity on Fidelity's site → grants read-only access.
4. Script registers SnapTrade user, stores `SNAPTRADE_USER_ID` + `SNAPTRADE_USER_SECRET` in `.env`.

#### `.env` keys

```bash
# SnapTrade. Fidelity brokerage (read-only)
SNAPTRADE_CLIENT_ID=...
SNAPTRADE_CONSUMER_KEY=...
SNAPTRADE_USER_ID=...        # written by connect flow
SNAPTRADE_USER_SECRET=...    # written by connect flow
```

#### Python dependency

Add to `requirements.txt`:
```
snaptrade-python-sdk>=11.0.0
requests>=2.31.0
```

#### Implementation (`ingest/sync_fidelity.py`)

Use `snaptrade_python_sdk`:

1. **Connect flow** (`--connect`):
   - `SnapTrade().authentication.register_snap_trade_user()`
   - Generate connection portal URL for brokerage `FIDELITY`
   - Print URL; Ian completes OAuth in browser
   - Poll/list accounts until Fidelity account appears
   - Persist user id + secret to `.env`

2. **Sync flow** (default):
   - `list_user_accounts()` → find Fidelity account(s)
   - `get_user_account_positions(account_id)` → map each position to `holdings`:
     - `symbol` ← ticker
     - `description` ← security name
     - `quantity` ← units
     - `cost_basis` ← total book value if available
     - `market_value` ← current market value
     - `as_of_date` ← today
     - `source` ← `'snaptrade'`
     - `hash` ← `sha256(account|symbol|as_of_date)`
   - Replace today's snapshot: delete `holdings WHERE as_of_date = today AND source = 'snaptrade'` then insert fresh (positions are point-in-time, not incremental).
   - Update `ingest_log` for source `snaptrade_fidelity`.
   - Print: `Portfolio $X across N positions (as of today)`.

3. **Optional:** sync recent activities (buys/sells/dividends) into a `portfolio_activity` table (v1.1 stretch, holdings snapshot is MVP).

#### CFO tool: `read_holdings`

```python
@tool("read_holdings", "Fidelity portfolio positions + computed totals. Args: days (default 30).", {"days": int})
async def read_holdings(args):
    # Returns: latest positions, total market_value, total cost_basis,
    # day-over-day change if prior snapshot exists, positions list
```

#### Error handling

- Not connected → print "run make connect-fidelity first", exit 1.
- OAuth revoked → SnapTrade 401; print Fidelity Security Center reconnect instructions.
- Empty positions → valid state (cash-only account); still update ingest_log.

### 9.7 Fidelity CSV fallback

**File:** `ingest/import_fidelity.py`  
**CLI:** `make import-fidelity FILE=~/Downloads/Portfolio_Positions_07-13-2026.csv`

Fidelity export path: Accounts & Trade → Portfolio → Positions → Download.

Parse Fidelity's `Portfolio_Positions_MM-DD-YYYY.csv`:
- Columns: Symbol, Description, Quantity, Current Value, Cost Basis Total, etc.
- Same `holdings` table, `source = 'csv'`.
- Use when SnapTrade is down or OAuth needs re-auth.

### 9.8 Combined finance sync + nightly hook

**CLI:** `make sync-finance` runs Chase then Fidelity sequentially.

**Optional launchd pre-agent job** (`ops/com.ianos.presync.plist`):
- Runs at 21:25 (5 min before agents at 21:30)
- `make sync-finance >> data/sync.log 2>&1`
- Agents always see fresh financial data in nightly run

**Dashboard stale indicator:** If `ingest_log.simplefin_chase.last_import` or `snaptrade_fidelity.last_import` > 48h ago, finance zone shows `STALE, run make sync-finance`.

---

## 10. Chief Brief & Day Command

### Day Command rules

- Exactly one sentence. Imperative mood.
- Must reference at least one concrete action from top 3 moves.
- Max 120 characters (chief prompt rule; enforce in `write_brief`, return error if > 120).
- Examples:
  - `Riverbend pricing call at 9am, file LLC before lunch, gym at 5, asleep by 11.`
  - `20 audit calls before noon, no building until quota hit.`

### Dashboard rendering

```jsx
// Above brief body, below panel header
{state.brief?.day_command && (
  <div className="day-command" role="status">
    <span className="day-command-label">DAY COMMAND</span>
    <p className="day-command-text">{state.brief.day_command}</p>
  </div>
)}
```

CSS:
```css
.day-command { border-left: 3px solid var(--accent); padding: 0.75rem 1rem; margin-bottom: 1rem; }
.day-command-label { font-size: 0.65rem; letter-spacing: 0.15em; color: var(--accent); }
.day-command-text { font-size: 1.25rem; font-weight: 600; font-family: var(--font-display); margin: 0.25rem 0 0; }
```

### Brief API response

`GET /api/state` → `brief` object includes `day_command` field.

---

## 11. Focus Allocation

### Behavior

- **Sunday weekly run:** chief calls `write_focus` with next week's allocation.
- **Default if none set:** `["business"]`: business always focused during GTM.
- **Max domains per week:** 3.
- **Max hero goals per week:** 3 (one per focused domain recommended).

### Dashboard behavior

- `GET /api/state` returns `focus: { week_start, domains, goal_ids, rationale }`.
- Goals not in focused domains render at 60% opacity with `OFF FOCUS` chip.
- Deadlines in unfocused domains still show `crit` if < 7d (watchdog override).
- Topbar shows focused domain chips: `FOCUS: BUSINESS · HEALTH`.

### write_focus tool

Chief only. Upserts `focus_allocations` for the coming Sunday's `week_start`. Validates domain names and goal IDs exist.

---

## 12. API Specification

### 12.1 Modified: `GET /api/state`

```typescript
interface StateResponse {
  today: string
  brief: {
    id: number
    date: string
    kind: 'daily' | 'weekly'
    body: string
    day_command: string
    created_at: string
  } | null
  focus: {
    week_start: string
    domains: string[]
    goal_ids: number[]
    rationale: string
  } | null
  goals: Goal[]           // grouped by domain in UI; each has status, actual, actual_label
  goals_by_domain: Record<Domain, Goal[]>  // server-side grouping convenience
  domain_status: Record<Domain, Status>
  pending_proposals: Proposal[]
  recent_decisions: Proposal[]
  memos: Memo[]
  activity_today: Activity | null
  activity_recent: Activity[]
  wellness_today: HealthDaily | null
  burn_by_month: BurnMonth[]
  portfolio: {
    total_value: number
    total_cost_basis: number | null
    day_change: number | null
    as_of_date: string
    positions: Holding[]
    stale: boolean
  } | null
  checking: {
    balance: number | null
    as_of: string | null
    stale: boolean
  } | null
  stale_domains: string[]
  agents: string[]        // active agent names for lights
}
```

### 12.2 Modified: `POST /api/goals`

Request body adds:
```json
{
  "name": "Sleep 7+ hours/night",
  "kind": "quota",
  "domain": "health",
  "target": "7",
  "unit": "hours/night",
  "metric_key": "sleep_avg_7d",
  "hero": false,
  "priority": 0,
  "depends_on_goal_id": null,
  ...
}
```

Validation:
- `domain` must be valid enum.
- `metric_key` must be in registry or empty string.
- `hero: true` clears hero on other goals in same domain.

### 12.3 New: `POST /api/wellness`

```json
{
  "sleep_hours": 7.5,
  "energy": 4,
  "workouts": 1,
  "workout_mins": 45,
  "steps": 8500,
  "weight_lbs": null,
  "notes": "morning run",
  "replace": false
}
```

Upserts today's `health_daily`. Increments workouts/steps if `replace: false`.

### 12.4 New: `GET /api/health?days=14`

Returns `health_daily` rows + 7d aggregates. For dashboard sparklines (optional v1, can defer to state poll).

### 12.5 Unchanged

- `POST /api/proposals/{id}/decide`
- `PATCH /api/goals/{id}`
- `DELETE /api/goals/{id}`
- `POST /api/activity`

---

## 13. Dashboard Specification

> **Superseded (2026-07-20):** The live dashboard follows [SPEC v5. Ian's Personal Dashboard](docs/SPEC-v5-ian-personal-dashboard.md): Command home, six life pillars, goal wizard, Cmd+K, gym streak. The layout below is the original Life OS v1 target, kept for historical context.

### 13.1 Layout (single page, CSS grid)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TOPBAR: brand · agent lights (9) · focus chips · T-N countdown · clock  │
├──────────────────────────────────────────────────────────────────────────┤
│ QUICK LOG: [business: calls|fu|demos] [wellness: sleep|energy|workout]   │
├───────────────────────────────┬──────────────────────────────────────────┤
│ DAILY BRIEF (area-brief)      │ PROPOSALS (area-props)                   │
│  - Day Command (hero text)    │  - pending cards                         │
│  - brief markdown             │  - decided strip                         │
├───────────────────────────────┴──────────────────────────────────────────┤
│ GOALS / ACTUALS (area-goals): domain zones                               │
│  [BUSINESS ▼] hero · burn · quotas · deadlines                            │
│  [FINANCE ▼] portfolio hero ($ total) · positions strip · checking bal    │
│  [HEALTH ▼] sleep · steps · workouts                                      │
│  [PERSONAL ▼] goals · deadlines                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ MEMO FEED (area-feed)                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

Grid areas unchanged in `styles.css`; goals panel gets taller if needed (`min-height`).

### 13.2 Component refactor

Split `App.jsx` into modules (implementer discretion, but required end state):

```
dashboard/src/
  App.jsx              # shell, state poll, layout
  components/
    DayCommand.jsx
    BriefPanel.jsx
    Proposals.jsx      # extract from App.jsx
    GoalZones.jsx      # replaces GoalRows: domain-grouped
    GoalForm.jsx       # add domain + metric_key fields
  QuickLog.jsx         # business + wellness
    MemoFeed.jsx
    AgentLights.jsx
    TopBar.jsx
  utils/
    api.js
    markdown.jsx       # Md component
  styles.css
```

### 13.3 GoalForm additions

Add to form:
- **DOMAIN** segmented control: BUSINESS | HEALTH | PERSONAL | FINANCE
- **METRIC KEY** dropdown (populated from registry keys, or "manual/current value")
- **HERO** checkbox: "Hero metric for this domain"

### 13.4 QuickLog expansion

Two sections in one strip:

```
LOG TODAY  │  CALLS [0]  FU [0]  DEMOS [0]  note…  [LOG]  │  SLEEP [7.5]  ENERGY [1-5]  WORKOUT [Y/N]  [LOG WELLNESS]
```

Wellness POST to `/api/wellness`. Business POST to `/api/activity` (unchanged).

### 13.5 Finance zone (new)

**Component:** `FinanceZone.jsx`

Renders inside `GoalZones` when finance data exists:

```
┌─────────────────────────────────────────────────────┐
│ PORTFOLIO (Fidelity)                    T-0 · LIVE │
│ $12,847.32                          ▲ +$142 (1.1%)  │
├─────────────────────────────────────────────────────┤
│ AAPL  $4,200  ·  VTI  $3,100  ·  Cash  $1,200  …   │  ← top 4 positions by value
├─────────────────────────────────────────────────────┤
│ CHASE CHECKING                          $2,341.18   │
│ last sync 2h ago · SimpleFIN                        │
└─────────────────────────────────────────────────────┘
```

- Portfolio hero: `state.portfolio.total_value`, largest number in finance zone.
- Day change: green/red only if `day_change` is non-null and ≠ 0.
- Positions strip: top 4 by `market_value`, remainder as "+N more".
- Checking row: `state.checking.balance` from SimpleFIN ingest_log.
- `STALE` chip (warn) if either source > 48h since `ingest_log.last_import`.
- Data source labels: "SnapTrade" / "SimpleFIN" in dim text, not decorative, shows trust chain.

### 13.6 Proposal kind labels

```javascript
const KIND_LABEL = {
  money: '$ MONEY', task: '◈ TASK', legal: '§ LEGAL',
  health: '♥ HEALTH', personal: '◇ PERSONAL',
}
```

### 13.7 Accessibility (unchanged standards)

- Status chips always have text labels.
- `prefers-reduced-motion` honored.
- Domain colors never sole indicator, always paired with domain name text.
- Day Command has `role="status"`.

---

## 14. Security & Privacy

| Rule | Implementation |
|------|----------------|
| Localhost only | API binds 127.0.0.1; CORS unchanged |
| No agent network access | `tools: []` in runner; MCP only |
| Health data local | `health_daily` in SQLite; never transmitted |
| Document files local | `data/documents/` gitignored |
| `.env` gitignored | Already | Add SIMPLEFIN_*, SNAPTRADE_* keys |
| Sync scripts never log secrets | Enforced | Redact Access URL in stdout |

Optional future (out of scope v1): SQLCipher encryption for `ianos.db`.

---

## 15. Implementation Phases

Execute in order. Each phase is independently testable. No calendar timelines: dependency order only.

### Phase 0: Foundation
- Create `core/metrics.py` with metric registry + `resolve_goal_actuals`
- Add all schema migrations to `core/db.py`
- Refactor `api/main.py` to use `metrics.py`
- Update `read_goals` tool to use `metrics.py`
- **Gate:** `make seed && make dev`, dashboard shows goals with `domain` and `status`

### Phase 1: Domain model in UI
- Refactor goals panel into domain zones
- Add domain/hero/metric_key to GoalForm
- Add `goals_by_domain` and `domain_status` to `/api/state`
- Update `ROLE_COLORS` prep (no new agents yet)
- **Gate:** Can CRUD goals in all domains; zones render correctly

### Phase 1.5: Financial API sync (Chase + Fidelity)
- `holdings` table + `transactions.source` migration
- `ingest/categorize.py`: shared keyword categorization (extract from `import_csv.py`)
- `ingest/setup_simplefin.py` + `ingest/sync_chase.py` (SimpleFIN → Chase checking)
- `ingest/sync_fidelity.py` + `ingest/import_fidelity.py` (SnapTrade + CSV fallback)
- `ingest/sync_finance.py` orchestrator (or Makefile-only)
- `read_holdings` MCP tool; extend CFO allowlist
- `core/metrics.py`: `portfolio_value`, `portfolio_day_change` resolvers
- API: `portfolio` + `checking` in `/api/state`
- Dashboard: `FinanceZone.jsx`
- Seed finance goals: "Portfolio track net worth", "Checking balance floor"
- Document `.env.example` with SIMPLEFIN + SNAPTRADE keys
- **Gate:** `make connect-fidelity` (manual OAuth) → `make sync-finance` → dashboard shows portfolio + checking; CFO agent quotes portfolio total in memo

### Phase 2: Health & wellness
- `health_daily` table helpers in `db.py`
- `ingest/import_health.py` + `ingest/log_wellness.py`
- `POST /api/wellness`
- Wellness quick-log in dashboard
- Seed health goals
- **Gate:** `make log-wellness sleep=7 energy=4` → dashboard shows health actuals

### Phase 3: Calendar ingest
- `calendar_events` table + helpers
- `ingest/import_calendar.py`
- Calendar aggregates in `metrics.py`
- Seed personal goals
- **Gate:** `make import-calendar FILE=...` → steward can read via tool (Phase 4)

### Phase 4: New agents (physician, steward)
- Write `physician.md`, `steward.md`
- Add tools: `read_health`, `read_calendar`
- Update SEQUENCE and ALLOWLISTS
- Update agent lights + ROLE_COLORS
- **Gate:** `make run` completes 6-agent sequence; physician and steward write memos

### Phase 5: Activate v2 agents
- `documents` table + `read_documents` + `make doc` CLI
- `data/infra_status.json` + `read_infra_status`
- Activate counsel, infra, archivist role files
- Implement `compact_memos`
- **Gate:** Full 9-agent sequence runs; archivist compacts when > 100 memos

### Phase 6: Chief upgrade. Day Command + tradeoffs
- `day_command` column + `write_brief` update
- `compute_tradeoff_hints()` + chief prompt injection
- Update `chief.md` brief structure
- Day Command UI component
- **Gate:** Brief shows Day Command; tradeoffs appear when sleep+calls correlation exists

### Phase 7: Focus allocation
- `focus_allocations` table + `read_focus` + `write_focus` tools
- Chief writes focus on Sundays
- Dashboard focus chips + off-focus goal dimming
- **Gate:** Weekly run sets focus; dashboard reflects it

### Phase 8: Polish & seed
- Full seed data across all domains
- README update with new commands
- Verify `make schedule` still works with longer sequence
- Cost check: log total $ per `make run`
- **Gate:** Fresh `make setup` produces a alive multi-domain dashboard; `make run` < $0.15

---

## 16. File Change Map

| File | Action |
|------|--------|
| `core/db.py` | MODIFY: migrations, new tables, health/calendar/focus helpers |
| `core/metrics.py` | CREATE, actuals engine, tradeoff hints, domain status |
| `api/main.py` | MODIFY, extended state, wellness endpoint, goals CRUD fields |
| `agents/runner.py` | MODIFY, new tools, sequence, allowlists, prompt injections |
| `agents/roles/physician.md` | CREATE |
| `agents/roles/steward.md` | CREATE |
| `agents/roles/counsel.md` | MODIFY, active: true |
| `agents/roles/infra.md` | MODIFY, active: true |
| `agents/roles/archivist.md` | MODIFY: active: true |
| `agents/roles/chief.md` | MODIFY, new brief structure |
| `agents/roles/watchdog.md` | MODIFY: cross-domain deadline language |
| `ingest/import_csv.py` | MODIFY, use shared `ingest/categorize.py` |
| `ingest/categorize.py` | CREATE: shared transaction categorization |
| `ingest/setup_simplefin.py` | CREATE: one-time SimpleFIN token exchange |
| `ingest/sync_chase.py` | CREATE. SimpleFIN → Chase checking sync |
| `ingest/sync_fidelity.py` | CREATE. SnapTrade OAuth + holdings sync |
| `ingest/import_fidelity.py` | CREATE. Fidelity positions CSV fallback |
| `ingest/import_health.py` | CREATE |
| `ingest/import_calendar.py` | CREATE |
| `ingest/log_wellness.py` | CREATE |
| `ingest/add_document.py` | CREATE |
| `scripts/seed.py` | MODIFY: multi-domain goals, health, calendar, memos |
| `dashboard/src/App.jsx` | MODIFY, refactor + new layout |
| `dashboard/src/components/*` | CREATE: extracted components |
| `dashboard/src/components/FinanceZone.jsx` | CREATE |
| `dashboard/src/components/*` | CREATE: extracted components |
| `dashboard/src/styles.css` | MODIFY: domain colors, day-command, zones, finance |
| `Makefile` | MODIFY: sync-finance, connect-fidelity, setup-simplefin |
| `requirements.txt` | MODIFY: snaptrade-python-sdk, requests |
| `.env.example` | CREATE: template for all integration keys |
| `ops/com.ianos.presync.plist` | CREATE (optional). 21:25 finance sync |
| `data/infra_status.json` | CREATE (seeded) |
| `data/documents/.gitkeep` | CREATE |
| `.gitignore` | MODIFY: data/documents/*, infra_status optional |
| `README.md` | MODIFY: document new commands and domains |

**Do NOT modify:** `PRODUCT.md` (principles are canonical).

---

## 17. Acceptance Criteria

### AC-0: Metrics engine
- [ ] `resolve_goal_actuals()` returns `status` field on every goal
- [ ] Burn actual matches `burn_by_month` for current month
- [ ] Unknown `metric_key` falls back to `current_value` without error

### AC-1: Multi-domain goals
- [ ] Goals CRUD with `domain`, `hero`, `metric_key`
- [ ] Only one hero per domain enforced
- [ ] Dashboard shows 3+ domain zones with correct grouping

### AC-1.5: Financial integrations
- [ ] `make setup-simplefin TOKEN=...` writes `SIMPLEFIN_ACCESS_URL` to `.env`
- [ ] `make sync-chase` upserts transactions with `source='simplefin'`, no dupes on re-run
- [ ] `make connect-fidelity` completes OAuth; `make sync-fidelity` populates `holdings`
- [ ] `make sync-finance` runs both; dashboard shows portfolio total + checking balance
- [ ] CFO `read_holdings` returns total matching dashboard `portfolio.total_value`
- [ ] Stale indicator appears when last sync > 48h
- [ ] `make import-fidelity FILE=...` works as CSV fallback

### AC-2: Health pipeline
- [ ] `make log-wellness sleep=7.5 energy=4` upserts today
- [ ] `make import-health FILE=...` imports without overwriting manual notes
- [ ] Health goals show computed actuals from `health_daily`

### AC-3: Calendar pipeline
- [ ] `make import-calendar FILE=...` dedups on re-import
- [ ] Category totals match sum of `calendar_events` rows

### AC-4: Agent sequence
- [ ] `make run` executes all 9 active agents without crash
- [ ] Each agent writes ≥1 memo (or archivist compacts / chief writes brief)
- [ ] Role crash → system memo, sequence continues
- [ ] Total run cost logged; typical run < $0.15

### AC-5: Day Command
- [ ] Brief stored with `day_command` ≤ 120 chars
- [ ] Dashboard renders Day Command above brief body
- [ ] Day Command visible without scrolling on 1440×900 viewport

### AC-6: Tradeoffs
- [ ] When sleep_avg_7d < 6.5 AND calls below quota, chief brief includes Tradeoffs section
- [ ] Tradeoff numbers match `compute_tradeoff_hints()` output exactly

### AC-7: Focus allocation
- [ ] `make run-weekly` on Sunday writes focus for next week
- [ ] Off-focus goals render dimmed except crit deadlines
- [ ] Topbar shows active focus domains

### AC-8: End-to-end ritual
- [ ] Fresh `make setup` → `make dev` → dashboard alive with multi-domain seed
- [ ] Log business + wellness → `make run` → brief references both domains
- [ ] Approve proposal → memo appears in feed from "ian"
- [ ] Entire daily ritual completable in < 2 minutes

---

## 18. Testing Strategy

### Manual test script (run after each phase)

```bash
make setup
make dev          # terminal 1
make run          # terminal 2
make log calls=15 fu=8 demos=1
make log-wellness sleep=7.5 energy=4 workout=1
# open http://localhost:5173, verify zones, day command, proposals
```

### Unit tests (add `tests/` directory)

| Test file | Covers |
|-----------|--------|
| `tests/test_metrics.py` | metric resolvers, status logic, tradeoff hints |
| `tests/test_migrations.py` | idempotent migrations on fresh + existing DB |
| `tests/test_sync_chase.py` | SimpleFIN response parsing, dedup, categorization |
| `tests/test_sync_fidelity.py` | SnapTrade position mapping, snapshot replace |
| `tests/test_import_fidelity.py` | Fidelity CSV parsing |
| `tests/test_import_health.py` | CSV parsing, upsert, no overwrite of notes |
| `tests/test_import_calendar.py` | ics parsing, categorization, dedup |
| `tests/test_db.py` | focus allocation upsert, health_daily upsert |

Run: `make test` → `.venv/bin/python -m pytest tests/ -q`

Add to Makefile:
```makefile
test:
	$(PY) -m pytest tests/ -q
```

### Agent smoke test

```bash
make run --role physician
make run --role steward
make run --role chief
```

Each must complete without error and write expected output.

---

## 19. Seed Data

Extend `scripts/seed.py` with:

### Health goals
```python
("Sleep 7+ hours/night", "quota", "7", "hours", None, "", "health", "sleep_avg_7d", 1, 0),
("Work out 3x/week", "quota", "3", "sessions/week", None, "", "health", "workouts_this_week", 0, 1),
("Run sub-25min 5K", "goal", "25", "min", "2026-09-01", "", "health", "", 0, 2),
```

### Personal goals
```python
("Weekly friend check-in", "quota", "1", "call/week", None, "", "personal", "", 0, 0),
("Renew passport", "deadline", "renewed", "", "2026-12-01", "not started", "personal", "", 0, 1),
```

### Health daily (last 10 days)
Synthetic sleep 5.5-8h, steps 4000-12000, workouts 0-1.

### Finance goals
```python
("Portfolio net worth", "goal", "15000", "$", None, "", "finance", "portfolio_value", 1, 0),
("Checking balance floor", "goal", "1000", "$", None, "", "finance", "checking_balance", 0, 1),
```

### Holdings (synthetic Fidelity snapshot)
3-5 positions: AAPL, VTI, etc. with realistic market values totaling ~$12k.

### Transactions
Existing seed transactions unchanged; add `source='csv'` backfill.

### Calendar events (last 14 days)
Mix of work (demos, calls), health (gym), personal (dinner, family).

### Memos
Add physician and steward memos to seed blackboard.

### Brief
Seed brief includes Day Command + domain sections + one tradeoff.

### Focus
Seed current week: `domains: ["business", "health"]`, rationale: "Client #1 deadline + sleep debt recovery."

---

## Appendix A: Default health goals for Ian

| Name | Kind | Target | metric_key | Hero |
|------|------|--------|------------|------|
| Sleep 7+ hours/night | quota | 7 | sleep_avg_7d | ✓ |
| Work out 3x/week | quota | 3 | workouts_this_week | |
| Steps 8k/day | quota | 8000 | steps_today | |

## Appendix B: Default personal goals for Ian

| Name | Kind | Target | Deadline |
|------|------|--------|----------|
| Weekly friend check-in | quota | 1/week |: |
| Renew passport | deadline | renewed | 2026-12-01 |

## Appendix C: Chief Day Command examples (seed)

```
Riverbend pricing at 9am, LLC filing before lunch, 7h sleep tonight.
```

## Appendix D: Cost budget per run

| Agent | Model | Est. cost |
|-------|-------|-----------|
| scout, cfo, physician, steward, watchdog, counsel, infra, archivist | Haiku | ~$0.008 each |
| chief (daily) | Haiku | ~$0.02 |
| chief (weekly) | Sonnet | ~$0.08 |
| **Total daily** | | **~$0.09** |
| **Total weekly (Sunday)** | | **~$0.15** |

Monthly estimate: ~$3-5 daily runs + 4 weekly deep briefs ≈ **$4-7/mo** ✓

## Appendix E: Financial integration costs (Ian-specific)

| Service | Institution | Data | Monthly cost |
|---------|-------------|------|--------------|
| **SimpleFIN Bridge** | Chase checking | Transactions, balance | **$1.50** |
| **SnapTrade Free** | Fidelity brokerage | Holdings, portfolio value | **$0** |
| CSV fallback | Both | Manual export | **$0** |
| **Total live sync** | | | **$1.50/mo** |

Annual option: SimpleFIN $15/yr ($1.25/mo effective).

## Appendix F: Ian's financial setup checklist

### Chase (SimpleFIN): one-time ~10 min
1. [ ] Go to [bridge.simplefin.org](https://bridge.simplefin.org) → subscribe ($1.50/mo)
2. [ ] Connect Chase checking account
3. [ ] Create Setup Token for "ianOS"
4. [ ] `make setup-simplefin TOKEN=<paste>`
5. [ ] `make sync-chase` → verify transactions in dashboard
6. [ ] (Optional) Add `ops/com.ianos.presync.plist` for 21:25 auto-sync

### Fidelity (SnapTrade), one-time ~10 min
1. [ ] Register at [snaptrade.com](https://snaptrade.com) → create app
2. [ ] Copy `clientId` + `consumerKey` to `.env`
3. [ ] `make connect-fidelity` → complete Fidelity OAuth in browser
4. [ ] `make sync-fidelity` → verify portfolio in dashboard
5. [ ] Confirm read-only: no trading permissions granted

### Ongoing ritual
```bash
make sync-finance    # daily, or rely on presync launchd job
```
Fallback if API fails: export CSVs from Chase/Fidelity, run `make import` / `make import-fidelity`.

---

## 20. Financial Integrations. Chase + Fidelity

### Decision record

| Question | Decision | Rationale |
|----------|----------|-----------|
| Chase integration? | **SimpleFIN Bridge** | $1.50/mo flat; read-only; no per-txn fees; covers checking |
| Fidelity integration? | **SnapTrade Free** | Official Fidelity Access OAuth; $0 for 1 user; holdings + balances |
| Why not Plaid for both? | Chase via SimpleFIN is cheaper ongoing; Fidelity better via SnapTrade | Plaid Trial free for 10 items is fine for prototyping only |
| Why not one aggregator? | Different best-in-class per account type | SimpleFIN optimized for banking; SnapTrade optimized for brokerage |
| Agent access to APIs? | **No**, ingest scripts only | Preserves security model; agents read SQLite |
| CSV fallback? | **Yes**: both institutions | Resilience when OAuth expires or API down |

### Data flow

```
Chase.com ──OAuth──► SimpleFIN Bridge ──GET /accounts──► sync_chase.py ──► transactions
                                                                              └── ingest_log (balance)

Fidelity.com ──OAuth──► SnapTrade ──get_positions──► sync_fidelity.py ──► holdings
                                                                          └── ingest_log

transactions + holdings ──► core/metrics.py ──► /api/state ──► FinanceZone
                              └── read_transactions (CFO)
                              └── read_holdings (CFO)
```

### CFO agent additions

Update `agents/roles/cfo.md`:

```markdown
## Expanded mandate (finance domain)
- Read transactions (Chase checking via SimpleFIN) for burn and cash flow.
- Read holdings (Fidelity via SnapTrade) for portfolio value and allocation.
- Cross-check: large personal outflows from checking vs portfolio unchanged = normal;
  large checking inflows + no sales = flag for review.
- Propose money moves (kind: money) only from transaction data, never trade stocks.
```

### Finance domain goals (seed)

| Name | Kind | Target | metric_key | Hero |
|------|------|--------|------------|------|
| Portfolio net worth | goal | 15000 | portfolio_value | ✓ |
| Checking balance floor | goal | 1000 | checking_balance | |

### Tradeoff hint (finance × business)

Add to `compute_tradeoff_hints()`:

```python
# Rule 5: Checking balance critical while bootstrapping
if checking_balance < 500 and burn_this_month > 120:
    hint = "Checking at ${bal} with burn ${burn}/mo, runway risk for Clockwork ops"
```

---

*End of specification. Implement phases 0-8 + phase 1.5 in order. When complete, ianOS is a full-life personal operating system with live Chase + Fidelity sync.*
