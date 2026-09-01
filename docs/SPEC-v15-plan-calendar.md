# SPEC-v15: The Plan calendar, on both surfaces

Status: **shipped** (all four phases). Supersedes nothing; extends SPEC-v7
(Plan) and inherits the design law of SPEC-v10 (osUI), SPEC-v13 (mobile) and
SPEC-v14 (desktop). Where the build diverged from this plan, §6 says so.

Scope: `dashboard/src/pages/PlanPage.jsx`, `dashboard/src/lib/plan.js`,
`core/plan.py`, the `.plan-*` layer of `dashboard/src/styles.css`, and the
`/api/day` + `/api/plan/*` endpoints.

## 0. Why this exists

Two separate reasons, and they pull in different directions.

The first is that **Plan has no desktop layer at all**. Not a thin one: none.
A brace-matched scan of every `@media (min-width: 901px)` block in
`styles.css` returns zero `.plan-*` selectors. The page is a 375px phone
column with `max-width: 760px` (`styles.css:2941`, a base rule, not an
enhancement) centred on a 1440px screen. SPEC-v14 built the desktop
enhancement layer for Money, Memory, Roster and Inbox and **missed Plan
entirely**. This is osUI L16 unapplied on the one page where a laptop's extra
width is worth the most, because a calendar is the canonical wide surface.

The second is that the interaction model is a **form**, not a calendar. You
tap a cell, a sheet opens, you fill in a title and two `<input type="time">`
fields and pick a duration chip. Every real calendar app lets you draw a block
directly on the grid. Ian has attention constraints; the product's whole thesis is
low activation energy. A four-field modal is the highest-activation-energy way
to say "gym at seven".

### What "better than a real calendar app" actually means here

Not feature parity. Fantastical and Apple Calendar are built for people
tracking obligations they will keep. ianOS is built for one person who
sometimes will not, and whose planning surface must not punish him for it.
That difference is the advantage, and it is currently under-exploited:

- ianOS already distinguishes **commitments** (external, read-only, synced
  from iCloud) from **intentions** (his own, editable). Apple Calendar has no
  such concept; everything is an "event". ianOS renders both as near-identical
  rectangles and throws the distinction away.
- ianOS already knows his call quota, his hero goal, his gym streak and his
  open Partner tasks. No calendar on earth can suggest "call block, 60 minutes"
  because you are 12 dials under quota. ianOS computes exactly that in
  `suggest_blocks()`, then hides it inside a modal.
- A sailed block is a solved design problem here (`--crit` banned, softened
  rendering, never "overdue"). But recovering from three sailed blocks still
  costs six taps.

The spec below fixes the defects first, then leans into those three.

## 1. Verified defect ledger

Every item was read in source, not inferred. Severity: **P1** ships broken
behaviour a user will hit; **P2** is a real gap with a workaround; **P3** is
polish.

| # | Sev | Defect | Evidence |
|---|---|---|---|
| C1 | P1 | **A block hides a commitment completely.** `.plan-commit` is `left:56px; right:8px; z-index:2; pointer-events:none`; `.plan-block` is `z-index:3` over the same span. `layoutColumns(blocks)` is passed blocks only, so overlap resolution never sees commitments. Plan a block at 10:00 and your 10:00 class vanishes, untappable. | `styles.css:3003-3014`, `PlanPage.jsx:51`, `lib/plan.js:48` |
| C2 | P1 | **Blocks outside 06:00-23:00 are creatable and invisible.** The API accepts any `0 <= hh < 24` on a 15-minute boundary; the ribbon renders `DAY_START=06:00` to `DAY_END=23:00`. Type `05:00` into the sheet's time input: it saves, returns 200, and renders at `top: -60px`, clipped. Same for a 05:30 iCloud commitment. | `api/main.py:756-765`, `lib/plan.js:4-5`, `PlanPage.jsx:285` |
| C3 | P1 | **Resize is blind.** The block's time label renders `toHHMM(s)` while dragging, but a resize only mutates `e`. So during a resize the number on screen never changes. You are dragging an edge with no readout of where it lands. | `PlanPage.jsx:297`, `PlanPage.jsx:147` |
| C4 | P2 | **The day strip re-centres on every tap.** `weekDates` is `addDays(date, i-3)`, always `[date-3 … date+3]`. Tapping the rightmost chip shifts all seven chips three days left and moves the tapped day to the middle. Chip positions carry no stable meaning, so spatial memory never forms. | `PlanPage.jsx:70-73` |
| C5 | P2 | **`day.icloud` is returned and never rendered.** `/api/day` returns `{configured, last_sync}`. A grep for `icloud` across `dashboard/src/` returns nothing. SPEC-v7 §"inline line under the header, never a modal" specified this surface; it was never built. There is no way to tell a stale calendar from an empty one. | `api/main.py:789-792`, `PlanPage.jsx` (absent) |
| C6 | P2 | **Delete has no undo**, while Goals, Notes and Memory all got undo-toasts in SPEC-v13/v14. `del()` fires a hard `DELETE` and toasts `removed`. The osUI trap table's soft-delete law is applied on three surfaces and skipped on this one. | `PlanPage.jsx:199-202` |
| C7 | P2 | **No way back to now.** The now-line is centred once, in an effect keyed `[day, isToday]`. Scroll away and nothing returns you; `Today` changes the date but never scrolls. On a laptop left open, the now-line drifts off-screen for the rest of the day. | `PlanPage.jsx:54-59` |
| C8 | P2 | **Suggestions are unreachable until you are already committed.** They render only inside the create sheet. The empty state says "or start with a suggestion" while displaying no suggestion. | `PlanPage.jsx:387-394`, `PlanPage.jsx:313` |
| C9 | P2 | **No drag-to-create.** `.plan-cell` is a per-hour `<button>` with a click handler. Creation is always tap → modal → form. Every mainstream calendar draws the block on the grid. | `PlanPage.jsx:253-262` |
| C10 | P3 | **Overlap degrades to unreadable.** `layoutColumns` divides width evenly. Three overlapping blocks at 375px, minus the 56px gutter, leave roughly 100px each; `.plan-block-title` is `white-space: nowrap` with ellipsis, so the third block shows two characters. | `lib/plan.js:48-73`, `styles.css:3027` |
| C11 | P3 | **Cell `aria-label` lies.** It announces "Add a block at 9:00" but the handler creates at the tapped 15-minute offset, so a screen-reader user is told 9:00 and gets 9:45. | `PlanPage.jsx:257-261` |
| C12 | P3 | **The now-line carries no time.** It is a rule plus a dot, `aria-hidden`. Every reference calendar labels it. | `styles.css:3036-3037` |
| C13 | P3 | **A linked block never names its goal.** `goal_id` earns a green left border and nothing else; the sheet does not say which goal. The signal is decorative. | `styles.css:3025`, `PlanPage.jsx:456` |
| C14 | P3 | **No keyboard model on desktop.** Only `Escape`. No day navigation, no "new block", no focus ring on the grid. SPEC-v14 established keyboard parity as a desktop obligation. | `PlanPage.jsx:41-45` |
| C15 | P3 | **`.plan-ribbon` height is a magic number**, `calc(var(--app-height,100dvh) - 250px)`, with a second magic `280px` at the desktop breakpoint. The osUI trap table already records what hard-coded bar heights in two places cost. | `styles.css:2985`, `styles.css:3083` |

Open copy question, not a defect: the overpack line reads
`"That's a lot for one day. Champions pick 3."` (`core/plan.py:66`). The
aphoristic cadence sits close to what the anti-slop rule bans, and "Champions"
is motivational-poster register. Flagging for Ian's call, not changing it
unilaterally, since SPEC-v7 shipped that string deliberately.

## 2. Design law additions (binding, extends SPEC-v14 L16-L19)

**L20. Commitments and intentions are different object classes, and must never
occupy the same lane.** An external commitment is a constraint Ian does not
control; a block is an intention he does. Rendering them as competing
rectangles in one column is what produced C1. They get separate lanes, and
overlap resolution runs per lane.

**L21. A time surface renders every item it will accept.** If an endpoint
accepts 00:00-23:59, the grid shows 00:00-23:59, or the endpoint narrows to
match. A row that saves successfully and renders nowhere is data loss with a
success toast.

**L22. A direct-manipulation gesture shows the value it is changing, live.**
Drag-to-move shows the new start; drag-to-resize shows the new end. A gesture
whose readout does not track the mutation is worse than a form, because the
form at least tells the truth.

**L23. Destructive actions carry the same undo on every surface.** The app
established single-tap-plus-undo-toast on Goals, Notes and Memory. A fourth
surface using a bare hard delete is not a local choice, it is an
inconsistency the user has to remember.

## 3. The build

### Phase 1: correctness (C1, C2, C3, C6, C11)

**Two-lane ribbon (C1, and it sharpens the identity).** Split the grid into a
narrow **commitment rail** and a wide **intention lane**:

```
| 06 | ▏commitments▕ |          blocks           |
   56px    ~72px              remaining width
```

Commitments keep `pointer-events: none` and their muted, italic treatment.
Blocks lay out with `layoutColumns` inside their own lane only. Nothing can
hide anything. This is one CSS change plus one inline-style change and it
resolves C1 permanently, because the two classes can no longer collide by
construction.

**Derived ribbon bounds (C2).** Replace the constants with a window computed
from the day's contents:

```js
// 06:00-23:00 by default; widen to include anything the day actually holds.
const lo = Math.min(DAY_START, ...items.map(startOf))
const hi = Math.max(DAY_END,   ...items.map(endOf))
```

An early flight pulls the top of the ribbon up to 05:00 on that day only. No
wasted empty hours on ordinary days, no invisible rows ever. `core/plan.py`
keeps `DAY_START_MIN`/`LATEST_START_MIN` for *suggestion* placement, which is a
different question and correctly stays 06:00-22:00.

**Live resize readout (C3).** Render the edge being dragged:
`mode === 'resize' ? toHHMM(e) : toHHMM(s)`. One expression.

**Undo on delete (C6).** Use the existing toast-undo pattern. Server-side,
`DELETE` already writes a `plan_tombstones` row for sync safety, so undo must
recreate *and* clear the tombstone, or the next iCloud pull will delete it
again remotely. That coupling is the reason this is Phase 1 and not a
one-liner.

**Honest cell labels (C11).** Announce the hour range the cell covers
("Add a block between 9:00 and 10:00"), since the exact minute depends on tap
position and cannot be known ahead of the event.

### Phase 2: the desktop calendar (C4, C7, C14, and the L16 gap)

**Week view, desktop only, behind `@media (min-width: 901px)`.** Seven columns
sharing one hour gutter and one scroller, same `PX` scale, now-line spanning
only today's column. Day view stays the mobile default and stays available on
desktop via a `D`/`W` segmented control.

This is the single largest visible win on the web surface, and it is exactly
the enhancement L1 licenses: the phone keeps one screen and one job, the
laptop gets the overview the extra 700px is for.

**Stable week strip (C4).** Anchor the strip to the week containing `date`,
Monday-first, and move only the selection. Tapping Friday leaves Monday where
Monday was. On desktop the strip is redundant with week view and hides.

**Jump to now (C7).** A pill that appears only when the now-line is scrolled
out of view, and scrolls it back to the upper third. Same affordance real
calendars use, and it costs nothing when you are already looking at now.

**Keyboard model (C14), desktop only:**

| Key | Action |
|---|---|
| `←` `→` | previous / next day (week in week view) |
| `T` | today |
| `N` | new block at the next free slot |
| `D` `W` | day / week view |
| `Enter` | open the focused block |
| `Escape` | close the sheet |

Grid cells become focusable with a visible ring, reusing SPEC-v14's focus
tokens. `useFocusTrap` is already wired on the sheet.

### Phase 3: activation energy (C8, C9, and the differentiators)

**Natural-language quick add.** One text field, always visible above the
ribbon on both surfaces:

```
gym 7            → "gym",       07:00-08:00
deep work 2h @ 9 → "deep work", 09:00-11:00
call block 30m 2pm → "call block", 14:00-14:30
partner dinner 6-8 → "partner dinner", 18:00-20:00
```

**Deterministic parser, never a model call.** This follows the binding
precedent from The Line: `call_card()` composes its script by templating
because a model in the interaction path costs money per keystroke and adds
latency at the exact moment Ian needs none. The parser lives in `core/plan.py`
with a mirror in `lib/plan.js` (the same dual-implementation contract the time
math already uses), and it is trivially unit-testable: a table of input
strings to expected `(title, start, end)` triples.

Rules, in order: strip a trailing duration (`30m`, `2h`, `1.5h`), strip a
trailing time or range (`7`, `7am`, `14:30`, `6-8`, `@ 9`), the remainder is
the title. No time found means the next free slot. No duration found means 60
minutes. If parsing yields no title, do nothing and leave the text alone;
never guess a title.

**The ambiguity rule is nearest-future.** A bare hour has two readings, so take
the next one that has not yet passed, falling back to the later reading when
both have. `gym 7` at 06:00 is 07:00; the same words at 09:00 can only mean
19:00, and `6-8` typed in the morning is 18:00-20:00. One rule covers every
case, which matters because the user has to be able to predict it.

This is the highest-leverage item in the spec. It turns planning from
tap-modal-form-form-chip-submit into one line of typing, on the page that
exists specifically to lower activation energy.

**Suggestions on the page, not in the modal (C8).** Render the
`suggest_blocks()` chips inline under the quick-add field whenever the day has
room. They are already computed and already returned by `/api/day`. This is
the feature no commercial calendar can copy, because it needs the call quota,
the hero goal and the gym streak, and it is currently invisible until you have
already decided to create something.

**Drag to create (C9).** Press and drag on empty grid to draw the block, then
the sheet opens pre-filled with the drawn range and focus in the title field.
The existing gesture arbitration applies unchanged: 300ms long-press arming on
touch, 8px threshold on mouse, non-passive `touchmove` (osUI trap table).

**Sweep sailed to tomorrow.** When a day ends with sailed blocks, one control:
`Move 3 sailed blocks to tomorrow`. One tap, one toast, one undo.

This is the item that makes the calendar better than Apple's rather than equal
to it. Every mainstream calendar treats a missed event as a historical fact to
be left alone or turned red. ianOS already refuses to redden it (`--crit`
banned here). Refusing to *charge six taps for the recovery* is the same
principle carried through to its conclusion, and it is the single most
attention-specific idea in this document.

### Phase 4: honest signals (C5, C10, C12, C13, C15)

- **iCloud status line (C5).** One inline line under the day strip:
  `Calendar synced 14:32` / `Calendar sync not configured`. Never a modal,
  never blocking, per SPEC-v7 §"inline line under the header".
- **Overlap cascade (C10).** Past two columns, stop dividing. Offset each
  additional block by 12px with a shadow, so the top one stays readable and
  the count stays visible. Fantastical's resolution, and it degrades to
  "there are several things here" instead of to noise.
- **Labelled now-line (C12).** The current time in the gutter, replacing the
  bare dot. Drop `aria-hidden` and expose it as a `<time>`.
- **Named goal link (C13).** The sheet shows `Linked: {goal name}`. The green
  border stays as the at-a-glance marker.
- **One ribbon-height token (C15).** `--ribbon-offset`, set once, overridden
  once at the breakpoint. The trap table already documents what two hard-coded
  heights cost.

## 4. Explicitly not doing

- **Recurring blocks.** A real want (gym is five identical blocks a week), but
  recurrence is a schema change plus an expansion rule plus an exception model
  plus a two-way sync contract with iCloud's own RRULE handling. That is its
  own spec, and doing it badly corrupts the CalDAV seam. Deferred, named here
  so it is not mistaken for an oversight.
- **Month view.** A month grid answers "what is the shape of my month", which
  is a question the six pillars and the goal targets already answer better.
  It would be a calendar feature added because calendars have it.
- **Block completion percentages, adherence rings, streaks.** Banned by
  SPEC-v7 §25 and by inherited product law. `plan_adherence_7d` stays
  agent-only. Non-negotiable.
- **`--crit` red anywhere on this page**, including on conflict warnings and
  the overpack line. A conflict softens or outlines; it never alarms.
- **An LLM in the quick-add path.** See Phase 3.

## 5. Verification

Standard osUI order (`.claude/skills/osui/SKILL.md` §"Verifying UI work"),
plus:

1. `cd dashboard && npm run build`, cache-busted reload.
2. **375×667**: quick-add and the now-line both above the fold; every target
   ≥44×44; no horizontal scroll at 320/375/390/430.
3. **Simulated insets** (47px top / 34px bottom): the sheet, the quick-add
   field and the sweep control all clear the tab bar and the home indicator.
4. **1280×800 and 1440×900**: week view renders seven columns with no
   horizontal scroll; every keyboard binding in §Phase 2 works; focus ring
   visible on grid cells.
5. **C1 regression**: create a block exactly over a synced commitment on both
   surfaces, confirm both remain visible and the commitment stays untappable.
6. **C2 regression**: create a 05:00 block and a 23:30 block; both render.
7. `make test`, including new `tests/test_plan.py` cases for the quick-add
   parser table and the derived ribbon bounds, and the existing SPEC-v7
   assertions unchanged.

## 6. As built: where this plan was wrong

Recorded because a spec is a record of intent, and the next person needs the
codebase, not the intent.

- **`--ribbon-offset` was the wrong fix for C15.** §Phase 4 called for one
  token set once and overridden once. Building it showed the token is
  unknowable: the chrome above the ribbon changes height with whether
  suggestions, signals or the sweep control are present. Measured at 375x667
  the new offset put the ribbon's bottom edge at 620px against a tab bar
  starting at 615px, that is, **under it**, exactly the class of bug the
  original literal caused. The ribbon now flexes inside a flex-column page and
  no number exists to be wrong.
- **That flex change then broke the rows above it.** Every flex child is
  shrinkable by default, so once content exceeded the page height the browser
  compressed them: the suggestion row collapsed to 9px around its own 18px
  chips and sliced them in half. Fixed with
  `.plan-page > *:not(.plan-ribbon) { flex: 0 0 auto }`. Worth stating plainly
  because it is the second-order cost of a layout change that looked local.
- **The cascade needed opacity, not just offset.** §Phase 4 specified a 12px
  offset and a shadow. At the block's `0.14` alpha all three titles showed
  through each other, which is *less* legible than the even split it replaced.
  Cascaded blocks now composite the same tint over an opaque base so the front
  card genuinely occludes.
- **Week headers cannot live in the column.** The obvious placement puts them
  at `top: 0` of each `.plan-col`, which is the top of a ~1000px scrolling
  canvas, so the day each column belongs to scrolls out of view immediately.
  They are a fixed row above the scroller, mirroring `.plan-cols` padding and
  gap so the labels stay over their columns.
- **`GET /api/week` was not in the plan.** Week view needs seven days with one
  shared time axis; seven `/api/day` calls would have computed suggestions,
  overpack and iCloud status seven times for a view that shows none of them.
  The endpoint is deliberately lighter, and computes bounds across the whole
  week so a 05:00 block on Thursday moves the top of every column rather than
  desynchronising them.
- **Drag within a column works in week view; dragging *across* days does not.**
  The gesture is delta-on-Y and needs no change per column, but changing a
  block's date by dragging is a different feature. Not built, named here so it
  is not mistaken for a bug.
- **The suggestion row is a horizontal scroller and carries `data-swipe-own`.**
  Four chips wrapped to three rows at 375px. Making it one scrolling line
  triggers the osUI trap about two horizontal gestures on the same pixel, so
  it claims the gesture and the pillar ring skips it.

## Related

- `docs/SPEC-v7-plan.md`, the original Plan spec: data model, iCloud seam,
  design laws this document inherits.
- `docs/SPEC-v10-osui.md`, mobile-first law; `.claude/skills/osui/SKILL.md`,
  the working checklist and the trap table.
- `docs/SPEC-v13-impeccable-mobile.md` (L10-L15),
  `docs/SPEC-v14-impeccable-web.md` (L16-L19), the two audit passes whose
  desktop-parity lesson this spec applies to the page they missed.
