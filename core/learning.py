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
