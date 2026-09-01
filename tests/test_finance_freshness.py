"""SPEC-v20 Phase D: truthful finance ingest health and fire-once alerts."""

from datetime import datetime, timedelta
import sqlite3

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core import db, freshness, metrics


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _stamp(conn, source: str, **fields) -> dict:
    db.record_ingest_attempt(conn, source)
    assignments = ", ".join(f"{key}=?" for key in fields)
    if assignments:
        conn.execute(
            f"UPDATE ingest_log SET {assignments} WHERE source=?",
            (*fields.values(), source),
        )
        conn.commit()
    return db.ingest_status(conn, source)


def test_legacy_success_timestamp_is_backfilled(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        """CREATE TABLE ingest_log (
           id INTEGER PRIMARY KEY, source TEXT UNIQUE, last_import TEXT,
           row_count INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '')"""
    )
    legacy.execute(
        "INSERT INTO ingest_log (source,last_import) VALUES (?,?)",
        ("simplefin_chase", "2026-08-01 09:30:00"),
    )
    legacy.commit()
    legacy.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    migrated = db.connect()
    try:
        row = db.ingest_status(migrated, "simplefin_chase")
        assert row["last_attempt"] == "2026-08-01 09:30:00"
        assert row["last_success"] == "2026-08-01 09:30:00"
    finally:
        migrated.close()


def test_attempt_failure_and_zero_row_success_have_distinct_semantics(conn):
    db.record_ingest_success(conn, "simplefin_chase", 4, "known-good")
    good = db.ingest_status(conn, "simplefin_chase")

    db.record_ingest_attempt(conn, "simplefin_chase")
    db.record_ingest_failure(conn, "simplefin_chase", "network")
    failed = db.ingest_status(conn, "simplefin_chase")
    assert failed["last_import"] == good["last_import"]
    assert failed["last_success"] == good["last_success"]
    assert failed["last_error"] == "network"
    assert failed["consecutive_failures"] == 1

    db.record_ingest_success(conn, "simplefin_chase", 0, "")
    recovered = db.ingest_status(conn, "simplefin_chase")
    assert recovered["row_count"] == 0
    assert recovered["last_import"] is not None
    assert recovered["last_error"] == ""
    assert recovered["consecutive_failures"] == 0
    assert recovered["stale_alerted_at"] is None


def test_failure_rejects_raw_or_unclassified_error_content(conn):
    with pytest.raises(ValueError):
        db.record_ingest_failure(
            conn, "simplefin_chase", "401 https://user:secret@example.test",
        )
    assert db.ingest_status(conn, "simplefin_chase") is None


def test_pure_freshness_states_and_exact_48_hour_boundary():
    now = datetime(2026, 8, 16, 12, 0, 0)
    recent = (now - timedelta(hours=2)).isoformat(sep=" ")
    boundary = (now - timedelta(hours=48)).isoformat(sep=" ")

    assert freshness.evaluate(None, False, now) == "disabled"
    assert freshness.evaluate(None, True, now) == "never"
    assert freshness.evaluate({"last_attempt": recent}, True, now) == "never"
    assert freshness.evaluate({"last_attempt": boundary}, True, now) == "stale"
    assert freshness.evaluate({"last_success": recent}, True, now) == "healthy"
    assert freshness.evaluate(
        {"last_success": recent, "last_attempt": now.isoformat(sep=" "),
         "consecutive_failures": 1},
        True,
        now,
    ) == "degraded"
    assert freshness.evaluate({"last_success": boundary}, True, now) == "stale"


def test_two_recent_manual_attempts_do_not_manufacture_staleness():
    now = datetime(2026, 8, 16, 12, 0, 0)
    status = {
        "last_attempt": (now - timedelta(minutes=2)).isoformat(sep=" "),
        "consecutive_failures": 2,
    }
    assert freshness.evaluate(status, True, now) == "never"


def test_mixed_legacy_and_aware_timestamps_are_safe():
    now = datetime.fromisoformat("2026-08-16T12:00:00+00:00")
    status = {
        "last_success": "2026-08-16 09:00:00",
        "last_attempt": "2026-08-16T11:00:00+00:00",
    }
    assert freshness.evaluate(status, True, now) == "degraded"


def test_finance_metrics_share_one_result(conn):
    now = datetime(2026, 8, 16, 12, 0, 0)
    _stamp(
        conn,
        "snaptrade_fidelity",
        last_success=(now - timedelta(hours=49)).isoformat(sep=" "),
        last_import=(now - timedelta(hours=49)).isoformat(sep=" "),
    )
    configured = {"simplefin_chase": False, "snaptrade_fidelity": True}
    state = metrics.finance_state(conn, configured=configured, now=now)
    assert state["sources"]["snaptrade_fidelity"]["state"] == "stale"
    assert state["sources"]["simplefin_chase"]["state"] == "disabled"
    assert "finance" in metrics.stale_data_domains(
        conn, finance_health=state["sources"], now=now,
    )


def test_stale_alert_claim_is_fire_once_and_success_rearms(conn):
    db.record_ingest_attempt(conn, "simplefin_chase")
    assert db.claim_stale_ingest_alerts(conn, ["simplefin_chase"]) == ["simplefin_chase"]
    assert db.claim_stale_ingest_alerts(conn, ["simplefin_chase"]) == []

    db.record_ingest_success(conn, "simplefin_chase", 0)
    assert db.claim_stale_ingest_alerts(conn, ["simplefin_chase"]) == ["simplefin_chase"]


def test_state_exposes_safe_health_projection_only(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    for key in (
        "SIMPLEFIN_ACCESS_URL", "SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
        "SNAPTRADE_USER_ID", "SNAPTRADE_USER_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    connection = db.connect()
    db.record_ingest_attempt(connection, "simplefin_chase")
    db.record_ingest_failure(connection, "simplefin_chase", "auth")
    connection.close()

    payload = TestClient(app).get("/api/state").json()
    source = payload["finance_health"]["simplefin_chase"]
    assert set(source) == {
        "state", "last_success", "last_attempt", "consecutive_failures",
    }
    assert "last_error" not in payload["finance_health"]["simplefin_chase"]
    assert "auth" not in str(payload["finance_health"])


def test_holdings_and_success_can_roll_back_together(conn):
    position = {
        "account": "fidelity", "symbol": "TEST", "quantity": 1,
        "market_value": 10, "hash": "phase-d-test",
    }
    db.replace_holdings_snapshot(
        conn, "2026-08-16", [position], "snaptrade", commit=False,
    )
    db.record_ingest_success(
        conn, "snaptrade_fidelity", 1, commit=False,
    )
    conn.rollback()
    assert db.latest_holdings(conn, "snaptrade") == []
    assert db.ingest_status(conn, "snaptrade_fidelity") is None


def test_deliberate_zero_position_success_hides_old_snapshot_without_deleting_history(conn):
    position = {
        "account": "fidelity", "symbol": "HISTORY", "quantity": 1,
        "market_value": 10, "hash": "historical-position",
    }
    db.replace_holdings_snapshot(conn, "2026-08-15", [position], "snaptrade")
    db.record_ingest_success(conn, "snaptrade_fidelity", 1, "1 positions")
    assert db.portfolio_snapshot(conn)["positions"][0]["symbol"] == "HISTORY"

    # --allow-empty is represented by a durable zero-row success. The old row
    # remains available for history/audit, but no longer masquerades as current.
    db.record_ingest_success(conn, "snaptrade_fidelity", 0, "0 positions")
    assert db.portfolio_snapshot(conn) is None
    assert db.latest_holdings(conn, "snaptrade")[0]["symbol"] == "HISTORY"


# ------------------------------------------------- SPEC-v37 8.4: finance_state


def test_finance_state_reads_checking_freshness_from_its_own_source(conn, monkeypatch):
    """simplefin_chase was replaced by Plaid and is permanently 'disabled';
    hardcoding it as the checking freshness source made every checking
    balance read as stale-by-a-disabled-source no matter how current the
    real (Plaid) sync actually was."""
    monkeypatch.setenv("PLAID_CLIENT_ID", "x")
    monkeypatch.setenv("PLAID_SECRET", "y")
    monkeypatch.setenv("PLAID_ACCESS_TOKEN_CHASE", "z")
    conn.execute(
        "INSERT INTO financial_accounts (source, external_id, type, subtype, "
        "current_balance, as_of) VALUES (?,?,?,?,?,?)",
        ("plaid_chase", "checking1", "depository", "checking", 500.0, "2026-09-01"),
    )
    conn.commit()
    db.record_ingest_success(conn, "plaid_chase", 1, "1 account")
    state = metrics.finance_state(conn)
    assert state["checking"]["freshness"] == "healthy"
    assert state["checking"]["stale"] is False


# --------------------------------------------- SPEC-v37 8.4: failure memos


def test_ingest_failure_writes_a_system_memo_only_on_the_first_of_a_streak(conn):
    """A finance source that fails must not be silent (the role-crash
    precedent), but a 15-minute retry loop against an already-known-broken
    source must not spam a memo every cycle either (the fire-once-guard
    precedent, D9's push-alert note applied to ingest)."""
    db.record_ingest_failure(conn, "plaid_chase", "protocol")
    memos = db.recent_memos(conn, days=1)
    assert len(memos) == 1
    assert memos[0]["from_role"] == "system"
    assert "plaid_chase" in memos[0]["body"]

    db.record_ingest_failure(conn, "plaid_chase", "protocol")
    db.record_ingest_failure(conn, "plaid_chase", "protocol")
    assert len(db.recent_memos(conn, days=1)) == 1

    db.record_ingest_success(conn, "plaid_chase", 1, "")
    db.record_ingest_failure(conn, "plaid_chase", "network")
    assert len(db.recent_memos(conn, days=1)) == 2
