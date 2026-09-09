"""SPEC-v25 chat tables, prune, and chip connection bits."""

import sqlite3

import pytest

from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def test_prefs_default_to_sonnet_and_reject_other_models(conn):
    prefs = db.get_chat_prefs(conn)
    assert prefs["default_model"] == db.CHAT_DEFAULT_MODEL
    updated = db.set_chat_prefs_model(conn, "claude-haiku-4-5")
    assert updated["default_model"] == "claude-haiku-4-5"
    with pytest.raises(ValueError):
        db.set_chat_prefs_model(conn, "claude-opus-4")


def test_create_thread_keeps_siblings_open_and_validates_chips(conn):
    """SPEC-v40 §3.1: threads are durable. A second thread for the same role
    leaves the first OPEN (SPEC-v26's auto-close is repealed); a CLOSED
    thread accepts exactly one patch, reopening, and nothing else."""
    first = db.create_chat_thread(conn, db.CHAT_DEFAULT_MODEL)
    second = db.create_chat_thread(conn, "claude-haiku-4-5")
    assert db.get_chat_thread(conn, first["id"])["status"] == "OPEN"
    assert second["status"] == "OPEN"
    # SPEC-v37 2.7: Files is granted by default on every new thread.
    assert second["granted_chips"] == ["files"]
    patched = db.patch_chat_thread(conn, second["id"], granted_chips=["money", "money", "calendar"])
    assert patched["granted_chips"] == ["money", "calendar"]
    with pytest.raises(ValueError):
        db.patch_chat_thread(conn, second["id"], granted_chips=["gmail"])
    db.patch_chat_thread(conn, second["id"], status="CLOSED")
    with pytest.raises(ValueError):
        db.patch_chat_thread(conn, second["id"], model="claude-haiku-4-5")
    with pytest.raises(ValueError):
        db.patch_chat_thread(conn, second["id"], status="OPEN", effort="low")
    reopened = db.patch_chat_thread(conn, second["id"], status="OPEN")
    assert reopened["status"] == "OPEN"
    assert db.patch_chat_thread(conn, second["id"], effort="low")["effort"] == "low"


def test_thread_title_is_the_first_question_and_lists_carry_counts(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    assert thread["title"] == ""
    long_q = "Review my SPAN 210 notes from this week and tell me what looks thin before the quiz"
    db.create_chat_turn(conn, thread["id"], long_q, model="claude-sonnet-5")
    db.create_chat_turn(conn, thread["id"], "second question never retitles", model="claude-sonnet-5")
    row = db.get_chat_thread(conn, thread["id"])
    assert row["title"].startswith("Review my SPAN 210 notes from this week and tell me")
    assert row["title"].endswith("…") and len(row["title"]) <= db.CHAT_THREAD_TITLE_CHARS + 1
    [listed] = db.list_chat_threads(conn)
    assert listed["turn_count"] == 2 and listed["has_summary"] is False
    assert listed["title"] == row["title"]


def test_turns_require_open_thread_and_copy_model(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    turn = db.create_chat_turn(conn, thread["id"], "  What next?  ", model="claude-sonnet-5")
    assert turn["mode"] == "chat"
    assert turn["invocation_kind"] == "chat_turn"
    assert turn["thread_id"] == thread["id"]
    assert turn["role"] == "chief"
    assert turn["question"] == "What next?"
    db.patch_chat_thread(conn, thread["id"], status="CLOSED")
    with pytest.raises(ValueError):
        db.create_chat_turn(conn, thread["id"], "again", model="claude-sonnet-5")


def test_turn_cap_and_children_cascade(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    for index in range(db.CHAT_TURNS_PER_THREAD):
        db.create_chat_turn(conn, thread["id"], f"q{index}", model="claude-sonnet-5")
    with pytest.raises(ValueError):
        db.create_chat_turn(conn, thread["id"], "overflow", model="claude-sonnet-5")
    parent = db.create_chat_thread(conn, "claude-sonnet-5")
    turn = db.create_chat_turn(conn, parent["id"], "ask specialists", model="claude-sonnet-5")
    children = db.create_chat_children(conn, turn["id"], ["scout", "physician"])
    assert [child["invocation_kind"] for child in children] == ["chat_child", "chat_child"]
    assert all(child["thread_id"] == parent["id"] for child in children)
    with pytest.raises(ValueError):
        db.create_chat_children(conn, turn["id"], ["chief", "scout"])


def test_prune_deletes_old_chat_turns_and_empty_threads_not_memos(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    turn = db.create_chat_turn(conn, thread["id"], "old", model="claude-sonnet-5")
    db.claim_agent_invocation(conn, turn["id"])
    db.finish_agent_invocation_success(conn, turn["id"], '{"verdict":"ok"}', [], "m", 1, 0)
    db.add_memo(conn, "chief", "keep-me", "live memo")
    conn.execute(
        "UPDATE agent_invocations SET created_at='2020-01-01 00:00:00', "
        "finished_at='2020-01-01 00:01:00' WHERE id=?",
        (turn["id"],),
    )
    conn.execute(
        "UPDATE chat_threads SET updated_at='2020-01-01 00:00:00' WHERE id=?",
        (thread["id"],),
    )
    conn.commit()
    # SPEC-v40 §3.4: a compacted thread outlives its turns; its summary is
    # the memory a future thread with this agent receives.
    kept = db.create_chat_thread(conn, "claude-sonnet-5")
    conn.execute(
        "UPDATE chat_threads SET updated_at='2020-01-01 00:00:00', summary='we agreed X' WHERE id=?",
        (kept["id"],),
    )
    conn.commit()
    db.prune_agent_invocations(conn, older_than_days=7)
    assert db.get_agent_invocation(conn, turn["id"]) is None
    assert db.get_chat_thread(conn, thread["id"]) is None
    assert db.get_chat_thread(conn, kept["id"])["summary"] == "we agreed X"
    memos = conn.execute("SELECT topic FROM memos WHERE topic='keep-me'").fetchall()
    assert len(memos) == 1


def test_fail_stale_includes_chat_mode(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    turn = db.create_chat_turn(conn, thread["id"], "stale", model="claude-sonnet-5")
    db.claim_agent_invocation(conn, turn["id"])
    conn.execute(
        "UPDATE agent_invocations SET started_at='2020-01-01 00:00:00' WHERE id=?",
        (turn["id"],),
    )
    conn.commit()
    assert db.fail_stale_agent_invocations(conn, age_minutes=10) == 1
    assert db.get_agent_invocation(conn, turn["id"])["error_code"] == "interrupted"


def test_chip_connected_bits_do_not_collapse(conn):
    assert db.chat_chip_connected(conn, "money") is False
    assert db.chat_chip_connected(conn, "mail") is False
    assert db.chat_chip_connected(conn, "calendar") is False
    conn.execute(
        "INSERT INTO calendar_events (date, summary, hash) VALUES ('2026-08-17','x','h1')"
    )
    conn.commit()
    assert db.chat_chip_connected(conn, "calendar") is True
    db.add_memo(conn, "ian", "email: hello", "a synced note")
    assert db.chat_chip_connected(conn, "mail") is True


def test_legacy_inspect_db_migrates_to_chat_without_losing_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy.db")
    conn = db.connect()
    existing = db.create_agent_invocation(conn, "chief", "ask", "legacy question")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript("""
        CREATE TABLE agent_invocations_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('ask', 'inspect')),
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

    reconnected = db.connect()
    try:
        migrated = db.get_agent_invocation(reconnected, existing["id"])
        assert migrated["question"] == "legacy question"
        thread = db.create_chat_thread(reconnected, "claude-sonnet-5")
        turn = db.create_chat_turn(
            reconnected, thread["id"], "chat after migrate", model="claude-sonnet-5",
        )
        assert turn["mode"] == "chat"
        assert turn["thread_id"] == thread["id"]
    finally:
        reconnected.close()


def test_v26_migration_widens_models_and_adds_role(tmp_path, monkeypatch):
    """A v25-shaped chat_threads must rebuild without losing a row."""
    import sqlite3

    path = tmp_path / "v25.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE chat_threads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model TEXT NOT NULL DEFAULT 'claude-sonnet-5'
              CHECK (model IN ('claude-haiku-4-5','claude-sonnet-5')),
            granted_chips TEXT NOT NULL DEFAULT '[]',
            specialist_sonnet INTEGER NOT NULL DEFAULT 0 CHECK (specialist_sonnet IN (0,1)),
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO chat_threads (model, granted_chips, status)
            VALUES ('claude-haiku-4-5','["money"]','OPEN');
        """
    )
    raw.commit()
    raw.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    conn = db.connect()
    try:
        row = dict(conn.execute("SELECT * FROM chat_threads").fetchone())
        assert row["role"] == "chief"
        assert row["model"] == "claude-haiku-4-5"
        assert row["granted_chips"] == '["money"]'
        assert row["status"] == "OPEN"
        # The widened CHECK accepts the new models and still refuses junk.
        conn.execute("INSERT INTO chat_threads (model, role) VALUES ('claude-opus-5','cfo')")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO chat_threads (model) VALUES ('gpt-4')")
    finally:
        conn.close()


def test_chat_turns_keep_a_longer_window_than_ask(conn):
    """SPEC-v26: chat prunes at 30 days, ask/inspect still at 7."""
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    chat_turn = db.create_chat_turn(conn, thread["id"], "old chat", model="claude-sonnet-5")
    db.claim_agent_invocation(conn, chat_turn["id"])
    db.finish_agent_invocation_success(conn, chat_turn["id"], "body", [], "m", 1, 0.0)
    ask = db.create_agent_invocation(conn, "chief", "ask", "old ask")
    db.claim_agent_invocation(conn, ask["id"])
    db.finish_agent_invocation_success(conn, ask["id"], "body", [], "m", 1, 0.0)
    # Age both to 10 days: past the ask window, inside the chat window.
    conn.execute(
        "UPDATE agent_invocations SET finished_at = datetime('now','localtime','-10 days')"
    )
    conn.commit()

    db.prune_agent_invocations(conn, older_than_days=7)
    surviving = {
        row["id"] for row in conn.execute("SELECT id FROM agent_invocations").fetchall()
    }
    assert chat_turn["id"] in surviving
    assert ask["id"] not in surviving


def test_in_flight_guard_replaces_the_cooldown(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    assert db.chat_turn_in_flight(conn, thread["id"]) is False
    turn = db.create_chat_turn(conn, thread["id"], "q", model="claude-sonnet-5")
    assert db.chat_turn_in_flight(conn, thread["id"]) is True
    db.claim_agent_invocation(conn, turn["id"])
    assert db.chat_turn_in_flight(conn, thread["id"]) is True
    db.finish_agent_invocation_success(conn, turn["id"], "body", [], "m", 1, 0.0)
    assert db.chat_turn_in_flight(conn, thread["id"]) is False


def test_dumbledore_threads_open_with_school_on(conn):
    """A role whose beat lives behind one source chip opens with it granted.
    Every other role still opens with Files alone (SPEC-v37 2.7)."""
    watchdog = db.create_chat_thread(conn, db.CHAT_DEFAULT_MODEL, role="watchdog")
    assert watchdog["granted_chips"] == ["school", "files"]  # registry order
    steward = db.create_chat_thread(conn, db.CHAT_DEFAULT_MODEL, role="steward")
    assert steward["granted_chips"] == ["files"]


def test_threads_that_predate_titles_are_backfilled_from_their_first_question(conn):
    thread = db.create_chat_thread(conn, "claude-sonnet-5")
    db.create_chat_turn(conn, thread["id"], "Where is burn this month?", model="claude-sonnet-5")
    empty = db.create_chat_thread(conn, "claude-sonnet-5")
    conn.execute("UPDATE chat_threads SET title=''")
    conn.commit()
    db.run_migrations(conn)
    assert db.get_chat_thread(conn, thread["id"])["title"] == "Where is burn this month?"
    assert db.get_chat_thread(conn, empty["id"])["title"] == ""
