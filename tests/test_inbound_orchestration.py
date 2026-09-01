"""SPEC-v20 Phase C: every complete inbound seam runs independently."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import sync_btc


INBOUND_ENV = (
    "BTC_SYNC_URL", "BTC_SYNC_TOKEN", "PERSONAL_SYNC_URL", "PERSONAL_SYNC_TOKEN",
)


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def clean_inbound_env(monkeypatch):
    for key in INBOUND_ENV:
        monkeypatch.delenv(key, raising=False)


def _configure(monkeypatch, source: str):
    seam = sync_btc.SEAMS[source]
    monkeypatch.setenv(seam["url_var"], f"https://{source}.example.test/inbox")
    monkeypatch.setenv(seam["token_var"], f"{source}-secret")


def test_sync_all_runs_only_complete_seams_with_separate_connections(monkeypatch):
    _configure(monkeypatch, "btc")
    _configure(monkeypatch, "personal")
    connections = []
    calls = []

    def connect():
        connection = FakeConnection()
        connections.append(connection)
        return connection

    def fake_sync(conn, *, dry_run, source):
        calls.append((conn, dry_run, source))
        return {"loaded": 2, "deduped": 1, "rejected": [], "acked": 3}

    monkeypatch.setattr(sync_btc.db, "connect", connect)
    monkeypatch.setattr(sync_btc, "sync", fake_sync)

    report = sync_btc.sync_all()

    assert [call[2] for call in calls] == ["btc", "personal"]
    assert len({id(call[0]) for call in calls}) == 2
    assert all(connection.closed for connection in connections)
    assert report == {
        "reports": [
            {"source": "btc", "status": "ok",
             "counts": {"loaded": 2, "deduped": 1, "rejected": 0, "acked": 3},
             "error_code": None},
            {"source": "personal", "status": "ok",
             "counts": {"loaded": 2, "deduped": 1, "rejected": 0, "acked": 3},
             "error_code": None},
        ],
        "configured": 2,
        "failed": 0,
    }
    assert sync_btc.all_configured_exit_code(report) == 0


def test_partial_seam_is_a_configuration_failure_but_does_not_block_other(monkeypatch):
    monkeypatch.setenv("BTC_SYNC_URL", "https://btc.example.test/inbox")
    _configure(monkeypatch, "personal")
    calls = []

    monkeypatch.setattr(sync_btc.db, "connect", FakeConnection)
    monkeypatch.setattr(
        sync_btc, "sync",
        lambda conn, *, dry_run, source: calls.append(source) or {
            "loaded": 1, "deduped": 0, "rejected": [], "acked": 1,
        },
    )

    report = sync_btc.sync_all(dry_run=True)

    assert calls == ["personal"]
    btc = report["reports"][0]
    assert btc["status"] == "failed"
    assert btc["error_code"] == "partial_config:BTC_SYNC_URL+BTC_SYNC_TOKEN"
    assert report["reports"][1]["status"] == "ok"
    assert sync_btc.all_configured_exit_code(report) == 1


def test_one_network_failure_still_attempts_the_other_configured_seam(monkeypatch):
    _configure(monkeypatch, "btc")
    _configure(monkeypatch, "personal")
    calls = []

    monkeypatch.setattr(sync_btc.db, "connect", FakeConnection)

    def fake_sync(_conn, *, dry_run, source):
        calls.append(source)
        if source == "btc":
            raise requests.ConnectionError("offline")
        return {"loaded": 1, "deduped": 0, "rejected": [], "acked": 1}

    monkeypatch.setattr(sync_btc, "sync", fake_sync)
    report = sync_btc.sync_all()

    assert calls == ["btc", "personal"]
    assert report["reports"][0]["error_code"] == "network"
    assert report["reports"][1]["status"] == "ok"
    assert sync_btc.all_configured_exit_code(report) == 1


def test_no_complete_seam_is_quietly_unconfigured_and_partial_is_not(monkeypatch):
    none = sync_btc.check_all_configured()
    assert sync_btc.all_configured_exit_code(none) == 2

    monkeypatch.setenv("PERSONAL_SYNC_TOKEN", "token-only")
    partial = sync_btc.check_all_configured()
    assert sync_btc.all_configured_exit_code(partial) == 1
    assert partial["reports"][1]["error_code"] == (
        "partial_config:PERSONAL_SYNC_URL+PERSONAL_SYNC_TOKEN"
    )


def test_cli_rejects_source_and_all_configured_together(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["sync_btc.py", "--source", "btc", "--all-configured"])
    with pytest.raises(SystemExit) as exc:
        sync_btc.main()
    assert exc.value.code == 2
