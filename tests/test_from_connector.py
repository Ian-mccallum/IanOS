"""Connector loader: validation, forced fields, dedup, and the no-transactions rule."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from ingest.from_connector import load
from agents import runner


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ------------------------------------------------------------ calendar

def test_calendar_event_loads_and_dedupes(conn):
    payload = {"records": [{"kind": "calendar_event", "date": "2026-07-18",
                            "start_time": "09:00", "end_time": "10:30",
                            "summary": "Riverbend demo call", "category": ""}]}
    r1 = load(payload, "calendar", conn)
    assert r1["loaded"] == {"calendar_event": 1}
    row = conn.execute("SELECT * FROM calendar_events").fetchone()
    assert row["category"] == "work"          # keyword-categorized
    assert row["duration_min"] == 90
    r2 = load(payload, "calendar", conn)      # identical re-run
    assert r2["loaded"] == {} and r2["deduped"] == {"calendar_event": 1}
    assert _count(conn, "calendar_events") == 1
    log = db.ingest_status(conn, "calendar")  # exact source name clears staleness
    assert log is not None and log["row_count"] == 1


# ---------------------------------------------------------------- facts

def test_fact_verified_and_source_role_forced(conn):
    payload = {"records": [{"kind": "fact", "topic": "market:namecheap-renewal",
                            "body": "renews 3/2 for $12.98", "fact_kind": "date",
                            "date": "2027-03-02", "verified": 1,
                            "source_role": "ian"}]}
    r = load(payload, "gmail", conn)
    assert r["loaded"] == {"fact": 1}
    row = conn.execute("SELECT * FROM facts").fetchone()
    assert row["verified"] == 0               # forced despite payload
    assert row["source_role"] == "connector-gmail"
    assert row["domain"] == "finance"         # market: namespace routing


def test_fact_date_kind_requires_date(conn):
    payload = {"records": [{"kind": "fact", "topic": "uiuc:reg",
                            "body": "x", "fact_kind": "date"}]}
    r = load(payload, "gmail", conn)
    assert len(r["rejected"]) == 1
    idx, kind, reason = r["rejected"][0]
    assert idx == 0 and kind == "fact" and "date" in reason
    assert _count(conn, "facts") == 0


def test_fact_partner_namespace_routes_personal(conn):
    payload = {"records": [{"kind": "fact", "topic": "partner:concert",
                            "body": "mentioned a concert 8/2", "fact_kind": "date",
                            "date": "2026-08-02"}]}
    load(payload, "gmail", conn)
    assert conn.execute("SELECT domain FROM facts").fetchone()["domain"] == "personal"


# ------------------------------------------------------------- documents

def test_document_pending_dedup_and_tripwire(conn):
    payload = {"records": [{"kind": "document", "name": "Riverbend agreement",
                            "path": "drive://Contracts/fv.pdf"}]}
    load(payload, "drive", conn)
    load(payload, "drive", conn)              # same (name, path): no dup
    assert _count(conn, "documents") == 1
    assert conn.execute("SELECT status FROM documents").fetchone()["status"] == "pending"
    fired = runner.pending_documents()(conn, date.today())
    assert fired is not None and "pending" in fired


# ----------------------------------------------------------------- notes

def test_note_priority_pinned_prefix_truncated_deduped(conn):
    payload = {"records": [{"kind": "note", "topic": "Riverbend reply",
                            "body": "x" * 900, "priority": 3}]}
    load(payload, "gmail", conn)
    row = conn.execute("SELECT * FROM memos").fetchone()
    assert row["priority"] == 1               # pinned despite payload
    assert row["topic"].startswith("email: ")
    assert len(row["body"]) == 500            # truncated
    assert row["from_role"] == "ian"
    r2 = load(payload, "gmail", conn)         # identical within 7 days
    assert r2["deduped"] == {"note": 1}
    assert _count(conn, "memos") == 1


# ----------------------------------------------------------- hard rules

def test_transaction_kind_rejected(conn):
    payload = {"records": [{"kind": "transaction", "date": "2026-07-01",
                            "description": "TWILIO", "amount": -20.0}]}
    r = load(payload, "gmail", conn)
    assert len(r["rejected"]) == 1 and "unsupported kind" in r["rejected"][0][2]
    assert _count(conn, "transactions") == 0


def test_batch_partial_failure_loads_the_rest(conn):
    payload = {"records": [
        {"kind": "note", "topic": "a", "body": "ok"},
        {"kind": "fact", "topic": "uiuc:x", "body": "b", "fact_kind": "date"},  # bad
        {"kind": "document", "name": "doc"},
    ]}
    r = load(payload, "gmail", conn)
    assert r["n_loaded"] == 2 and len(r["rejected"]) == 1


def test_all_rejected_batch(conn):
    payload = {"records": [{"kind": "nope"}, {"kind": "transaction"}]}
    r = load(payload, "gmail", conn)
    assert r["n_loaded"] == 0 and len(r["rejected"]) == 2


def test_malformed_payload_raises(conn):
    with pytest.raises(ValueError):
        load({"rows": []}, "gmail", conn)
    with pytest.raises(ValueError):
        load({"records": []}, "slack", conn)


def test_dry_run_writes_nothing(conn):
    payload = {"records": [
        {"kind": "calendar_event", "date": "2026-07-18", "summary": "Gym"},
        {"kind": "fact", "topic": "uiuc:x", "body": "b", "fact_kind": "fact"},
        {"kind": "document", "name": "doc"},
        {"kind": "note", "topic": "t", "body": "b"},
    ]}
    r = load(payload, "gmail", conn, dry_run=True)
    assert r["n_loaded"] == 4
    for table in ("calendar_events", "facts", "documents", "memos", "ingest_log"):
        assert _count(conn, table) == 0, table
