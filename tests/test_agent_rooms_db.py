"""Durable parent/child lifecycle for the bounded sequential agent room."""

import sqlite3

import pytest

from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _finish(conn, invocation_id):
    assert db.claim_agent_invocation(conn, invocation_id)
    assert db.finish_agent_invocation_success(
        conn, invocation_id, "answer", ["Goals"], "claude-haiku-4-5", 2, 0.01,
    )


def test_legacy_invocations_migrate_to_single_with_parent_index(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE agent_invocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            mode TEXT NOT NULL,
            question TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'QUEUED',
            answer TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            turns INTEGER,
            cost_usd REAL,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO agent_invocations (role,mode,question)
        VALUES ('chief','ask','legacy question');
    """)
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(db, "DB_PATH", path)

    connection = db.connect()
    try:
        invocation = db.get_agent_invocation(connection, 1)
        assert invocation["invocation_kind"] == "single"
        assert invocation["parent_id"] is None
        assert invocation["sequence_index"] == 0
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_agent_invocations_parent_sequence'"
        ).fetchone()
        assert index is not None
    finally:
        connection.close()


def test_create_room_is_one_parent_and_ordered_children(conn):
    parent = db.create_agent_room(
        conn, ["scout", "physician", "steward"], "  What should tomorrow protect?  "
    )
    assert parent["role"] == "chief"
    assert parent["mode"] == "ask"
    assert parent["question"] == "What should tomorrow protect?"
    assert parent["status"] == "QUEUED"
    assert parent["invocation_kind"] == "room"
    assert parent["parent_id"] is None
    assert parent["sequence_index"] == 0

    children = db.get_agent_room_children(conn, parent["id"])
    assert [child["role"] for child in children] == ["scout", "physician", "steward"]
    assert [child["sequence_index"] for child in children] == [1, 2, 3]
    assert all(child["parent_id"] == parent["id"] for child in children)
    assert all(child["invocation_kind"] == "room_child" for child in children)
    assert all(child["status"] == "QUEUED" for child in children)
    assert db.get_agent_room_children(conn, 999999) == []

    single = db.create_agent_invocation(conn, "chief", "ask", "single")
    assert single["invocation_kind"] == "single"
    assert single["parent_id"] is None
    assert single["sequence_index"] == 0


@pytest.mark.parametrize("roles,question", [
    (["scout"], "question"),
    (["scout", "cfo", "physician", "steward"], "question"),
    (["scout", "scout"], "question"),
    (["chief", "scout"], "question"),
    (["Scout", "cfo"], "question"),
    (["bad-role", "cfo"], "question"),
    (["scout", "cfo"], "   "),
    (["scout", "cfo"], "x" * 1501),
])
def test_room_validation_writes_nothing(conn, roles, question):
    with pytest.raises(ValueError):
        db.create_agent_room(conn, roles, question)
    assert conn.execute("SELECT COUNT(*) FROM agent_invocations").fetchone()[0] == 0


def test_room_creation_rolls_back_parent_and_first_child_on_later_failure(conn):
    conn.execute("""
        CREATE TRIGGER fail_second_room_child
        BEFORE INSERT ON agent_invocations
        WHEN NEW.invocation_kind='room_child' AND NEW.sequence_index=2
        BEGIN
            SELECT RAISE(ABORT, 'injected child failure');
        END
    """)
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError, match="injected child failure"):
        db.create_agent_room(conn, ["scout", "cfo"], "Atomic?")
    assert conn.execute("SELECT COUNT(*) FROM agent_invocations").fetchone()[0] == 0


def test_prune_keeps_standalone_children_and_cascades_with_old_parent(conn):
    parent = db.create_agent_room(conn, ["scout", "cfo"], "Old room")
    children = db.get_agent_room_children(conn, parent["id"])
    for invocation in [parent, *children]:
        _finish(conn, invocation["id"])
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00', "
        "finished_at='2020-01-01 00:01:00' WHERE id=?",
        (children[0]["id"],),
    )
    conn.commit()
    assert db.prune_agent_invocations(conn, older_than_days=7) == 0
    assert db.get_agent_invocation(conn, children[0]["id"]) is not None

    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00', "
        "finished_at='2020-01-01 00:01:00' WHERE id=?",
        (parent["id"],),
    )
    conn.commit()
    assert db.prune_agent_invocations(conn, older_than_days=7) == 1
    assert db.get_agent_invocation(conn, parent["id"]) is None
    assert db.get_agent_room_children(conn, parent["id"]) == []
    assert all(db.get_agent_invocation(conn, child["id"]) is None for child in children)


def test_stale_recovery_terminalizes_live_parent_and_children(conn):
    parent = db.create_agent_room(conn, ["scout", "cfo"], "Interrupted room")
    children = db.get_agent_room_children(conn, parent["id"])
    assert db.claim_agent_invocation(conn, parent["id"])
    assert db.claim_agent_invocation(conn, children[0]["id"])
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00', "
        "started_at='2020-01-01 00:00:00' WHERE id IN (?,?)",
        (parent["id"], children[0]["id"]),
    )
    conn.commit()

    assert db.fail_stale_agent_invocations(conn, age_minutes=10) == 2
    assert db.get_agent_invocation(conn, parent["id"])["status"] == "FAILED"
    assert db.get_agent_invocation(conn, children[0]["id"])["status"] == "FAILED"
    assert db.get_agent_invocation(conn, children[1]["id"])["status"] == "QUEUED"
