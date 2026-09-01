"""SPEC-v24 BUILD 1-3: transactions/account detail endpoints and the
/api/state financial_accounts augmentation (utilization + liabilities)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from api import main
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _insert_txn(connection, **overrides):
    values = {
        "date": "2026-08-01", "description": "Coffee", "amount": -5.0,
        "category": "personal", "account": "Checking", "account_key": "",
        "source": "csv",
    }
    values.update(overrides)
    connection.execute(
        """INSERT INTO transactions (date, description, amount, category, account, account_key, source)
           VALUES (?,?,?,?,?,?,?)""",
        (values["date"], values["description"], values["amount"], values["category"],
         values["account"], values["account_key"], values["source"]),
    )
    connection.commit()


# ------------------------------------------------------- BUILD 1: /api/transactions

def test_get_transactions_returns_rows_and_totals(client, conn):
    _insert_txn(conn, description="Coffee", amount=-5.0, category="personal", date="2026-08-01")
    _insert_txn(conn, description="Salary", amount=1000.0, category="income", date="2026-08-02")

    response = client.get("/api/transactions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["sum_in"] == 1000.0
    assert body["sum_out"] == 5.0
    assert len(body["rows"]) == 2
    # newest first (list_transactions orders by date DESC, id DESC)
    assert body["rows"][0]["description"] == "Salary"


def test_get_transactions_applies_filters_matching_list_and_count(client, conn):
    _insert_txn(conn, description="Coffee", amount=-5.0, category="personal", date="2026-08-01",
                account_key="plaid_chase:acct-1")
    _insert_txn(conn, description="Coffee", amount=-6.0, category="personal", date="2026-07-01",
                account_key="plaid_chase:acct-2")

    response = client.get("/api/transactions", params={"account_key": "plaid_chase:acct-1"})
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["amount"] == -5.0

    response = client.get("/api/transactions", params={"month": "2026-07"})
    body = response.json()
    assert body["total"] == 1
    assert body["rows"][0]["date"] == "2026-07-01"

    response = client.get("/api/transactions", params={"q": "coffee"})
    assert response.json()["total"] == 2


def test_get_transactions_clamps_limit_and_offset(client, conn):
    for i in range(5):
        _insert_txn(conn, description=f"Item {i}", amount=-1.0, date=f"2026-08-{i + 1:02d}")

    response = client.get("/api/transactions", params={"limit": 10000, "offset": -50})
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 5  # only 5 rows exist, limit clamped to <=200 but never fabricates rows
    assert body["total"] == 5


# ------------------------------------------------------- BUILD 2: /api/accounts/{source}/{external_id}

def test_get_account_detail_returns_full_shape(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-checking", "name": "Checking", "type": "depository",
        "subtype": "checking", "mask": "1234",
        "balances": {"current": 500.0, "available": 480.0, "limit": None},
    }], as_of=db.now())
    conn.commit()
    _insert_txn(conn, description="Coffee", amount=-5.0, account_key="plaid_chase:acct-checking")

    response = client.get("/api/accounts/plaid_chase/acct-checking")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "plaid_chase"
    assert body["external_id"] == "acct-checking"
    assert body["current_balance"] == 500.0
    assert body["liabilities"] is None
    assert body["snapshots_90d"] == []
    assert len(body["recent_transactions"]) == 1
    assert body["recent_transactions"][0]["description"] == "Coffee"
    assert body["holdings"] == []


def test_get_account_detail_404_for_missing_account(client):
    response = client.get("/api/accounts/plaid_chase/does-not-exist")
    assert response.status_code == 404


# ------------------------------------------------------- BUILD 3: /api/state financial_accounts

def test_state_includes_plaid_and_snaptrade_accounts(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-checking", "name": "Checking", "type": "depository",
        "subtype": "checking", "mask": "1234",
        "balances": {"current": 500.0, "available": 480.0, "limit": None},
    }], as_of=db.now())
    db.upsert_financial_accounts(conn, "snaptrade", "fidelity", "SnapTrade", [{
        "account_id": "acct-brokerage", "name": "Brokerage", "type": "investment",
        "subtype": "brokerage", "mask": "9999",
        "balances": {"current": 10000.0, "available": None, "limit": None},
    }], as_of=db.now())
    conn.commit()

    response = client.get("/api/state")
    assert response.status_code == 200
    accounts = response.json()["financial_accounts"]
    sources = {(a["source"], a["external_id"]) for a in accounts}
    assert ("plaid_chase", "acct-checking") in sources
    assert ("snaptrade", "acct-brokerage") in sources


def test_state_credit_accounts_get_utilization_and_liabilities(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-credit", "name": "Card", "type": "credit",
        "subtype": "credit card", "mask": "9999",
        "balances": {"current": 500.0, "available": 1500.0, "limit": 2000.0},
    }], as_of=db.now())
    db.upsert_card_liabilities(
        conn, "plaid_chase", "acct-credit",
        statement_balance=500.0, minimum_payment=25.0,
        due_date="2026-09-01", apr=24.99, is_overdue=False,
    )
    conn.commit()

    accounts = client.get("/api/state").json()["financial_accounts"]
    credit = next(a for a in accounts if a["external_id"] == "acct-credit")
    assert credit["utilization"] == 0.25
    assert credit["liabilities"]["statement_balance"] == 500.0
    assert credit["liabilities"]["due_date"] == "2026-09-01"
    assert credit["liabilities"]["minimum_payment"] == 25.0
    assert credit["liabilities"]["apr"] == 24.99


def test_state_credit_account_without_liability_row_omits_the_key(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-credit-no-liab", "name": "Card", "type": "credit",
        "subtype": "credit card", "mask": "1111",
        "balances": {"current": 100.0, "available": 400.0, "limit": 500.0},
    }], as_of=db.now())
    conn.commit()

    accounts = client.get("/api/state").json()["financial_accounts"]
    credit = next(a for a in accounts if a["external_id"] == "acct-credit-no-liab")
    assert credit["utilization"] == 0.2
    assert "liabilities" not in credit


def test_state_credit_account_with_no_limit_has_null_utilization(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-credit-no-limit", "name": "Card", "type": "credit",
        "subtype": "credit card", "mask": "2222",
        "balances": {"current": 100.0, "available": None, "limit": None},
    }], as_of=db.now())
    conn.commit()

    accounts = client.get("/api/state").json()["financial_accounts"]
    credit = next(a for a in accounts if a["external_id"] == "acct-credit-no-limit")
    assert credit["utilization"] is None


def test_state_non_credit_accounts_get_no_utilization_key(client, conn):
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
        "account_id": "acct-checking-2", "name": "Checking", "type": "depository",
        "subtype": "checking", "mask": "3333",
        "balances": {"current": 200.0, "available": 200.0, "limit": None},
    }], as_of=db.now())
    conn.commit()

    accounts = client.get("/api/state").json()["financial_accounts"]
    checking = next(a for a in accounts if a["external_id"] == "acct-checking-2")
    assert "utilization" not in checking
    assert "liabilities" not in checking


# ------------------------------------------------- SPEC-v37 §8.4: refresh control

def test_money_refresh_is_501_when_no_finance_source_is_configured(client, monkeypatch):
    monkeypatch.setattr(main, "_money_refresh_started_at", 0.0)
    monkeypatch.setattr(main, "_finance_source_configured", lambda: False)
    response = client.post("/api/money/refresh")
    assert response.status_code == 501


def test_money_refresh_is_200_throttled_within_cooldown(client, monkeypatch):
    """200, not 429/409, on throttle (the plan-sync/btc-sync precedent): the
    Money hero can tap this without ever surfacing an error toast for
    tapping it twice."""
    monkeypatch.setattr(main, "_finance_source_configured", lambda: True)
    monkeypatch.setattr(main, "_money_refresh_started_at", time.time())
    response = client.post("/api/money/refresh")
    assert response.status_code == 200
    assert response.json() == {"ok": True, "throttled": True}


# ------------------------------------------------- SPEC-v37 §8.6: roster consent

def test_roster_flags_health_sharing_off_only_for_health_roles(client, conn):
    roster = client.get("/api/state").json()["roster"]
    physician = next(r for r in roster if r["role"] == "physician")
    scout = next(r for r in roster if r["role"] == "scout")
    assert physician["health_sharing_off"] is True
    assert scout["health_sharing_off"] is False

    db.set_health_ai_sharing(conn, True, "v1")
    roster = client.get("/api/state").json()["roster"]
    physician = next(r for r in roster if r["role"] == "physician")
    assert physician["health_sharing_off"] is False
