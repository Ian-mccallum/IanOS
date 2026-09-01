"""Tests for ianOS metrics and migrations."""

import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, metrics


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def test_migrations_idempotent(conn):
    c2 = db.connect()
    assert isinstance(db.all_goals(c2), list)
    c2.close()


def test_seed_holdings_are_deleted_and_the_migration_is_idempotent(conn):
    """SPEC-v37 §8.4: four source='seed' rows (2026-07-21, $7,420 combined)
    that real SnapTrade data never replaced -- a cliff to $1,742 in any
    history view. Only source='seed' is touched; a real snaptrade row
    survives."""
    conn.execute(
        "INSERT INTO holdings (account, symbol, quantity, market_value, as_of_date, source, hash) "
        "VALUES ('fidelity','AAPL',12,2280.0,'2026-07-21','seed','seed-aapl')"
    )
    conn.execute(
        "INSERT INTO holdings (account, symbol, quantity, market_value, as_of_date, source, hash) "
        "VALUES ('fidelity','VTI',8,1000.0,'2026-08-01','snaptrade','real-vti')"
    )
    conn.commit()
    db.run_migrations(conn)
    conn.commit()
    remaining = conn.execute("SELECT source, symbol FROM holdings").fetchall()
    assert [dict(r) for r in remaining] == [{"source": "snaptrade", "symbol": "VTI"}]

    # Idempotent: running it again with none left to delete changes nothing.
    db.run_migrations(conn)
    conn.commit()
    assert conn.execute("SELECT COUNT(*) n FROM holdings").fetchone()["n"] == 1


def test_resolve_goal_actuals_burn(conn):
    conn.execute(
        "INSERT INTO goals (name,kind,target,domain,metric_key) VALUES (?,?,?,?,?)",
        ("Monthly burn under cap", "goal", "150", "business", "burn_this_month"),
    )
    conn.execute(
        "INSERT INTO transactions (date,description,amount,category,account,hash,source) "
        "VALUES ('2026-07-01','test',-50,'ai','chase','abc123','csv')",
    )
    # SPEC-v30 Phase 3: burn_by_month now sums against the active
    # budget_categories row instead of the hardcoded BUSINESS_CATEGORIES
    # set. The migration already seeds this exact row (name UNIQUE), so
    # this is belt-and-suspenders explicitness, not a second source of
    # truth: INSERT OR IGNORE is a no-op against the seeded row and only
    # matters if a future migration ever stops seeding it.
    conn.execute(
        "INSERT OR IGNORE INTO budget_categories (name, cap, categories) VALUES (?,?,?)",
        ("Business burn", 150,
         json.dumps(["ai", "telecom", "hosting", "saas", "domain", "marketing", "fees", "legal"])),
    )
    conn.commit()
    goals = metrics.resolve_goal_actuals(conn)
    burn = next(g for g in goals if "burn" in g["name"].lower())
    assert burn["status"] in ("ON TRACK", "AT RISK", "OFF TRACK", "NO DATA")
    assert burn["actual"] is not None


def test_portfolio_snapshot_empty(conn):
    assert db.portfolio_snapshot(conn) is None


def test_tradeoff_hints_no_crash(conn):
    hints = metrics.compute_tradeoff_hints(conn)
    assert isinstance(hints, list)


# ------------------------------------------------------- SPEC-v37 8.4: money


def _insert_account(conn, source, external_id, acct_type, balance, **extra):
    fields = {
        "source": source, "external_id": external_id, "type": acct_type,
        "current_balance": balance, "institution": extra.pop("institution", "Test"),
        "name": extra.pop("name", "Account"), "subtype": extra.pop("subtype", ""),
        **extra,
    }
    cols = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    conn.execute(
        f"INSERT INTO financial_accounts ({cols}) VALUES ({placeholders})",
        tuple(fields.values()),
    )
    conn.commit()


def test_net_worth_subtracts_credit_and_loan_balances(conn):
    """Plaid's own sign convention: a credit/loan current_balance is a
    positive amount OWED, never negative. Summing every balance the way the
    pre-fix code effectively did would count debt as an asset."""
    _insert_account(conn, "plaid_chase", "checking1", "depository", 529.0)
    _insert_account(conn, "plaid_capital_one", "savings1", "depository", 375.82)
    _insert_account(conn, "plaid_chase", "credit1", "credit", 38.59)
    _insert_account(conn, "snaptrade", "brokerage1", "investment", 1080.10)
    worth = db.net_worth(conn)
    assert worth == round(529.0 + 375.82 - 38.59 + 1080.10, 2)


def test_net_worth_is_none_with_no_accounts_but_zero_when_balances_are_zero(conn):
    assert db.net_worth(conn) is None
    _insert_account(conn, "plaid_chase", "checking1", "depository", 0.0)
    assert db.net_worth(conn) == 0.0


def test_cash_position_is_a_rolling_30_day_window_over_linked_accounts_only(conn):
    """The old query summed every transaction since the first CSV import
    ever, seeded demo rows included -- "~$81 months of runway" on $670.04 /
    $105 was SUM(amount) since forever, not a real number. account_key is
    only populated by a real sync; the legacy/seed rows never got one."""
    today = date.today()
    old = (today - timedelta(days=40)).isoformat()
    recent = (today - timedelta(days=5)).isoformat()
    conn.execute(
        "INSERT INTO transactions (date,description,amount,category,account,hash,source,account_key) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (recent, "recent linked", -100.0, "", "chase", "h1", "plaid", "plaid_chase:checking1"),
    )
    conn.execute(
        "INSERT INTO transactions (date,description,amount,category,account,hash,source,account_key) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (old, "old linked, outside window", -9999.0, "", "chase", "h2", "plaid", "plaid_chase:checking1"),
    )
    conn.execute(
        "INSERT INTO transactions (date,description,amount,category,account,hash,source,account_key) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (recent, "recent but unlinked seed row", -7420.0, "", "seed", "h3", "csv", ""),
    )
    conn.commit()
    position = db.cash_position(conn)
    assert position["net_flow_30d"] == -100.0


def test_checking_balance_carries_its_own_source(conn):
    _insert_account(conn, "plaid_capital_one", "checking1", "depository", 100.0,
                     subtype="checking", as_of="2026-09-01")
    result = db.checking_balance(conn)
    assert result["source"] == "plaid_capital_one"
