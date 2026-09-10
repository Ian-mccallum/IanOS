> This is the operator manual of ianOS, moved here from the private repo's README. Paths and commands assume the repo root.

# ianOS: personal life operating system

A local-first mission control for Ian's full life: **business** (Clockwork GTM),
**finance** (Chase checking + Fidelity portfolio), **health**, **personal**, and
**college** (UIUC Gies) goals.

**10 pop-culture-named AI agents** run nightly on a shared blackboard and compose a
daily brief with a **Day Command**, one sentence that orchestrates tomorrow. Ian
is CEO; agents READ, MEMO, and PROPOSE for anything hard to reverse — nothing
there executes without pressing APPROVE — plus a closed list of **Ring 1**
reversible acts (SPEC-v37 §4) that apply immediately, receipted and undoable.

Most agents sleep most nights: a **dispatcher** (pure Python) decides who wakes,
so a skipped agent costs $0.00. What they learn persists in a **facts store** : 
domain-scoped long-term memory that compounds for months, plus a full-text
**memory index** (SPEC-v37 §5.4) any agent can search for recall (never as a
substitute for a confirmed fact).

See [SPEC-v37. Agent rebuild](SPEC-v37-agent-rebuild.md) for the current
agent architecture: tiered agency (Ring 1/Ring 2), the memory ledger + index,
the two-plane consult surface, and the roster retirement to 10. Read this
first; it supersedes SPEC-v23, SPEC-v25's stance, and much of SPEC-v26.  
See [SPEC-v10. osUI](SPEC-v10-osui.md) for the current dashboard UX (mobile-first; navigation, Command, Notes, Roster). Its law is also a skill, `.claude/skills/osui/`, to be loaded before any interface work.  
[SPEC-v13. Impeccable mobile](SPEC-v13-impeccable-mobile.md) and [SPEC-v14. Impeccable web](SPEC-v14-impeccable-web.md) for the audit-and-fix passes that hardened osUI on phone and desktop.  
[SPEC-v12. Lock screen](SPEC-v12-lock-screen.md) for Face ID / password unlock on the PWA.  
[PHONE.md](PHONE.md) for install, Tailscale, icons, and Face ID setup.  
[SPEC-v5. Ian's Personal Dashboard](SPEC-v5-ian-personal-dashboard.md) for the original pillar layout that v10 rebuilt.  
[SPEC-v9. The Line](SPEC-v9-the-line.md) for the lead pipeline and the cold-call loop.  
[SPEC-v2-dispatcher-deck.md](SPEC-v2-dispatcher-deck.md) for the agent dispatcher.  
[SPEC-LIFE-OS.md](../SPEC-LIFE-OS.md) for the original architecture.  
[GOALS.md](../GOALS.md) for adding and configuring your own goals.  
[IAN-SETUP.md](../IAN-SETUP.md) for Ian's setup checklist.

## The roster

Internal role ids (left) never change, they're the keys in memo history.
Codenames are display only. Five earlier roles (advisor, archivist, family,
infra, publicist) are retired (`active: false`, kept so their history still
renders) — advisor's academic mandate merged into watchdog, archivist's
weekly distillation became a pure nightly function (`core/ledger.py`).

| codename | role | domain | when it runs |
|---|---|---|---|
| Nick Fury | chief | all | nightly (composes the brief, last) |
| Jordan Belfort | cfo | finance | nightly |
| Dr. House | physician | health | nightly (consent-gated, see Body page) |
| Alfred Pennyworth | steward | all | nightly: the default agent when you don't pick one |
| Dwight Schrute | scout | business | nightly: reads The Line (read-only) |
| Dumbledore | watchdog | all | nightly (absorbed advisor's academic mandate) |
| Rocky Balboa | coach | health | weekly (consent-gated) + workout-gap tripwire |
| Cupid | lovebird | personal | weekly + Partner-date tripwire |
| Rockefeller | wealth | finance | weekly: portfolio, never trades |
| Harvey Specter | counsel | legal | tripwire: a document needs review |

## How it works

- **Dispatcher tiers:** `daily` runs every night; `weekly` runs on its day OR when
  a tripwire fires; `tripwire` runs only when a condition hits (a date within N
  days, a workout gap, a pending document). `make plan` shows tonight's slate
  without spending anything.
- **Facts store (RAG memory):** durable `facts` scoped by domain and topic
  namespace (`partner:*`, `uiuc:*`, `family:*`, `content:*`, `training:*`, `market:*`).
  An agent reads only its own domains; a nightly function (`core/ledger.py::distill`,
  the retired archivist's mandate, now pure code) promotes memo/calendar/school/
  proposal chatter into `verified=1` facts with real provenance. A separate,
  full-text **memory index** (`search_memory`, every active role) is recall
  only — it can surface a memory, never assert one as true. Curate facts on
  the dashboard's **Memory** page.
- **Brief budget:** memos carry a priority (0-3). The chief surfaces at most 5
  non-proposal items; priority-3 is uncuttable; cuts are stated explicitly. The
  brief also carries a code-computed dispatcher line ("5 of 10 woke; 2 off; 3
  out of season"), never mixed into the chief's own prose.
- **Domains:** goals tagged `business` | `finance` | `health` | `personal` | `school`
- **Dashboard (v10, mobile-first):** six **life pillars** (Beat the Clock, Body, Partner, School, Life, Money) plus **Command** home. Authored at 375px; desktop is the enhancement.
  - **Navigation:** five fixed tabs (Command · Plan · BtC · Partner · More), swipe sideways through the pillar ring, everything else in the More sheet. Desktop rail shows the brand lockup + **⌘K**. `Cmd+K` jumps anywhere on a laptop.
  - **Command** leads with the Day Command sentence, then one next action, then at most three signals, then an inline **consult dock**: the last exchange with your default agent (Alfred), tap to expand.
  - **The consult surface** (SPEC-v37 §2/§7): one chat surface, not three. Roster "Ask X" and a record's Inspect both open a thread with that agent, seeded with context Ian reviews before sending. A thread is attended (real Claude Code: Read/Grep/Glob/Bash/WebSearch behind opt-in capability chips, alongside the same walled `ianos` database tools every nightly run uses) and bounded to one turn at a time. Fury can convene up to 3 other agents as real subagents for a synthesized answer. Dock / expanded / full-screen, state kept per-tab, never a route.
  - **Editing where you look:** tap empty calendar space to make a block at that minute, long-press a block to drag or resize it, tap a goal's target to change it, swipe a goal row for Edit / Archive.
  - **Notes** is a real notes app (autosave, search, pin, soft delete + Undo), readable by `chief` only (the retired archivist's read grant went with it). **Roster** shows the 10 active agents and how often you took their advice; a health-gated agent (physician, coach) shows "off, health sharing" rather than a stale "spoke N days ago" when you haven't opted in.
  - **Phone PWA** ([docs/PHONE.md](PHONE.md)): Tailscale HTTPS, offline cache, **lock screen** (Face ID or password `ianos`, SPEC-v12) before any UI loads.
- **SQLite** (`data/ianos.db`): transactions, holdings, health_daily, calendar_events,
  memos, proposals, briefs, goals, focus_allocations, **facts**, **content_log**,
  plan_blocks, journal_entries, **notes**, **leads / lead_touches / call_runs**,
  **agent_invocations**, **chat_prefs / chat_threads**, **agent_acts** (Ring 1
  receipts, one-tap Undo), **attention_snoozes**, **memory_fts** (the search index)
- **Financial sync** (optional, add keys to `.env`):
  - Bank and card accounts → SimpleFIN (`make sync-chase`): $1.50/mo
  - Chase + Capital One → Plaid Trial (`make sync-plaid`): free for up to 10 Items
  - Personal brokerage and crypto accounts → SnapTrade (`make sync-fidelity`): free
  - Without keys: seed data + CSV fallbacks work out of the box
  - The CFO/wealth/chief can see the whole account set (`read_accounts`), not
    just checking, and the Money page has its own refresh button now.
- **Models:** `claude-haiku-4-5` for every nightly role run and for Fury's
  convened subagents; `claude-sonnet-5` is the default for a chat thread's own
  model setting (four plan models available per thread) and the chief's weekly
  deep brief (Sundays or `make run-weekly`). Target: <$5/mo, plus a real
  SDK-enforced dollar ceiling per run now, not just an estimate.
- **Hard rules enforced in code** (agents/runner.py, not just prompts):
  - Zero built-in tools at night, no shell, no filesystem, no web. Only the
    ianOS database tools exist, and each role has an allowlist (`ALLOWLISTS`).
    A daytime consult gets real tools, but every one of them passes through
    one runtime gate (`agents/consult_gate.py`) before it executes.
  - scout can't read transactions; only chief writes briefs; wealth can't
    create money proposals or propose a trade (blocked inside `create_proposal`).
  - Every number must trace to a table row, tools return raw rows plus
    code-computed aggregates; date math is precomputed in Python, never left
    to a model.
  - A role crash becomes a memo from "system" and the sequence continues.
  - Briefs are idempotent per (date, kind): re-running a day replaces, never duplicates.
  - A closed list of 13 Ring 1 acts (plan blocks, notes, Partner tasks, gym
    confirm, activity log, goal rebaseline/archive, transaction recategorize,
    fact unverify, attention snooze) apply immediately and are always
    receipted and undoable. Money movement, sending anything, lead stage/
    touch, journal, health values, and proposal decisions are never Ring 1,
    for any role, in any plane.
  - Proposal drafts are inert structured text. Approving one records a decision; it never sends a message, opens a provider, or performs the drafted action.

## Quickstart

```bash
make setup    # venv + deps + dashboard deps + seed demo data
make dev      # API :8787 + dashboard :5173  →  open http://localhost:5173
make run      # execute the nightly agent sequence right now
make phone    # production build + launchd serve for the iPhone PWA
make icons    # regenerate PWA icons + logo-lockup from brand sources
```

**Dashboard highlights** (after `make dev`):

| Page | What it does |
|------|----------------|
| **Command** | Day Command, review the next proposal in Inbox, +1 calls, confirm gym, ask an agent |
| **Plan** | low-friction day calendar, tap-to-block, live now-line, two-way iCloud sync |
| **Journal** | One surface: blank composer + look-back (days/photos). Private from agents. Works on phone (SPEC-v11) |
| **Beat the Clock** | **The Line**, cold-call runs with the script already written; business goals, quotas, LLC→EIN→A2P chain |
| **Body** | Gym weekday streak (confirm button), health goals |
| **Partner** | Tasks + relationship goals |
| **School** | UIUC deadlines, move-in countdown |
| **Life** | Personal admin goals |
| **Money** | Portfolio, checking, burn |
| **Memory** | Facts store: add, edit, confirm |
| **Inbox** | Review proposals, copy inert drafts, and explicitly confirm hard-to-reverse approvals |

Press **Cmd+K** (desktop nav chip or keyboard) to search pages and goals. It also
accepts `ask chief <question>` / `tell Jordan <question>`, resolved against
the live roster right in the browser — `tell` is still read-only; it does not
execute. First paint on any device shows the **lock screen** until Face ID / password unlock (SPEC-v12).

### The consult surface

SPEC-v37 §7 replaced the old Ask sheet, inspect mode, and hand-rolled rooms
with one surface: an ordinary chat thread, wherever you open it from.

- **Roster "Ask X"** and a record's **Inspect** both open (or resume) a
  thread with that agent. Inspect seeds the composer with a plain question
  about the record — you review and send it, nothing fires on its own.
- **The dock** lives inline on Command, under the Order: composer plus the
  last exchange, tap to expand. Off Command it's a small floating re-entry
  pill. **Expanded** grows the same panel bigger without taking over the
  page (desktop) or opens a bottom sheet (phone). **Full screen** is the one
  state that actually blocks the rest of the app. State lives in this
  browser tab only, never a URL.
- **Every thread is attended (Plane B).** Alongside the same walled `ianos`
  database tools every nightly run uses, a thread can use real Claude Code
  tools behind opt-in **capability chips**: Files (Read/Grep/Glob, on by
  default), Workspace (Write/Edit, scoped to a private scratch folder),
  Shell (sandboxed Bash). Every one of those calls passes through one
  runtime gate (`agents/consult_gate.py`) that denies secret paths, denies
  writing outside the scratch folder, and denies any connector write tool by
  name. Money/Mail/Calendar/School chips still gate the existing `ianos`
  read tools the same way they always did.
- **Fury can convene.** Pick up to 3 other agents and Fury delegates to them
  as real subagents in the same turn, then synthesizes with attribution kept
  visible — never a health-role agent, even if you ask.
- **Threads remember.** A thread resumes the actual prior conversation
  (native session continuity), not a quoted summary. One open thread per
  agent; picking a new agent from Roster opens (or reopens) its own thread
  without disturbing anyone else's.
- Money/Mail/Calendar chips grant read tools only after the source is
  connected; they do not auto-enable from a missing-access hint. "Refresh
  money" inside a thread re-runs the existing Plaid / SimpleFIN / SnapTrade
  loaders (same button now also lives directly on the Money page). File in
  Inbox records a draft as an inert proposal. Nothing a thread does ever
  sends anything.

The relevant API surface is:

```text
GET  /api/chat/prefs              default model + default agent
PATCH /api/chat/prefs             closed enum only
GET  /api/chat/chips              money / mail / calendar / school + connected bits
GET  /api/chat/threads            open and recent threads, no turn bodies
POST /api/chat/threads            opens one thread, closes any other OPEN for that role
GET  /api/chat/threads/{id}       thread + turn projections, no-store
PATCH /api/chat/threads/{id}      model, effort, granted chips, close
POST /api/chat/threads/{id}/turns 202 queued turn
POST /api/chat/threads/{id}/turns/{id}/file  record draft in Inbox (does not send)
POST /api/money/refresh           the Money page's own refresh, 120s cooldown
```

Chat rows, questions, verdicts, and chip grants never appear in `/api/state`.
Chat does not write memos, facts, briefs, or focus. File in Inbox records a
proposal only.

**One-time auth for agent runs** (pick one):
- Subscription token (no separate bill): in Terminal run
  `./bin/claude setup-token` (the `bin/claude` symlink targets the desktop
  app's CLI, whose `/login` is disabled), authorize in the browser, then put
  the printed token in `ianOS/.env` as `CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...`
 , all on ONE line, or
- Create `ianOS/.env` containing `ANTHROPIC_API_KEY=sk-ant-...` (per-token API billing)

Without this, `make run` logs an auth-failure memo from "system" and the
dashboard keeps serving the seeded/demo brief.

## Daily rituals

### Make calls (The Line. Beat the Clock page)

**Start a run.** Pick 5, 10 or 20. The screen dims to one lead at a time with
the number huge, the owner's name, the review that proves they miss calls, and
an opener already written from your own enrichment data.

```
Start a run → [ ▸ Start call ] → live (script + objections + notes) → one tap
```

- **Start call** fires the `tel:` link immediately, it's ringing before the
  screen finishes moving.
- **One tap logs the outcome** and advances. Any tap is undoable for 8 seconds;
  nothing ever asks you to confirm.
- **You never type a counter again.** Logging a call against a lead bumps
  `activity` in the same transaction, so your audit-call, follow-up and demo
  quotas fill themselves.
- Keyboard: `Space` start/end · `1`-`6` outcomes · `N` note · `S` skip ·
  `U` undo · `Esc` leave.

Nothing here can break. A run resets by design, and momentum is earned by
*dialing*, a no-answer counts exactly as much as a booked demo.

**The script is already written when the card loads.** Every lead arrives with
an opener, a hook, the ask, and three objection replies, composed from that
row's own enrichment, deterministic templating, no model call, nothing to wait
for. The hook uses the strongest evidence available, in order:

| | |
|---|---|
| a review proving they miss calls **and** a 24/7 claim | *"You advertise 24/7, and a review says '…never heard back'. That's the thing I fix."* |
| just the review | quotes it back |
| just the 24/7 claim | *"Who actually picks up at 9pm on a Saturday?"* |
| no website | *"Every lead you get is a phone call. What happens to the ones you miss?"* |
| a soft rating | *"You're at 4.0 across 80, usually that's response time, not the work."* |
| nothing scraped | *"You're the size where one missed call is a real week."* |

Two guards exist because you say these words out loud. Quotes are trimmed to a
sentence you can actually speak, the scraper clips them mid-word at both ends : 
and any quote that is an **accusation** ("rude", "harassing", a legal
complaint) or where the *customer* admits they were the unreachable one is
suppressed entirely, falling through to a softer hook. Four of your 86 quotes
are suppressed today.

**Nervous before a session?** Read the run cold, away from the app:

```bash
make prep
```

Prints the next 5 calls in full, number, who to ask for, their review, your
three lines, and the objection replies. `make prep N=10` for more. It opens no
run and writes nothing. The hardest call is the first one, and the dread lives
in the minutes before it, not during.

**Loading the list:**

```bash
make import-leads-dry      # report what would happen, write nothing
make import-leads          # load leads/enriched.csv
```

Import `enriched.csv` **only**: `tier_a/b/c/d.csv` are slices of it
(A+B+C+D = 1,958), so importing them separately just duplicates rows. Re-running
after a fresh scrape is safe: scores and contact details refresh, **your call
history never does**. Rows with no phone, an out-of-state address, or a
kiosk/distributor name (KeyMe, Minute Key, Johnstone Supply) are parked on
import and never reach the queue.

The queue orders itself: promised callbacks first, then leads you've spoken to,
then tier A, B, and C, north market first until you move for school, south first after. Tier D never appears.

**Looking something up.** "Browse the whole list →" on Beat the Clock opens a
search over all 1,958, by name, city, phone or owner, filtered by tier, stage
and market. It's collapsed by default on purpose: the queue is where you work,
and a 1,958-row table is the wall this whole feature exists to avoid. Unlike the
queue, the list shows everything, including parked leads and tier D.

**Closing the loop.**

```bash
make export-leads    # -> leads/exported.csv, call history filled in
make backtest        # did Fit/Pain/Reach actually predict who answers?
```

`export-leads` writes your call outcomes back into the *scraper's own* column
shape (`Call 1 Date`, `Answered?`, `Outcome`, `Next Step`…), so
`enrich_prospects.py` can re-run against reality instead of guesses.

`backtest` then asks the only question that matters about the model: **does tier
A answer more often than tier C?** If it doesn't, the ordering, which is the
entire product, is wrong, and the weights in `score_row()` need changing. It
also shows which of Fit, Pain and Reach is actually carrying the signal, so you
reweight on evidence rather than instinct.

It will tell you it doesn't have enough data until ~100 leads have been dialed,
and it means it. A contact rate off a handful of calls is noise, and tuning the
scorer on noise is worse than leaving it alone. It never edits a tier itself : 
you change `enrich_prospects.py`, re-run it, and `make import-leads`.

**What the agents see.** Dwight (scout) and Nick Fury (chief) get a read-only
view: counts by tier and stage, callbacks due and overdue, dials over 7 days,
runway math, and the next 5 leads by name. They can memo and propose: *"block
9-11am for the 4 overdue callbacks"*, but **no agent can set a stage, log a
touch, or open a run.** There is no tool that would let them. They also never
see how a calling session went beat by beat, only that dials happened.

### Log sales activity (for calls made off the line)

```bash
make log calls=12 fu=5 demos=1 note="Riverbend wants pricing"
```

Counts **increment** today's row, so log as you go. Or use **Command** / **Beat the Clock**
quick-log buttons on the dashboard. Flags: `-c` calls, `-f` follow-ups, `-d` demos,
`-v` conversations, `-n` note, `--set` to overwrite instead of increment.

### Decide proposals

Open the dashboard, read the PROPOSALS panel, APPROVE or REJECT (optionally
with a note). Your decision is written back to the blackboard as a memo from
"ian", the agents read those and learn your judgment.

### Log content & workouts (fuel for Rocky)

```bash
make content platform=site item="Riverbend case study" url=https://… note="portfolio"
make log-wellness sleep=7.5 energy=4 type=mma      # type: mma|lift|soccer|run|rest
```

### Curate the agents' memory

The **Memory** page shows every durable fact the agents remember, grouped by
domain. Use **+ Add memory** to add facts directly. Seeded personal placeholders (Partner's anniversary, siblings' birthdays,
UIUC dates) start **unconfirmed**: the agents won't trust them until you press
**Confirm** or edit them. Delete anything wrong.

### Preview tonight's run (free)

```bash
make plan     # prints who the dispatcher would wake tonight and why, no agents run, $0.00
```

## Financial sync (when you add API keys)

Copy `.env.example` → `.env`, then:

```bash
# Bank and card accounts. SimpleFIN ($1.50/mo at bridge.simplefin.org)
make setup-simplefin TOKEN=<setup-token>
make sync-chase

# Personal brokerage/crypto portfolio. SnapTrade Personal is free.
# Set SNAPTRADE_CLIENT_ID + SNAPTRADE_CONSUMER_KEY in .env. Personal keys do
# not use SNAPTRADE_USER_ID or SNAPTRADE_USER_SECRET.
make connect-fidelity    # Only if Fidelity is not already linked in SnapTrade
make sync-fidelity

# Chase + Capital One. Plaid Trial: add PLAID_CLIENT_ID, PLAID_SECRET,
# PLAID_ENV=production, and an HTTPS PLAID_REDIRECT_URI to .env. Link each
# institution once from Money → Connect bank accounts, then sync both Items.
make sync-plaid

make sync-finance        # both at once
```

Without keys, `make sync-chase` and `make sync-fidelity` skip gracefully, seed data keeps the dashboard alive.

## Connector sync (free, via Claude)

Claude's built-in connectors (Google Calendar, Gmail, Google Drive) can feed
ianOS without any paid API. Connectors live in a Claude *session*, so the flow
is: the session READS via the connector and shapes strict JSON; the loader
(`ingest/from_connector.py`) is the ONLY writer, it validates, dedupes, and
fills the same tables the dashboard renders.

One-time setup: enable Google Calendar, Gmail, and Google Drive in claude.ai →
Settings → Connectors (or `/mcp` in an interactive session) and sign in.

Then, in a `claude` session in this repo:

```
/sync-calendar    # events ±3 weeks → steward's time audit (clears personal staleness)
/sync-gmail       # prospect replies, LLC/EIN/A2P confirmations, renewals, UIUC email
/sync-drive       # contracts in Clockwork/Contracts → wakes Harvey Specter (counsel)
```

Guardrails enforced in the loader, not just prompts: connector data NEVER
writes transactions (bank CSV/SimpleFIN stays the money source of truth);
connector facts arrive **unverified**: confirm them on the Memory page before
agents trust them; connector notes are pinned to priority 1; every sync is
idempotent. Manual test without any connector:
`make sync-load source=gmail FILE=samples/connector_payload.json`.

## Plan: your day calendar (Plan page)

An low-friction daily planner: a 06:00-23:00 ribbon with a live now-line, tap an
hour to drop a time-block (one-tap suggestion chips from your goals + Day Command),
tap a block to mark it done. A block you don't finish **softens quietly, it never
turns red**. Works fully offline; no setup needed.

**Blocks can be any length.** The create sheet has both **Start** and **End**
pickers (15-minute grid) plus duration presets: `30m · 1h · 1.5h · 2h · 3h · 4h`
so a four-hour deep-work marathon is one tap, and any custom end time works.
Editing a block changes its start *and* end, so you can stretch or shrink it.
Multi-hour blocks render proportionally tall on the ribbon.

**Two-way iCloud sync** (optional) round-trips your blocks to a dedicated
**"ianOS Plan"** calendar so they appear on your iPhone, and reads your other
calendars in as read-only commitments, ianOS never modifies them.

```bash
make sync-icloud       # push/pull the plan (needs ICLOUD_* in .env, see IAN-SETUP.md)
make sync-icloud-dry   # preview what would change, no writes
```

Design laws (SPEC-v7): two stored statuses (`planned`|`done`) with "sailed" derived;
remote-wins conflicts; a local delete leaves a tombstone so it can't resurrect;
`--crit` red is absent from the whole surface. The steward reads plan-vs-done as a
task-**initiation** signal (a re-planned block → propose it as tomorrow's first block),
never as failure. Journaling is a planned follow-up (SPEC-v8).

## Journal, the nightly Shutdown (Journal page)

A private, blank-page **evening reflection**. At night the app dims into
**Shutdown**: write freely about your day, optionally attach **one photo or
video**, and press *Close the day*. Entries persist to a private timeline you
look back on, an **"On this day"** strip resurfaces prior years. Your words and
media are **yours alone**: the agents never read them. The only thing they see is
a boolean: *"Ian closed the day"*, plus a rolling count that can't break (no
streak to shame you). To hand a single entry's text to the agents, tap **Share**
(media is never shared).

Design laws (SPEC-v8): blank & promptless; **privacy is structural** : 
`/api/journal*` is refused off-localhost even with the LAN token, and journal
data never enters `/api/state` or any agent prompt; zero shame (no `--crit`, no
"missed"); the exhale is the reward. Laptop-only (AirDrop a photo to the Mac).

## The Corner. low-friction health (Body page)

Health tracking built for how an distractible brain actually works (docs/SPEC-v6-the-corner.md):

The proposed source-aware Apple Watch health-data roadmap lives in
docs/SPEC-v35-health-data-loop.md. It keeps Apple Health as the sensor ledger,
ianOS as the private decision engine, and ChatGPT Health as an optional,
separate analyst.

- **Bending streak.** Every 5 gym weekdays banks a "corner stool." Miss a day and
  the nightly run spends a stool automatically, the streak *survives* (◐ marks
  the graced day). Out of stools, it's "Round 2," never "streak broken." Zero shame,
  ever: no red on the Body page, and the chain forgives by default.
- **The Garden.** A living plant beside the streak that grows from your last 14 days
  and wilts, never dies, when you drift. No number, no label. You just see it.
- **Phone capture.** `make api-lan` serves a token-gated endpoint for three manual
  iPhone Shortcuts (Gym ✓ / Sleep / Note). Scheduled Apple Watch summaries use the
  separate source-aware v35 route, never the manual `/api/quick` endpoint. See
  docs/SHORTCUTS.md.
- **Health sharing needs your yes.** A one-time card on the Body page explains
  exactly what leaves the Mac (which logged fields, which two agents, nightly-
  prompt-only) with **Turn on / Not now**; declining still counts as answered,
  so the card doesn't nag you again. Turn it on or off any time from the
  Health details sheet. Physician and coach simply don't run until you decide
  — the Roster shows "off, health sharing" instead of a stale "spoke N days
  ago" while that's true.
- **Weekly reflection.** With explicit AI-health consent, a dedicated health role
  can save one private weekly reflection for Body; it never enters the shared memo
  board or fact store.
- **Sleep signal.** A short night can reshape the local Body cue (work after 10am,
  gym in the afternoon, no 7am anything) instead of scolding yesterday. It is not
  automatically sent to the Chief or a general agent.
- **The log.** A poop counter, one tap, with a drawn poop that plops and throws
  coils. Below it: today's count, a 7-day rail, and when the last one was.
  Optional Bristol score and note per entry, never required. **Add one you
  missed** backfills something you forgot at the time it actually happened
  (today or yesterday, four presets or an exact time, nothing in the future and
  nothing past 14 days back). Every entry is removable and the Undo restores the
  same row. No target, no percentage, no streak, no red. Counts and Bristol ride
  the same health-sharing consent as sleep and steps; the note text never leaves
  the Mac.

## Wellness & calendar

```bash
make log-wellness sleep=7.5 energy=4 workout=1
make import-health FILE=~/Downloads/health.csv
make import-calendar FILE=~/Downloads/calendar.ics
make import-fidelity FILE=~/Downloads/Portfolio_Positions.csv
```

## School: Canvas, class notes, homework (School page)

```bash
make import-canvas FILE=~/Downloads/calendarfeed.ics
make sync-syllabus                                                 # seed only, no .ics
.venv/bin/python ingest/import_canvas_calendar.py FILE --dry-run   # counts only
```

Download the `.ics` export from Canvas yourself and import the **file**. ianOS
never asks for a Canvas feed URL, token, or password: the feed URL is a bearer
secret, and the parser deliberately drops event descriptions and URLs, keeping
only titles, courses, and times. A dry run parses into an in-memory database
and writes nothing.

What you get:

- **Deadlines that block Plan.** Academic items project into the shared
  calendar, so a due date collides with a call block like any other commitment.
- **Cross homework off with one tap.** The urgency dot on each row is the
  checkbox. Finished work leaves "Next moves" and every count, then sits behind
  a "crossed off" disclosure so it stays visible and undoable. The count of what
  is done only ever goes up: there is no streak to break and no percentage.
  Completion is stored separately from the Canvas snapshot, so **re-importing
  never un-ticks something you finished.**
- **A note per real class session.** The School page and a verified class block
  on Plan both open the same daily note. Notes are private rich documents, not
  the general Notes page, and files you attach to a course live in their own
  private library (never public, always downloaded rather than previewed).
- **Study aids are off until you turn them on.** `School → study mode` is one
  local consent switch, and it is the only gate: a course's syllabus AI policy
  is shown on the page but does not block your own study aids. Turning the
  switch off stops queued work and prevents an in-flight reply from ever being
  saved.
- **Classes are listed by when they next meet.** Today's first, in time order,
  then forward through the week. A course with no meetings (an asynchronous
  one) sits last.
- **Search reads every word of every note.** Type in the notebook's search
  field and you get the notes that mention it, each with the sentence around
  every hit and the word highlighted, not just the ones whose first few lines
  happen to contain it.
- **Writing full screen.** The note takes the window: no nav, no rails, a
  wider measure and larger type. One floating bar has Notes, Details, Files,
  Finish and Exit; Escape also exits. **Cmd+B** bolds the selection, or the
  whole line when nothing is selected. **Cmd+.** (a dot) starts a bullet list
  (Cmd+Shift+. numbered). Hover a toolbar button to see its shortcut.
- **A deadline Canvas never sent** goes in `known_major_dates` in
  `data/fall_2026_school_seed.json`, then `make sync-syllabus`. Give it an
  explicit `id`. Do not insert the row into the database by hand: the next
  seed load archives anything the file does not list. This is how the Week 3
  Forensic Science deadlines got in, since ANTH 210 is asynchronous and its
  module deadlines are not in the .ics feed.

## Monthly CSV import ritual

1. Export last month's transactions from the bank as CSV (Chase: Accounts →
   Download activity → CSV).
2. `make import FILE=~/Downloads/chase_june.csv`
3. Check for uncategorized business spend (uncategorized rows don't count
   toward the burn cap):
   ```bash
   sqlite3 data/ianos.db "SELECT id,date,description,amount FROM transactions WHERE category='' ORDER BY date DESC LIMIT 20"
   sqlite3 data/ianos.db "UPDATE transactions SET category='saas' WHERE id=123"
   ```

Header names are flexible (date/description/amount in any common bank
spelling); re-imports dedup safely; real same-day duplicate charges are
preserved (see [samples/bank_sample.csv](../samples/bank_sample.csv)). Known
merchants (Anthropic, Twilio, Railway, …) auto-categorize via
`KEYWORD_CATEGORIES` in [ingest/import_csv.py](../ingest/import_csv.py).
Burn-cap categories live in `BUSINESS_CATEGORIES` in [core/db.py](../core/db.py).

## Schedule the nightly run (macOS)

```bash
make schedule   # installs + loads ~/Library/LaunchAgents/com.ianos.nightly.plist (21:30 nightly)
```

Logs land in `data/nightly.log`. To change the time, edit
[ops/com.ianos.nightly.plist](../ops/com.ianos.nightly.plist) and re-run
`make schedule`. Prefer cron? `crontab -e` and:

```
30 21 * * * cd ~/ianOS && .venv/bin/python agents/runner.py >> data/nightly.log 2>&1
```

(launchd is the better default on a laptop, cron jobs are skipped if the lid
is closed at 21:30; launchd runs the job when the machine wakes.)

## Backups (nightly, encrypted, off-site)

Every night at 21:45 an encrypted snapshot of the database, journal, documents,
lead CSVs and `.env` goes to Backblaze B2. Encryption happens on the laptop;
Backblaze stores noise it cannot read. Setup, the disaster runbook, and the
Framework/Linux migration notes: [docs/BACKUP.md](BACKUP.md). Reasoning:
[docs/SPEC-v16-backup.md](SPEC-v16-backup.md).

```bash
make backup          # snapshot now
make backup-status   # last success + recent snapshots
make backup-verify   # re-read every byte + test-restore the DB
make restore         # latest (or SNAPSHOT=<id>) into a NEW folder, never in place
make schedule-backup # install the 21:45 launchd job
```

The one sacred thing is `RESTIC_PASSWORD` in `.env`: it must also live in the
password manager and on paper. Lose it and the backups are unreadable, by design.

## Inbound from the websites (SPEC-v17 / v18 / v19)

Demo bookings and messages from **beatyourclock.com**, and messages from
**ianmccallum.com**, land in ianOS by themselves.

It's a **pull**, not a webhook: ianOS has no public URL by design and the Mac
sleeps, so the sites hold each submission in a small queue and ianOS collects
and acknowledges it whenever it's awake. Nothing is lost across a closed lid,
a dead week, or a laptop swap.

```bash
make sync-btc        # pull from beatyourclock.com
make sync-personal   # pull from ianmccallum.com
make sync-inbound    # pull every configured inbound seam once
make schedule-inbound # run every configured seam every 15 min via launchd
```

**The two rules worth knowing:**

- **A personal inquiry never becomes a lead.** `leads` is Clockwork's scored,
  tiered call queue, and its ordering guarantee is the whole feature. Messages
  from ianmccallum.com carry `source='personal'`, get no lead row and no
  deadline, and land on the **Inbox** page. Clockwork bookings land on **BtC**.
- **Good news arrives quietly, a broken promise arrives loudly.** The sites
  email you on every submission. ianOS pushes to your phone only when a demo
  is still unconfirmed and the 24-hour promise printed on `/demo` is about to
  expire. Silent 21:00-08:00.

A booked window is one tap: it writes a real touch, moves the lead's stage and
feeds `demos_last_7d`, exactly as if you'd dialed it.

Setup lives in the specs: [SPEC-v17](SPEC-v17-btc-inbound.md) (the seam),
[SPEC-v18](SPEC-v18-inbound-alerts.md) (the promise clock),
[SPEC-v19](SPEC-v19-personal-inbound.md) (the personal site + Cloudflare
Turnstile on both). Every piece is optional: unconfigured is silent, never an
error. `make schedule-btc` remains an alias for `make schedule-inbound`.

## Adding a new agent

Three edits, by design:

1. **Write the role file** `agents/roles/<name>.md`, frontmatter (`role:`,
   `codename:`, `persona:`, `active: true`, `tier:`, `day:` if weekly, `domains:`)
   plus the mandate. Steal the structure from [agents/roles/coach.md](../agents/roles/coach.md).
2. **Add one allowlist entry** in [agents/runner.py](../agents/runner.py)
   (`ALLOWLISTS["<name>"] = {...}`).
3. **Add the id to `SEQUENCE`** in [core/roles.py](../core/roles.py) where it should
   run (before `chief`). If it's a `tripwire` agent, add a check to `TRIPWIRES`
   in runner.py.

`make plan` then shows it in tonight's dispatch slate.

## Public mirror

This repo is private (`Ian-mccallum/ianOS-private`). A scrubbed mirror with none of
the private history is published as `Ian-mccallum/ianOS` for anyone who wants to read the
architecture. It is regenerated, never edited in place:

```bash
make export-public               # rebuild ../ianOS-public, leak-check it, commit
cd ../ianOS-public && git push   # publish
```

`../ianOS-public` is just the local checkout's directory name; on GitHub the
mirror is plain `Ian-mccallum/ianOS`. The export script and its templates are
private and are excluded from the mirror; the mirror's own
`docs/PUBLIC-MIRROR.md` says what differs. The law and the substitution map:
`docs/SPEC-v39-public-mirror.md` (private).

## Layout

```
core/roles.py           role loader (frontmatter) + canonical SEQUENCE
agents/runner.py        10-agent runner: dispatcher, MCP tools, allowlists, Ring 1 acts, chat
agents/consult_gate.py  Plane B (attended chat) runtime capability wall
agents/roles/*.md       agent mandates (persona + tier + domains in frontmatter)
core/db.py              schema + migrations + helpers (incl. facts store)
core/acts.py            the closed Ring 1 reversible-act list + undo handlers
core/ledger.py          the retired archivist's memo-to-fact distillation, now a function
core/memory_index.py    the FTS5 memory search index (search_memory)
core/situation.py       the nightly situation block every producer's prompt gets
core/metrics.py         goal actuals, tradeoffs, domain status, net worth, cash position
core/pillars.py         pillar summaries for dashboard (btc, body, partner, …)
core/plan.py            day-plan derivations: sailed, suggestions, free-slot (pure)
core/journal.py         journal derivations: day-attribution, rolling count, on-this-day (pure)
dashboard/src/lib/poop.js  the log's derivations: rail levels, the day's line, backfill bounds (pure)
core/leads.py           lead queue order, call script, run/heat math (pure, no model call)
api/main.py             FastAPI dashboard API (state, facts, goals, gym, /api/day, leads, runs)
dashboard/              Vite/React mission control: pillar pages, Command, Plan, Memory, Cmd+K
dashboard/src/pages/    CommandPage, PlanPage, NotesPage, RosterPage, JournalPage, …
dashboard/src/components/LockScreen.jsx  SPEC-v12 unlock gate (Face ID / password)
dashboard/src/lib/lock.js               WebAuthn + password + session / re-lock
dashboard/src/lib/swipe.js    pillar swipe ring: edge exclusion, axis lock, opt-outs
dashboard/src/lib/agents.js   agent identity (colour, glyph, cadence, trust) in ONE place
dashboard/public/ianOS.jpg    app icon source → `make icons` → public/icons/*.png
dashboard/public/logo.png     site logo source → logo-lockup.png for chrome
.claude/skills/osui/    the interface law, loaded before any UI work
.claude/skills/data/    the data law: schema, write boundaries, privacy walls, backups
dashboard/src/components/TheLine.jsx     the call loop, brief → live → outcome
dashboard/src/components/PoopLog.jsx     Body's log: tap, burst, rail, backfill
dashboard/src/components/PoopMark.jsx    the one poop in the product (drawn, not the emoji)
ingest/                 CSV + SimpleFIN + SnapTrade + iCloud CalDAV + content/wellness loggers
ingest/import_leads.py  the ONLY bulk writer for leads (re-import never wipes call state)
ingest/export_leads.py  leads -> CSV with real call history, for re-enrichment
scripts/backtest_leads.py  did Fit/Pain/Reach predict who answers? (reports, never rewrites)
scripts/prep_calls.py   print the next calls + full scripts, to read before dialing
scripts/make_icons.py   PWA icons + logo lockup from brand sources
scripts/export_public.py       builds the scrubbed public mirror (private, never exported; SPEC-v39)
scripts/public_export/         the mirror's templates: public README, sample dossier, CI, screenshots
leads/                  Clockwork's scraper + enricher + the CSVs (gitignored: real contacts)
scripts/seed.py         multi-domain demo data (goals, facts, LLC chain deps)
docs/SPEC-v5-ian-personal-dashboard.md   v5 dashboard spec (shipped)
docs/SPEC-v7-plan.md                     v7 Plan spec: day calendar + iCloud (shipped)
docs/SPEC-v8-journal.md                  v8 Journal spec: nightly Shutdown + media (shipped)
docs/SPEC-v9-the-line.md                 v9 The Line, lead pipeline + call loop (shipped)
docs/SPEC-v10-osui.md                    v10 osUI, mobile-first UI law + Notes + Roster (shipped)
docs/SPEC-v11-journal-delight.md         v11 Journal one-surface + phone unlock (shipped)
docs/SPEC-v12-lock-screen.md             v12 PWA Face ID / password lock (shipped)
docs/SPEC-v13-impeccable-mobile.md       v13 mobile PWA audit + fix pass (shipped)
docs/SPEC-v14-impeccable-web.md          v14 desktop/web audit + fix pass (shipped)
docs/SPEC-v15-plan-calendar.md           v15 Plan calendar, both surfaces (shipped)
docs/PHONE.md                            phone install, Tailscale, icons, Face ID
docs/BACKUP.md                           backup setup, disaster runbook, Linux migration
scripts/backup.sh + scripts/restore.sh   the SPEC-v16 engine (restic + B2, encrypted)
ingest/sync_btc.py      the ONLY writer on both website seams (SEAMS = btc | personal)
core/promises.py        the promise clock: pure, no clock of its own, no model
docs/SPEC-v2-dispatcher-deck.md          the v2 agent dispatcher spec
docs/SPEC-v37-agent-rebuild.md           v37: Ring 1/2, the ledger + memory index, the consult surface (shipped)
docs/SPEC-v38-learning.md                v38: a drafted, unbuilt spec for a personal-topics Learning pillar
data/ianos.db           SQLite (gitignored) · data/dispatch.log nightly decisions
```
