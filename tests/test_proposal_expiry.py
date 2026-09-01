"""SPEC-v32 Part A: the EXPIRED status, its migration, and its walls.

EXPIRED exists because proposal dedupe is exact-match and a model rephrases:
by 2026-08-25 the real DB held 29 PENDING proposals from July, six of them the
same "confirm LLC filing status", all sitting in attention band 1 ahead of
anything real. The tests below pin the two things that make the fix safe: the
CHECK rebuild must not lose a column or a row, and a timeout must never be
counted as a verdict against the agent that proposed it.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _proposal(conn, role="watchdog", action="Confirm Illinois LLC filing status",
              created_at=None) -> int:
    pid = db.add_proposal(conn, role, action, "reasoning body", "task")
    if created_at:
        conn.execute("UPDATE proposals SET created_at=? WHERE id=?", (created_at, pid))
        conn.commit()
    return pid


# ------------------------------------------------------------------ migration

def test_migration_widens_check_without_losing_columns_or_rows(tmp_path, monkeypatch):
    """A pre-v32 proposals table must rebuild with every ALTERed column intact.

    The chat_threads.effort lesson: a rebuild that omits a column added by
    _migrate_columns silently drops the state it was meant to preserve. Every
    SPEC-v23 draft column is asserted by value, not just by presence.
    """
    path = tmp_path / "legacy.db"
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE proposals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            role              TEXT NOT NULL,
            action            TEXT NOT NULL,
            reasoning         TEXT NOT NULL,
            kind              TEXT NOT NULL DEFAULT 'task'
                              CHECK (kind IN ('money','task','legal','health','personal')),
            status            TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING','APPROVED','REJECTED')),
            created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            decided_at        TEXT,
            attachment_type   TEXT NOT NULL DEFAULT '',
            attachment_json   TEXT NOT NULL DEFAULT '',
            urgency           TEXT NOT NULL DEFAULT 'normal',
            due_at            TEXT,
            reversibility     TEXT NOT NULL DEFAULT 'reversible',
            evidence_json     TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO proposals
            (id, role, action, reasoning, kind, status, created_at, decided_at,
             attachment_type, attachment_json, urgency, due_at, reversibility,
             evidence_json)
        VALUES
            (7, 'watchdog', 'Confirm LLC status', 'blocked chain', 'task',
             'PENDING', '2026-07-21 21:33:19', NULL,
             'checklist', '{"v":1}', 'time_sensitive', '2026-07-28 09:00:00',
             'hard_to_reverse', '[{"label":"Goals"}]'),
            (8, 'cfo', 'Dispute Twilio charge', 'duplicate', 'money',
             'APPROVED', '2026-07-22 22:08:32', '2026-07-23 08:00:00',
             '', '', 'normal', NULL, 'reversible', '[]');
        """
    )
    raw.commit()
    raw.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    conn = db.connect()

    rows = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM proposals ORDER BY id")}
    assert set(rows) == {7, 8}, "the rebuild dropped a row"

    kept = rows[7]
    assert kept["role"] == "watchdog"
    assert kept["status"] == "PENDING"
    assert kept["created_at"] == "2026-07-21 21:33:19"
    # Every column that only ever arrived via _migrate_columns:
    assert kept["attachment_type"] == "checklist"
    assert kept["attachment_json"] == '{"v":1}'
    assert kept["urgency"] == "time_sensitive"
    assert kept["due_at"] == "2026-07-28 09:00:00"
    assert kept["reversibility"] == "hard_to_reverse"
    assert kept["evidence_json"] == '[{"label":"Goals"}]'

    decided = rows[8]
    assert decided["status"] == "APPROVED"
    assert decided["decided_at"] == "2026-07-23 08:00:00"

    # The widened CHECK accepts EXPIRED and still refuses junk.
    conn.execute("UPDATE proposals SET status='EXPIRED' WHERE id=7")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE proposals SET status='SNOOZED' WHERE id=8")
    conn.close()


def test_migration_is_idempotent(conn):
    """Re-running migrations on an already-v32 table must not rebuild it."""
    _proposal(conn)
    before = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()[0]
    db.run_migrations(conn)
    db.run_migrations(conn)
    after = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()[0]
    assert before == after
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1


def test_fresh_schema_accepts_expired(conn):
    pid = _proposal(conn)
    conn.execute("UPDATE proposals SET status='EXPIRED' WHERE id=?", (pid,))
    conn.commit()
    assert db.get_proposal(conn, pid)["status"] == "EXPIRED"


# --------------------------------------------------------------- expiry window

def test_expiry_window_is_pinned_at_both_edges(conn):
    """Day 7 expires, one minute younger survives. A window with one edge is
    the term_active bug: a guard that can never go false."""
    at = datetime(2026, 8, 25, 21, 30, 0)
    old = _proposal(conn, action="seven days and one minute old",
                    created_at=(at - timedelta(days=7, minutes=1)).strftime("%Y-%m-%d %H:%M:%S"))
    edge = _proposal(conn, action="exactly seven days old",
                     created_at=(at - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"))
    young = _proposal(conn, action="one minute inside the window",
                      created_at=(at - timedelta(days=7) + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"))

    assert db.expire_stale_proposals(conn, at=at) == 2

    statuses = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM proposals")}
    assert statuses[old] == "EXPIRED"
    assert statuses[edge] == "EXPIRED"
    assert statuses[young] == "PENDING"


def test_expiry_stamps_when_it_lapsed_and_is_idempotent(conn):
    at = datetime(2026, 8, 25, 21, 30, 0)
    pid = _proposal(conn, created_at="2026-07-21 21:33:19")

    assert db.expire_stale_proposals(conn, at=at) == 1
    row = db.get_proposal(conn, pid)
    assert row["status"] == "EXPIRED"
    assert row["decided_at"] == "2026-08-25 21:30:00"

    # A second sweep finds nothing: EXPIRED is terminal, not re-expirable.
    assert db.expire_stale_proposals(conn, at=at) == 0


def test_expiry_never_touches_decided_rows(conn):
    at = datetime(2026, 8, 25, 21, 30, 0)
    approved = _proposal(conn, action="approved long ago", created_at="2026-07-01 09:00:00")
    db.decide_proposal(conn, approved, "approve")
    conn.execute("UPDATE proposals SET decided_at='2026-07-02 09:00:00' WHERE id=?", (approved,))
    conn.commit()

    assert db.expire_stale_proposals(conn, at=at) == 0
    row = db.get_proposal(conn, approved)
    assert row["status"] == "APPROVED"
    assert row["decided_at"] == "2026-07-02 09:00:00"


def test_expiry_writes_no_memo(conn):
    """A timeout is not news. A memo per expiry is the nag this product bans."""
    at = datetime(2026, 8, 25, 21, 30, 0)
    _proposal(conn, created_at="2026-07-21 21:33:19")
    before = db.memo_count(conn)
    db.expire_stale_proposals(conn, at=at)
    assert db.memo_count(conn) == before


# ------------------------------------------------------- EXPIRED is not a verdict

def test_expired_leaves_the_pending_queue_and_the_compiler(conn):
    at = datetime(2026, 8, 25, 21, 30, 0)
    stale = _proposal(conn, created_at="2026-07-21 21:33:19")
    fresh = _proposal(conn, action="a proposal from this morning")
    db.expire_stale_proposals(conn, at=at)

    pending_ids = {p["id"] for p in db.pending_proposals(conn)}
    assert pending_ids == {fresh}
    assert stale not in pending_ids


def test_expired_cannot_be_approved_after_the_fact(conn):
    at = datetime(2026, 8, 25, 21, 30, 0)
    pid = _proposal(conn, created_at="2026-07-21 21:33:19")
    db.expire_stale_proposals(conn, at=at)
    assert db.decide_proposal(conn, pid, "approve") is None
    assert db.get_proposal(conn, pid)["status"] == "EXPIRED"


def test_role_stats_never_counts_expiry_as_rejection(conn):
    """SPEC-v32 law 4. The roster divides approved / (approved + rejected);
    an expired proposal must not silently move that denominator."""
    at = datetime(2026, 8, 25, 21, 30, 0)
    approved = _proposal(conn, action="a call Ian took")
    db.decide_proposal(conn, approved, "approve")
    rejected = _proposal(conn, action="a call Ian declined")
    db.decide_proposal(conn, rejected, "reject")
    _proposal(conn, action="one nobody ever read", created_at="2026-07-21 21:33:19")
    db.expire_stale_proposals(conn, at=at)

    stats = db.role_stats(conn)["watchdog"]
    assert stats["approved"] == 1
    assert stats["rejected"] == 1
    assert stats["expired"] == 1
    assert stats["pending"] == 0
    # SPEC-v37 §8.8: `made` is the ratio's denominator (approved + rejected +
    # pending), and must never count the lapsed proposal as if Ian had seen it.
    assert stats["made"] == 2
    # The ratio the roster actually renders.
    assert stats["approved"] + stats["rejected"] == 2


def test_expired_never_enters_recent_decisions(conn, monkeypatch):
    """App.jsx renders every non-APPROVED row in this list as "Rejected", so
    an expired proposal here would show Ian a verdict he never gave."""
    from fastapi.testclient import TestClient

    import api.main as main

    monkeypatch.setattr(main.db, "DB_PATH", db.DB_PATH)
    at = datetime(2026, 8, 25, 21, 30, 0)
    rejected = _proposal(conn, action="a call Ian declined")
    db.decide_proposal(conn, rejected, "reject")
    _proposal(conn, action="one nobody ever read", created_at="2026-07-21 21:33:19")
    db.expire_stale_proposals(conn, at=at)

    payload = TestClient(main.app).get("/api/state").json()
    statuses = {p["status"] for p in payload["recent_decisions"]}
    assert statuses == {"REJECTED"}
    assert "EXPIRED" not in statuses


def test_a_reraised_proposal_is_not_blocked_by_its_expired_twin(conn):
    """Dedupe scans PENDING only. If an agent files the same action again
    after a timeout, that is a genuine re-raise and must land as a new row."""
    at = datetime(2026, 8, 25, 21, 30, 0)
    first = _proposal(conn, created_at="2026-07-21 21:33:19")
    db.expire_stale_proposals(conn, at=at)
    second = _proposal(conn)
    assert second != first
    assert db.get_proposal(conn, second)["status"] == "PENDING"


# --------------------------------------------------------- the nightly sweep

def _run_nightly(monkeypatch, tmp_path, *, plan_only=False):
    """Drive run_sequence's dispatch half without the SDK.

    run_role is stubbed because the sweep and the slate are what is under test;
    ROOT is repointed so _log_dispatch cannot append to the real dispatch.log,
    and push is silenced so a test can never fire a notification at Ian.
    """
    import asyncio

    from agents import runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.push, "configured", lambda: "")

    ran: list[str] = []

    async def fake_run_role(meta, conn, brief_kind, wake_reason=""):
        ran.append(meta["name"])
        return {"ok": True, "turns": 1, "cost_usd": 0.0,
                "memos_written": 1, "brief_written": False}

    monkeypatch.setattr(runner, "run_role", fake_run_role)
    asyncio.run(runner.run_sequence(None, False, plan_only=plan_only))
    return ran


def test_nightly_expires_before_it_decides_the_slate(conn, tmp_path, monkeypatch):
    """An abandoned proposal must not be able to wake the chief."""
    _proposal(conn, created_at="2026-07-21 21:33:19")
    conn.commit()

    _run_nightly(monkeypatch, tmp_path)

    fresh = db.connect()
    try:
        assert fresh.execute(
            "SELECT status FROM proposals"
        ).fetchone()["status"] == "EXPIRED"
    finally:
        fresh.close()


def test_dry_run_writes_nothing(conn, tmp_path, monkeypatch):
    """`make plan` is advertised as free and inert (the apply_gym_grace
    precedent: nothing mutates before the plan_only return)."""
    _proposal(conn, created_at="2026-07-21 21:33:19")
    conn.commit()

    _run_nightly(monkeypatch, tmp_path, plan_only=True)

    fresh = db.connect()
    try:
        assert fresh.execute(
            "SELECT status FROM proposals"
        ).fetchone()["status"] == "PENDING"
    finally:
        fresh.close()


def test_dry_run_predicts_the_same_chief_decision_as_the_real_run(conn, tmp_path,
                                                                  monkeypatch, capsys):
    """The dry run must not promise a brief the real run will not write.

    Without the upper bound on the stale_pending window, `make plan` reports
    "brief: stale proposals" off rows the real run is about to expire.
    """
    from agents import runner

    _proposal(conn, created_at="2026-07-21 21:33:19")
    conn.commit()

    # Every role asleep, so the chief's only possible wake reason is a stale
    # proposal -- and the one on file is already past the timeout.
    monkeypatch.setattr(runner, "should_run", lambda meta, c, today, force: (False, "test"))
    _run_nightly(monkeypatch, tmp_path, plan_only=True)

    printed = capsys.readouterr().out
    assert "brief: stale proposals" not in printed
    assert "skip: nothing ran tonight" in printed


def test_a_proposal_inside_the_window_still_wakes_the_chief(conn, tmp_path,
                                                            monkeypatch, capsys):
    """The sweep must not silence the signal it was meant to bound."""
    from datetime import datetime, timedelta

    from agents import runner

    two_days_ago = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    _proposal(conn, action="a decision Ian genuinely owes", created_at=two_days_ago)
    conn.commit()

    monkeypatch.setattr(runner, "should_run", lambda meta, c, today, force: (False, "test"))
    _run_nightly(monkeypatch, tmp_path, plan_only=True)

    assert "brief: stale proposals" in capsys.readouterr().out
