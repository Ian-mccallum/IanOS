# ianOS v5. Ian's Personal Dashboard Specification

> **Superseded for interface work by [SPEC-v10 osUI](SPEC-v10-osui.md).** This
> spec describes the pillar model and the Command page, which still stand, but
> it was written desktop-first: its navigation, layout and spacing decisions
> were rebuilt at 375px in v10. Read v10 first, and load `.claude/skills/osui/`
> before touching the UI.

**Status:** All phases shipped. 2026-07-20  
**Version:** 5.2  
**Date:** 2026-07-20  
**Audience:** Implementing agents (including lower-tier models) with no prior context  
**Scope:** Dashboard UX overhaul + goals architecture + Command page fix + pillar navigation  
**Sacred:** All principles in `PRODUCT.md` remain non-negotiable.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Questions for Ian (blockers)](#2-questions-for-ian-blockers)
3. [Psychology & Design Thesis](#3-psychology--design-thesis)
4. [Information Architecture](#4-information-architecture)
5. [Command Page (Home). Full Redesign](#5-command-page-home--full-redesign)
6. [Life Pillars. Goals Navigation](#6-life-pillars--goals-navigation)
7. [Goal Creation. Wizard & Templates](#7-goal-creation--wizard--templates)
8. [Per-Pillar Page Specifications](#8-per-pillar-page-specifications)
9. [Cross-Page Fixes](#9-cross-page-fixes)
10. [Data Model & API Changes](#10-data-model--api-changes)
11. [Agent & Brief Integration](#11-agent--brief-integration)
12. [Visual Design Tokens](#12-visual-design-tokens)
13. [Component Architecture Refactor](#13-component-architecture-refactor)
14. [Implementation Phases](#14-implementation-phases)
15. [Acceptance Criteria](#15-acceptance-criteria)
16. [File Change Map](#16-file-change-map)

---

## 1. Executive Summary

### The problem

Ian is starting UIUC, building **Clockwork** (Beat the Clock product), training at the gym, dating **Partner**, and trying to run his life from one dashboard. Today:

- All goals live behind one **Goals** page with four tabs, cognitive overload; everything feels like "work."
- Goal creation exposes implementation details (`metric_key`, `kind`, `hero`), high activation energy.
- **Command** (home) is beautiful but passive: no actions, dead space, CLI dependency for briefs.
- **College** deadlines exist only in Memory facts, invisible on the daily surface.
- Edit affordances are hidden (hover-only pencil).
- Navigation has 8 flat items with no mental grouping.

### The solution: "Life Pillars"

Replace the monolithic Goals page with **six life pillars**, each a first-class destination in the nav.

| Pillar | Nav label | Icon | Covers |
|--------|-----------|------|--------|
| `btc` | **Beat the Clock** | ◆ | GTM, clients, quotas, LLC chain (Clockwork CRM is the product sold) |
| `body` | Body | ◉ | Gym weekday streak, health goals, wellness |
| `partner` | Partner | ♥ | Tasks + relationship goals (`#partner` in notes) |
| `school` | School | △ | UIUC: move-in in August; calendar later |
| `life` | Life | ○ | Personal admin (passport, friends): not Partner |
| `money` | Money | $ | Finance goals, portfolio, checking |

**Command** becomes the **morning cockpit**: Day Command + one-tap actions + pillar health strip. Ian never needs to visit all five pillars in one session. Command tells him which one needs him.

### Success criteria (Ian-specific)

| Metric | Target |
|--------|--------|
| Morning check-in | ≤90 seconds to read command + take primary action |
| Goal add flow | ≤3 taps from any pillar to saved goal (template path) |
| Cognitive load | Never more than 5 visible goals per pillar (rest collapsed) |
| Navigation clarity | Ian can name all 5 pillars without looking |
| Attention fit | Zero jargon on default path; advanced fields behind "More options" |

---

## 2. Ian's answers (locked in)

| # | Decision |
|---|----------|
| Q1 | **Beat the Clock** = business/GTM pillar. **Clockwork** = CRM product sold by BtC. Nav: "Beat the Clock". |
| Q2 | Gym **every weekday** (Mon-Fri). Confirm button + streak on Body page. |
| Q3 | Move-in **August 19, 2026**. Class schedule via calendar feature later. |
| Q4 | **Life** pillar added (6th) for personal admin separate from Partner. |
| Q5 | Command works for **both** morning and night sessions. |
| Q6 | **Generate command** button → `POST /api/agents/run` (implemented). |
| Q7 | Relationship goals on **Partner** pillar (`#partner` tag). |
| Q8 | Gym tracked as **sessions/week** + weekday confirm streak. |

### Phase 1 shipped (this build)

- Command grid: Day Command + Action Stack + Pillar Strip
- Nav: Beat the Clock, Body, Partner, School, Life, Money
- `POST /api/gym/confirm` + weekday streak state
- `POST /api/agents/run`
- Pillar pages: Beat the Clock, Body, School, Life
- Simplified goal form with "More options" collapse
- `#goals` redirects to `#btc`

### Phase 2 shipped

- Goal wizard with templates (Add goal on any pillar)
- Legal chain LLC → EIN → A2P on Beat the Clock
- Memory: + Add memory, inline edit
- Cmd+K command palette (pages + goals)
- App.jsx dead code removed (~560 lines)

### Phase 3 shipped

- Command page performance polish (memoized `CommandPage` / `ActionStack` / `PillarStrip`, rich empty state, shared `Md` renderer, time-of-day action ordering)
- Goal deadline chains UI (`depends_on_goal_id` dropdown in GoalForm, "Blocked by" badge on deadlines, seed wires LLC→EIN→A2P, API enriches `depends_on_name`)
- Mobile nav refinement (bottom bar: Command / BtC / Body / Partner + More sheet; desktop sidebar unchanged)
- Explicit CSS grid areas (`nav` / `main`) so layout survives multi-child nav fragments
- Post-ship fix: `ActionStack` null-safe when `activity_today` is `null` (was crashing React on load)

### Post-ship notes

- `startTransition` on state polling was tried and removed, deferred updates caused blank loading states.
- `#goals` still redirects to `#btc` for old bookmarks.
- Command page lag/emptiness when no brief is a known follow-up; empty state now shows greeting + pillar glance chips.

---

## 2b. Original questions (archived)

| # | Question | Why it matters | Default if unanswered |
|---|----------|----------------|----------------------|
| Q1 | Is the product name **Clockwork**, **Beat the Clock**, or both (Clockwork = company, BtC = product)? | Nav label + pillar copy | Nav: "Clockwork"; hero copy mentions Beat the Clock |
| Q2 | Gym schedule: fixed days (e.g. M/W/F) or flexible "3x/week"? | Body pillar calendar vs quota UI | Flexible quota only |
| Q3 | UIUC start date and key deadlines, confirm or replace seed facts? | School pillar countdowns | Use seeded `uiuc:*` facts, Ian confirms on Memory |
| Q4 | Should **personal** domain goals (passport, friend check-in) live under a 6th "Life" pillar or merge into School/Partner? | Nav count | Merge: social → Partner page footer; admin → School |
| Q5 | Morning or night primary session? | Command layout priority | Both: Command works at either; actions ordered by time-of-day |
| Q6 | OK to add `POST /api/agents/run` so Command can trigger brief without terminal? | Removes `make run` friction | Yes, implement |
| Q7 | Relationship goals (e.g. "date night 1x/week"), on Partner pillar or separate? | Goal placement | Partner pillar |
| Q8 | Preferred gym metric: sessions/week, hours/week, or specific program? | Body templates | sessions/week (existing) |

---

## 3. Psychology & Design Thesis

### 3.1 Executive-function mapping

| Attention challenge | Design response | Where |
|----------------|-----------------|-------|
| **Working memory overload** | External brain: agents + facts + goals hold context | Memory, brief, notes |
| **Task initiation paralysis** | ≤3 tap paths; templates pre-fill fields | Goal wizard |
| **Time blindness** | Countdowns, Day Command, "next 7 days" strip | Command, pillar headers |
| **Context-switch cost** | Pillars isolate domains; Command routes to ONE pillar | Nav + signals |
| **Decision fatigue** | Smart defaults; hide on-track goals; one hero per pillar | All pillar pages |
| **Hyperfocus trap** | Weekly focus dims off-pillar goals (keep existing) | Focus allocation |
| **Need for novelty** | Partner-level micro-delight on milestone completion only | Body, Clockwork |
| **Shame spiral** | Never scold; "needs attention" not "failed"; stale ≠ red | Status copy |
| **Dopamine / motivation** | Quick wins: check-off tasks, +1 call button, progress meters | Command, Log |

### 3.2 Behavioral principles (evidence-based)

1. **Implementation intentions**. Day Command format: `[TIME/ANCHOR], [VERB] [OBJECT]` (already in chief prompt). UI reinforces with clickable time anchors when detected.
2. **Chunking (Miller + attention literature)**. Max 5±2 items visible; collapse the rest.
3. **Progress monitoring**. Meters and numbers (not checklists alone) per PRODUCT.md.
4. **Environmental scaffolding**. Dashboard is the desk environment; open it = work mode.
5. **Variable reward (ethical)**. Subtle completion animation on quota hit; no slot-machine patterns.

### 3.3 What we are NOT building

- Not a generic productivity app (no Pomodoro, no habit streak guilt)
- Not a social product (no sharing, no accounts)
- Not Notion (no freeform docs on pillar pages)
- Not a calendar replacement (calendar is ingest → facts → deadlines)

---

## 4. Information Architecture

### 4.1 New navigation structure

Replace `Nav.jsx` `LINKS` array with grouped nav:

```
COMMAND          ← always first
─────────
CLOCKWORK        ← pillar
BODY             ← pillar
PARTNER            ← pillar
SCHOOL           ← pillar (NEW)
MONEY            ← pillar (existing page, elevated)
─────────
INBOX            ← system
LOG              ← quick capture (fallback; pillar pages absorb most)
MEMORY
NOTES
```

**Hash routes** (extend existing hash router in `App.jsx`):

| Route | Page component | Notes |
|-------|----------------|-------|
| `#home` | `CommandPage` | Renamed from HomePage |
| `#clockwork` | `ClockworkPage` | NEW: extract from GoalsPage business zone |
| `#body` | `BodyPage` | NEW: extract from GoalsPage health zone |
| `#partner` | `PartnerPage` | EXTEND: add relationship goals section |
| `#school` | `SchoolPage` | NEW |
| `#money` | `MoneyPage` | KEEP |
| `#inbox` | `InboxPage` | KEEP |
| `#log` | `LogPage` | KEEP: slim down to "everything else" capture |
| `#memory` | `MemoryPage` | KEEP |
| `#notes` | `NotesPage` | KEEP |

**Remove:** `#goals` route. Add redirects: `#goals` → `#clockwork`, `#goals?domain=health` → `#body` (parse hash query if present).

### 4.2 Pillar → domain mapping (backend unchanged)

Pillars are a **presentation layer** over existing `goals.domain`:

| Pillar | `goals.domain` values | `facts` topics |
|--------|----------------------|----------------|
| clockwork | `business` |: |
| body | `health` |: |
| partner | `personal` (filter: name contains partner OR `notes` tag `#partner`) | `partner:*` |
| school | NEW: `school` OR facts-only until schema migration | `uiuc:*` |
| money | `finance` |: |

**Personal goals not about Partner** (passport, friend check-in): show in School page section "Life admin" until Ian decides otherwise (Q4).

### 4.3 Header focus chips

`FocusChips` in page header: show **pillar names** not raw domains. Map `business` → Clockwork, `health` → Body, etc. Clicking a chip navigates to that pillar.

---

## 5. Command Page (Home). Full Redesign

### 5.1 Layout (1440×900 target)

Two-column grid inside `--content-w: 920px`:

```
┌─────────────────────────────────────────────────────────────┐
│  TODAY · 2026-07-20                    [Run brief] [···]    │
├──────────────────────────────┬──────────────────────────────┤
│  DAY COMMAND (hero)        │  DO THIS NEXT (action stack) │
│  Large, centered-left      │  1. Approve proposal (if any)│
│  max-width 42ch              │  2. Log calls +1             │
│                              │  3. Log workout ✓            │
│  Headline (1 line)           │  4. Open top pillar signal   │
│                              │                              │
│  Signals (clickable)         │  PILLAR STRIP (5 rows)       │
│                              │  ◆ Clockwork  · 2 need you   │
│  [Read brief]                │  ◉ Body       · on track     │
│                              │  ♥ Partner      · 1 open       │
│                              │  △ School     · 12d to move-in│
│                              │  $ Money      · on track     │
└──────────────────────────────┴──────────────────────────────┘
```

**Mobile/narrow (<720px):** Stack columns; actions above pillar strip.

### 5.2 Day Command block

**File:** `dashboard/src/pages/CommandPage.jsx` (extract from App.jsx)

| Element | Spec |
|---------|------|
| Eyebrow | `TODAY · {date}` or `LAST BRIEF · {date}` + amber `stale` chip if not today |
| Command text | `--t-lg` (20px), `--ink`, max-width 42ch, line-height 1.45. NO `clamp()`. |
| Empty state | Replace `make run` code block with button **"Generate today's command"** calling `POST /api/agents/run` |
| Headline | `--t-base`, `--muted`, single line, ellipsis overflow |
| Stale brief | Banner: "Brief is from {date}. Generate fresh?" with button |

### 5.3 Signals row (keep, enhance)

Existing signals in `HomePage`: preserve logic, update routes:

| Signal | Condition | Navigates to |
|--------|-----------|--------------|
| `{n} days to client` | hero business goal deadline | `#clockwork` |
| `{n} to decide` | pending proposals | `#inbox` |
| `{n} need attention` | goals AT RISK/OFF TRACK | highest-priority pillar |
| `all clear` | none of above | static |

**Add signals:**
- `{n} days to move-in` if school fact `uiuc:move-in` exists
- `{n} open for Partner` if partner tasks undone

### 5.4 "Do this next" action stack

**Component:** `ActionStack.jsx`

Priority-ordered, show max 4 actions. First incomplete action gets `action-primary` styling.

| Priority | Action | Condition | Behavior |
|----------|--------|-----------|----------|
| 1 | Approve/reject top proposal | `pending_proposals[0]` exists | Inline mini-card: role tag, 1-line action, Approve / Reject buttons |
| 2 | Log audit call | business quota below target today | `POST /api/activity` increment `audit_calls`, single tap "+1 call" |
| 3 | Log follow-up | same for follow_ups | "+1 follow-up" |
| 4 | Log workout | health quota below weekly target | `POST /api/wellness` `{worked_out: true}` |
| 5 | Confirm Partner task | oldest open partner task | Checkbox inline |
| 6 | Review stale pillar | `stale_domains` includes pillar | Link to pillar |

**Empty state:** "You're clear. Read the brief or pick a pillar."

### 5.5 Pillar strip

**Component:** `PillarStrip.jsx`

Five rows, fixed order: Clockwork, Body, Partner, School, Money.

Each row:
```
[icon] [Pillar name]     [hero metric or status]     [chevron →]
```

| Pillar | Hero metric source | Status text |
|--------|-------------------|-------------|
| Clockwork | `clients_signed` / target OR burn | worst business goal status |
| Body | workouts_this_week / target OR sleep | worst health goal status |
| Partner | open task count | "{n} open" or "all done ♥" |
| School | nearest deadline days | "{n}d to {event}" |
| Money | portfolio or checking hero | worst finance goal status |

Row click → navigate to pillar. Row status uses `StatusChip`, never color alone.

**Off-focus dimming:** If weekly focus excludes pillar's domain, row opacity 0.55 unless status is OFF TRACK.

### 5.6 Brief expansion

Keep existing `showBrief` toggle. Brief renders below grid full-width when expanded. Continue stripping duplicate Day Command from markdown (`stripDayCommand`).

### 5.7 Command page CSS

**New classes in `styles.css`:**

```css
.command-grid {
  display: grid;
  grid-template-columns: 1fr 280px;
  gap: var(--s5);
  align-items: start;
}
.command-hero { /* left column */ }
.command-rail { /* right column: action stack + pillar strip */ }
.pillar-row { /* clickable row, padding --s3, border-radius --radius-sm */ }
.pillar-row:hover { background: rgba(255,255,255,0.04); }
.action-stack-item { /* card-item style */ }
.action-primary { border-color: var(--accent); }
```

---

## 6. Life Pillars. Goals Navigation

### 6.1 Shared pillar page template

**Component:** `PillarPage.jsx` (layout shell)

Every pillar page uses the same skeleton:

```
┌─────────────────────────────────────────┐
│ PILLAR HERO                             │
│ [Big number] [unit]                     │
│ [Hero goal name]                        │
│ [StatusChip] [T-minus if deadline]      │
├─────────────────────────────────────────┤
│ NEEDS ATTENTION (0-5 goals)             │
│ [GoalRow...]                            │
├─────────────────────────────────────────┤
│ ON TRACK (collapsed by default)         │
│ [Show N on track ✓]                     │
├─────────────────────────────────────────┤
│ [+ Add goal]  [Quick log buttons]       │
└─────────────────────────────────────────┘
```

### 6.2 Goal row (unified)

**Keep** `GoalRow`, `QuotaRow`, `DeadlineRow` from App.jsx but:

1. **Always visible edit button**, replace hover-only `.edit-glyph` with visible `✎` button, min 44×44px touch target, `--t-xs` "Edit" label on focus.
2. **Click row** to expand inline detail (notes, deadline, actual source).
3. **Status + label** always text, e.g. "AT RISK · 3 days left".

### 6.3 Hide on track (default on)

Preserve `hideOnTrack` default `true` per pillar page. Toggle copy: `Show {n} on track ✓`.

### 6.4 Cross-pillar search

`Cmd+K` palette: search goals by name and jump to pages/pillars. **Shipped** in Phase 2.

---

## 7. Goal Creation. Wizard & Templates

### 7.1 Replace raw GoalForm as default

**New component:** `GoalWizard.jsx`

Three steps. Advanced users can click "Edit as form" to open legacy `GoalForm`.

#### Step 1. Pick a template

Visual cards (2 columns). Each card: icon, title, one-line description.

| Template ID | Title | Pre-fills |
|-------------|-------|-----------|
| `client` | Land a client | kind=goal, domain=business, metric=clients_signed |
| `daily-quota` | Daily number target | kind=quota, domain=business, metric picker |
| `weekly-quota` | Weekly number target | kind=quota |
| `deadline` | One-time milestone | kind=deadline |
| `money-target` | Savings/net worth | kind=goal, domain=finance, metric picker |
| `health-habit` | Health habit | kind=quota, domain=health, metric picker |
| `relationship` | Relationship ritual | kind=quota, domain=personal, notes=#partner |
| `school-date` | School deadline | kind=deadline, domain=school |
| `custom` | Start from scratch | opens full form |

#### Step 2. Plain English fields

**Never show:** `metric_key`, `kind`, `domain` as raw labels on default path.

| UI label | Maps to | Input type |
|----------|---------|------------|
| "What do you want to hit?" | `name` | text, autofocus |
| "How much?" | `target` + `unit` | split inputs with suggestions |
| "By when?" | `deadline` | date picker, optional for quotas |
| "Track automatically?" | `metric_key` | dropdown: "From my logs" options per pillar |
| "Or track manually" | `metric_key=""` | shows `current_value` field |

**Metric dropdown options by pillar:**

Clockwork: audit calls today, follow-ups today, demos last 7d, clients signed, burn this month  
Body: sleep avg 7d, workouts this week, steps today, energy today  
Money: portfolio value, checking balance  
School/Partner: manual only (default)

#### Step 3. Confirm

Summary card in plain English:
> "Get **1 client** by **Aug 15, 2026**, tracked automatically from signed clients"

Buttons: **Save goal** | Back | Cancel

**Checkbox:** "Make this my main focus for [pillar]" → sets `hero: true`

#### Kind inference (no user-facing "kind")

```javascript
function inferKind(template, hasDeadline, isRepeating) {
  if (template === 'deadline' || template === 'school-date') return 'deadline'
  if (template === 'daily-quota' || template === 'weekly-quota' || template === 'health-habit' || template === 'relationship') return 'quota'
  return 'goal'
}
```

### 7.2 GoalForm (legacy/advanced)

Keep `GoalForm` for "Edit as form" and power users. Add collapsible **"More options"** section:

- `priority` (number input, default 0)
- `depends_on_goal_id` (dropdown of deadlines in same pillar)
- `metric_key` (text input with autocomplete)
- `hero` (checkbox)
- `notes` (textarea, not single line)

### 7.3 Deadline chains UI

When `depends_on_goal_id` set, show chain badge on row: "Blocked by: File Illinois LLC" with link to parent goal.

**API:** Already supports `depends_on_goal_id`. UI only.

---

## 8. Per-Pillar Page Specifications

### 8.1 Clockwork (`ClockworkPage.jsx`)

**Hero:** Client #1 goal OR `clients_signed` actual vs target (big `--n-hero` number).

**Sections:**
1. **Revenue path**: hero client goal, T-minus to Aug 15
2. **Today's numbers**, audit calls, follow-ups (QuotaRows + inline +1 buttons)
3. **Burn**, burn meter + 3-month sparkline (move from GoalsPage)
4. **Legal chain**. LLC → EIN → A2P deadlines as visual chain:

```
[LLC ●──] → [EIN ○──] → [A2P ○──]
 in progress   not started   not started
```

Chain reads `depends_on_goal_id` or falls back to hardcoded order from seed goal names.

**Quick log bar (sticky bottom on pillar):**
- `+1 Call` | `+1 Follow-up` | `+1 Demo` (demo logs to activity with type `demo`)

**Add goal:** Opens wizard with `clockwork` pillar preset.

### 8.2 Body (`BodyPage.jsx`)

**Hero:** This week's workouts `workouts_this_week` / target OR sleep avg.

**Sections:**
1. **This week**, workout quota, steps, sleep (QuotaRows)
2. **Today**, energy, last night's sleep (from `wellness_today`)
3. **Log**, embedded wellness mini-form (move from LogPage):
   - Sleep hours (number, compact)
   - Energy 1-5 (segmented buttons, not dropdown)
   - Worked out (toggle)
   - Steps (optional number)

**Delight:** On workout quota met, subtle teal pulse on hero number (respect `prefers-reduced-motion`).

**Add goal:** Wizard preset `body`.

### 8.3 Partner (`PartnerPage.jsx`, extend)

**Keep existing** task list, sparkles, animations.

**Add section below tasks:** "Goals for us", relationship quotas (date nights, etc.) filtered by `#partner` in notes or pillar filter.

**Add section:** "Remember": top 3 unconfirmed `partner:*` facts from Memory with "Confirm" inline (links to Memory for edit).

**Add goal:** Wizard preset `relationship`.

### 8.4 School (`SchoolPage.jsx`, new)

**Hero:** Countdown to nearest `uiuc:*` dated fact OR school goal deadline.

**Data sources (Phase 1):** Read `facts` where `topic LIKE 'uiuc:%'` AND `kind='date'`. Display as deadline rows even before `school` domain migration.

**Sections:**
1. **Coming up**: dated facts sorted by `days_until`
2. **School goals**, goals with `domain=school` (after migration)
3. **Life admin**, personal deadlines (passport): optional section

**Seed facts to surface:**
- `uiuc:move-in`
- `uiuc:registration`
- `uiuc:orientation`
- `uiuc:faFSA` (if exists)

**Add goal:** Wizard preset `school-date`. Creating also offers "Add to Memory" for agent visibility.

### 8.5 Money (`MoneyPage.jsx`)

**No structural change** in Phase 1. Add:
- Link from finance goals section to goal wizard (money-target template)
- Ensure finance goals from old Goals page appear here in a collapsible "Targets" section below portfolio

---

## 9. Cross-Page Fixes

### 9.1 Inbox

| Fix | Detail |
|-----|--------|
| Collapsed note input | Note field hidden until "Add note" clicked (SPEC v3 D10) |
| Inline on Command | Top proposal also in ActionStack |
| Batch approve | Phase 3: not blocking |

### 9.2 Log page

Slim to **overflow capture**:
- Sales activity (if not on Clockwork page)
- Wellness (if not on Body page)
- Message: "Most logging lives on Clockwork and Body now."

### 9.3 Memory

| Fix | Detail |
|-----|--------|
| Add fact | `+ Add memory` button → form: topic, body, kind, date |
| Edit body | Inline edit on FactCard |
| Pillar tags | Show pillar badge on each fact (computed from topic) |

### 9.4 Notes

No major change. Ensure memo filter persists in URL hash query ` #notes?filter=p3` (optional).

### 9.5 Global

| Fix | Detail |
|-----|--------|
| Edit affordance | Visible on all editable rows (SPEC v3 D9) |
| Focus ring | `outline: 2px solid var(--accent); outline-offset: 2px` |
| Nav badge urgency | Inbox badge amber unless P3 memo today OR deadline <3d |
| Offline state | Actionable: "Start API" button runs nothing but links to IAN-SETUP.md anchor |
| Page titles | Update `PAGE_TITLES` map for new routes |

### 9.6 Remove Goals page

Delete `GoalsPage`, `GoalZones` business/finance/health/personal tabs. Logic distributes to pillar pages.

---

## 10. Data Model & API Changes

### 10.1 Add `school` domain (Phase 2)

**File:** `core/db.py`

Migration (SQLite, no ALTER CHECK support, use recreation or loose validation):

```python
# Option A: Remove CHECK constraint on domain in new installs
# Option B: application-level validation only, add 'school' to allowed list in api/main.py
```

Update:
- `GOALS.md` four domains → five
- `DOMAINS` constant in App.jsx → pillar mapping
- `agents/runner.py` domain lists in role files if needed
- `seed.py`, add 2-3 school goals from uiuc facts

### 10.2 New API endpoint: trigger agent run

```
POST /api/agents/run
Body: { "mode": "brief" | "full" }  // default "brief"
Response: { "ok": true, "started": true }
```

**Implementation:** Spawn `agents/runner.py` subprocess async or use existing `make run` logic. Return immediately; dashboard polls `state.brief.date` until updated.

**Safety:** Rate limit 1 request per 5 minutes. Show spinner on Command page.

### 10.3 Extend `GET /api/state`

Add computed fields:

```json
{
  "pillars": {
    "clockwork": { "hero": {...}, "attention_count": 2, "status": "AT RISK" },
    "body": { ... },
    "partner": { "open_tasks": 1, ... },
    "school": { "next_deadline": { "label": "Move-in", "days": 12 }, ... },
    "money": { ... }
  }
}
```

**File:** `api/main.py`: new function `_compute_pillars(state)`.

### 10.4 Goal templates API (optional Phase 2)

```
GET /api/goal-templates
Returns template definitions for wizard (could be static JSON in frontend instead).
```

Prefer **static JSON** in `dashboard/src/data/goalTemplates.json` for Phase 1.

---

## 11. Agent & Brief Integration

### 11.1 Chief brief prompt additions

**File:** `agents/roles/chief.md`

Add to Day Command instructions:
- Reference **pillar** names (Clockwork, Body, Partner, School, Money) not "business domain"
- Include school countdown when uiuc fact within 30 days
- Max 3 concrete time anchors per command

### 11.2 Focus allocation

Chief's `write_focus` continues using backend domains. Dashboard maps:
- `business` → Clockwork
- `health` → Body
- `personal` → Partner (if partner goals in focus) OR Life admin
- `finance` → Money
- `school` → School

### 11.3 Agent memos on goal create

Preserve existing behavior: Ian's goal changes write memos (`from_role: ian`).

Wizard should append pillar name to memo body for agent context.

---

## 12. Visual Design Tokens

Extend SPEC v3 tokens (do not change colors).

### 12.1 Pillar colors

```css
--pillar-clockwork: var(--domain-business);  /* green */
--pillar-body: var(--domain-health);         /* teal */
--pillar-partner: #e879a8;                     /* existing partner pink */
--pillar-school: #8b9cff;                    /* new: soft indigo */
--pillar-money: var(--domain-finance);       /* amber */
```

### 12.2 Pillar icons (nav)

Use existing nav icon pattern. School: `△` (graduation metaphor, minimal).

### 12.3 Typography (Command hero)

Day Command: `--t-lg` (20px), NOT larger. The command is read daily, legibility > drama.

Pillar hero numbers: `--n-hero` (40px) mono tabular.

---

## 13. Component Architecture Refactor

### 13.1 Extract from App.jsx

| New file | Contents |
|----------|----------|
| `pages/CommandPage.jsx` | HomePage redesign |
| `pages/ClockworkPage.jsx` | Business pillar |
| `pages/BodyPage.jsx` | Health pillar |
| `pages/SchoolPage.jsx` | School pillar |
| `components/PillarPage.jsx` | Shared layout shell |
| `components/PillarStrip.jsx` | Command right rail |
| `components/ActionStack.jsx` | Command actions |
| `components/GoalWizard.jsx` | 3-step wizard |
| `components/GoalForm.jsx` | Legacy form (move from App.jsx) |
| `components/GoalRow.jsx` | Row variants |
| `components/LegalChain.jsx` | LLC→EIN→A2P visual |
| `lib/api.js` | Shared `api()` helper |
| `lib/format.js` | `fmtMoney`, `cap`, `relTime` |
| `data/goalTemplates.json` | Wizard templates |

**Target:** App.jsx < 400 lines (routing, state fetch, layout shell only).

### 13.2 Shared primitives

Consolidate duplicate `Meter`, `StatusChip`, `Card` from MoneyPage into `components/ui/`.

---

## 14. Implementation Phases

All three phases are **shipped** as of 2026-07-20.

### Phase 1. Command + Nav ✓

1. New nav structure + routes
2. Command page grid + PillarStrip + ActionStack
3. `#goals` redirect
4. Visible edit buttons
5. `POST /api/agents/run`

### Phase 2. Pillars ✓

1. BeatTheClockPage, BodyPage, SchoolPage, LifePage
2. Extended PartnerPage, MoneyPage
3. GoalWizard + templates
4. `school` domain migration
5. `pillars` in API state

### Phase 3. Polish ✓

1. Memory add/edit
2. Legal chain visualization
3. Cmd+K search
4. App.jsx refactor (routing shell + shared components)
5. Goal deadline chains UI + mobile nav
6. Docs updated (`GOALS.md`, `IAN-SETUP.md`, `README.md`, this spec)

---

## 15. Acceptance Criteria

### Command

- [x] Day Command visible without scrolling at 1440×900
- [x] "Generate today's command" works without terminal
- [x] Top proposal approvable from Command in ≤2 clicks
- [x] +1 call works from Command
- [x] All 6 pillars visible in strip with correct status
- [x] Brief expand does not duplicate Day Command text

### Pillars

- [x] No `#goals` route in nav (`#goals` redirects to `#btc`)
- [x] Each pillar shows ≤5 attention goals by default (hide on-track toggle)
- [x] Add goal via wizard in ≤3 taps (template path)
- [x] Beat the Clock +1 buttons update quota actuals within 15s poll
- [x] School shows uiuc countdown from facts
- [x] Partner page shows tasks + relationship goals

### Goals

- [x] Wizard does not expose `metric_key` on default path
- [x] Edit button visible without hover
- [x] Deadline chain shows "Blocked by" when `depends_on_goal_id` set
- [x] Hero goal one per domain enforced (API)

### Accessibility

- [x] All actions keyboard reachable
- [x] Focus ring visible
- [x] Status never color-only (chips + labels)
- [x] `prefers-reduced-motion` disables pillar delight animations

### Regression

- [x] All existing pytest tests pass (48 as of 2026-07-20)
- [x] `make dev` + `make seed` works
- [x] Agents still read goals correctly
- [x] Inbox approve/reject unchanged functionally

---

## 16. File Change Map

| File | Action |
|------|--------|
| `dashboard/src/App.jsx` | Routing shell, state poll, layout (overlays outside grid) |
| `dashboard/src/components/Nav.jsx` | Pillar nav + mobile bottom bar |
| `dashboard/src/pages/CommandPage.jsx` | CREATE, home / Command |
| `dashboard/src/pages/BeatTheClockPage.jsx` | CREATE: business pillar |
| `dashboard/src/pages/BodyPage.jsx` | CREATE, health + gym confirm |
| `dashboard/src/pages/SchoolPage.jsx` | CREATE, school pillar |
| `dashboard/src/pages/LifePage.jsx` | CREATE, personal admin pillar |
| `dashboard/src/pages/PartnerPage.jsx` | EXTEND, tasks + relationship goals |
| `dashboard/src/pages/MoneyPage.jsx` | MINOR, finance targets |
| `dashboard/src/components/goals/GoalWizard.jsx` | CREATE |
| `dashboard/src/components/goals/GoalForm.jsx` | CREATE: edit form + deadline chains |
| `dashboard/src/components/goals/PillarGoalPanel.jsx` | CREATE: shared goal lists |
| `dashboard/src/components/goals/LegalChain.jsx` | CREATE. LLC→EIN→A2P |
| `dashboard/src/components/goals/BlockedBadge.jsx` | CREATE |
| `dashboard/src/components/PillarStrip.jsx` | CREATE |
| `dashboard/src/components/ActionStack.jsx` | CREATE |
| `dashboard/src/components/CommandPalette.jsx` | CREATE. Cmd+K |
| `dashboard/src/components/Md.jsx` | CREATE, brief markdown renderer |
| `dashboard/src/lib/pillars.js` | CREATE, pillar routing + goal filters |
| `dashboard/src/lib/goals.js` | CREATE, deadline chain helpers |
| `dashboard/src/styles.css` | command-grid, pillar-*, mobile nav, gym |
| `api/main.py` | `/api/agents/run`, `/api/gym/confirm`, `/api/facts` POST, `pillars` in state |
| `core/pillars.py` | CREATE, pillar summary computation |
| `core/db.py` | `school` domain, `gym_confirmed` on health_daily |
| `scripts/seed.py` | school facts, gym goal, LLC chain `depends_on_goal_id` |
| `GOALS.md` | UPDATE, pillars + chains |
| `IAN-SETUP.md` | UPDATE, dashboard tour |
| `tests/test_gym_pillars.py` | CREATE |
| `tests/test_facts_api.py` | CREATE |

---

## Appendix A. Default seed goals for School pillar

```python
("UIUC move-in ready", "deadline", "ready", "", "2026-08-20", "not started",
 "Dorm setup, packing.", "school", "", 1, 0),
("Fall course registration", "deadline", "registered", "", "2026-08-10", "not started",
 "Gies Business.", "school", "", 0, 1),
```

## Appendix B. Wizard copy (Ian-facing)

Use Ian's voice, direct, not corporate:

- "What do you want to hit?" not "Goal name"
- "By when?" not "Deadline (ISO date)"
- "Track automatically?" not "Metric key"
- "Make this my main focus" not "Hero metric"

## Appendix C. Move 78 one-liner

> **Command tells Ian which life pillar needs him; each pillar holds only that life's goals; adding a goal is a 3-tap template, not a form.**

---

*End of specification.*
