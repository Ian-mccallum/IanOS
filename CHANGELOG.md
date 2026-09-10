# Changelog

All notable changes to ianOS are recorded here, newest first. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); dates are when a
change landed on `main`, not when work started.

This file starts with SPEC-v37. Everything before it (SPEC-v2 through v36)
shipped without a changelog entry — `git log` and the `docs/SPEC-vN-*.md`
files are the record for that history; CLAUDE.md's "Conventions & gotchas"
section links each one to what it shipped.

## 2026-09-09 — Four fixes: chat full screen, source of truth, Life, Learning

Five requests in one message. Four became independent parallel builds (two
Opus, two Sonnet, run via the Workflow tool); the fifth (notebook search)
had already shipped earlier the same day. Every workstream's own tests
passed before merge; the orchestrator then ran the full suite together,
found and fixed one cross-workstream visual bug live in a browser, and
verified the other three against a scratch copy of the real database.

### Chat: full screen, properly

Desktop "open" mode was a 420px right-anchored drawer over an otherwise
unmodified page ("modal on the side," Ian's words). It is now a full-screen
two-pane takeover: nav, mobile bar, the page's own header, and the offline
bar all hide. Opened from Command, a hero column (Order card, same DOM,
same handlers) fills a `clamp(320px, 26vw, 440px)` left column and chat
fills the rest, hairline seam, zero gap, zero overlap (measured live).
Opened from anywhere else, there is no fake hero — chat goes true
edge-to-edge. Mobile is unchanged.

**Found during verification, not by the build agent** (it had no browser):
in the no-hero case, the underlying page was never hidden, only covered by
the panel's deliberately translucent background — at full viewport width
that let the whole page bleed through as illegible overlapping text.
Fixed: `.page-content` goes `visibility: hidden` in that case.

### Chat: Ian is the source of truth on his own life

He said it plainly: agents can suggest, they cannot refuse a plan he's
already decided on. `CHAT_LAW_LAYER` (outranks the persona) now says so
explicitly, and a paired rule covers the one real gap left after last
session's `goal_id` fix: when a write is missing exactly one thing it
genuinely needs, ask one direct question instead of guessing or refusing.
Verified with two real live model calls against a `VACUUM INTO` snapshot:
a complete request wrote immediately with one named concern and no
hedging; an incomplete one asked a single follow-up and wrote nothing.
Also fixed a real internal contradiction the file already had: "do not
call writer tools" sat a few paragraphs above "make the write,"
unqualified — it now says which writer tools (the nightly-only ones).

### Life: the rebuild had a broken container

"The life ui page sucks. the to do is terrible" — after SPEC-v41's own
rebuild. Root cause: two CSS defects shipped in the spec itself
(`.today-panel` had zero padding on any side; a -6px optical alignment
trick was silently clipped by the swipe wrapper, costing 6px off a 34×44
target), invisible to a code review of the component alone. Three defects
were functional, not aesthetic: completing a task was **unrecoverable**
(`task._done` never existed anywhere in the codebase, so Undo was always a
no-op and the done row was an inert span); a rejected write left a row
permanently lying (no try/catch anywhere but `add`); a committed rename
visibly flashed back to the old text for the length of the round trip. All
three fixed. Also: the mobile composer's dead `position: sticky` (removed),
the separator that could structurally never match its intended anchor
(fixed), the spec'd "Done for today" delight that was never built (built),
and `.life-page`'s missing mobile gap that fused two panels into one
doubled hairline (fixed). Known and deliberately unfixed: the Life goal
panel's milestone checkbox is Partner's pink brand colour, a second checkbox
language on the same screen — flagged, not touched (spans other pillars).

### Learning: a topic that vanishes with no trace

`core/learning.py::clarifying_topics()` already existed; the dashboard
projection never called it. A topic mid-onboarding was absent from
`/api/state` entirely — no card, no trace, nothing. Ian's own real database
had exactly this: a topic named "Ai," created today, stuck in `clarifying`
since a one-minute-old tutor thread that never ran a turn. Fixed:
`_learning_state` now returns `clarifying_topics()` under its own key,
and the page renders an "Unfinished setup" card with a Continue action
that reopens the same thread. Verified against a read-only copy of the
real database: the fix surfaces exactly the stuck "Ai" topic and resumes
the real onboarding conversation.

## 2026-09-09 — The nightly backup had been dead for 29 days

Found while verifying that everything was up to date. `make backup-status`
reported a last success of 2026-08-11, and `launchctl list` showed
`com.ianos.backup` exiting **126** on every scheduled attempt.

### Fixed
- **Root cause: macOS TCC.** The repo lives under `~/Desktop`, a protected
  folder. A LaunchAgent whose program is `/bin/bash` has no access there, so
  every run died with `Operation not permitted` at exec, **before**
  `backup.sh` started. Its `set -Eeuo pipefail` ERR trap therefore never
  fired, and the "a failed scheduled run writes a system memo, never fails
  silently" guarantee could not cover it: the script has to run to report
  that it did not.
- **Why only this job.** Every other agent (`nightly`, `serve`,
  `financesync`, `btcsync`, `canvassync`) execs `.venv/bin/python` or
  `.venv/bin/uvicorn`, which already hold the grant. The backup was the only
  plist on `/bin/bash`.
- **`ops/com.ianos.backup.plist` launches through the venv python** and
  `os.execv`s bash, since TCC responsibility survives an exec. Confirmed:
  through `make schedule-backup` and a real launchd run, exit 0, snapshot
  `4641200e`, `17:01:50 OK`. Ruled out first: exec'ing the script directly
  (still 126) and a Homebrew bash (not installed).
- **The engine is untouched.** Still bash + restic + sqlite3 per SPEC-v16;
  the shim is a macOS launcher only, and Linux's systemd unit calls
  `scripts/backup.sh` directly.
- **Three fresh snapshots taken**, closing the 29-day gap.

### Worth knowing
- ianOS *was* signalling this. `dayArc.js` rings the agent pulse when the
  last backup success is over 48h old, so the ring had been on for a month.
  The mechanism is right; a thin ring on a small dot may be too quiet for
  "your only off-site copy is stale".

## 2026-09-09 — Agents could not edit the calendar: a schema that lied

Ian asked Alfred to put dinner and stargazing on tonight's plan. Alfred
refused, explaining that the plan-block tool required a `goal_id` and that
inventing one would misattribute progress to a real goal. He was right, and
the bug was ours.

### Fixed
- **Root cause: the SDK marks every key of a dict-style tool schema
  required.** `_build_schema` ends `"required": list(properties.keys())`, so
  `{"date": str, ..., "goal_id": int}` told the model `goal_id` was a
  mandatory integer, while the tool's own description said "goal_id
  optional". The model reads the contract, not the prose. Nothing was wrong
  below the tool: `plan_block_create`, `db.create_plan_block` and the column
  all took `goal_id=None` happily.
- **`_schema()` in `agents/runner.py`** builds a real JSON Schema (passed
  through verbatim by the SDK) where `T | None` means optional, matching how
  the handlers already declare their own defaults, and
  `Annotated[T, "..."]` documents a parameter where the model reads it.
- **18 tools corrected**, not one. The same defect was in
  `chat_write_task.goal_id` (identical misattribution risk),
  `chat_write_goal` (10 required parameters where 8 have defaults),
  `chat_write_note.domain`, `chat_confirm_gym.date`,
  `chat_write_partner_task.parent_id`, `create_proposal.attachment/metadata`,
  `write_memo.priority`, `read_school`'s four, `act_plan_block_create.goal_id`
  and every single-argument reader's `days`/`limit`.
- **Verified end to end**, not just in the schema: a real steward chat turn
  on Ian's own request ("bdubs 7 till 9, middle fork 9 till 11") now writes
  both blocks with `goal_id=None`, against a snapshot of the live database.

### Added
- `tests/test_agents_guards.py` gains three guards: a per-parameter check on
  the twelve known-optional arguments, a general one that fails if ANY tool
  requires a parameter its own description calls optional, and its mirror so
  `_schema()` cannot quietly make a required argument optional.

### Not a bug, checked
- Ring 1 `act_*` tools hardcode `plane="nightly"`, which is correct: they
  are absent from both `READ_ONLY_TOOLS` and `INSTANT_WRITE_TOOLS`, so chat
  cannot reach them.
- The SDK's `CanUseToolShadowedWarning` for the ianos MCP tools is benign:
  `make_consult_pretooluse_hook` is wired as a `PreToolUse` hook alongside
  `can_use_tool`, which is exactly what Law A2's two-wirings-one-decision
  design is for.

## 2026-09-09 — School: the writing surface, notebook search, class order

Five requests from Ian in one pass. Nothing here is a new subsystem; each one
is an existing School mechanism that was pointed at the wrong thing.

### Changed
- **A course's AI policy no longer gates study tools.** Study aids are built
  from Ian's own notes for his own revision, so which course they came from is
  not the machine's call. `_school_course_blocks_study` is deleted from
  `core/school.py` and from `agent_note_texts`. **Consent is untouched and is
  now the only wall**: `school_ai_settings` still gates creation, the claiming
  UPDATE, and completion. `policy_json.ai_policy` stays on the School page as
  display metadata. The test that asserted the old block was rewritten to
  assert both halves of the new truth, so the consent gate cannot quietly
  leave with the policy gate.
- **The course rail is ordered by the next class, not the alphabet.**
  `dashboard_snapshot` sorts on the `next_meeting.start_at` it already
  computed. Today's classes lead in time order, the list walks forward through
  the week, and an asynchronous course sorts last. A class that already met
  today stays ahead of tomorrow's rather than jumping to the back.
- **Notebook search reads the whole note.** The SQL always searched
  `plain_text`; the UI filtered client-side over the 280-character preview, so
  a word written later in a lecture never matched. Rows now carry
  `match_count` and `matches` (the sentence around each hit, the matched text
  as written, head/tail flags for the ellipsis), the field is debounced
  server-side with a request-id guard, and a typed `%` searches for itself
  instead of returning every note in the course.
- **The writing surface got the room.** The measure went from 68ch to 80ch
  normally and 100ch in full screen, with a type-size and spacing step up in
  full screen. Deliberately not a full bleed: past ~100 characters the eye
  stops reliably finding the start of the next line.
- **Full screen is now actually full.** It hides `.school-notebook-head` too,
  whose actions were pinned top-right and measured overlapping the new fixed
  control bar. That bar carries Notes / Details / Files / Finish / Exit, and
  the sessions rail renders into a Sheet since full screen hides the rail.

### Added
- **Keyboard shortcuts.** **Cmd+B with nothing selected bolds the whole
  line** (the editor default only flipped the stored mark at the caret, which
  looked like nothing happened); with a selection it is the ordinary toggle.
  **Cmd+P toggles a bullet list**, Cmd+Shift+P numbered. The extension needs
  `priority: 1000` to outrank StarterKit, which binds Mod-b itself and Mod-y
  to redo. Returning true from the handler preventDefaults Cmd+P, so the print
  dialog never opens inside a note.
- **`make sync-syllabus`** (`import_canvas_calendar.py --seed-only`), and the
  Week 3 Forensic Science deadlines Canvas never put in the .ics feed. ANTH
  246 is asynchronous, so its weekly module deadlines live on the module page.
  They belong in `known_major_dates` in the school seed, because
  `seed_inventory` archives any `syllabus` item the file no longer lists, so a
  hand-inserted row is erased on the next load. Canvas items are not read or
  archived by this path (262 before, 262 after).

### Fixed
- **The placeholder no longer sits under what you are typing.** It was an
  absolutely positioned `<p>` stacked over the prose, hidden on
  `editor.isEmpty`, so it only disappeared when React happened to re-render.
  It is Tiptap's `Placeholder` decoration now, part of the document's own
  render pass. `@tiptap/extensions` was a transitive dependency being imported
  directly; it is declared in package.json now.
- **Every new entry in the school seed gets an explicit `id`.** Without one
  the loader derives `external_item_id` from LIST POSITION, and
  `school_item_completions` is keyed on that: inserting an entry mid-list
  silently re-keys every later item and orphans its completions. ANTH 210's
  existing six are pinned to the ids they already had.

## 2026-09-09 — Body's log

Ian asked Body for a poop counter with a comedic animation and a simple
logger. Deliberately small: one table, one panel, no new page, no new spec
file. Every decision below is his, answered before any code was written
(agents see it, one tap plus optional detail, Body page only, count plus
7-day rail plus last time).

### Added
- **`poop_log`** (`core/db.py`), events not tallies (D3): the day's number is
  always `COUNT(*)` over live rows, so Undo is a soft delete and the count
  rebuilds itself. `day` is stamped at the tap, not derived from `logged_at`,
  so a tap made on a sleeping Mac still counts for the day it happened (the
  gym-confirm precedent). `bristol` (1-7) and `note` are optional and stay
  empty for a one-tap log.
- **`/api/poop`** (log / patch / delete / restore) plus `GET /api/poop/today`.
  Its own `no-store` routes, **not `/api/state`**, for the same reason the
  sleep and step values are kept off it: state is polled every 15s and cached
  by the phone's service worker. The log tap is `queueable`, so the phone can
  log with the Mac asleep and a replayed mutation cannot become a second poop.
- **The backfill door.** `POST /api/poop` accepts a `logged_at`, so
  remembering at 6pm that it happened at 10am keeps the real time. Bounded on
  both sides in code (`POOP_BACKFILL_MAX_DAYS`, no future, naive-local only,
  the SPEC-v18 timezone law), and refused in the UI before the tap rather
  than as a 422 after it. A backfill names its own day; the state that comes
  back is always the day the panel is showing, so adding one to yesterday
  moves the rail without replacing today's count.
- **`PoopMark.jsx`**, the one poop in the product. Drawn, not the 💩 glyph,
  for the reason `StarMark` is drawn rather than ★: an emoji is a font, so it
  renders as whatever face the OS ships and cannot take the app's material.
  Three domes, each outlined over the fill of the one below so the stack
  reads as coils rather than a pyramid.
- **`PoopLog.jsx` on Body.** Today's count, the day's line, a 96px tap
  target, a 7-day rail in the sleep rail's grammar, and today's entries with
  one-tap detail and remove. The tap fires three things of deliberately
  different lengths: the button squashes and rebounds, five coils arc out on
  fixed vectors (a constant, so it is the same joke every time and not a slot
  machine), and two stink lines rise. Reduced motion swaps the thrown burst
  for a held one, never nothing.
- **Agent visibility.** Counts, the 7-day per-day average, the Bristol mix
  and hours-since-last ride `read_health`'s existing consent gate, computed
  in Python. `note` is withheld: Ian's own writing about himself follows the
  journal/notes wall, not the sensor rule. No agent writes this table and no
  Ring 1 act touches it; logging is Ian's tap.

### Design law it holds to
No target, no percentage, no streak, no lifetime counter, and `--crit`
appears nowhere on the surface (`--warn` is the worst state, on the backfill
bound). The day's line reacts to volume and to nothing else, so no state it
can enter reads as a verdict. `tests/test_poop.py` and
`dashboard/tests/poop-log.ui.test.jsx` assert each of those.

## 2026-09-02 — SPEC-v38: Mr. Miyagi and the Learning pillar

Ian named three things he was teaching himself unprompted (case interviews,
AI, Python) that had no home on School's Canvas-driven surface. Learning
gives self-directed practice the same product treatment School has for
coursework, minus the deadlines nobody set. `docs/SPEC-v38-learning.md`
carries the audit; shipped in four phases, each its own commit, sequenced
after SPEC-v41 (`GoalSheet` and Life's Today list had to exist first).

### Added
- **Mr. Miyagi (`tutor`), an 11th nightly role.** Reads a topic's working
  profile and the last 14 days of session history, writes one concrete
  exercise for tomorrow, never a lecture. Zero active topics is not an
  error: it says so and writes nothing.
- **`core/learning.py`**, its own schema (`learning_topics`,
  `learning_sessions`, `learning_streak_events`) isolated from
  `core/db.py`'s migrations, the `core/school.py` precedent. A streak that
  structurally mirrors the gym's weekly rest-day allowance without ever
  sharing a row with it.
- **Onboarding as an ordinary consult thread.** Ian types a topic name, Mr.
  Miyagi asks real clarifying questions before calling
  `chat_write_learning_profile` (SPEC-v29's instant-write family's first
  role-scoped member, tutor only) to flip the topic from `clarifying` to
  `active`. The agent may suggest a topic via a plain proposal but never
  creates the row itself; Ian always runs the clarification pass.
- **`learning.confirm`, a Ring 1 act granted to `tutor` only**, mirroring
  `gym.confirm` exactly: today only, one event, never grace or reset.
- **The Learning pillar page**, behind More: today's featured practice row,
  topic cards with a per-topic growth visual that only ever grows (5 stages,
  never the streak, which can legitimately reset), a "suggested by Mr.
  Miyagi" card, and a single "Add a topic" field.

### Fixed
- `App.jsx`'s `PAGE_TITLES` had no entry for the new page, so it silently
  fell back to displaying "Command" as the page's own title. Caught live in
  browser verification, not by any unit test.
- The spec's own `LearningPage.jsx` read `state.proposals`, a key that has
  never existed in `/api/state`; the real key is `pending_proposals`.
- `core/pillars.py`/`dashboard/src/lib/pillars.js`: Learning routes through
  the existing `personal` domain like partner and life already do, no
  `goals.domain` widening.

## 2026-09-02 — SPEC-v41: the day arc, the tagline purge, and Life

Ian, on three header mockups: "Those bars are ugly and useless." Plus: "Get
rid of all cliché text," a daily to-do for Life that rolls forward instead
of resetting, and a goal composer he can type a sentence into instead of
stepping through a wizard. `docs/SPEC-v41-arc-taglines-life.md` carries the
audit; shipped in five phases, each its own commit.

### Added
- **The day arc + agent pulse.** One hairline (06:00-24:00, today's plan
  blocks and calendar commitments) with a breathing now-dot, plus a pulse
  dot for agent/backup health, replacing the header's status dot, "Agents
  ran Xm ago", focus chips, the "Nd to client" countdown, and the clock.
- **Life's Today.** A daily to-do (`tasks`) that rolls an unfinished item
  forward by reading, never a nightly write. A priority tap puts it on
  Command's Order; only Ian's tap can, never a nightly agent. Three doors
  for agents: chat's `chat_write_task`, Ring 1 `task.create`/`task.complete`
  (steward only, `task.create` capped at two a night), and read-only
  `read_tasks`.
- **GoalSheet.** One sheet replaces the three-step goal wizard: describe a
  goal in a sentence, an optional role-less Draft (a zero-tool, single-turn
  Haiku parser that never writes) fills in the rest, and Milestone goals no
  longer need a fake numeric target. Two new Life metric resolvers
  (`tasks_done_this_week`, `tasks_done_for_goal`) give Life goals a live
  number instead of a permanent "no data".

### Fixed
- `db.create_goal` is now the one `INSERT INTO goals` in the codebase; the
  API and chat's `chat_write_goal` both call it and both validate
  `metric_key` against the real resolver list instead of trusting free text.
- The goal-draft model wraps its JSON in a markdown fence often enough to
  break parsing even though the prompt says not to; caught live in
  verification and fixed before it shipped.
- A percentage width on a flex item with no definite size of its own
  resolves to 0px: the arc's mobile hairline collapsed to nothing until the
  layout was rewritten with `flex-grow` up the chain.

### Removed
- `GoalWizard.jsx` and `data/goalTemplates.json`.
- 18 static page subtitles, Partner's rotating whispers, and every other
  decorative second line across the dashboard; `test_no_taglines`
  (`tests/test_mobile_ui.py`) is the executable form of the rule.

## 2026-09-01 — SPEC-v40: the chat, properly

Ian, after two weeks of use: "the UI is good but the UX is messed up; for
the PWA it sucks, the chat seems so small instead of a typical chat bar at
bottom interface; the position isn't fixed." Plus: new chats with the same
agent, some memory between them, and Compact. `docs/SPEC-v40-chat-threads-
and-layout.md` carries the audit ledger; shipped in four phases.

### Fixed
- The chat UI polled `GET /api/agent-invocations/{id}`, a route SPEC-v37
  deleted, so every reply sat behind "thinking" dots until a manual reload.
  It polls the thread detail now, and a reload mid-turn resumes.
- Every consult turn had been failing since SPEC-v37 Phase 5: the SDK
  requires a streaming prompt whenever `can_use_tool` is set, and the runner
  passed a string. Unit tests mock `query()` and never hit that check.
- Dumbledore could not read class notes: the School chip was off by default
  on his threads, and note text was walled from every agent. Threads for
  watchdog open with School on, and `read_school notes=true` returns recent
  note text in an attended consult only (plane B), gated in code by study
  mode and the per-course AI policy. Nightly runs still never see a note.
- Ian's own messages had no bubble and the agent's reply was dimmer than his
  question: the `--agent` colour tokens sat on a class nothing rendered.
- Focusing the composer on the phone swapped its React parent, unmounted
  the textarea, and dropped the keyboard it had just raised.
- The lock screen re-locked after 90 seconds in the background; now 15 min.

### Added
- **The layout.** Two states. Phone dock: one row under the Order. Phone
  open: the conversation is the screen, composer pinned above the keyboard.
  Desktop dock: last exchange plus composer, no inner scroller. Desktop
  open: a right drawer the page stays usable behind. One flex column, the
  stream pinned bottom-first with `column-reverse`, no `vh` literal left.
- **Durable threads.** Creating a thread no longer closes the agent's other
  threads; every thread is listed under its agent in a Threads sheet, with
  New chat per agent, reopen for archived ones, and a title taken from the
  first question.
- **Memory and Compact.** A thread summary (zero-tool Haiku, model pinned in
  code, bounded, dash-free) written by a Compact button, automatically at a
  turn threshold, and when New chat retires a thread. Compact clears the
  native session so the next turn starts from the summary; turns are never
  deleted, and a divider marks the spot. A new thread's first turn hears the
  last three summaries from the same agent only.

### Removed
- Mobile "expanded" and desktop "fullscreen" chat states; the per-agent
  auto-close; the agent list inside the Reasoning sheet (it is Threads now).

## 2026-09-01 — SPEC-v37: the agent rebuild

An audit found 870 tests proving every wall held and none proving any claim
about the agents was actually true: a dead APPROVE loop (proposals piled up
with no verb to act on them), a memory flywheel that never turned (the
archivist's weekly distillation was configured but never wired in), and an
interactive-agent surface (Ask sheet, inspect mode, rooms) built on a threat
model tuned for unattended nightly runs. `docs/SPEC-v37-agent-rebuild.md` is
the full spec; shipped in six phases, each its own commit.

### Added
- **Tiered agency.** A closed list of 13 Ring 1 reversible acts
  (`core/acts.py`) apply immediately, receipted (`agent_acts` table) and
  undoable in one tap from Command's new Receipts strip. Two new Ring 2
  proposal kinds, `goal_change` and `quota_rebaseline`, give the roster a
  verb it was missing.
- **The situation block.** Every nightly producer's prompt now opens with a
  precomputed status block (`core/situation.py`): season/capacity, hero
  goal, nearest deadlines, live quotas, expired-undecided goals, the full
  open-proposal ledger, and the last 24h of Ring 1 acts — the fix for the
  dead APPROVE loop.
- **The roster, reworked.** Ten active agents (was fifteen): advisor merged
  into watchdog (now Dumbledore), archivist retired in favor of a pure
  function, family/infra/publicist retired. Alfred Pennyworth (steward) is
  now the default agent. Role files carry no hardcoded dates or dollar
  figures anymore (`test_no_expired_dates_in_prompts`).
- **Memory: the ledger and the index.** `upsert_fact` now defaults to
  `verified=0`; `write_fact` requires resolvable evidence; `write_memo` at
  priority ≥2 requires a read this run. The archivist's weekly distillation
  became `core/ledger.py::distill()`, called every night. A new FTS5 memory
  index (`core/memory_index.py`, `search_memory` tool) gives every agent
  full-text recall over memos/briefs/notes/facts/school notes/proposals —
  explicitly recall-only, never a source of truth (`grounding: "recall_only"`
  on every result), and structurally excluded from every existing privacy
  wall (journal, health, school files).
- **The consult surface.** One chat surface replaces the Ask sheet, inspect
  mode, and hand-rolled rooms. A daytime thread is now genuinely attended
  (Plane B): real Claude Code tools (Read/Grep/Glob/Bash/WebSearch) behind
  new opt-in capability chips (Files, Workspace, Shell), gated by one runtime
  wall (`agents/consult_gate.py`) regardless of which chip is on. Fury can
  convene up to three other agents as real SDK subagents. Threads resume
  their actual native conversation instead of a quoted-summary cache. The
  chat panel is a portal into Command's grid (dock / expanded / full screen),
  not a separate overlay.
- **Money the CFO can actually see.** `read_accounts` gives cfo/wealth/chief
  the whole linked account set and a real computed net worth
  (`db.net_worth()`). The Money hero has its own refresh button
  (`POST /api/money/refresh`).
- **Health consent has a front door.** A one-time card on the Body page asks
  explicitly before physician/coach ever see a health log; the Roster now
  says so plainly instead of showing a stale timestamp.

### Fixed
- The runner no longer runs inside the web process; a crash there used to
  take a brief down with it, silently.
- A brief written at 21:30 was stamped with the night it ran, not the day it
  governs, so the "stale" indicator was wrong almost all day, every day.
  `briefs.governs_date` fixes it.
- `cash_position()` summed every transaction since the first CSV import ever
  (seeded demo rows included) with no time window — the exact shape of bug
  that turned two small balances into "~$81 months of runway". Now a real rolling
  30-day window over linked accounts only.
- Checking-balance freshness was hardcoded to a data source (`simplefin_chase`)
  that Plaid replaced months ago and that ingest marks permanently
  `disabled` — every checking balance therefore always read as stale. Now
  traced to the source that actually produced the number.
- Four seeded demo holdings rows ($7,420 combined, dated 2026-07-21) were
  never removed once real SnapTrade data arrived, producing a false cliff in
  any balance history view. Deleted.
- A finance sync failure was recorded to `ingest_log` and nowhere else — an
  entire SnapTrade drop-out (4 of 9 accounts) went unnoticed for days. Now
  writes one `system` memo on the first failure of a streak (shared with
  Canvas sync, not just finance).
- `role_stats()` counted `EXPIRED` proposals toward the "proposed" total its
  own docstring said it excluded — Watchdog's roster card read "31 proposed"
  when 13 of those had simply timed out unread.
- `REGISTERED_TOOLS` was missing all 13 Ring 1 act tools, so no real agent
  could ever call one — only direct test harness calls (Phase 2, caught
  during Phase 4 integration).
- Fury's live-state block read a nonexistent key off `portfolio_snapshot()`,
  silently dropping the portfolio from every net worth figure it ever cited
  (introduced in Phase 5, caught during Phase 6).
- `db.CHAT_CHIP_IDS` never gained "documents" or "web" when those chips
  shipped in SPEC-v27 — neither was ever actually toggleable via the API.

### Removed
- `run_interactive_role`, `/api/agent-invocations`, `/api/agent-commands`,
  `/api/agent-rooms`, `AskAgentSheet.jsx`, and the sequential-Haiku-children
  rooms path — superseded by the consult surface above.
- The old prior-turn quoted-history cache (`CHAT_PRIOR_*`,
  `_chat_prior_block`) as the primary chat memory mechanism — kept only as a
  fallback for when native session resume fails, now including both sides of
  the conversation (the old cache never quoted Ian's own messages).
