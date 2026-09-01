# SPEC-v14: Impeccable web: the desktop enhancement, made worthy of the name

Status: Phase 1 implemented this pass (all P1 + a large curated P2/P3 slice).
Extends `SPEC-v10-osui.md` L1 ("mobile is the design target, desktop is the
enhancement") and `SPEC-v13-impeccable-mobile.md`'s shared z-scale and form
laws. Does not change any agent, guardrail, table, or metric.

---

## 0. Why this exists

`SPEC-v13` made the phone impeccable. This pass does the same for the other
half of the same app: the `@media (min-width: 901px)` enhancement layer Ian
actually uses at night, from a laptop (1280-1512px, per `PRODUCT.md`), not a
phone. An `/impeccable audit` ran nine specialist passes (accessibility,
performance/theming, anti-patterns, layout density, interaction model,
typography, data-heavy pages, navigation/command-palette) and returned 65 raw
findings; every one was re-verified against source before being trusted.

**Anti-pattern / AI-slop scorecard: 3/4** ("disciplined system, two localized
SaaS-cliche drifts", the audit's own words). The dark-glass HUD identity is
intact almost everywhere; Money's and Partner's hero cards are the two spots
that drifted toward the generic SaaS-dashboard template this product was
explicitly built to avoid (`PRODUCT.md` anti-references).

**Scorecard (impeccable audit rubric, before this pass):**

| Dimension | Before | Key finding |
|---|---|---|
| Accessibility | Real WCAG AA gaps | Placeholder/label text ~1.9-4.4:1 (below 4.5:1), no `<main>`/skip link, no focus trap on the palette or Plan sheet, no visible focus on `<select>`, goal Archive literally `display: none` on every desktop width |
| Performance | Good, two real gaps | One arbitrary `z-index: 45` outside the shared scale; Memory/memo lists re-render in full on every 15s poll |
| Theming | Good, tokens mostly honored | ~100 hand-typed `rgba()` restatements of 4 tokens; `--font-mono` referenced but never defined (silently falls back) |
| Responsive/desktop | The real gap | Every data-heavy page (Money, Memory, Roster, Inbox, Leads) is the identical single mobile-derived column, just wider, with 100-350px of dead gutter on a real laptop |
| Anti-patterns | 3/4 | Money and Partner hero cards read as the banned "hero-metric" SaaS template; one decorative infinite animation with zero state meaning; one redundant color-stripe border |

---

## 1. Design law additions (binding, extends SPEC-v13 L10-L15)

**L16. A desktop-enhancement page differentiates prose width from list/grid
width.** `--content-w` (920px) remains the correct cap for anything read as
running prose (the Command hero's 40ch measure, a memo body, a brief). It is
the WRONG cap for anything that is fundamentally a list or grid of records
(Money's cards, Memory's fact domains, the Roster grid, Inbox's proposals +
memo feed): those get their own `@media (min-width: 901px)` width, sized to
actually use the laptop viewport instead of stretching a phone column wider.
This revises the file's prior "ONE content width, every page" comment,
deliberately, for the data-dense pages named above; prose pages keep 920px.

**L17. Every state-carrying color signal that exists on mobile exists on
desktop, and vice versa.** The mobile tab-tint fix (muted-by-default,
accent-on-active) never reached the desktop nav-rail, leaving 14 nav-rail
glyphs permanently lit regardless of page. A fix landing on one input surface
and not the other is exactly the "same conceptual weight, same visual weight
throughout" law from the impeccable product register; apply state-carrying
CSS to the shared selector, not a device-scoped one, unless the two surfaces
genuinely need different visual treatments (they don't, here).

**L18. A soft-delete law stated in prose must be true on every input device.**
"Goals are archived, never deleted, from the UI" is a CLAUDE.md law enforced
by a single component (the swipe-reveal Archive action) that is `display:
none` above 901px with no substitute. A product law that only holds on one
input device isn't a law, it's an accident. Every mobile-only interaction that
enforces a stated product law needs an always-available desktop equivalent.

**L19. Decorative motion tied to nothing in the data is deleted, not kept
"because it's pretty."** This restates the product register's own ban
explicitly against the one place it was violated (Partner's infinite 6s glow
pulse), because "the user likes this page" is not an exemption from the law.

---

## 2. The defect ledger

Deduplicated from the 64 verified findings (several were independently
re-derived from two dimensions at once; that convergence is itself signal).

### P1: WCAG AA violations, broken product law, or clear daily-use degradation

| # | Defect | Fix |
|---|---|---|
| W1 | Journal composer placeholder renders at ~1.9:1 contrast (`opacity: 0.5` stacked on `var(--muted)`) | Drop the opacity override; placeholder color promoted to `var(--dim)` (~8.5:1) |
| W2 | `var(--muted)` (labels, tags, all placeholders) computes 4.24-4.60:1 on glass/panel surfaces, under the 4.5:1 AA floor for normal text | Promote every load-bearing use of `--muted` (`.section-label`, `.panel-tag`, `.empty-title`, `::placeholder`) to `var(--dim)`; `--muted` stays for genuinely decorative/tertiary text only |
| W3 | Native `<select>` has zero visible focus indicator (own base rule sets `outline: none`, the shared `:focus-visible` rule omits `select`) | Add `select` to the global `:focus-visible` rule |
| W4 | Goal Archive (the CLAUDE.md soft-delete law) is `display: none` at every desktop width; the only remaining path is `GoalForm`'s hard, un-doable `DELETE` | A persistent Archive glyph beside the existing `.edit-glyph` pencil, calling the same `archive()` `SwipeRow` already uses |
| W5 | Command Palette and the Plan block sheet are `role="dialog"` with no focus trap and no return-focus on close | A small shared focus-trap: capture `activeElement` on open, wrap Tab/Shift+Tab at the dialog's first/last focusable child, restore focus on close |
| W6 | No `<main>` landmark, no skip link; a keyboard visit tabs through all 16 nav-rail stops before reaching any page content | `<div className="app-main">` → `<main id="main-content">`; a visually-hidden-until-focused "Skip to content" link as the first focusable element |
| W7 | `.plan-burst` (`position: fixed`, page-level stacking) uses a bare `z-index: 45`, the sole non-token value in a file whose entire premise (SPEC-v13) is one semantic z-scale | `z-index: var(--z-sheet)` (the burst never needs to outrank a sheet) |
| W8 | `.money-hero` uses a `linear-gradient` wash + uppercase eyebrow + oversized number + stat grid: the literal hero-metric SaaS template the skill bans, the only pillar hero styled this way besides Partner | Flatten to the same single-tint `rgba()` wash `.goal-hero`/`.school-hero` already use correctly; keep the number and stats, they're earned instrumentation |
| W9 | `.partner-hero` runs a perpetual 6s box-shadow pulse tied to nothing in the data, plus a 3-stop gradient wash | Delete the infinite animation (or make it one-shot on mount, matching `.ord-text`'s reveal-once pattern); flatten the gradient |
| W10 | `.plan-block`'s `border-left: 3px solid var(--accent)` restates state the full border/background already carry (a banned side-stripe accent) | Drop the border-left override for the default/accent/done states; **keep it for `.plan-block.linked`**, which has no other visual signal at all (verified: the ONLY rule for that class) |
| W11 | `.money-grid`, `.memory-domain` sections, and the Command grid all stay a single mobile-derived column at every desktop width, with 100-350px of dead gutter on a real laptop (L16) | Per-page `@media (min-width: 901px)` overrides: Money → 2-col grid, Memory → 2-col domain layout, Command → widened cap + rail |
| W12 | Plan blocks arm a 300ms long-press timer before a drag begins, on **mouse** input too, a delay that exists solely to disambiguate touch-drag from touch-scroll | Branch `beginPress` by pointer type: keep the 300ms arm for touch, arm immediately past an 8px threshold for mouse |
| W13 | Inbox stacks Proposals and the full Agent Memo Feed vertically with no side-by-side layout and no keyboard triage, on the one page whose entire job is nightly approve/reject | `@media (min-width: 901px)`: two-column grid (proposals left, memo context right) |
| W14 | Desktop nav-rail's 14 glyphs are unconditionally `color: var(--accent)`; the SPEC-v13 mobile fix ("unselected muted, tint reserved for active") never reached the desktop selector (L17) | Apply the same pattern to the base `.nav-icon` rule, not just `.nav-mobile .nav-icon` |

### P2/P3 (large curated slice implemented in Phase 1)

- **Accessibility, the rest:** `GoalForm`'s Goal/Quota/Deadline segmented
  picker gets `role="radiogroup"`/`role="radio"`/`aria-checked` (the exact
  pattern already correct on the workout picker two files over); the Memory
  fact-edit textarea gets a real label; the note-autosave status gets
  `aria-live="polite"`; three inputs (`.journal-box`, `.line-note`,
  `.lead-search`) get the same `box-shadow` focus ring every other control
  already has; Command Palette's result buttons get `tabIndex={-1}` so Tab
  and the `aria-activedescendant` arrow-key model stop fighting each other.
- **Anti-pattern/theming cleanup:** the two fluid `clamp()` font-sizes on the
  live Day Command text (`.ord-text`, `.ord-text-dim`) become fixed sizes
  with a `min-width: 901px` override, honoring the file's own declared "fixed
  type scale" law; `--font-mono` (referenced, never defined, silently
  falling back) corrected to `--mono` on the two elements that use it
  (notably the Cmd+K `kbd` chip); the desktop input/textarea/select font
  restore moves from 13px to 14px so typed text doesn't sit a full step
  below the surrounding reading text; uppercase micro-label letter-spacing
  (0.04em-0.14em across near-identical roles) unified to one token; the
  Journal page's stray `min-width: 900px` breakpoint corrected to the file's
  standard 901px.
- **Data-heavy pages:** Roster's grid widened to reach 4 columns on a
  laptop instead of an implicit 3; Roster gains a sort control (trust rate /
  last-seen / alphabetical) over data that already exists; Roster and Notes
  gain real loading states (no more blank-flash or false-empty-state before
  the fetch resolves); Money's detail section now defaults open at desktop
  widths (`matchMedia('(min-width: 901px)')`) instead of costing an extra
  click every session; Memory gains a search input over its fact store;
  Memory's fact-delete now matches the app's own single-tap-plus-Undo
  convention instead of being the one two-click, no-undo delete in the
  product; ellipsis-truncated Plan block titles and Notes previews get
  native `title` tooltips (mirroring Money's existing pattern); LeadList's
  pre-debounce render no longer flashes a false "nothing matches" on a
  1,958-row list.
- **Command Palette:** indexed pages gain the missing `roster` entry; the
  inline partner-vs-life goal routing (which had drifted from `lib/pillars.js`'s
  `isPartnerGoal`, a real misroute for goals named with "partner" but no
  `#partner` note tag) now imports the shared helper; the Cmd+K trigger in the
  nav-rail gains a visible "Jump" label instead of relying on a tooltip for
  the product's single most power-user-branded feature; generic "Go to page"
  filler sub-labels removed (L3, zero-value pixels); the palette now also
  indexes Memory facts, so "jump anywhere" can actually reach the app's
  fact store, not just pages/pillars/goals.
- **Cleanup:** dead, byte-identical `.prop-more` CSS rule removed in favor of
  the `.memo-more` it duplicates; `finance-change` gets the `tabular-nums`
  its sibling money figures all have; the Notes pin-toggle button gains a
  hover state to match its neighboring delete button; Notes' empty-state
  copy ("Tap ✎ New") no longer references a touch gesture unconditionally.

### Backlog: deliberately deferred

- **Full j/k list navigation** across the memo feed, proposals, and lead
  rows (Inbox's two-column layout ships this pass; the keyboard-nav hook
  extraction from `CommandPalette`'s existing arrow-key reducer is real work
  worth its own pass).
- **A shared `Skeleton` primitive** replacing bare "Loading…" text/blank
  flashes app-wide (Roster and Notes get real loading states this pass as
  the two worst offenders; a systematic skeleton component for every async
  view is a bigger, separable job).
- **Rebuilding the six-step type scale** onto a strict 1.125-1.2 ratio. Real
  finding (12/13/14/16/20/28 jumps unevenly, 1.08x at the bottom to 1.4x at
  the top), but changing the base scale touches every page in the app at
  once; it deserves its own dedicated, carefully-diffed pass, not a
  side-effect of a broader sweep.
- **Token-derived alpha color variants** (`color-mix()` or `--accent-14`-style
  tokens) replacing the ~100 hand-typed `rgba()` restatements of the four
  status colors. Real drift risk, but a pure refactor with no user-visible
  change; sequenced after the visible fixes above.
- **Memory/memo-feed re-render memoization.** Real finding, but wrapping
  `FactCard`/`FactRow` in `React.memo` only pays off if `fact` itself keeps a
  stable reference across unrelated polls; `state.facts` is freshly
  JSON-parsed on every `/api/state` fetch, so the actual fix needs a
  content-based comparator (id/verified/body/date), not a default shallow
  one, the same pattern used for `rosterMap` in SPEC-v13. Deferred rather
  than shipped half-effective.
- **A global `?` shortcuts sheet.** Lower value than the audit's first pass
  suggested once corrected: the palette already documents its own shortcuts
  inline (`.cmdk-hint`). Worth revisiting once the j/k list-nav backlog item
  above actually ships new shortcuts that need documenting.
- **`AuroraBackground` viewport-aware scaling** for desktop's larger canvas
  area (blob count/particle count fixed regardless of canvas size). Real,
  low urgency; the component already does the load-bearing mitigations
  (dpr cap, hidden-tab pause, reduced-motion).

---

## 3. Verification

`npm run build`, bust the service-worker cache, verify at 1280×800 and
1440×900 (the stated laptop target; also spot-check 1920×1080 to confirm
nothing degrades wider), keyboard-only pass through the nav-rail / palette /
Plan sheet / Inbox to confirm the new focus trap and skip link, and re-run
`tests/test_mobile_ui.py` + the full suite to confirm none of these changes
regressed the shared mobile rules (the z-index scale, the form-control base
rule, and the `--content-w` law are all shared tokens touched by this pass).

## Related

- [SPEC-v13-impeccable-mobile.md](SPEC-v13-impeccable-mobile.md): the shared z-scale, form-control base rule, and L1-L15 this spec extends
- [SPEC-v10-osui.md](SPEC-v10-osui.md): L1, "mobile is the design target, desktop is the enhancement", the binding constraint this whole pass works inside
