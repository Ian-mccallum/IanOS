# SPEC-v13: Impeccable mobile: closing the gap to an Apple-made app

Status: Phase 1 implemented this pass (P0 + P1 + a curated P2 slice).
Extends `SPEC-v10-osui.md` law, does not weaken or replace any of it.
Does not change any agent, guardrail, table, or metric.

---

## 0. Why this exists

ianOS is read by exactly one device that matters: Ian's iPhone,
installed to the home screen. `SPEC-v10-osui.md` fixed the defects that made
the phone unusable (no nav, wrong viewport unit, safe-area strip). This spec
is the next pass: the defects that make the phone usable but not *impeccable*,
the gap between "works on a phone" and "feels like Apple made it."

A `/impeccable audit` ran nine specialist passes over the dashboard source
(iOS runtime/viewport, form/input zoom, z-index/stacking, touch/gesture,
two per-page UX passes, motion/performance, Apple HIG conformance, a targeted
bug hunt) and returned 117 raw findings. Every finding below was re-verified
against the actual source before being trusted; several were independently
rediscovered by two to five separate passes without being told about each
other; that kind of convergence is itself a severity signal, not noise.

**Scorecard (osUI audit gates, before this pass):**

| Gate | Before | After Phase 1 |
|---|---|---|
| Every toast/undo reachable and visible on the phone | **No** (rendered under the opaque tab bar) | Yes |
| Inbox page opens without crashing | **No** (`ReferenceError`, white screen) | Yes |
| Focusing a text field never zooms the page | **No** (~30 controls under 16px) | Yes |
| One coherent z-index scale | **No** (4 tokens + 6 magic numbers, two unrelated layers both `40`) | Yes |
| Committed modes (call, journal) dim *all* chrome including the portaled tab bar | **No** | Yes |
| A background call survives a 90s relock | **No** (run silently discarded) | Yes |

---

## 1. Design law additions (binding, extends osUI L1-L9)

**L10. Every focusable text control ships at 16px+ on the phone.** iOS zooms
the entire layout on focusing any control under 16px, and this app's shell is
a fixed single viewport with no code to un-zoom afterward. `input, textarea,
select` default to `var(--t-md)` (16px) below the 901px breakpoint; recover
visual density with padding, never with font-size. This was already known and
half-applied (`.goal-target-input`'s own comment: `/* < 16px makes iOS zoom
the page */`); L10 makes it the rule instead of a spot fix.

**L11. One semantic z-index scale, nothing invents its own number.**

```
--z-bg: 0        aurora canvas
--z-grain: 1     film-grain overlay
--z-shell: 2     .app-shell, .boot, .lock-screen
--z-nav: 30      the portaled mobile tab bar
--z-sheet: 40    bottom sheets (plan create/edit, goal wizard, More)
--z-modal: 60    full-screen dialogs (More sheet backdrop)
--z-palette: 70  command palette
--z-toast: 80    toasts, the Line's undo pill
--z-lock: 90     the lock screen (already highest by mount order; token exists for clarity)
```

Local integers scoped inside their own stacking context (`.plan-block` 3 vs
`.plan-now` 4, `.nav-glow` -1, `.ord-atmosphere` 0/1 under `isolation:
isolate`) are unaffected: they never resolve against the root scale and stay
as-is.

**L12. `color-scheme: dark` is declared once, globally.** Every native
control this app cannot restyle itself (keyboard, date/time picker wheel,
`<select>` popover, file-picker sheet) should match the near-black app instead
of flashing light-mode chrome over it.

**L13. Every tap gets a pressed state, and no tap gets a stuck one.**
`-webkit-tap-highlight-color: transparent` globally (haptics don't exist in a
PWA; a real `:active` scale/opacity is the substitute Apple ships). Any
`:hover` rule that shares a declaration with a real toggled state (open/on) is
gated behind `@media (hover: hover)`, because iOS's synthetic hover sticks
after a tap and a shared rule reads as "still selected."

**L14. A fixed or portaled element is never trapped by a transformed
ancestor's stacking context, and a committed mode's dim reaches every layer of
chrome, including anything portaled to `document.body`.** (`Nav.jsx` already
documents the containing-block hazard for exactly this reason; L14 makes sure
the fix doesn't reintroduce a second, invisible failure mode.)

**L15. A timer or listener an effect starts, that same effect tears down.**
A relock/unlock cycle is routine (every ≥90s backgrounded, SPEC-v12), not an
edge case; an effect that re-arms global listeners on every cycle without
removing the old ones will leak for the entire life of the tab.

---

## 2. The defect ledger

Findings are deduped from the raw audit (several of these were reported by
3-5 independent passes; that count is noted where relevant). P0/P1 are all
fixed in Phase 1. The P2 column marks what Phase 1 also picked up because it
was cheap and high-value; unmarked P2/P3 items are Phase 2/3 backlog, §4.

### P0: broken on the only device that matters

| # | Defect | Where | Fix |
|---|---|---|---|
| P0.1 | `MemoFeed` reads `ROLE_COLORS[m.from_role]` but `App.jsx` never imports `ROLE_COLORS` (only `roleColor`/`roleGlyph`). Any memo throws a `ReferenceError`; with no error boundary, React unmounts the tree. Inbox (the only place proposals are approved) white-screens the instant a memo exists, i.e. always, after any seed or nightly run. *(independently found 3x)* | `App.jsx:259` | The `.role-dot` it colors is a redundant zero-value pixel, `RoleTag` two elements over already renders a colored glyph. Deleted the dot instead of patching the color source. |
| P0.2 | Toasts and the Line's undo pill render at `bottom: 24-28px, z-index: 20`. The mobile tab bar is `bottom: 0, z-index: 40`, ~86px tall, 97%-opaque. Every toast and the app's only undo affordance (soft-delete-instead-of-confirm is the stated pattern) is fully hidden behind the bar on the phone. *(independently found 5x across both audit passes)* | `styles.css` `.toasts` / `.line-undo` | Mobile override lifts both above `var(--nav-h) + env(safe-area-inset-bottom)` and raises them onto the new `--z-toast: 80` token (L11). |

### P1: degrades daily use or breaks an iOS platform expectation

| # | Defect | Where | Fix |
|---|---|---|---|
| P1.1 | Global `input, textarea` font-size is 13px (`--t-sm`); ~30 controls app-wide inherit it and zoom on focus (proposal note, quick-log note/sleep, Partner add/edit, Memory topic/body/date, Notes search, Plan time pickers, lead search/filters...). | `styles.css:1495` | L10: base rule → 16px below 901px; desktop keeps 13px via `min-width: 901px`. |
| P1.2 | `.line-note` (the call-notes textarea) sets its own 14px, independent of the global rule, so it zooms **mid live call**, right as the script and End-call button are on screen. | `styles.css:3401` | 16px. |
| P1.3 | `select` is excluded from the forms rule entirely: unstyled UA font/height in GoalForm, GoalWizard, MemoryPage; separately `.lead-search`/`.lead-list-filters select` declare their own sub-16px sizes that survive any base-rule fix. | `styles.css` forms block + `.lead-search`/`.lead-list-filters select` | `select` joins the base rule; explicit sub-16px overrides removed. |
| P1.4 | Log page's wellness inputs reset from `wellnessToday` on every 15s poll because the effect depends on the *object*, which is a fresh reference every fetch even when nothing changed. A half-typed sleep-hours entry or an energy tap can be silently erased mid-type. | `App.jsx` `LogPage` | Depend on the primitive fields (`wellnessToday?.sleep_hours`, `?.energy`, `?.workout`), the pattern `PartnerPage` already uses correctly. |
| P1.5 | Plan's create/edit sheet autofocuses its title input the instant it opens; the sheet is bottom-anchored and nothing in the app listens to `visualViewport`, so the iOS keyboard can cover Start/End, the duration chips, and Add/Cancel with no way to see them without dismissing the keyboard first. | `PlanPage.jsx:360` | `visualViewport` resize listener while the sheet is open, translates the sheet clear of the keyboard. |
| P1.6 | No coherent z-index scale: 4 tokens stop at 20, then six magic numbers (12/40/45/50/1000) layer on top, two of them both named `40` for unrelated things, and the plan sheet's declared `40` is actually trapped inside `.app-shell`'s stacking context and resolves at root `2`, *under* the portaled tab bar. Toasts, the More sheet, and the command palette all under/overlap each other unpredictably. | `styles.css` throughout | L11's semantic scale applied everywhere; the plan sheet portaled to `document.body` (the `Nav.jsx` precedent) so its z-index is no longer trapped. |
| P1.7 | `.plan-ribbon`'s height uses bare `100dvh` in two places, the exact bug class the file's own header comment says never to reintroduce (`100dvh` under-reports by the Dynamic Island inset in standalone; that's why `--app-height` exists). | `styles.css:2788,2879` | Routed through `var(--app-height, 100dvh)` like every other height in the file. |
| P1.8 | The 90s background-relock timer (routine: any answered call over 90s backgrounds the PWA) unmounts the whole shell mid-call-run. The Line's queue, index, phase, elapsed timer, and typed note all live in component state and vanish; the server-side run is never closed. | `lib/lock.js` + `TheLine.jsx` | A run snapshot (run id, target, lead ids, index, phase, note) persists to `sessionStorage` on each transition; `TheLine` offers "Resume run N of M" after unlock. `sessionStorage` survives relock by design (only the two lock keys are cleared). |
| P1.9 | `TheLine`'s `callMode` flag has no unmount cleanup and `App.jsx` never resets it on navigation (unlike `journalComposing`, which it does reset). A stray tap away from BtC mid-call leaves the whole app dimmed at 0.22 and re-laid-out until BtC happens to remount, and the run is abandoned server-side. | `TheLine.jsx:77` | Effect cleanup sets `callMode` false on unmount; `App.jsx`'s page-change effect also clears it for any page that isn't `btc`/`goals`, mirroring the existing `journalComposing` reset. |
| P1.10 | A run that exhausts the queue *before* hitting its target jumps to the summary phase with `summary` still `null`, so it prints "no calls." and 0/0 after real dials, and the run is never closed server-side (a second "Run again" opens a second concurrent run). | `TheLine.jsx:144` | Mirrors the target-reached branch: end the run, capture the real summary, then show it. |
| P1.11 | Committed-mode dimming (`call-mode`, `journal-mode`) only targets `.nav-wrap`, but the mobile tab bar is intentionally portaled to `document.body` (a real Safari containing-block fix) and sits entirely outside that selector. The one dimming scale the product law calls for doesn't reach the brightest chrome on screen during a cold call or the journal ritual. | `styles.css` dim rules + `Nav.jsx` | `App.jsx` mirrors `callMode`/`journalComposing` onto `document.body` as classes; the dim rules gain a matching `body.call-mode .nav-mobile` / `body.journal-mode .nav-mobile` pair. |
| P1.12 | No `color-scheme` is declared app-wide (only on `input[type=date]`), so the system keyboard, time-wheel picker, and `select` popover render in light appearance over a near-black app; sharpest on the Journal's dim wind-down ritual. | `styles.css` | L12: `color-scheme: dark` in `:root` + `<meta name="color-scheme" content="dark">`; the now-redundant per-input rule removed. |
| P1.13 | Partner's checkbox (26px) and delete (28px) are the highest-frequency taps on that pillar and sit well under the 44px law with no hit-area inflation, despite the app already having that exact pattern elsewhere. | `styles.css:1723,1789` | Invisible `::after` 44px hit area, the established `.focus-signal`/`.goal-target-btn` recipe. |
| P1.14 | Plan blocks under ~44 minutes render shorter than 44px, and the bottom 16px resize grip eats most of what's left, so a long-press meant to move a short block frequently resolves as a resize instead. | `PlanPage.jsx` `GRAB_EDGE` | Grab edge scales with block height (`min(16, height/3)`), guaranteeing at least two-thirds of any block stays move-only. |
| P1.15 | The goal-row swipe reveal applies horizontal drag from the very first touch-move event with no axis judgment (unlike `lib/swipe.js`, which deliberately waits for 12px and picks whichever axis dominates), and its listener is passive with no `user-select: none`, so an ordinary vertical scroll of the goal list can drag a row sideways or hand the gesture to iOS's text-selection loupe. | `PillarGoalPanel.jsx` `SwipeRow` | Same 12px-then-dominant-axis judgment as `lib/swipe.js`; `-webkit-user-select: none` on `.swipe-face`. |
| P1.16 | `AuroraBackground`'s canvas (plus the `mix-blend-mode: overlay` grain layer stacked on it) runs its `requestAnimationFrame` loop unconditionally, including while the lock screen is showing, with no `visibilitychange` pause, on a PWA opened ~20x/day. | `AuroraBackground.jsx` | Loop pauses on `document.hidden`, resumes on visible. |
| P1.17 | `startAutoFlush`'s `online`/`visibilitychange` listeners are never removed; the effect that calls it re-arms on every unlock (routine, every relock cycle), so listeners accumulate for the life of the tab and later reconnect events fire N concurrent `flush()` calls, producing duplicate "synced" toasts and duplicate writes. *(the write duplication is harmless only because writes are day-stamped idempotent; the client-side leak is still a real bug)* | `lib/offline.js:96` + `App.jsx:595` | `startAutoFlush` returns a real teardown; the `App.jsx` effect calls it alongside the existing `unsub`. |
| P1.18 | `PartnerPage` ships a private `api()` copy that bypasses `lib/api.js` entirely, so it has neither the `GATEWAY_DOWN` handling (the Mac-asleep-behind-Tailscale case) nor `{queueable: true}`. Partner is a permanently pinned tab: toggling a task while the Mac sleeps surfaces a raw `502` instead of "saved, syncs when your Mac wakes." | `PartnerPage.jsx:14` | Local copy deleted; imports the shared `api` from `lib/api.js`, `queueable: true` on the task writes. |

### P2 (curated slice implemented in Phase 1: cheap, mechanical, high visual return)

- **Plan/Line design-law leaks:** Plan's Delete button and all four of Plan's
  error toasts used `--crit` red on a surface that explicitly bans it (the
  file's own header comment says so); switched Delete to the ghost/grey
  "retiring, not failing" treatment the goal-archive swipe already uses, and
  toasts to `warn`, matching The Line's own convention for the identical
  failure.
- **Tab bar tint inverted from the HIG contract:** all five icons were
  accent-tinted at all times, with selection marked only by a faint glow;
  swapped to muted-by-default / accent-on-active, the standard iOS contract.
- **No pressed feedback, stuck hover (L13):** `-webkit-tap-highlight-color:
  transparent` added globally; real `:active` states added to the highest-
  traffic controls that had none; the worst stuck-hover offenders
  (`.note-toggle`, `.plan-block`) gated behind `@media (hover: hover)`.
- **44px hit-area law applied to the rest of the under-sized dense controls**
  it had missed: `.memo-filter-btn`, `.fact-delete`/`.fact-btn`, `.plan-arrow`,
  `.plan-today-btn`, `.plan-dur-btn`, `.plan-suggest-chip`, `.edit-glyph`,
  `.toast-undo`, `.ord-chip`/`.ord-link`, `.nudge-dismiss`.
- **Duplicate "Nd to client" pixel:** printed twice on Command (a header pill
  and a signal chip); header pill hidden on mobile, the tappable rank-sorted
  chip keeps the number (L3).
- **Backdrop-filter stacking over the ≤2 cap:** per-row `glass-card` blur on
  every Partner task and every Memory fact meant 3+ concurrent blur regions on
  ordinary scrolling of two permanent tabs; rows go flat, page-level glass
  stays on one container.
- **`rosterMap` rebuilt every render** defeated `CommandPage`'s own
  content-equality memo guard (`prev.roster === next.roster` was comparing two
  always-different objects), forcing a full re-render and a redundant
  `/api/day` fetch on every 15s poll; wrapped in `useMemo`.
- **`InlineTarget`'s local edit buffer never resynced** with the goal's
  server value once mounted, so an external update (an approved proposal
  changing the same target) could be silently reverted on the next unrelated
  edit; now resyncs whenever not actively editing.
- **Journal composer's post-close `setTimeout` had no unmount cleanup**;
  navigating away during the ~2s close ritual let a stale closure fire
  `onClosed`/state-setters against an unmounted tree. Cleared on unmount.
- **Mobile nav badge never carried `urgent`** outside the desktop rail (the
  mobile bar and More sheet render the raw link object, which never has the
  field merged in), so the Inbox badge could never actually turn red on the
  one navigation surface that matters. Threaded through.

### Backlog: Phase 2/3 (documented, not implemented this pass)

Real, worth doing, deliberately deferred because each is either a bigger
architectural lift (a true bottom-sheet primitive with drag-to-dismiss, a
custom SVG icon set replacing the mixed-fallback unicode glyphs, history-based
push/pop for Journal's day drill-down so iOS edge-swipe-back behaves) or lower
daily-use impact than the above (Dynamic Type support, self-hosted fonts,
`apple-touch-startup-image`, a service-worker update-ready prompt, pull-to-
refresh on feeds, a segmented-control sliding thumb). Tracked findings, for
whoever picks this up next:

1. **A real bottom-sheet primitive.** The More sheet, Plan's create/edit
   sheet, and the goal wizard are each their own one-off centered/bottom
   `position: fixed` panel with no shared motion, no grabber, no
   swipe-to-dismiss. Worth one shared component (slide up from `y: '100%'`,
   grabber hairline, drag-down dismiss over ~80px or by velocity) instead of
   three bespoke ones.
2. **Custom icon set.** The tab bar and More sheet draw from Unicode
   dingbats (`◈ ▤ ◆ ♥ ⋯ △ ○ ⬡ ❋ ≡ ☾`) that Space Grotesk doesn't contain, so
   iOS pulls each glyph from a different fallback font with mismatched stroke
   weight and baseline. A ~1KB inline-SVG set (`currentColor`, 1.5px stroke)
   would read as intentional instead of clip-art next to an SF-Symbol bar.
3. **Journal day-detail as real navigation.** Opening a day is a state swap,
   not a history push, so iOS's edge-swipe-back (which the pillar-swipe
   gesture deliberately reserves 24px for) pops the *previous hash page*
   instead of closing the day, and scroll position is lost.
4. **Pull-to-refresh** on the memo feed, inbox, and queue: muscle memory on
   iOS feed surfaces, currently the bounce exists (`overscroll-behavior-y:
   contain` already lets it rubber-band) but does nothing.
5. **Dynamic Type / self-hosted fonts.** All type is fixed px, so iOS's
   Larger Text accessibility setting changes nothing; separately, two
   `@fontsource` packages are installed and unused while the app depends on a
   render-blocking Google Fonts CDN call for the fonts it actually renders.
6. **Cold-open flash + service-worker update prompt.** No inline background
   on `<html>` before the stylesheet loads (a white flash into `#04050a` on a
   slow/cold PWA launch, one CSS line to fix); no `controllerchange` listener,
   so a long-foregrounded session never learns a new deploy is ready.
7. **Command palette has no mobile entry point today outside this pass's fix**
   (see Phase 1 note below); a full palette redesign for touch (bottom-anchored,
   keyboard-safe) is still backlog-worthy beyond the minimal fix shipped.
8. **Segmented controls** (workout picker, memo filter, journal day/photos
   toggle) teleport a background fill between states instead of animating a
   sliding thumb the way iOS's native control does.
9. **Facts list has no windowing** unlike the equivalent Leads list, which
   already paginates at 25/page for the identical unbounded-growth risk; the
   archivist writes new facts weekly forever.
10. **Landscape safe-area on the tab bar.** Only the bottom edge reads
    `env(safe-area-inset-bottom)`; rotating in a Safari tab (the manifest's
    portrait lock only binds the installed PWA) puts the leftmost/rightmost
    tab icons under the rounded-corner cutout with no inset protection.

---

## 3. Implementation notes (Phase 1)

- **`Nav.jsx` gained a small mobile fix beyond the ledger above:** the
  desktop-only Cmd+K chip is invisible on the phone (`.nav-desktop` is
  `display: none` under 901px), so the product's own "Cmd+K to jump anywhere"
  promise was dead code on the target device. A "Jump" row was added to the
  top of the More sheet, wired to the same `onOpenPalette` prop the desktop
  chip already receives. This is the minimal fix; the full touch-redesign of
  the palette itself (bottom-anchored, keyboard-aware) is backlog item 7.
- Every fix here is additive inside the existing `@media (max-width: 900px)`
  block or a targeted selector; nothing changes desktop layout except where a
  bug (the z-index trap, the memo guard) was equally wrong there.
- No change here touches an agent, a guardrail, a table, or a metric. The
  `--crit`/no-streak/no-percentage product law is honored throughout; the
  z-index and touch-target fixes are pure CSS/architecture, not new UI
  surfaces.

## 4. Verification

Per `osui`'s checklist: `npm run build`, bust the service-worker cache (a
stale asset from cache-first fetch has produced two wrong conclusions in this
repo before), verify at 375×667 *and* 402×874 (667 is the real fold
constraint, 874 is the target device), simulate 47px/34px safe-area insets,
confirm `prefers-reduced-motion` disables the newly-added `visibilitychange`-
gated aurora loop cleanly, and re-run `tests/test_mobile_ui.py` /
`tests/test_lock_screen.py` / `tests/test_leads.py` (the last one specifically
guards the "heat is earned by dialing, not outcome" law this pass never
touches, but Plan/Line CSS changes are exactly the kind of change that could
regress it by accident).

## Related

- [SPEC-v10-osui.md](SPEC-v10-osui.md): the binding mobile design law this spec extends
- [SPEC-v9-the-line.md](SPEC-v9-the-line.md): call-run state machine (P1.8-P1.10 touch it)
- [SPEC-v7-plan.md](SPEC-v7-plan.md): day-plan derivations (P1.5, P1.7, P1.14 touch it)
- [SPEC-v12-lock-screen.md](SPEC-v12-lock-screen.md): relock timing (P1.8, P1.17 touch it)
