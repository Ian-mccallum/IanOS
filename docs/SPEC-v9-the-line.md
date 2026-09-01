# ianOS v9: "The Line" (lead pipeline, the call loop, and the run)

**Status:** **Shipped in full 2026-07-28**. Phases A-E (see §12).
Written from the profile of `leads/*.csv` on 2026-07-28.
**Audience:** an implementing agent with no prior context. Read this file + the
repo; verify every "current state" claim with the greps in §0 before coding.

**What shipped:** `leads`/`lead_touches`/`call_runs` tables + helpers in
`core/db.py`; `core/leads.py` (queue, `call_card`, transitions, run/heat math);
`ingest/import_leads.py`; `/api/leads/*` + `/api/runs/*` including the undo;
`dashboard/src/components/TheLine.jsx` (all three beats, call mode, undo, ma,
keyboard); the `ActionStack` swap; the aurora `bloom` prop; `read_pipeline` for
scout + chief; `LeadList.jsx`; `ingest/export_leads.py`;
`scripts/backtest_leads.py`; `scripts/prep_calls.py` (`make prep`, read a run
before dialing it). 105 tests across `tests/test_leads.py`,
`tests/test_leads_api.py` and `tests/test_agents_guards.py` (232 in the repo
overall). The real 1,958 rows are imported: 25 A / 426 B / 853 C / 654 D,
131 parked; 1,254 are callable.

**Deviations from this spec as written, and why:**
- The Beat-3 card carries **six** outcome buttons plus `Call back in 2 days`
  and `Bad number` as secondary controls, rather than seven equal buttons : 
  `bad_number` is rare and does not deserve primary weight.
- `TheLine.jsx` keys its card by **lead, not by phase**. Keying by phase
  deadlocked `AnimatePresence mode="wait"` (the card froze on the brief while
  the timer ran), and it also contradicted §5's "the brief recomposes, it does
  not disappear". Keep it keyed by lead.
- `_clean_quote` (§6) grew well beyond a trim, because everything it produces
  is **read aloud to a stranger**. Raw `Miss Signal` values are clipped mid-WORD
  at *both* ends (~10% end mid-word: "they over look everything, every com"), so
  it snaps to the sentence around the complaint phrase and trims a partial word
  off whichever end it failed to snap. Whether the scraper cut mid-word is
  unknowable from the text, so the tail uses a length heuristic, every real
  stub in the data is 1-3 chars, every legitimate ending is longer, with a
  whitelist so "never called back" does not lose its last word.
- **`quote_is_readable()` is new and not in the original spec.** The scraper's
  miss-signal sweep also catches (a) accusations rather than missed-call
  complaints: "rude", "harassing", "legal department", "scam": and (b)
  reviews where the *customer* admits **they** were the unreachable one ("there
  were times when I was unresponsive to calls from the office"). Both are
  actively harmful to say on a live call: the first ends it, the second is
  simply false. An unsafe quote is suppressed and the hook falls through to the
  next-strongest evidence. 4 of the 86 real quotes are suppressed today,
  including the leads that were ranked #3, #4 and #5 in the queue.

  This is the general lesson for anyone extending `call_card()`: **the output is
  speech, not text.** A field that merely looks fine in JSON can still be
  unsayable, false, or hostile out loud, and the cost lands on Ian mid-call.

**Thesis:** Ian has **1,304 callable leads and 19 weekdays** before school
collapses his selling time to ~5 hrs/week (1,304 = tiers A+B+C in the raw file;
**1,254 after the import parks junk and out-of-market rows**, §1). At his
20-calls/day quota he reaches
**380 of them. 29%.** So The Line has exactly two jobs:

1. **Order**, guarantee the 380 calls he makes are the best 380 in the file,
   and that a promised callback never falls on the floor.
2. **Motion**, make picking up the phone the lowest-energy action on the
   screen, and make doing it twenty times in a row feel like *playing something*
   rather than *grinding something*.

Job 2 is not decoration. Cold calling fails for distractible founders at the moment of
**initiation**, not execution: the dread lives in the three seconds before the
dial, and it compounds with every call already made. A tracker that only
*records* calls optimizes the wrong half of the problem. **The call loop is the
feature. The database is scaffolding for it.**

---

## Design laws

These are fences. A change that violates one is wrong even if it tests green.

**Zero shame, structurally, not cosmetically.**
- `--crit` (#f87171) is banned on this page, as on Plan and Shutdown.
- **Nothing that can break.** No streak, no "days since", no decaying score that
  carries between sessions. Every run starts at zero and **zero is neutral**.
- **Momentum is earned by dialing, never by outcome.** A no-answer advances the
  run exactly as much as a booked demo. Ian controls whether he dials; he does
  not control whether they pick up. Rewarding the second teaches him to fear the
  phone. This is the single most load-bearing rule in the document.
- No percentages, no conversion rate, no "1,278 remaining" doom counter shown to
  Ian, ever. Those numbers exist for agents (§9) and nowhere else.

**The lead is the content.** ~80% of the visual weight is one lead. Chrome, nav
and stats are scaffolding. There is never a table on screen during a call.

**One tap, two truths.** Logging an outcome writes the lead's disposition *and*
increments `activity` in the same transaction. Ian never types a counter again.

**Ian owns outcomes; agents own observations.** Only Ian moves a stage. Agents
READ and PROPOSE. Enforced in code, like the money rule.

**The scoring model is Ian's.** `enrich_prospects.py` already scores Fit/Pain/
Reach and assigns tiers. The Line **imports and obeys** it, never re-scores.

**Delight is committed or absent.** Full animation, or an instant swap under
`prefers-reduced-motion`. No half-hearted transitions (v7 law, carried forward).

**A re-import must never destroy call history.**

---

## 0. Current state to verify first

```bash
grep -n "CREATE TABLE IF NOT EXISTS activity" -A 10 core/db.py   # the counters to feed
grep -n "def log_activity" -A 25 core/db.py                      # increment-vs-replace helper
grep -n "audit_calls_today\|follow_ups_today\|demos_last_7d" core/metrics.py
grep -n "ALLOWLISTS" -A 15 agents/runner.py                      # scout's tool set
grep -n "PAGES = " dashboard/src/App.jsx                         # hash-router page list
grep -n "auditDone < auditTarget" -B 4 -A 6 dashboard/src/components/ActionStack.jsx
grep -n "shutdown-mode" dashboard/src/App.jsx dashboard/src/styles.css  # THE MODE PRECEDENT
grep -n "MOVE_IN_DATE" core/pillars.py                           # 2026-08-19, drives market order
grep -n "useReducedMotion" dashboard/src/pages/PlanPage.jsx      # motion conventions
grep -n -- "--crit is deliberately absent" dashboard/src/styles.css
```

**Design system facts (verified 2026-07-28).** Dark glass: `--bg #04050a`,
`--glass`, `--glass-border`; accent `--accent #6ea8ff`; semantic `--good
#4ade80`, `--warn #fbbf24`, `--crit #f87171` *(banned here)*; type `--sans`
Space Grotesk + `--mono` JetBrains Mono; `--n-hero 40px`; spacing `--s1..--s7`.
Motion is **`motion/react`** (not framer-motion) and every animated page imports
`useReducedMotion`. Per-feature accent colors are an established pattern
(`--partner`, `--partner-glow`, `--partner-soft` at styles.css:1325).

> **Aesthetic note for the implementer.** If you arrive here via `/skill-ui`,
> ignore its default palette. Gore-core red, glitch artifacts and indie-sleaze
> grain are wrong for this product: `--crit` red is *banned* on this surface by
> product law, and a shame-free page cannot be styled with horror cues. Take the
> method (content-first hierarchy, reduction to essentials, typography as
> object, darkness with the subject as light) and render it in ianOS's existing
> calm glass system.

---

## 1. What is actually in `leads/` (profiled, do not re-derive)

Seven CSVs, but **not seven lists**. `scrape_prospects.py` → `prospects.csv`
(1,958 rows) → `enrich_prospects.py` → `enriched.csv` (1,958 rows, 41 cols) →
four tier files + `email_ready.csv`.

| File | Rows | What it is |
|---|---:|---|
| `enriched.csv` | 1,958 | **The superset. Import this and only this.** |
| `prospects.csv` | 1,958 | Pre-enrichment; same businesses. Ignore. |
| `tier_a_call_first.csv` | 25 | View: `WHERE tier='A'` |
| `tier_b_high_value.csv` | 426 | View: `WHERE tier='B'` |
| `tier_c_working.csv` | 853 | View: `WHERE tier='C'` |
| `tier_d_skip.csv` | 654 | View: `WHERE tier='D'` |
| `email_ready.csv` | 542 | View: `WHERE email != '' AND tier != 'D'` |

**A+B+C+D = 1,958 = enriched.** A clean partition, no cross-file dedupe
problem, and importing the tier files separately would only create duplicates.

Profile facts that drive the design:

- **Phone is a perfect key.** 1,892/1,958 (96.6%) normalize to 10 digits;
  **zero duplicates.** 64 blank, 2 unparseable (extensions).
- **Zero call history.** All eight call-log columns are empty in all 1,958 rows.
  Clean slate. **Do not import them**: `lead_touches` replaces them.
- **`Total` = `Fit` + `Pain` + `Reach`, exactly, 0 exceptions.** Tier is *not* a
  Total threshold: D is a **disqualification** (franchise / competitor tool / no
  phone), which is why D spans Total −9…9 and overlaps A/B/C.
- **Two markets:** `north` = Naperville-Aurora (1,286, the current market);
  `south` = Champaign-Urbana + Bloomington-Normal (672, where he moves
  for school).
- **`Why` is a pre-written rationale**, e.g. `right-size shop; review complains
  of no answer; PROMISES 24/7 AND MISSES CALLS; ask for Pat`. It is the raw
  material for the call script (§6).
- **`Miss Signal` is a quoted customer review proving they miss calls.** 86 rows
  have one; **23 of the 25 tier-A rows do.** With `Claims 24/7` (664 rows) it is
  the strongest pitch Clockwork has. 18 A/B/C leads have both.

### Two data bugs to fix at the import boundary

1. **Out-of-market bleed. 14 rows, 5 in A/B.** The scraper matched the wrong
   Bloomington. The **#1 ranked lead in the file**. Hillside Properties,
   `Total=17`, the only 17, is in Bloomington, **Indiana**. Also MN, CA, OH.
   Rule: parse the state from `Address`; non-`IL` imports `parked`.
2. **Kiosk / distributor junk. 53 rows, 41 of them queue-bound** (B:15, C:26).
   `KeyMe Locksmiths` ×36, `Minute Key` ×7, `Key Center at The Home Depot` ×6
   are unstaffed key-cutting **machines**; `Johnstone Supply` ×4 is a parts
   **distributor**. Rule: a `JUNK_NAMES` list forces `parked`.

~46 dead calls kept out of the queue: **2.3 of Ian's 19 remaining weekdays.**

---

## 2. Data (Phase A)

### Schema (append to `SCHEMA` in `core/db.py`)

```sql
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_norm    TEXT UNIQUE,                  -- 10 digits; the import key
    phone         TEXT NOT NULL DEFAULT '',
    business_name TEXT NOT NULL,
    owner_name    TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    city          TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL DEFAULT '',
    market        TEXT NOT NULL DEFAULT '',     -- north | south
    segment       TEXT NOT NULL DEFAULT '',     -- trades | property | emergency
    service_type  TEXT NOT NULL DEFAULT '',
    -- the enricher's model, imported as-is, never recomputed here
    tier          TEXT NOT NULL DEFAULT 'C' CHECK (tier IN ('A','B','C','D')),
    fit           INTEGER NOT NULL DEFAULT 0,
    pain          INTEGER NOT NULL DEFAULT 0,
    reach         INTEGER NOT NULL DEFAULT 0,
    total         INTEGER NOT NULL DEFAULT 0,
    why           TEXT NOT NULL DEFAULT '',
    miss_signal   TEXT NOT NULL DEFAULT '',     -- the review quote, the ammunition
    claims_247    INTEGER NOT NULL DEFAULT 0,
    rating        REAL,
    reviews       INTEGER,
    website       TEXT NOT NULL DEFAULT '',
    site_status   TEXT NOT NULL DEFAULT '',     -- ok | none | failed
    platform      TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    maps_url      TEXT NOT NULL DEFAULT '',
    -- state Ian owns. NEVER written by the importer on an existing row.
    stage         TEXT NOT NULL DEFAULT 'new'
                  CHECK (stage IN ('new','attempted','reached','demo','won','lost','parked')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_touch    TEXT,
    next_touch    TEXT,
    notes         TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'enriched.csv',
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Events, not tallies (the streak_events precedent). One row per touch, ever.
CREATE TABLE IF NOT EXISTS lead_touches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    run_id     INTEGER REFERENCES call_runs(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('call','follow_up','demo','email','text')),
    outcome    TEXT NOT NULL DEFAULT '' CHECK (outcome IN
                 ('','no_answer','voicemail','gatekeeper','reached',
                  'booked','not_interested','bad_number')),
    duration_s INTEGER NOT NULL DEFAULT 0,      -- from the in-call timer
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- A "run" is one bounded calling session. It is the unit of the game (§7).
-- Runs never carry a penalty forward; they exist to be finite.
CREATE TABLE IF NOT EXISTS call_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    ended_at   TEXT,
    target     INTEGER NOT NULL DEFAULT 10,     -- the run's chosen size
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_leads_stage  ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_tier   ON leads(tier);
CREATE INDEX IF NOT EXISTS idx_leads_next   ON leads(next_touch);
CREATE INDEX IF NOT EXISTS idx_touches_lead ON lead_touches(lead_id);
CREATE INDEX IF NOT EXISTS idx_touches_date ON lead_touches(date);
CREATE INDEX IF NOT EXISTS idx_runs_date    ON call_runs(date);
```

### `ingest/import_leads.py`: the only bulk writer

Mirrors the "money is sacred" boundary of `import_csv.py`.

```
.venv/bin/python ingest/import_leads.py leads/enriched.csv
.venv/bin/python ingest/import_leads.py leads/enriched.csv --dry-run
```

- Key on `phone_norm` (`re.sub(r"\D","",phone)`, strip leading `1`, require 10).
- **Insert** → full row. **Conflict** → refresh *scored/scraped* columns only
  (`tier, fit, pain, reach, total, why, miss_signal, claims_247, rating,
  reviews, email, owner_name, website, site_status, platform, address,
  maps_url`). **Never** touch `stage, attempts, last_touch, next_touch, notes`.
  This is what makes re-scraping safe; it gets its own test.
- No phone → `parked`, `notes='no phone'`. Non-IL → `parked`,
  `notes='out-of-market (IN)'`. `JUNK_NAMES` → `parked`, `notes='kiosk/distributor'`.
- Tier D imports normally but **never enters the queue**. Inventory, not a task.
- Writes `ingest_log` source `'leads_csv'` + one `system` memo with counts.

### `core/leads.py`, pure functions (unit-tested, no network, no LLM)

```python
norm_phone(raw) -> str
market_priority(today, move_in=MOVE_IN_DATE)   # ('north','south') before, flipped after
rest_days(attempts) -> int                     # 3, 5, 8: a lead rests longer each miss
is_resting(lead, today) -> bool
call_queue(conn, today, limit) -> list[dict]   # THE ordering function (§3)
queue_reason(lead, today) -> str               # "promised callback" | "tier A · proof of pain"
call_card(lead) -> dict                        # THE SCRIPT (§6): deterministic, no model
next_stage(stage, outcome, attempts) -> str    # transition table
run_state(conn, run_id, today) -> dict         # dialed, heat, milestones (§7)
pipeline_stats(conn, today) -> dict            # for agents only
runway(conn, today) -> dict                    # for agents only
```

---

## 3. The queue (ordering)

`call_queue()` is **pure Python, deterministic, never a model call**, the same
posture as `should_run()` and `suggest_blocks()`.

| # | Band | Rule | Sort within band |
|---|---|---|---|
| 0 | **Promised** | `next_touch <= today`, stage ∉ (won, lost, parked) | `next_touch` asc |
| 1 | **Warm** | `stage='reached'`, no demo booked | `last_touch` asc |
| 2 | **Tier A** | `stage='new'`, `tier='A'` | `total` desc |
| 3 | **Tier B** | `stage='new'`, `tier='B'` | market-priority, `total` desc |
| 4 | **Second pass** | `stage='attempted'`, `attempts < 4`, rest expired | `total` desc |
| 5 | **Tier C** | `stage='new'`, `tier='C'` | market-priority, `total` desc |

**Tier D and `parked` never appear.** Capped at the remaining daily quota
(`20 − activity.audit_calls today`), so the queue empties as he works and is
never a wall.

**Market priority is date-aware.** Before `MOVE_IN_DATE` (2026-08-19), `north`
outranks `south`. On and after, it flips, he's in Champaign and the 672
southern leads become the ones he can drive to. `core/pillars.py` owns the date.

**Rest, not shame.** An unanswered call sets `stage='attempted'` and the lead
rests `rest_days(attempts)`. 3, then 5, then 8 days. At **4 attempts with no
contact** it moves to `parked` automatically. Never "overdue," never red, never
counted against him. The gym streak's forgiveness rule, applied to a pipeline.

### Transition table (`next_stage`, enforced in code)

| outcome | → stage | `activity` bump |
|---|---|---|
| `no_answer`, `voicemail`, `gatekeeper` | `attempted` (+1, rest) | `audit_calls +1` |
| `reached` | `reached` | `audit_calls +1`, `conversations +1` |
| `booked` | `demo` | `audit_calls +1`, `demos +1` |
| `not_interested` | `lost` | `audit_calls +1` |
| `bad_number` | `parked` |: (a dead number is not a call) |
| kind `follow_up` | per above | `follow_ups +1` instead of `audit_calls` |

This is why **no goal or metric in the repo changes**: `audit_calls_today`,
`follow_ups_today` and `demos_last_7d` resolve exactly as today, now fed by real
events. `activity.conversations`: currently written by nothing but a CLI flag : 
comes alive for free.

---

## 4. API (`api/main.py`)

| Route | Purpose |
|---|---|
| `GET /api/leads/queue?limit=` | Ordered queue, each with `queue_reason` **and `call_card`** |
| `GET /api/leads?tier=&stage=&market=&q=&limit=&offset=` | Searchable list (paged; the detour) |
| `GET /api/leads/{id}` | One lead + full touch history |
| `POST /api/leads/{id}/touch` | `{kind, outcome, note, next_touch, duration_s, run_id}` → touch + stage + `activity` bump, **one transaction** |
| `DELETE /api/leads/touches/{touch_id}` | **Undo**, reverses the touch, the stage, and the `activity` bump (§8) |
| `PATCH /api/leads/{id}` | `stage`, `notes`, `next_touch`, manual override |
| `POST /api/runs` / `POST /api/runs/{id}/end` | Open / close a run |
| `GET /api/runs/current` | Live run state: dialed, heat, milestones |
| `GET /api/leads/stats` | Counts + runway (agent-facing numbers; not rendered to Ian) |

- The queue endpoint returns the **fully composed `call_card`** so the brief is
  present the instant the card mounts, no second request, no spinner at the
  moment of highest anxiety. Prefetch depth 3.
- Memo policy: a memo from `"ian"` on **outcomes that matter** (`booked`,
  `not_interested`, `won`, `lost`) so agents learn his judgment. **No memo on a
  routine no-answer**. 20 memos/day would drown the blackboard.
- `/api/state` gains only `{queue_len, next_lead, callbacks_due, run}`. **Not
  the 1,958 rows**, the SPA polls this every 15s.
- Add `"leads": True` to `/api/health` features.

---

## 5. The call loop, three beats

**Call Mode is a MODE, not a modal.** When Ian starts a call the app shell dims
and The Line takes over the viewport. This is the existing `shutdown-mode`
pattern (a class on `.app-shell`, see ShutdownPage/SPEC-v8), reused, not a new
paradigm and not a dialog. Vaughn Oliver's rule rendered in this design system:
**darken everything, and the lead is the only light.**

Reuse the exact mechanism, verified: `App.jsx:586` puts `shutdown-mode` on
`.app-shell`, and `styles.css:2103` dims `.nav-wrap` / `.page-header` to
**opacity 0.22** over 0.4s, restoring to 0.6 on hover. Add `call-mode` beside it
with the same values, do not invent a second dimming scale. `Esc` exits at any
time and never loses state.

```
     ┌──── BEAT 1 ─────┐   ┌──── BEAT 2 ────┐   ┌──── BEAT 3 ────┐
     │   THE BRIEF     │ → │      LIVE      │ → │    THE CARD    │
     │   ~6 seconds    │   │   the call     │   │   one tap      │
     └─────────────────┘   └────────────────┘   └────────────────┘
              ↑                                          │
              └──────────  next lead, 400ms  ─────────────┘
```

### Beat 1. The Brief (pre-call)

Everything he needs to dial with confidence, nothing else. One lead, centered,
large. The phone number is the largest typographic object on the screen : 
Carson's "typography as image," except the image is the thing he must act on.

```
┌──────────────────────────────────────────────────────┐
│  ◆ TIER A · proof of pain              run 3 of 10   │
│                                                      │
│  Lakeshore Heating and Cooling                          │
│  Plainfield · HVAC contractor · 4.6 ★ 63 reviews     │
│                                                      │
│         (630) 555-0142           ← --n-hero, mono    │
│         ask for Sam                                 │
│                                                      │
│  ❝ called three times, never heard back ❞            │
│                         : their own review          │
│                                                      │
│  ─────────────────────────────────────────────       │
│  OPEN     "Hi, is Sam around? … I'm Ian, I'm        │
│            local here in Plainfield."                │
│                                                      │
│  HOOK     "You advertise 24/7: but a review says    │
│            someone called three times and never      │
│            heard back. That's the thing I fix."      │
│                                                      │
│  ASK      "Can I send a 2-minute audit of what your  │
│            phone missed last week?"                  │
│  ─────────────────────────────────────────────       │
│                                                      │
│            [  ▸  START CALL  ]        [ skip ]       │
└──────────────────────────────────────────────────────┘
```

**The impossible moment (Teller).** `START CALL` fires the `tel:` link
**immediately**, the phone is already dialing before the brief finishes its
400ms transition into Live. Ian expects *read, then dial*. Instead it's already
ringing and the script arrives in time. The gap between intention and action
collapses to zero, which is precisely where task initiation fails. It is one
button and it is fully committed: no confirm, no "are you ready?", no second
step.

The `Skip` control exists and is deliberately quiet, skipping costs nothing,
records nothing, and shames nothing. It re-queues the lead at the back of its
band.

### Beat 2. Live (during the call)

The brief does not disappear, it **recomposes**. Adrià's deconstruction: same
ingredients, transformed. The script stays; the dial affordance becomes a timer;
a note field slides in under the thumb.

```
┌──────────────────────────────────────────────────────┐
│  ● live  0:47                    Lakeshore Heating      │
│                                                      │
│  OPEN  ✓ (dimmed once 20s elapse: you're past it)   │
│  HOOK     "You advertise 24/7, but a review says…"  │
│  ASK      "Can I send a 2-minute audit…"             │
│                                                      │
│  IF THEY SAY…                                        │
│    "we're fine"    → "What happens to the 6pm call?" │
│    "send email"    → "What address? I'll send now."  │
│    "not the owner" → "When's Sam usually in?"       │
│                                                      │
│  ┌────────────────────────────────────────────────┐  │
│  │ notes…                                         │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
│           [ end call → log outcome ]                 │
└──────────────────────────────────────────────────────┘
```

- **The timer is elapsed, never a target.** It counts up. It is `--dim`, small,
  and never turns a warning color. It exists so `duration_s` is real data, not
  to pressure him.
- **Objection cards are pre-written per `segment`** (trades / property /
  emergency): three lines, chosen deterministically. The panic moment in a cold
  call is the objection, and a founder should not be composing under load.
- **The `OPEN` line dims after 20 seconds.** A tiny lived-in detail (Miyazaki):
  the script quietly tracks where he probably is in the call. Nothing is
  enforced; it just breathes with him.
- Notes autosave to local state; they land on the touch row at log time.

### Beat 3. The Card (post-call)

One tap. Six outcomes, ordered by real-world frequency so the most likely is the
easiest target (~70% of cold calls are no-answer/voicemail).

```
┌──────────────────────────────────────────────────────┐
│  How'd it go?                                        │
│                                                      │
│   [ No answer ]  [ Voicemail ]  [ Gatekeeper ]       │
│   [ Reached ]    [ Booked demo ]                     │
│   [ Not interested ]         [ Bad number ]          │
│                                                      │
│   ⟲ call back →   (date picker, defaults +2 business)│
└──────────────────────────────────────────────────────┘
```

**The button becomes the receipt (Adrià's deconstruction).** The tapped outcome
expands to fill the card and *becomes* the confirmation line, the same element,
transformed, via a `layoutId` shared-element transition. It does not disappear
and get replaced by a toast; it *is* the toast. Same ingredients.

**Then the layers fire, in this sequence** (order matters):

| # | Layer | Detail |
|---|---|---|
| 1 | Core | `POST /api/leads/{id}/touch`, optimistic |
| 2 | Visual | Outcome button morphs to receipt, `springs`-style spring |
| 3 | Haptic | `navigator.vibrate(10)` where supported |
| 4 | Counter | The run tally ticks: **one tick for any outcome** |
| 5 | Ma | A held beat (§8) before the next lead |
| 6 | Milestone | Only at thresholds (§7) |

---

## 6. `call_card()`: the script writes itself

Pure Python in `core/leads.py`. **Deterministic templating from the row: not an
LLM call.** Rejected alternative: generating the script with Haiku per lead. It
would cost money on every dial, add latency at the exact moment Ian needs zero
latency, and the enricher already computed the reasoning (`Why`). Determinism
here is consistent with "LLM only for narration" and keeps the queue free.

```python
def call_card(lead: dict) -> dict:
    """-> {ask_for, open, hook, ask, objections: [{trigger, reply}], evidence}"""
```

**`hook` is chosen by the strongest available signal, in this order:**

| Priority | Condition | Hook |
|---|---|---|
| 1 | `miss_signal` **and** `claims_247` | *"You advertise 24/7, and a review says someone called three times and never heard back. That's the thing I fix."* |
| 2 | `miss_signal` only | Quote the review back verbatim. |
| 3 | `claims_247` only | *"You promise 24/7, who picks up at 9pm on a Saturday?"* |
| 4 | `site_status` ∈ (`none`,`failed`) | *"You don't have a site up, so every lead you get is a phone call. What happens to the ones you miss?"* |
| 5 | `rating < 4.3` and `reviews >= 30` | *"You're at {rating} across {reviews}: usually that's response time, not the work."* |
| 6 | fallback | *"You're the size where one missed call is a real week."* |

`ask_for` uses `owner_name` when present (24.5% of rows): *"ask for Sam"* : 
otherwise *"whoever handles the phones."* `evidence` carries the raw
`miss_signal` for the pull-quote.

**The second impossible moment (Teller).** Ian never wrote this script. It
composes out of a review *the business's own customer left*, surfaced at the
exact second he needs ammunition. He didn't know that quote was in the file. The
prestige is that the data he scraped three weeks ago hands him his opening line
while the phone is ringing.

---

## 7. The game layer: "the run"

The framing is a **run**, not a streak: a bounded session with a start, a size,
and an end. Roguelike, not Duolingo. **You cannot break a run, you finish it or
you stop, and stopping costs nothing.** This is the shame-free structure: the
thing that resets by design cannot be lost.

### Starting a run

The Line's resting state on Beat the Clock is a single control:

```
┌──────────────────────────────────────────┐
│  THE LINE                                │
│  4 callbacks owed · 3 tier-A left        │
│                                          │
│      [ ▸ start a run ]                   │
│         5 · 10 · 20                      │
└──────────────────────────────────────────┘
```

Three sizes. **5 exists because on a bad day 5 is the whole win**, the attention
escape hatch that makes starting possible. Default to 10. The chosen size is
`call_runs.target`.

### Heat, momentum that cannot betray him

`heat` is a run-scoped 0-5 value. **It increments on every logged dial,
regardless of outcome.** A no-answer is worth exactly as much as a booked demo.

- It **decays one step per 4 idle minutes** inside a run, cooling is neutral
  and silent, never announced, never red.
- It **does not persist between runs.** Each run starts cold, and cold is fine.
- It renders as the accent glow intensity on the card border (`--line-glow`),
  nothing more. **No number, no bar, no label.** It's felt, not read.

This is the rule that makes the game ethical: it rewards the only variable Ian
controls. A design that rewarded connects would teach him that dialing a
non-answerer was wasted effort, the exact belief that kills a cold-call habit.

### Milestones

Rare, earned, and quiet. Fired at:

- **Run complete** (dialed == target): the big one.
- **First `booked` of the day.**
- **A tier-A lead worked**, there are only 25 in existence.
- **Last tier-A lead**, a one-time event, ever.

The reward is **the existing `AuroraBackground`**, not confetti. On a milestone
the aurora blooms once, a slow, wide pulse of `--accent-glow` behind the dimmed
shell, 1.2s, then gone. It is ianOS's own visual language rather than a generic
particle library, and it is quiet enough to fire at 11pm without feeling like a
slot machine.

*Implementation note:* `AuroraBackground.jsx:45` currently takes **no props** and
reads `prefers-reduced-motion` internally at line 50. The bloom is therefore not
free, add a `bloom` prop (a counter that the page increments) and a
`useEffect` that runs one canvas pulse per change, keeping the existing internal
reduced-motion guard as the authority. Do not fork the component.

### The run summary (the end of the run)

```
        ten calls.

        3 conversations · 1 demo booked
        Lakeshore Heating wants a callback Thursday

        [ run again ]        [ that's the day ]
```

Numbers, no percentage, no comparison to yesterday, no "you're 60% to quota."
Then **stillness**, the summary holds for a beat before the buttons fade in.

> **What is deliberately absent:** XP, levels, badges, leaderboards, daily
> streaks, combo multipliers on *outcomes*, any counter that persists and can
> therefore be broken. Every one of those imports shame through the back door.
> The game is: a finite run, a warm glow while you're moving, and a quiet
> bloom when you finish.

---

## 8. Motion, ma, and the undo

**Motion system.** `motion/react`, matching every other page. `useReducedMotion`
is mandatory; under reduce, every transition below becomes an instant swap and
the aurora bloom does not fire. Animate `transform`/`opacity` only.

| Moment | Motion | Duration |
|---|---|---|
| Enter call mode | Shell dims, card rises 12px + fades | 320ms, ease-out |
| Brief → Live | Script stays put (`layoutId`), dial → timer morph | 400ms spring |
| Outcome tap | Button expands into receipt (`layoutId`) | 380ms spring |
| Receipt → next brief | Old card exits left, new enters right | 400ms |
| Milestone | Aurora bloom | 1.2s |
| Exit call mode | Shell un-dims | 240ms |

### Ma (間), the pause is the reward

**After a `reached` or a `booked`, do not serve the next lead.** Hold. The
screen shows the receipt and nothing else for a beat, and the "next" affordance
fades in *after* ~1.4s. He must wait, and the wait is the point, it is where
the win registers.

After a `no_answer` the loop is fast (400ms), no dwelling on a non-event, and
critically **no commentary**. The receipt says `No answer · logged` and moves.
It never says "that's okay!" or "keep going!", encouragement after a non-event
implies something needed forgiving. Nothing did.

At the end of a run, the summary holds ~2s before the buttons appear (matching
`ShutdownPage`'s done-state cadence, which already does exactly this).

### The impossible undo (Teller)

**No confirmation dialog exists anywhere in this feature.** Every outcome is
instant and every outcome is reversible for 8 seconds via an `Undo` on the
receipt. `DELETE /api/leads/touches/{id}` reverses the touch row, the stage
transition, *and* the `activity` counter bump, in one transaction, so the
quota numbers never drift from reality.

He tapped "Not interested" on the wrong lead at call 14 of 20 with his hands
full. He un-taps it. Nothing was lost, nothing was confirmed, no modal broke his
flow. That's the prestige.

### Keyboard (desktop = fastest path)

`Space` start call · `1`-`6` outcomes · `N` note · `S` skip · `U` undo ·
`Esc` exit. Shown once as a ghosted hint on first run, then never again.
Cmd+K gains `Start a run`, `Callbacks due today`, `Find lead…`.

### Accessibility

Outcome buttons are real `<button>`s with visible focus rings; the queue is a
live region announcing the new business name on advance; the timer is
`aria-live="off"` (it would be noise); heat is decorative and `aria-hidden`;
color is never the only signal, tier shows a letter, not just a hue; all
targets ≥44px.

---

## 9. Agent visibility

One new tool, `read_pipeline`, added to `ALLOWLISTS` for **`scout`** and
**`chief`** only. Scout is already `tier: daily`; no new tripwire needed.

Returns **code-computed** aggregates (the "every number traces to a table row"
rule):

```json
{
  "tier_counts": {"A": 25, "B": 426, "C": 853, "D": 654},
  "stage_counts": {"new": 1204, "attempted": 61, "reached": 12, "demo": 3},
  "callbacks_due_today": 4,
  "callbacks_overdue": 1,
  "runs_last_7d": 9,
  "dials_last_7d": 87,
  "reached_rate_7d": "9/87",
  "runway": {"weekdays_to_school": 19, "callable_remaining": 1204,
             "coverage_at_quota": "31%"},
  "next_5": [{"business_name": "…", "city": "…", "tier": "A", "why": "…"}]
}
```

**Guardrails (code, not prose):** no agent may write a stage, a touch, a run, or
a lead. `read_pipeline` is read-only; no write tool exists. Scout proposes
(`kind: "task"`): *"block 9-11am for the 4 overdue callbacks"*, and Ian
approves.

This retires the weakest seam in the architecture: `agents/roles/scout.md:24`
currently tells Dwight to find *"named leads from the activity notes"*, prose-
scraping a free-text column. Replace that instruction with `read_pipeline`.

**Scout must never see run/heat data as performance.** It gets dials and
outcomes, never "he stopped after 4." The steward's plan-adherence precedent
applies: task-**initiation** signal, never "try harder."

The **chief** gets `next_5` and `callbacks_due_today` so the Day Command names a
real business: *"Four callbacks owed; start with Sam's at 9."*

---

## 10. `ActionStack`: the home page change

[ActionStack.jsx:67](../dashboard/src/components/ActionStack.jsx) currently
renders `+1 audit call (3/20)`, the highest-value real estate in the app spent
on an integer. It becomes the run entry point:

```
Do this next
┌──────────────────────────────────────┐
│  ▸ Start a run. 4 callbacks owed    │
│    first up: Lakeshore Heating, Plainfield │
└──────────────────────────────────────┘
```

Deep-links to `#btc` and opens call mode. Keep the raw `+1` button as a
secondary fallback for calls made off-list. Session-aware ordering
(`lib/timeSession.js`) already puts calls first in the morning, leave that.

---

## 11. Tests: `tests/test_leads.py`

1. `norm_phone` handles `(630) 555-0142`, `630-555-0142`, `16305550142`, ext.
2. Import is idempotent: run twice → 1,958 rows, not 3,916.
3. **Re-import preserves Ian's state**, set `stage='reached'`, `attempts=2`,
   `notes='…'`; re-import; all three survive, `tier`/`total` still refresh.
   *(The load-bearing test.)*
4. Out-of-state and `JUNK_NAMES` rows import `parked`, never queued.
5. Tier D never appears in `call_queue`, at any limit.
6. Band order: a due callback outranks tier A.
7. `market_priority` flips on `MOVE_IN_DATE`.
8. A `no_answer` touch bumps `activity.audit_calls` by exactly 1, sets a rest.
9. Four unanswered attempts → `parked`; no path un-parks it.
10. `booked` bumps `demos`, sets `stage='demo'`, writes an `ian` memo.
11. Queue caps at remaining quota; returns `[]` at 20/20.
12. **Undo reverses all three writes**, touch row gone, stage restored,
    `activity.audit_calls` back down. *(The one that protects data integrity.)*
13. **`heat` increments identically for `no_answer` and `booked`.** *(The one
    that protects the design law, if this ever fails, the feature has become a
    shame machine.)*
14. `call_card` hook priority: a lead with both `miss_signal` and `claims_247`
    gets hook 1; `miss_signal` alone gets hook 2; an empty lead still gets a
    usable fallback and never returns `None`.
15. A run's `heat` does not leak into the next run.

---

## 12. Build order

- ~~**Phase A: engine.**~~ **SHIPPED.** Schema + `core/leads.py` (incl.
  `call_card`) + `import_leads.py` + tests.
- ~~**Phase B, the loop.**~~ **SHIPPED.** `/api/leads/*`, `/api/runs/*`, call
  mode, the three beats, undo, ma. Heat, milestones, the aurora bloom, the run
  summary, keyboard and the `ActionStack` swap came with it rather than waiting
  for C, they are what make the loop feel like anything.
- ~~**Phase C, agents.**~~ **SHIPPED.** `read_pipeline` (allowlisted to
  scout + chief, and re-checked inside the tool against `PIPELINE_READERS`),
  `_pipeline_lines` precomputed prompt block, `scout.md` rewritten off
  prose-scraping, chief told to name a real business in the Day Command.
  6 guard tests in `tests/test_agents_guards.py`, including one asserting no
  lead-writing tool exists in `ALL_TOOLS` at all.
- ~~**Phase D, the list.**~~ **SHIPPED.** `LeadList.jsx` (collapsed by default,
  search + tier/stage/market filters, paged) and `ingest/export_leads.py`, which
  re-exports into the enricher's own column shape with the call-log columns
  filled. `db._lead_filter()` is now shared by `list_leads`/`count_leads`, they
  had drifted, and the pager reported a total it could never reach.
- ~~**Phase E, back-test.**~~ **SHIPPED.** `leads.backtest()` +
  `scripts/backtest_leads.py` + `make backtest`. Gated at 30 dialed leads for
  any rate at all and 100 before it drops the "preliminary" label; groups under
  15 are marked thin and excluded from the verdict so a 3-call 100% cannot flip
  it. Reports `verdict` (`ordering holds` / `ORDERING INVERTED` / `mixed`),
  tier lift, bands for pain/reach/fit/miss-signal/claims-24-7, and a
  `separation` table naming which component carries the signal.

A and B are the product. C stopped Dwight prose-scraping activity notes. D and E
are the feedback loop, they exist so the *ordering* can be corrected with
evidence, which is the one thing that would make the other phases wrong.

**Phase E is inert until there is data.** As of shipping, 0 leads have been
dialed, so `make backtest` correctly reports "not enough data" and nothing else.
That is the intended behaviour, not an unfinished state, the machinery is
tested against synthetic populations (working model, inverted ordering, thin
groups, never-dialed leads) in `tests/test_leads.py`.

---

## 13. Non-goals (fences, not suggestions)

- **No re-scoring.** ianOS never recomputes Fit/Pain/Reach or reassigns a tier.
- **No dialer, no auto-texting, no auto-email.** ianOS shows the number; Ian
  dials. Nothing here contacts a business automatically, consistent with the
  read-only connector pledge in `.claude/commands/`.
- **No LLM in the call path.** The script is deterministic templating. No model
  call may ever sit between "start call" and the number ringing.
- **No agent writes a lead's stage.** Not even the chief.
- **No persistent score, XP, level, badge, leaderboard, or daily streak.**
- **No conversion analytics for Ian.** No cohort charts, no win-rate dashboard.
  If it can't change the next call, it isn't on the page.
- **No CRM features.** No deal amounts, no multiple pipelines, no custom fields,
  no assignment, there is one salesperson.
- **`leads/*.csv` stays gitignored.** 1,958 real businesses' names, phones,
  emails and addresses never enter git history.

---

## 14. Future sparks (not now)

- Re-export `leads` → CSV with real outcomes so `Fit/Pain/Reach` can be
  **back-tested** against who actually answered and who actually bought. After
  ~300 calls that turns a hand-tuned heuristic into a fitted one.
- Objection replies that learn: log which objection card preceded a `booked`.
- Post-move-in "south corridor" day-trip planner, cluster tier-A/B southern
  leads by drive time using `maps_url`, drop them into Plan blocks.
- A `market:` fact when a segment demonstrably converts (`market:property-
  managers-answer`): archivist territory.
