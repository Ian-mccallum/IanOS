"""SPEC-v32 A4: near-duplicate proposals collapse before they reach the queue.

Fixtures are the real July action texts from Ian's DB, verbatim. Exact-match
dedupe filed every one of them; the pile reached 29 and took over attention
band 1.

The asymmetry this file defends: a FALSE POSITIVE silently discards a proposal
Ian never sees, while a FALSE NEGATIVE just leaves a duplicate that
expire_stale_proposals times out. Every veto below is tuned in that direction.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402

# Verbatim from proposals #30 and #35 (watchdog, 2026-07-28 and 2026-07-29).
LLC_30 = (
    "Confirm Illinois LLC filing status with Secretary of State: retrieve receipt "
    'number, verify "filed" status, note any pending items. If filing is incomplete, '
    "identify the missing document and complete it within 24 hours."
)
LLC_35 = (
    "Confirm Illinois LLC filing status with Secretary of State by phone or online "
    "portal: (1) Is filing submitted, pending review, rejected, or complete? "
    "(2) Obtain receipt number if complete. (3) If incomplete, identify missing document."
)
# Verbatim from #11 and #36: same verb, same object, different tail.
SS4_11 = (
    "File IRS Form SS-4 (EIN application) online at irs.gov on 2026-07-23 morning, "
    "immediately after LLC filing receipt is confirmed."
)
SS4_36 = (
    "File IRS Form SS-4 (EIN application) within 2 hours of LLC receipt confirmation. "
    "Online filing at irs.gov (fastest)."
)
# Verbatim from #32: a DIFFERENT verb on the same object. Must stay separate.
SS4_PREPARE = (
    "Prepare IRS Form SS-4 (EIN application) for filing: gather Clockwork LLC legal "
    "name, address, entity type confirmation, principal business activity code."
)


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


# ------------------------------------------------------------------ similarity

def test_rephrasings_of_the_same_ask_score_above_threshold():
    assert db.proposal_similarity(LLC_30, LLC_35) >= db.PROPOSAL_SIMILARITY
    assert db.proposal_similarity(SS4_11, SS4_36) >= db.PROPOSAL_SIMILARITY


def test_similarity_is_symmetric_and_reflexive():
    assert db.proposal_similarity(LLC_30, LLC_30) == 1.0
    assert db.proposal_similarity(LLC_30, LLC_35) == db.proposal_similarity(LLC_35, LLC_30)


def test_only_the_opening_clause_counts():
    """Tails are elaboration that differs nightly. Scoring the whole string put
    two plainly identical asks at 0.41, under any usable threshold."""
    base = "Confirm Illinois LLC filing status with Secretary of State"
    assert db.proposal_similarity(
        base + ": retrieve receipt number and verify the filed status today",
        base + ": call the office before noon and report what they say",
    ) >= db.PROPOSAL_SIMILARITY


def test_a_different_verb_is_a_different_action():
    """File vs Prepare overlap 0.67 on words alone. One is do, one is get ready."""
    assert db.proposal_similarity(SS4_11, SS4_PREPARE) == 0.0
    assert db.proposal_similarity(
        "Complete Illinois LLC filing", "Confirm Illinois LLC filing status",
    ) == 0.0


def test_a_different_number_is_a_different_ask():
    """$20 and $200 overlap 0.67 on words alone. Merging those loses money."""
    assert db.proposal_similarity(
        "Dispute Twilio duplicate charge of $20",
        "Dispute Twilio duplicate charge of $200",
    ) == 0.0
    assert db.proposal_similarity(
        "Schedule 1 gym session Monday", "Schedule 3 gym sessions Monday",
    ) == 0.0


def test_unrelated_actions_score_zero():
    assert db.proposal_similarity(
        "Confirm LLC filing status", "File IRS Form SS-4 EIN application",
    ) == 0.0
    assert db.proposal_similarity("", "Confirm anything") == 0.0


# ----------------------------------------------------------------- integration

def test_a_rephrased_proposal_collapses_into_the_original(conn):
    first = db.add_proposal(conn, "watchdog", LLC_30, "chain is blocked", "task")
    second, created = db.add_proposal(
        conn, "watchdog", LLC_35, "different reasoning entirely", "task",
        return_created=True,
    )
    assert second == first
    assert created is False
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1


def test_the_oldest_row_wins_so_the_clock_does_not_restart(conn):
    """The original keeps its place in the queue; a nightly rephrase must not
    reset the age that expire_stale_proposals measures."""
    first = db.add_proposal(conn, "watchdog", LLC_30, "reason", "task")
    conn.execute("UPDATE proposals SET created_at='2026-07-28 21:32:14' WHERE id=?", (first,))
    conn.commit()
    db.add_proposal(conn, "watchdog", LLC_35, "reason", "task")
    rows = conn.execute("SELECT id, created_at FROM proposals").fetchall()
    assert len(rows) == 1
    assert rows[0]["created_at"] == "2026-07-28 21:32:14"


def test_a_different_verb_still_creates_a_row(conn):
    db.add_proposal(conn, "watchdog", SS4_11, "reason", "task")
    second, created = db.add_proposal(
        conn, "watchdog", SS4_PREPARE, "reason", "task", return_created=True,
    )
    assert created is True
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 2


def test_two_agents_reaching_the_same_conclusion_both_speak(conn):
    """Cross-role agreement is signal Ian should see, not noise to collapse."""
    db.add_proposal(conn, "watchdog", LLC_30, "reason", "task")
    other, created = db.add_proposal(
        conn, "counsel", LLC_35, "reason", "task", return_created=True,
    )
    assert created is True
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 2
    assert other != conn.execute("SELECT id FROM proposals ORDER BY id").fetchone()[0]


def test_kind_is_never_crossed(conn):
    action = "Dispute the Twilio charge from July"
    db.add_proposal(conn, "cfo", action, "reason", "money")
    _, created = db.add_proposal(
        conn, "cfo", action + " and note it", "reason", "task", return_created=True,
    )
    assert created is True


def test_a_proposal_with_a_draft_attachment_is_never_collapsed(conn):
    """An attachment carries content beyond `action`; merging would discard
    exactly the part that differed."""
    draft = {
        "version": 1,
        "type": "document_outline",
        "title": "LLC status call",
        "body": "1. Ask for the receipt number\n2. Confirm the filed date",
    }
    first = db.add_proposal(
        conn, "watchdog", LLC_30, "reason", "task", attachment=draft, return_created=True,
    )
    second, created = db.add_proposal(
        conn, "watchdog", LLC_35, "reason", "task", attachment=draft, return_created=True,
    )
    assert created is True
    assert second != first[0]


def test_a_decided_or_expired_twin_never_blocks_a_re_raise(conn):
    """Dedupe scans PENDING only. Re-raising after a decision is legitimate."""
    from datetime import datetime

    first = db.add_proposal(conn, "watchdog", LLC_30, "reason", "task")
    conn.execute("UPDATE proposals SET created_at='2026-07-28 21:32:14' WHERE id=?", (first,))
    conn.commit()
    db.expire_stale_proposals(conn, at=datetime(2026, 8, 25, 21, 30))

    second, created = db.add_proposal(
        conn, "watchdog", LLC_35, "reason", "task", return_created=True,
    )
    assert created is True
    assert second != first


def test_dedupe_writes_nothing_when_it_collapses(conn):
    db.add_proposal(conn, "watchdog", LLC_30, "reason", "task")
    before = conn.total_changes
    db.add_proposal(conn, "watchdog", LLC_35, "reason", "task")
    assert conn.total_changes == before
