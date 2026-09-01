"""SPEC-v20 Phase B: facts retain auditable memo evidence after compaction."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main  # noqa: E402
from core import db  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def old_memo(conn, *, role="archivist", topic="memory:decision", body="Ian chose this"):
    memo_id = db.add_memo(conn, role, topic, body)
    conn.execute(
        "UPDATE memos SET created_at=datetime('now', 'localtime', '-31 days') WHERE id=?",
        (memo_id,),
    )
    conn.commit()
    return memo_id


def test_cited_fact_survives_archive_and_evidence_keeps_the_original_body(conn):
    memo_id = old_memo(conn, role="scout", topic="decision:focus", body="Ian approved the campus launch plan.")
    fact_id = db.upsert_fact(
        conn, "business", "decision:campus-launch", "Campus launch is the current plan.",
        source_role="archivist", source_memo_ids=[memo_id],
    )

    first = db.compact_memos(conn, before_days=30)
    second = db.compact_memos(conn, before_days=30)

    assert first == {"compacted": 1, "summaries_written": 1}
    assert second == {"compacted": 0, "summaries_written": 0}
    fact = db.get_fact(conn, fact_id)
    assert fact["source_memo_ids"] == str(memo_id)
    evidence = db.fact_sources_for_fact(conn, fact_id)
    assert evidence == [{
        "id": memo_id,
        "from_role": "scout",
        "topic": "decision:focus",
        "body": "Ian approved the campus launch plan.",
        "created_at": evidence[0]["created_at"],
        "archived": True,
    }]
    assert all(m["id"] != memo_id for m in db.recent_memos(conn, days=365))
    archived = conn.execute(
        "SELECT archived, archived_into_id FROM memos WHERE id=?", (memo_id,)
    ).fetchone()
    assert archived["archived"] == 1 and archived["archived_into_id"] is not None


def test_citations_validate_and_none_preserves_existing_links(conn):
    memo_id = old_memo(conn, role="lovebird")
    fact_id = db.upsert_fact(conn, "personal", "partner:flowers", "Peonies", source_memo_ids=[memo_id])
    db.upsert_fact(conn, "personal", "partner:flowers", "Peonies and tulips")
    assert db.get_fact(conn, fact_id)["source_memo_ids"] == str(memo_id)

    with pytest.raises(ValueError, match="unique"):
        db.upsert_fact(conn, "personal", "partner:duplicate", "x", source_memo_ids=[memo_id, memo_id])
    with pytest.raises(ValueError, match="does not exist"):
        db.upsert_fact(conn, "personal", "partner:missing", "x", source_memo_ids=[999999])
    assert conn.execute("SELECT COUNT(*) FROM facts WHERE topic IN ('partner:duplicate', 'partner:missing')").fetchone()[0] == 0


def test_invalid_citations_roll_back_an_existing_fact_update(conn):
    memo_id = old_memo(conn, role="lovebird")
    fact_id = db.upsert_fact(
        conn, "personal", "partner:source-rollback", "Original fact", source_memo_ids=[memo_id],
    )

    with pytest.raises(ValueError, match="does not exist"):
        db.upsert_fact(
            conn, "personal", "partner:source-rollback", "Should not commit",
            source_memo_ids=[999999],
        )

    fact = db.get_fact(conn, fact_id)
    assert fact["body"] == "Original fact"
    assert fact["source_memo_ids"] == str(memo_id)


def test_public_fact_reads_derive_citations_from_the_relation(conn):
    memo_id = old_memo(conn)
    fact_id = db.upsert_fact(
        conn, "business", "decision:canonical-links", "Keep canonical links", source_memo_ids=[memo_id],
    )
    conn.execute("UPDATE facts SET source_memo_ids='999999' WHERE id=?", (fact_id,))
    conn.commit()

    assert db.get_fact(conn, fact_id)["source_memo_ids"] == str(memo_id)
    assert db.list_facts(conn)[0]["source_memo_ids"] == str(memo_id)


def test_cited_memo_cannot_be_physically_deleted(conn):
    memo_id = old_memo(conn)
    db.upsert_fact(conn, "business", "decision:protected", "keep evidence", source_memo_ids=[memo_id])

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM memos WHERE id=?", (memo_id,))

    assert db.delete_fact(conn, fact_id := conn.execute(
        "SELECT id FROM facts WHERE topic='decision:protected'"
    ).fetchone()["id"])
    conn.execute("DELETE FROM memos WHERE id=?", (memo_id,))
    conn.commit()


def test_archived_montage_stays_discoverable(conn):
    montage_id = old_memo(conn, role="coach", topic="montage: Comeback Week", body="Cold open.")
    db.compact_memos(conn, before_days=30)

    montage = db.latest_montage(conn)
    assert montage and montage["id"] == montage_id
    assert montage["archived"] == 1


def test_compaction_rolls_back_summary_when_archiving_fails(conn):
    memo_id = old_memo(conn, role="scout", topic="decision:atomic")
    conn.execute(
        """CREATE TRIGGER reject_memo_archive BEFORE UPDATE OF archived ON memos
           WHEN NEW.archived = 1
           BEGIN SELECT RAISE(ABORT, 'archive rejected'); END"""
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="archive rejected"):
        db.compact_memos(conn, before_days=30)

    original = conn.execute("SELECT archived FROM memos WHERE id=?", (memo_id,)).fetchone()
    assert original["archived"] == 0
    assert conn.execute("SELECT COUNT(*) FROM memos WHERE from_role='archivist'").fetchone()[0] == 0


def test_fact_sources_are_on_demand_not_in_normal_state(client):
    conn = db.connect()
    try:
        memo_id = old_memo(conn, role="scout", topic="evidence", body="original private-to-facts evidence")
        fact_id = db.upsert_fact(conn, "business", "decision:evidence", "Auditable conclusion", source_memo_ids=[memo_id])
        db.compact_memos(conn, before_days=30)
    finally:
        conn.close()

    sources = client.get(f"/api/facts/{fact_id}/sources")
    state = client.get("/api/state")
    assert sources.status_code == 200
    assert sources.json()["fact_id"] == fact_id
    assert sources.json()["sources"][0]["body"] == "original private-to-facts evidence"
    assert sources.json()["sources"][0]["archived"] is True
    # The active compacted summary may describe the old memo, but the archived
    # evidence row itself is absent and its body is never injected into facts.
    assert all(memo["id"] != memo_id for memo in state.json()["memos"])
    assert "original private-to-facts evidence" not in str(state.json()["facts"])


def test_legacy_source_strings_backfill_once_and_drop_missing_ids(tmp_path, monkeypatch):
    """An older database upgrades without fabricating historical evidence."""
    legacy_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", legacy_path)
    raw = sqlite3.connect(legacy_path)
    raw.executescript(
        """
        CREATE TABLE memos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_role TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL,
            priority INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL, topic TEXT NOT NULL, body TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'fact', date TEXT, recurs TEXT NOT NULL DEFAULT '',
            source_role TEXT NOT NULL DEFAULT '', source_memo_ids TEXT NOT NULL DEFAULT '',
            verified INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE (domain, topic)
        );
        INSERT INTO memos (id, from_role, topic, body) VALUES
            (7, 'ian', 'decision', 'First'), (9, 'ian', 'decision', 'Second');
        INSERT INTO facts (id, domain, topic, body, source_memo_ids)
            VALUES (4, 'business', 'decision:legacy', 'Legacy fact', '9, 7, 7, nope, 999');
        """
    )
    raw.commit()
    raw.close()

    conn = db.connect()
    try:
        assert db.get_fact(conn, 4)["source_memo_ids"] == "7,9"
        assert [source["id"] for source in db.fact_sources_for_fact(conn, 4)] == [7, 9]
        assert conn.execute("SELECT archived FROM memos WHERE id=7").fetchone()["archived"] == 0
    finally:
        conn.close()

    reopened = db.connect()
    try:
        assert reopened.execute("SELECT COUNT(*) FROM fact_sources WHERE fact_id=4").fetchone()[0] == 2
        assert reopened.execute("SELECT source_memo_ids FROM facts WHERE id=4").fetchone()[0] == "7,9"
    finally:
        reopened.close()
