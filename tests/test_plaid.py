"""Plaid link, cursor, and local-storage boundaries."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import main
from core import db, plaid
from ingest import sync_plaid


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "plaid.db")
    connection = db.connect()
    yield connection
    connection.close()


def _plaid_env(monkeypatch, item_key="chase"):
    monkeypatch.setenv("PLAID_CLIENT_ID", "client")
    monkeypatch.setenv("PLAID_SECRET", "secret")
    monkeypatch.setenv("PLAID_ENV", "sandbox")
    monkeypatch.setenv(plaid.token_env_key(item_key), "access-token")


def _account(account_id="acct-checking"):
    return {
        "account_id": account_id,
        "name": "Checking",
        "type": "depository",
        "subtype": "checking",
        "mask": "1234",
        "iso_currency_code": "USD",
        "balances": {"current": 123.45, "available": 120.0, "limit": None},
    }


def _credit_account(account_id="acct-credit"):
    return {
        "account_id": account_id,
        "name": "Card",
        "type": "credit",
        "subtype": "credit card",
        "mask": "9999",
        "iso_currency_code": "USD",
        "balances": {"current": 500.0, "available": 1500.0, "limit": 2000.0},
    }


def _transaction(transaction_id="txn-1", *, amount=12.5, name="Coffee"):
    return {
        "transaction_id": transaction_id,
        "account_id": "acct-checking",
        "date": "2026-08-17",
        "amount": amount,
        "name": name,
        "pending": False,
    }


def test_sync_applies_paginated_updates_and_stores_no_token(conn, monkeypatch):
    _plaid_env(monkeypatch)
    monkeypatch.setattr(plaid, "item", lambda key: {"item_id": "item-chase", "institution_id": "ins_1"})
    monkeypatch.setattr(plaid, "accounts", lambda key: [_account()])
    pages = iter([
        {"added": [_transaction()], "modified": [], "removed": [], "next_cursor": "page-2", "has_more": True},
        {"added": [], "modified": [_transaction(name="Coffee Shop")], "removed": [], "next_cursor": "final", "has_more": False},
    ])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: next(pages))

    result = sync_plaid.sync_item(conn, "chase")

    assert result == {"inserted": 1, "accounts": 1, "removed": 0}
    row = conn.execute("SELECT amount, description, source FROM transactions").fetchone()
    assert dict(row) == {"amount": -12.5, "description": "Coffee Shop", "source": "plaid_chase"}
    assert db.plaid_item(conn, "chase")["cursor"] == "final"
    checking = db.checking_balance(conn)
    assert checking is not None
    assert checking["balance"] == 123.45
    assert isinstance(checking["as_of"], str)
    assert "access-token" not in json.dumps(db.plaid_item(conn, "chase"))


def test_sync_removes_provider_removed_transaction(conn, monkeypatch):
    _plaid_env(monkeypatch)
    db.upsert_plaid_item(conn, "chase", "item-chase")
    db.upsert_plaid_transaction(conn, "chase", "txn-1", {
        "date": "2026-08-17", "description": "Old", "amount": -10,
        "category": "", "account": "Checking", "hash": "plaid-old", "source": "plaid_chase",
    })
    conn.commit()
    monkeypatch.setattr(plaid, "accounts", lambda key: [_account()])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: {
        "added": [], "modified": [], "removed": [{"transaction_id": "txn-1"}],
        "next_cursor": "next", "has_more": False,
    })

    result = sync_plaid.sync_item(conn, "chase")

    assert result["removed"] == 1
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_empty_provider_snapshot_clears_account_balances_and_rejects_nonfinite(conn, monkeypatch):
    _plaid_env(monkeypatch)
    db.upsert_plaid_item(conn, "chase", "item-chase")
    db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [_account()])
    conn.commit()
    monkeypatch.setattr(plaid, "accounts", lambda key: [])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: {
        "added": [], "modified": [], "removed": [], "next_cursor": "next", "has_more": False,
    })

    sync_plaid.sync_item(conn, "chase")
    assert db.financial_accounts(conn, source_prefix="plaid_") == []

    with pytest.raises(ValueError, match="malformed"):
        db.upsert_financial_accounts(conn, "plaid_chase", "chase", "Chase", [{
            **_account(), "balances": {"current": float("nan")},
        }])


def test_link_token_uses_no_store_and_never_returns_provider_error(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(main.plaid, "create_link_token", lambda key: "link-secret")
    with TestClient(main.app) as client:
        response = client.post("/api/plaid/link-token/chase")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"link_token": "link-secret"}

    monkeypatch.setattr(main.plaid, "create_link_token", lambda key: (_ for _ in ()).throw(plaid.PlaidHTTPError(400)))
    with TestClient(main.app) as client:
        failed = client.post("/api/plaid/link-token/chase")
    assert failed.status_code == 502
    assert "Plaid HTTP" not in failed.text


def test_sync_stores_account_key_on_transactions(conn, monkeypatch):
    _plaid_env(monkeypatch)
    monkeypatch.setattr(plaid, "item", lambda key: {"item_id": "item-chase", "institution_id": "ins_1"})
    monkeypatch.setattr(plaid, "accounts", lambda key: [_account()])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: {
        "added": [_transaction()], "modified": [], "removed": [],
        "next_cursor": "final", "has_more": False,
    })

    sync_plaid.sync_item(conn, "chase")

    row = conn.execute("SELECT account_key FROM transactions").fetchone()
    assert row["account_key"] == "plaid_chase:acct-checking"


def test_sync_balance_snapshot_is_idempotent_same_day(conn, monkeypatch):
    _plaid_env(monkeypatch)
    monkeypatch.setattr(plaid, "item", lambda key: {"item_id": "item-chase", "institution_id": "ins_1"})
    monkeypatch.setattr(plaid, "accounts", lambda key: [_account()])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: {
        "added": [], "modified": [], "removed": [], "next_cursor": "final", "has_more": False,
    })

    sync_plaid.sync_item(conn, "chase")
    sync_plaid.sync_item(conn, "chase")

    count = conn.execute(
        "SELECT COUNT(*) FROM balance_snapshots WHERE source = ? AND external_id = ?",
        ("plaid_chase", "acct-checking"),
    ).fetchone()[0]
    assert count == 1
    snapshot = db.account_snapshots(conn, "plaid_chase", "acct-checking")
    assert len(snapshot) == 1
    assert snapshot[0]["current"] == 123.45


def test_liabilities_failure_does_not_abort_sync(conn, monkeypatch):
    _plaid_env(monkeypatch)
    monkeypatch.setattr(plaid, "item", lambda key: {"item_id": "item-chase", "institution_id": "ins_1"})
    monkeypatch.setattr(plaid, "accounts", lambda key: [_account(), _credit_account()])
    monkeypatch.setattr(plaid, "transactions_sync", lambda key, cursor: {
        "added": [_transaction()], "modified": [], "removed": [],
        "next_cursor": "final", "has_more": False,
    })

    def _boom(key):
        raise plaid.PlaidProtocolError("PRODUCT_NOT_READY")
    monkeypatch.setattr(plaid, "liabilities", _boom)

    result = sync_plaid.sync_item(conn, "chase")

    assert result == {"inserted": 1, "accounts": 2, "removed": 0}
    assert conn.execute("SELECT COUNT(*) FROM card_liabilities").fetchone()[0] == 0
    row = conn.execute("SELECT description, source FROM transactions").fetchone()
    assert dict(row) == {"description": "Coffee", "source": "plaid_chase"}


def test_exchange_persists_only_env_token_and_returns_closed_projection(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(main.plaid, "exchange_public_token", lambda key, token: {"item_id": "item-1"})
    monkeypatch.setattr(main.plaid, "item", lambda key: {"item_id": "item-1", "institution_id": "ins_1"})
    with TestClient(main.app) as client:
        response = client.post("/api/plaid/items/chase", json={"public_token": "public-token"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"item_key": "chase", "linked": True}
    connection = db.connect()
    try:
        assert db.plaid_item(connection, "chase")["item_id"] == "item-1"
        assert "public-token" not in json.dumps(db.plaid_item(connection, "chase"))
    finally:
        connection.close()
