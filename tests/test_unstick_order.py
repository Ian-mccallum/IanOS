"""SPEC-v32 Part A1: scripts/unstick_order.py.

The script is an operator script that deliberately touches the real DB via
db.connect(); this test file is the opposite - it isolates against a
throwaway DB (the standard tests/test_proposal_expiry.py fixture pattern) so
running the test suite never writes into Ian's real data.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402
from scripts import unstick_order  # noqa: E402

EIN_NAME = "Obtain EIN from IRS"
A2P_NAME = "Twilio A2P 10DLC campaign approved"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _seed_goal(conn, name, archived=0):
    conn.execute(
        """INSERT INTO goals (name, kind, target, domain, archived)
           VALUES (?, 'deadline', 'done', 'business', ?)""",
        (name, archived),
    )
    conn.commit()


def _seed_proposal(conn, action, days_old):
    pid = db.add_proposal(conn, "watchdog", action, "reasoning", "task")
    created_at = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE proposals SET created_at=? WHERE id=?", (created_at, pid))
    conn.commit()
    return pid


def _pending_status(conn, pid):
    return conn.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()[0]


def test_dry_run_is_a_true_no_op(conn):
    _seed_goal(conn, EIN_NAME)
    _seed_goal(conn, A2P_NAME)
    old_pid = _seed_proposal(conn, "old one", days_old=db.PROPOSAL_EXPIRY_DAYS + 1)
    young_pid = _seed_proposal(conn, "young one", days_old=1)

    before = conn.total_changes
    report = unstick_order.run(conn, apply=False)
    after = conn.total_changes

    assert after == before, "dry run must not write anything"
    assert set(report["goals_archived"]) == {EIN_NAME, A2P_NAME}
    assert report["proposals_expired"] == 1
    assert _pending_status(conn, old_pid) == "PENDING"
    assert _pending_status(conn, young_pid) == "PENDING"
    assert db.memo_count(conn) == 0


def test_apply_archives_both_goals_expires_old_proposals_writes_one_memo(conn):
    _seed_goal(conn, EIN_NAME)
    _seed_goal(conn, A2P_NAME)
    old_pid = _seed_proposal(conn, "old one", days_old=db.PROPOSAL_EXPIRY_DAYS + 1)
    young_pid = _seed_proposal(conn, "young one", days_old=1)

    report = unstick_order.run(conn, apply=True)

    assert set(report["goals_archived"]) == {EIN_NAME, A2P_NAME}
    assert report["goals_already_archived"] == []
    assert report["goals_not_found"] == []
    assert report["proposals_expired"] == 1

    rows = {r["name"]: r["archived"] for r in conn.execute("SELECT name, archived FROM goals")}
    assert rows[EIN_NAME] == 1
    assert rows[A2P_NAME] == 1

    assert _pending_status(conn, old_pid) == "EXPIRED"
    assert _pending_status(conn, young_pid) == "PENDING"

    memos = db.recent_memos(conn, days=1)
    assert len(memos) == 1
    assert memos[0]["from_role"] == "ian"


def test_apply_is_idempotent_on_second_run(conn):
    _seed_goal(conn, EIN_NAME)
    _seed_goal(conn, A2P_NAME)
    _seed_proposal(conn, "old one", days_old=db.PROPOSAL_EXPIRY_DAYS + 1)

    unstick_order.run(conn, apply=True)
    second = unstick_order.run(conn, apply=True)

    assert second["goals_archived"] == []
    assert set(second["goals_already_archived"]) == {EIN_NAME, A2P_NAME}
    assert second["proposals_expired"] == 0

    memos = db.recent_memos(conn, days=1)
    assert len(memos) == 1, "second run must not write a second memo"


def test_partial_state_archives_the_one_it_finds(conn):
    _seed_goal(conn, EIN_NAME)
    # A2P goal renamed / missing entirely.

    report = unstick_order.run(conn, apply=True)

    assert report["goals_archived"] == [EIN_NAME]
    assert report["goals_not_found"] == [A2P_NAME]

    row = conn.execute("SELECT archived FROM goals WHERE name=?", (EIN_NAME,)).fetchone()
    assert row["archived"] == 1

    memos = db.recent_memos(conn, days=1)
    assert len(memos) == 1
