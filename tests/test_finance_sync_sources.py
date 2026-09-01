"""SPEC-v20 Phase D: source hardening and independent finance orchestration."""

from __future__ import annotations

import sqlite3
import urllib.error
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from core import db
from ingest import sync_chase, sync_fidelity, sync_finance, sync_plaid


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _simplefin_payload():
    return {
        "accounts": [{
            "name": "checking",
            "balance": "42.00",
            "transactions": [{
                "id": "txn-1", "posted": 1_700_000_000,
                "amount": "-12.50", "description": "Lunch",
            }],
        }],
    }


def test_simplefin_rejects_payload_with_neither_accounts_nor_balance(monkeypatch, conn):
    monkeypatch.setattr(sync_chase, "fetch_accounts", lambda *args, **kwargs: {"errors": []})
    with pytest.raises(sync_chase.SimpleFINProtocolError):
        sync_chase.sync(conn, "https://example.test/access")
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    monkeypatch.setattr(sync_chase, "fetch_accounts", lambda *args, **kwargs: {"balance": "9.50"})
    assert sync_chase.sync(conn, "https://example.test/access") == {
        "inserted": 0, "balance": 9.5,
    }


def test_simplefin_ignores_only_unique_constraint_duplicates(monkeypatch, conn):
    monkeypatch.setattr(sync_chase, "fetch_accounts", lambda *args, **kwargs: _simplefin_payload())
    first = sync_chase.sync(conn, "https://example.test/access")
    assert first == {"inserted": 1, "balance": 42.0}
    assert sync_chase.sync(conn, "https://example.test/access")["inserted"] == 0

    conn.execute(
        """CREATE TRIGGER reject_simplefin BEFORE INSERT ON transactions
           BEGIN SELECT RAISE(ABORT, 'forced integrity failure'); END"""
    )
    changed = _simplefin_payload()
    changed["accounts"][0]["transactions"][0]["id"] = "txn-2"
    monkeypatch.setattr(sync_chase, "fetch_accounts", lambda *args, **kwargs: changed)
    with pytest.raises(sqlite3.IntegrityError, match="forced integrity failure"):
        sync_chase.sync(conn, "https://example.test/access")


def test_finance_sources_reject_nonfinite_money(monkeypatch, conn):
    payload = _simplefin_payload()
    payload["accounts"][0]["transactions"][0]["amount"] = "NaN"
    monkeypatch.setattr(sync_chase, "fetch_accounts", lambda *args, **kwargs: payload)
    with pytest.raises(sync_chase.SimpleFINProtocolError, match="amount"):
        sync_chase.sync(conn, "https://example.test/access")


def _snap_responses(accounts, positions):
    def request(path, **kwargs):
        if path == "/api/v1/accounts":
            return accounts
        account_id = path.split("/")[4]
        result = positions[account_id]
        if isinstance(result, Exception):
            raise result
        return {"results": result, "data_freshness": {"as_of": "2026-08-17T12:00:00Z"}}
    return request


def _snap_env(monkeypatch):
    for key in sync_fidelity.REQUIRED_ENV_KEYS:
        monkeypatch.setenv(key, "configured")


def test_snaptrade_stages_every_account_before_replacement(monkeypatch, conn):
    _snap_env(monkeypatch)
    client = _snap_responses(
        [{"id": "a", "name": "one"}, {"id": "b", "name": "two"}],
        {
            "a": [{"instrument": {"symbol": "AAA"}, "units": 1, "price": 10}],
            "b": RuntimeError("provider secret response"),
        },
    )
    monkeypatch.setattr(sync_fidelity, "_request_json", client)
    replaced = []
    monkeypatch.setattr(db, "replace_holdings_snapshot", lambda *args, **kwargs: replaced.append(args) or 0)

    with pytest.raises(sync_fidelity.SnapTradeProtocolError):
        sync_fidelity.sync_holdings(conn)
    assert replaced == []


def test_snaptrade_empty_snapshot_requires_deliberate_override(monkeypatch, conn):
    _snap_env(monkeypatch)
    monkeypatch.setattr(sync_fidelity, "_request_json", _snap_responses([], {}))
    monkeypatch.setattr(db, "latest_holdings", lambda *args: [{"symbol": "OLD"}])
    published = []
    monkeypatch.setattr(
        db, "replace_holdings_snapshot",
        lambda connection, day, rows, source, commit=True: published.append((rows, commit)) or len(rows),
    )

    with pytest.raises(sync_fidelity.SnapTradeProtocolError, match="empty portfolio"):
        sync_fidelity.sync_holdings(conn)
    assert published == []

    result = sync_fidelity.sync_holdings(conn, allow_empty=True, commit=False)
    assert result == {"positions": 0, "total": 0}
    assert published == []
    db.record_ingest_success(conn, sync_fidelity.SOURCE, result["positions"])
    assert db.ingest_status(conn, sync_fidelity.SOURCE)["row_count"] == 0
    # Once Ian deliberately established empty as current truth, routine
    # scheduled refreshes may confirm that same empty state without a flag.
    assert sync_fidelity.sync_holdings(conn, commit=False)["positions"] == 0


def test_orchestrator_runs_fidelity_after_simplefin_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "orchestrator.db")
    monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", "https://configured.invalid/access")
    _snap_env(monkeypatch)
    # This test asserts the orchestrator's exact report list for SimpleFIN +
    # SnapTrade only. Plaid is a third, independently-configured source
    # (SPEC-v24); strip any real Plaid credentials a developer's .env may
    # hold so this test never makes live Plaid calls and stays isolated from
    # local machine state.
    for key in (*sync_plaid.plaid.APP_ENV_KEYS,
                *(sync_plaid.plaid.token_env_key(item) for item in sync_plaid.plaid.ITEM_KEYS)):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        sync_chase, "sync",
        lambda connection, *args, **kwargs: chase_connections.append(connection) or
        (_ for _ in ()).throw(urllib.error.URLError("private endpoint")),
    )
    chase_connections = []
    fidelity_calls = []
    fidelity_connections = []
    monkeypatch.setattr(
        sync_fidelity, "sync_holdings",
        lambda connection, *args, **kwargs: fidelity_connections.append(connection) or
        fidelity_calls.append(kwargs) or {"positions": 2, "total": 100},
    )
    monkeypatch.setattr(sync_finance.push, "configured", lambda: None)

    reports = sync_finance.run()
    assert reports == [
        {"source": "SimpleFIN", "status": "failed", "error": "network"},
        {"source": "SnapTrade", "status": "ok", "rows": 2},
    ]
    assert fidelity_calls == [{"commit": False}]
    assert chase_connections[0] is not fidelity_connections[0]
    connection = db.connect()
    try:
        assert db.ingest_status(connection, sync_chase.SOURCE)["last_error"] == "network"
        assert db.ingest_status(connection, sync_fidelity.SOURCE)["row_count"] == 2
    finally:
        connection.close()


def test_configuration_check_names_keys_never_values(monkeypatch):
    for key in sync_chase.REQUIRED_ENV_KEYS + sync_fidelity.REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "extremely-secret-value")
    errors = sync_finance.configuration_errors()
    rendered = " ".join(errors)
    assert "SNAPTRADE_CONSUMER_KEY" in rendered
    assert "extremely-secret-value" not in rendered


def test_snaptrade_personal_configuration_needs_only_app_keys(monkeypatch):
    for key in sync_fidelity.REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "personal-client")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "personal-secret")

    assert sync_fidelity.configured() is True
    assert sync_fidelity.missing_config_keys() == []


def test_snaptrade_rejects_half_configured_commercial_identity(monkeypatch):
    for key in sync_fidelity.REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "client")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "key")
    monkeypatch.setenv("SNAPTRADE_USER_ID", "user")

    assert sync_fidelity.configured() is False
    assert sync_fidelity.missing_config_keys() == ["SNAPTRADE_USER_SECRET"]


def test_snaptrade_personal_request_omits_commercial_credentials(monkeypatch):
    for key in sync_fidelity.REQUIRED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SNAPTRADE_CLIENT_ID", "personal-client")
    monkeypatch.setenv("SNAPTRADE_CONSUMER_KEY", "personal-secret")
    monkeypatch.setattr(sync_fidelity.time, "time", lambda: 1_700_000_000)
    monkeypatch.setattr(sync_fidelity, "ssl_context", lambda: "tls-context")
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b"[]"

    def fake_urlopen(request, *, context, timeout):
        captured.update(request=request, context=context, timeout=timeout)
        return Response()

    monkeypatch.setattr(sync_fidelity, "urlopen", fake_urlopen)

    assert sync_fidelity._request_json("/api/v1/accounts") == []
    query = parse_qs(urlsplit(captured["request"].full_url).query)
    assert query == {"clientId": ["personal-client"], "timestamp": ["1700000000"]}
    assert captured["request"].get_header("Signature")
    assert captured["context"] == "tls-context"
    assert captured["timeout"] == 30


def test_snaptrade_unified_positions_are_normalized(monkeypatch, conn):
    _snap_env(monkeypatch)
    monkeypatch.setattr(
        sync_fidelity,
        "_request_json",
        _snap_responses(
            [{"id": "acct-1", "name": "Roth"}],
            {"acct-1": [{
                "instrument": {"kind": "etf", "symbol": "ETF", "description": "Index ETF"},
                "units": "2.5",
                "price": "100",
                "cost_basis": "80",
            }]},
        ),
    )

    result = sync_fidelity.sync_holdings(conn)

    assert result == {"positions": 1, "total": 250.0}
    row = db.latest_holdings(conn, "snaptrade")[0]
    assert row["account"] == "Roth"
    assert row["symbol"] == "ETF"
    assert row["quantity"] == 2.5
    assert row["market_value"] == 250.0
    assert row["cost_basis"] == 200.0


def test_snaptrade_holdings_carry_account_key(monkeypatch, conn):
    _snap_env(monkeypatch)
    monkeypatch.setattr(
        sync_fidelity,
        "_request_json",
        _snap_responses(
            [{"id": "acct-1", "name": "Roth"}],
            {"acct-1": [{"instrument": {"symbol": "ETF"}, "units": 2, "price": 100}]},
        ),
    )

    sync_fidelity.sync_holdings(conn)

    row = db.latest_holdings(conn, "snaptrade")[0]
    assert row["account_key"] == "snaptrade:acct-1"


def test_snaptrade_registers_financial_accounts_from_position_totals(monkeypatch, conn):
    _snap_env(monkeypatch)
    monkeypatch.setattr(
        sync_fidelity,
        "_request_json",
        _snap_responses(
            [{"id": "acct-1", "name": "Roth IRA"}, {"id": "acct-2", "name": "Individual"}],
            {
                "acct-1": [{"instrument": {"symbol": "ETF"}, "units": 2, "price": 100}],
                "acct-2": [{"instrument": {"symbol": "AAPL"}, "units": 1, "price": 50}],
            },
        ),
    )

    sync_fidelity.sync_holdings(conn)

    accounts = {a["external_id"]: a for a in db.financial_accounts(conn, source_prefix="snaptrade")}
    assert set(accounts) == {"acct-1", "acct-2"}
    assert accounts["acct-1"]["type"] == "investment"
    assert accounts["acct-1"]["subtype"] == "roth"
    assert accounts["acct-1"]["current_balance"] == 200.0
    assert accounts["acct-2"]["subtype"] == "brokerage"
    assert accounts["acct-2"]["current_balance"] == 50.0


def test_snaptrade_resync_keeps_one_balance_snapshot_per_account_per_day(monkeypatch, conn):
    _snap_env(monkeypatch)
    monkeypatch.setattr(
        sync_fidelity,
        "_request_json",
        _snap_responses(
            [{"id": "acct-1", "name": "Individual"}],
            {"acct-1": [{"instrument": {"symbol": "AAPL"}, "units": 1, "price": 50}]},
        ),
    )

    sync_fidelity.sync_holdings(conn)
    sync_fidelity.sync_holdings(conn)

    rows = db.account_snapshots(conn, "snaptrade", "acct-1")
    assert len(rows) == 1
    assert rows[0]["current"] == 50.0


def test_stale_alert_is_one_generic_aggregate_without_financial_data(monkeypatch, conn):
    now = datetime(2026, 8, 16, 12, 0, 0)
    old = (now - timedelta(hours=49)).isoformat(sep=" ")
    db.record_ingest_success(conn, sync_chase.SOURCE, 1, '{"balance": 987654}')
    conn.execute(
        "UPDATE ingest_log SET last_import=?, last_success=?, last_error=? WHERE source=?",
        (old, old, "auth", sync_chase.SOURCE),
    )
    conn.commit()
    sent = []
    monkeypatch.setattr(sync_finance.push, "configured", lambda: "test")
    monkeypatch.setattr(
        sync_finance.push, "send",
        lambda title, message: sent.append((title, message)) or True,
    )

    configured = {sync_chase.SOURCE: True, sync_fidelity.SOURCE: False}
    assert sync_finance._stale_alert(conn, configured, now) == [sync_chase.SOURCE]
    assert sync_finance._stale_alert(conn, configured, now) == []
    assert len(sent) == 1
    rendered = " ".join(sent[0])
    assert "SimpleFIN" in rendered
    assert "987654" not in rendered
    assert "auth" not in rendered


@pytest.mark.parametrize("module", [sync_chase, sync_fidelity])
def test_direct_source_cli_records_unexpected_failure_without_raw_error(
    module, monkeypatch, capsys,
):
    class Connection:
        def rollback(self):
            pass

        def close(self):
            pass

    connection = Connection()
    monkeypatch.setattr(db, "connect", lambda: connection)
    monkeypatch.setattr(db, "record_ingest_attempt", lambda *args: None)
    failures = []
    monkeypatch.setattr(db, "record_ingest_failure", lambda conn, source, code: failures.append(code))
    monkeypatch.setattr(module, "configured", lambda: True)
    monkeypatch.setattr(module.sys, "argv", [module.__file__])

    if module is sync_chase:
        monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", "https://configured.invalid/access")
        monkeypatch.setattr(module, "sync", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("raw secret")))
    else:
        monkeypatch.setattr(module, "sync_holdings", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("raw secret")))

    with pytest.raises(SystemExit) as exited:
        module.main()
    assert exited.value.code == 1
    assert failures == ["protocol"]
    assert "raw secret" not in capsys.readouterr().out
