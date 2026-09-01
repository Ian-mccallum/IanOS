# SPEC-v10: "osUI": mobile-first, and a design law of its own

Status: proposed
Supersedes the mobile half of `SPEC-v3-ux-overhaul.md` and `SPEC-v5-ian-personal-dashboard.md`.
Does not change any agent, guardrail, table, or metric except where noted in §7.

---

## 0. Why this exists

ianOS was designed on a 15" laptop and then shipped to a phone. Everything in
this spec follows from that one fact.

The audit found three defects that are not opinions:

| # | Defect | Evidence | Consequence |
|---|---|---|---|
| **D1** | `.nav-mobile { display: none }` at `styles.css:1687` sits *after* the `@media (max-width: 900px)` block that ends at 1685. Equal specificity, later rule wins. | Computed `display: none` at 375px on both `.nav-mobile` and `.nav-desktop`. | **There is no navigation on the phone at all.** You land on Command and cannot leave. |
| **D2** | `.app-shell { height: 100vh }` plus `body { overflow: hidden }`. | `styles.css:101`, `:1681`. | In mobile Safari `100vh` is the viewport *with the URL bar hidden*, taller than what you can see. The bottom of the app sits under Safari's toolbar. This is the "way too high." |
| **D3** | The Command page spends ~300px of an 812px screen (37%) before the first actionable pixel. | Measured: first action-stack element at y=980, below a viewport of 812. | The one thing the product exists to tell you is below the fold. |
| **D4** | `.app-main { padding: a b c }` inside the mobile breakpoint replaces the base rule's four `env(safe-area-inset-*)` values with nothing. | `styles.css:1690`. Reported from the installed app: "command is above my screen." | **Breaks only once installed.** In a Safari tab the browser chrome owns the notch so `inset-top` is 0 and nothing is lost; standalone + `viewport-fit=cover` puts the web view under the status bar and the first line renders beneath the clock. |

D1 and D2 are bugs. D3 is a design failure. This spec fixes all three and then
raises the bar.

**The through-line: on a phone, the screen is the scarcest resource in the
product.** Every rule below is downstream of that.

---

## 1. Design law (binding, this is what `osui` will encode)

These extend, and never contradict, the existing laws in `CLAUDE.md`
(no `--crit` in Plan/Journal/The Line; no percentages, streaks or lifetime
counters that can shame; heat earned by dialing, not outcome).

**L1. Mobile is the design target, desktop is the enhancement.**
Every component is authored at 375px first and allowed to grow. No component may
be laid out for desktop and then patched with a `@media (max-width:)` override.

**L2. One screen, one job.** A phone screen answers exactly one question. If a
second question needs answering, that is a second screen or a disclosure, never
a second column.

**L3. Zero-value pixels are a bug.** A label that restates the page title
("Command / Your day at a glance"), a metric reading `0` with no unit, a chip
duplicating a row 400px below, all are deleted, not shrunk. *If it isn't
actionable or alarming, it doesn't get shown on mobile.*

**L4. Nothing that matters lives below the fold.** The single most important
element must be fully visible at 375×667 (iPhone SE, the smallest realistic
target) without scrolling.

**L5. Thumb zone is law.** Every primary action sits in the bottom third.
Minimum hit target 44×44 CSS px. Destructive actions never sit adjacent to
frequent ones.

**L6. Safari is the reference browser, not Chrome.** `dvh` over `vh`; no
`body { overflow: hidden }` scroll-jail; `-webkit-` prefixes on
`backdrop-filter`; `env(safe-area-inset-*)` on every fixed edge; no more than
**two** stacked `backdrop-filter` layers in a paint (Safari compositing cost).

**L7. Motion explains, or motion goes.** Every animation must communicate
causality (where a thing came from, what it became). Decorative motion is
deleted. All motion respects `prefers-reduced-motion`. Budget: **200ms** for
state, **320ms** for transitions between surfaces.

**L9. The installed app is a different runtime, and it is the real one.**
Verifying in a Safari tab does not verify the PWA. Standalone reports real
`env(safe-area-inset-*)` values where a tab reports zero, so a whole class of
defect is *invisible* in the browser and obvious on the home screen. Any rule
setting `padding` on a full-bleed container must carry the insets, a shorthand
that omits them is a silent regression. Every phase must be checked with
simulated insets (47px top / 34px bottom) before it is called done.

**L8. Futuristic means restraint, not decoration.** The vocabulary is: deep
near-black, one accent, hairline borders, generous negative space, mono for
numbers, and light used sparingly as emphasis. Glow is a highlight, not a
texture. When in doubt, remove.

---

## 2. Navigation (the centerpiece)

### 2.1 The tab bar

Five slots, fixed, bottom, thumb-reachable. **Decided:**

```
  ◈ Command      ▤ Plan      ◆ The Line      ♥ Partner      ⋯ More
```

- Height 56px + `env(safe-area-inset-bottom)`.
- Icon 22px over a 10px label; the active tab is accent-tinted with a
  hairline top-glow, no filled pill, no bounce.
- The active indicator animates between tabs via a shared `layoutId`
  (already in `Nav.jsx`), 220ms spring. This is the one piece of decorative
  motion that survives L7, because it shows *where you came from*.
- Badges: Partner shows open-task count; More shows pending proposals. **A badge
  appears only when the number is > 0.** Never a zero badge.

### 2.2 Swipe between pillars

Horizontal swipe moves through the pillar ring in a fixed order:

```
Command ⇄ Plan ⇄ The Line ⇄ Body ⇄ Partner ⇄ School ⇄ Life ⇄ Money ⇄ (wraps)
```

- **The outer 24px on each side belongs to iOS.** A swipe starting there is
  ignored so the system back/forward gesture still works in the installed app.
  We take the middle; iOS keeps the rails.
- Threshold: 60px travel **or** velocity > 0.4 px/ms. A short *fast* flick
  navigates; a short *slow* drift does not, verified with real timings, since
  synthetic events fired in one millisecond report infinite velocity and will
  lie to you.
- Vertical intent wins ties, a swipe more vertical than horizontal scrolls,
  never navigates. (Ratio test on first 12px of travel.)
- Disabled inside `call-mode` and `shutdown-mode`, those are committed modes
  and must not be exitable by accident.
- Disabled over the Plan time-ribbon and any horizontally scrollable child.
- A 2px progress hairline under the tab bar shows position in the ring.

### 2.3 The More sheet

Not a dropdown, a **bottom sheet** that rises to 60% height, with the
remaining pillars as a 2-column grid of large tap targets, then system pages
(Inbox, Log, Notes, Memory) as a list below. Dismiss by swipe-down or backdrop
tap. `Journal` is always listed (SPEC-v11; phone uses the same LAN token).

### 2.4 The header problem

Today every page renders a title + subtitle block (~120px).

**Shipped in P1, simpler than the original plan.** The spec first called for a
collapsing 28px context strip. That is machinery in service of a question the
tab bar already answers. The rule instead:

- **Subtitle: always deleted on mobile.** It never earns its space.
- **Title: deleted only when the page owns a lit tab** (Command, Plan, BtC,
  Partner). The highlighted tab already names those.
- **Pages behind "More" keep their title**, nothing else tells you where you
  are, so removing it there would be minimalism at the cost of orientation.
- Clock and focus chips are desktop garnish; the phone keeps status only.

No scroll listener, no collapsing animation, ~100px reclaimed on the four
screens that matter most.

---

## 3. Command, the one screen that matters

Rebuilt to satisfy L4: at 375×667, above the fold, in priority order:

1. **The Day Command**, the sentence. `--n-hero`, max 3 lines, nothing above
   it but a 20px date/staleness line.
2. **The next action**, one button, full-width, in the thumb zone. This is
   "Start a run", "Confirm gym", or "Decide: <proposal>", chosen by the same
   deterministic priority the ActionStack already computes.
3. **At most three signals**, as a single wrapping row of chips
   (`9d to client · 2 to decide`). Currently up to five, plus a duplicate
   pillar strip. Cap at three, ranked by urgency; the rest live in More.

Everything else (pillar list, brief body, glance chips) moves **below** the
fold or behind "Read brief". The pillar strip is **deleted from Command on
mobile**, it duplicates the tab bar and the More sheet (L3).

**Shipped in P2.** The root cause was worse than D3 estimated: a
`.command-rail { order: -1 }` at the 720px breakpoint hoisted the action list
above the hero, so on a 667px screen the Day Command rendered at **y=1012** : 
below a 420px pillar strip that repeats the tab bar. Measured after: date line
72, Day Command 106, signals 222, generate 266, next action 397-562, against a
fold at 602. Everything above it, on the smallest screen we target.

**Empty state:** when there is no brief, do not render an empty hero and a
paragraph of apology. Render the greeting, the next action, and a single
"Generate today's command" button. Nothing else.

---

## 4. Editing calendar and goals (the two "hard to edit" surfaces)

### 4.1 Plan

- **Tap empty ribbon space → creates a block at that time**, snapped to 15 min,
  with the title field already focused. **Shipped in P3:** the tap already
  opened a focused sheet, but snapped to the top of the hour, tapping 9:40 and
  getting 09:00 meant correcting every block right after making it. The start
  now comes from where the thumb actually landed.
- **Drag a block to move it; drag its bottom edge to resize.** **Shipped in P3.**
  A vertical calendar and a vertical scroller want the same gesture, so a block
  is *picked up* by a **300ms long press**, move more than 8px before that and
  it was a scroll all along. The `touchmove` listener is **non-passive**,
  because only a non-passive listener may `preventDefault`, and without it the
  ribbon scrolls out from under the block being dragged. Everything is a
  15-minute-snapped preview until the finger lifts; nothing is written mid-drag.
  The bottom 16px resizes (a 3px visual handle), and a completed drag suppresses
  the click that would otherwise also open the edit sheet.
- The existing sheet remains for precise edits, reachable by tapping a block.
- **Now-line** stays; auto-scroll to it on mount.

### 4.2 Goals

- **Inline target editing** (**shipped in P3**): the number *is* the control.
  Tap it, get a numeric keypad, commit on blur or Enter, Escape to abandon. It
  PATCHes **only** `target`: sending the whole goal back would let a stale
  field clobber something you never touched. The input is 16px on mobile
  because anything smaller makes iOS zoom the page on focus.
- A goal row is **swipe-actionable**: swipe left reveals Edit / Archive.
  **Shipped.** Two details carry it:
  - The row marks itself `data-swipe-own`, and the pillar ring skips any touch
    that starts inside such an element. Two horizontal gestures on one pixel is
    one gesture too many; without this, a single drag would both open the row
    and change pillar.
  - **Archive, not delete.** Goals only had a hard `DELETE`, which is the wrong
    thing to hang off a gesture that is one thumb-slip from a tap. `goals` gains
    an `archived` flag, filtered in `all_goals` (the single read path, so a
    retired goal disappears from `/api/state`, metrics, pillars *and* the
    nightly run at once), with an Undo in the toast. Undo restores the **same
    row** because metrics resolve off goal ids: a re-created goal is not a
    restore.
- The goal wizard on mobile: **nothing to build.** The spec assumed a cramped
  modal. The wizard has always rendered inline (`display: flex`, no overlay, no
  `position: fixed`) so there was no modal to escape. The premise was inherited
  from this document rather than from the code.

---

## 5. Notes, a real notes app (agents can read it)

**Decided: real notes, agent-readable. Shipped in P4.**

What "Notes" used to be: a read-only feed of agent memos. Not notes at all : 
nothing Ian wrote, nothing he could edit. It also crashed the whole app on open
(a `bold()` called without an import), which is the best evidence available
that nobody had used it. That feed now lives under **Inbox**, beside the
decisions it belongs with.

### 5.1 Data

New table `notes` (does *not* reuse `journal_entries`, the journal's defining
property is that agents never see it, and that must not be diluted):

```sql
CREATE TABLE notes (
  id         INTEGER PRIMARY KEY,
  title      TEXT NOT NULL DEFAULT '',
  body       TEXT NOT NULL DEFAULT '',
  pinned     INTEGER NOT NULL DEFAULT 0,
  domain     TEXT,              -- optional routing hint for agents
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT               -- soft delete: "Recently Deleted", 30 days
);
```

`title` is derived from the first line on save (iPhone Notes behaviour) but
stored, so list rendering never parses bodies.

### 5.2 Surface (identical on web and mobile; mobile authored first)

- **List**: title, one-line preview, relative date. Pinned section on top.
- **New note**: a single ✎ button, top-right. Opens straight into an empty
  body with the keyboard up. No dialog, no "title" field.
- **Autosave**: debounce 600ms; no save button ever. Offline-queued via the
  existing `lib/offline.js` (notes are `queueable`).
- **Search**: filters as you type across title+body.
- **Swipe left on a row**: Pin / Delete. Delete is a soft delete with an undo
  toast (5s), never a confirm dialog.
- **Detail view**: full-screen with a back chevron and a live "Saving… / Saved"
  state on the phone. **From 901px up the list and editor sit side by side**,
  and the back chevron disappears because the list never left. One component at
  every width.

  *This was deferred once, on the grounds that a second pane would be "the only
  place mobile and desktop diverge structurally, against L1". That reading was
  wrong: L1 says desktop **is** the enhancement, and a `min-width` two-pane over
  identical markup is exactly the enhancement it describes. Corrected and built.*

**One bug worth recording**, because it will happen again to anyone rendering
SQLite booleans in JSX: `pinned` arrives as `0`, and `{note.pinned && <Pin/>}`
evaluates to `0`, which React renders as a literal character. Every note title
read `0Dorm packing list`. Only `false`/`null`/`undefined` are dropped, coerce
with `!!` at every boolean-ish column.

### 5.3 Agent visibility

- New read-only tool `read_notes`, allowlisted to **`chief` + `archivist`
  only** (the two roles whose job is synthesis and memory).
- Notes are surfaced to those agents as `(title, body, updated_at)`; there is
  **no writing counterpart**: no agent may create, edit or delete a note.
  This mirrors `read_pipeline` in v9 exactly.
- The existing agent-memo feed moves to **Inbox**, where decisions already live.

---

## 6. Agents: full character cards

- **Roster page** (`#roster`, reachable from More): 15 cards, each with the
  agent's glyph, codename, real role id, domain badges, cadence
  (daily / weekly / tripwire), and **last seen** ("ran last night", "sleeping : 
  wakes on a Partner date within 14 days").
- **Track record**, computed from existing tables, no new writes:
  proposals made / approved / rejected. This is honest and useful, it tells
  Ian which agents he actually trusts. *(No shaming framing: it is the agent's
  record, not Ian's.)*
- **Voice**: each memo/proposal renders with the agent's signature color and
  glyph avatar (extends the existing `RoleTag.jsx`).
- **Tonight's slate**: a quiet line on Command: "Belfort, Hermione and Samwell
  ran": sourced from the dispatcher's existing decision, costing nothing.
- Personality remains **seasoning, not content** (existing `SHARED_RULES`
  law): if voice ever fights clarity, clarity wins.

---

## 7. What this touches outside the UI

Deliberately small:

- `core/db.py`, one new table (`notes`) + helpers. No changes to existing tables.
- `agents/runner.py`, one new read-only tool `read_notes`, two allowlist entries.
- `api/main.py`: `/api/notes` CRUD; `/api/roster` extended with track record.
- **No change** to: guardrails, dispatcher, streaks, metrics, The Line, the
  journal privacy wall, or any existing goal/metric resolver.

---

## 8. Phases

| Phase | Scope | Why this order |
|---|---|---|
| **P0. Stop the bleeding** | D1 nav visibility, D2 `dvh` + scroll-jail, 44px targets | The phone app is currently unusable. Hours, not days. |
| **P0.5. Standalone** | D4 safe-area insets survive every override; installed-only defects | The browser and the installed app are *different runtimes*. P0 was verified in a tab, which is exactly why D4 survived it. |
| **P1. Navigation** | Tab bar, swipe ring, More sheet, collapsing context strip, delete page titles | The spine everything else hangs on |
| **P2. Command** | L4 rebuild, signal cap, delete duplicate pillar strip, empty states | The screen he opens 20×/day |
| **P3. Editing** | Plan tap-to-create/drag/resize; goal swipe + inline target | His two named complaints |
| **P4. Notes** | Table, API, list/detail, autosave, search, swipe, `read_notes` | Net-new capability |
| **P5. Agents** | Roster page, character cards, voice, tonight's slate | Delight layer |
| **P6: osui skill** | `.claude/skills/osui/SKILL.md` | Encodes §1 so it survives me |

**Status:** P0, P0.5, P1, P2, P3, P4, P5, P6 shipped, and the three items this
spec once listed as deferred are now resolved:

| Deferred item | Outcome |
|---|---|
| Swipe actions on goal rows (§4.2) | **Built.** The conflict with the pillar swipe was real; solved with a `data-swipe-own` opt-out rather than by dropping the feature. Archive replaces delete, because a hard `DELETE` may not hang off a gesture. |
| Two-pane desktop notes (§5.2) | **Built.** The reason for deferring it misread L1: desktop *is* the enhancement. |
| Full-screen goal wizard (§4.2) | **Nothing to build.** The "cramped modal" never existed; the wizard has always been inline. The premise came from this document, not the code. |

Found while finishing them: on a phone `.goal-row` gave the meter a fixed 220px
of a 261px row, leaving **25px for the title**, so "Gym every weekday" wrapped
to one word per line at 60px tall. Pre-existing, on a page behind "More" that
had never been screenshotted at 375px. Now one column: title, meter, value.

Each phase ends with: `make test` green, a real-device-width browser pass, and
a screenshot at 375×667 and 375×812.

---

## 9. Acceptance gates

A phase is not done until **all** of these hold at 375px:

1. The tab bar is visible and every tab reaches its page.
2. No horizontal scroll on `body` at 320px, 375px, 390px, 430px.
3. The primary action of every page is within the bottom third.
4. Nothing important is below the fold at 375×**667**.
5. `100vh` appears nowhere; `dvh`/`svh` used with a `vh` fallback.
6. **Revised during P0.** Originally "`body` is scrollable; the URL bar
   collapses on scroll." On reflection that is the wrong call *for this app*:
   ianOS is installed to the home screen and runs **standalone**, where there is
   no URL bar to reclaim, and document scrolling would let the tab bar drift
   under a rubber-band. The gate is now: the shell is exactly one viewport
   (`100dvh`), `.page-content` is the single scroller, and it must have
   `overscroll-behavior-y: contain` plus momentum scrolling so it never chains
   to the page behind it.
7. Every fixed edge respects `env(safe-area-inset-*)`, **and no later rule
   drops them via a padding shorthand**, checked with simulated insets
   (47px / 34px), not only in a browser tab (L9).
8. All interactive targets ≥ 44×44px.
9. No more than two stacked `backdrop-filter` layers.
10. `prefers-reduced-motion` disables all non-essential motion.
11. No zero-value badges, no title/subtitle restating the tab name.
12. Existing design laws intact: no `--crit` in Plan/Journal/The Line/lock
    screen; no percentage, streak-break, or lifetime counter anywhere.

---

## 10. Explicit non-goals

- No new color palette. The existing near-black + accent stays (Ian likes it).
- No component library. Hand-rolled, as today.
- No router. Hash pages stay.
- No redesign of The Line's three beats, v9 shipped them deliberately.
- No touching the journal's privacy wall.
