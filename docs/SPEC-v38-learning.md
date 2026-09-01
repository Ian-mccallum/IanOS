# SPEC v38: Learning

**Status:** QUEUED. No implementation is authorized by this document alone.

**Date:** 2026-09-01
**Owner:** Ian
**Audience:** Ian and the implementing agent
**Decision:** Give Ian's self-directed skill-building (case interviews, AI,
Python were his own examples) the same product treatment School already has
for coursework: a dedicated pillar, a daily practice loop, a bending streak,
and an 11th nightly agent whose whole job is picking tomorrow's rep and
knowing the topics well enough to write one. School stays school; this is
everything Ian decided to get better at because he wanted to, not because a
syllabus said so.

---

## 0. Executive decision

School (SPEC-v36) answers "what does UIUC require." Nothing in ianOS answers
"what am I trying to get good at on my own." That gap is real: Ian named
three live examples unprompted (case interviews, AI, Python) and none of them
belong on a Canvas-driven surface built around due dates and grade
categories. Coursework and self-directed practice are different shapes of
obligation — one has a deadline someone else set, the other only survives if
showing up costs nothing and misses cost nothing either.

Everything this spec needs already exists in the codebase in a different
shape:

| Need | Existing precedent |
|---|---|
| A miss that doesn't reset progress | `core/streaks.py`'s weekly rest-day allowance (SPEC-v34, superseding the original SPEC-v6 stool-bank), applied to the gym streak today |
| A domain that can be reshaped without touching shared migrations | `core/school.py`'s `SCHOOL_SCHEMA` + `ensure_schema(conn)` (SPEC-v36) |
| A pillar that isn't a `goals.domain` value | `core/pillars.py`'s `is_partner_goal` split of `personal` into partner vs life |
| An agent acting immediately instead of only proposing | `core/acts.py`'s Ring 1, specifically `gym.confirm` (SPEC-v37 §4) |
| A chat thread writing directly instead of proposing | `chat_write_allow`'s six-tool instant-write family (SPEC-v29/v37) |
| An interactive, in-app session with an agent | the consult surface: dock/expanded/fullscreen, native session resume (SPEC-v37 §7) |

This spec is deliberately a composition of those six things under a new name,
not a new interaction engine. The only genuinely new code is a schema
(`core/learning.py`), one Ring 1 act, one instant-write tool, one role file,
and a page. Everything that moves a conversation forward — the daily
practice session, the topic-onboarding chat — is an ordinary chat thread
scoped to the new role, exactly as SPEC-v37 built it.

---

## 1. The agent: Mr. Miyagi (`tutor`)

An 11th nightly role, following CLAUDE.md's unchanged three-edit process
(role file, one `ALLOWLISTS` entry, one `SEQUENCE` slot). Not folded into an
existing role: Rocky Balboa (`coach`) already owns fitness repetition and a
tone built for a corner-man, not a mentor who has to hold a *working profile*
of a dozen different skills and ask good clarifying questions. Fitness is one
domain with one metric (did you train). Learning is N domains, each with its
own current level, its own definition of "better," and its own daily
exercise — that needs a mentor archetype, not a corner-man.

**Codename: Mr. Miyagi. Role id: `tutor`.** Patient, practice-through-
repetition, teaches by handing over one small concrete thing to do rather
than a lecture — it is the right archetype for "one exercise a day, indefinitely,
across topics you chose." This is a naming call, not a structural one: if Ian
doesn't want it, everything below still holds with `codename:` changed in
`agents/roles/tutor.md` and `ROLE_GLYPHS`/`ROLE_COLORS` in
`dashboard/src/lib/agents.js`. The role id `tutor` is the one thing that must
not change once shipped (CLAUDE.md: role ids are foreign keys in memos,
proposals, and facts history).

Illustrative, swappable choices for `dashboard/src/lib/agents.js`: glyph `✎`
(unused in `ROLE_GLYPHS` today — a pencil reads as practice/study without
colliding with School's `△` or Coach's fist-adjacent territory), colour
`#2dd4bf` (teal, unused in `ROLE_COLORS`, deliberately calmer than Coach's
`#fca5a5` so the two don't read as the same energy on the Roster page).

- **Tier:** `daily` (Ian's explicit call — this runs every night like
  `scout`/`cfo`/`steward`, not on a weekly cadence like `coach`/`lovebird`).
- **Domain:** `health` is wrong (that's House/Rocky's wall) and there is no
  `learning` domain (§6 explains why one is never added). The role file's
  `domains:` frontmatter reads `personal`, matching where its goals/facts
  actually live.
- **`SEQUENCE`** (`core/roles.py`): inserted among the daily producers, before
  `chief`. Current sequence is
  `["scout", "cfo", "wealth", "physician", "coach", "steward", "lovebird", "watchdog", "counsel", "chief"]`;
  `tutor` goes after `watchdog` (both are "growth" agents with no Ring 1
  overlap) and before `counsel`:
  `[..., "watchdog", "tutor", "counsel", "chief"]`.

---

## 2. Data: `core/learning.py`

Its own file, its own `LEARNING_SCHEMA` string, its own `ensure_schema(conn)`
— byte-for-byte the School precedent (`core/school.py`'s `SCHOOL_SCHEMA` +
`ensure_schema`, called once from `agents/runner.py` alongside
`school.ensure_schema(conn)`). The reasoning is the same reasoning SPEC-v36
gave for School: this domain should be reshapeable — new topic states, a
richer session shape, whatever a semester of real use surfaces — without
touching `core/db.py`'s migration list or risking money, leads, or journal
tables in the same diff.

Three tables (literal SQL in §10):

### 2.1 `learning_topics`

One row per thing Ian wants to get better at. `status` starts `clarifying`
and only becomes `active` through `chat_write_learning_profile` (§4) — never
automatically, never by a nightly write. A `clarifying` topic generates no
daily tasks; `write_learning_task` (§3.3) only ever selects from `active`
rows. `archived` exists for the obvious case (Ian's actually done with a
topic, or it turned out to be School's job after all) and is filtered out of
selection the same way `goals.archived` is filtered out of `all_goals()`
(SPEC-v30) — never deleted, so its history stays attached to the same id.

`profile` is prose, not JSON. That mirrors Notes' choice of "a narrow
agent-readable Markdown dialect" over a structured shape (CLAUDE.md, School
section) for the identical reason: the only reader of this field is the
tutor's own nightly prompt, never a machine that needs to parse it, so
structure would be pure overhead. It holds whatever the onboarding
conversation established — current level, what "better" means to Ian for
this specific topic, what he's already tried — written by the model in its
own words at the end of that thread, not filled in by a form.

`origin` (`user` | `agent_proposed`) records *whose idea the name was*, not
whether Ian consented — he always runs the same clarification pass regardless
(§5). A topic is `user` when Ian typed a fresh name into "Add a topic." It is
`agent_proposed` only when he started that same flow from a suggestion Mr.
Miyagi surfaced via an ordinary `create_proposal` (§5) — the UI prefills the
name field from the proposal's `action` text, but the *row* still isn't
created until Ian taps through, and the clarification conversation still has
to run before the topic goes live. `origin` is provenance for the topic card
("suggested by Mr. Miyagi") and for a future Roster-style track record, not a
bypass of the onboarding gate.

`thread_id` links to the `chat_threads` row that ran (or is running) the
onboarding clarification. It is nullable and set once the thread opens, not
before — a topic can exist for a few seconds in `clarifying` state with no
thread yet, between "Ian typed a name" and "the consult dock finished
opening," and that's fine, it just isn't selectable for tasks in either
state.

### 2.2 `learning_sessions`

One row per calendar day, enforced by `date UNIQUE`: exactly one featured
task exists system-wide on any given day, never N parallel obligations
across topics. This is the load-bearing product decision from Ian's answer
to "daily engine" — both paths (the generated task, and Ian logging his own
initiative) resolve to *this one row*, not to separate per-topic rows, so
"did I do something today" stays one yes/no fact the streak can read, exactly
like the gym streak reads one `gym_confirmed` boolean per day regardless of
which of the three trained disciplines it was.

`thread_id` is NULL until Ian actually opens the day's practice session —
lazy creation, matching how a consult thread is only created when a consult
actually starts (SPEC-v37 §7.3), never speculatively the night before just
because the row that will hold its id already exists.

`task_prompt` is empty on a row created by Ian's own "I did something today"
log (§3.2) rather than by the nightly write. `agent_note` is a short free-text
line closing out the day — either the tutor's own reflection when a practice
thread wraps, or Ian's one-line note when he self-logs outside material.
Either way it is prose the tutor can read back next time it writes a task for
that topic, never a score.

### 2.3 `learning_streak_events`

A **structural mirror of `streak_events`**, and a **separate table with
separate rows** — this is Ian's explicit cadence-law answer, and it matters
enough to say twice: this table shares no row, no foreign key, and no code
path with the gym streak. `core/streaks.py`'s own docstring is explicit that
it "never imports db" and its SQL names the `streak_events` table directly
in every query; parametrizing it to accept an arbitrary table name would mean
building its `SELECT`/`INSERT` strings by interpolating a table identifier,
which is exactly the footgun this codebase avoids everywhere else it touches
SQL. So `core/learning.py` gets its **own** copies of the same four pure
functions — `sync_confirms`, `compute`, `apply_grace`, `last_grace_or_reset`
— reading and writing `learning_sessions`/`learning_streak_events` instead of
`health_daily`/`streak_events`. It is ~120 lines of already-proven logic
duplicated once, which is a smaller risk than coupling two independent
behavior domains (gym health, self-directed learning) through one shared
low-level function whose parameters (`track_days_per_week`,
`rest_days_per_week`) might need to diverge for good reason later (see below).

> **Law B1 — A mirror is a copy, never a shared row.**
> `learning_streak_events` and `streak_events` are structurally identical and
> operationally unrelated. No code path may write to one from logic that
> reads the other, and no test may assert one from the other's fixtures.

**Note the SPEC-v6 → SPEC-v34 history**, since CLAUDE.md and this codebase
still reference SPEC-v6 by name: the mechanic that actually ships in
`core/streaks.py` **today** is not SPEC-v6's original "5 consecutive confirms
banks 1 stool, cap 2" rule — that rule never forgave a real, gap-filled
attendance history, because a genuine confirm log with gaps never reaches 5
*consecutive* days, so the bank sits at 0 forever. SPEC-v34 replaced it with
a **weekly rest-day allowance that refills every calendar week** regardless
of the week before. Learning mirrors the mechanic that is *actually live* —
SPEC-v34's version — not the superseded SPEC-v6 one. Concretely: a miss on a
tracked day spends one of that week's rest days if any remain (writes
`grace`, streak survives); once the week's allowance is spent, a further miss
writes `reset`. `apply_grace` is the nightly run's job alone, exactly as it
is for the gym, and is idempotent for the same reason (a day that already
has an event is left untouched).

Two parameters `core/streaks.py` threads through from `gym_prefs` have no
equivalent prefs table here — v1 does not give Learning its own configurable
settings row (that would be a fourth table nobody asked for). Instead
`core/learning.py` fixes them as module constants: **every calendar day is
tracked** (no weekday exception — Learning has no "day off" the way the gym's
5-day mode treats weekends, since a case-interview drill on a Saturday is as
real as one on a Tuesday), and **`rest_days_per_week = 2`**, matching the
gym's own default so the two streaks *feel* the same without sharing state.
Making this Ian-configurable later is a small, obvious follow-up, not a
blocker for v1.

---

## 3. Ring 1: `learning.confirm`

Mirrors `gym.confirm` in `core/acts.py` exactly, including its scope: today
only, marks the day's row done, writes exactly one `confirm` streak event,
and **never** writes `grace` or `reset` — that split stays the nightly run's
alone, unchanged from the gym precedent.

### 3.1 The act

```python
# core/acts.py
RING1_ACTS = (..., "learning.confirm")          # 14th entry

RING1_GRANTS: dict[str, frozenset[str]] = {
    ...,
    "tutor": frozenset({"learning.confirm"}),   # mirrors coach: frozenset({"gym.confirm"})
}

def learning_confirm(conn, *, role: str, plane: str, thread_id: int | None) -> dict:
    """Today only; never writes grace or reset. Requires today's session row
    to already exist (created by write_learning_task the night before, or by
    Ian's own dashboard confirm -- see 3.2)."""
    _require(role, "learning.confirm")
    today = db.today()
    row = learning.get_session(conn, today)
    if row is None:
        raise ActError("learning.confirm: no session for today yet")
    return _apply(
        conn, role=role, act="learning.confirm", plane=plane, thread_id=thread_id,
        target_kind="learning_session", target_id=today,
        summary=f"{role} confirmed today's learning session.",
        inverse={"act": "learning.confirm", "day": today},
        write=lambda: learning.confirm_session(conn, today, commit=False),
    )
```

Registered in `agents/runner.py` next to `act_gym_confirm`, granted to
`tutor` only (mirroring `HEALTH_GENERIC_WRITERS`'s narrow addition of
`act_gym_confirm` to `coach` alone): this is the tool Mr. Miyagi calls from
inside the daily practice thread once Ian has actually worked the exercise,
not something any other role can reach.

### 3.2 Ian's own dashboard-side confirm

`gym.confirm` has a second entry point that never touches `core/acts.py` at
all: `POST /api/gym/confirm` calls `db.confirm_gym` directly, writes an
`ian`-authored memo by hand, and returns the fresh streak state — because
Ian tapping his own confirm button isn't an agent acting, so it has no
business going through Ring 1's role-eligibility check or receipt machinery.
Learning needs the identical second door, because Ian's decision #3 ("bring
his own material to log against a topic") is exactly this case: work he did
with no thread open at all.

`POST /api/learning/sessions/today/confirm` (`{topic_id?: int, note?: str}`)
calls `core/learning.py::confirm_session()` directly:

- If today's row already exists (the nightly-generated task), it marks it
  done, optionally attaching `note` to `agent_note`.
- If no row exists yet — no active topics were live when the nightly last
  ran, or Ian is getting ahead of the schedule — it **creates** today's row
  with the given `topic_id` (required in that case; the endpoint 400s
  without one) and `note` as `agent_note`, `task_prompt` left empty to mark
  it as self-directed rather than generated.

Either way it writes the `confirm` streak event and drops an `ian`-authored
memo (`db.add_memo(conn, "ian", "learning confirmed", ...)`), the same shape
as `/api/gym/confirm`'s, so tomorrow night's `read_learning` (§5.2) sees what
Ian actually did without a thread ever having existed for it.

---

## 4. The instant-write exception: `chat_write_learning_profile`

The SPEC-v29 six-domain instant-write family (`chat_write_goal`,
`chat_write_plan_block`, `chat_write_note`, `chat_confirm_gym`,
`chat_write_partner_task`, `write_fact`) has one property this tool has to
break: `chat_write_allow`'s docstring is explicit that "every role that can
open a chat thread at all gets the same six," because a goal write or a
plan-block write isn't specialist-scoped. A `profile` write is different —
it flips a `learning_topics` row from `clarifying` to `active`, which is a
decision that only makes sense inside the one conversation built to make it.
A physician thread or a cfo thread has no business ending a Learning
onboarding.

So this is the family's **first role-scoped member**, and `chat_write_allow`
gains its first branch beyond the existing health blanket-deny:

```python
INSTANT_WRITE_TOOLS = {
    "chat_write_goal", "chat_write_plan_block", "chat_write_note",
    "chat_confirm_gym", "chat_write_partner_task", "write_fact",
    "chat_write_learning_profile",             # new; role-scoped, see below
}

def chat_write_allow(role: str) -> set[str]:
    if role not in ALLOWLISTS:
        role = "chief"
    if role in HEALTH_AGENT_ROLES:
        return set()
    allowed = set(INSTANT_WRITE_TOOLS) - {"chat_write_learning_profile"}
    if role == "tutor":
        allowed.add("chat_write_learning_profile")
    return allowed
```

```python
@tool("chat_write_learning_profile",
      "Instant-write (tutor-only): save the clarified working profile for a "
      "learning topic. If the topic is still 'clarifying', flips it to "
      "'active' so it becomes eligible for tomorrow's task. If it is already "
      "'active', just updates the profile text.",
      {"topic_id": int, "profile": str})
async def chat_write_learning_profile(args): ...
```

This is the **one** thing an onboarding thread can do beyond ordinary
conversation. Everything else in that thread — the clarifying questions
about current level, what "better" means, what Ian's already tried — is
plain talk, same as any other consult.

> **Law B2 — Onboarding is inert until the profile lands.**
> A `clarifying` topic generates no task, appears on no rotation, and blocks
> nothing. The only thing that moves it to `active` is a model, inside a
> `tutor`-role thread, calling this one tool. There is no timer, no default,
> and no path that flips the status without it.

---

## 5. Topic management and the nightly write

### 5.1 Onboarding: Ian types a name, the tutor asks before it acts

"Add a topic" (§7) takes a topic name, creates a `learning_topics` row
(`status='clarifying'`, `origin='user'`, `profile=''`), and opens a consult
thread scoped to `tutor`, seeded via the same `consultRequest` mechanism
SPEC-v37 §7.3 built for Inspect (`{role: 'tutor', seedText: "I want to get
better at ${name}.", view: 'expanded'}`) — no second seeding path, the exact
one already shipped. The role file (§1, and see `agents/roles/coach.md` for
the shape a role file's `## Chat` section takes) instructs Mr. Miyagi to ask
before generating anything: current level, what "better" actually means to
Ian for this specific thing, what he's already tried. When he's satisfied it
has enough to work from, it calls `chat_write_learning_profile` and says so
plainly — the topic is live, tomorrow's rotation can pick it.

### 5.2 `read_learning` (Ring 0)

```python
@tool("read_learning",
      "Active learning topics with their working profile, recent session "
      "history, and current streak state. Args: none.", {})
async def read_learning(args): ...
```

Precomputed in Python, the law every nightly read tool follows ("date math
… precomputed in Python, not left to the model"): active topics (id, name,
profile), the last 14 days of `learning_sessions` (date, topic, status,
whether it was generated or self-logged), and `learning.compute(conn)`'s
streak/rest-days-remaining state. Allowlisted to `tutor` (and, for the same
reason `chief` reads `read_school`'s aggregate view to protect the daily
plan, optionally `chief` gets a thin read for the Day Command — see §7.5 of
SPEC-v37's live-state precedent). Clarifying topics are visible too, so the
tutor doesn't lose track of an onboarding still in progress.

### 5.3 `write_learning_task` (nightly, tutor-only)

The rotation itself is **pure Python, not a model decision** — the same law
that keeps date math out of every other producer's prompt. Before the tutor's
prompt is built, `build_user_prompt` computes the night's selected topic:

```python
def _select_learning_topic(conn) -> dict | None:
    """Least-recently-featured active topic. A topic that has never been
    featured sorts first (NULL last_featured treated as earliest)."""
    topics = learning.active_topics(conn)   # excludes clarifying/archived
    if not topics:
        return None
    return min(topics, key=lambda t: t.get("last_featured_date") or "")
```

The chosen topic's id and profile go into the prompt text and into
`RUN["learning_topic_id"]` (mirroring how `RUN["role"]` already threads
context through the run). The tool the model actually calls takes no topic
argument at all — it only writes the prose:

```python
@tool("write_learning_task",
      "Write tomorrow's practice task for the topic you were given tonight. "
      "One concrete exercise, not a lecture.", {"task_prompt": str})
async def write_learning_task(args):
    topic_id = RUN.get("learning_topic_id")
    if topic_id is None:
        return _err("no active topic to write for")
    tomorrow = (date.fromisoformat(db.today()) + timedelta(days=1)).isoformat()
    row = learning.create_or_replace_session(RUN["conn"], tomorrow, topic_id,
                                              args.get("task_prompt") or "")
    return _text({"ok": True, "session_id": row["id"]})
```

`learning_sessions.date UNIQUE` gives this the same idempotency law briefs
already have ("re-running a day replaces, never duplicates"): a second
nightly run for the same night overwrites tomorrow's row rather than
conflicting or duplicating.

**Zero active topics is not an error.** If `_select_learning_topic` returns
`None`, the prompt tells the model there is nothing to rotate and it writes
nothing — the same "no data" lane `coach.md` already documents for a
health-log-free stretch: don't nag, just note it plainly, and skip.

### 5.4 Mr. Miyagi may suggest a topic, never create one

Ordinary `create_proposal(kind="task", ...)` — no new proposal kind, no new
table column linking the proposal to a topic row. This generalizes the
existing law cleanly: approving *any* proposal in this codebase never
triggers an automated downstream write (a proposal attachment is inert,
approving a document proposal doesn't file it, approving this one doesn't
create a topic). The UI's "Start this topic" affordance on a suggested-topic
proposal card just prefills "Add a topic"'s name field from the proposal's
`action` text and, if Ian follows through, tags the resulting row
`origin='agent_proposed'` — but the clarification conversation (§5.1) still
has to run in full before it goes live. This is the same inert-until-Ian
pattern every other proposal kind already has; Learning adds no exception to
it.

---

## 6. Pillar routing: no schema widening

> **Law B3 — A pillar is a filter, never a column.**
> Learning is a *view* over existing `personal`-domain goals and facts, the
> same way partner and life already are. It never becomes a fifth value on
> `goals.domain`'s CHECK constraint.

`goals.domain` is a SQLite `CHECK` constraint. SQLite cannot `ALTER` a
`CHECK` — widening one means a full table rebuild, and CLAUDE.md already
carries the scar tissue from that trap (`chat_threads.model` — "a rebuild
must carry every ALTERed column or it drops the one it was meant to
preserve"). `core/pillars.py` already solved this exact problem once:
`is_partner_goal(goal)` inspects `notes`/`name` for a `#partner` tag or name
match and splits `personal` into `partner` vs `life` **without** a `goals.partner`
column. Learning is the identical move a third time.

### 6.1 Goals

```python
def is_learning_goal(goal: dict) -> bool:
    notes = (goal.get("notes") or "").lower()
    name = (goal.get("name") or "").lower()
    return "#learning" in notes or "learning:" in notes
```

A Learning goal (e.g. "finish 20 case-interview reps this month") is created
on `domain='personal'` with a `#learning` note tag, exactly like a Partner goal
carries `#partner`. `goals_for_pillar` gains a `learning` branch:

```python
if pillar == "learning":
    return [g for g in goals if g.get("domain") == "personal" and is_learning_goal(g)]
```

`life`'s existing branch (`domain == "personal" and not is_partner_goal(g)`)
must also exclude `is_learning_goal(g)`, the same three-way split partner/life
already required when partner carved itself out of personal.

### 6.2 Facts

`core/db.py`'s `NAMESPACE_DOMAINS` gains one entry, the same move `training`
made to route into `health` and `market` into `finance`:

```python
NAMESPACE_DOMAINS = {
    "partner": "personal", "family": "personal", "uiuc": "college",
    "content": "business", "training": "health", "market": "finance",
    "learning": "personal",                      # new
}
```

So a fact topic like `learning:python` (Mr. Miyagi's own memory of what he's
noticed about a topic over time, written via `write_fact` — already in
`chat_write_allow`'s universal six, unaffected by §4's role-scoping since
that only touches `chat_write_learning_profile`) resolves to `domain_for_topic("learning:python", default) == "personal"`
with zero changes to `FACT_DOMAINS`.

### 6.3 `core/pillars.py`

`PILLAR_ORDER` gains `"learning"`, placed with the other `personal`-domain
pillars rather than at the end:
`("btc", "body", "partner", "school", "life", "learning", "money")`.
`PILLAR_META["learning"] = {"label": "Learning", "icon": "✎", "domains": ("personal",)}`
(the pillar-icon set already in use is `◆ ◉ ♥ △ ○ $`; `✎` is unused there —
note it's a different glyph namespace than the role glyph in §1, which is
fine, `PILLAR_META` and `ROLE_GLYPHS` are separate tables with no shared
identity requirement). `compute_pillars` gets a `learning` branch: `detail`
reads the streak (`f"{streak}d streak"`, mirroring body's own `gym.get('streak')`
line) and, like `partner`, status is never allowed to read as a scolding
verdict — `st = "ON TRACK"` unconditionally, because an open Learning topic
with a gap in it is context, not a red pillar, the identical call already
made for open Partner intentions.

---

## 7. UI: `dashboard/src/pages/LearningPage.jsx`

### 7.1 Wiring (osui skill's "when adding a surface" checklist, at the same
concreteness this repo's other specs use)

- `dashboard/src/components/Nav.jsx`: one entry in `ALL_LINKS`
  (`{ id: 'learning', label: 'Learning', short: 'Learn', icon: '✎', section: 'pillars' }`),
  placed after `life` and before `money` to match `PILLAR_ORDER`. One entry
  in `ALL_MOBILE_MORE` (`[..., 'life', 'learning', 'money', ...]`) — Learning
  sits behind the More sheet exactly like Body/School/Life/Money already do;
  it is not one of the five fixed tabs (`MOBILE_PRIMARY` stays
  `['home', 'plan', 'btc', 'partner']`, unchanged).
- `dashboard/src/App.jsx`: `'learning'` added to `PAGES`
  (`[..., 'life', 'learning', 'money', ...]`) and a `case 'learning':` render
  branch, following the same hash-conditional pattern every other pillar page
  uses (a page with a lit tab drops its own title; this one has no tab, so it
  keeps its title, same as School/Life/Money today).

### 7.2 Content

- **Topic cards** — name, and a streak visual using the **same bending-streak
  vocabulary the gym already uses**: rest-day glyphs (◐-style, `--warn`-tinted,
  never `--crit`), never a percentage, never a raw number framed as a
  verdict. This is a direct instruction from CLAUDE.md's inherited product
  law and from Ian's own answer: reusing a known pattern means Ian reads it
  instantly instead of learning a second streak language.
- **"Today's practice"** — the one featured task (or "no active topic yet" in
  the zero-topics lane from §5.3). Tapping it opens or resumes today's
  session thread via `consultRequest` (`{role: 'tutor', seedText: ..., view:
  'expanded'}`) — the identical seeding mechanism §5.1 uses for onboarding,
  not a second path. If `learning_sessions.thread_id` is already set, the
  seed carries no text and the existing thread simply resumes (native session
  resume, SPEC-v37 §7.4); if it's the first open, the seed hands the tutor
  the day's `task_prompt` as context.
- **"Add a topic"** — a single-field entry point (§5.1). No level picker, no
  goal-setting form here; that conversation happens in the thread, on
  purpose, because a form can't ask a real follow-up question and a chat
  thread already can.
- A **"suggested by Mr. Miyagi"** affordance on any pending Learning-kind
  proposal, per §5.4 — visually a small card, not a modal, matching how
  proposals surface everywhere else in this app.

---

## 8. Delight

Ian said delight matters here specifically, so this gets real, specific
choices rather than a line saying "make it delightful":

- **A per-topic growth visual that only ever grows.** In the spirit of
  `core/garden.py`'s existing element on the Body page — "no label, generous
  space, it just IS there," a plant that cannot die (stage floor 1, mood
  recovers after any single alive day). A Learning topic gets a small,
  quiet, per-card visual keyed off cumulative confirmed sessions for that
  topic (never off the streak, which can legitimately reset — the *visual*
  should track "how much of this have you actually done," a number that only
  climbs, the same non-negotiable Garden already enforces). No number is
  printed next to it; like the Garden, Ian is told once what it means and
  then it's simply there.
- **A brief reveal when today's task first appears.** Motion that says
  "something new arrived" (osui L7), budgeted the same 200-320ms window this
  codebase already uses everywhere else for a reveal — no new timing
  constant, no new easing curve, reuse what `motion` already has configured
  for the gym confirm delight sequence.
- **Completion copy that names what actually happened, never "Great job!".**
  `CHAT_VOICE_LAYER` already states the law for every agent in this
  system — "Praise only what he actually did, and be specific" — and it
  applies here with no exception. When a practice session or a self-log
  closes out, the line the tutor writes into `agent_note` (and the toast
  that surfaces it) names the actual exercise and what Ian actually produced
  ("Walked the market-sizing case for the streaming service, landed on a
  TAM estimate with a real bottom-up build"), never a generic exclamation.
  This is the same anti-slop discipline `strip_em_dashes()` already enforces
  mechanically elsewhere in the codebase, applied here as prompt law rather
  than a string transform, because "specific praise" isn't a pattern a regex
  can enforce the way an em dash is.

---

## 9. Non-goals

- **No grading, scoring, or rubric in v1.** The daily session's "feedback" is
  the tutor's own conversational replies in that thread, same as any other
  agent chat. No structured pass/fail, no numeric rating.
- **No more than one featured task per day, system-wide.** `learning_sessions.date
  UNIQUE` enforces this at the schema level; it is a product decision, not a
  temporary limitation. Ian picking N topics does not mean N daily
  obligations.
- **No new `goals.domain` or `facts` domain value.** §6 is exhaustive on
  this: Learning routes through the existing `personal` domain the same way
  partner and life already do. Anyone tempted to add a `learning` domain later
  should re-read §6 first — it exists specifically to head that off.
  Widening `goals.domain`'s `CHECK` requires the table-rebuild trap this
  codebase has already been burned by once.
- **The agent never creates a topic on its own.** A `create_proposal` is
  informational only, exactly like every other proposal kind. Ian personally
  runs the clarification pass (§5.1) for every topic that goes live,
  regardless of whether he or the tutor thought of the name first.
- **No per-topic configurable cadence in v1.** `rest_days_per_week` is a
  fixed module constant (§2.3), not a Ian-editable prefs row. A `learning_prefs`
  table is a reasonable follow-up, not a v1 requirement.
- **No Learning-specific study-aid pipeline.** SPEC-v36's cited-Q&A workbench
  is School's, built around Canvas material and source grounding; Learning's
  daily task is generated fresh each night from a short prose profile, not
  retrieved from indexed files. The two systems solve different problems and
  neither one's machinery should leak into the other.

---

## 10. Schema changes

```sql
-- core/learning.py :: LEARNING_SCHEMA

CREATE TABLE IF NOT EXISTS learning_topics (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE,
    status         TEXT NOT NULL DEFAULT 'clarifying'
                     CHECK (status IN ('clarifying', 'active', 'archived')),
    origin         TEXT NOT NULL DEFAULT 'user'
                     CHECK (origin IN ('user', 'agent_proposed')),
    profile        TEXT NOT NULL DEFAULT '',
    thread_id      INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    archived_at    TEXT
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id       INTEGER REFERENCES learning_topics(id) ON DELETE SET NULL,
    date           TEXT NOT NULL UNIQUE,
    task_prompt    TEXT NOT NULL DEFAULT '',
    thread_id      INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    status         TEXT NOT NULL DEFAULT 'open'
                     CHECK (status IN ('open', 'completed', 'skipped')),
    agent_note     TEXT NOT NULL DEFAULT '',
    completed_at   TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS learning_streak_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL UNIQUE,
    kind           TEXT NOT NULL CHECK (kind IN ('confirm', 'grace', 'reset')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

```sql
-- core/acts.py: RING1_ACTS gains a 14th entry, "learning.confirm"
-- (no schema change -- agent_acts.act is a free-text column, same as every
--  other Ring 1 act string).
```

`core/learning.py::ensure_schema(conn)` is called once from `agents/runner.py`
next to the existing `school.ensure_schema(conn)` call. Backups: this data
lives in `data/ianos.db`, already claimed by `scripts/backup.sh` via
`VACUUM INTO`; no new path needs adding to the restic include list, unlike
`data/consult/out/` was for SPEC-v37.

---

## 11. Phases

Each phase ships independently and leaves the system working, following
SPEC-v37 §11's own shape.

### Phase 1 — Data model, Ring 1 act, nightly skeleton (~1 day)
§2 `core/learning.py`, `LEARNING_SCHEMA`, `ensure_schema` wired into the
runner · §3 `learning.confirm` in `core/acts.py` (`RING1_ACTS`,
`RING1_GRANTS["tutor"]`, `_apply`, undo handler) plus the `/api/learning/sessions/today/confirm`
dashboard endpoint · `agents/roles/tutor.md` written and wired (`ALLOWLISTS["tutor"]`,
`SEQUENCE` slot) but reading/writing nothing user-facing yet — the nightly
run's only job in this phase is proving `ensure_schema` and the dispatcher
slot work, with `write_learning_task` stubbed to a no-op.
**After Phase 1:** the tables exist, `learning.confirm` is receipted and
undoable, and `make plan` shows `tutor` in the nightly slate. Nothing is
visible to Ian yet.

### Phase 2 — Onboarding and the instant-write tool (~1-2 days)
§4 `chat_write_learning_profile`, `chat_write_allow`'s new role-scoped branch
· §5.1 the onboarding conversation instructions in `tutor.md`'s `## Chat`
section · a bare-bones "Add a topic" entry point (can predate the full page —
even a Cmd+K action is enough to prove the loop) that creates a `clarifying`
row and opens the seeded consult thread.
**After Phase 2:** Ian can type a topic name, get asked real clarifying
questions, and watch it flip to `active`. Still nothing generates a task.

### Phase 3 — Nightly task generation and the daily session (~1-2 days)
§5.2 `read_learning` · §5.3 `write_learning_task` and the least-recently-
featured rotation, including the zero-active-topics no-op lane · §5.4 the
Ring 2 topic-suggestion proposal (plain `create_proposal`, no new kind) · the
daily practice thread wired through `consultRequest` exactly as §7.2
describes, with `learning.confirm` reachable from inside it.
**After Phase 3:** the full daily loop is real — Mr. Miyagi writes a task
overnight, Ian works it in a thread the next day, confirms it, and the
streak moves.

### Phase 4 — The pillar UI and delight polish (~2 days)
§6 `core/pillars.py`'s `learning` carve-out (`is_learning_goal`,
`PILLAR_ORDER`, `PILLAR_META`, `compute_pillars`) · §7 `LearningPage.jsx` and
the Nav/App.jsx wiring · §8 the growth visual, the reveal motion, and the
specific-completion-copy instruction in `tutor.md`.
**After Phase 4:** Learning has its own pillar page, its own place in the
More sheet, and reads as a finished, delightful surface rather than a chat
thread with no home.

**Order matters** for the same reason SPEC-v37 §11 called out: Phase 2
before Phase 3, because a task-generation rotation with nothing `active` to
select from is dead code exercising nothing; Phase 3 before Phase 4, because
building the pillar page before the daily loop actually produces data means
building it against fixtures instead of the real shape the UI will render.

---

## 12. Laws this spec asserts in tests

| Test | Asserts |
|---|---|
| `test_learning_streak_never_touches_gym_events` | No code path in `core/learning.py` inserts into or reads from `streak_events`, and no gym code path touches `learning_streak_events`. (§2.3, Law B1) |
| `test_learning_confirm_today_only` | `learning.confirm` raises on a date other than today and never writes `grace`/`reset`. (§3.1, mirrors `gym.confirm`'s own test) |
| `test_clarifying_topic_generates_no_task` | `_select_learning_topic` never returns a `clarifying` or `archived` row. (§5.3, Law B2) |
| `test_profile_write_is_tutor_only` | `chat_write_allow("cfo")` and every other role omit `chat_write_learning_profile`; only `"tutor"` includes it. (§4) |
| `test_topic_proposal_creates_nothing` | Approving a Learning-suggestion proposal leaves `learning_topics` row count unchanged. (§5.4) |
| `test_no_new_goal_or_fact_domain` | `db.DOMAINS` and `db.FACT_DOMAINS` are unchanged by this spec; Learning goals/facts resolve to `personal` via `is_learning_goal`/`NAMESPACE_DOMAINS`. (§6, Law B3) |
| `test_learning_session_date_unique` | A second `write_learning_task` call for the same night's date replaces, never duplicates, tomorrow's row. (§5.3) |
| `test_zero_topics_is_not_an_error` | `tutor`'s nightly run with no active topics writes no error memo, just the "no data" note. (§5.3) |

---

## 13. Open questions for Ian

- **How many active topics before rotation gets stale?** With three named
  examples (case interviews, AI, Python) and least-recently-featured
  selection, each gets featured roughly every third day. That's probably
  fine at 3-4 topics; it's not obvious it's still fine at 8, where three
  weeks can pass between reps on any one topic and the tutor's "working
  profile" of it may go stale faster than it gets refreshed. No cap is
  proposed here — just flagging that rotation quality should get a real look
  once Ian actually has more than a handful of topics live.
- **What happens after several days of an ignored featured task?** The
  streak mechanic already answers "what happens to the streak" (rest days,
  then a reset, same as the gym). It doesn't answer whether a task that sat
  `open` for, say, five days should just keep rolling forward unacknowledged,
  get quietly marked `skipped` by the nightly run once it's stale, or
  surface as a gentle nudge somewhere. This spec leaves `learning_sessions.status
  = 'skipped'` in the schema for exactly this case but does not specify who
  sets it or when — a reasonable v1 default is "the nightly run marks
  yesterday's still-`open` row `skipped` before writing tonight's new one,"
  but that's a guess, not a decision, and should get Ian's actual answer
  before Phase 3 locks it in.
