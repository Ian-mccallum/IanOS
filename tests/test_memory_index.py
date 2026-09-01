"""SPEC-v37 §5.4/§5.5: the memory index. Law A6 (retrieval informs, the
ledger asserts) and Law A7 (the index inherits every wall). This file
asserts: the indexer's explicit six-table allowlist is exhaustive and can
never silently grow to include a walled table; the health-role memo
exclusion actually happens at sync time; search_memory always marks its
results recall-only; BM25 + recency ordering isn't arbitrary; domain
scoping on facts mirrors read_facts exactly while the other five source
tables stay unscoped; a hostile query string never crashes the tool; and
search_memory is granted to all ten active roles/chat and to no retired one.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import db, memory_index, school  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _result(res: dict) -> dict:
    return json.loads(res["content"][0]["text"])


def _search(conn, query, role="scout", role_domains=None, **kw):
    runner.RUN.update(role=role, conn=conn, role_domains=role_domains or ["business"],
                       interactive_read_sources=set(), reads_this_run=set())
    args = {"query": query}
    args.update(kw)
    return _result(asyncio.run(runner.search_memory.handler(args)))


# --------------------------------------------------------- Law A7 exclusions

def test_index_excludes_private_stores(conn):
    """§12's required test, exact name. A health-role memo never enters
    memory_fts, and the indexer's own source-table list structurally cannot
    name a walled table."""
    db.add_memo(conn, "physician", "vitals", "resting heart rate trend note")
    db.add_memo(conn, "coach", "training", "deload week programming note")
    db.add_memo(conn, "scout", "pipeline", "warm lead called back today")
    memory_index.sync_memory_index(conn)

    rows = conn.execute("SELECT source_table, body FROM memory_fts").fetchall()
    roles_seen = {r["body"] for r in rows}
    assert "resting heart rate trend note" not in roles_seen
    assert "deload week programming note" not in roles_seen
    assert "warm lead called back today" in roles_seen
    hit = conn.execute(
        "SELECT * FROM memory_fts WHERE memory_fts MATCH 'heart OR deload'"
    ).fetchall()
    assert hit == []

    # Structural: the allowlist itself can never silently grow to include a
    # walled table (Law A7). Mirrors tests/test_journal.py's source-text style.
    forbidden = ("journal_entries", "health_daily", "health_insights",
                 "school_note_assets", "leads")
    for name in forbidden:
        assert name not in memory_index.SOURCE_TABLES
    src = (Path(__file__).resolve().parent.parent / "core" / "memory_index.py").read_text()
    for name in forbidden:
        # Only school_note_assets/leads/journal_entries/health_* may appear
        # in PROSE (the module's own docstrings talk about the wall); they
        # must never appear as a literal SQL table reference. The safest
        # structural check available without a SQL parser: they never
        # appear inside a "FROM <table>" or "TABLE <table>" clause.
        assert f"FROM {name}" not in src
        assert f"INTO {name}" not in src


# ----------------------------------------------------------- basic indexing

def test_sync_indexes_all_six_source_tables(conn):
    db.add_memo(conn, "scout", "pipeline", "ZZMEMO warm lead follow-up")
    db.upsert_brief(conn, db.today(), "daily", "ZZBRIEF day command body", day_command="Call the lead.")
    db.create_note(conn, body="ZZNOTE remember to renew the domain")
    db.upsert_fact(conn, "business", "clockwork:test", "ZZFACT deadline is real", kind="fact", verified=1)
    db.add_proposal(conn, "scout", "ZZPROPOSAL call the lead back", "warm callback promised", "task")
    school.ensure_schema(conn)
    conn.execute("INSERT INTO school_courses (code, name) VALUES ('FIN199', 'Finance seminar')")
    conn.execute(
        "INSERT INTO school_note_sessions "
        "(course_code, school_item_id, session_type, session_date, title, plain_text) "
        "VALUES ('FIN199', NULL, 'study', ?, 'Study session', 'ZZSCHOOL exam review notes')",
        (db.today(),),
    )
    conn.commit()

    n = memory_index.sync_memory_index(conn)
    assert n == 6

    tables = {r["source_table"] for r in conn.execute("SELECT DISTINCT source_table FROM memory_fts")}
    assert tables == set(memory_index.SOURCE_TABLES)
    for needle in ("ZZMEMO", "ZZBRIEF", "ZZNOTE", "ZZFACT", "ZZPROPOSAL", "ZZSCHOOL"):
        hit = conn.execute("SELECT 1 FROM memory_fts WHERE body LIKE ?", (f"%{needle}%",)).fetchone()
        assert hit, f"{needle} missing from the index"


def test_sync_memory_index_is_idempotent(conn):
    db.add_memo(conn, "scout", "pipeline", "idempotency check memo")
    db.upsert_fact(conn, "business", "clockwork:idem", "idempotency check fact", verified=1)
    first = memory_index.sync_memory_index(conn)
    second = memory_index.sync_memory_index(conn)
    third = memory_index.sync_memory_index(conn)
    assert first == second == third
    count = conn.execute("SELECT COUNT(*) c FROM memory_fts").fetchone()["c"]
    assert count == first


def test_sync_excludes_soft_deleted_notes(conn):
    row = db.create_note(conn, body="ZZDELETED note body")
    conn.execute("UPDATE notes SET deleted_at = datetime('now') WHERE id = ?", (row["id"],))
    conn.commit()
    memory_index.sync_memory_index(conn)
    hit = conn.execute("SELECT 1 FROM memory_fts WHERE body LIKE '%ZZDELETED%'").fetchone()
    assert hit is None


def test_notes_body_resolves_image_embeds_not_raw_tokens(conn):
    """read_notes resolves note-image: tokens to a caption placeholder before
    an agent ever sees them; the index must do the same, never leak the raw
    token as searchable/returnable text."""
    db.create_note(conn, body="![a photo](note-image:abc123) ZZIMAGETEST rest of body")
    memory_index.sync_memory_index(conn)
    row = conn.execute("SELECT body FROM memory_fts WHERE body LIKE '%ZZIMAGETEST%'").fetchone()
    assert row is not None
    assert "note-image:abc123" not in row["body"]
    assert "[image" in row["body"]


# --------------------------------------------------------- search_memory

def test_search_memory_marks_recall_only(conn):
    """§12's required test, exact name."""
    db.add_memo(conn, "scout", "pipeline", "ZZRECALL warm lead in Naperville")
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZRECALL")
    assert out["count"] >= 1
    for r in out["results"]:
        assert r["grounding"] == "recall_only"
        assert "source_table" in r and "source_id" in r and "occurred_at" in r


def test_search_memory_finds_seeded_memo_by_keyword(conn):
    db.add_memo(conn, "scout", "pipeline", "ZZFINDME warm lead called back")
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZFINDME")
    assert out["count"] == 1
    assert out["results"][0]["source_table"] == "memos"


def test_search_memory_finds_seeded_fact_by_keyword(conn):
    db.upsert_fact(conn, "business", "clockwork:findme", "ZZFACTFINDME contract signed", verified=1)
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZFACTFINDME")
    assert out["count"] == 1
    assert out["results"][0]["source_table"] == "facts"


def test_search_memory_finds_seeded_note_by_keyword(conn):
    db.create_note(conn, body="ZZNOTEFINDME renew the domain before it lapses")
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZNOTEFINDME", role="chief", role_domains=["all"])
    assert out["count"] == 1
    assert out["results"][0]["source_table"] == "notes"


def test_search_memory_finds_seeded_proposal_by_keyword(conn):
    db.add_proposal(conn, "scout", "ZZPROPFINDME call the lead back", "warm callback promised", "task")
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZPROPFINDME")
    assert out["count"] == 1
    assert out["results"][0]["source_table"] == "proposals"


def test_search_memory_days_filter(conn):
    conn.execute(
        "INSERT INTO memos (from_role, topic, body, created_at) VALUES (?,?,?,?)",
        ("scout", "old", "ZZANCIENT warm lead from long ago", "2020-01-01 00:00:00"),
    )
    conn.commit()
    memory_index.sync_memory_index(conn)
    within_30 = _search(conn, "ZZANCIENT", days=30)
    assert within_30["count"] == 0
    within_everything = _search(conn, "ZZANCIENT", days=3000)
    assert within_everything["count"] == 1


def test_search_memory_limit_is_respected_and_capped(conn):
    for i in range(60):
        db.add_memo(conn, "scout", "pipeline", f"ZZCAPTEST warm lead number {i}")
    memory_index.sync_memory_index(conn)
    small = _search(conn, "ZZCAPTEST", limit=3)
    assert small["count"] == 3
    over_cap = _search(conn, "ZZCAPTEST", limit=1000)
    assert over_cap["count"] == 50  # _MEMORY_SEARCH_MAX_LIMIT


def test_search_memory_empty_query_returns_no_results_no_crash(conn):
    out = _search(conn, "")
    assert out == {"results": [], "count": 0, "note": "empty query"}


@pytest.mark.parametrize("hostile", [
    'leads" OR 1=1 --',
    "AND OR NOT NEAR",
    "*" * 5,
    '"unterminated quote',
    "col:injected^3",
    "   ",
])
def test_search_memory_hostile_query_never_crashes(conn, hostile):
    db.add_memo(conn, "scout", "pipeline", "a plain warm lead memo")
    memory_index.sync_memory_index(conn)
    out = _search(conn, hostile)
    assert "count" in out
    assert isinstance(out["results"], list)


def test_search_memory_ordering_recency_breaks_a_relevance_tie(conn):
    """Two memos with identical body text score identically on BM25; the
    newer one must rank first once recency is blended in."""
    conn.execute(
        "INSERT INTO memos (from_role, topic, body, created_at) VALUES (?,?,?,?)",
        ("scout", "old", "ZZTIEBREAK warm lead outreach note", "2020-01-01 00:00:00"),
    )
    conn.execute(
        "INSERT INTO memos (from_role, topic, body, created_at) VALUES (?,?,?,?)",
        ("scout", "new", "ZZTIEBREAK warm lead outreach note", db.now()),
    )
    conn.commit()
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZTIEBREAK", days=3000, limit=5)
    assert out["count"] == 2
    assert out["results"][0]["occurred_at"] > out["results"][1]["occurred_at"]


def test_search_memory_ordering_relevance_beats_a_weak_recent_match(conn):
    """A document that repeats the query term (strong BM25 relevance) should
    outrank a same-day document that mentions it only once in passing --
    relevance is weighted 0.7 vs recency's 0.3 for exactly this reason."""
    conn.execute(
        "INSERT INTO memos (from_role, topic, body, created_at) VALUES (?,?,?,?)",
        ("scout", "strong", "clockwork clockwork clockwork demo booked warm lead", db.now()),
    )
    conn.execute(
        "INSERT INTO memos (from_role, topic, body, created_at) VALUES (?,?,?,?)",
        ("scout", "weak",
         "a long unrelated memo about many other things that happens to mention "
         "clockwork exactly once near the very end of an otherwise unrelated body",
         db.now()),
    )
    conn.commit()
    memory_index.sync_memory_index(conn)
    out = _search(conn, "clockwork", days=3000, limit=5)
    assert out["count"] == 2
    assert out["results"][0]["topic"] == "strong"


def test_recency_score_decays_monotonically():
    ref = date(2026, 8, 31)
    fresh = runner._memory_search_recency(ref.isoformat(), ref)
    half_life = runner._memory_search_recency(
        (ref - timedelta(days=runner._MEMORY_SEARCH_HALF_LIFE_DAYS)).isoformat(), ref)
    old = runner._memory_search_recency((ref - timedelta(days=3650)).isoformat(), ref)
    assert fresh == pytest.approx(1.0)
    assert half_life == pytest.approx(0.5, rel=1e-6)
    assert old < half_life < fresh
    assert runner._memory_search_recency(None, ref) == 0.0
    assert runner._memory_search_recency("not-a-date", ref) == 0.0


# ------------------------------------------------------- domain scoping

def test_search_memory_fact_domain_scoping_excludes_other_domain(conn):
    db.upsert_fact(conn, "personal", "partner:flowers", "ZZDOMAIN Partner likes tulips", verified=1)
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZDOMAIN", role="scout", role_domains=["business"])
    assert out["count"] == 0


def test_search_memory_fact_domain_scoping_allows_matching_domain(conn):
    db.upsert_fact(conn, "personal", "partner:flowers", "ZZDOMAIN Partner likes tulips", verified=1)
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZDOMAIN", role="lovebird", role_domains=["personal"])
    assert out["count"] == 1


def test_search_memory_fact_domain_scoping_all_is_unrestricted(conn):
    db.upsert_fact(conn, "personal", "partner:flowers", "ZZDOMAIN Partner likes tulips", verified=1)
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZDOMAIN", role="chief", role_domains=["all"])
    assert out["count"] == 1


def test_search_memory_memos_notes_proposals_not_domain_filtered(conn):
    """Only facts.* results are domain-scoped (§5.4's literal reading of
    'exactly as read_facts is'). The other five source tables are already
    broadly shared/visible today (recent_shared_memos has no domain filter),
    so a business-domain role must still see a personal-flavored memo/note/
    proposal in search results."""
    db.add_memo(conn, "lovebird", "partner", "ZZNODOMAIN Partner's birthday plan")
    db.create_note(conn, body="ZZNODOMAIN note about Partner's birthday", domain="personal")
    db.add_proposal(conn, "lovebird", "ZZNODOMAIN plan Partner's birthday", "reasoning here", "personal")
    memory_index.sync_memory_index(conn)
    out = _search(conn, "ZZNODOMAIN", role="scout", role_domains=["business"], limit=10)
    tables = {r["source_table"] for r in out["results"]}
    assert tables == {"memos", "notes", "proposals"}


# --------------------------------------------- allowlist / grant wiring

def test_search_memory_granted_to_all_ten_active_roles():
    ten = ("steward", "scout", "cfo", "wealth", "watchdog", "physician",
           "coach", "lovebird", "counsel", "chief")
    for role in ten:
        assert "search_memory" in runner.ALLOWLISTS[role], role
        assert "search_memory" in runner.interactive_allow(role)


def test_search_memory_not_granted_to_retired_roles():
    retired = ("advisor", "family", "publicist", "infra", "archivist")
    for role in retired:
        assert "search_memory" not in runner.ALLOWLISTS[role], role


def test_search_memory_reachable_from_chat_for_sample_roles():
    for role in ("scout", "cfo", "chief"):
        assert "search_memory" in runner.chat_allow([], role)


def test_search_memory_registered_with_the_mcp_server():
    assert "search_memory" in runner.ALL_TOOLS
    assert "search_memory" in runner.READ_ONLY_TOOLS
