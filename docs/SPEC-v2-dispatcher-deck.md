# ianOS v2: "Dispatcher Deck" Specification

**Status:** approved by Ian, ready to build.
**Audience:** an implementing agent with NO prior conversation context. Everything
you need is in this file plus the repo. Read this whole spec before writing code.
**Estimated scope:** 3 phases, each independently shippable and verifiable.

---

## 0. Orientation: what ianOS is and what exists today

ianOS is Ian McCallum's personal agent headquarters. Ian is in the Chicago suburbs,
solo founder of Clockwork (AI CRM for HVAC/plumbing contractors, $199/mo, goal:
client #1 by 2026-08-15), starting at UIUC Gies (Finance + Data Science) ~Aug 24
2026, girlfriend Partner, younger siblings, the family dog, trains MMA/lifting/soccer,
wants an externalized executive function.

### Architecture (unchanged in v2: do not redesign)

- **ONE runner** ([agents/runner.py](../agents/runner.py)): executes markdown role
  files from `agents/roles/*.md` via the Claude Agent SDK (`claude-agent-sdk`,
  Python). Bounded tool loop (`max_turns=10`). Auth: `CLAUDE_CODE_OAUTH_TOKEN` in
  `.env` (subscription, not API billing): loaded by `load_dotenv()` in the runner.
- **Blackboard**: agents never talk to each other live; they read/write the
  `memos` table in `data/ianos.db` (SQLite, WAL). Nightly sequence runs roles in
  order so later roles see earlier memos. Chief runs LAST and composes THE brief.
- **Models**: `claude-haiku-4-5` for everything except the chief's weekly deep
  brief (`claude-sonnet-5`, Sundays or `--weekly`).
- **Hard rules (enforced in code, these are the product, never weaken):**
  1. Agents have ZERO built-in tools (`tools=[]` in options), no shell/fs/web.
  2. Per-role tool allowlists in `ALLOWLISTS` dict in runner.py, enforced via
     `allowed_tools` + `disallowed_tools` (complement set).
  3. Agents read, memo, and propose. NOTHING executes. Proposals are decided by
     Ian on the dashboard; decisions write back as memos from "ian".
  4. Every number traceable to a table row; deterministic math in Python, LLM
     narrates. If data is missing agents say "no data", never estimate.
  5. A role crash = memo from "system", sequence continues (try/except per role).
  6. Briefs idempotent per (date, kind), upsert.

### Current state (verified 2026-07; re-verify with the greps below before starting)

- **Roles (9, all `active: true`)**: scout (sales pipeline), cfo (burn vs $150/mo
  cap), physician (sleep/energy), steward (calendar/life admin), watchdog
  (deadline chains), counsel (document flags), infra (hosting status), archivist
  (memo compaction), chief (the brief).
  `SEQUENCE = [scout, cfo, physician, steward, watchdog, counsel, infra, archivist, chief]`
- **Tables (13)** in [core/db.py](../core/db.py): transactions, memos, briefs,
  goals (has domain/metric_key/priority/hero columns + migrations), activity,
  health_daily, calendar_events, focus_allocations, ingest_log, holdings,
  documents, proposals, partner_tasks. There is a migration helper
  (`run_migrations`, `_migrate_columns`): use it for all new columns.
- **Agent tools (14)** in runner.py: read_goals, read_transactions, read_holdings,
  read_activity, read_health, read_calendar, read_focus, read_documents,
  read_infra_status, read_memos, write_memo, create_proposal, write_brief,
  write_focus, compact_memos.
- **API** ([api/main.py](../api/main.py)): GET /api/health, /api/state;
  POST /api/proposals/{id}/decide, /api/goals, /api/activity, /api/wellness,
  /api/partner-tasks; PATCH/DELETE for goals and partner-tasks.
- **Ingest** ([ingest/](../ingest/)): import_csv, import_calendar, import_health,
  import_fidelity, sync_chase (SimpleFIN), sync_fidelity (SnapTrade),
  log_activity, log_wellness, categorize, setup_simplefin.
- **Dashboard** ([dashboard/](../dashboard/)): Vite/React multi-page app
  (pages: home, goals, money, partner, inbox, log, notes in `App.jsx` + `pages/`),
  glass/aurora aesthetic, polls `/api/state`.
- **Scheduling**: launchd job `com.ianos.nightly` runs the sequence 21:30 nightly.

Orient yourself first (do not skip):

```bash
grep -n "SEQUENCE\|ALLOWLISTS" agents/runner.py | head
grep -n "^CREATE TABLE" core/db.py
grep -n "@app\." api/main.py
ls agents/roles/ ingest/ dashboard/src/pages/
```

---

## 1. What v2 builds, one paragraph

v2 grows the network from 9 to 15 agents WITHOUT growing noise or cost, via four
mechanisms: **(a) codenames**: every agent gets a pop-culture persona for display
while internal role ids stay stable; **(b) a facts store**, durable, domain-scoped
memory distilled from memo chatter, giving agents months-long memory with tiny
contexts (this is the RAG layer); **(c) a dispatcher**, pure-Python cadence tiers
and tripwires decide WHO runs each night, so most agents sleep most nights and a
skipped agent costs $0.00; **(d) a brief budget**, memos carry priority, the chief
gets a hard cap on surfaced items, and silence becomes the network's default state.

**Design principle for every decision: Ian's attention is the scarce resource.
An agent that has nothing new to say must not run, and if it runs by mistake it
must not reach the brief.**

---

## 2. Agent identity model (Phase 1)

### 2.1 Internal ids vs codenames

Internal role ids (existing and new) are lowercase functional slugs and NEVER
change, they're foreign keys in memos/proposals history. Codename + persona are
frontmatter, display-only.

Role file frontmatter schema (extend `load_role()` in runner.py, which already
parses `key: value` frontmatter):

```markdown
---
role: cfo
codename: Jordan Belfort
persona: money-obsessed wolf, permanently defanged: can only propose, never touch a dollar
active: true
tier: daily            # daily | weekly | tripwire  (Phase 2 reads this; harmless in Phase 1)
day: sun               # only for tier: weekly: mon|tue|wed|thu|fri|sat|sun
domains: finance       # comma-separated; scopes read_facts (Phase 1)
---
```

### 2.2 The full roster

| internal id | codename | persona hook | tier | day | domains | status |
|---|---|---|---|---|---|---|
| scout | Dwight Schrute | relentless top salesman, calls out slack | daily |: | business | exists |
| cfo | Jordan Belfort | wolf on a leash: proposes, never touches money | daily |: | finance | exists |
| watchdog | Hermione Granger | has never missed a deadline in her life | daily |: | all | exists |
| physician | Dr. House | blunt differential diagnosis of sleep/energy | daily |: | health | exists |
| chief | Nick Fury | assembles the roster, cuts the brief | daily (last) |: | all | exists |
| steward | Alfred Pennyworth | impeccable butler: calendar, errands, time | weekly | sun | personal | exists |
| counsel | Harvey Specter | flags clauses; always "consult a real lawyer" | tripwire |: | legal | exists |
| infra | Scotty | "she cannae take more load": prod health | tripwire |: | business | exists |
| archivist | Samwell Tarly | maester: compacts memos into facts | weekly | sun | all | exists (rewrite) |
| **lovebird** | Hitch | never lets Ian show up empty-handed for Partner | tripwire + weekly | sat | personal | **new** |
| **advisor** | Dumbledore | UIUC/Gies headmaster: registration, GPA, load vs business | weekly + tripwire | wed | college | **new** |
| **wealth** | Bobby Axelrod | portfolio watch; hard-coded to observe, never advise trades | weekly | fri | finance | **new** |
| **publicist** | Don Draper | content cadence as pipeline fuel | weekly | mon | business | **new** |
| **coach** | Rocky Balboa | corner-man for MMA/lifting/soccer streaks | tripwire |: | health | **new** |
| **family** | Uncle Iroh | siblings, parents, the dog, family trips | weekly + tripwire | sun | personal | **new** |

`domains: college` requires adding `'college'` to the goals-domain CHECK constraint
values and anywhere domains are enumerated (core/db.py `goals` CHECK + migration,
`DOMAINS` list in dashboard App.jsx, DOMAIN_COLORS). Use a migration that recreates
the CHECK via table-rebuild ONLY if SQLite version requires it; otherwise note that
SQLite doesn't enforce CHECK retroactively on existing rows, prefer relaxing to
app-level validation if a rebuild is risky. Facts domains are app-validated
(`business|finance|health|personal|college|legal|all`), not DB-constrained.

### 2.3 Sequence order (Phase 1)

Information flows toward the chief. New SEQUENCE (only roles whose dispatcher says
"run tonight" actually execute, Phase 2):

```python
SEQUENCE = [
    "scout", "publicist", "cfo", "wealth", "physician", "coach",
    "steward", "family", "lovebird", "advisor", "watchdog",
    "counsel", "infra", "archivist", "chief",
]
```

Rationale: producers of domain data run before cross-domain synthesizers;
watchdog late so it can escalate anything dated that others surfaced; archivist
before chief on Sundays so the weekly brief sees compacted facts; chief always last.

### 2.4 Exposing the roster

New endpoint `GET /api/roster` in api/main.py: parses all role files via the same
frontmatter loader (import from `agents.runner` or duplicate a tiny parser in
`core/roles.py`, prefer extracting `load_role` into `core/roles.py` and importing
it from both runner and API to avoid drift). Returns:

```json
[{"role": "cfo", "codename": "Jordan Belfort", "persona": "…", "tier": "daily",
  "domains": ["finance"], "active": true}, …]
```

Dashboard: wherever a role id renders (memo feed, proposals, brief byline, agent
lights), display `codename` with the internal role as a small subtitle/tooltip : 
e.g. **Jordan Belfort** · cfo. Fetch `/api/roster` once and cache in a context.
Add role→color entries in `ROLE_COLORS` for the six new ids (pick from the
existing palette vars; each new agent gets a distinct hue; keep `ian`/`system` as-is).

---

## 3. The facts store. RAG memory (Phase 1)

### 3.1 Schema (add to core/db.py SCHEMA + `_migrate_columns` no-ops if exists)

```sql
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain      TEXT NOT NULL,            -- business|finance|health|personal|college|legal
    topic       TEXT NOT NULL,            -- kebab slug, namespaced: 'partner:favorite-flowers'
    body        TEXT NOT NULL,            -- the durable fact, one to three sentences
    kind        TEXT NOT NULL DEFAULT 'fact'
                CHECK (kind IN ('fact', 'preference', 'date', 'rule')),
    date        TEXT,                     -- YYYY-MM-DD; REQUIRED when kind='date'
    recurs      TEXT NOT NULL DEFAULT ''  -- '' | 'yearly' (birthdays/anniversaries)
    ,source_role TEXT NOT NULL DEFAULT '',
    source_memo_ids TEXT NOT NULL DEFAULT '',   -- comma-separated memo ids
    verified    INTEGER NOT NULL DEFAULT 1,     -- 0 = agent must ask Ian to confirm
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (domain, topic)
);
```

Topic namespace conventions (document in README): `partner:*` (lovebird),
`family:*`, `uiuc:*` (advisor), `content:*` (publicist), `training:*` (coach),
`market:*` (wealth). Watchdog may read dated facts from ALL domains.

### 3.2 db.py helpers

```python
def upsert_fact(conn, domain, topic, body, kind='fact', date=None, recurs='',
                source_role='', source_memo_ids='', verified=1) -> int
    # INSERT ... ON CONFLICT(domain, topic) DO UPDATE body/kind/date/recurs/
    # source_*/verified, updated_at=now. Returns fact id.

def facts_for_domains(conn, domains: list[str], limit=80) -> list[dict]
    # ORDER BY: kind='date' with nearest upcoming occurrence first (see
    # next_occurrence below), then updated_at DESC. 'all' in domains → no filter.

def delete_fact(conn, fact_id) -> bool

def upcoming_dated_facts(conn, within_days: int, domains=None) -> list[dict]
    # every fact with kind='date' whose next occurrence is within `within_days`.
    # next occurrence: if recurs='yearly', project month-day onto current/next
    # year; else the literal date if >= today. Include days_until in each row.
    # Pure Python date math, this feeds the dispatcher, correctness matters;
    # handle Feb 29 → Feb 28 projection.
```

### 3.3 Agent tools (runner.py)

```python
@tool("read_facts", "Durable long-term facts for YOUR domains (code-scoped), "
      "dated facts first with days_until. Args: none.", {})
# Implementation: uses RUN['role_domains'] (set by run_role from frontmatter),
# NOT a model-supplied arg, the model cannot request another domain. 'all' → all.

@tool("write_fact", "Persist a durable fact worth remembering for months. "
      "topic: namespaced slug ('partner:favorite-flowers'); body: the fact; "
      "kind: fact|preference|date|rule; date: YYYY-MM-DD when kind=date; "
      "recurs: ''|'yearly'.", {"topic": str, "body": str, "kind": str,
                                "date": str, "recurs": str})
# Implementation: domain = first entry of RUN['role_domains'] unless topic's
# namespace maps to a domain (partner:/family:→personal, uiuc:→college,
# content:→business, training:→health, market:→finance). source_role=RUN['role'].
# Reject kind='date' without a valid date. Upserts (same topic = update, not dup).
```

Add both to the allowlists of: lovebird, advisor, wealth, publicist, coach,
family, archivist (write_fact + read_facts), watchdog (+read_facts only),
steward (+read_facts only), chief (+read_facts only). scout/cfo/physician:
+read_facts only (they may cite facts, but only specialists and archivist write).

### 3.4 Archivist rewrite (Samwell Tarly becomes the memory engine)

Rewrite [agents/roles/archivist.md](../agents/roles/archivist.md): weekly (Sunday),
reads the last ~30 days of memos (`read_memos` with days=30) + existing facts,
and (a) writes NEW durable facts it finds in chatter (decisions Ian made and why,
lead states, recurring costs, confirmed dates) via `write_fact` citing
source_memo_ids; (b) calls the existing `compact_memos` tool to archive old memo
noise. Rule: facts must cite source memo ids; compress, never invent. The
archivist is the only agent allowed to write facts OUTSIDE its own namespace.

### 3.5 API + dashboard

- `GET /api/facts?domain=personal` and `DELETE /api/facts/{id}`,
  `PATCH /api/facts/{id}` (body/verified only). Ian curates memory by hand.
- Dashboard: a "Memory" section (either a new page `pages/MemoryPage.jsx` in the
  existing Nav pattern, or a panel on the partner/home pages, follow the existing
  page structure in `App.jsx`/`Nav.jsx`): facts grouped by domain, dated facts
  show countdown chips, unverified facts get a "confirm?" affordance that PATCHes
  `verified=1`. Keep the existing glass aesthetic and component vocabulary.

---

## 4. Six new agents (Phase 1)

Create these role files. Voice matters: each persona is a writing style, not a
gimmick, memos must still lead with numbers and follow every hard rule. Include
in EVERY new role file the same structural skeleton the existing roles use
(mandate, "Your job each run" numbered list, Rules, Style) plus the frontmatter
from §2.1. Specific requirements per agent:

### 4.1 `lovebird.md`. Hitch (tripwire + weekly Sat)
- Domain personal; allowlist: read_goals, read_memos, read_facts, read_calendar,
  write_memo, create_proposal, write_fact.
- Mandate: Partner. Reads `partner:*` facts (preferences, important dates, gift
  history, mentioned wishes): this is the "full relationship memory" Ian chose.
  Sources are ONLY what Ian logs (partner notes land as memos/facts); no scraping.
- Tripwire (see §5): any `partner:*` dated fact within 14 days → wake. Escalation
  ladder in the role prompt: 14d heads-up (plan + budget proposal so cfo/Ian can
  see cost), 7d concrete plan, 2d final check (reservation? gift acquired?).
- Weekly Saturday pass: one short memo, relationship maintenance ideas drawn
  from preference facts, next dated item, anything Ian promised (kind='rule'
  facts like "Ian promised X by Y").
- Writes facts: new preferences/dates/promises it spots in Ian's notes and memos.
- Proposals kind: personal. It NEVER proposes money moves > $0 without pairing
  the amount against cfo's burn context read from memos.
- Privacy rule in prompt: Partner facts never appear in business-domain memos; only
  the chief may mention upcoming Partner dates in the brief (one line, no details).

### 4.2 `advisor.md`. Dumbledore (weekly Wed + tripwire)
- Domain college; allowlist: read_goals, read_memos, read_facts, read_calendar,
  write_memo, create_proposal, write_fact.
- Mandate: full academic copilot for UIUC Gies (Finance + Data Science, starting
  ~2026-08-24): registration windows, tuition/FAFSA/scholarship deadlines,
  course-load strategy each term, GPA tracking (Ian logs grades as memos/facts),
  exam-week collision warnings against Clockwork commitments (reads scout's
  memos + calendar), and freshman logistics (housing, orientation).
- Tripwire: any `uiuc:*` dated fact within 21 days → wake.
- Seed facts (§8) are `verified=0`; the role prompt instructs: when citing an
  unverified fact, ask Ian to confirm it in the memo and propose (kind task)
  "Confirm UIUC date: X". Never treat unverified dates as authoritative.
- Hard boundary: no academic dishonesty help, planning and logistics only.

### 4.3 `wealth.md`. Bobby Axelrod (weekly Fri)
- Domain finance; allowlist: read_goals, read_memos, read_facts, read_holdings,
  write_memo, create_proposal, write_fact.
- Mandate: portfolio watch (SnapTrade/Fidelity holdings already ingest into
  `holdings`), savings discipline vs goals, concentration/drift observations,
  fee/cash-drag flags. Writes `market:*` facts (e.g., cost-basis notes Ian logs).
- **Hard rule in BOTH prompt and code**: educational observation only. It NEVER
  proposes buying/selling any security. In `create_proposal`, when
  `RUN['role'] == 'wealth'`, reject any proposal whose action matches
  `\b(buy|sell|trade|short|swap|rebalance into)\b` (case-insensitive) with an
  error telling it to write an observational memo instead, same pattern as the
  existing watchdog money-proposal block (find it in `create_proposal`).
  Its allowed proposal kind: task (e.g., "review your Fidelity cash sweep rate").
- If holdings data is stale (>14 days since last snapshot; use ingest_log),
  say so and propose running `make sync-fidelity` (check the Makefile for the
  actual target name; if absent, name the script path).

### 4.4 `publicist.md`. Don Draper (weekly Mon)
- Domain business; allowlist: read_goals, read_memos, read_facts, read_content,
  write_memo, create_proposal, write_fact.
- New table (add to SCHEMA + helper + seed): 
  `content_log(id, date, platform, item, url DEFAULT '', notes DEFAULT '')` : 
  Ian's publishing record (site updates, portfolio pieces, posts, videos).
- New tool `read_content` (content_log last 30 days + per-platform counts,
  code-computed): allowlist: publicist only.
- New CLI `ingest/log_content.py` (mirror log_activity.py's structure/flags):
  `make content platform=x item="..." url=... note=...` Makefile target.
- Mandate: publishing cadence vs a simple floor (1 meaningful item/week unless a
  `content:cadence` rule fact says otherwise), brand presence as Clockwork/
  Beat-the-Clock pipeline fuel, portfolio staleness (site last updated: from
  content_log). Blunt about gaps, Draper-style economy of words.

### 4.5 `coach.md`. Rocky Balboa (tripwire)
- Domain health; allowlist: read_goals, read_memos, read_facts, read_health,
  write_memo, create_proposal, write_fact.
- Inspect `health_daily`'s actual columns first (`grep -n "health_daily" -A 12
  core/db.py`), it stores wellness fields; if there is no workout field, add
  column `workout TEXT NOT NULL DEFAULT ''` (migration) and extend
  `ingest/log_wellness.py` + POST /api/wellness with it (short slug like
  'mma', 'lift', 'soccer', 'rest').
- Tripwire: no workout logged in the last 3 days (and health_daily HAS rows in
  the last 14, no data at all means the physician's "no data" lane, don't
  double-nag) → wake. Also wake if a `training:*` dated fact (fight, match,
  meet) is within 14 days.
- Mandate: streaks, weekly training mix (MMA/lifting/soccer balance), taper
  awareness near dated events, correlate with House's sleep memos when present.
  Corner-man voice: short, punchy, zero shame, next action always concrete.

### 4.6 `family.md`. Uncle Iroh (weekly Sun + tripwire)
- Domain personal; allowlist: read_goals, read_memos, read_facts, read_calendar,
  write_memo, create_proposal, write_fact.
- Mandate: siblings' + parents' birthdays, the dog's vet cadence, family
  family trips, family commitments Ian logs. Warm voice, one short
  memo. Distinct from lovebird (Partner is NOT family lane) and steward (calendar
  hygiene stays Alfred's).
- Tripwire: any `family:*` dated fact within 10 days → wake.

### 4.7 Runner wiring

- Add the six ids to `ALLOWLISTS` exactly as specified above and to `SEQUENCE`
  (§2.3). Update the `--role` argparse choices (it derives from ALLOWLISTS : 
  verify). Add codename/persona/tier/day/domains frontmatter to ALL 15 role
  files (existing 9 get codenames from the roster table; steward/counsel/infra/
  archivist tiers per the table).
- `run_role` sets `RUN['role_domains']` from frontmatter before the query.

---

## 5. The dispatcher (Phase 2)

### 5.1 Semantics

Pure Python decides, per role per night, run/skip. In `agents/runner.py`:

```python
def should_run(role_meta: dict, conn, today: date, force: bool) -> tuple[bool, str]:
    """Returns (run?, human-readable reason). NEVER calls a model."""
```

Rules, in order:
1. `--role X` CLI or `force` → (True, "forced").
2. `active: false` → (False, "inactive").
3. `tier: daily` → True.
4. `tier: weekly` → True iff `today.strftime('%a').lower()[:3] == day`, OR any
   of that role's tripwires fire (weekly roles may ALSO have tripwires, see
   table §2.2 "weekly + tripwire").
5. `tier: tripwire` → True iff any tripwire for the role fires.
6. chief: always runs IF at least one other role ran tonight OR there are
   pending proposals older than 24h; else (False, "nothing new, no brief
   tonight is itself signal"): on skip, `latest_brief` stays yesterday's and the
   dashboard already shows STALE. (Keep chief daily in practice; this guard only
   matters if a night produces literally zero role runs.)

### 5.2 Tripwire registry

```python
TRIPWIRES: dict[str, list[Callable[[Any, date], str | None]]] = {
    # each callable returns a reason string if fired, else None
    "lovebird": [dated_fact_within("partner:", 14)],
    "advisor":  [dated_fact_within("uiuc:", 21)],
    "family":   [dated_fact_within("family:", 10)],
    "coach":    [no_workout_streak(3), dated_fact_within("training:", 14)],
    "counsel":  [pending_documents()],          # documents table has unreviewed rows
    "infra":    [infra_status_alert()],         # data/infra_status.json exists AND
                                                # contains a non-ok status
}
```

Implement `dated_fact_within(prefix, days)` on top of `upcoming_dated_facts()`
(§3.2) filtered by topic prefix. `no_workout_streak(n)`: health_daily has ≥1 row
in last 14 days AND no row with non-empty workout in last n days. All tripwires
must be cheap single queries. Unit-test each (see §9).

### 5.3 Runner output + observability

- Print per role: `[lovebird] SKIP (no partner date within 14d)` or
  `[lovebird] RUN (partner:anniversary in 6d)`, the reason string.
- Fired tripwire reasons get injected into that role's user prompt
  (`build_user_prompt`): "You were woken because: {reason}. Address it first."
- Add `--plan` flag: print tonight's run/skip table and exit WITHOUT running
  anything (dry-run for testing and for Ian's curiosity). Zero model calls.
- Record each night's dispatch decisions as one system memo? NO, that's noise.
  Instead append one line per night to `data/dispatch.log` (plain text).

---

## 6. Brief budget + memo priority (Phase 3)

### 6.1 Memo priority

- Migration: `memos.priority INTEGER NOT NULL DEFAULT 1` (0=FYI, 1=normal,
  2=important, 3=urgent-uncuttable).
- `write_memo` tool gains optional `priority: int` arg (validate 0-3, default 1).
  Update SHARED_RULES in runner.py: "Set priority honestly: 3 is reserved for
  breached caps, deadlines <7 days, and things that cost real money if missed
  tonight. Inflated priority is a firing offense."
- Code guard: watchdog memos referencing a deadline <14 days away are stamped
  priority=max(priority, 2), implement by letting watchdog set it; do NOT parse
  memo text in code. Simpler enforced rule: the runner passes the precomputed
  deadline table to watchdog (already exists); watchdog's prompt instructs
  priority 3 when any chain deadline <7d. Trust + verify via tests of the prompt
  file content (string assertions).

### 6.2 Chief's budget (Nick Fury)

- `build_user_prompt` for chief adds a code-computed digest: tonight's memos
  grouped by priority (id, role, topic, priority) + pending proposals + which
  roles were skipped and why (from dispatch decisions).
- Rewrite `chief.md` brief contract:
  - Headline (1 sentence).
  - Per-domain lines ONLY for domains where something changed tonight (max 6).
  - Top 3 moves for tomorrow.
  - Pending proposals (all: these are decisions, never cut).
  - HARD CAP: at most 5 surfaced non-proposal items; priority 3 memos are
    uncuttable and count first; if >5 exist, keep highest priority then newest,
    and end with one line: "Cut N lower-priority items, they're in the feed."
- Weekly (Sunday, sonnet): adds week retrospective + next-week focus (chief
  already has write_focus, keep).

### 6.3 Dashboard

- Memo feed: render priority as a subtle left-of-topic marker (0 muted dot,
  1 default, 2 amber, 3 red pulse, reuse existing chip/dot vocabulary; do NOT
  use a >1px colored left border, that's a banned pattern in this repo's design
  system). Filter control: All / P2+ / P3.
- Brief panel: unchanged (chief's markdown already renders).

---

## 7. Prompts & shared rules changes (Phase 1, finalize in Phase 3)

Update `SHARED_RULES` in runner.py, keep every existing rule, add:

1. "You have long-term memory: read_facts gives you durable facts for your
   domains; write_fact persists anything worth remembering for months. Prefer
   updating an existing topic over creating near-duplicates."
2. "You are {codename}. Write memos in that voice, but a persona is seasoning,
   not content: numbers first, verdict, next action. If the voice ever fights
   clarity, clarity wins."
3. The silence rule: "If your domain genuinely changed tonight, memo it. If not,
   write ONE line: 'quiet, nothing new' with priority 0." (The dispatcher makes
   this rare; the rule covers woken-but-nothing-found cases.)
4. Priority honesty rule (§6.1).

`run_role` interpolates `{codename}` into SHARED_RULES from frontmatter.

---

## 8. Seeds (Phase 1): make the new agents alive on first boot

Extend [scripts/seed.py](../scripts/seed.py) (keep its existing structure: wipe +
reinsert, compute narrative numbers from inserted rows, relative dates via `d()`):

- **Facts** (verified=1 unless noted):
  - `personal / partner:anniversary` kind=date recurs=yearly, date ≈ `d(-20)`
    projected (i.e., ~20 days out), placeholder, body says "seeded placeholder : 
    Ian: correct this", verified=0.
  - `personal / partner:favorite-flowers` kind=preference, body placeholder, verified=0.
  - 3 × `family:sibling-*-birthday` kind=date recurs=yearly, verified=0 placeholders
    spread across the year; `family:dog-vet-checkup` kind=date ~45 days out, verified=0.
  - `college / uiuc:fall-move-in` kind=date ≈ 2026-08-20, verified=0;
    `uiuc:fall-registration` ≈ 2026-07-25, verified=0; `uiuc:fafsa-2027` kind=date
    2026-12-01, verified=0. Bodies must say "UNVERIFIED. Dumbledore must ask Ian".
  - `business / content:cadence` kind=rule, "Floor: 1 meaningful published item
    per week while school is out."
  - `health / training:mix` kind=rule, "Target mix: 2 MMA, 3 lift, 1 soccer per week."
- **content_log**: ~4 rows over the last 3 weeks (site tweak, portfolio
  update, an IG post, gap last week, gives Draper something to flag).
- **workout column**: backfill the seeded health_daily rows with a plausible
  workout mix, including a 4-day recent gap (gives Rocky a tripwire on first boot).
- Do NOT invent real personal data beyond placeholders marked verified=0. The
  agents' first job is asking Ian to confirm/replace them.

---

## 9. Testing & acceptance criteria

There is `pytest` in requirements.txt. Put tests in `tests/` (create if absent;
check for existing tests first and follow their conventions).

### Phase 1 acceptance
- [ ] `pytest tests/test_facts.py`, upsert_fact idempotency (same domain+topic
      updates), upcoming_dated_facts yearly projection (incl. Dec→Jan wrap and
      Feb 29), domain scoping of facts_for_domains.
- [ ] `python agents/runner.py --role lovebird` runs end-to-end: Hitch reads
      seeded partner facts, writes ≥1 memo mentioning the seeded (unverified)
      anniversary and asks Ian to confirm it. Verify in DB.
- [ ] Wealth guard unit test: simulate `RUN['role']='wealth'`, call
      create_proposal handler with action "Buy 10 shares of VOO" → is_error, and
      nothing inserted into proposals.
- [ ] read_facts scoping test: with RUN role_domains=['personal'], returned facts
      contain no `uiuc:*` topics.
- [ ] `/api/roster` returns 15 entries with codenames; dashboard memo feed shows
      "Dwight Schrute · scout" style rendering (verify in browser).
- [ ] Full nightly `make run` completes with all 15 roles (Phase 1 = everyone
      runs; dispatcher lands in Phase 2), each writes ≥1 memo or brief, chief's
      brief renders on the dashboard.

### Phase 2 acceptance
- [ ] `python agents/runner.py --plan` prints a run/skip table with reasons and
      exits without model calls (assert: no cost lines, exits 0).
- [ ] `pytest tests/test_dispatcher.py`: table-driven: for a fixed fake "today",
      each tier/day/tripwire combination from §2.2 yields the expected decision.
      Tripwire tests seed the DB fixtures (dated fact 5 days out fires 14d wire;
      16 days out doesn't; workout gap fires; etc.)
- [ ] On a Tuesday (no tripwires firing), a real `make run` executes exactly:
      scout, cfo, physician, watchdog, chief. Cost line total < $0.15.

### Phase 3 acceptance
- [ ] Memo priority migration applied; write_memo rejects priority=7.
- [ ] Seed >5 high/low priority memos, run chief only: brief surfaces ≤5
      non-proposal items, includes every priority-3, states the cut count.
- [ ] Dashboard filter All/P2+/P3 works (browser verify + screenshot).

### Regression (every phase)
- [ ] Existing hard-rule tests still pass (scout denied read_transactions at
      harness level; watchdog money-proposal block; brief idempotency : 
      re-running chief same night replaces, not duplicates).
- [ ] `make seed && make run` from clean DB crashes zero roles (a role crash
      memo from "system" = failure).
- [ ] Auth note: runs use `CLAUDE_CODE_OAUTH_TOKEN` from `.env`. If runs fail
      with auth errors, STOP and tell Ian to regenerate via
      `./bin/claude setup-token`, do not attempt credential workarounds.

---

## 10. Non-goals (do NOT build these now)

- `/ask` life-RAG search endpoint (Phase 4, later, schema in §3 already supports it).
- Embedding/vector search: the facts table with domain+topic scoping IS the
  retrieval layer at this scale; revisit only if facts exceed ~2k rows.
- New ingest integrations (calendar/health/brokerage sync already exist).
- Any execute-capability for agents. Ever. This is the product's identity.
- Auto-decisions on proposals, auto-sending anything to Partner (Hitch preps Ian;
  it never contacts her), auto-trading (Axelrod observes only).
- Renaming internal role ids in the DB/history.

## 11. Build order & commits

Work Phase 1 → 2 → 3 strictly. Within Phase 1: (1) core/roles.py extraction +
frontmatter, (2) facts schema/helpers/tools + tests, (3) archivist rewrite,
(4) six new role files + allowlists + sequence, (5) content_log + workout column
+ CLIs, (6) seeds, (7) roster API + dashboard rendering, (8) run acceptance
list. Commit per numbered step with messages like `v2: facts store schema +
scoped read_facts/write_fact`. Verify each phase's acceptance list fully before
starting the next. When all three phases pass, update README.md (roster table,
facts/memory ritual, dispatcher explanation, new make targets) and
`docs/`, this spec stays as the record of intent.
