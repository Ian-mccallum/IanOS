"""SPEC-v32 Part C: the live Canvas feed sync never leaks its bearer secret.

Every test mocks this module's own fetch function, never urllib globally, and
never makes a real network call.
"""

from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import app
from core import db, school
from ingest import sync_canvas
from ingest.canvas_ics import CanvasICSParseError

FAKE_URL = "https://canvas.example.edu/feeds/SECRETTOKEN123.ics"

_VALID_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:stat107-hw1@canvas.instructure.com
DTSTART;VALUE=DATE:20260901
DTEND;VALUE=DATE:20260902
SUMMARY:STAT 120: Homework 1 due
END:VEVENT
END:VCALENDAR
""".encode("utf-8")


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, n=-1):
        return self._data if n is None or n < 0 else self._data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_unconfigured_raises_runtime_error(conn, monkeypatch):
    monkeypatch.delenv("CANVAS_ICS_URL", raising=False)
    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)


def test_check_configured_exits_1_when_absent(monkeypatch, capsys):
    monkeypatch.delenv("CANVAS_ICS_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["sync_canvas.py", "--check-configured"])
    with pytest.raises(SystemExit) as exc_info:
        sync_canvas.main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "CANVAS_ICS_URL" in out


def test_fetch_caps_bytes_before_any_disk_write(monkeypatch):
    """The byte cap trips on the raw fetch itself, before anything is written."""
    oversized = b"x" * (sync_canvas.MAX_FETCH_BYTES + 10)
    monkeypatch.setattr(
        sync_canvas.urllib.request, "urlopen",
        lambda *a, **k: _FakeResponse(oversized),
    )
    with pytest.raises(sync_canvas.CanvasSyncTooLargeError):
        sync_canvas.fetch_ics_bytes(FAKE_URL)


def test_successful_sync_records_success_and_items(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)
    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", lambda url: _VALID_ICS)

    report = sync_canvas.sync(conn)

    assert report["imported"] >= 1
    state = school.sync_state(conn)
    assert state["last_success"] is not None
    assert state["item_count"] > 0
    assert state["last_error"] == ""

    log = db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)
    assert log is not None
    assert log["last_success"] is not None
    assert log["row_count"] == report["imported"]
    assert log["last_error"] == ""
    assert log["consecutive_failures"] == 0


def test_byte_cap_exceeded_records_too_large_and_never_partially_writes(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)

    def _raise(url):
        raise sync_canvas.CanvasSyncTooLargeError("too big")

    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", _raise)

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    state = school.sync_state(conn)
    assert state["last_error"] == "too_large"
    assert state["last_success"] is None
    count = conn.execute("SELECT COUNT(*) FROM school_items").fetchone()[0]
    assert count == 0
    assert db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)["last_error"] == "protocol"


def test_http_404_records_http_4xx(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)

    def _raise(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", _raise)

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    assert school.sync_state(conn)["last_error"] == "http_4xx"
    assert db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)["last_error"] == "protocol"


def test_http_500_records_http_5xx(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)

    def _raise(url):
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", _raise)

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    assert school.sync_state(conn)["last_error"] == "http_5xx"
    assert db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)["last_error"] == "provider_5xx"


def test_network_error_records_network(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)

    def _raise(url):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", _raise)

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    assert school.sync_state(conn)["last_error"] == "network"
    assert db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)["last_error"] == "network"


def test_malformed_ics_bytes_record_parse(conn, monkeypatch):
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)
    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", lambda url: b"this is not a calendar file")

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    assert school.sync_state(conn)["last_error"] == "parse"
    assert db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)["last_error"] == "protocol"


def test_classify_maps_parse_error_directly():
    assert sync_canvas._classify(CanvasICSParseError("bad")) == "parse"
    assert sync_canvas._classify(sync_canvas.CanvasSyncTooLargeError("big")) == "too_large"


def test_ingest_log_code_uses_db_vocabulary():
    """core.db.record_ingest_failure only accepts network/auth/provider_5xx/protocol."""
    assert sync_canvas._ingest_log_code(
        urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    ) == "auth"
    assert sync_canvas._ingest_log_code(
        urllib.error.HTTPError("u", 404, "Not Found", {}, None)
    ) == "protocol"
    assert sync_canvas._ingest_log_code(
        urllib.error.HTTPError("u", 502, "Bad Gateway", {}, None)
    ) == "provider_5xx"
    assert sync_canvas._ingest_log_code(urllib.error.URLError("no route")) == "network"
    assert sync_canvas._ingest_log_code(CanvasICSParseError("bad")) == "protocol"
    for code in (
        sync_canvas._ingest_log_code(urllib.error.HTTPError("u", 401, "x", {}, None)),
        sync_canvas._ingest_log_code(urllib.error.HTTPError("u", 404, "x", {}, None)),
        sync_canvas._ingest_log_code(urllib.error.HTTPError("u", 502, "x", {}, None)),
        sync_canvas._ingest_log_code(urllib.error.URLError("x")),
        sync_canvas._ingest_log_code(CanvasICSParseError("x")),
    ):
        assert code in db._SAFE_INGEST_ERRORS


def test_sentinel_feed_url_never_leaks(conn, monkeypatch):
    """Law 6: the feed URL must never appear in any agent- or API-visible surface."""
    monkeypatch.setenv("CANVAS_ICS_URL", FAKE_URL)

    def _raise(url):
        raise urllib.error.URLError("simulated failure, no real network call")

    monkeypatch.setattr(sync_canvas, "fetch_ics_bytes", _raise)

    with pytest.raises(RuntimeError):
        sync_canvas.sync(conn)

    secret = "SECRETTOKEN123"

    sync_row = conn.execute(
        "SELECT * FROM school_sync_state WHERE provider=?", (school.CANVAS_PROVIDER,)
    ).fetchone()
    assert sync_row is not None
    assert secret not in json.dumps(dict(sync_row))

    ingest_row = db.ingest_status(conn, sync_canvas.INGEST_LOG_SOURCE)
    assert ingest_row is not None
    assert secret not in json.dumps(ingest_row)

    memo_rows = conn.execute("SELECT * FROM memos").fetchall()
    for row in memo_rows:
        assert secret not in json.dumps(dict(row))

    state_json = TestClient(app).get("/api/state").json()
    assert secret not in json.dumps(state_json)
    assert FAKE_URL not in json.dumps(state_json)
