# SPEC v29: the design system

Status: **decided, implementation starting**. Extends SPEC-v28 (the audit and
its six-phase plan) with the actual shape of the fix. v28 said what was
broken; this spec says what it becomes. Born from a judge-panel workflow: 3
independently-lensed proposals ("Bridge & Rail," "Substrate," "Bridge, Not
Booth"), scored and synthesized by a fourth agent that re-verified every
citation against source rather than trusting the proposals, catching a
self-undermining citation in one, a false accessibility claim in a second,
and a structural flaw in the third (its routed `ChatPage.jsx` would still
unmount on tab switch, the exact bug it claimed to fix). Winner: **Bridge &
Rail**, with grafts pulled from the other two. This document is my own
synthesis on top of that judging, re-verified again against source before
writing it down, not a pass-through of the workflow's output.

## Decided, not open

Three things Ian settled this round, binding for everything below:

1. **Command reverts to the old grid, verbatim.** "The only thing I truly
   like are the command screen for web, and the colors" followed by "I don't
   like the new command, the old version was so much better." Resolved: the
   pre-SPEC-v26 two-column grid (Order hero + persistent ActionStack/
   PillarStrip rail) is the liked thing; SPEC-v26/v27's chat-takeover
   version is not. Chat demotes to a secondary, reachable-but-never-forced
   surface.
2. **Chat gets instant write access to six safe domains only**: goals, plan
   blocks, notes, facts, gym confirm (not grace/reset), Partner tasks. Instant,
   undoable, no approval tap. Money and The Line are untouched: read, advise,
   file a proposal Ian approves, exactly as today. This was an explicit
   AskUserQuestion answer ("Safe domains only, instant"), not a default I
   picked. Do not widen it without asking again.
3. **The LLC goal is archived, not deleted.** Done already, via
   `POST /api/goals/6/archive`, confirmed `archived=1`, fully restorable via
   `?restore=true`. Nothing further needed here.

The palette (`--accent`, the agent color map in `lib/agents.js`, `--good/
--warn/--crit`) is frozen. No proposal found or needed a defect there, and
none of what follows touches it.

## Architecture decision: chat is shell chrome, not a page

This is the one call that shapes everything else, so it goes first and gets
argued, not just stated.

SPEC-v28's root cause for "leaves Command, comes back to Fury" was page
lifecycle: `AgentChat` mounts inside `CommandPage`, and `CommandPage` only
renders while `page === 'home'`. Leave Command, the component unmounts,
thread/draft/scroll/running-turn all die with it. The naive fix, give chat
its own routed page, does not fix this: a `ChatPage.jsx` reachable via
`page === 'chat'` in the same hash-conditional scheme every other page uses
would unmount on the exact same schedule, just relocated. One of the three
brainstormed directions proposed exactly that and the judge caught it:
"claims to resolve the amnesia root cause 'for free'... but ChatPage.jsx
would only render while `page === 'chat'`... so navigating to Money and back
still unmounts/remounts it." Verified against `App.jsx`'s `PAGES` array and
hash-routing: every page, hypothetical or real, shares this lifecycle.

The only fix that actually kills the bug is not mounting chat as a page at
all: **mount `<AgentChat>` once at the app-shell level in `App.jsx`**,
sibling to `<Nav>` and the toast stack, never inside a page component. This
is SPEC-v28 Phase 2's own proposed fix ("mount AgentChat once at the app
shell... like nav and toasts," `docs/SPEC-v28-transformation.md:103-104`),
now the actual placement decision rather than a fallback option. Thread,
draft, scroll position, and a running turn survive every tab switch because
there is nothing to unmount, structurally, not by convention.

Consequence: `#chat` retires as a concept entirely, not just as a route.
It's already dead (`App.jsx` folds any `#chat` hash straight to `#home`,
there's no `ChatPage.jsx`, `PAGES` has no `'chat'` entry). This proposal
finishes that thought: chat becomes pure UI chrome with no hash and no page,
so there is nothing left behind on tab switch to begin with. It never
becomes a sixth tab, the five-tab law (Command, Plan, BtC, Partner, More)
holds unchanged.

## Phase 0: stop the bleeding (unchanged from v28, ship first)

Still the fastest, highest-value slice, do this before anything else below:

- Define the real max-height chain (see Phase 4's token pair) so
  `.ask-agent-sheet`'s `max-height: min(720px, calc(var(--app-height) -
  var(--s8)))` (`styles.css:3058`) stops resolving to `none`. Confirmed live:
  `--s1` through `--s7` (48px) are the entire spacing scale
  (`styles.css:53-59`), `--s8` does not exist.
- Fix the `.chat-file-sheet` / `.chat-file-dialog` rename mismatch: JSX
  renders `chat-file-sheet` (`AgentChat.jsx:191,214,261`, confirmed), the
  real layout rule (width/max-height/padding) still targets the orphaned
  `.chat-file-dialog` (`styles.css:4794-4807`, confirmed). Superseded by
  Phase 3's Sheet migration rather than patched standalone, since these
  three overlays are getting rebuilt on the primitive anyway.
- Agent amnesia: superseded by the shell-mount architecture above, not a
  separate patch.
- Un-crit the $0 credit card (`--crit` only when balance > 0).
- Raise `.ac-source-state` / `.ac-agent-meta` contrast above 4.5:1 on glass
  (currently 4.43, borderline).

## Phase 1: Command reverts to the grid

`CommandPage.jsx`'s return block becomes byte-identical to
`CommandPage.jsx.old-reference:135-241`. Verified: the two files diverge
**only** in the return JSX, lines 1-134 (state, greeting/stamp helpers,
`runBrief`/`confirmGym`/`bumpActivity`/`runPrimary`, the shutdown-nudge and
once-per-day reveal effects) are already byte-identical. This is a revert,
not a rebuild.

Concretely:

- `.command-grid` = `.command-hero.command-orders` (Order label, day/mon/CT
  stamp, the Day Command sentence, a full-width `.ord-go` primary button,
  `.ord-foot` with Brief/Re-run text links) beside a permanent
  `.command-rail` holding `<ActionStack>` + `<PillarStrip>`, both
  **unconditionally visible**. The CSS is confirmed still live and
  unreferenced since SPEC-v26 switched to `.cmd-pin`: `.command-grid`
  (`styles.css:2524-2537`), `.command-hero`/`.command-orders`
  (`2542-2567`), the `.ord-*` family (`2594-2764`), `.command-rail`
  (`2770`), the SPEC-v14 desktop rail-widening (`2530-2537`).
- Delete the `<details className="cmd-today">` disclosure
  (`CommandPage.jsx:201-214`) outright, don't restyle it, remove it.
  ActionStack + PillarStrip return to always-on, which is the literal fix
  for "the old version was so much better": the thing Ian actually
  complained about losing was permanent visibility, not a specific pixel
  layout.
- Remove `<AgentChat>`'s inline mount (`CommandPage.jsx:199`) from the page
  body entirely. It moves to the shell (above).
- Restore the old file's `ord-foot` "Ask Fury" link
  (`old-reference:203-205`) as the one dedicated chat entry point from
  Command, generalized to "Ask an agent" and repointed from
  `navigate('chat')` (which resolves to nothing today) to opening the
  shell-mounted instance.
- Keep the current file's two real, additive improvements the old one
  lacked: the `attentionFresh`/"last synced" staleness badge, and the
  shutdown nudge. These are additive, not structural, no reason to lose
  them in the revert.

## Phase 2: chat as shell-mounted chrome

- **Desktop (≥901px)**: a slim edge-toggle opens a docked rail, capped at
  **380-420px**, sliding in as an overlay over the page's own content rather
  than reflowing it. Keep this cap tight. One of the three directions
  proposed the same mechanism at roughly `--content-w` (~920px); on a real
  laptop that's wide enough to functionally re-dominate the screen when
  open, which undercuts the entire point of the revert. The narrower cap is
  the one that actually keeps Command primary.
- **Mobile (<901px)**: the restored "Ask an agent" link opens the mounted
  instance as a bottom sheet through the Phase 3 Sheet primitive, sliding up
  and leaving the grid visibly peeking above it.
- **Cmd+K** stays a second entry point exactly as today: `CommandPalette.jsx`
  already resolves agent intents via `onAgentInvocation`; it now opens the
  same mounted rail/sheet pre-scoped to the chosen agent's thread instead of
  navigating anywhere.
- Nav.jsx's `ALL_LINKS`/`ALL_MOBILE_MORE` inventory is untouched, a rail/
  sheet is not a page, this adds no entry and no sixth tab.

## Phase 3: one Sheet primitive

The app has (at least) five independent hand-rolled overlay implementations
today, confirmed by direct inspection:

| Overlay | Portal | Focus trap | Escape | Close button | Notes |
|---|---|---|---|---|---|
| `AskAgentSheet.jsx` | yes | yes | yes | yes | the good pattern |
| `AccountSheet.jsx` | yes | yes | yes | yes | mirrors AskAgentSheet by design |
| `PlanPage.jsx` block editor | n/a (inline) | yes (`:663`) | yes (`:352`) | edit mode: no, only backdrop tap | own `visualViewport` listener (`:666`) duplicating `--kb` |
| `Nav.jsx` More sheet | n/a | **no** | **no** | yes, top-of-panel (thumb travel) | zero grep matches for Escape or `useFocusTrap` |
| `AgentChat.jsx` Context/Reasoning/FileDraft | **no** | yes | **no** | **no** | renders `.chat-file-sheet`, styled for the orphaned `.chat-file-dialog`, effectively no layout CSS at all |

Build one `<Sheet>` component (`dashboard/src/components/Sheet.jsx`) and
migrate all five onto it. `CommandPalette.jsx` is explicitly excluded, it's
search-first and keyboard-driven, a different primitive, correctly carved
out by two of the three directions.

Contract: `open`, `onClose`, `title`, `variant: 'popover' | 'drawer' |
'dialog'`, `tone: 'neutral' | 'destructive'`, optional `anchor`. Always:
portal to `document.body`, the existing `useFocusTrap` hook (not a refork),
a real Escape listener, backdrop-tap closes, internal scroll on content
only, max-height from the Phase 4 tokens.

Variant chosen by content weight, never by which spec shipped it:

- **Phone**: always `variant="drawer"` in its bottom-sheet form, rising from
  the trigger edge, thumb-reachable close, respects `--kb`.
- **Desktop, small closed choice set** (≤4-6 options: Context's 4 source
  rows, Reasoning's model/effort halves): `variant="popover"`, anchored
  under the trigger.
- **Desktop, real reading weight** (the 15-row agent list, a filed draft
  preview, account transaction history, Plan's block-edit form):
  `variant="dialog"`, centered.

Dismiss standard, one rule everywhere: 44px target, `--dim` at rest,
`var(--agent)` (agent surfaces) or `--accent` (everywhere else) on
hover/focus, top-right on desktop dialogs, bottom-reachable on mobile
sheets, always paired with backdrop-tap and Escape. `tone="destructive"`
(discard a draft, delete inside a sheet) gets a `--warn`-tinted control with
a text label ("Delete" vs "Cancel"), never sharing the plain neutral close's
bare glyph, a text label reads unambiguously for an irreversible action in
a way a recolored icon doesn't.

Fold `PlanPage.jsx`'s block editor onto `<Sheet>` as a reference migration:
it already has real Escape handling (`:352`) and a working focus trap
(`:663`), the fix here is dropping its ~20-line bespoke `visualViewport`
listener (`:666`, confirmed present) in favor of the shell's existing `--kb`
custom property (already set globally, `lib/viewport.js:56`), not repairing
broken behavior.

## Phase 4: token system

Two real gaps, not a bigger spacing scale (`--s1`-`--s7` and `--radius`/
`--radius-sm` are correct as-is):

**Overlay sizing.** Add a semantic pair instead of a spacing step past the
scale's actual end: `--overlay-inset` (the margin every sheet reserves from
the viewport edge) and a computed `--sheet-max-h: min(720px,
calc(var(--app-height, 100dvh) - var(--overlay-inset)))`. Every sheet's
max-height points at `--sheet-max-h`. This retires the undefined `--s8`
reference and, in the same move, the three unrelated ad hoc vh guesses
already scattered in the file answering the identical question
("how much of the screen is safe to fill") three different ways:
`.cmd-pin-brief` 38vh (`:5060`), `.cmd-today-body` 52vh (`:5084`), `.ac-bar
textarea` 34vh (`:5152`).

**Elevation.** No named scale exists today, box-shadows are one-off
literals with no link to the (good, already-existing) z-scale:
`.glass-card` `0 8px 32px rgba(0,0,0,.25)` (`:730`), the More panel
`0 8px 32px rgba(0,0,0,.4)` (`:1947`), `.plan-block.dragging`
`0 10px 28px rgba(0,0,0,.5)` (`:3406`), `.cmdk-panel`
`0 24px 48px rgba(0,0,0,.45)` (`:3539`). Add `--elev-card`, `--elev-sheet`,
`--elev-modal`, tied to `--z-sheet:40`/`--z-modal:60` so stacking order and
shadow depth are declared together instead of independently reinvented per
surface.

**Two build-time guardrails**, not one, they catch different failure
classes:

1. A test that every `var(--x)` referenced in `styles.css` resolves to a
   name declared in `:root` (SPEC-v28 Phase 5's own proposal). Would have
   caught `--s8` with zero manual review.
2. A grep-level check that every `className` string in a `.jsx` file has at
   least one matching selector in `styles.css`. The var()-guard cannot see
   the `.chat-file-sheet`/`.chat-file-dialog` drift, that's a renamed
   selector, not an undefined token, and needs its own check.

## Phase 5: the dismiss standard

Folded into Phase 3's Sheet contract above rather than a separate pass, one
component enforcing one rule is stronger than a style-guide entry every
future overlay has to remember. The More sheet migrating onto `<Sheet>`
picks up Escape, focus trap, and a bottom-reachable close for free, it has
neither today (confirmed: zero grep matches for Escape or `useFocusTrap` in
`Nav.jsx`).

## Phase 6: instant write from chat (new, not in v28)

The load-bearing constraint: `chat_allow()` (`agents/runner.py:216-239`)
intersects against `READ_ONLY_TOOLS` **unconditionally at the final
return**, "Writer tools cannot appear" per its own docstring. That wall is
correct and stays exactly as-is, it is what keeps chat from ever reaching
money writes, trade proposals, or pipeline mutation by accident. Instant
write is not a weakening of that wall, it is a second, narrower, equally
code-enforced wall next to it, following the same pattern as
`NO_MONEY_PROPOSALS`/`TRADE_VERBS`: a closed set, checked in code, not in a
prompt.

**New closed set**: `INSTANT_WRITE_TOOLS`, six tools, one per domain,
disjoint from `READ_ONLY_TOOLS` and from the nightly `ALLOWLISTS` writer
tools (so a nightly run or an Ask/room invocation never gets these by
accident, `run_chat_turn` is the only caller that ever queries them). Money
and pipeline tools structurally cannot appear here, there is no tool for
them, not a blocked one, the same "no writing counterpart exists" pattern
already used for `read_pipeline`/`read_notes`.

Each tool maps to a real, already-existing endpoint pair, chat reuses the
app's own write and undo code rather than growing a second implementation:

| Domain | Write tool calls | Undo calls | Notes |
|---|---|---|---|
| Goals | `db.create_goal` (`api/main.py:1117`) | `db.archive_goal(restore=False)` on the row just created | goals are archive-not-delete already; "undo create" = archive, consistent with that law |
| Plan blocks | `POST /api/plan/blocks` (`api/main.py:3346`) | `DELETE /api/plan/blocks/{id}` (`:3392`) | tombstone-safe per SPEC-v7 already |
| Notes | `db.create_note` (`api/main.py:3518`) | `db.delete_note` (soft, `:3543`), `restore_note` (`:3555`) exists too |
| Facts | `write_fact`, already an agent tool (`ALLOWLISTS`, e.g. physician/coach/family) | `db.delete_fact` (`core/db.py:3975`) | facts from any writer are born `verified=0` per the facts law, already the lowest-risk domain of the six |
| Gym log | `db.confirm_gym` (`core/db.py:2443`), the exact action Command's own confirm button already performs | **new**: no unconfirm path exists today, add one narrow reversal (`gym_confirmed=0` for that date) | must call `confirm_gym` only, never `apply_grace`/reset, `core/streaks.py:11` is explicit that the nightly run is the ONLY writer of grace/reset and this must not change |
| Partner tasks | `db.add_partner_task` (`api/main.py:3122`) | `db.archive_partner_task` (`:3195`), `restore_partner_tasks` (`:3222`) exists |

The one real gap: gym log has no undo endpoint yet. Small, narrow, add it
alongside the tool, don't skip undo on one of six domains because the
reversal happens to be missing.

**Visual language**: a third bubble type in `Exchange`
(`AgentChat.jsx:76-183`), alongside the existing `.ac-verdict` (opinion) and
`.ac-draft` (still needs a tap, this is where money/pipeline proposals stay
forever). `.ac-write`: left border in `chatRoleColor(role)`
(`AgentChat.jsx:42-45`), a filled checkmark glyph, past tense, one
numbers-first line naming exactly what changed ("Added block: Gym, 6-7pm,"
"Logged: gym confirmed, 14 day streak"), never "Proposed." Three visual
grammars, never confused: plain agent-colored text = it just talked, a
checkmark receipt = it already wrote something, an outlined draft card =
it wants your tap.

**Undo, two entry points, one code path**: fire the app's existing
`toast(msg, level, undo)` (`App.jsx:871`) the instant a write lands, same
idiom `TheLine.jsx` already uses for a reversible server write. Because a
toast times out and the conversation doesn't, the `.ac-write` bubble also
keeps a second, non-expiring inline Undo wired to the identical callback,
so a write from five scroll-backs ago stays reversible for as long as the
thread is open. Once used, the bubble flips to a dimmed "Undone" state in
place rather than vanishing, scrolling back up later never lies about
what's still true.

**Teach by disclosure, not surprise**: the first write in any thread
triggers a one-line, once-per-thread, localStorage-gated line in the
existing `.ac-hint` slot (already used for the specialist-count nudge):
"Fury can write to your plan, goals, and notes directly. Money and calls
always ask first." One sentence, never a modal, never blocking, doesn't add
a confirmation tap the "instant" requirement forbids.

## Phase 7: other-pages cleanup

- **Money** (`MoneyPage.jsx`): pull Business burn, the one number with a
  real $150 cap and a real on-pace verdict (`burnLevel`, `:16-20,242-245`),
  out from behind the `showDetails` toggle (`:198-200,373-376`) so it
  renders unconditionally under net worth, same "numbers first, no gate"
  treatment the Order card gets. Also pull it out of the generic `<Card>`
  wrapper all four Money modules share identically (`:76-88`, reused
  unchanged at `:383,414,461,468`), a direct hit against `PRODUCT.md`'s
  anti-reference against identical stat-card grids, give it its own
  big-number-plus-meter treatment instead of one more equal-weight
  rectangle. Leave the account-group `<details>` as the one remaining
  collapse layer, that's a legitimate phone-space call.
- **MoneyHistoryPage.jsx**: no way back to Money short of the OS back
  gesture (confirmed, no "back"/crumb string anywhere in the file). Add a
  slim sticky header with a text back-link at the Sheet primitive's own
  header weight. (The month input already has `aria-label="Filter by
  month"`, `:147`, confirmed, that part of one proposal's finding was
  wrong, no accessibility fix needed there.)
- **AccountSheet.jsx** inherits the `--s8` P0 for free via the shared
  `.ask-agent-sheet` class, fixed automatically once Phase 3/4 land, no
  Money-specific change needed beyond migrating onto `<Sheet>`.
- **Roster** (`RosterPage.jsx`): `AgentCard` spends its agent color on only
  the glyph border and codename text (`:16-60`), everything else (persona,
  domains, cadence, trust) renders in flat ink, on the one page whose
  entire premise is "the agents are characters." `AgentChat` already proved
  the fix and shipped it elsewhere: washing the whole surface in `--agent`/
  `--agent-soft`/`--agent-line` (`styles.css:5209-5223`) instead of
  spending color on one glyph. Extend that exact technique to
  `.agent-card`, the most literal application of "restore the colors" to
  the page currently underselling them most.

## Phase 8: mechanics and guardrails (carried from v28 Phase 5)

- The two build-time guardrails from Phase 4, unchanged.
- `strip_em_dashes` applied at proposal/memo write time, not only chat.
- The two `padding-left` hover transitions become `transform`.
- Bundle: split the single 512KB chunk (route-level lazy for Journal, Plan,
  Money history); drop per-tick `JSON.stringify` comparators for cheap key
  equality.

## What's still open

v28's second open question is still open, none of the three brainstormed
directions substantively answered it (they answered "how the picker is
displayed," Phase 3's popover/dialog split, not "should a 15-agent x
4-model x 4-effort picker exist at all" when deterministic dispatch is
supposed to be the product's soul). Carrying it forward unanswered rather
than deciding it by default:

- **Should you be picking models at all?**, or does a "smart default,
  override rarely" design shrink the Reasoning sheet closer to nothing.

Everything else v28 left open (mount-once chat) is now decided above.

## Sequencing

Implementation proceeds in the phase order above: 0 and 1 first (fastest,
highest-value, directly answers "the old version was better"), then 2-3
together (the shell-mount and the primitive it needs to open sheets
correctly), then 4-5 (mostly mechanical once 3 exists), then 6 (new
backend surface, wants its own review pass given it's a real database
write path), then 7-8 (cleanup, can run any time after 3).
