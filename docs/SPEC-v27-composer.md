# SPEC v27: the composer

Status: **proposed**. Extends SPEC-v26 (Agent Chat as Command). Read
`.claude/skills/osui` before touching the surface and `.claude/skills/data`
before the source registry.

## 0. What is wrong today

SPEC-v26 shipped a working conversation with a developer's control panel
bolted under it: an `Options` button that unfolds four rows of chips. Every
control is visible at once or hidden at once, the model picker is three taps
deep, and Opus is not discoverable even though it has shipped since v26
phase 2. Ian asked for the ChatGPT shape, which is not decoration: it is a
composer where the message is the only thing on screen until you ask for
more, and where each control opens its own focused surface.

Three asks, in Ian's words: typing to Nick should look like ChatGPT; `+`
should pick sections; the model selector should choose agent, effort, and
reach Opus.

## 1. The shape

One pill. Inside it, left to right:

```
( + )  Message Nick Fury................  [ Sonnet · High ▾ ]  ( ↑ )
```

- **`+`** opens the Context sheet (§2). It carries a count badge when
  anything optional is on, so state is legible without opening it.
- **The field** grows to a cap, then scrolls. 16px, never smaller (osui L10).
- **Model chip** shows `model · effort` and opens the Reasoning sheet (§3).
  Always visible, unlike v26 where it hid unless non-default: this is the
  control Ian asked to reach, so it does not get to be invisible.
- **Send** is a 44px circle, disabled until there is text.

Everything else that lived in the v26 dock (chips, workflows, specialist
picker) moves inside one of the two sheets. The dock's resting state is one
row.

## 2. The Context sheet (`+`)

**Sources, not topics.** Every row grants real read tools. A row that
granted nothing would be a lie, so topics are not rows: in ianOS the way to
scope a question to school is to talk to the advisor, which the Reasoning
sheet already does. This is the honest reading of Ian's "sections" ask, and
the one that matches what the `+` does in the product he pointed at, where
the entries are capabilities and connectors rather than subjects.

| Row | Tools it grants | Gate |
|---|---|---|
| Money | `read_transactions`, `read_holdings` | a connected bank or brokerage |
| Mail | `read_mail` | a Gmail sync has landed |
| Calendar | `read_calendar` | a calendar sync has landed |
| Documents | `read_documents` | none |
| Web search | the built-in `WebSearch` | none, but see §5 |

Each row shows one of three states: **on**, **off**, or **not connected**
(which deep-links to the page that connects it and never silently grants).
The `connected != granted != synced` rule from v26 stands, and the
server-side refusal to grant an unconnected chip stands with it.

An agent's base readers are its identity, not a toggle. Fury reads goals,
memos, facts, focus, activity, health, notes, and the pipeline because he is
the chief of staff; the CFO does not, because he is not. Those never appear
as rows.

## 3. The Reasoning sheet (model chip)

One sheet, three groups, because they are one decision: who answers, with
what, and how hard.

- **Agent**: the active roster. Switching opens that agent's thread, which
  keeps its own history, model, and sources (v26 §6).
- **Model**: `haiku`, `sonnet`, `opus`, `fable`. Closed enum. Opus stops
  being a discovery problem: it is the third row of a sheet one tap away.
- **Effort**: `low`, `medium`, `high`, `max`. New. Maps to the SDK's
  `effort` option, which guides thinking depth. Default `high`, which is
  the SDK default. `xhigh` is deliberately not offered: it silently falls
  back on most models, so it would be a control that sometimes lies.

Effort is stored per thread beside the model (`chat_threads.effort`, CHECK
constrained, default `high`). Unknown values are 422, never coerced.

Specialist consultation keeps its v26 rules (2-3 roles, Haiku, the
2-or-turn-it-off hint) and moves into this sheet under the agent list,
since "who answers" is the question it belongs to.

## 4. Cost and quota

Subscription auth means no per-message dollar cost, so the enum stays open
to Opus. Quota is shared with Ian's coding sessions, so the defaults do the
discipline: Sonnet at `high` for chat, Haiku for specialist contributors,
and nothing auto-escalates. `max_budget_usd` is not wired; it measures
dollars, which are not the constraint here.

## 5. Web search: what it changes, and the walls

This is the only part of v27 that moves a security boundary, so it is
written down rather than shipped quietly.

**The law it touches.** "Zero built-in tools. Agents get `tools=[]`; the
only tools that exist are the in-process MCP `ianos` server." Web search is
a built-in, server-side tool. Turning it on for a thread means that thread's
`tools` list is no longer empty.

**What does not change.** Chat still writes nothing: no memo, no fact, no
brief, no proposal except the inert Inbox draft Ian files himself. Chat
still cannot send, pay, schedule, or post. So there is no outbound channel
for anything the model reads on the web to escape through. The realistic
failure is not exfiltration; it is a poisoned page talking the model into
bad advice, which Ian then reads.

**The walls.**

1. **Off by default, per thread, and never granted implicitly.** It is a
   source row like any other, and `chat_allow` still intersects everything
   with the read-only set.
2. **Web results are untrusted input.** The law layer already says tool
   results are data and not instructions; v27 names web content explicitly,
   because that is the case where it matters most.
3. **No fetch-any-URL.** Only the curated search tool, never `WebFetch`,
   so the model cannot be steered into pulling an arbitrary address.
4. **Say where a claim came from.** A reply mixing Ian's records with the
   open web must attribute, so he can tell which is which. The evidence
   line gains a `Web` label when the tool ran.
5. **Private data does not become a query.** The prompt forbids putting
   balances, account numbers, or personal facts into a search string.

**Honest residual risk.** Search terms leave the machine when the tool is
on. That is the trade for the feature, it is off unless Ian turns it on
per thread, and it is the reason this section exists.

## 6. Data and API

```sql
ALTER TABLE chat_threads ADD COLUMN effort TEXT NOT NULL DEFAULT 'high';
```

CHECK cannot be added by ALTER, so effort is validated at the API boundary
against a closed set, matching how `role` is handled in v26.

`CHAT_SOURCES` replaces `CHAT_CHIPS` in `runner.py`, keeping the same
shape (id, label, tools, connect page, copy) plus `kind` (`tool` or
`builtin`) so the runner knows whether a granted source belongs in the MCP
allowlist or in `tools`. `chat_allow()` returns MCP tool names as today;
a new `chat_builtins()` returns the built-in list, so the read-only
intersection is untouched by the addition.

`PATCH /api/chat/threads/{id}` accepts `effort`. `GET` projections carry
`effort` beside `model`.

## 7. UI rules that bind

- The dock's resting state is one row; nothing else is visible until a
  sheet is opened (osui L3: no control earns permanent pixels).
- Both sheets are the existing bottom-sheet pattern (portal, backdrop,
  focus trap, Escape), so there is one sheet implementation, not three.
- The `+` badge counts granted optional sources; zero renders nothing.
- Sheets are scrollable and never taller than the visible viewport minus
  the keyboard inset (`--kb`, SPEC-v26 fix).
- `--crit` stays banned on this surface.

## 8. Tests

- `effort` round-trips, unknown values are 422, and the default is `high`.
- A granted source appears in the allowlist; an ungranted one does not;
  writers never appear regardless of which sources are on.
- Web search is absent from `chat_allow` (it is not an MCP tool) and
  present in `chat_builtins` only when granted.
- The composer's resting state renders one row; the model chip is always
  present.
- The persona eval gains a probe: with web search off, a question needing
  the open web is answered with "no data" rather than invention.

## Considered and cut

- **Topic chips (School, Body, Partner).** A chip that grants no tool is
  decoration that reads like access. Scoping to a subject is what choosing
  an agent already does, and doing it twice in two different ways would
  make neither obvious.
- **`WebFetch`.** Arbitrary URL retrieval turns a curated search into a
  general fetch primitive pointed at whatever a page suggests next.
- **`xhigh` effort.** Falls back silently on most models; a control that
  quietly does nothing is worse than one that is absent.
- **File and image upload in `+`.** ianOS has no vision path and the
  journal already owns media. Nothing would consume the file.
- **Auto-escalating effort on hard questions.** Guessing when to spend
  more of a shared quota is exactly the kind of invisible decision this
  product makes Ian's instead.
