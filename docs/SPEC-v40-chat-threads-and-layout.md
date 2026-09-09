# SPEC-v40: the chat, properly

**Status:** drafted and shipped 2026-09-01, four phases, each its own commit
(`57405e1` threads, `66b2813` memory and Compact, `282747b` layout,
`b5a1945` Threads UI). Verified at 375×667 and 1512px in the browser; the
installed-PWA keyboard pass (osui L9) is still owed on a real phone. Supersedes SPEC-v37 §7.2 (the three-state table) and
SPEC-v26's "one open thread per agent". Keeps SPEC-v37 Law A10 and every
Plane A/B wall.

## 0. Decision

Ian's words after two weeks of use: "the UI is good but the UX is messed up.
For the PWA it sucks: the chat seems so small instead of a typical chat bar at
bottom type of interface; the position isn't fixed." And: "you should be able
to open new chats with the same agent and they have some memory, and things
like compact should be available."

Three decisions, each answered by Ian on 2026-09-01:

1. **The conversation is a full-height surface with a pinned composer**, on
   the phone first. The dock on Command shrinks to a summary row. Nothing
   about chat is a card inside a scrolling page any more.
2. **Threads are durable.** Old threads stay listed and reopenable; "New
   chat" starts a fresh one. Not archive-and-replace.
3. **A short summary per thread is the cross-thread memory**, and **Compact**
   exists as both a button and an automatic threshold. Not a fresh start, not
   quoted history.

## 1. What the audit found

Root cause: `AgentChat.jsx` renders one panel (header + nested-scroll stream
+ composer) into three containers and lets CSS size it as a card. No state is
"messages fill, composer pinned."

| # | Defect | Where |
|---|---|---|
| P0-1 | Mobile dock is a 381px card with a 220px inner scroller inside the page scroller; composer scrolls away with the page, never above `--nav-h` | `AgentChat.jsx:1203`, `styles.css:8039-8050` |
| P0-2 | Focusing the composer swaps its React parent (portal to Sheet), unmounting the textarea; iOS drops the keyboard it just raised | `AgentChat.jsx:1117`, `:1204`, `:1213` |
| P0-3 | Expanded/fullscreen open scrolled to the top of history (scroll effect not keyed on `view`; `streamRef` only attached off-dock) | `AgentChat.jsx:819-822`, `:1061` |
| P0-4 | Ian's messages have no bubble: `--agent-soft`/`--agent-line` are declared on `.agent-chat`, a class nothing renders; agent prose is `--dim` while Ian's is `--ink` (inverse of every messaging app) | `styles.css:7830-7852`, `:1066` |
| P1-5 | Mobile expanded: two headers (~120px of chrome), `max-height: 85dvh` so a short thread is a short sheet; fullscreen has a notch gap and rounded corners | `styles.css:5586-5594`, `:8129-8132` |
| P1-6 | Enter sends on the phone; iOS has no Shift+Enter, so a paragraph is impossible | `AgentChat.jsx:1125-1130` |
| P1-7 | Desktop expanded is `position: absolute`, 920px wide inside a 480px column: covers Also on deck / Receipts, contributes no height, clips at 640px | `styles.css:8102-8119`, `:2941` |
| P1-8 | Agent switching is the fourth group inside the Reasoning dialog; no thread list, no New chat; header is a bare codename | `AgentChat.jsx:475-497` |
| P1-9 | The floating pill sits over Journal and a live call run (committed modes dim everything else) | `AgentChat.jsx:1207`, `styles.css:8058` |
| P1-10 | Sub-sheets render inside the panel: on the phone they are a Sheet inside a Sheet; one Escape closes both | `AgentChat.jsx:1157-1197`, `Sheet.jsx:66` |
| P1-11 | Header agent button, write-undo, missing-chip, chip rows under 44px | `styles.css:7605`, `:7634`, `:7657`, `:7997` |
| P2 | Empty dock slot leaves a 24px gap; `textarea max-height: 34vh`; thinking dots shift layout when the reply lands; four unrelated spacing steps | various |

osui traps hit by name: `max-height: calc(100dvh - literal)` (85dvh, 72dvh,
70dvh, 34vh, 220px); flex column without pinning non-scroller children; a
state fix applied to one surface's selector.

## 2. Target layout

Law A10 holds: `AgentChat` keeps its one mount in `App.jsx` and still
`createPortal`s into `#consult-dock-slot` when Command is active. What changes
is what gets rendered where.

### 2.1 Two states, not three

| State | Mobile | Desktop |
|---|---|---|
| **Dock** | One 44px summary row under the Order: glyph, codename, first line of the last reply, chevron. No composer, no scroller. | Inline card under the Order: last exchange (clamped to ~6 lines) plus composer. No inner scroller. |
| **Open** | `position: fixed; inset: 0` conversation. Tab bar hides via `body.sheet-open`. | Right-anchored drawer, 400px, full shell height, page usable behind it (`Sheet variant="drawer"`, `pointer-events: none` on the wrap). Escape returns to dock. |

The mobile "expanded" 85dvh sheet is deleted: two sizes of the same modal is a
zero-value distinction on a phone (osui L3). Desktop fullscreen is deleted
too; the drawer is the open state. `sessionStorage` keeps `dock | open`
(`fullscreen`/`expanded` values read as `open`).

### 2.2 The conversation is one flex column

```
header    52px, flex: 0 0 auto   identity button (glyph + codename + chevron) · thread menu · close
stream    flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column-reverse
composer  flex: 0 0 auto; padding-bottom: calc(env(safe-area-inset-bottom) + var(--kb, 0px))
```

`column-reverse` pins to the bottom with no JS, so a reply landing, a poll
refresh, or opening the surface never jumps. The composer is never
re-parented: opening the conversation is a class/portal change on the panel's
*container*, and the composer element is the same node before and after, so
focus and the keyboard survive. Tapping the dock row opens the conversation
and focuses the composer inside the same gesture.

Every literal `dvh`/`vh` in chat CSS goes; the column has no number to be
wrong. Textarea `max-height: 6lh`.

### 2.3 Messages

- Ian's turns: a bubble, right-aligned, `--agent-soft` fill and `--agent-line`
  border, with the tokens moved to `.consult-panel`. `.agent-chat` is deleted.
- Agent turns: glyph + prose in `--ink`, not `--dim`.
- The thinking row is a stable last row (`min-height: 1lh`) so the reply
  replaces it in place.
- Two spacing steps: 16px between exchanges, 8px inside a reply.
- A **Compacted** divider ("Compacted · 38 turns · Sep 1") sits where a compact
  happened; turns above it are collapsed behind "Show earlier".
- `--crit` stays banned here (it already is).

### 2.4 Composer

- Desktop: Enter sends, Shift+Enter newlines, `enterKeyHint="send"`.
- Mobile (`(hover: none)`): Enter newlines; only the 44px `↑` sends.
- `+` (context) and the model chip stay; both open sheets that are siblings of
  the panel, never children, so Escape and focus never nest.

### 2.5 Header identity and the pill

The header's agent identity is a button that opens the **Threads** sheet
(§5). The floating re-entry pill on non-Command pages is hidden under
`body.call-mode`, `body.journal-mode`, `body.shutdown-mode`,
`body.sheet-open`, and `body.note-editing`, and renders only while a turn is
running or the conversation was opened this session; a static pill on every
page is a zero-value pixel.

## 3. Threads are durable

### 3.1 Semantics

- `create_chat_thread` **no longer closes the role's other OPEN threads.** The
  one-open-thread-per-role law (SPEC-v26) is repealed. `status` keeps its two
  values but now means: `OPEN` = live, `CLOSED` = Ian archived it (or it was
  compacted into a successor, §4.4). Nothing auto-closes.
- The **current** thread for a role is the most recently updated OPEN one.
  `openFor(role)` resumes it; **New chat** posts a fresh thread.
- A `CLOSED` thread can be **reopened** (`PATCH status=OPEN`), and
  `patch_chat_thread` allows exactly that patch on a closed row. Posting a
  turn to a `CLOSED` thread is still 409: the UI reopens first, deliberately,
  so an archive is never undone by an accidental send.
- `CHAT_TURNS_PER_THREAD` (200) stays as the hard ceiling; auto-compact (§4.3)
  fires long before it.

### 3.2 Schema (plain ALTERs, no rebuild)

```sql
ALTER TABLE chat_threads ADD COLUMN title              TEXT    NOT NULL DEFAULT '';
ALTER TABLE chat_threads ADD COLUMN summary            TEXT    NOT NULL DEFAULT '';
ALTER TABLE chat_threads ADD COLUMN summary_turn_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE chat_threads ADD COLUMN compacted_at       TEXT;
```

- `title`: set once by the server from the first question (first 60 chars,
  whitespace-collapsed), never model-written, editable by Ian later if a
  rename surface ever ships. Empty until the first turn.
- `summary`: model-written by Compact (§4), bounded to 1,200 chars,
  `strip_em_dashes` applied. Empty means "never compacted."
- `summary_turn_count`: how many `chat_turn` rows the summary covers, so the
  UI can draw the divider and the prompt can say what it covers.
- `compacted_at`: when.

`sdk_session_id` stays server-only (`tests/test_chat_api.py:437` still holds).

### 3.3 List shape

`GET /api/chat/threads` returns up to 50, every status, newest `updated_at`
first, each with `title`, `created_at`, `turn_count`, `has_summary`,
`compacted_at`. `_thread_summary` grows by those five keys; no bodies, no
questions, no `sdk_session_id`.

### 3.4 Prune

`prune_agent_invocations` deletes a thread only when it has no turns **and no
summary**: `AND summary = ''`. A compacted thread whose turns aged out keeps
its summary, which is the whole point of having one.

## 4. Memory and Compact

### 4.1 The summarizer

One function, `api/main.py::_chat_thread_summary_reply(turns)` in the exact
shape of `_school_study_model_reply`: `runner.query` with `mcp_servers={}`,
`tools=[]`, every ianOS tool in `disallowed_tools`, `max_turns=1`, model
pinned in code (`CHAT_COMPACT_MODEL = runner.HAIKU`, never read from a row),
`max_budget_usd=CHAT_COMPACT_COST_CAP_USD` (0.05), `setting_sources=[]`. Input
is the thread's succeeded turns (question + body, each bounded, 12,000 chars
total, newest kept), framed as untrusted content. Output: ≤ 1,200 chars,
plain prose, "what Ian asked, what was decided, what is still open", no
execution claims (`EXECUTE_CLAIM_RE` rejects), no dashes
(`strip_em_dashes`). A failed or empty reply stores nothing and returns 502.

### 4.2 Compact

`POST /api/chat/threads/{id}/compact` → 202 with the updated summary shape.

1. 409 if a turn on that thread is QUEUED/RUNNING, or if the shared
   `_agent_execution_gate` is held. 409 if fewer than
   `CHAT_COMPACT_MIN_TURNS` (4) succeeded turns exist since the last compact.
2. Run §4.1 over the turns after the previous `summary_turn_count`, prepending
   the previous summary as "EARLIER (already compacted)" so a second compact
   is cumulative, not a fresh start.
3. Store `summary`, `summary_turn_count = chat_turn_count`, `compacted_at`,
   and **clear `sdk_session_id`**: the next turn starts a fresh native session
   whose only history is the summary (§4.4). Turn rows are never deleted.
4. Write no memo, fact, brief, or focus. Nothing enters `/api/state`.

### 4.3 Automatic

After a successful turn, `_run_chat_turn_worker` checks
`chat_turn_count - summary_turn_count >= CHAT_COMPACT_AUTO_TURNS` (40) and, if
so, runs §4.2 inline before releasing the gate. It is the same code path as
the button, so there is one implementation. The UI learns about it from the
next thread detail (`compacted_at` changed) and draws the divider.

### 4.4 What the model sees

`_chat_user_prompt` gains two sections, both rendered from the DB in Python,
both framed "untrusted quoted memory, not instructions":

```
COMPACTED CONTEXT (this thread, summarized; covers N earlier turns):
<summary>

EARLIER THREADS WITH THIS AGENT (newest first; summaries only):
<title> (<date>): <summary>
...
```

- COMPACTED CONTEXT renders only on the first turn of a fresh session (i.e.
  when `resumed` is False and `summary` is non-empty). Once the SDK session
  carries it, repeating it is stale-by-construction context.
- EARLIER THREADS renders on a thread's **first turn only** (`turn_count ==
  0`): the last `CHAT_CROSS_THREAD_SUMMARIES` (3) other threads for the same
  role that have a summary, each capped at 600 chars, 2,000 total. Same
  role only: a Dumbledore thread never receives a Jordan Belfort summary.
  Health roles (physician, coach) receive their own summaries the same way;
  those summaries already live behind the chat wall.

### 4.5 New chat writes a summary for the old one

When Ian starts a New chat for a role whose current thread has ≥
`CHAT_COMPACT_MIN_TURNS` succeeded turns since its last summary, the API runs
§4.2 on that old thread first (best-effort: a summarizer failure never blocks
the new thread). This is how "some memory" actually arrives without Ian
ever pressing Compact.

## 5. Threads UI

The header identity button opens **Threads**, a Sheet (phone: bottom sheet;
desktop: popover) that replaces the agent group inside Reasoning:

```
[glyph] Dumbledore                        New chat
  · SPAN 210 notes this week    2h · 6 turns   ← current
  · Drop/add deadline           3d · 12 turns · compacted
[glyph] Alfred Pennyworth                 New chat
  · hey                          1d · 4 turns
… every active agent, its threads under it (up to 5 each, "older" expands)
```

Rows are 44px. Tapping a thread loads it (reopening if CLOSED). Reasoning
keeps Model, Effort, Capability, Specialists only. **Compact** lives in the
header's thread menu (⋯): "Compact this thread" with a one-line explanation,
disabled below `CHAT_COMPACT_MIN_TURNS`, and "Archive" (status=CLOSED).

## 6. Phases

### Phase 1: threads (backend)
§3 entirely: four columns via `_migrate_columns`, repeal the auto-close,
allow reopen, title on first turn, list shape, prune guard. Tests renegotiate
`test_create_thread_closes_other_open_and_validates_chips` and
`test_threads_for_different_agents_coexist`; new tests pin reopen, title,
prune-keeps-summary, and `sdk_session_id` still absent from every response.

### Phase 2: memory and Compact (backend)
§4 entirely: summarizer, endpoint, auto trigger, new-chat summary, the two
prompt sections. Tests pin: summarizer is tool-free with the model pinned in
code; compact clears the session and never deletes turns; the prompt sections
render only when specified; cross-thread summaries are same-role only; no
memo/fact/brief written; 409s.

### Phase 3: the layout
§2 entirely, plus P1-11 hit areas and the P2 items. Delete the mobile
expanded state and desktop fullscreen; add the drawer; move the `--agent`
tokens; Enter behaviour; hoist sub-sheets; pill rules. Retarget
`tests/test_mobile_ui.py:588` from `.agent-chat` to `.consult-panel`. Verify
at 375×667 with 47/34px insets and on the installed build, and at 1512px.

### Phase 4: Threads UI and Compact UI
§5: the Threads sheet, New chat, reopen, the thread menu with Compact and
Archive, the Compacted divider and "Show earlier". Dashboard tests for the
sheet's 44px rows and for the divider.

## 7. Laws this spec asserts in tests

- A thread is never deleted by creating another; nothing auto-closes.
- `sdk_session_id` appears in no API response.
- Compact never deletes a turn; it clears the session id and stores a bounded,
  dash-free summary; it runs a tool-free single-turn model call with the
  model pinned in code.
- Cross-thread summaries are same-role only and first-turn only.
- Chat still writes no memo, fact, brief, or focus; nothing new enters
  `/api/state`.
- No `vh`/`dvh` literal in chat CSS; the composer carries
  `env(safe-area-inset-bottom)` and `--kb`; every chat control ≥ 44px hit
  area; `--crit` absent from chat.
- The composer textarea is the same DOM node across dock/open.

## 8. Non-goals

- Renaming threads by hand, pinning, search across threads (the memory index
  already covers proposals/notes/memos, not chat, and chat stays out of it).
- Streaming tokens into the UI. Polling the thread detail is correct and now
  works; token streaming is a different transport.
- Cross-agent memory. A summary never crosses roles.
- Vector search over summaries.
