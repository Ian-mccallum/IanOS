"""Durable lifecycle tests for transient interactive-agent consultations."""

import sqlite3

import pytest

from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def test_invocation_lifecycle_is_conditional_and_projects_safe_evidence(conn):
    queued = db.create_agent_invocation(conn, "chief", "ask", "  What matters?  ")
    assert queued["status"] == "QUEUED"
    assert queued["question"] == "What matters?"
    assert queued["evidence"] == []
    assert "evidence_json" not in queued

    running = db.claim_agent_invocation(conn, queued["id"])
    assert running["status"] == "RUNNING"
    assert running["started_at"]
    assert db.claim_agent_invocation(conn, queued["id"]) is None

    done = db.finish_agent_invocation_success(
        conn,
        queued["id"],
        "  Use the plan.\x00  ",
        ["Goals", "Calendar and plan", "Goals", "RAW TOOL RESULT", {"raw": "forbidden"}],
        "claude-haiku-4-5",
        3,
        0.012345,
    )
    assert done["status"] == "SUCCEEDED"
    assert done["answer"] == "Use the plan."
    assert done["evidence"] == ["Goals", "Calendar and plan"]
    assert done["turns"] == 3
    assert done["cost_usd"] == pytest.approx(0.012345)
    assert done["finished_at"]

    assert db.finish_agent_invocation_failure(
        conn, queued["id"], "runner_error", "Try again."
    ) is None
    assert db.get_agent_invocation(conn, queued["id"])["status"] == "SUCCEEDED"


def test_direct_db_caller_cannot_persist_model_authored_or_raw_evidence(conn):
    invocation = db.create_agent_invocation(conn, "chief", "ask", "What matters?")
    db.claim_agent_invocation(conn, invocation["id"])
    done = db.finish_agent_invocation_success(
        conn,
        invocation["id"],
        "Answer",
        ["Goals", "The database row was 42", "tool args: days=60", "Notes"],
        "claude-haiku-4-5",
        2,
        0.01,
    )
    assert done["evidence"] == ["Goals", "Notes"]
    raw = conn.execute(
        "SELECT evidence_json FROM agent_invocations WHERE id=?", (invocation["id"],)
    ).fetchone()[0]
    assert raw == '["Goals","Notes"]'


def test_success_requires_claim_but_failure_can_close_a_queue(conn):
    queued = db.create_agent_invocation(conn, "scout", "ask", "Next lead?")
    assert db.finish_agent_invocation_success(
        conn, queued["id"], "answer", [], "model", 1, 0
    ) is None

    failed = db.finish_agent_invocation_failure(
        conn, queued["id"], "runner_error", "The consultation failed. Please try again."
    )
    assert failed["status"] == "FAILED"
    assert failed["error_code"] == "runner_error"
    assert failed["answer"] == ""
    assert failed["evidence"] == []
    assert db.claim_agent_invocation(conn, queued["id"]) is None


def test_create_validates_mode_question_and_bounds_answer(conn):
    with pytest.raises(ValueError):
        db.create_agent_invocation(conn, "chief", "execute", "Do it")
    with pytest.raises(ValueError):
        db.create_agent_invocation(conn, "chief", "ask", "   ")

    with pytest.raises(ValueError):
        db.create_agent_invocation(conn, "chief", "ask", "x" * 1600)
    invocation = db.create_agent_invocation(conn, "chief", "ask", "bounded answer")
    db.claim_agent_invocation(conn, invocation["id"])
    done = db.finish_agent_invocation_success(
        conn, invocation["id"], "a" * 9000, [], "m" * 200, 1, 0
    )
    assert len(done["answer"]) == 8000
    assert len(done["model"]) == 100


def test_fail_stale_marks_only_old_nonterminal_rows_interrupted(conn):
    old_queued = db.create_agent_invocation(conn, "chief", "ask", "old queued")
    old_running = db.create_agent_invocation(conn, "chief", "ask", "old running")
    fresh = db.create_agent_invocation(conn, "chief", "ask", "fresh")
    db.claim_agent_invocation(conn, old_running["id"])
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00' WHERE id=?",
        (old_queued["id"],),
    )
    conn.execute(
        "UPDATE agent_invocations SET started_at='2020-01-01 00:00:00' WHERE id=?",
        (old_running["id"],),
    )
    conn.commit()

    assert db.fail_stale_agent_invocations(conn, age_minutes=10) == 2
    for invocation_id in (old_queued["id"], old_running["id"]):
        row = db.get_agent_invocation(conn, invocation_id)
        assert row["status"] == "FAILED"
        assert row["error_code"] == "interrupted"
        assert "try again" in row["error_message"].lower()
    assert db.get_agent_invocation(conn, fresh["id"])["status"] == "QUEUED"


def test_prune_deletes_only_old_terminal_conversation_cache(conn):
    old_done = db.create_agent_invocation(conn, "chief", "ask", "old done")
    old_live = db.create_agent_invocation(conn, "chief", "ask", "old live")
    fresh_done = db.create_agent_invocation(conn, "chief", "ask", "fresh done")
    for item in (old_done, fresh_done):
        db.claim_agent_invocation(conn, item["id"])
        db.finish_agent_invocation_success(conn, item["id"], "answer", [], "m", 1, 0)
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00', "
        "finished_at='2020-01-01 00:01:00' WHERE id=?",
        (old_done["id"],),
    )
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00' WHERE id=?",
        (old_live["id"],),
    )
    conn.commit()

    assert db.prune_agent_invocations(conn, older_than_days=7) == 1
    assert db.get_agent_invocation(conn, old_done["id"]) is None
    assert db.get_agent_invocation(conn, old_live["id"])["status"] == "QUEUED"
    assert db.get_agent_invocation(conn, fresh_done["id"])["status"] == "SUCCEEDED"


def test_connect_migrates_an_existing_database_and_builds_index(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE legacy_marker (id INTEGER PRIMARY KEY)")
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(db, "DB_PATH", path)

    connection = db.connect()
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_invocations'"
        ).fetchone()
        index = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_agent_invocations_status_created'"
        ).fetchone()
        assert table is not None
        assert index is not None
    finally:
        connection.close()


def test_legacy_mode_check_migrates_to_allow_inspect_without_losing_rows(tmp_path, monkeypatch):
    """A pre-SPEC-v24 DB has mode CHECK (mode IN ('ask')). Reconnecting must
    widen it in place (SQLite cannot ALTER a CHECK) and keep existing rows.

    Moved here from the now-deleted test_agent_invocations_api.py (SPEC-v37
    deleted the Ask/inspect API endpoints, not the agent_invocations schema
    or its 'inspect' mode value, which chat's own rows never use but which
    an old database on disk may still carry)."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy.db")
    conn = db.connect()
    existing = db.create_agent_invocation(conn, "chief", "ask", "legacy question")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
        CREATE TABLE agent_invocations_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('ask')),
            question TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED'))
                DEFAULT 'QUEUED',
            answer TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            error_code TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            turns INTEGER,
            cost_usd REAL,
            started_at TEXT,
            finished_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            invocation_kind TEXT NOT NULL DEFAULT 'single'
                CHECK (invocation_kind IN ('single','room','room_child')),
            parent_id INTEGER,
            sequence_index INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO agent_invocations_old (
            id, role, mode, question, status, answer, evidence_json, error_code,
            error_message, model, turns, cost_usd, started_at, finished_at,
            created_at, invocation_kind, parent_id, sequence_index
        )
        SELECT id, role, mode, question, status, answer, evidence_json, error_code,
               error_message, model, turns, cost_usd, started_at, finished_at,
               created_at, invocation_kind, parent_id, sequence_index
        FROM agent_invocations;
        DROP TABLE agent_invocations;
        ALTER TABLE agent_invocations_old RENAME TO agent_invocations;
    """)
    conn.commit()
    conn.close()

    reconnected = db.connect()  # run_migrations fires again on connect()
    try:
        migrated = db.get_agent_invocation(reconnected, existing["id"])
        assert migrated["question"] == "legacy question"
        assert migrated["mode"] == "ask"
        inspect_row = db.create_agent_invocation(reconnected, "cfo", "inspect", "")
        assert inspect_row["mode"] == "inspect"
    finally:
        reconnected.close()
