"""The archivist becomes a function (SPEC-v37 5.3).

`facts` used to be distilled by a weekly Haiku "archivist" role that read
memo chatter and *inferred* what was worth remembering. Six of its
seventeen rows were fabricated, and a fabricated row was born `verified=1`
and read as ground truth by every other agent. The archivist is retired
(`agents/roles/archivist.md` has `active: false`, dropped from
`core.roles.SEQUENCE`); it never runs again.

This module is what replaces it, and the replacement is the actual fix:

    Law A6 -- Retrieval informs; the ledger asserts. An agent may *claim*
    only what traces to a ledger row or a live tool read in this run.

`distill()` promotes a fact **only** when one of four deterministic
extractors below recognizes a real row in a real table: a durable date from
`calendar_events`, an exam date from `school_items`, an account's identity
from `financial_accounts`, a decided proposal, or a completed deadline goal.
Nothing here ever asks a model anything -- every extractor is plain SQL plus
Python string formatting, so there is nothing for it to hallucinate. Facts it
writes go straight through `db.upsert_fact(..., verified=1, source_role=
"ledger")`, never through the `write_fact` *tool* path (that path is for a
model's own claims and is rightly born `verified=0`; code that traces
directly to a row it just read cannot be lying about it, so it is trusted
from the start -- the same shape as a connector sync or Ian's own Memory-page
edit, both of which already call `upsert_fact` directly).

Everything an extractor does *not* recognize stays a memo. It is still
searchable (SPEC-v37 5.4's `search_memory`) as recall, just never promoted to
a durable, "ground truth" claim.

Idempotency: every extractor keys its fact's `(domain, topic)` off the
source row's own stable identity (an id, or an (source, external_id) pair),
so `upsert_fact`'s `ON CONFLICT(domain, topic) DO UPDATE` makes a second
`distill()` over the same data update the same rows rather than duplicate
them. `distill()` is meant to run at the end of every nightly sequence,
forever, so this has to hold on run #2 as much as it does on run #200.

This module also runs 5.3's compaction sibling (8.7): `db.compact_memos`
already existed, fully deterministic, with no real caller -- the
`compact_memos` *tool* is a permanent stub, and the only prompt line that
ever told an agent to call it was aimed at the now-retired archivist. Code is
the right caller for a code-only operation, so `distill()` is it.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from core import db

# --------------------------------------------------------------- routing

# Calendar categories (`core.db.calendar_events.category`, written by
# `ingest/import_calendar.py`, `ingest/sync_icloud.py`, `ingest/from_connector.py`)
# map onto the same domain vocabulary `goals.domain` and role frontmatter
# `domains:` already use. Unrecognized/blank categories default to personal,
# the safest of the three (never finance, never a business claim).
_CALENDAR_CATEGORY_DOMAIN = {"work": "business", "health": "health", "personal": "personal"}

# A one-off meeting or errand is routine noise; a birthday or anniversary is
# the textbook durable date ianOS should never need to be told twice. This is
# deliberately narrow -- calendar_events can hold an entire semester of
# imported noise, and most of it is not worth a lifetime fact.
_DURABLE_CALENDAR_RE = re.compile(r"\b(birthday|anniversary)\b", re.IGNORECASE)

# `proposals.kind` (SPEC-v32/v37 CHECK) routes a decided proposal to the
# domain its own subject matter belongs to, mirroring FACT_DOMAINS.
_PROPOSAL_KIND_DOMAIN = {
    "money": "finance", "legal": "legal", "health": "health",
    "personal": "personal", "task": "business",
}

# goals.domain's own CHECK constraint (core/db.py) -- defensive fallback only.
_GOAL_DOMAINS = {"business", "health", "personal", "finance"}


def _slug(text: str, limit: int = 60) -> str:
    """A stable, filesystem/topic-safe key from free text (never re-derived
    from anything the model wrote -- always from a real column's value).
    Apostrophes are dropped rather than turned into a hyphen so "Mom's
    Birthday" reads as "moms-birthday", not "mom-s-birthday"."""
    s = text.strip().lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:limit] or "event"


# ------------------------------------------------------------ extractor 1a
# calendar_events: recurring/named life events only.

def _promote_calendar_dates(conn) -> int:
    """Promote a `calendar_events` row only when its summary names a
    recurring, named life event (birthday, anniversary) -- see
    `_DURABLE_CALENDAR_RE`. Everything else (meetings, errands, one-off
    appointments) is exactly the routine noise this spec says must not
    become a "durable" fact. `category == 'school'` rows are skipped: those
    are `school_calendar_projection`'s own copies of `school_items` rows,
    and extractor 1b below already owns academic dates -- promoting both
    would file the same underlying deadline as two different facts.

    Keyed by a slug of the summary text, not the row id: a recurring event
    can appear as more than one row (one per occurrence) as new imports
    bring later years into view, and every occurrence of "Mom's Birthday"
    is the same durable fact, not a new one each year.
    """
    rows = db.rows_to_dicts(conn.execute(
        "SELECT date, summary, category FROM calendar_events "
        "WHERE category != 'school'"
    ).fetchall())
    promoted = 0
    for row in rows:
        summary = (row.get("summary") or "").strip()
        if not summary or not _DURABLE_CALENDAR_RE.search(summary):
            continue
        category = (row.get("category") or "").strip().lower()
        domain = _CALENDAR_CATEGORY_DOMAIN.get(category, "personal")
        topic = f"calendar:{_slug(summary)}"
        body = f"{summary} -- a recurring calendar event."
        db.upsert_fact(
            conn, domain, topic, body, kind="date", date=row.get("date"),
            recurs="yearly", source_role="ledger", verified=1,
        )
        promoted += 1
    return promoted


# ------------------------------------------------------------ extractor 1b
# school_items: exams only.

def _promote_school_exams(conn) -> int:
    """Promote a `school_items` row only when `kind == 'exam'` (set by
    `ingest/import_canvas_calendar.py::_kind`, which recognizes "exam",
    "midterm", "final" in the title). Lectures, discussions, labs, and
    ordinary assignments recur weekly and are exactly the routine noise this
    spec warns against; an exam is a real, high-stakes, one-time deadline --
    the "an exam" example the spec itself gives for what's worth a lifetime
    fact. Archived items (dropped by a later Canvas sync) are excluded.

    `school_items` is created lazily (`core.school.ensure_schema`, called
    from the School routes, not from `db.connect()`), so an install that has
    never touched School has no such table yet; this must degrade to "no
    school data" rather than crash the whole nightly run, the same guard
    `core.school.term_bounds` already uses for the identical reason.
    """
    try:
        rows = db.rows_to_dicts(conn.execute(
            "SELECT id, course_code, kind, title, due_at FROM school_items "
            "WHERE archived_at IS NULL AND kind = 'exam' AND due_at IS NOT NULL"
        ).fetchall())
    except sqlite3.OperationalError:
        return 0
    promoted = 0
    for row in rows:
        due_date = (row.get("due_at") or "")[:10] or None
        topic = f"uiuc:exam:{row['id']}"
        domain = db.domain_for_topic(topic, "college")
        body = f"{row['course_code']}: {row['title']} is due {due_date}."
        db.upsert_fact(
            conn, domain, topic, body, kind="date", date=due_date,
            source_role="ledger", verified=1,
        )
        promoted += 1
    return promoted


# ------------------------------------------------------------- extractor 2
# financial_accounts: identity, never a balance.

def _promote_account_identities(conn) -> int:
    """Promote an account's *identity* ("Ian holds a Fidelity Roth IRA"),
    never its balance. `current_balance` is live and always-changing -- the
    moment a promoted dollar figure is one sync old it is exactly the kind
    of stale "ground truth" this spec exists to stop writing, and
    `read_transactions`/`read_holdings` already serve the real-time number
    to any agent that needs it. An account's existence, institution, and
    type barely ever change, which is what makes it actually durable.

    Keyed by the account's own (source, external_id) primary key, so a
    provider's periodic re-sync updates the same fact in place instead of
    piling up a new one. Skips rows with no institution/name on file (an
    incomplete sync artifact, not a real linked account).
    """
    rows = db.rows_to_dicts(conn.execute(
        "SELECT source, external_id, institution, name, type, subtype "
        "FROM financial_accounts WHERE institution != '' AND name != ''"
    ).fetchall())
    promoted = 0
    for row in rows:
        topic = f"market:account:{row['source']}:{row['external_id']}"
        domain = db.domain_for_topic(topic, "finance")
        kind_label = row.get("type") or "account"
        if row.get("subtype"):
            kind_label = f"{kind_label}/{row['subtype']}"
        body = (f"Ian holds a {row['institution']} {row['name']} "
                f"({kind_label}) account via {row['source']}.")
        db.upsert_fact(
            conn, domain, topic, body, kind="fact",
            source_role="ledger", verified=1,
        )
        promoted += 1
    return promoted


# ------------------------------------------------------------- extractor 3
# decided proposals.

def _promote_proposal_decisions(conn) -> int:
    """Promote a fact from the `proposals` row itself (`status`,
    `decided_at`), not from the memo `decide_proposal` also writes -- the
    row is the source of truth and the memo is just its human-readable
    echo, so reading the row directly means this extractor is never coupled
    to that memo's exact wording.

    Only `APPROVED`/`REJECTED` count. `EXPIRED` is deliberately excluded:
    SPEC-v32's law is that a timeout is not a verdict (it is why
    `role_stats` and `recent_decisions` both keep EXPIRED out of an agent's
    record), and a fact claiming Ian "decided" something he never looked at
    would be exactly the kind of quiet fabrication this spec is fixing.
    `PENDING` is obviously not a decision yet either.

    Keyed by the proposal's own id, so re-running `distill()` after the
    proposal is long done still lands on the same fact.
    """
    rows = db.rows_to_dicts(conn.execute(
        "SELECT id, role, action, kind, status, decided_at FROM proposals "
        "WHERE status IN ('APPROVED', 'REJECTED') AND decided_at IS NOT NULL"
    ).fetchall())
    promoted = 0
    for row in rows:
        topic = f"proposal:{row['id']}"
        default_domain = _PROPOSAL_KIND_DOMAIN.get(row.get("kind") or "", "business")
        domain = db.domain_for_topic(topic, default_domain)
        verb = "approved" if row["status"] == "APPROVED" else "rejected"
        decided_date = (row.get("decided_at") or "")[:10] or None
        body = (f"Ian {verb} {row['role']}'s proposal: "
                f"\"{row['action']}\" on {decided_date}.")
        db.upsert_fact(
            conn, domain, topic, body, kind="date", date=decided_date,
            source_role="ledger", verified=1,
        )
        promoted += 1
    return promoted


# ------------------------------------------------------------- extractor 4
# completed deadline goals.

def _promote_completed_goals(conn) -> int:
    """Promote a fact only for a `kind == 'deadline'` goal whose
    `current_value` is one of `db.DONE_STATES` -- the exact terminal-state
    test `core.metrics.goal_status` already uses to call a deadline goal
    "done". This is deliberately narrower than "any goal at or above
    target": a `quota`/`goal`-kind goal's ON-TRACK status is a recurring,
    fluctuating weekly read (a gym quota is ON TRACK this week and may not
    be next), not a one-time achievement, and there is no "completed_at"
    column to say precisely when it stopped being true. A deadline goal's
    terminal state ("filed", "approved", "signed", ...) is the only signal
    in this schema that is genuinely discrete and non-reversible, which is
    what makes it a real historical fact rather than a live status the
    dashboard already shows.

    Archived goals are excluded (SPEC-v30: `goals.archived` retires a goal
    from every read path, and a re-created goal is deliberately not treated
    as a restore -- this extractor follows the same rule, keyed on id).
    """
    rows = db.rows_to_dicts(conn.execute(
        "SELECT id, name, current_value, domain FROM goals "
        "WHERE archived = 0 AND kind = 'deadline'"
    ).fetchall())
    promoted = 0
    for row in rows:
        current_value = (row.get("current_value") or "").strip()
        if current_value.lower() not in db.DONE_STATES:
            continue
        topic = f"goal:{row['id']}:done"
        domain = row.get("domain") if row.get("domain") in _GOAL_DOMAINS else "business"
        body = f"Goal completed: \"{row['name']}\" ({current_value})."
        db.upsert_fact(
            conn, domain, topic, body, kind="fact",
            source_role="ledger", verified=1,
        )
        promoted += 1
    return promoted


def distill(conn, today: date | None = None) -> dict:
    """Run every deterministic extractor once, then compact old memos.

    Called once, at the end of every nightly sequence (`agents.runner.
    run_sequence`), after every role has had its turn -- so it can promote
    whatever the night actually produced (a decision Ian made earlier today,
    a goal that just crossed its finish line) as well as whatever was
    already sitting in the tables. Safe to call more than once a day: every
    extractor is idempotent (see each docstring for its own key).

    Returns a summary dict -- counts per extractor plus the compaction
    result -- meant for one nightly log line, not for any agent-facing
    surface.
    """
    today = today or date.today()
    facts_promoted = {
        "calendar_dates": _promote_calendar_dates(conn),
        "school_exams": _promote_school_exams(conn),
        "financial_accounts": _promote_account_identities(conn),
        "proposal_decisions": _promote_proposal_decisions(conn),
        "completed_goals": _promote_completed_goals(conn),
    }
    compaction = db.compact_memos(conn)
    return {
        "date": today.isoformat(),
        "facts_promoted": facts_promoted,
        "facts_promoted_total": sum(facts_promoted.values()),
        "compaction": compaction,
    }
