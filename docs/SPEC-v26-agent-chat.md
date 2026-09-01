# SPEC v26: Agent Chat, the OS you talk to

Status: **proposed**. Supersedes the product stance of SPEC-v25 (daytime
chat behind More) while keeping its security architecture. Read
`.claude/skills/data` and `.claude/skills/osui` before implementing.

## 0. Why v25's stance is being reversed

SPEC-v25 shipped a consult booth: structured verdict replies, 60s/15s
cooldowns, one Chief, behind More. One session of real use falsified the
premise. Ian said "hey" and got a schema failure. The consult framing
assumed chat was an occasional escalation from the dashboard; actual
desire is the inverse: conversation as the primary interface, dashboard
as the escalation.

Second falsified premise: cost. v25's Haiku-everywhere discipline and
cooldowns were metered-API defenses. This install authenticates with
`CLAUDE_CODE_OAUTH_TOKEN` (subscription); marginal dollar cost of a chat
turn is $0. Verified empirically: `claude-haiku-4-5`, `claude-sonnet-5`,
`claude-opus-5`, and `claude-fable-5` all run under the current plan.
The real budget is plan quota shared with Ian's coding sessions, which is
a softer constraint and is handled by model defaults, not cooldowns.

What v25 got right and v26 keeps unchanged: the read-only runner
boundary, chip gating, thread/turn data model, the privacy walls, the
`/api/state` exclusion, prompt-injection posture, and file-to-Inbox as
the only path from talk to action.

## 1. Product decisions (locked with Ian, 2026-08-17)

1. **Chat becomes the Command home surface.** Opening ianOS = talking to
   your chief of staff. The Day Command sentence stays pinned on top.
   The five-tab law survives: chat took no slot.
2. **The feature is called Agent Chat.** Fury is who greets you, not the
   feature name.
3. **Hybrid replies.** Conversational plain text by default; a reply MAY
   carry one structured verdict block that the UI renders as a card. The
   JSON-only reply contract dies.
4. **Any agent per thread, Fury default.** A thread is bound to one role
   at creation. Each role keeps exactly its own interactive read
   allowlist.
5. **Cooldowns die.** Concurrency is guarded by correctness (one in
   flight), not by timers.
6. **Model picker is a closed enum of four:** `claude-haiku-4-5`,
   `claude-sonnet-5`, `claude-opus-5`, `claude-fable-5`. Default
   `claude-sonnet-5`. Unknown strings stay 422. Specialist contributors
   stay Haiku (quota discipline).
7. **Fury's persona is a first-class spec artifact**: witty in Ian's
   casual register, serious in his serious one, attention-literate delivery,
   structurally not a yes-man, and grounded in a three-layer knowledge
   stack (dossier, product manual, live state).

## 2. Laws

1. **Chat reads, Ian acts.** No writer tool can appear in any chat
   allowlist; the `chat_allow`-style intersection with `READ_ONLY_TOOLS`
   is mandatory for every role. Filing a draft to Inbox remains the only
   write, and approval still does not send.
2. **The journal stays invisible.** "Knows all about Ian" has exactly one
   deliberate hole and this is it. Counts only, never words. The
   existing sentinel tests must keep passing unmodified.
3. **Chat content never enters `/api/state`.** Unchanged from v25; the
   marker-string test stays.
4. **Grounding survives the schema's death.** Numbers and personal facts
   must come from tool output or the injected live-state block in the
   current conversation; otherwise the reply says "no data" or `-`. The
   enforcement moves from output schema to prompt law plus the existing
   evidence attachment (server-recorded reads only).
5. **Persona is layered, never merged.** Every chat system prompt is
   LAW LAYER (identical for all roles: boundaries, grounding, injection
   posture, execution-claim ban) + PERSONA LAYER (per role). Persona text
   can never weaken a law because laws are appended last and say so.
6. **A role's chat allowlist is its interactive allowlist.**
   `interactive_allow(role)` intersected with granted chips' tools where
   chip-gated. No new tools are granted by v26.
7. **Register asymmetry.** When Fury cannot tell if Ian is being casual
   or serious, he defaults to serious. Misreading serious as casual
   costs more than the reverse. This is prompt law, and the eval in
   §8 tests it.

## 3. Reply contract (hybrid)

The model replies in plain text (markdown subset). Optionally, it may end
with exactly one block:

```
<verdict>{"verdict": "...", "next_action": "...", "draft": {...}}</verdict>
```

- `verdict` <= 160 chars, `next_action` <= 200 chars or "-", `draft`
  follows the existing `validate_draft_attachment` shapes. All optional
  keys, closed set, fail-closed parsing: a malformed block is stripped
  and logged, never fatal to the turn.
- The conversational text above the block is the answer. `EXECUTE_CLAIM_RE`
  still runs against the full text; a claim of execution fails the turn
  (this law outranks conversational tone).
- `validate_chat_reply` is rewritten to: strip controls, cap total length
  (12,000 chars stored), extract the optional verdict block, run the
  execution-claim ban, filter `missing_access` against non-granted chips
  as today. `invalid_reply` now means "execution claim or oversized",
  not "wasn't JSON".
- Storage: `answer` holds the conversational text; the verdict block is
  stored in the existing structured columns/JSON the same way v25 stored
  parsed fields, so Inbox filing is unchanged.

## 4. Knowledge stack (what "knows all about me" means)

Three layers, injected server-side, model does no date math (the
`build_user_prompt` precedent):

1. **Dossier** (static, versioned): `agents/dossier.md`, markdown, single
   source of truth about Ian: identity, Clockwork, Gies, quotas,
   deadlines, Partner, communication preferences. Injected into EVERY
   role's chat prompt. Editing the dossier is editing markdown; no code
   change. The dossier states its own last-updated date so the model can
   say "as of".
2. **Product manual** (static, generated): a compact block describing
   ianOS surfaces (the five tabs, what is behind More), the 15 agents
   with codename and beat, and what chat can and cannot do. Generated at
   prompt-build time from `core/roles.py` and a hand-written surface map
   so it cannot drift from the real roster.
3. **Live state** (dynamic, per turn, pure Python): today's Day Command
   sentence, gym streak state, checking balance + runway, pending
   proposal count, today's plan blocks, days to move-in. Reuses existing
   helpers (`latest_brief`, `gym_streak_state`, `checking_balance`,
   `metrics.finance_state`). Computed in `build_chat_user_prompt`, never
   left to tools, so "how am I doing" costs zero tool calls.

`read_facts` remains the long-tail memory on top (role-domain scoped as
always). Layer 3 respects the same walls as `/api/state`: nothing
journal-derived beyond the existing counts signal, no consent data, no
invocation bodies.

## 5. Persona layer

### 5.1 Fury (default thread)

The persona text below is normative; implementation copies it into the
persona layer for role `chief` in chat mode. (Law layer is appended after
it and wins on conflict.)

- Identity: chief of staff, dry, seen everything twice. Wit is
  register-matched, not constant.
- **Reading the room:** joking Ian gets actual banter; a real question
  gets the answer first and at most one line of wit riding along;
  stressed or crisis Ian gets zero jokes and all signal; self-critical
  Ian gets neither jokes nor pep talk, just facts and the smallest next
  step. Unknown register defaults to serious (law 7).
- **attention-literate delivery:** lead with the answer; default short and
  expand willingly on request; one priority at a time; numbers first
  when numbers exist; never scold, a missed day is a fact not a flaw;
  match register ("hey" gets a greeting, with one urgent line appended
  only if something is actually on fire); no padding, no summarizing Ian
  back to himself.
- **Not a yes-man:** wrong-on-facts is said in the first sentence with
  the number; plan holes are named before helping; bad premises are
  corrected before answering; three tiers with different behavior
  (data-wrong: plain; judgment-risk: once, labeled, then help anyway;
  taste: defer). Flag once, then execute: Ian is the CEO. Praise only
  when earned and specific.
- **Knowledge honesty:** dossier can be stale, live state is current,
  everything else needs a tool call. Knowing a lot is not a license to
  guess the rest.

### 5.2 Other roles

Each role file (`agents/roles/<id>.md`) gains an optional `## Chat`
section: 5-15 lines of voice in the same shape (register rules, beat,
one-line disagreement stance). Missing section = a generated neutral
persona naming the role's beat. The dossier and manual inject for every
role; live state injects for every role; allowlists stay per-role.

## 6. API and data changes

- `chat_threads.role TEXT NOT NULL DEFAULT 'chief'` (migration guard,
  CHECK against canonical role at the API layer, not SQL). Thread
  creation accepts `role`; 422 on unknown/inactive. Existing threads
  read as chief.
- Model enum widened to the four models in `db.CHAT_MODELS` and
  `runner.CHAT_MODELS`. Default `claude-sonnet-5`. Prefs unchanged
  otherwise.
- **Cooldowns:** `_CHAT_FOLLOWUP_COOLDOWN_SEC` and the 60s first-turn
  check are deleted for chat turns. Concurrency guard: 409 while a turn
  in the same thread is QUEUED/RUNNING; the global `AgentExecutionGate`
  stays (correctness with the nightly run, not cost).
- **Retention:** chat threads/turns prune at 30 days (up from 7); Ask
  and inspect stay at 7. A Jarvis whose memory resets weekly reads as
  broken; durable memory still belongs to `facts`, not chat.
- Turn cap per thread rises to 200; prior-turn context injection windows
  the last 12 turns (verdicts + bodies truncated) rather than 4.
- `GET /api/chat/threads` gains `role` in its projection for the thread
  list UI.
- Server-side chip law hardening (review finding): PATCH rejects
  granting a chip whose `chat_chip_connected()` is false with 422, so
  the "not connected does not grant" rule stops living only in the UI.

## 7. UI (osui-bound; author at 375px first)

- **Command page = Agent Chat.** Pinned header: Day Command sentence
  (tap opens the old brief detail) + a one-line status strip. Below:
  the conversation, newest at bottom, single scroller. Composer docked
  above the tab bar in the thumb zone, safe-area respected, 16px font
  (no iOS zoom-jack).
- **Conversation rendering:** user turns right-aligned quiet bubbles;
  agent turns left with the role glyph, plain typography on the page
  surface (Claude-style, not SMS-style chrome). Markdown subset: bold,
  lists, inline code, links. A reply carrying a verdict block renders it
  as the existing card component inside the conversation flow, with
  File-to-Inbox on the card.
- **Thread/agent switching:** a compact header control opens a sheet
  listing threads grouped by agent, plus "New thread with..." over the
  roster (glyphs from `lib/agents.js`, the single source). Fury thread
  is created and opened by default on first visit.
- **Model picker** moves into the composer's overflow, four options,
  current one shown as a small chip only when not the default (L3: no
  zero-value pixels).
- **Old Command content:** the ActionStack/pillar material moves behind
  a `Today` disclosure under the status strip. Nothing is deleted;
  Command stops being a grid with a chat bolted on and becomes a chat
  with the day pinned on top.
- **Waiting state:** typing indicator on the agent side; if SSE/streaming
  is not implemented in phase 1, poll fast (the existing
  `invocationPollDelay` curve) and render the indicator; streaming is a
  phase 4 upgrade, not a blocker.
- `#chat` redirects to `#home`. More-sheet entry and Cmd+K entries
  update. The Fury glyph row in More goes away (L3).
- No `--crit` anywhere in the conversation surface. A failed turn gets a
  quiet retry affordance, not a red wall.

## 8. Persona eval (new, cheap, honest)

A tiny offline eval script (`tests/eval_chat_persona.py`, marked slow,
run manually) sends ~10 fixed probes through `run_chat_turn` against a
seeded DB and asserts mechanical proxies:

- "hey" -> reply under 200 chars, no verdict block, no tool calls.
- "how am I doing?" -> mentions a number from live state, no invented
  sources.
- A question with a false premise (seeded wrong balance claim) -> first
  sentence contradicts it.
- "give me the long version" after a short answer -> longer reply.
- A serious message (seeded crisis phrasing) -> no humor markers.

These are heuristics, not proofs; they catch regressions in the prompt,
which is now a load-bearing artifact.

## 9. What dies, what is rewritten (SPEC-v25 delta)

Dies: JSON-only reply contract and its validator branches, verdict-card
-only turn rendering, both cooldown constants for chat, the More-sheet
placement, `Ask Fury` footer copy, the fixed Haiku/Sonnet two-model enum.

Rewritten tests: `test_chat_runner.py` reply-shape tests target the
hybrid contract; `test_chat_api.py` cooldown tests become concurrency
tests; `test_mobile_ui.py` chat placement tests assert the Command
takeover and thumb-zone composer instead of behind-More.

Kept verbatim: state-exclusion test, journal sentinel tests, chip gating
tests, cascade/prune tests (with the 30-day constant), injection-posture
tests, execution-claim ban tests.

Also fixed in passing (v25 review findings): specialist picker enforces
2-3 before send with a visible hint; `refreshMoney` clears when the
Money chip is revoked; `submit()` copies its workflows argument.

## 10. Phases

1. **Contract + persona.** Hybrid validator, law/persona layer split,
   Fury persona, dossier file, product manual generator, live-state
   injection. Ask/inspect/rooms untouched. Ship with old UI still
   rendering `answer` as text: immediately makes "hey" work.
2. **Threads + models.** `chat_threads.role`, four-model enum, cooldown
   removal, retention/window changes, chip-grant hardening.
3. **The Command takeover.** New conversation UI, thread/agent sheet,
   Today disclosure, redirects. The visible payoff.
4. **Polish.** Per-role `## Chat` personas for the full roster, persona
   eval, streaming/SSE exploration, review-finding UI fixes if not
   already landed in 2-3.

Each phase ships alone and leaves every wall test green.

## Considered and cut

- **True token streaming in phase 1.** The worker/poll architecture is
  load-bearing (durable invocations, crash recovery). Fast polling with
  a typing indicator gets 90% of the feel; SSE is worth doing only
  after the surface proves itself.
- **Letting chat write facts ("remember this").** Tempting, violates the
  single-writer law and the verified=0 trust model. The existing path
  (file a draft, approve on Inbox) already covers it; a lighter
  "remember" flow can be its own spec if the friction proves real.
- **A free-text model field.** Quota is shared with coding sessions;
  a closed enum keeps a fat-fingered model string from becoming a
  silent expensive default. Widening the enum is a one-line change
  when new models ship.
- **Dropping the Fury persona for a neutral assistant.** Ian chose the
  roster identity; the persona layer makes it cheap and swappable
  rather than baked in.
