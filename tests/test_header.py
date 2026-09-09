"""SPEC-v41 §2.4: the /api/state 'header' projection (day arc + agent pulse)
is entirely code-computed, so the phone and the desktop can never disagree
about what's next.
"""

import pytest
from fastapi.testclient import TestClient

from api import main
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_header_projection_is_code_computed(client, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "BACKUP_LAST_SUCCESS_PATH", tmp_path / "missing")
    # This machine's real .env configures restic (SPEC-v16); isolate from it
    # so this test exercises the "unconfigured" branch regardless of host.
    monkeypatch.delenv("RESTIC_REPOSITORY", raising=False)
    monkeypatch.delenv("RESTIC_PASSWORD", raising=False)
    conn = db.connect()
    today = db.today()
    conn.execute(
        "INSERT INTO plan_blocks (date, start_time, end_time, title, status) "
        "VALUES (?,?,?,?,?)",
        (today, "09:00", "10:00", "Deep work", "done"),
    )
    conn.execute(
        "INSERT INTO plan_blocks (date, start_time, end_time, title, status) "
        "VALUES (?,?,?,?,?)",
        (today, "23:50", "23:59", "Late block", "planned"),
    )
    conn.commit()
    conn.close()

    resp = client.get("/api/state")
    header = resp.json()["header"]

    assert header["pulse"]["backup_at"] is None
    assert header["pulse"]["backup_configured"] is False
    assert header["arc"]["next"]["label"] == "Late block"
    assert header["arc"]["next"]["at"] == "23:50"
