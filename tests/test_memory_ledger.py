"""SPEC-v37 §5.2 / Law A6: retrieval informs, the ledger asserts. `facts` was
simultaneously the assertion store and the recall store, written by a model,
born verified=1, and read as ground truth -- six of its seventeen rows were
fabricated. This file asserts the hardening: a model-written fact is born
unverified, write_fact requires real evidence, write_memo rejects a
priority 2/3 claim with nothing behind it, and the migrations that clean up
what the old behavior already wrote.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import db  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _result_text(res: dict) -> str:
    return res["content"][0]["text"]


# --------------------------------------------------- test_fact_default_is_unverified

def test_fact_default_is_unverified(conn):
    """§12's required test, exact name. upsert_fact's own default, called
    with no verified= at all."""
    fid = db.upsert_fact(conn, "business", "test:topic", "some fact")
    row = db.get_fact(conn, fid)
    assert row["verified"] == 0


def test_connector_and_ian_edit_paths_are_unaffected_by_the_default_flip(conn):
    """The two callers that legitimately know a fact is verified already
    pass verified= explicitly -- confirm the flip doesn't silently downgrade
    them too."""
    fid_connector = db.upsert_fact(
        conn, "business", "connector:test", "synced value",
        source_role="connector-gmail", verified=0,
    )
    assert db.get_fact(conn, fid_connector)["verified"] == 0

    fid_ian = db.upsert_fact(
        conn, "personal", "ian:note", "Ian said this himself",
        source_role="ian", verified=1,
    )
    assert db.get_fact(conn, fid_ian)["verified"] == 1


# ------------------------------------------------------------ write_fact evidence

def test_write_fact_requires_evidence(conn):
    runner.RUN.update(role="cfo", conn=conn, role_domains=["finance"])
    memo_id = db.add_memo(conn, "cfo", "burn", "June ran over cap.")
    no_evidence = asyncio.run(runner.write_fact.handler({
        "topic": "market:test", "body": "some fact", "kind": "fact",
        "source_memo_ids": [memo_id],
    }))
    assert no_evidence.get("is_error") is True
    assert "evidence" in _result_text(no_evidence)
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_write_fact_evidence_must_resolve_to_a_real_row(conn):
    runner.RUN.update(role="cfo", conn=conn, role_domains=["finance"])
    memo_id = db.add_memo(conn, "cfo", "burn", "June ran over cap.")
    fake = asyncio.run(runner.write_fact.handler({
        "topic": "market:test", "body": "some fact", "kind": "fact",
        "source_memo_ids": [memo_id], "evidence": [{"source": "memo:999999"}],
    }))
    assert fake.get("is_error") is True
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


def test_write_fact_with_real_memo_evidence_succeeds_and_is_unverified(conn):
    runner.RUN.update(role="cfo", conn=conn, role_domains=["finance"])
    memo_id = db.add_memo(conn, "cfo", "burn", "June ran over cap.")
    ok = asyncio.run(runner.write_fact.handler({
        "topic": "market:test", "body": "some fact", "kind": "fact",
        "source_memo_ids": [memo_id], "evidence": [{"source": f"memo:{memo_id}"}],
    }))
    assert not ok.get("is_error")
    fact_id = json.loads(_result_text(ok))["fact_id"]
    fact = db.get_fact(conn, fact_id)
    assert fact["verified"] == 0


def test_write_fact_evidence_can_cite_a_goal_not_just_a_memo(conn):
    """The evidence mechanism is shared with create_proposal's, extended
    with a 'memo' source type -- goal/fact/document still work too."""
    cur = conn.execute(
        "INSERT INTO goals (name, target, domain) VALUES ('Test goal', '1', 'finance')"
    )
    conn.commit()
    goal_id = cur.lastrowid
    runner.RUN.update(role="cfo", conn=conn, role_domains=["finance"])
    memo_id = db.add_memo(conn, "cfo", "burn", "context")
    ok = asyncio.run(runner.write_fact.handler({
        "topic": "market:test", "body": "some fact", "kind": "fact",
        "source_memo_ids": [memo_id], "evidence": [{"source": f"goal:{goal_id}"}],
    }))
    assert not ok.get("is_error")


def test_write_fact_no_longer_lets_any_role_write_domain_all(conn):
    """SPEC-v37 §5.2: the archivist exemption is gone (archivist is
    retired); every role, including one that used to be exempt, is bound by
    its own domain now."""
    runner.RUN.update(role="wealth", conn=conn, role_domains=["finance"])
    memo_id = db.add_memo(conn, "wealth", "note", "context")
    out_of_domain = asyncio.run(runner.write_fact.handler({
        # 'partner:' namespaces to 'personal', not wealth's 'finance' domain.
        "topic": "partner:favorite-flowers", "body": "tulips", "kind": "preference",
        "source_memo_ids": [memo_id], "evidence": [{"source": f"memo:{memo_id}"}],
    }))
    assert out_of_domain.get("is_error") is True
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


# ------------------------------------------------- write_memo priority guard

def test_write_memo_priority_2_requires_a_read_this_run(conn):
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"],
                       reads_this_run=set(), memos_written=0)
    blocked = asyncio.run(runner.write_memo.handler({
        "topic": "pipeline", "body": "urgent slippage", "priority": 3,
    }))
    assert blocked.get("is_error") is True
    assert "read" in _result_text(blocked)
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0


def test_write_memo_priority_2_succeeds_after_a_real_read(conn):
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"],
                       reads_this_run=set(), memos_written=0)
    asyncio.run(runner.read_goals.handler({}))
    ok = asyncio.run(runner.write_memo.handler({
        "topic": "pipeline", "body": "urgent slippage", "priority": 3,
    }))
    assert not ok.get("is_error")


def test_write_memo_priority_0_and_1_never_need_a_read(conn):
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"],
                       reads_this_run=set(), memos_written=0)
    fyi = asyncio.run(runner.write_memo.handler({
        "topic": "quiet", "body": "nothing new", "priority": 0,
    }))
    assert not fyi.get("is_error")
    normal = asyncio.run(runner.write_memo.handler({
        "topic": "note", "body": "routine update", "priority": 1,
    }))
    assert not normal.get("is_error")


# --------------------------------------------------------------- read_facts

def test_read_facts_carries_verified_prominently(conn):
    db.upsert_fact(conn, "business", "verified:one", "a", verified=1)
    db.upsert_fact(conn, "business", "unverified:one", "b", verified=0)
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"])
    out = asyncio.run(runner.read_facts.handler({}))
    parsed = json.loads(_result_text(out))
    assert parsed["verified_count"] == 1
    assert parsed["unverified_count"] == 1
    assert all("verified" in f for f in parsed["facts"])


# --------------------------------------------------------------- migrations

def test_migration_routes_domain_all_facts_to_their_namespace_home(conn):
    conn.execute(
        "INSERT INTO facts (domain, topic, body, kind, verified) "
        "VALUES ('all', 'partner:test', 'body', 'fact', 1)"
    )
    conn.commit()
    db._migrate_facts_domain_all(conn)
    row = conn.execute("SELECT domain FROM facts WHERE topic='partner:test'").fetchone()
    assert row["domain"] == "personal"


def test_migration_domain_all_falls_back_to_business_with_no_namespace_match(conn):
    conn.execute(
        "INSERT INTO facts (domain, topic, body, kind, verified) "
        "VALUES ('all', 'unnamespaced-topic', 'body', 'fact', 1)"
    )
    conn.commit()
    db._migrate_facts_domain_all(conn)
    row = conn.execute("SELECT domain FROM facts WHERE topic='unnamespaced-topic'").fetchone()
    assert row["domain"] == "business"


def test_migration_forces_seeded_placeholder_facts_unverified(conn):
    conn.execute(
        "INSERT INTO facts (domain, topic, body, kind, verified) "
        "VALUES ('personal', 'partner:anniversary', "
        "'SEEDED PLACEHOLDER. Ian: correct this date.', 'date', 1)"
    )
    conn.execute(
        "INSERT INTO facts (domain, topic, body, kind, verified) "
        "VALUES ('college', 'uiuc:fall-registration', "
        "'UNVERIFIED. Dumbledore must ask Ian.', 'date', 1)"
    )
    conn.commit()
    db._backfill_seeded_placeholder_facts_unverified(conn)
    rows = conn.execute("SELECT verified FROM facts").fetchall()
    assert all(r["verified"] == 0 for r in rows)


def test_migration_never_touches_a_real_verified_fact(conn):
    fid = db.upsert_fact(conn, "personal", "partner:real-preference", "she likes tulips",
                          verified=1)
    db._backfill_seeded_placeholder_facts_unverified(conn)
    assert db.get_fact(conn, fid)["verified"] == 1


def test_migrations_are_idempotent(conn):
    conn.execute(
        "INSERT INTO facts (domain, topic, body, kind, verified) "
        "VALUES ('all', 'market:test', 'SEEDED PLACEHOLDER. x', 'fact', 1)"
    )
    conn.commit()
    db._migrate_facts_domain_all(conn)
    db._backfill_seeded_placeholder_facts_unverified(conn)
    db._migrate_facts_domain_all(conn)
    db._backfill_seeded_placeholder_facts_unverified(conn)
    row = conn.execute("SELECT domain, verified FROM facts WHERE topic='market:test'").fetchone()
    assert row["domain"] == "finance"
    assert row["verified"] == 0
