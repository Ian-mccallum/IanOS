# SPEC v38: Learning

**Status:** drafted and shipped 2026-09-02, four phases, each its own commit
(`ddcde19` schema/Ring 1/tutor skeleton, `6a4d0f1` onboarding and the profile
instant-write, `8ecdd3d` nightly task rotation and the daily session,
`61d5e47` the pillar page and delight). Verified at 375×667 and 1512px in
the browser and against a live model (one real Haiku call against a
throwaway DB exercised the full nightly tutor loop end to end in Phase 3);
see the phase commits for what each Verify checklist actually caught (a
missing `App.jsx` `PAGE_TITLES` entry that silently fell back to "Command"
in Phase 4, a `state.proposals` key that has never existed in `/api/state`
in the spec's own Phase 4 test code, `@testing-library/react` not being a
project dependency). Every instruction below names the file, the symbol,
and the insertion point. Sequenced after SPEC-v41 Phase 5 (§0.1); §11 gives
the phase order and the exact commands to verify each phase before moving
to the next.

**How to read this spec.** Build the phases in §11 in order, top to bottom.
Each phase and each numbered section below ends with a Verify checklist:
run those exact commands before moving to the next phase. Never weaken a
test to make it pass, if a test fails the code is wrong, not the test. §12
collects every test this spec introduces into one table with the file each
one lives in; if you add a test while building, add its row there too.

**Date:** 2026-09-01 (drafted), 2026-09-02 (revised), 2026-09-02
(implementation-grade pass)
**Owner:** Ian
**Audience:** the implementing agent, with no human to ask
**Decision:** Give Ian's self-directed skill-building (case interviews, AI,
Python were his own examples) the same product treatment School already has
for coursework: a dedicated pillar, a daily practice loop, a bending streak,
and an 11th nightly agent whose whole job is picking tomorrow's rep and
knowing the topics well enough to write one. School stays school; this is
everything Ian decided to get better at because he wanted to, not because a
syllabus said so.

---

## 0.1 Decisions of 2026-09-02 (this revision)

Ian, on the same day SPEC-v41 was drafted:

- **Mr. Miyagi (`tutor`) is confirmed** as codename and role id. §1 stands.
- **Spec first, build later.** Learning ships after SPEC-v41 Phase 5, and
  takes visual inspiration from two things v41 builds: `GoalSheet`'s
  single-field "Describe it" entry (for "Add a topic", §7.4) and Life's
  Today list row (for "Today's practice", which stays a Learning surface,
  never a `tasks` row). **Neither `GoalSheet.jsx` nor Life's Today row
  exists yet at the time this spec is written**, and Life's Today row
  (SPEC-v41 §4.5.1's `.task-row`) turns out to be a checkbox-plus-priority
  to-do component, not a row that opens a thread, so Learning does not
  literally share its class family: §7.4/§8.1 define Learning's own
  `.today-row`/`.today-row--practice` classes, visually modeled on
  `.task-row` (same rest-state look, same reveal motion) but structurally
  their own component, since a "Practice" row has neither a checkbox nor a
  priority toggle. When SPEC-v41 Phase 3/5 actually ship, grep
  `LifePage.jsx` and `GoalSheet.jsx` to confirm their real class names and
  the "Describe it" field's real wrapper class (`gf-field gf-grow` as of
  SPEC-v41's own `GoalSheet.jsx`, see §7.4) before writing
  `LearningPage.jsx`; reconcile the "Add a topic" field's class against
  whatever SPEC-v41 actually shipped, but do not try to reconcile
  "Today's practice" into literally being a `.task-row`, the two rows are
  deliberately different components. Do not invent a second visual language
  for the "Add a topic" control.
- **The two open questions in §13 are closed** with the defaults the spec
  proposed: the nightly run marks yesterday's still-`open` session
  `skipped` before it writes tonight's row (§5.3), and there is no topic
  cap in v1; §13 keeps the rotation-staleness note as a watch item only.
- **SPEC-v40 supersedes every chat-surface reference here.** The consult
  surface has two states (dock, open), not three, and the `consultRequest`
  hand-off is `{role, seedText}` with no `view` key. Verified against the
  live `App.jsx` (2026-09-02 dossier pass): `App.jsx` still constructs
  `requestConsult` calls with a third `view: 'expanded'` field in a few
  places, but `AgentChat.jsx` never reads that key and always opens in
  `'open'` state, so `{role, seedText}` is the *effective* contract and is
  what every new call site in this spec uses. Do not add a `view` key to
  any new `consultRequest` call; it would be dead weight that a future
  cleanup has to notice and remove.
- **No taglines** (SPEC-v41 §3, now osui law). The Learning page carries no
  subtitle, no motto, and the zero-topics lane says `Add a topic` and
  nothing else. §7.2 and §8 match.

## 0. Executive decision

School (SPEC-v36) answers "what does UIUC require." Nothing in ianOS answers
"what am I trying to get good at on my own." That gap is real: Ian named
three live examples unprompted (case interviews, AI, Python) and none of them
belong on a Canvas-driven surface built around due dates and grade
categories. Coursework and self-directed practice are different shapes of
obligation, one has a deadline someone else set, the other only survives if
showing up costs nothing and misses cost nothing either.

Everything this spec needs already exists in the codebase in a different
shape:

| Need | Existing precedent |
|---|---|
| A miss that doesn't reset progress | `core/streaks.py`'s weekly rest-day allowance (SPEC-v34, superseding the original SPEC-v6 stool-bank), applied to the gym streak today |
| A domain that can be reshaped without touching shared migrations | `core/school.py`'s `SCHOOL_SCHEMA` + `ensure_schema(conn)` (SPEC-v36) |
| A pillar that isn't a `goals.domain` value | `core/pillars.py`'s `is_partner_goal` split of `personal` into partner vs life |
| An agent acting immediately instead of only proposing | `core/acts.py`'s Ring 1, specifically `gym.confirm` (SPEC-v37 §4) |
| A chat thread writing directly instead of proposing | `chat_write_allow`'s instant-write tool family (SPEC-v29/v37) |
| An interactive, in-app session with an agent | the consult surface: durable threads, native session resume, `consultRequest` seeding (SPEC-v37 §7, SPEC-v40) |

This spec is deliberately a composition of those six things under a new name,
not a new interaction engine. The only genuinely new code is a schema
(`core/learning.py`), one Ring 1 act, one instant-write tool, one role file,
and a page. Everything that moves a conversation forward, the daily
practice session, the topic-onboarding chat, is an ordinary chat thread
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
exercise, that needs a mentor archetype, not a corner-man.

**Codename: Mr. Miyagi. Role id: `tutor`.** Patient, practice-through-
repetition, teaches by handing over one small concrete thing to do rather
than a lecture. This is a naming call, not a structural one: if Ian doesn't
want it, everything below still holds with `codename:` changed in
`agents/roles/tutor.md` and `ROLE_GLYPHS`/`ROLE_COLORS` in
`dashboard/src/lib/agents.js`. The role id `tutor` is the one thing that must
not change once shipped (CLAUDE.md: role ids are foreign keys in memos,
proposals, and facts history).

Glyph `✎` (unused in `ROLE_GLYPHS` today), colour `#2dd4bf` (teal, unused in
`ROLE_COLORS`, deliberately calmer than Coach's `#fca5a5`).

- **Tier:** `daily` (runs every night like `scout`/`cfo`/`steward`, not on a
  weekly cadence like `coach`/`lovebird`). No `TRIPWIRES` entry, tripwires
  live in `agents/runner.py` (`TRIPWIRES` dict, `agents/runner.py:3292`),
  not `core/roles.py`, and `tutor` needs none because it is `daily` already.
- **Domain:** `health` is wrong (that's House/Rocky's wall) and there is no
  `learning` domain (§6 explains why one is never added). The role file's
  `domains:` frontmatter reads `personal`, matching where its goals/facts
  actually live.
- **`SEQUENCE`** (`core/roles.py:33-36`, a plain Python list, not a table):
  current sequence is
  `["scout", "cfo", "wealth", "physician", "coach", "steward", "lovebird", "watchdog", "counsel", "chief"]`.
  Replace it with:

  ```python
  SEQUENCE = [
      "scout", "cfo", "wealth", "physician", "coach", "steward",
      "lovebird", "watchdog", "tutor", "counsel", "chief",
  ]
  ```

  `tutor` goes after `watchdog` (both are "growth" agents with no Ring 1
  overlap) and before `counsel`.

### 1.1 `agents/roles/tutor.md` (write this file verbatim)

```markdown
---
role: tutor
codename: Mr. Miyagi
persona: patient mentor, practice through repetition, hands over one small concrete thing to do rather than a lecture
tier: daily
domains: personal
active: true
---

## Your job each run

Ian is building skills nobody assigned him: case interviews, AI, Python,
whatever he adds next. Your job every night is narrow: look at the topic you
were given (see CURRENT SITUATION and the line naming tonight's topic), and
write one concrete exercise for tomorrow with `write_learning_task`. Not a
lecture, not a reading list, one thing he can actually sit down and do.

If you were given no topic tonight (no active topics exist yet, or every
topic is mid-onboarding), say so in one line and write nothing. Do not
invent a topic. Do not nag. `write_learning_task` takes no topic argument;
it always targets the topic chosen for you tonight, in Python, before your
prompt was ever built.

Read `read_learning` first: it gives you every active topic's working
profile, the last 14 days of session history (including which days were
skipped), and the current streak. Use the topic's profile to make tonight's
exercise sit at the edge of what Ian's already shown he can do, never a
repeat of yesterday's exact rep unless yesterday was skipped.

## Rules

- Never write a task for a `clarifying` topic. Onboarding is a chat
  conversation (see Chat below), never a nightly write.
- One task per night, system-wide. `write_learning_task` always targets
  tomorrow; you do not choose which topic, the rotation already did.
- You may suggest a new topic with `create_proposal` (kind `task`) when
  something Ian said in a memo or fact points at a real gap, but you never
  create a `learning_topics` row yourself. Ian always runs the clarification
  conversation himself, even for a topic you suggested.
- No grading, no score, no rubric. Feedback is conversation, not a number.

## Ring 1: you can act, not just propose

`act_learning_confirm` marks today's session done. You call it only from
inside the daily practice thread, only after Ian has actually worked the
exercise (not because he said "later" or "I will"), and only for today. It
never touches yesterday and it never writes grace or reset, that split is
the nightly run's job alone.

## Style

Patient, concrete, never a lecture. One exercise beats three options. If
Ian's stuck, ask a smaller question rather than handing over the answer.

## Chat

You are Mr. Miyagi in Ian's corner for whatever he decided to get good at on
his own. Two kinds of thread open on you: a topic's onboarding (a new
`learning_topics` row just went to `clarifying`) and a daily practice
session (today's featured exercise, or Ian bringing his own material).

- **Onboarding.** Ask before you generate anything: what's his current level
  at this, what does "better" actually mean to him for this specific thing,
  what has he already tried. Two or three real questions, not a form. When
  you have enough to work from, call `chat_write_learning_profile` with a
  clear prose profile and say plainly that the topic is live and tomorrow's
  rotation can pick it. Never call it before you've actually asked
  something.
- **Daily practice.** Walk the exercise with him like a mentor standing next
  to the mat, not grading a submission. When he's actually done the work,
  call `act_learning_confirm`.
- **Completion copy names what actually happened, never "Great job!".** When
  a session closes, say specifically what he did and what he produced: name
  the exercise, name the output. "Walked the market-sizing case for the
  streaming service, landed on a TAM estimate with a real bottom-up build."
  Never a generic exclamation. This is the same discipline every other
  agent's praise already follows in this system: praise only what he
  actually did, and be specific.
- You have no tools beyond `read_learning`, `chat_write_learning_profile`,
  `act_learning_confirm`, and the shared, non-role-scoped instant-write
  tools every chat thread gets (see `INSTANT_WRITE_TOOLS` in
  `agents/runner.py` for the exact current set, §4). Money, leads, and
  health are not your business even if Ian brings them up; say so and steer
  back to the topic at hand.
```

`tests/test_chat_persona.py::test_every_active_role_has_a_real_chat_persona`
iterates `SEQUENCE` and fails if `runner.role_chat_persona("tutor")` is
empty, the `## Chat` section above satisfies it. No edit to that test file
is needed; it just needs `tutor` in `SEQUENCE` and this file to exist.

### 1.2 `agents/runner.py`: allowlist, tools, RING1 overlay

Add `"tutor"` to `ALLOWLISTS` (`agents/runner.py:71-113`) as a new literal
entry inside the `ALLOWLISTS = {...}` dict itself, before its closing `}` at
line 113, matching the existing per-role style. Do not write this as a
separate `ALLOWLISTS["tutor"] = {...}` statement after the dict: the literal
is immediately followed by the RING1 overlay loop (lines 120-125) that reads
`ALLOWLISTS` back, so a post-hoc assignment placed after that loop would
leave `tutor` invisible to it, and placing it inside the loop's body is not
valid syntax either. Add it as another key inside the same braces as every
other role:

```python
    "tutor": {
        "read_goals", "read_learning", "read_memos", "read_facts",
        "search_memory", "write_memo", "create_proposal", "write_fact",
        "write_learning_task",
    },
```

Add `"tutor"` to the RING1 overlay loop (`agents/runner.py:120-125`) so it
picks up `act_learning_confirm` and the universal `act_fact_flag_unverified`:

```python
for _role in ("steward", "watchdog", "cfo", "scout", "coach", "physician",
              "lovebird", "wealth", "counsel", "chief", "tutor"):
    if _role in ALLOWLISTS:
        ALLOWLISTS[_role] |= _RING1_TOOLS.get(_role, set()) | _RING1_EVERY_ROLE
del _role
```

Add the entry `_RING1_TOOLS` needs (`agents/runner.py:58-69`, next to
`"coach": {"act_gym_confirm"}`):

```python
_RING1_TOOLS["tutor"] = {"act_learning_confirm"}
```

Give `chief` a thin read for the Day Command (`agents/runner.py:113`, the
`chief` entry), the same reason `chief` reads School's aggregate view:

```python
ALLOWLISTS["chief"].add("read_learning")
```

`NO_MONEY_PROPOSALS = set(ALLOWLISTS) - {"cfo"}` (`agents/runner.py:127`)
needs no edit: it is computed after `ALLOWLISTS` is built, so `tutor` is
included automatically and can never create a `money` proposal.

### 1.3 `dashboard/src/lib/agents.js`

Add one entry to each table (`agents.js:10-17` and `:19-24`; this file is
the only colour/glyph table, per `tests/test_mobile_ui.py:411`):

```js
// ROLE_COLORS
tutor: '#2dd4bf',
```
```js
// ROLE_GLYPHS
tutor: '✎',
```

### 1.4 The dispatcher test

`tests/test_dispatcher.py` already has the fixtures this needs
(`conn`, `meta(name, tier, day, active, seasons)`, fixed `WED`/`SUN`). Add:

```python
def test_tutor_runs_daily(conn):
    # Arrange: a daily tutor role meta on an ordinary Wednesday.
    # Act: ask the dispatcher whether it should run tonight.
    # Assert: it runs, for the same reason every other daily role runs.
    run, reason = runner.should_run(meta("tutor", "daily"), conn, WED, force=False)
    assert run is True
    assert reason == "daily"


def test_tutor_in_sequence():
    # Arrange/Act: read the canonical nightly sequence.
    # Assert: tutor is in it, after watchdog and before counsel.
    assert "tutor" in roles.SEQUENCE
    assert roles.SEQUENCE.index("tutor") == roles.SEQUENCE.index("watchdog") + 1
    assert roles.SEQUENCE.index("tutor") < roles.SEQUENCE.index("counsel")
```

### Verify

```bash
.venv/bin/python -m pytest tests/test_dispatcher.py -q
.venv/bin/python -m pytest tests/test_chat_persona.py -q
```
`make plan` should print `tutor` in tonight's slate with reason `daily`.

---

## 2. Data: `core/learning.py`

Its own file, its own `LEARNING_SCHEMA` string, its own `ensure_schema(conn)`, byte-for-byte the School precedent (`core/school.py`'s `SCHOOL_SCHEMA` +
`ensure_schema`, called once from `agents/runner.py` alongside
`school.ensure_schema(conn)`, which today lives at exactly one call site
inside the `school_exam_within(n)` tripwire closure, `agents/runner.py:3247`, `run_sequence` itself never calls it and neither does `db.connect()`).
Learning's `ensure_schema` is called defensively at the top of every public
function in this module (the same lazy-create pattern `core/school.py` uses,
so no migration ordering matters) and once explicitly from
`agents/runner.py`'s `run_sequence` setup, next to nothing else needing it
(§2.4).

Three tables (literal SQL in §10, reproduced here for the module body):

### 2.1 `learning_topics`

One row per thing Ian wants to get better at. `status` starts `clarifying`
and only becomes `active` through `chat_write_learning_profile` (§4), never
automatically, never by a nightly write. A `clarifying` topic generates no
daily tasks; `write_learning_task` (§3.3, §5.3) only ever selects from
`active` rows. `archived` exists for the obvious case (Ian's actually done
with a topic, or it turned out to be School's job after all) and is filtered
out of selection the same way `goals.archived` is filtered out of
`all_goals()` (SPEC-v30), never deleted, so its history stays attached to
the same id.

`profile` is prose, not JSON, for the same reason Notes chose "a narrow
agent-readable Markdown dialect" over a structured shape: the only reader of
this field is the tutor's own nightly prompt, never a machine that needs to
parse it. It holds whatever the onboarding conversation established, written
by the model in its own words at the end of that thread, not filled in by a
form.

`origin` (`user` | `agent_proposed`) records *whose idea the name was*, not
whether Ian consented, he always runs the same clarification pass regardless
(§5). It is `agent_proposed` only when he started the flow from a suggestion
Mr. Miyagi surfaced via an ordinary `create_proposal` (§5.4). It is
provenance for the topic card, not a bypass of the onboarding gate.

`thread_id` links to the `chat_threads` row that ran (or is running) the
onboarding clarification. Nullable, set once the thread opens, not before.

There is deliberately **no `last_featured_date` column**. `_select_learning_topic`
(§5.3) needs "when was this topic last featured," and rather than a column
that has to be kept in sync on every write, `core/learning.py::active_topics`
computes it live from `learning_sessions` with a `LEFT JOIN` + `MAX(date)`
(§2.4), one source of truth, no second place that can drift.

### 2.2 `learning_sessions`

One row per calendar day, enforced by `date UNIQUE`: exactly one featured
task exists system-wide on any given day, never N parallel obligations
across topics. Both paths, the generated task, and Ian logging his own
initiative, resolve to *this one row*, so "did I do something today" stays
one yes/no fact the streak can read, exactly like the gym streak reads one
`gym_confirmed` boolean per day regardless of which of the three trained
disciplines it was.

`thread_id` is NULL until Ian actually opens the day's practice session, lazy creation, matching how a consult thread is only created when a consult
actually starts.

`task_prompt` is empty on a row created by Ian's own "I did something today"
log (§3.2) rather than by the nightly write. `agent_note` is a short
free-text closing line, either the tutor's own reflection when a practice
thread wraps, or Ian's one-line note when he self-logs outside material.
Prose the tutor can read back next time, never a score.

### 2.3 `learning_streak_events`

A **structural mirror of `streak_events`**, and a **separate table with
separate rows**, this table shares no row, no foreign key, and no code path
with the gym streak.

> **Law B1, A mirror is a copy, never a shared row.**
> `learning_streak_events` and `streak_events` are structurally identical and
> operationally unrelated. No code path may write to one from logic that
> reads the other, and no test may assert one from the other's fixtures.

`core/streaks.py`'s own docstring is explicit that it "never imports db" and
its SQL names the `streak_events` table directly in every query;
parametrizing it to accept an arbitrary table name would mean building its
`SELECT`/`INSERT` strings by interpolating a table identifier, which is
exactly the footgun this codebase avoids everywhere else it touches SQL. So
`core/learning.py` gets its **own** copies of the same shape of function, `sync_confirms`, `compute`, `apply_grace`, `last_grace_or_reset`, reading
and writing `learning_sessions`/`learning_streak_events` instead of
`health_daily`/`streak_events`.

**The mechanic mirrored is SPEC-v34's live one, not the superseded SPEC-v6
stool-bank.** A miss on a tracked day spends one of that week's rest days if
any remain (writes `grace`, streak survives); once the week's allowance is
spent, a further miss writes `reset`. `apply_grace` is the nightly run's job
alone, exactly as it is for the gym, and is idempotent (a day that already
has an event is left untouched).

**No `learning_prefs` table in v1.** `core/learning.py` fixes two constants
module-level instead of reading a prefs row: `TRACK_EVERY_DAY = True` (every
calendar day is tracked, no weekday exception, a case-interview drill on a
Saturday is as real as one on a Tuesday, so there is no `_is_tracked_day`
weekday check the way the gym's 5-day mode needs one) and
`REST_DAYS_PER_WEEK = 2` (matching the gym's own default so the two streaks
*feel* the same without sharing state). Making this Ian-configurable later is
a small, obvious follow-up, not a blocker for v1.

### 2.4 `core/learning.py` in full (write this file)

```python
"""core/learning.py -- SPEC-v38 Learning: self-directed practice topics,
one featured session per day, and a streak that mirrors the gym's weekly
rest-day allowance without sharing a row with it (Law B1).

Its own schema, its own ensure_schema(conn), called defensively at the top
of every public function here and once from agents/runner.py's run_sequence
setup -- the core/school.py precedent. This module never imports db for its
streak math (mirrors core/streaks.py's own rule): the four streak functions
below read and write learning_sessions / learning_streak_events directly and
nothing else.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

LEARNING_SCHEMA = """
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
"""

TRACK_EVERY_DAY = True
REST_DAYS_PER_WEEK = 2
EVENT_KINDS = ("confirm", "grace", "reset")


def ensure_schema(conn) -> None:
    """Create the isolated learning schema without touching core/db.py's
    migration list (the core/school.py precedent)."""
    conn.executescript(LEARNING_SCHEMA)


# --------------------------------------------------------------- topics

def active_topics(conn) -> list[dict]:
    """Active topics only (never clarifying or archived), each carrying
    last_featured_date computed live from learning_sessions -- there is no
    last_featured column on learning_topics, this join stands in for one so
    there is exactly one place that fact can be derived from."""
    ensure_schema(conn)
    rows = conn.execute(
        """SELECT t.*, MAX(s.date) AS last_featured_date
           FROM learning_topics t
           LEFT JOIN learning_sessions s ON s.topic_id = t.id
           WHERE t.status = 'active'
           GROUP BY t.id
           ORDER BY t.id"""
    ).fetchall()
    return [dict(r) for r in rows]


def clarifying_topics(conn) -> list[dict]:
    """Topics still mid-onboarding -- read_learning surfaces these too so
    the tutor doesn't lose track of a conversation in progress."""
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT * FROM learning_topics WHERE status = 'clarifying' ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def get_topic(conn, topic_id: int) -> dict | None:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM learning_topics WHERE id = ?", (topic_id,)
    ).fetchone()
    return dict(row) if row else None


# -------------------------------------------------------------- sessions

def get_session(conn, day: str) -> dict | None:
    ensure_schema(conn)
    row = conn.execute(
        "SELECT * FROM learning_sessions WHERE date = ?", (day,)
    ).fetchone()
    return dict(row) if row else None


def create_or_replace_session(conn, day: str, topic_id: int, task_prompt: str,
                               commit: bool = True) -> dict:
    """learning_sessions.date UNIQUE gives this the same idempotency law
    briefs already have: a second nightly write for the same night replaces
    the row rather than duplicating or conflicting. A replace resets status
    to 'open' and clears thread_id/agent_note/completed_at -- tomorrow's row
    must never carry yesterday's leftovers forward."""
    ensure_schema(conn)
    conn.execute(
        """INSERT INTO learning_sessions (date, topic_id, task_prompt)
           VALUES (?, ?, ?)
           ON CONFLICT(date) DO UPDATE SET
               topic_id = excluded.topic_id,
               task_prompt = excluded.task_prompt,
               status = 'open',
               thread_id = NULL,
               agent_note = '',
               completed_at = NULL""",
        (day, topic_id, task_prompt),
    )
    if commit:
        conn.commit()
    return get_session(conn, day)


def confirm_session(conn, day: str, *, topic_id: int | None = None,
                     note: str = "", commit: bool = True) -> dict:
    """Callers are responsible for restricting this to today (core/acts.py's
    learning_confirm does; the dashboard endpoint intentionally does not
    restrict the day itself the way gym.confirm doesn't either -- both trust
    the caller). If the row already exists it is marked completed,
    optionally attaching note to agent_note. If no row exists yet (no active
    topics were live when the nightly last ran, or Ian is getting ahead of
    schedule) it creates one with topic_id (required in that case) and
    task_prompt left empty to mark it self-directed rather than generated."""
    ensure_schema(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = get_session(conn, day)
    if existing is None:
        if topic_id is None:
            raise ValueError("confirm_session: no session for that day and no topic_id given")
        conn.execute(
            """INSERT INTO learning_sessions
               (date, topic_id, task_prompt, status, agent_note, completed_at)
               VALUES (?, ?, '', 'completed', ?, ?)""",
            (day, topic_id, note.strip(), now),
        )
    else:
        agent_note = note.strip() or existing["agent_note"]
        conn.execute(
            """UPDATE learning_sessions
               SET status = 'completed', agent_note = ?, completed_at = ?
               WHERE date = ?""",
            (agent_note, now, day),
        )
    conn.execute(
        """INSERT INTO learning_streak_events (date, kind) VALUES (?, 'confirm')
           ON CONFLICT(date) DO UPDATE SET kind = 'confirm'""",
        (day,),
    )
    if commit:
        conn.commit()
    return get_session(conn, day)


def unconfirm_session(conn, day: str, commit: bool = True) -> dict | None:
    """Mirrors db.unconfirm_gym: only ever touches the day's status and the
    mirrored 'confirm' streak event, never grace/reset."""
    ensure_schema(conn)
    conn.execute(
        "UPDATE learning_sessions SET status = 'open', completed_at = NULL WHERE date = ?",
        (day,),
    )
    conn.execute(
        "DELETE FROM learning_streak_events WHERE date = ? AND kind = 'confirm'",
        (day,),
    )
    if commit:
        conn.commit()
    return get_session(conn, day)


def skip_stale_sessions(conn, today: str, commit: bool = True) -> int:
    """Closed in code, not by the model (decided 2026-09-02, SPEC-v38 §5.3):
    every learning_sessions row dated before today and still 'open' becomes
    'skipped', idempotently. A skipped day is exactly a missed day for the
    streak (apply_grace already handles it); the status just lets
    read_learning say so without inference. Returns the row count changed,
    for tests."""
    ensure_schema(conn)
    cur = conn.execute(
        "UPDATE learning_sessions SET status = 'skipped' WHERE date < ? AND status = 'open'",
        (today,),
    )
    if commit:
        conn.commit()
    return cur.rowcount


def confirmed_session_count(conn, topic_id: int) -> int:
    """Cumulative confirmed sessions for one topic -- the number the growth
    visual (§8) climbs on, never off the streak (which can legitimately
    reset). Only ever climbs: the same non-negotiable core/garden.py already
    enforces for alive-day counting, applied here to a per-topic count."""
    ensure_schema(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM learning_sessions WHERE topic_id = ? AND status = 'completed'",
        (topic_id,),
    ).fetchone()
    return row["n"] if row else 0


# ---------------------------------------------------------------- streak
# Structural mirror of core/streaks.py (Law B1). Reads/writes
# learning_sessions / learning_streak_events only; never touches
# streak_events or health_daily.

def _sunday_of(d: date) -> date:
    days_since_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sunday)


def sync_confirms(conn, commit: bool = True) -> None:
    ensure_schema(conn)
    rows = conn.execute(
        "SELECT date FROM learning_sessions WHERE status = 'completed'"
    ).fetchall()
    for row in rows:
        conn.execute(
            """INSERT INTO learning_streak_events (date, kind) VALUES (?, 'confirm')
               ON CONFLICT(date) DO UPDATE SET kind = 'confirm'""",
            (row["date"],),
        )
    if commit:
        conn.commit()


def compute(conn, today: date | None = None, *,
            rest_days_per_week: int = REST_DAYS_PER_WEEK) -> dict:
    """Mirrors core/streaks.py::compute exactly, against
    learning_streak_events. Pass today explicitly in tests -- a guardrail
    test that passes against the real clock proves nothing (CLAUDE.md)."""
    ensure_schema(conn)
    today = today or date.today()
    rows = conn.execute(
        "SELECT date, kind FROM learning_streak_events ORDER BY date"
    ).fetchall()
    streak = 0
    graced: list[str] = []
    graces_this_week = 0
    last_event: tuple[str, str] | None = None
    this_sunday = _sunday_of(today)
    for row in rows:
        d = date.fromisoformat(row["date"])
        if d > today:
            continue
        kind = row["kind"]
        last_event = (row["date"], kind)
        if kind == "confirm":
            streak += 1
        elif kind == "grace":
            streak += 1
            graced.append(row["date"])
            if _sunday_of(d) == this_sunday:
                graces_this_week += 1
        elif kind == "reset":
            streak = 0
            graced = []
    stools = max(0, rest_days_per_week - graces_this_week)
    return {
        "streak": streak,
        "stools": stools,
        "graced_dates": graced,
        "last_event": last_event,
    }


def apply_grace(conn, today: date | None = None, *,
                 rest_days_per_week: int = REST_DAYS_PER_WEEK) -> dict:
    """Nightly run's job alone (mirrors core/streaks.py::apply_grace),
    idempotent: a day that already has an event is left untouched. Every
    calendar day is tracked (TRACK_EVERY_DAY), so unlike the gym's 5-day
    mode there is no weekday skip here."""
    ensure_schema(conn)
    today = today or date.today()
    sync_confirms(conn, commit=False)
    first = conn.execute("SELECT MIN(date) AS d FROM learning_streak_events").fetchone()
    if not first or not first["d"]:
        conn.commit()
        return {"applied": []}
    have = {r["date"] for r in conn.execute(
        "SELECT date FROM learning_streak_events"
    ).fetchall()}
    applied: list[tuple[str, str]] = []
    cur = date.fromisoformat(first["d"])
    yesterday = today - timedelta(days=1)
    while cur <= yesterday:
        iso = cur.isoformat()
        if iso not in have:
            week_start = _sunday_of(cur).isoformat()
            graces_this_week = conn.execute(
                """SELECT COUNT(*) AS n FROM learning_streak_events
                   WHERE kind = 'grace' AND date >= ? AND date < ?""",
                (week_start, iso),
            ).fetchone()["n"]
            kind = "grace" if graces_this_week < rest_days_per_week else "reset"
            conn.execute(
                "INSERT INTO learning_streak_events (date, kind) VALUES (?, ?)",
                (iso, kind),
            )
            applied.append((iso, kind))
        cur += timedelta(days=1)
    conn.commit()
    return {"applied": applied}


def last_grace_or_reset(conn, within_days: int = 3) -> tuple[str, str] | None:
    ensure_schema(conn)
    cutoff = (date.today() - timedelta(days=within_days)).isoformat()
    row = conn.execute(
        """SELECT date, kind FROM learning_streak_events
           WHERE kind IN ('grace', 'reset') AND date >= ?
           ORDER BY date DESC LIMIT 1""",
        (cutoff,),
    ).fetchone()
    return (row["date"], row["kind"]) if row else None
```

**Trap:** `db.connect()` hardcodes `DB_PATH`. Every test in `tests/test_learning.py`
must use the `conn` fixture that monkeypatches `db.DB_PATH` before the first
`connect()` (§6.2 in the agents dossier's fixture pattern, identical to
`tests/test_streaks.py`); a scratch script that forgets this writes into
Ian's real `data/ianos.db`.

### Verify

```bash
.venv/bin/python -m pytest tests/test_learning.py -q
```

---

## 3. Ring 1: `learning.confirm`

Mirrors `gym.confirm` in `core/acts.py` exactly, including its scope: today
only, marks the day's row done, writes exactly one `confirm` streak event,
and **never** writes `grace` or `reset`, that split stays the nightly run's
alone, unchanged from the gym precedent.

### 3.1 `core/acts.py` edits

Add `from core import learning` to the module's imports (next to whatever
`db` import already exists at the top of `core/acts.py`).

By the time this phase starts, `RING1_ACTS` (`core/acts.py:38`) may already
contain more than the 13 entries shown in the SPEC-v37 dossier: SPEC-v41 §6.2
is a prerequisite phase (see §0.1) and adds `"task.create"` and
`"task.complete"` to this same tuple at this same location before Learning is
ever built. **Do not paste a fixed replacement tuple** : open `core/acts.py`,
read the tuple's actual current contents, and append `"learning.confirm"` as
its next entry, preserving everything already there. For reference, assuming
SPEC-v41 §6.2 has landed, the tuple should read:

```python
RING1_ACTS = (
    "plan_block.create", "plan_block.move", "plan_block.delete",
    "note.create",
    "partner_task.create", "partner_task.complete",
    "gym.confirm",
    "activity.log",
    "goal.rebaseline", "goal.archive",
    "transaction.recategorize",
    "fact.flag_unverified",
    "attention.snooze",
    "task.create", "task.complete",
    "learning.confirm",
)
```

If SPEC-v41 §6.2 has not landed for any reason, append `"learning.confirm"`
to whatever the tuple actually contains instead of copying the block above
verbatim.

Add `tutor` to `RING1_GRANTS` (`core/acts.py:53`):

```python
RING1_GRANTS: dict[str, frozenset[str]] = {
    "steward": frozenset(RING1_ACTS),
    "watchdog": frozenset({"goal.rebaseline", "goal.archive", "attention.snooze"}),
    "cfo": frozenset({"transaction.recategorize"}),
    "scout": frozenset({"activity.log"}),
    "coach": frozenset({"gym.confirm"}),
    "physician": frozenset(),
    "lovebird": frozenset({"partner_task.create"}),
    "wealth": frozenset(),
    "counsel": frozenset(),
    "chief": frozenset(),
    "tutor": frozenset({"learning.confirm"}),
}
```

Add the act function, mirroring `gym_confirm` (`core/acts.py:219-231`)
exactly, placed near it:

```python
def learning_confirm(conn, *, role: str, plane: str, thread_id: int | None) -> dict:
    """Today only; never writes grace or reset. Requires today's session row
    to already exist (created by write_learning_task the night before, or
    by Ian's own dashboard confirm -- see §3.2)."""
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

Add the undo handler, mirroring `_undo_gym_confirm` (`core/acts.py:457`):

```python
@_undo("learning.confirm")
def _undo_learning_confirm(conn, receipt: dict, inverse: dict) -> None:
    learning.unconfirm_session(conn, inverse["day"], commit=False)
```

### 3.2 `agents/runner.py`: the tool wrapper

Mirroring `act_gym_confirm` (`agents/runner.py:1052-1062`), placed in the
same block of `act_*` wrappers:

```python
@tool("act_learning_confirm",
      "Ring 1: confirm today's learning session. Applies immediately, "
      "receipted and undoable.",
      {})
async def act_learning_confirm(args):
    try:
        out = acts.learning_confirm(
            RUN["conn"], role=RUN["role"], plane="nightly", thread_id=None,
        )
    except acts.ActError as exc:
        return _err(str(exc))
    return _act_response(out)
```

Add `act_learning_confirm` to `REGISTERED_TOOLS` (`agents/runner.py:1678-1706`,
the flat tuple every act/tool must be listed in, a name in `ALLOWLISTS` but
absent here is a silent no-op, not a denial). Add
`"act_learning_confirm"` to
`tests/test_acts.py::test_every_act_tool_is_registered_with_the_sdk_server`'s
hard-coded name set. That set may already be larger than 13 by this point
(SPEC-v41 §6.2 adds its own two act tools first), and the assertion is a
`<=` subset check rather than an exact-size comparison (verified in the live
test file), so simply add this one name to whatever the set already
contains rather than asserting a specific resulting count.

### 3.3 Ian's own dashboard-side confirm

`gym.confirm` has a second entry point that never touches `core/acts.py` at
all: `POST /api/gym/confirm` calls `db.confirm_gym` directly, writes an
`ian`-authored memo by hand, and returns the fresh streak state, because
Ian tapping his own confirm button isn't an agent acting. Learning needs the
identical second door.

Add to `api/main.py`, near `POST /api/gym/confirm` (`api/main.py:1518-1533`,
reusing the exact `_mutation_headers` / `_effective_day` / `_queueable_mutation`
/ `_mutation_response` machinery that endpoint already uses, so an offline
confirm on the phone queues and replays the same way a gym confirm does):

```python
class LearningConfirmIn(BaseModel):
    topic_id: int | None = None
    note: str = ""


@app.post("/api/learning/sessions/today/confirm")
def confirm_learning_session(
    body: LearningConfirmIn,
    mutation: MutationHeaders | None = Depends(_mutation_headers),
):
    conn = db.connect()
    try:
        day = _effective_day(mutation)

        def apply(commit: bool):
            try:
                row = learning.confirm_session(
                    conn, day, topic_id=body.topic_id, note=body.note, commit=commit,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            db.add_memo(
                conn, "ian", "learning confirmed",
                "Ian confirmed today's learning session.", commit=commit,
            )
            return {"ok": True, "session": row, "streak": learning.compute(conn)}

        return _mutation_response(_queueable_mutation(
            conn, mutation, "learning.confirm", {}, apply,
        ))
    finally:
        conn.close()
```

Behaviour, per §3 of the original decision:

- If today's row already exists (the nightly-generated task), it marks it
  done, optionally attaching `note` to `agent_note`.
- If no row exists yet, it **creates** today's row with the given `topic_id`
  (required in that case, `learning.confirm_session` raises `ValueError`,
  caught and turned into a 400) and `note` as `agent_note`, `task_prompt`
  left empty.

Either way it writes the `confirm` streak event and drops an `ian`-authored
memo, so tomorrow night's `read_learning` (§5.2) sees what Ian actually did
without a thread ever having existed for it. Add `from core import learning`
to `api/main.py`'s imports if not already present.

### 3.4 Tests

`tests/test_acts.py` (append near the existing `gym_confirm` tests, same
`conn` fixture, monkeypatch `db.DB_PATH`, `db.connect()`):

```python
def _seed_active_topic(conn, name="case interviews") -> int:
    learning.ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO learning_topics (name, status, origin, profile) "
        "VALUES (?, 'active', 'user', 'started three weeks ago')",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def test_learning_confirm_today_only(conn):
    # Arrange: an active topic with today's session row already written.
    # Act: confirm it through the Ring 1 act as tutor.
    # Assert: the session is completed and exactly one confirm event exists, no grace/reset.
    topic_id = _seed_active_topic(conn)
    today = db.today()
    learning.create_or_replace_session(conn, today, topic_id, "walk one case")
    out = acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)
    row = db.execute_query_or_whatever  # see note below
    session = learning.get_session(conn, today)
    assert session["status"] == "completed"
    events = conn.execute("SELECT kind FROM learning_streak_events").fetchall()
    assert [e["kind"] for e in events] == ["confirm"]


def test_learning_confirm_requires_a_session_row(conn):
    # Arrange: an active topic but no session row for today.
    # Act/Assert: confirming raises ActError rather than creating one.
    _seed_active_topic(conn)
    with pytest.raises(acts.ActError):
        acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)


def test_learning_confirm_is_reversible(conn):
    # Arrange: a confirmed session.
    # Act: undo the act.
    # Assert: the session reopens and its confirm event is gone.
    topic_id = _seed_active_topic(conn)
    today = db.today()
    learning.create_or_replace_session(conn, today, topic_id, "walk one case")
    out = acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)
    acts.undo_act(conn, out["act_id"])
    session = learning.get_session(conn, today)
    assert session["status"] == "open"
    assert conn.execute("SELECT COUNT(*) n FROM learning_streak_events").fetchone()["n"] == 0


def test_ring1_denies_learning_confirm_to_other_roles(conn):
    # Arrange: nothing (the grant table is static).
    # Act/Assert: every role but tutor is refused learning.confirm.
    with pytest.raises(acts.ActError):
        acts.learning_confirm(conn, role="coach", plane="nightly", thread_id=None)
```

(The stray line in `test_learning_confirm_today_only` above referencing
`db.execute_query_or_whatever` is not real code, delete it; the assertions
that matter are the two below it. This note exists because a spec that
silently "fixes" a copy-paste slip without flagging it is worse than one
that says so.)

### Verify

```bash
.venv/bin/python -m pytest tests/test_acts.py -q
```
Also confirm `POST /api/learning/sessions/today/confirm` by hand against a
seeded dev DB (`make seed`, then `curl -X POST localhost:8787/api/learning/sessions/today/confirm -d '{"topic_id": 1}' -H 'content-type: application/json'`) once a topic exists (§4-5 wire topic creation).

---

## 4. The instant-write exception: `chat_write_learning_profile`

The SPEC-v29 instant-write family (`chat_write_goal`, `chat_write_plan_block`,
`chat_write_note`, `chat_confirm_gym`, `chat_write_partner_task`, `write_fact`)
has one property this tool has to break: `chat_write_allow`'s docstring is
explicit that every role that can open a chat thread at all gets the same
set, because a goal write or a plan-block write isn't specialist-scoped. A
`profile` write is different, it flips a `learning_topics` row from
`clarifying` to `active`, a decision that only makes sense inside the one
conversation built to make it. A physician thread or a cfo thread has no
business ending a Learning onboarding.

So this is the family's **first role-scoped member**. By the time this
section is implemented, `INSTANT_WRITE_TOOLS` (`agents/runner.py:425-456`)
may already hold more than the six names shown above: SPEC-v41 §6.1 is a
prerequisite phase (see §0.1) and adds `"chat_write_task"` to this same set
first, as a plain non-role-scoped member. **Do not paste a literal
replacement set** : open `agents/runner.py`, read `INSTANT_WRITE_TOOLS`'s
actual current contents, and add `"chat_write_learning_profile"` to it
rather than retyping the whole set from scratch. Assuming SPEC-v41 §6.1 has
landed, it should read:

```python
INSTANT_WRITE_TOOLS = {
    "chat_write_goal", "chat_write_plan_block", "chat_write_note",
    "chat_confirm_gym", "chat_write_partner_task", "write_fact",
    "chat_write_task",
    "chat_write_learning_profile",
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

The new function body is written against the live `INSTANT_WRITE_TOOLS` set,
whatever it holds at build time, not the literal above: every non-health,
non-tutor role's return value is unchanged (the same set minus
`chat_write_learning_profile`); `tutor` gets that same set plus this one;
health roles still get the empty set. If SPEC-v41 §6.1 has not landed for
any reason, add `"chat_write_learning_profile"` to whatever
`INSTANT_WRITE_TOOLS` actually contains instead of copying the six-plus-one
literal above verbatim.

Add the tool itself, near `chat_write_partner_task` (`agents/runner.py:1648`):

```python
@tool("chat_write_learning_profile",
      "Instant-write (tutor-only): save the clarified working profile for a "
      "learning topic. If the topic is still 'clarifying', flips it to "
      "'active' so it becomes eligible for tomorrow's task. If it is already "
      "'active', just updates the profile text.",
      {"topic_id": int, "profile": str})
async def chat_write_learning_profile(args):
    try:
        topic_id = int(args.get("topic_id"))
    except (TypeError, ValueError):
        return _err("topic_id must be an integer")
    profile = (args.get("profile") or "").strip()
    if not profile:
        return _err("profile needs some text")
    conn = RUN["conn"]
    row = learning.get_topic(conn, topic_id)
    if row is None:
        return _err("topic not found")
    was_clarifying = row["status"] == "clarifying"
    conn.execute(
        "UPDATE learning_topics SET profile = ?, status = 'active' WHERE id = ?",
        (profile, topic_id),
    )
    conn.commit()
    label = f'Learning profile saved for "{row["name"]}"' + (", now active" if was_clarifying else "")
    _record_chat_write("chat_write_learning_profile", "personal", label, record_id=topic_id)
    return _text({"ok": True, "topic_id": topic_id, "label": label})
```

Add `chat_write_learning_profile` to `REGISTERED_TOOLS`
(`agents/runner.py:1678-1706`).

> **Law B2, Onboarding is inert until the profile lands.**
> A `clarifying` topic generates no task, appears on no rotation, and blocks
> nothing. The only thing that moves it to `active` is a model, inside a
> `tutor`-role thread, calling this one tool. There is no timer, no default,
> and no path that flips the status without it.

### Undo in `AgentChat.jsx`

`chat_write_learning_profile` writes a real row change (profile text +
status), so it needs an undo branch or Undo throws `'Nothing to undo for
this one.'`. There is no clean "undo" for a profile write in v1 (unlike
archiving a goal, there's no natural inverse that doesn't also lose the
onboarding work), add it to `reverseWrite` (`AgentChat.jsx:1158-1192`)
explicitly refusing with a clearer message rather than falling through to
the generic one:

```jsx
if (tool === 'chat_write_learning_profile') {
  throw new Error("Learning profiles can't be undone from here, edit the topic on the Learning page.")
}
```

### Tests

`tests/test_chat_runner.py` (append):

```python
def test_profile_write_is_tutor_only():
    # Arrange: nothing, chat_write_allow is pure.
    # Act: compute the instant-write set for tutor and for every other role.
    # Assert: only tutor's set contains chat_write_learning_profile.
    assert "chat_write_learning_profile" in runner.chat_write_allow("tutor")
    for role in runner.ALLOWLISTS:
        if role in ("tutor",) or role in runner.HEALTH_AGENT_ROLES:
            continue
        assert "chat_write_learning_profile" not in runner.chat_write_allow(role)
```

`tests/test_learning_runner.py` (new file, mirrors the `conn` fixture in
`tests/test_acts.py`):

```python
import asyncio
import pytest
from agents import runner
from core import db, learning


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed_clarifying(conn, name="python") -> int:
    learning.ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES (?, 'clarifying', 'user')",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def test_chat_write_learning_profile_activates_topic(conn):
    # Arrange: a clarifying topic and a fake RUN context pointed at it.
    # Act: call the tool with a real profile.
    # Assert: the topic flips to active and carries the new profile text.
    topic_id = _seed_clarifying(conn)
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor"})
    try:
        out = asyncio.run(runner.chat_write_learning_profile.handler(
            {"topic_id": topic_id, "profile": "beginner, wants to drill market sizing"}
        ))
    finally:
        runner._RUN_CONTEXT.reset(token)
    row = learning.get_topic(conn, topic_id)
    assert row["status"] == "active"
    assert "market sizing" in row["profile"]
```

(If `runner._RUN_CONTEXT` is not directly settable this way in the actual
`RUN` proxy implementation, use whatever harness `tests/test_acts.py` or
`tests/test_chat_runner.py` already uses to populate `RUN` for a bare tool
call, grep those files for the pattern before writing this test, since the
`_RunProxy`/`ContextVar` shape is internal and this spec's job is to name
the behaviour to assert, not to guess at every private plumbing detail.)

### Verify

```bash
.venv/bin/python -m pytest tests/test_chat_runner.py tests/test_learning_runner.py -q
```

---

## 5. Topic management and the nightly write

### 5.1 Onboarding: Ian types a name, the tutor asks before it acts

"Add a topic" (§7.2) takes a topic name, creates a `learning_topics` row
(`status='clarifying'`, `origin='user'`, `profile=''`), and opens a consult
thread scoped to `tutor`, seeded via the exact `consultRequest` mechanism
SPEC-v37 §7.3 built and SPEC-v40 kept:

```js
{ role: 'tutor', seedText: `I want to get better at ${name}.` }
```

No `view` key (§0.1). No second seeding path. On the phone the thread opens
as the whole screen (SPEC-v40 §2.1). The tutor's `## Chat` section (§1.1)
instructs it to ask before generating anything: current level, what "better"
actually means to Ian for this specific thing, what he's already tried. When
satisfied, it calls `chat_write_learning_profile` (§4) and says so plainly.

### 5.2 `read_learning` (Ring 0)

Add to `agents/runner.py`, near the other `read_*` tools:

```python
@tool("read_learning",
      "Active learning topics with their working profile, recent session "
      "history, and current streak state. Args: none.", {})
async def read_learning(args):
    conn = RUN["conn"]
    _record_interactive_read("read_learning")
    today = date.fromisoformat(db.today())
    active = learning.active_topics(conn)
    clarifying = learning.clarifying_topics(conn)
    since = (today - timedelta(days=14)).isoformat()
    rows = conn.execute(
        """SELECT s.date, s.topic_id, t.name AS topic_name, s.status,
                  (s.task_prompt = '') AS self_logged
           FROM learning_sessions s
           LEFT JOIN learning_topics t ON t.id = s.topic_id
           WHERE s.date >= ?
           ORDER BY s.date DESC""",
        (since,),
    ).fetchall()
    streak = learning.compute(conn, today)
    return _text({
        "active_topics": [
            {"id": t["id"], "name": t["name"], "profile": t["profile"]}
            for t in active
        ],
        "clarifying_topics": [
            {"id": t["id"], "name": t["name"]} for t in clarifying
        ],
        "recent_sessions": [dict(r) for r in rows],
        "streak": streak,
    })
```

Add `read_learning` to `REGISTERED_TOOLS`. It is already in
`ALLOWLISTS["tutor"]` and `ALLOWLISTS["chief"]` (§1.2), so no further
allowlist edit is needed. Precomputed date math (`since`, `today`) in
Python, the law every nightly read tool follows.

### 5.3 `write_learning_task` (nightly, tutor-only) and topic selection

The rotation is **pure Python, not a model decision**. In
`agents/runner.py::build_user_prompt` (wherever it branches on `role` to add
role-specific prompt content, follow the pattern already used for `coach`'s
gym note, `agents/runner.py:1897` `if role == "coach" and ...`), add:

```python
def _select_learning_topic(conn) -> dict | None:
    """Least-recently-featured active topic. A topic that has never been
    featured sorts first (NULL last_featured_date treated as earliest)."""
    topics = learning.active_topics(conn)
    if not topics:
        return None
    return min(topics, key=lambda t: t.get("last_featured_date") or "")
```

And, inside `build_user_prompt` where `role == "tutor"`:

```python
if role == "tutor":
    learning.skip_stale_sessions(conn, db.today())
    topic = _select_learning_topic(conn)
    RUN["learning_topic_id"] = topic["id"] if topic else None
    if topic:
        lines.append(
            f"Tonight's topic: {topic['name']}\nProfile: {topic['profile'] or '(no profile yet)'}"
        )
    else:
        lines.append(
            "No active learning topics tonight (none active, or all still "
            "mid-onboarding). Nothing to rotate; write nothing."
        )
```

`skip_stale_sessions` runs before topic selection every night, closing
yesterday's still-`open` row before tonight's write, per the 2026-09-02
decision (§0.1). Add `"learning_topic_id": None` to `_new_run_state()`'s
default dict (`agents/runner.py:459-469`) so the key always exists and is
`None` outside a `tutor` run.

The tool the model actually calls takes no topic argument:

```python
@tool("write_learning_task",
      "Write tomorrow's practice task for the topic you were given tonight. "
      "One concrete exercise, not a lecture.", {"task_prompt": str})
async def write_learning_task(args):
    topic_id = RUN.get("learning_topic_id")
    if topic_id is None:
        return _err("no active topic to write for")
    task_prompt = (args.get("task_prompt") or "").strip()
    if not task_prompt:
        return _err("task_prompt needs text")
    tomorrow = (date.fromisoformat(db.today()) + timedelta(days=1)).isoformat()
    row = learning.create_or_replace_session(RUN["conn"], tomorrow, topic_id, task_prompt)
    return _text({"ok": True, "session_id": row["id"]})
```

Add `write_learning_task` to `REGISTERED_TOOLS`.

**Zero active topics is not an error.** If `_select_learning_topic` returns
`None`, the prompt tells the model there is nothing to rotate and it writes
nothing, same "no data" lane `coach.md` documents for a health-log-free
stretch.

### 5.4 Mr. Miyagi may suggest a topic, never create one

Ordinary `create_proposal(kind="task", ...)` from the tutor's own prompt
instructions (§1.1 Rules), no new proposal kind, no new column linking a
proposal to a topic row. Approving any proposal in this codebase never
triggers an automated downstream write; the UI's "Start this topic"
affordance (§7.2) just prefills "Add a topic"'s name field from the
proposal's `action` text, and if Ian follows through the resulting
`POST /api/learning/topics` call carries `origin: "agent_proposed"`. The
clarification conversation (§5.1) still runs in full before it goes live.

### 5.5 Tests

`tests/test_learning_runner.py` (append):

```python
def test_clarifying_topic_generates_no_task(conn):
    # Arrange: one clarifying topic and one active topic.
    # Act: select tonight's topic.
    # Assert: only the active one is ever eligible.
    _seed_clarifying(conn, "ai")
    active_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('python', 'active', 'user')"
    ).lastrowid
    conn.commit()
    picked = runner._select_learning_topic(conn)
    assert picked["id"] == active_id


def test_zero_active_topics_is_not_an_error(conn):
    # Arrange: no topics at all.
    # Act: select tonight's topic.
    # Assert: None, not an exception.
    assert runner._select_learning_topic(conn) is None


def test_least_recently_featured_topic_is_picked(conn):
    # Arrange: two active topics, one featured yesterday, one never featured.
    # Act: select tonight's topic.
    # Assert: the never-featured one wins (NULL sorts first).
    a = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('a', 'active', 'user')"
    ).lastrowid
    b = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('b', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-08-30", a, "did a rep")
    picked = runner._select_learning_topic(conn)
    assert picked["id"] == b
```

`tests/test_learning.py` (append):

```python
def test_learning_session_date_unique(conn):
    # Arrange: a topic and a first written task for tomorrow.
    # Act: write a second task for the same date.
    # Assert: still one row, now carrying the second write's content.
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('python', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "first draft")
    learning.create_or_replace_session(conn, "2026-09-05", topic_id, "second draft")
    rows = conn.execute("SELECT * FROM learning_sessions WHERE date = '2026-09-05'").fetchall()
    assert len(rows) == 1
    assert rows[0]["task_prompt"] == "second draft"


def test_skip_stale_sessions_marks_only_old_open_rows(conn):
    # Arrange: an old open row, an old completed row, and today's open row.
    # Act: skip stale sessions as of today.
    # Assert: only the old open row flips to skipped.
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('ai', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-09-01", topic_id, "old open")
    learning.confirm_session(conn, "2026-08-31", topic_id=topic_id)
    learning.create_or_replace_session(conn, "2026-09-03", topic_id, "today")
    changed = learning.skip_stale_sessions(conn, "2026-09-03")
    assert changed == 1
    assert learning.get_session(conn, "2026-09-01")["status"] == "skipped"
    assert learning.get_session(conn, "2026-08-31")["status"] == "completed"
    assert learning.get_session(conn, "2026-09-03")["status"] == "open"
```

### Verify

```bash
.venv/bin/python -m pytest tests/test_learning.py tests/test_learning_runner.py -q
```

---

## 6. Pillar routing: no schema widening

> **Law B3, A pillar is a filter, never a column.**
> Learning is a *view* over existing `personal`-domain goals and facts, the
> same way partner and life already are. It never becomes a fifth value on
> `goals.domain`'s CHECK constraint.

`goals.domain` is a SQLite `CHECK` constraint (`core/db.py`'s live rebuild
DDL, `_migrate_goals_school_domain`, is the authoritative shape today:
`CHECK (domain IN ('business','health','personal','finance','school'))`).
SQLite cannot `ALTER` a `CHECK`, widening one means a full table rebuild
that must carry every already-ALTERed column (`chat_threads.model`'s scar
tissue, per CLAUDE.md). `core/pillars.py` already solved this exact problem
twice (partner vs life). Learning is the identical move a third time.

### 6.1 `core/pillars.py`

Add the helper, next to `is_partner_goal` (`core/pillars.py:30-33`):

```python
def is_learning_goal(goal: dict) -> bool:
    notes = (goal.get("notes") or "").lower()
    name = (goal.get("name") or "").lower()
    return "#learning" in notes or "learning:" in notes
```

Edit `goals_for_pillar` (`core/pillars.py:36-49`). The current `life` branch
(`domain == "personal" and not is_partner_goal(g)`) must also exclude
`is_learning_goal(g)`, the same three-way split partner/life already needed
when partner carved itself out of `personal`. **Trap:** the `school` branch
below (`domain in ("school", "college")`) is this spec's own assumption
about what that branch looked like, not a verified read of the live file:
as actually shipped, `core/pillars.py`'s `school` branch is
`domain == "school"` only, since `goals.domain`'s CHECK constraint has never
allowed `"college"` a goal could carry that value. Copy the function body
below for the `partner`/`life`/`learning` edits, but keep the `school` branch
whatever the live file actually has, don't paste a `college` widening this
spec never had a reason to introduce:

```python
def goals_for_pillar(goals: list[dict], pillar: str) -> list[dict]:
    if pillar == "btc":
        return [g for g in goals if g.get("domain") == "business"]
    if pillar == "body":
        return [g for g in goals if g.get("domain") == "health"]
    if pillar == "partner":
        return [g for g in goals if g.get("domain") == "personal" and is_partner_goal(g)]
    if pillar == "school":
        return [g for g in goals if g.get("domain") in ("school", "college")]
    if pillar == "life":
        return [
            g for g in goals
            if g.get("domain") == "personal"
            and not is_partner_goal(g)
            and not is_learning_goal(g)
        ]
    if pillar == "learning":
        return [g for g in goals if g.get("domain") == "personal" and is_learning_goal(g)]
    if pillar == "money":
        return [g for g in goals if g.get("domain") == "finance"]
    return []
```

(Written out in full because this function's `if`-chain shape means the
`life` branch's edit is easy to get wrong by pattern-matching the wrong
line, copy this whole function body rather than patching one clause.)

Add `"learning"` to `PILLAR_ORDER` (`core/pillars.py:9`), placed with the
other `personal`-domain pillars rather than at the end:

```python
PILLAR_ORDER = ("btc", "body", "partner", "school", "life", "learning", "money")
```

Add to `PILLAR_META` (`core/pillars.py:11-18`):

```python
PILLAR_META["learning"] = {"label": "Learning", "icon": "✎", "domains": ("personal",)}
```

(`PILLAR_META` is a plain dict in the file; add this line after the
existing literal dict or fold it into the dict literal directly, either way, the key must exist before `compute_pillars` runs.)

Edit `compute_pillars` (`core/pillars.py:112-171`): add a `learning` branch
using the same shape as `body`'s gym-streak `detail` line
(`f"{gym.get('streak', 0)}d streak"`), reading Learning's own streak instead,
and forcing status the way `partner`'s branch does:

```python
if pillar_id == "learning":
    from core import learning as learning_mod
    streak_state = learning_mod.compute(conn)
    detail = f"{streak_state['streak']}d streak"
    st = "ON TRACK"
```

Wire this into whichever per-pillar `if`/`elif` chain `compute_pillars`
already uses for `body`/`partner` (follow that exact structure; the function
signature `compute_pillars(conn, goals, focus, partner_tasks, fin, gym)`
already receives `conn`, so no new parameter is needed, Learning is the
first pillar branch to query its own table directly inside
`compute_pillars` rather than only reading a pre-passed dict, which is fine
since `conn` is already in scope).

### 6.2 `core/db.py`: `NAMESPACE_DOMAINS`

Add one entry, the same move `training` made to route into `health`:

```python
NAMESPACE_DOMAINS["learning"] = "personal"
```

So a fact topic like `learning:python` (Mr. Miyagi's own memory of what he's
noticed about a topic over time, written via `write_fact`, already
universal, unaffected by §4's role-scoping since that only touches
`chat_write_learning_profile`) resolves to `domain_for_topic("learning:python", default) == "personal"`
with zero changes to `FACT_DOMAINS`.

### 6.3 `dashboard/src/lib/pillars.js`

Mirror every edit above in the JS copy (`pillars.js`, 39 lines total):

```js
export const PILLAR_ORDER = ['btc', 'body', 'partner', 'school', 'life', 'learning', 'money']

export function isLearningGoal(goal) {
  const notes = (goal.notes || '').toLowerCase()
  const name = (goal.name || '').toLowerCase()
  return notes.includes('#learning') || notes.includes('learning:')
}

export function goalsForPillar(goals, pillar) {
  if (pillar === 'btc') return goals.filter(g => g.domain === 'business')
  if (pillar === 'body') return goals.filter(g => g.domain === 'health')
  if (pillar === 'partner') return goals.filter(g => g.domain === 'personal' && isPartnerGoal(g))
  if (pillar === 'school') return goals.filter(g => g.domain === 'school')
  if (pillar === 'life') return goals.filter(g => g.domain === 'personal' && !isPartnerGoal(g) && !isLearningGoal(g))
  if (pillar === 'learning') return goals.filter(g => g.domain === 'personal' && isLearningGoal(g))
  if (pillar === 'money') return goals.filter(g => g.domain === 'finance')
  return []
}

export function defaultDomainForPillar(pillar) {
  const map = { btc: 'business', body: 'health', partner: 'personal', school: 'school', life: 'personal', learning: 'personal', money: 'finance' }
  return map[pillar] || 'business'
}
```

**Trap:** this is the exact "a fix on one input surface must reach the
other" case CLAUDE.md warns about, `core/pillars.py` and
`dashboard/src/lib/pillars.js` are two hand-kept mirrors with no shared
source. Editing one and not the other ships a page that filters goals
differently than the agents who read the same goals overnight.

### 6.4 Tests

`tests/test_gym_pillars.py` (append, the existing home for `compute_pillars`
tests):

```python
def test_no_new_goal_or_fact_domain():
    # Arrange: nothing, these are static tables.
    # Act: read db.DOMAINS and db.FACT_DOMAINS.
    # Assert: neither gained a 'learning' value; routing goes through NAMESPACE_DOMAINS instead.
    assert "learning" not in db.DOMAINS
    assert "learning" not in db.FACT_DOMAINS
    assert db.NAMESPACE_DOMAINS["learning"] == "personal"


def test_life_goal_excludes_learning_goal():
    # Arrange: one personal goal tagged #learning and one plain personal goal.
    # Act: split personal goals into life vs learning.
    # Assert: the tagged goal appears only under learning, never life.
    goals = [
        {"domain": "personal", "notes": "#learning", "name": "Finish Python course"},
        {"domain": "personal", "notes": "", "name": "Renew passport"},
    ]
    life = pillars.goals_for_pillar(goals, "life")
    learn = pillars.goals_for_pillar(goals, "learning")
    assert [g["name"] for g in learn] == ["Finish Python course"]
    assert [g["name"] for g in life] == ["Renew passport"]


def test_learning_pillar_status_never_off_track(conn):
    # Arrange: an empty (no-streak) learning state.
    # Act: compute pillars.
    # Assert: the learning pillar's status is always ON TRACK, matching partner's precedent.
    out = pillars.compute_pillars(conn, [], {"goal_ids": [], "domains": []}, [], {}, {"streak": 0})
    # compute_pillars returns a dict keyed by pillar id, not {"pillars": [...]}
    # (verified against tests/test_gym_pillars.py's own working call, the
    # ground truth this spec's prose got wrong).
    assert out["learning"]["status"] == "ON TRACK"
```

(Adjust the `compute_pillars` call's exact positional/keyword shape to match
whatever `tests/test_gym_pillars.py:56-62`'s existing call already uses, copy that call's argument shape rather than inventing a new one, since the
signature in this spec's prose is a description, and the test file's own
working call is the ground truth for exact argument order.)

### Verify

```bash
.venv/bin/python -m pytest tests/test_gym_pillars.py -q
cd dashboard && npm test
```

---

## 7. UI: `dashboard/src/pages/LearningPage.jsx`

### 7.1 Wiring

`dashboard/src/components/Nav.jsx`: one entry in `ALL_LINKS` (`:6-21`),
placed after `life` and before `money` to match `PILLAR_ORDER`:

```js
{ id: 'learning', label: 'Learning', short: 'Learn', icon: '✎', section: 'pillars' },
```

One entry in `ALL_MOBILE_MORE` (`:24-25`), between `'life'` and `'money'`:

```js
export const ALL_MOBILE_MORE = ['body', 'school', 'life', 'learning', 'money', 'inbox', 'log', 'memory', 'notes', 'roster', 'journal']
```

Learning sits behind the More sheet exactly like Body/School/Life/Money
already do; it is not one of the five fixed tabs (`MOBILE_PRIMARY` stays
`['home', 'plan', 'btc', 'partner']`, unchanged).

`dashboard/src/App.jsx`: add `'learning'` to `PAGES` (`:37`), between
`'life'` and `'money'`:

```js
const PAGES = ['home', 'plan', 'btc', 'body', 'partner', 'school', 'schoolnotebook', 'life', 'learning', 'money', 'moneyhistory', 'memory', 'inbox', 'log', 'notes', 'goals', 'journal', 'roster', 'shutdown']
```

Import `LearningPage` at the top of `App.jsx` next to the other page
imports, and add a render branch following the same
`{page === 'x' && (<XPage .../>)}` chain every other page uses
(`App.jsx:1128-1214`), placed next to the `life` branch:

```jsx
{page === 'learning' && (
  <LearningPage state={state} refresh={refresh} toast={toast} requestConsult={requestConsult} />
)}
```

`requestConsult` is already defined in `App.jsx` (`:809-811`) and is the
same function every other consult-triggering surface uses; no new hand-off
mechanism.

### 7.2 API: `/api/state` gains a `learning` projection

Add a helper to `api/main.py`, near the other per-domain state builders:

```python
def _learning_state(conn) -> dict:
    today = db.today()
    topics = learning.active_topics(conn)
    session = learning.get_session(conn, today)
    streak = learning.compute(conn, date.fromisoformat(today))
    return {
        "topics": [
            {
                "id": t["id"],
                "name": t["name"],
                "confirmed_count": learning.confirmed_session_count(conn, t["id"]),
            }
            for t in topics
        ],
        "today": session,
        "streak": streak,
    }
```

Add `"learning": _learning_state(conn),` to the big `/api/state` response
dict, next to `"garden": garden.garden_state(conn)` (`api/main.py:980-981`).

### 7.3 Two new REST endpoints

```python
class LearningTopicIn(BaseModel):
    name: str
    origin: str = "user"


@app.post("/api/learning/topics")
def create_learning_topic(body: LearningTopicIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "topic needs a name")
    origin = body.origin if body.origin in ("user", "agent_proposed") else "user"
    conn = db.connect()
    try:
        learning.ensure_schema(conn)
        try:
            cur = conn.execute(
                "INSERT INTO learning_topics (name, status, origin, profile) "
                "VALUES (?, 'clarifying', ?, '')",
                (name, origin),
            )
        except Exception as exc:
            raise HTTPException(409, "a topic with that name already exists") from exc
        conn.commit()
        return {
            "ok": True,
            "topic_id": cur.lastrowid,
            "consultRequest": {"role": "tutor", "seedText": f"I want to get better at {name}."},
        }
    finally:
        conn.close()


@app.patch("/api/learning/topics/{topic_id}/archive")
def archive_learning_topic(topic_id: int):
    conn = db.connect()
    try:
        learning.ensure_schema(conn)
        row = conn.execute("SELECT id FROM learning_topics WHERE id = ?", (topic_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "topic not found")
        conn.execute(
            "UPDATE learning_topics SET status = 'archived', "
            "archived_at = datetime('now','localtime') WHERE id = ?",
            (topic_id,),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
```

`POST /api/learning/topics`'s `consultRequest` field carries no `view`
key (§0.1). The frontend passes it straight to `requestConsult()`.

### 7.4 Content and markup

- **Topic cards**, name plus a per-topic growth visual (`GrowthMark`, §8).
  Streak state is shown at the page level (via the featured row and the
  pulse-adjacent chip pattern already used elsewhere), never per-card as a
  raw number, a direct instruction from CLAUDE.md's inherited product law:
  never a percentage, never a raw number framed as a verdict.
- **"Today's practice"**, the one featured task, rendered as Learning's own
  row (`.today-row`, `.today-row--practice`, defined by this spec in §8.1,
  not borrowed wholesale from Life's Today list). Life's `.task-row`
  (SPEC-v41 §4.5.1) is a checkbox-plus-priority-toggle row built for a
  to-do; Learning's row opens a chat thread instead and has neither a
  checkbox nor a priority toggle, so the two rows are visually related but
  structurally different components, not one shared idiom. It carries a
  `Practice` label instead of a checkbox (it is a thread, not a tick). In
  the zero-topics lane the row is absent and the page shows the
  `Add a topic` field alone; no other copy (SPEC-v41 §3). Tapping it opens
  or resumes today's session thread via `consultRequest`, if
  `learning_sessions.thread_id` is already set, the seed carries no text and
  the thread simply resumes (native session resume); on the first open, the
  seed hands the tutor the day's `task_prompt`.
- **"Add a topic"**, a single-field entry point, visually matching the
  "Describe it" field SPEC-v41 §5.1 builds for `GoalSheet`. That field is a
  bare `<textarea>` inside `<label className="gf-field gf-grow">` with no
  class of its own on the textarea (verified against SPEC-v41's
  `GoalSheet.jsx`), so the class to reuse is `gf-field gf-grow` (also used by
  `GoalForm.jsx`), not a `gs-describe-field` that does not exist anywhere in
  SPEC-v41. Verify the real class in `GoalSheet.jsx` once SPEC-v41 ships and
  reconcile per §0.1 if it has since changed. Without the Draft button:
  Enter creates the `clarifying` row and opens the thread.
- A **"suggested by Mr. Miyagi"** card on any pending Learning-kind
  proposal (`state.pending_proposals` filtered to `role === 'tutor'`,
  `status === 'PENDING'`, `kind === 'task'` — `/api/state` has never carried
  a plain `proposals` key, only `pending_proposals`; check the real key
  before writing a client read), matching how proposals surface
  elsewhere, a small card, not a modal, with a "Start this topic" button
  that prefills the composer's name field and, on submit, sends
  `origin: 'agent_proposed'`.

```jsx
// dashboard/src/pages/LearningPage.jsx
import { useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import GrowthMark from '../components/GrowthMark.jsx'

function SuggestedTopicCard({ proposal, onStart }) {
  return (
    <div className="learning-suggested-card glass-card glass-card-pad">
      <span className="section-label">Suggested by Mr. Miyagi</span>
      <p className="learning-suggested-text">{proposal.action}</p>
      <button className="btn ghost" onClick={() => onStart(proposal.action)}>
        Start this topic
      </button>
    </div>
  )
}

function TopicCard({ topic, onOpen }) {
  return (
    <button className="learning-topic-card glass-card glass-card-pad" onClick={onOpen}>
      <GrowthMark count={topic.confirmed_count} />
      <span className="learning-topic-name">{topic.name}</span>
    </button>
  )
}

export default function LearningPage({ state, refresh, toast, requestConsult }) {
  const [name, setName] = useState('')
  const [pendingOrigin, setPendingOrigin] = useState('user')
  const [busy, setBusy] = useState(false)
  const reduced = useReducedMotion()
  const learningState = state.learning || { topics: [], today: null, streak: { streak: 0, stools: 2 } }
  const suggested = (state.pending_proposals || []).filter(
    (p) => p.role === 'tutor' && p.status === 'PENDING' && p.kind === 'task'
  )

  function startFromSuggestion(actionText) {
    setName(actionText)
    setPendingOrigin('agent_proposed')
  }

  async function addTopic(e) {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    try {
      const out = await api('/api/learning/topics', 'POST', { name: trimmed, origin: pendingOrigin })
      setName('')
      setPendingOrigin('user')
      refresh?.()
      requestConsult?.(out.consultRequest)
    } catch (err) {
      toast?.(err.message || 'could not add topic', 'crit')
    } finally {
      setBusy(false)
    }
  }

  function openToday() {
    const today = learningState.today
    requestConsult?.({
      role: 'tutor',
      seedText: today?.thread_id ? '' : (today?.task_prompt || ''),
    })
  }

  const todayOpen = learningState.today && learningState.today.status !== 'completed'

  return (
    <div className="learning-page page-stack">
      {todayOpen && (
        <motion.button
          type="button"
          className="today-row today-row--practice"
          onClick={openToday}
          initial={reduced ? false : { opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
        >
          <span className="today-row-check today-row-check--practice">Practice</span>
          <span className="today-row-title">
            {learningState.today.task_prompt || "Continue today's session"}
          </span>
        </motion.button>
      )}

      {learningState.topics.length > 0 && (
        <div className="learning-topics">
          {learningState.topics.map((t) => (
            <TopicCard
              key={t.id}
              topic={t}
              onOpen={() => requestConsult?.({ role: 'tutor', seedText: '' })}
            />
          ))}
        </div>
      )}

      {suggested.map((p) => (
        <SuggestedTopicCard key={p.id} proposal={p} onStart={startFromSuggestion} />
      ))}

      <form className="learning-add glass-card glass-card-pad" onSubmit={addTopic}>
        <textarea
          className="gf-field gf-grow learning-add-field"
          rows={1}
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              addTopic(e)
            }
          }}
          placeholder="Add a topic"
          disabled={busy}
        />
      </form>
    </div>
  )
}
```

### Verify

```bash
cd dashboard && npm test && npm run build
```
Browser: 375x667 with 47/34 insets (`resize_window` preset mobile,
`colorScheme` as needed), Learning reachable via More sheet, composer
reachable without scrolling past the fold, `Add a topic` field alone with no
line beneath it when there are zero topics. Then 1512px desktop, Learning
in the desktop nav rail, no dead gutter (`--content-w-wide`).

---

## 8. Delight

- **A per-topic growth visual that only ever grows.** Named component:
  `dashboard/src/components/GrowthMark.jsx`. Stages are keyed to cumulative
  confirmed sessions for that topic (`confirmed_count` from §7.2's state
  projection, backed by `learning.confirmed_session_count`, §2.4), never
  off the streak, which can legitimately reset. Exact thresholds, mirroring
  the shape of `core/garden.py`'s `STAGE_THRESHOLDS = (0, 1, 3, 6, 9, 12)`
  (floor stage 1, cap stage 5) without calling into `core/garden.py` itself, Learning's growth mark is a separate, frontend-only concept, never a
  second consumer of Body's Garden state:

  ```jsx
  // dashboard/src/components/GrowthMark.jsx
  import { useEffect, useRef, useState } from 'react'
  import { motion, useReducedMotion } from 'motion/react'

  export const GROWTH_STAGE_THRESHOLDS = [0, 1, 3, 6, 9, 12]

  export function growthStage(count) {
    let stage = 1
    for (let i = 1; i < GROWTH_STAGE_THRESHOLDS.length; i++) {
      if (count >= GROWTH_STAGE_THRESHOLDS[i]) stage = i + 1
    }
    return Math.min(stage, 5)
  }

  const STAGE_PATHS = {
    1: 'M12 20 L12 16',
    2: 'M12 20 L12 13 M12 13 L9 10',
    3: 'M12 20 L12 10 M12 13 L9 10 M12 13 L15 10',
    4: 'M12 20 L12 7 M12 12 L8 9 M12 12 L16 9 M12 8 L9 5',
    5: 'M12 20 L12 4 M12 11 L7 8 M12 11 L17 8 M12 7 L8 4 M12 7 L16 4',
  }

  export default function GrowthMark({ count = 0 }) {
    const stage = growthStage(count)
    const reduced = useReducedMotion()
    const prevStage = useRef(stage)
    const [pop, setPop] = useState(false)

    useEffect(() => {
      if (stage > prevStage.current) {
        setPop(true)
        const t = setTimeout(() => setPop(false), 320)
        prevStage.current = stage
        return () => clearTimeout(t)
      }
      prevStage.current = stage
    }, [stage])

    return (
      <motion.svg
        className="growth-mark"
        viewBox="0 0 24 24" width="20" height="20"
        animate={pop && !reduced ? { scale: [1, 1.22, 1] } : { scale: 1 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        aria-hidden="true"
      >
        <path d={STAGE_PATHS[stage]} stroke="var(--health)" strokeWidth="1.6"
              strokeLinecap="round" fill="none" />
      </motion.svg>
    )
  }
  ```

  No number is printed next to it. Ian is told once (in the onboarding
  thread's closing message, per the tutor's `## Chat` instructions) what it
  means and then it's simply there, the same "no label, generous space, it
  just IS there" treatment `core/garden.py`'s Body visual already gets.

- **A brief reveal when today's task first appears.** The `today-row`'s
  `initial`/`animate` in §7.4's JSX (`opacity 0, y:-6 -> opacity 1, y:0`,
  280ms, house easing `[0.22, 1, 0.36, 1]`) is that reveal, no new timing
  constant, reusing the same window (200-320ms) and easing curve `Sheet.jsx`
  and every other reveal in this codebase already uses. `useReducedMotion()`
  guards it exactly as `Sheet.jsx` does (`initial={false}` when reduced).
  When a session is confirmed, the row takes a strike-through draw (200ms,
  left to right) matching SPEC-v41 Phase 3's real one, which lands on
  `.task-row.completing .task-title::after` (`.task-row` is Life's Today
  checkbox row, not `.today-row`, so there is no shared class to hook here).
  Learning does not share that selector, since `.today-row-title` is its own
  element on its own component: define the equivalent transition directly
  on `.today-row-title` in §8.1's CSS, using the same 200ms duration and
  house easing curve rather than inventing a new timing constant. `GrowthMark`'s
  `pop` state advances one step in the same 320ms beat, so the two motions
  read as cause and effect.

- **Completion copy that names what actually happened, never "Great job!".**
  Enforced as prompt law in `agents/roles/tutor.md`'s `## Chat` section
  (§1.1), the same anti-slop discipline `strip_em_dashes()` enforces
  mechanically elsewhere, applied here because "specific praise" isn't a
  pattern a regex can catch the way an em dash is.

### 8.1 CSS

Add to `dashboard/src/styles.css`. Mobile-first block (inside the existing
`@media (max-width: 900px)` block, or as the unqualified base rules that
block already layers on top of, follow whichever pattern the file already
uses for a page-scoped class, e.g. `.partner-page`'s base rules at `:2327`):

```css
.learning-page { display: flex; flex-direction: column; gap: var(--s4); }

.today-row {
  display: flex; align-items: center; gap: var(--s3);
  min-height: 44px; padding: var(--s2) var(--s3);
  border-radius: var(--radius-sm);
  background: var(--glass); border: 1px solid var(--glass-border);
  width: 100%; text-align: left; cursor: pointer;
}
.today-row-check--practice {
  flex: 0 0 auto; font: 500 var(--t-xs) var(--sans); letter-spacing: var(--label-tracking);
  text-transform: uppercase; color: var(--accent);
  border: 1px solid var(--accent-dim); border-radius: var(--radius-sm);
  padding: 2px var(--s2);
}
.today-row-title {
  position: relative; font: 500 var(--t-sm) var(--sans); color: var(--ink);
}
/* Strike-through on confirm: same 200ms/easing as SPEC-v41's
   .task-row.completing .task-title::after, defined fresh here because
   .today-row-title is its own element on its own component, not a shared
   selector with Life's checkbox row. */
.today-row-title::after {
  content: ''; position: absolute; left: 0; top: 50%; height: 1px;
  width: 0; background: var(--ink); transition: none;
}
.today-row.completing .today-row-title::after {
  width: 100%; transition: width 200ms var(--ease-house, cubic-bezier(0.22, 1, 0.36, 1));
}

.learning-topics {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--s3);
}
.learning-topic-card {
  display: flex; align-items: center; gap: var(--s2);
  text-align: left; cursor: pointer; min-height: 44px;
}
.learning-topic-name { font: 500 var(--t-sm) var(--sans); color: var(--ink); }

.learning-suggested-card { display: flex; flex-direction: column; gap: var(--s2); }
.learning-suggested-text { color: var(--dim); font-size: var(--t-sm); margin: 0; }

.learning-add-field {
  width: 100%; min-height: 44px; resize: none;
  background: transparent; border: none; color: var(--ink);
  font: 400 16px var(--sans); /* 16px: iOS zoom-jacking law, osui L10 */
}
.learning-add-field:focus { outline: none; }

.growth-mark { flex: 0 0 auto; }

@media (prefers-reduced-motion: reduce) {
  .today-row, .learning-topic-card, .growth-mark { transition: none !important; }
}
```

Desktop enhancement block, inside `@media (min-width: 901px)`:

```css
@media (min-width: 901px) {
  .learning-page { max-width: var(--content-w-wide); }
  .learning-topics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .today-row { max-width: 640px; }
}
```

**Trap:** the mobile tab bar rule (`.nav-mobile { display: none }`) must
stay inside `@media (min-width: 901px)` only, nothing in this section
touches `Nav.jsx`'s CSS, but if a future edit ever adds a Learning-specific
nav override, it must follow the same rule or the phone loses navigation
entirely (this shipped once, per CLAUDE.md).

### 8.2 Tests

**Trap:** the two test files below are written against `@testing-library/react`
(`render`, `fireEvent`, `screen`), which is not a dependency of this project
as shipped: `dashboard/package.json` has no such entry, and every existing
`*.ui.test.jsx` file (`goal-sheet.ui.test.jsx`, `command-page.ui.test.jsx`,
...) uses `react-dom/client`'s `createRoot` + React's `act`, plus manual
`document.querySelector` DOM queries, instead. Write these two files against
that real idiom, not the RTL calls shown here; the assertions (what gets
called with what, what text renders) are the actual spec, the exact query
API is not. Also fix `baseState()`'s `proposals: []` to `pending_proposals: []`
to match `/api/state`'s real key (§7.4's own trap, repeated here since these
tests build the same shape).

`dashboard/tests/growth-mark.ui.test.jsx` (new file, vitest + jsdom, the
`*.ui.test.jsx` pattern):

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import GrowthMark, { growthStage } from '../src/components/GrowthMark.jsx'

describe('growthStage', () => {
  it('test_growth_stage_floors_at_one_and_caps_at_five', () => {
    // Arrange: the exact threshold boundaries.
    // Act: compute the stage at each boundary and past the top.
    // Assert: 0 confirms is stage 1, 12+ confirms is stage 5, never higher.
    expect(growthStage(0)).toBe(1)
    expect(growthStage(1)).toBe(2)
    expect(growthStage(3)).toBe(3)
    expect(growthStage(6)).toBe(4)
    expect(growthStage(9)).toBe(5)
    expect(growthStage(999)).toBe(5)
  })
})

describe('GrowthMark', () => {
  it('test_growth_mark_respects_reduced_motion', () => {
    // Arrange: matchMedia mocked to report reduced motion (setup-ui.js default).
    // Act: render GrowthMark at a fixed count.
    // Assert: it renders the stage path without throwing under the reduced-motion stub.
    const { container } = render(<GrowthMark count={4} />)
    expect(container.querySelector('svg.growth-mark')).toBeTruthy()
  })
})
```

`dashboard/tests/learning-page.ui.test.jsx` (new file):

```jsx
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent, screen } from '@testing-library/react'
import LearningPage from '../src/pages/LearningPage.jsx'

function baseState(overrides = {}) {
  return { learning: { topics: [], today: null, streak: { streak: 0, stools: 2 } }, proposals: [], ...overrides }
}

describe('LearningPage', () => {
  it('test_zero_topics_shows_only_the_composer', () => {
    // Arrange: state with no topics and no today session.
    // Act: render the page.
    // Assert: the add-a-topic field is present and no other copy renders.
    render(<LearningPage state={baseState()} />)
    expect(screen.getByPlaceholderText('Add a topic')).toBeTruthy()
    expect(screen.queryByText(/no active topic/i)).toBeNull()
  })

  it('test_today_row_opens_consult_with_seed_text', () => {
    // Arrange: state with an open, threadless today session carrying a task prompt.
    // Act: click the practice row.
    // Assert: requestConsult is called with the tutor role and the task prompt as seed text.
    const requestConsult = vi.fn()
    const state = baseState({ learning: { topics: [], today: { task_prompt: 'walk one case', thread_id: null, status: 'open' }, streak: { streak: 1, stools: 2 } } })
    render(<LearningPage state={state} requestConsult={requestConsult} />)
    fireEvent.click(screen.getByText('walk one case'))
    expect(requestConsult).toHaveBeenCalledWith({ role: 'tutor', seedText: 'walk one case' })
  })

  it('test_suggested_topic_card_prefills_composer', () => {
    // Arrange: one pending tutor-authored task proposal.
    // Act: click Start this topic.
    // Assert: the composer field's value becomes the proposal's action text.
    const state = baseState({ proposals: [{ id: 1, role: 'tutor', status: 'PENDING', kind: 'task', action: 'Start learning: negotiation' }] })
    render(<LearningPage state={state} />)
    fireEvent.click(screen.getByText('Start this topic'))
    expect(screen.getByPlaceholderText('Add a topic').value).toBe('Start learning: negotiation')
  })
})
```

### Verify

```bash
cd dashboard && npm test
```
375x667 and 1512px browser checks per §7's Verify block, plus: toggle
`prefers-reduced-motion: reduce` (`resize_window` `colorScheme` is separate
from this, use the browser's own reduced-motion emulation or
`matchMedia` override) and confirm the today-row reveal and `GrowthMark`
pop both render statically with no animation.

---

## 9. Non-goals

- **No grading, scoring, or rubric in v1.** The daily session's "feedback" is
  the tutor's own conversational replies in that thread, same as any other
  agent chat. No structured pass/fail, no numeric rating.
- **No more than one featured task per day, system-wide.** `learning_sessions.date
  UNIQUE` enforces this at the schema level (§2.2, §10); it is a product
  decision, not a temporary limitation. Ian picking N topics does not mean N
  daily obligations.
- **No new `goals.domain` or `facts` domain value.** §6 is exhaustive on
  this: Learning routes through the existing `personal` domain the same way
  partner and life already do. Widening `goals.domain`'s `CHECK` requires the
  table-rebuild trap this codebase has already been burned by once
  (`chat_threads.model`).
- **The agent never creates a topic on its own.** A `create_proposal` is
  informational only, exactly like every other proposal kind. Ian personally
  runs the clarification pass (§5.1) for every topic that goes live,
  regardless of whether he or the tutor thought of the name first.
- **No per-topic configurable cadence in v1.** `REST_DAYS_PER_WEEK` is a
  fixed module constant (§2.3, §2.4), not an Ian-editable prefs row. A
  `learning_prefs` table is a reasonable follow-up, not a v1 requirement.
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
-- core/acts.py: RING1_ACTS gains a new entry, "learning.confirm"
-- (append to whatever the tuple holds at build time; see §3.1)
-- (no schema change -- agent_acts.act is a free-text column, same as every
--  other Ring 1 act string).
```

`core/learning.py::ensure_schema(conn)` is called defensively at the top of
every public function in that module, and once explicitly from
`agents/runner.py`'s nightly setup path (wherever `school.ensure_schema(conn)`
would be called if `run_sequence` called it directly, today that call lives
inside the `school_exam_within` tripwire closure only, so for Learning add
one explicit call in `run_role` or `run_sequence`'s per-role setup for
`tutor`, e.g. immediately before `build_user_prompt` runs for that role, so
the tables are guaranteed to exist the first time a `tutor` run touches
them). Backups: this data lives in `data/ianos.db`, already claimed by
`scripts/backup.sh` via `VACUUM INTO`; no new path needs adding to the
restic include list.

### Verify

```bash
.venv/bin/python -c "
from core import db, learning
import tempfile, pathlib
db.DB_PATH = pathlib.Path(tempfile.mktemp())
conn = db.connect()
learning.ensure_schema(conn)
print(conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'learning_%'\").fetchall())
"
```
Expect three rows: `learning_topics`, `learning_sessions`,
`learning_streak_events`.

---

## 11. Phases

Each phase ships independently and leaves the system working. **This whole
spec is sequenced after SPEC-v41 Phase 5** (`GoalSheet.jsx` and Life's Today
list must exist first, per §0.1), do not start Phase 1 below until SPEC-v41
§7 Phase 5 is committed and its own Verify checklist passes.

### Phase 1, Data model, Ring 1 act, nightly skeleton (~1 day)

**Files:** `core/learning.py` (new, §2.4) · `core/acts.py` (§3.1: import,
`RING1_ACTS`, `RING1_GRANTS`, `learning_confirm`, `_undo_learning_confirm`)
· `agents/runner.py` (§3.2: `act_learning_confirm` tool, `REGISTERED_TOOLS`
entry, `ALLOWLISTS["tutor"]` skeleton, RING1 overlay loop entry, `_RING1_TOOLS["tutor"]`)
· `agents/roles/tutor.md` (new, §1.1, written in full even though nothing
reads it yet beyond `role_chat_persona`) · `core/roles.py` (§1: `SEQUENCE`
edit) · `dashboard/src/lib/agents.js` (§1.3: `ROLE_COLORS`/`ROLE_GLYPHS`) ·
`api/main.py` (§3.3: `POST /api/learning/sessions/today/confirm`).

**Tests:** `tests/test_learning.py` (all of §2's tests) · `tests/test_acts.py`
(§3.4's four new tests, plus adding `act_learning_confirm` to the
registration-set test) · `tests/test_dispatcher.py` (§1.4's two tests).

**Commit message:** `SPEC-v38 Phase 1: learning schema, Ring 1 act, tutor role skeleton`

**After Phase 1:** the tables exist, `learning.confirm` is receipted and
undoable, and `make plan` shows `tutor` in the nightly slate. Nothing is
visible to Ian yet.

**Verify:**
```bash
.venv/bin/python -m pytest tests/test_learning.py tests/test_acts.py tests/test_dispatcher.py -q
make plan
```
`make plan`'s output must list `tutor` with reason `daily`.

### Phase 2, Onboarding and the instant-write tool (~1-2 days)

**Files:** `agents/runner.py` (§4: `INSTANT_WRITE_TOOLS`, `chat_write_allow`,
`chat_write_learning_profile` tool, `REGISTERED_TOOLS` entry) ·
`dashboard/src/components/AgentChat.jsx` (§4: `reverseWrite` refusal branch)
· `api/main.py` (§7.3: `POST /api/learning/topics`, bare-bones, can predate
the full page, even a Cmd+K action or a temporary raw fetch call from the
browser console is enough to prove the loop per the original spec's guidance).

**Tests:** `tests/test_chat_runner.py` (§4's `test_profile_write_is_tutor_only`)
· `tests/test_learning_runner.py` (new file; §4's
`test_chat_write_learning_profile_activates_topic`).

**Commit message:** `SPEC-v38 Phase 2: learning topic onboarding and the profile instant-write`

**After Phase 2:** Ian can create a topic via the API (or a temporary UI
stub), get asked real clarifying questions in a `tutor` thread, and watch it
flip to `active`. Still nothing generates a task.

**Verify:**
```bash
.venv/bin/python -m pytest tests/test_chat_runner.py tests/test_learning_runner.py -q
```

### Phase 3, Nightly task generation and the daily session (~1-2 days)

**Files:** `agents/runner.py` (§5.2 `read_learning` + `REGISTERED_TOOLS`
entry + `ALLOWLISTS["tutor"]`/`ALLOWLISTS["chief"]` addition; §5.3
`_select_learning_topic`, the `build_user_prompt` `tutor` branch,
`write_learning_task` + `REGISTERED_TOOLS` entry, `_new_run_state`'s
`learning_topic_id` default) · `core/pillars.py` and
`dashboard/src/lib/pillars.js` are **not** touched yet (that's Phase 4) ·
`agents/roles/tutor.md` (§5.4's suggestion-proposal instruction, already
written in Phase 1, no further edit needed since it's in the Rules section
from the start).

**Tests:** `tests/test_learning_runner.py` (§5.5's three tests) ·
`tests/test_learning.py` (§5.5's two tests).

**Commit message:** `SPEC-v38 Phase 3: nightly task rotation and the daily learning session`

**After Phase 3:** the full daily loop is real, Mr. Miyagi writes a task
overnight, Ian works it in a thread the next day, confirms it, and the
streak moves. Still no dedicated page; the loop is exercised through the
existing consult surface and the Phase-2 stub topic creation.

**Verify:**
```bash
.venv/bin/python -m pytest tests/test_learning_runner.py tests/test_learning.py -q
make run --role=tutor   # or the equivalent single-role nightly invocation this repo uses
```

### Phase 4, The pillar UI and delight polish (~2 days)

**Files:** `core/pillars.py` (§6.1) · `core/db.py` (§6.2:
`NAMESPACE_DOMAINS`) · `dashboard/src/lib/pillars.js` (§6.3) ·
`dashboard/src/components/Nav.jsx` (§7.1) · `dashboard/src/App.jsx` (§7.1) ·
`dashboard/src/pages/LearningPage.jsx` (new, §7.4) ·
`dashboard/src/components/GrowthMark.jsx` (new, §8) · `api/main.py` (§7.2
`_learning_state`, §7.3 `PATCH /api/learning/topics/{id}/archive`) ·
`dashboard/src/styles.css` (§8.1, both breakpoints) · `agents/roles/tutor.md`
(§8's completion-copy instruction, already present from Phase 1's full
write, verify it's still there, don't duplicate it).

**Tests:** `tests/test_gym_pillars.py` (§6.4's three tests) ·
`dashboard/tests/growth-mark.ui.test.jsx` (new, §8.2) ·
`dashboard/tests/learning-page.ui.test.jsx` (new, §8.2).

**Commit message:** `SPEC-v38 Phase 4: the Learning pillar page and delight`

**After Phase 4:** Learning has its own pillar page, its own place in the
More sheet, and reads as a finished, delightful surface rather than a chat
thread with no home.

**Verify:**
```bash
.venv/bin/python -m pytest tests/test_gym_pillars.py -q
cd dashboard && npm test && npm run build
```
Browser: 375x667 with 47/34 insets, then 1512px, full checklist in §7's and
§8's own Verify blocks.

**Order matters**, same reasoning SPEC-v37 §11 gave: Phase 2 before Phase 3
(a rotation with nothing `active` to select from exercises nothing); Phase 3
before Phase 4 (building the pillar page before the daily loop produces real
data means building against fixtures instead of the real shape).

---

## 12. Laws this spec asserts in tests

| Test | File | Asserts |
|---|---|---|
| `test_learning_confirm_today_only` | `tests/test_acts.py` | `learning.confirm` marks the session completed and writes exactly one `confirm` event, never grace/reset (§3, Law B1) |
| `test_learning_confirm_requires_a_session_row` | `tests/test_acts.py` | Confirming with no session row for the day raises `ActError` instead of silently creating one (§3.1) |
| `test_learning_confirm_is_reversible` | `tests/test_acts.py` | Undo reopens the session and removes its confirm event (§3.1) |
| `test_ring1_denies_learning_confirm_to_other_roles` | `tests/test_acts.py` | Only `tutor` may apply `learning.confirm` (§3.1) |
| `test_profile_write_is_tutor_only` | `tests/test_chat_runner.py` | `chat_write_allow` includes `chat_write_learning_profile` for `tutor` only (§4) |
| `test_chat_write_learning_profile_activates_topic` | `tests/test_learning_runner.py` | A `clarifying` topic flips to `active` and carries the new profile after the tool runs (§4, Law B2) |
| `test_clarifying_topic_generates_no_task` | `tests/test_learning_runner.py` | `_select_learning_topic` never returns a `clarifying` or `archived` row (§5.3, Law B2) |
| `test_zero_active_topics_is_not_an_error` | `tests/test_learning_runner.py` | `_select_learning_topic` returns `None`, not an exception, with no active topics (§5.3) |
| `test_least_recently_featured_topic_is_picked` | `tests/test_learning_runner.py` | Selection is least-recently-featured, NULL sorting first (§5.3) |
| `test_learning_session_date_unique` | `tests/test_learning.py` | A second `create_or_replace_session` call for the same date replaces, never duplicates (§2.4, §5.3) |
| `test_skip_stale_sessions_marks_only_old_open_rows` | `tests/test_learning.py` | Only pre-today `open` rows flip to `skipped`; completed and today's rows are untouched (§5.3) |
| `test_learning_streak_never_touches_gym_events` | `tests/test_learning.py` | No code path in `core/learning.py` inserts into or reads `streak_events`; no gym code path touches `learning_streak_events` (§2.3, Law B1) |
| `test_topic_proposal_approval_creates_no_topic_row` | `tests/test_learning_api.py` | Approving a Learning-suggestion proposal leaves `learning_topics` row count unchanged (§5.4) |
| `test_no_new_goal_or_fact_domain` | `tests/test_gym_pillars.py` | `db.DOMAINS` and `db.FACT_DOMAINS` are unchanged; Learning routes through `NAMESPACE_DOMAINS["learning"] == "personal"` (§6, Law B3) |
| `test_life_goal_excludes_learning_goal` | `tests/test_gym_pillars.py` | A `#learning`-tagged personal goal appears under `learning`, never `life` (§6.1) |
| `test_learning_pillar_status_never_off_track` | `tests/test_gym_pillars.py` | The learning pillar's status is always `ON TRACK` (§6.1, the partner precedent) |
| `test_tutor_runs_daily` | `tests/test_dispatcher.py` | `should_run` returns `True, "daily"` for the `tutor` role meta (§1.4) |
| `test_tutor_in_sequence` | `tests/test_dispatcher.py` | `tutor` is in `SEQUENCE`, after `watchdog` and before `counsel` (§1.4) |
| `test_learning_topic_create_and_archive` | `tests/test_learning_api.py` | `POST /api/learning/topics` creates a `clarifying` row and returns a `consultRequest` with no `view` key; `PATCH .../archive` sets `status='archived'` (§7.3) |
| `test_learning_session_confirm_endpoint_creates_or_updates` | `tests/test_learning_api.py` | The dashboard confirm endpoint creates a row when none exists and updates one when it does (§3.3) |
| `test_growth_stage_floors_at_one_and_caps_at_five` | `dashboard/tests/growth-mark.ui.test.jsx` | `growthStage` never returns below 1 or above 5 (§8) |
| `test_growth_mark_respects_reduced_motion` | `dashboard/tests/growth-mark.ui.test.jsx` | `GrowthMark` renders without a pop animation under reduced motion (§8) |
| `test_zero_topics_shows_only_the_composer` | `dashboard/tests/learning-page.ui.test.jsx` | The zero-topics lane shows only the `Add a topic` field, no other copy (§7.4, SPEC-v41 §3) |
| `test_today_row_opens_consult_with_seed_text` | `dashboard/tests/learning-page.ui.test.jsx` | Tapping the practice row calls `requestConsult` with `{role: 'tutor', seedText: ...}` and no `view` key (§7.4) |
| `test_suggested_topic_card_prefills_composer` | `dashboard/tests/learning-page.ui.test.jsx` | "Start this topic" prefills the composer from the proposal's `action` text (§5.4, §7.4) |

---

## 13. Open questions for Ian

**Both closed 2026-09-02** (see §0.1): stale open sessions are marked
`skipped` by the nightly run before tonight's write (§5.3); no topic cap in
v1. The original text stays below as the record of the reasoning, and the
first item remains a watch item for whenever the topic count passes four.

- **How many active topics before rotation gets stale?** With three named
  examples (case interviews, AI, Python) and least-recently-featured
  selection, each gets featured roughly every third day. That's probably
  fine at 3-4 topics; it's not obvious it's still fine at 8, where three
  weeks can pass between reps on any one topic and the tutor's "working
  profile" of it may go stale faster than it gets refreshed. No cap is
  proposed here, just flagging that rotation quality should get a real look
  once Ian actually has more than a handful of topics live.
- **What happens after several days of an ignored featured task?** Answered
  by §5.3: the nightly run marks it `skipped` before writing tonight's new
  row. Nothing surfaces a nudge anywhere else: not the Order, not a memo,
  not a push. This is a decision now, not a guess.
