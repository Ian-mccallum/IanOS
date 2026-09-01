---
name: osui
description: ianOS interface work: the binding design law for this app's UI. Use whenever building, changing, reviewing or debugging anything the user sees in dashboard/, pages, components, styles, navigation, motion, mobile/PWA layout, empty states, or UX copy. Also use before adding a new page or surface. Not for backend, agent, ingest or data-layer work that has no visible surface.
---

# osUI, the interface law of ianOS

ianOS is a phone app that also opens on a laptop. It was built the other way
round, and every defect in `docs/SPEC-v10-osui.md` traces to that.

**Read `docs/SPEC-v10-osui.md` before making a judgment call this file doesn't
cover.** This is the working checklist; the spec is the reasoning.

## Who this is for

One user: Ian, founder, incoming UIUC. He opens this
twenty times a day, usually on a phone, usually with one thumb, often between
other things. Design for **low activation energy and no shame**, never for
feature count, and never for a stranger evaluating the product.

## The nine laws

**L1. Mobile is the design target, desktop is the enhancement.**
Author every component at 375px first. Never lay out for desktop and patch it
with a `@media (max-width:)` override. That inversion is what produced every
bug below.

**L2. One screen, one job.** A phone screen answers exactly one question. A
second question is a second screen or a disclosure, never a second column.

**L3. Zero-value pixels are a bug.** A subtitle restating the page title, a
metric reading `0`, a chip duplicating a row below, an empty state that
apologises at length. **Delete them, do not shrink them.** If it isn't
actionable or alarming, it doesn't belong on the phone.

**L4. Nothing that matters lives below the fold.** The most important element
must be fully visible at **375×667** without scrolling. Measure it; don't eyeball
it. On Command that means the Day Command sentence, then the next action.

**L5. Thumb zone is law.** Primary actions in the bottom third. Every target
≥44×44 CSS px. Destructive actions never adjacent to frequent ones.
*Inline chips keep their visual size and gain an invisible 44px hit area via
`::after`, never inflate a dense row to hit the minimum.*

**L6. Safari is the reference browser, not Chrome.**

**L7. Motion explains, or motion goes.** Animation must communicate causality:
where a thing came from, what it became. A swipe-in slides from the side the
thumb travelled. Budget: 200ms state, 320ms surface change. Everything respects
`prefers-reduced-motion`.

**L8. Futuristic means restraint.** Deep near-black, one accent, hairline
borders, generous negative space, mono for numbers. Glow is a highlight, not a
texture. When in doubt, remove.

**L9. The installed app is a different runtime, and it is the real one.**
Standalone reports real `env(safe-area-inset-*)` where a browser tab reports 0.
A whole class of defect is invisible in the browser and obvious on the home
screen. Verify with simulated insets (47px top / 34px bottom) before calling it
done.

## Inherited product law (do not weaken)

These predate v10 and outrank any visual preference:

- **`--crit` red is banned** in Plan, Journal, The Line, the **lock screen**,
  and **Fury chat**.
  A past unfinished block *softens*; it never reddens.
- **No percentage, no breakable streak, no lifetime counter** anywhere a number
  could read as a verdict on Ian. The gym streak bends instead of resetting.
- **The journal is private from agents, reachable on the phone.** `/api/journal`
  uses the same LAN token as the rest of the API (SPEC-v11). Bodies/media never
  appear in `/api/state` or agent tools, only an explicit Share sends text.
- **Lock screen (SPEC-v12)** gates the UI before state loads. Face ID needs
  HTTPS (Tailscale). Password `ianos` always works. Not a substitute for
  the LAN token. See `docs/SPEC-v12-lock-screen.md` and `docs/PHONE.md`.
- **Heat is earned by dialing, never by outcome** in The Line.
- **Agent personality is seasoning, not content.** If voice fights clarity,
  clarity wins.

## Traps that have actually shipped here

Each of these passed review, passed the build, and looked perfect on a laptop.

| Trap | What happens | Rule |
|---|---|---|
| `.nav-mobile { display: none }` after the breakpoint block | Equal specificity, later rule wins → **the phone had no navigation at all** | The mobile bar may only be hidden by a `min-width` query |
| `height: 100vh` | Safari's `vh` excludes the URL bar → the bottom sits under the toolbar | `100dvh`, with `vh` first as fallback |
| `padding: a b c` on a full-bleed container | Silently drops all four safe-area insets; invisible in a tab, **renders under the notch when installed** | Any padding on `.app-main`/`.app-shell` carries `env(safe-area-inset-*)` |
| Hard-coded bar height in two places | 56px reserved for a 65px bar, plus 16px elsewhere → dead space | One token (`--nav-h`), reserved by the shell, occupied by the bar |
| `.command-rail { order: -1 }` on narrow | Hoists the action list above the hero → **Day Command at y=1012 on a 667px screen** | Hero first. Measure the fold |
| `{row.pinned && <Pin/>}` with SQLite data | `0 && x` is `0`, which React renders as a literal character → titles read `0Dorm packing list` | Coerce with `!!` at every boolean-ish column |
| Clearing animation state in `onAnimationComplete` | Re-renders mid-flight and strands the element at `initial` | Hold one-shot animation direction in a **ref**, not state |
| Passive `touchmove` while dragging | Can't `preventDefault`, so the scroller moves under the drag | Attach non-passive; gate the drag behind a long press |
| A fixed-width column inside a narrow row | `minmax(100px, var(--meter-w))` took 220px of a 261px row, leaving **25px for the goal title**, which wrapped one word per line | On a phone, stack. Never give a decoration a fixed column ahead of the text that names the thing |
| A second horizontal gesture on the same pixel | A row swipe and the pillar swipe both fire: the row opens *and* the pillar changes | The inner element claims it (`data-swipe-own`); the ring skips touches starting there |
| A hard `DELETE` behind a swipe | A swipe is one thumb-slip from a tap, and there is nothing to undo | Soft-flag it (`archived`), filter in the single read path, Undo restores the **same row**, ids are referenced elsewhere |
| `:not([tabindex="-1"])` written as its own catch-all clause in a focus-trap selector | `button:not([disabled])` alone still matches a `tabIndex={-1}` button, tabindex isn't disqualifying for that branch on its own → Tab silently escapes a dialog meant to trap it | Combine `:not([tabindex="-1"])` onto **every** branch, not just a generic `[tabindex]` fallback |
| A visual state fix (icon tint, focus ring, contrast) applied to one input surface's selector | Ships fixed on mobile (`.nav-mobile`) and stays broken on desktop (the nav-rail), or vice versa; each looked complete in isolation | When a state-carrying bug is fixed on one surface, check the equivalent selector on the other before calling it done |
| `max-height: calc(100dvh - <literal>)` to leave room for chrome | The literal is a guess at a height that changes when any row is added or hidden. Measured, one such panel ran **5px under the tab bar** | Make the panel the flex child of a flex-column page so no number exists to be wrong |
| Turning a page into `display:flex; flex-direction:column` | Every child becomes shrinkable: a chip row collapsed to **9px around its own 18px chips** and sliced them in half | Pair it with `> *:not(.the-scroller) { flex: 0 0 auto }` in the same edit |
| A column header at `top: 0` inside the scrolling canvas | Scrolls away with the content, so the thing it labels becomes unlabelled one gesture in | Headers are a fixed row above the scroller, mirroring its padding and gap so they stay aligned |
| Offsetting overlapping cards without raising their opacity | At a low alpha every card's text shows through every other, which is *less* legible than the even split it replaced | A cascade must occlude: composite the tint over an opaque base |
| Adding a control to the shared 44px `::after` hit-area rule | That rule also sets `position: relative`, which silently kills a `position: sticky` element, decided purely by rule order | Sticky/absolute elements take the `::after` but must stay out of the `position: relative` list |

## Verifying UI work (in this order)

1. `cd dashboard && npm run build`
2. **Bust the cache.** The service worker serves assets cache-first, so an open
   tab keeps running old JS/CSS after a rebuild. Navigate with a fresh
   `?nocache=<something>`, or unregister the worker and clear caches. *Two wrong
   conclusions in this repo came from measuring stale assets.*
3. Set the viewport to **375×667** (not just 812. 667 is the real constraint).
4. Measure, don't eyeball: element rects against the tab bar's top edge.
5. Simulate the notch: mirror the same `calc()` with 47px/34px and confirm
   nothing hides under it.
6. **Screenshot before reading computed style.** The preview pane reports
   `visibilityState: hidden`, which pauses `requestAnimationFrame`: opacity
   reads `0` forever and looks exactly like a broken animation.
7. `make test`: `tests/test_mobile_ui.py` holds the gates as executable rules.

**Check the code before believing a spec.** Two items in SPEC-v10 were deferred
on reasons that did not survive contact: one misquoted L1 (desktop *is* the
enhancement, so a `min-width` two-pane is allowed), and one described a "cramped
modal" that had never existed. A spec is a record of intent, not of the
codebase. Read the source before accepting a premise from prose, including
prose written here.

## Gates (all must hold at 375px)

1. Tab bar visible; every tab reaches its page.
2. No horizontal scroll at 320 / 375 / 390 / 430.
3. Primary action within the bottom third.
4. Nothing important below the fold at 375×**667**.
5. No `100vh` without a `dvh` companion.
6. One viewport-height shell; `.page-content` is the single scroller with
   `overscroll-behavior-y: contain`.
7. Every fixed edge respects the safe-area insets, and no later rule drops them.
8. All targets ≥44×44 (hit area may exceed the visual box).
9. ≤2 stacked `backdrop-filter` layers (Safari compositing cost).
10. `prefers-reduced-motion` disables non-essential motion.
11. No zero badges; no title restating a lit tab.
12. Inherited product law above intact.

## When adding a surface

- Does an existing page answer this question? Prefer disclosure over a new page.
- Does it earn a tab? There are five slots: Command, Plan, BtC, Partner, More.
  Everything else lives in the More sheet, pillars as a grid, system pages as
  a list.
- Add it to `PAGES` in `App.jsx`, and to `ALL_LINKS` + `ALL_MOBILE_MORE` in
  `components/Nav.jsx`. A page not in the tab bar **keeps its title**; a page
  with a lit tab does not. `#chat` (Fury, SPEC-v25) is behind More on purpose.
  Do not make it a sixth tab. Chat questions are never `queueable`.
- New writes that a phone might make offline go through `lib/offline.js`
  (`queueable`), and must be day-stamped so a 2pm tap syncing at 6pm still
  counts for today. Chat turns, Ask, and rooms are live-only.

## Copy

Numbers first, verdict, next action. Blunt, never chirpy, never scolding.
An empty state says what to do in one line; it does not apologise.
Prefer "you took 2 of 4" over "50% approval".

**Anti-slop (binding):**
- No em dashes (—) or en dashes used as punctuation. Use commas, colons,
  semicolons, periods, or parentheses. Empty/missing values use ASCII `-`.
- No marketing buzzwords (seamless, leverage, unlock, world-class, etc.).
- No aphoristic cadence as default voice (serious line, then punchy negation,
  repeated). Specific nouns and verbs only.
- Prefer "Journal works on your phone with the LAN token" over soft hedging.
