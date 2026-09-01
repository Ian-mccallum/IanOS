"""SPEC-v37 5.4/5.5: the memory index. Pure(ish) data-layer module -- the
ONE writer of `memory_fts` (the schema itself lives in `core/db.py`'s
`SCHEMA` string; this module only populates it).

Law A6 (5.1): retrieval informs, the ledger asserts. This index is the
"retrieval informs" half -- a full-text recall surface over ianOS history,
never a source of truth. `search_memory` (agents/runner.py) marks every
result `"grounding": "recall_only"` so nothing that comes back from here can
be mistaken for a ledger fact.

Law A7 (5.5): the index inherits every wall. `SOURCE_TABLES` below is the
COMPLETE, EXHAUSTIVE list of tables this indexer may ever read. There is no
generic "walk every table" loop: a table not named here (journal_entries,
health_daily, health_insights, school_note_assets, leads, ...) is invisible
to the indexer forever, until a human deliberately adds it -- to both this
tuple AND its own `_rows_*` function. `tests/test_memory_index.py::
test_index_excludes_private_stores` asserts the tuple's contents directly,
mirroring `tests/test_journal.py`'s source-text privacy assertions.

Design: full rebuild, not trigger-maintained. `sync_memory_index()` deletes
every row in `memory_fts` and re-populates it from scratch inside one
transaction, so a mid-sync crash never leaves the index half-empty and a
second call is always safe (D4: idempotency is a requirement). This is
called once at the end of every nightly sequence
(`agents/runner.py::run_sequence`), so a search reflects last night's
state -- explicitly fine, since every result is recall, never live fact.
"""

from __future__ import annotations

import sqlite3

from core import db
from core import notes as notes_lib
from core import school

# The complete, exhaustive list of tables this indexer may ever populate
# memory_fts from. Adding a table means adding it here AND writing its own
# `_rows_<table>` function below -- see the Law A7 note above. Never widen
# this into a generic "SELECT name FROM sqlite_master" walk: that is exactly
# the shape of bug that would silently start indexing journal_entries the
# day someone renamed a column near it.
SOURCE_TABLES: tuple[str, ...] = (
    "memos", "briefs", "notes", "facts", "school_note_sessions", "proposals",
)

_INSERT_SQL = (
    "INSERT INTO memory_fts (body, topic, kind, source_table, source_id, occurred_at) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)


def _rows_memos(conn: sqlite3.Connection) -> list[tuple]:
    """memos -> memory_fts.

    Excludes any row `from_role` in `db.PRIVATE_HEALTH_MEMO_ROLES`
    (physician/coach): SPEC-v35's health-role memo wall, the same exclusion
    `db.recent_shared_memos` already applies before a memo reaches broad
    state. This is the one real exclusion in this module -- everything else
    in Law A7's table is satisfied by SOURCE_TABLES simply never naming the
    walled table.

    Archived rows ARE included. A compaction summary (`archived_into_id`) is
    exactly the kind of thing this tool exists to surface as recall, and an
    archived memo is still real history, not a secret -- `recent_shared_memos`
    excludes archived rows only because that reader feeds a *live* blackboard
    view, not because the content becomes private.
    """
    rows = conn.execute(
        "SELECT id, from_role, topic, body, created_at FROM memos"
    ).fetchall()
    out = []
    for r in rows:
        if r["from_role"] in db.PRIVATE_HEALTH_MEMO_ROLES:
            continue
        out.append((r["body"], r["topic"], "memo", "memos", r["id"], r["created_at"]))
    return out


def _rows_briefs(conn: sqlite3.Connection) -> list[tuple]:
    """briefs -> memory_fts. day_command is folded into body (it's the one
    sentence Ian actually reads); topic is synthesized as briefs has no
    topic column of its own. occurred_at uses `date` (the day the brief
    covers), not `created_at` (generation time, which is always the same
    night) -- `date` is the more meaningful "when did this happen" anchor.
    """
    rows = conn.execute(
        "SELECT id, date, kind, body, day_command FROM briefs"
    ).fetchall()
    out = []
    for r in rows:
        body = f"{r['day_command']}\n\n{r['body']}" if r["day_command"] else r["body"]
        topic = f"{r['kind']} brief {r['date']}"
        out.append((body, topic, r["kind"], "briefs", r["id"], r["date"]))
    return out


def _rows_notes(conn: sqlite3.Connection) -> list[tuple]:
    """notes -> memory_fts. Excludes soft-deleted rows (`deleted_at IS NOT
    NULL`) -- a deleted note is not history an agent should recall, and
    Undo already restores the row rather than un-deleting an index entry.
    Body and title both pass through `notes.resolve_note_body_for_agents`,
    the same transform `read_notes` applies, so an inline `note-image:`
    token never reaches the index as raw text -- only its "[image: caption]"
    placeholder does.
    """
    rows = conn.execute(
        "SELECT id, title, body, updated_at FROM notes WHERE deleted_at IS NULL"
    ).fetchall()
    out = []
    for r in rows:
        body = notes_lib.resolve_note_body_for_agents(r["body"] or "")
        topic = notes_lib.resolve_note_body_for_agents(r["title"] or "") or "note"
        out.append((body, topic, "note", "notes", r["id"], r["updated_at"]))
    return out


def _rows_facts(conn: sqlite3.Connection) -> list[tuple]:
    """facts -> memory_fts. Straightforward: body/topic/kind map onto the
    columns of the same name. occurred_at uses `updated_at` (facts are
    upserted in place on the same (domain, topic) key, so `updated_at` is
    when the fact was last confirmed true, the meaningful freshness signal
    for recency ranking) rather than `created_at`.

    Every fact is indexed regardless of `verified` -- `search_memory` marks
    every result recall-only, and an unverified fact is still something Ian
    or an agent said; hiding it from recall (as opposed to from grounding a
    claim, which Law A6 already blocks elsewhere) would make the index less
    useful for no privacy gain. Domain scoping happens at query time in
    `search_memory`, not here: this indexer is domain-blind by design
    (`memory_fts` carries no domain column), matching the spec's own
    framing of scoping as a `search_memory`-time concern.
    """
    rows = conn.execute(
        "SELECT id, topic, body, kind, updated_at FROM facts"
    ).fetchall()
    return [
        (r["body"], r["topic"], r["kind"], "facts", r["id"], r["updated_at"])
        for r in rows
    ]


def _rows_school_note_sessions(conn: sqlite3.Connection) -> list[tuple]:
    """school_note_sessions -> memory_fts, plain-text projection only.

    `plain_text` is already maintained on every save (core/school.py) --
    this function never touches `document_json` (the ProseMirror document)
    and needs no extractor of its own. Excludes soft-deleted rows and rows
    with no plain text yet (a brand-new empty session has nothing to
    search). `occurred_at` uses `session_date` (when the class met), not
    `updated_at` (last edit), matching `facts`/`briefs`' choice of the
    semantically real date over the touch timestamp.

    `school_note_assets` (private course files) is a DIFFERENT table and is
    never read here -- SPEC-v36's wall, satisfied by this function simply
    never naming that table.
    """
    # school_note_sessions lives in SCHOOL_SCHEMA, created lazily
    # (core/school.py's own module docstring): a DB that has never touched
    # a School route may not have the table yet. Every core/school.py
    # function calls this itself first for exactly that reason -- mirrored
    # here since this query goes straight at the table rather than through
    # a school.py accessor.
    school.ensure_schema(conn)
    rows = conn.execute(
        "SELECT id, course_code, session_type, session_date, title, plain_text "
        "FROM school_note_sessions WHERE deleted_at IS NULL"
    ).fetchall()
    out = []
    for r in rows:
        body = (r["plain_text"] or "").strip()
        if not body:
            continue
        topic = r["title"] or f"{r['course_code']} {r['session_type']}"
        out.append((body, topic, r["session_type"], "school_note_sessions",
                     r["id"], r["session_date"]))
    return out


def _rows_proposals(conn: sqlite3.Connection) -> list[tuple]:
    """proposals -> memory_fts. body combines action + reasoning: reasoning
    alone floats without the action it justifies, and action alone drops
    the "why" Ian would actually want back on recall. topic is synthesized
    as "<role> <kind>" (proposals has no topic column); kind maps to
    proposals.kind (money/task/legal/health/personal) directly.

    Every status is included (PENDING/APPROVED/REJECTED/EXPIRED) -- SPEC-v32
    Law 4: EXPIRED is a timeout, not a verdict, and all four are real
    history an agent might reasonably want to recall ("did anyone already
    propose this?"). occurred_at uses created_at, not decided_at (null for
    PENDING/EXPIRED).
    """
    rows = conn.execute(
        "SELECT id, role, action, reasoning, kind, created_at FROM proposals"
    ).fetchall()
    out = []
    for r in rows:
        body = f"{r['action']}\n\n{r['reasoning']}" if r["reasoning"] else r["action"]
        topic = f"{r['role']} {r['kind']}"
        out.append((body, topic, r["kind"], "proposals", r["id"], r["created_at"]))
    return out


_INDEXERS = {
    "memos": _rows_memos,
    "briefs": _rows_briefs,
    "notes": _rows_notes,
    "facts": _rows_facts,
    "school_note_sessions": _rows_school_note_sessions,
    "proposals": _rows_proposals,
}
assert set(_INDEXERS) == set(SOURCE_TABLES), "SOURCE_TABLES and _INDEXERS must name the same tables"


def sync_memory_index(conn: sqlite3.Connection) -> int:
    """Full rebuild of `memory_fts` from `SOURCE_TABLES`. Returns the row
    count indexed. Safe to call repeatedly forever: DELETE + re-INSERT from
    source tables, no dedup logic needed, one transaction so a crash
    mid-sync never leaves the index half (or doubly) populated.
    """
    try:
        conn.execute("DELETE FROM memory_fts")
        total = 0
        for table in SOURCE_TABLES:
            rows = _INDEXERS[table](conn)
            if rows:
                conn.executemany(_INSERT_SQL, rows)
                total += len(rows)
        conn.commit()
        return total
    except Exception:
        conn.rollback()
        raise
