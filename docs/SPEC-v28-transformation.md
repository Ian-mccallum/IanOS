# SPEC v28: the transformation

Status: **draft, awaiting Ian's additions**. Born from the third impeccable
pass (2026-08-20): a two-assessment audit (design review + mechanical
detector/browser evidence) over every surface at 375x667 and 1280x800.
This file is the plan; the full findings live in the audit report in the
session that produced it. Add freely below; nothing here is implemented yet.

## Audit verdict, in one paragraph

The foundation is genuinely product-specific and worth keeping: the agent
identity system, the reassurance copy at high-stakes moments, the codified
44px/focus/reduced-motion discipline, the no-shame color law. But the newest
layer (SPEC-v26/v27 chat) shipped a second, unfinished overlay system that
ignores the app's own established sheet pattern, page-lifecycle state dies on
every tab switch, and two undefined-CSS-token bugs leave desktop sheets
literally broken. Health score: **12/20 (Acceptable, significant work
needed)**. A11y 3, Performance 2, Theming 3, Responsive 2, Implementation
Integrity 2.

## The three complaints, root-caused

1. **"Leaves Command, comes back to Fury."** `AgentChat.jsx` mounts with a
   hard-coded `openFor('chief')` and the whole component unmounts on tab
   switch (`App.jsx` renders CommandPage conditionally). No storage key
   persists the active agent (full key inventory confirmed). Same lifecycle
   kills the typed draft, and produces a false "That turn expired" banner
   when a non-chief turn is running (the resume logic searches only the
   chief thread).
2. **"Whole-window modals for small choices."** All seven overlays are
   `fixed inset:0` dialogs. The three newest (Context, Reasoning, FileDraft)
   also lost the pattern their elders had: no portal, no Escape, no close
   button, no max-height (the layout rule still targets the renamed-away
   `.chat-file-dialog` class, so the sheet has NO layout at all: measured
   1107px tall at both widths, clipping half the agent list unreachably).
   Separately, desktop AccountSheet/AskAgentSheet reference `var(--s8)`,
   a token that does not exist, so `max-height` computes to `none`: a
   1613px sheet in an 800px viewport whose header and close button sit
   406px above the screen.
3. **"Grey dismisses."** Class-wide: every close/dismiss/cancel is an
   unweighted `--muted`/`--dim` ghost (~4.4:1, borderline for a control),
   placement varies per surface, two surfaces have no dismiss at all, and
   destructive ✕ (delete) shares a glyph with harmless close.

## Issue counts

P0 x3 (agent amnesia, layoutless chat sheets, undefined `--s8` desktop
sheets) · P1 x5 (draft loss, false expiry, sheet weight/placement, no
Escape/close on chat sheets + More sheet, two sub-4.5:1 contrast pairs:
`.ac-source-state` and `.ac-agent-meta` at 4.43) · P2 x10 · P3 x7. The
mechanical pass found zero horizontal scroll at any width, zero unlabeled
icon buttons, and 16 reduced-motion blocks covering all 8 keyframes: the
floor holds; the failures are architectural.

## Systemic causes (fix these, not just the instances)

- **No shared Sheet primitive.** Four hand-rolled overlay implementations;
  the newest forgot five of the pattern's load-bearing parts. Every future
  sheet re-rolls this dice.
- **Undefined CSS custom properties fail silently.** `var(--s8)` ->
  `max-height: none` broke a P0 with zero build warnings. Nothing checks
  that a `var()` reference resolves.
- **Component lifecycle == page visibility.** Everything Ian was doing on
  Command is UI-local state that dies on unmount; only turn ids were
  persisted, and that half-measure produced the false-expiry lie.
- **The one-surface trap is still live** (the repo's own documented trap):
  the sheet max-height is correct on mobile and broken on desktop.
- **Dismissal was never designed**, per surface or as a system.

## The plan

Six phases. Each ships alone; 0 is same-day, 1-2 are the transformation,
3-5 are the payoff on top.

### Phase 0: stop the bleeding (P0s + lies, ~a day)

- Define `--s8: 64px` (or use `--s7`); restore desktop sheet max-height.
- Point the sheet layout rule at `.chat-file-sheet` (or re-add the old
  class) so Context/Reasoning/FileDraft get width, max-height, scroll.
- Persist `ianos:last-chat-role`; mount opens it, falling back to chief.
- Resolve a stored running turn to its own thread before declaring it
  expired; open that thread instead of lying.
- Raise `.ac-source-state` / `.ac-agent-meta` contrast above 4.5 on glass.
- Un-crit the $0 credit card (crit only when balance > 0).

### Phase 1: one Sheet primitive (the complaint-2 killer)

Build a single `Sheet` component and a law, then migrate all seven
overlays (ask-agent, account, plan-block, nav-more, palette stays itself,
and the three chat sheets):

- Phone: bottom sheet rising from the trigger side, thumb-reachable close,
  respects `--kb`.
- Desktop: anchored popover when the content is a small choice set (the
  Context sheet's 4 rows, a model/effort picker), centered dialog otherwise.
- Always: portal to body, focus trap, Escape, visible close meeting the
  Phase 3 standard, internal scroll, max-height from real tokens.
- The law goes next to `--nav-h` and the 44px rule in osui: one overlay
  language, chosen by content weight, never by which spec shipped it.

### Phase 2: state survives navigation (the complaint-1 killer)

- Mount AgentChat once at the app shell (like nav and toasts) and hide it
  when Command is not the page, so thread, draft, scroll, and running turn
  survive tab switches for free. If hoisting fights the pillar-swipe or
  memo structure, fall back to: persisted role + sessionStorage draft
  mirror keyed by thread + turn-to-thread resolution (Phase 0's version).
- Audit every page for the same class: filters on Money history, disclosure
  state on Command, scroll on long feeds. Persist what a two-minute-visit
  user would expect to still be there.

### Phase 3: the dismiss/affordance standard (the complaint-3 killer)

- One close standard: 44px target, `--dim` at rest, agent/accent on
  hover-focus, top-right on desktop cards, bottom-reachable on mobile
  sheets, always paired with backdrop-tap and Escape.
- Destructive ✕ is visually distinct (warn treatment) from neutral close.
- More sheet: Escape + focus trap + exit moved off the top-right ghost.

### Phase 4: cognitive diet on the composer

- Split the Reasoning sheet: the chip opens a small model+effort popover
  (8 options max); agent switching becomes its own lighter affordance.
  25+ visible choices in one modal is the opposite of the product thesis.
- Sensible-defaults question for Ian below (see Open questions).
- "Inspect" once per surface, not once per row; rows become the target.
- Today disclosure gets a real affordance ("Today · N items"), promoted
  above the stream when it holds attention items.
- Keyboard hints desktop-only; zeros render as absence (osui gate 11);
  one T-minus grammar ("34d late" vs "T-5d"), stated once.

### Phase 5: mechanics and guardrails

- A test that every `var(--x)` in styles.css resolves to a defined token
  (would have caught both P0 classes; cheap grep-level).
- `strip_em_dashes` applied at proposal/memo write time, not only chat.
- The two `padding-left` hover transitions -> transform.
- Bundle: split the single 512KB chunk (route-level lazy for Journal,
  Plan, Money history); drop the per-tick `JSON.stringify` comparators
  for cheap key equality.
- Month filter labeled; Money history gets a "back to Money" crumb.

## Open questions for Ian (add answers or more items below)

1. **Mount-once chat**: OK to hoist AgentChat to the shell so it never
   unmounts (Phase 2's clean version)?
2. **Should you be picking models at all?** The audit's sharpest question:
   deterministic-dispatch is the product's soul, yet the composer's most
   prominent control is model x effort x 15 agents. A "smart default,
   override rarely" design would shrink the Reasoning sheet to almost
   nothing. Keep the full picker, or demote it?
3. Anything below this line is Ian's:

---
