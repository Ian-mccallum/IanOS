"""SPEC-v37 §5.3 / §8.7: the archivist becomes a function.

`core.ledger.distill()` is the only thing allowed to promote a `facts` row
now that the model-driven weekly archivist is retired. This file asserts:
each of the four deterministic extractors promotes a `verified=1` fact from
a real row it recognizes, and does NOT promote from a row that fails its own
stated criterion; running `distill()` twice never duplicates a fact
(idempotency); compaction (`db.compact_memos`) actually runs from inside
`distill()`; and `distill()` is wired into the end of `run_sequence`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, ledger, school  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _fact(conn, topic: str):
    row = conn.execute("SELECT * FROM facts WHERE topic = ?", (topic,)).fetchone()
    return dict(row) if row else None


def _fact_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]


# ------------------------------------------------------- calendar extractor

def test_calendar_extractor_promotes_a_recurring_named_event(conn):
    conn.execute(
        "INSERT INTO calendar_events (date, summary, category, hash) "
        "VALUES ('2026-09-10', \"Mom's Birthday\", 'personal', 'h1')"
    )
    conn.commit()

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["calendar_dates"] == 1
    fact = _fact(conn, "calendar:moms-birthday")
    assert fact is not None
    assert fact["verified"] == 1
    assert fact["kind"] == "date"
    assert fact["recurs"] == "yearly"
    assert fact["domain"] == "personal"
    assert fact["source_role"] == "ledger"


def test_calendar_extractor_skips_a_routine_meeting(conn):
    """A one-off meeting is not a named recurring life event -- routine
    noise, exactly what the criterion is meant to exclude."""
    conn.execute(
        "INSERT INTO calendar_events (date, summary, category, hash) "
        "VALUES ('2026-09-10', 'Team standup', 'work', 'h2')"
    )
    conn.commit()

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["calendar_dates"] == 0
    assert _fact_count(conn) == 0


def test_calendar_extractor_skips_school_projected_rows(conn):
    """category='school' rows are school_calendar_projection's own copy of
    a school_items row; the school extractor owns that deadline, so this
    branch must not double-file it even if the summary happens to match."""
    conn.execute(
        "INSERT INTO calendar_events (date, summary, category, hash) "
        "VALUES ('2026-09-10', 'CS 225 Final anniversary review', 'school', 'h3')"
    )
    conn.commit()

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["calendar_dates"] == 0


# --------------------------------------------------------- school extractor

def _inventory():
    return {"courses": [{
        "course_id": "cs-225",
        "code": "CS 225",
        "name": "Data Structures",
        "credits": 4,
        "cross_listings": ["CS 225 (fa26)"],
        "meetings": [],
        "grading": {"categories": []},
        "key_policy_flags": {},
    }]}


def _canvas_item(item_id: str, kind: str, title: str = "Item") -> dict:
    return {
        "external_id": item_id,
        "course_label": "CS 225 (fa26)",
        "title": title,
        "kind": kind,
        "due_at": "2026-10-14T09:00",
        "start_at": "2026-10-14T09:00",
        "end_at": "2026-10-14T10:15",
        "all_day": False,
        "location": "",
    }


def test_school_extractor_promotes_an_exam(conn):
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item("canvas:mid1", "exam", "Midterm 1")])

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["school_exams"] == 1
    item_id = conn.execute(
        "SELECT id FROM school_items WHERE external_item_id = 'canvas:mid1'"
    ).fetchone()["id"]
    fact = _fact(conn, f"uiuc:exam:{item_id}")
    assert fact is not None
    assert fact["verified"] == 1
    assert fact["domain"] == "college"
    assert fact["date"] == "2026-10-14"


def test_school_extractor_skips_a_routine_assignment(conn):
    """Weekly homework recurs constantly -- not the one-time, high-stakes
    'an exam' shape the spec names as worth a lifetime fact."""
    school.seed_inventory(conn, _inventory())
    school.import_canvas_items(conn, [_canvas_item("canvas:hw1", "assignment", "HW 1")])

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["school_exams"] == 0


def test_school_extractor_degrades_gracefully_with_no_school_table(conn):
    """school_items is created lazily; an install that never touched School
    must not crash the nightly run."""
    summary = ledger.distill(conn)
    assert summary["facts_promoted"]["school_exams"] == 0


# ------------------------------------------------------ financial accounts

def _seed_account(conn, source="snaptrade", external_id="acct-1",
                   institution="Fidelity", name="Roth IRA", type_="investment",
                   subtype="roth", balance=12345.67):
    conn.execute(
        """INSERT INTO financial_accounts
           (source, external_id, institution, name, type, subtype, current_balance)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source, external_id, institution, name, type_, subtype, balance),
    )
    conn.commit()


def test_financial_extractor_promotes_account_identity_not_a_balance(conn):
    _seed_account(conn)

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["financial_accounts"] == 1
    fact = _fact(conn, "market:account:snaptrade:acct-1")
    assert fact is not None
    assert fact["verified"] == 1
    assert fact["domain"] == "finance"
    assert "Fidelity" in fact["body"]
    # The whole point: no dollar figure, because it would be stale the
    # instant the account re-syncs.
    assert "12,345" not in fact["body"] and "12345" not in fact["body"]
    assert "$" not in fact["body"]


def test_financial_extractor_skips_an_incomplete_row(conn):
    """No institution/name on file reads as a sync artifact, not a real
    linked account."""
    _seed_account(conn, institution="", name="")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["financial_accounts"] == 0


# ------------------------------------------------------------- proposals

def test_proposal_extractor_promotes_a_decided_proposal(conn):
    pid = db.add_proposal(conn, "cfo", "Move $500 to savings", "runway math", "money")
    db.decide_proposal(conn, pid, "approve")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["proposal_decisions"] == 1
    fact = _fact(conn, f"proposal:{pid}")
    assert fact is not None
    assert fact["verified"] == 1
    assert fact["domain"] == "finance"
    assert "approved" in fact["body"]


def test_proposal_extractor_skips_an_expired_proposal(conn):
    """EXPIRED is a timeout, never a verdict (SPEC-v32) -- promoting one
    would fabricate a decision Ian never actually made."""
    from datetime import datetime

    pid = db.add_proposal(conn, "watchdog", "Confirm LLC status", "reasoning", "task")
    conn.execute("UPDATE proposals SET created_at = '2026-01-01 00:00:00' WHERE id = ?", (pid,))
    conn.commit()
    db.expire_stale_proposals(conn, at=datetime(2026, 8, 1))

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["proposal_decisions"] == 0
    assert _fact(conn, f"proposal:{pid}") is None


def test_proposal_extractor_skips_a_pending_proposal(conn):
    db.add_proposal(conn, "watchdog", "Confirm LLC status", "reasoning", "task")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["proposal_decisions"] == 0


# ------------------------------------------------------------------ goals

def _seed_goal(conn, current_value="filed", kind="deadline", domain="business", archived=0):
    cur = conn.execute(
        "INSERT INTO goals (name, kind, target, domain, current_value, archived) "
        "VALUES ('Illinois LLC filing', ?, '1', ?, ?, ?)",
        (kind, domain, current_value, archived),
    )
    conn.commit()
    return cur.lastrowid


def test_goal_extractor_promotes_a_completed_deadline_goal(conn):
    gid = _seed_goal(conn, current_value="filed")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["completed_goals"] == 1
    fact = _fact(conn, f"goal:{gid}:done")
    assert fact is not None
    assert fact["verified"] == 1
    assert fact["domain"] == "business"


def test_goal_extractor_skips_an_incomplete_deadline_goal(conn):
    _seed_goal(conn, current_value="in progress")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["completed_goals"] == 0


def test_goal_extractor_skips_a_quota_goal_even_when_on_track(conn):
    """A quota's ON-TRACK read is a recurring weekly status, not a discrete,
    non-reversible completion -- it can (and does) flip back next week."""
    _seed_goal(conn, kind="quota", current_value="done")

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["completed_goals"] == 0


def test_goal_extractor_skips_an_archived_goal(conn):
    _seed_goal(conn, current_value="filed", archived=1)

    summary = ledger.distill(conn)

    assert summary["facts_promoted"]["completed_goals"] == 0


# --------------------------------------------------------------- idempotent

def test_distill_twice_does_not_duplicate_facts(conn):
    conn.execute(
        "INSERT INTO calendar_events (date, summary, category, hash) "
        "VALUES ('2026-09-10', \"Mom's Birthday\", 'personal', 'h1')"
    )
    _seed_account(conn)
    pid = db.add_proposal(conn, "cfo", "Move $500 to savings", "runway math", "money")
    db.decide_proposal(conn, pid, "approve")
    _seed_goal(conn, current_value="filed")
    conn.commit()

    first = ledger.distill(conn)
    n_after_first = _fact_count(conn)
    second = ledger.distill(conn)
    n_after_second = _fact_count(conn)

    assert first["facts_promoted_total"] == 4
    assert second["facts_promoted_total"] == 4
    assert n_after_first == n_after_second
    assert n_after_first == 4


# ---------------------------------------------------------------- compaction

def test_distill_compacts_old_memos(conn):
    old_id = db.add_memo(conn, "cfo", "burn:june", "June ran over cap.")
    conn.execute(
        "UPDATE memos SET created_at = datetime('now', 'localtime', '-40 days') WHERE id = ?",
        (old_id,),
    )
    conn.commit()

    summary = ledger.distill(conn)

    assert summary["compaction"]["compacted"] == 1
    assert summary["compaction"]["summaries_written"] == 1
    row = conn.execute("SELECT archived, archived_into_id FROM memos WHERE id = ?", (old_id,)).fetchone()
    assert row["archived"] == 1
    assert row["archived_into_id"] is not None


def test_distill_leaves_recent_memos_alone(conn):
    recent_id = db.add_memo(conn, "cfo", "burn:today", "Fresh signal.")

    ledger.distill(conn)

    row = conn.execute("SELECT archived FROM memos WHERE id = ?", (recent_id,)).fetchone()
    assert row["archived"] == 0


# ---------------------------------------------------- wired into run_sequence

def _run_nightly(monkeypatch, tmp_path):
    """Drive run_sequence without the SDK (test_proposal_expiry.py's
    pattern): run_role is stubbed so no role actually executes, ROOT is
    repointed so _log_dispatch cannot touch the real dispatch.log, and push
    is silenced so a test can never fire a notification at Ian.

    A separate SPEC-v37 §5.4 effort (`core.memory_index`, the search_memory
    index) is being built concurrently in this same file and is out of
    scope here; its indexer needs school_note_sessions to exist, which a
    bare `db.connect()` never creates (lazy schema). Stubbing it keeps this
    test focused on what it actually asserts: that `ledger.distill()` is
    wired into the end of `run_sequence`, not a review of that other
    feature's own table-existence handling.
    """
    from agents import runner

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner.push, "configured", lambda: "")
    monkeypatch.setattr(runner.memory_index, "sync_memory_index", lambda conn: 0)

    async def fake_run_role(meta, conn, brief_kind, wake_reason="", now=None):
        return {"ok": True, "turns": 1, "cost_usd": 0.0,
                "memos_written": 1, "brief_written": False}

    monkeypatch.setattr(runner, "run_role", fake_run_role)
    asyncio.run(runner.run_sequence(None, False))


def test_distill_is_wired_into_run_sequence(conn, tmp_path, monkeypatch):
    pid = db.add_proposal(conn, "cfo", "Move $500 to savings", "runway math", "money")
    db.decide_proposal(conn, pid, "approve")
    conn.commit()

    _run_nightly(monkeypatch, tmp_path)

    fresh = db.connect()
    try:
        fact = fresh.execute(
            "SELECT * FROM facts WHERE topic = ?", (f"proposal:{pid}",)
        ).fetchone()
        assert fact is not None
        assert fact["verified"] == 1
    finally:
        fresh.close()
