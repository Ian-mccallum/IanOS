"""Phone capture: /api/quick routing + the LAN auth decision."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from api import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()  # init schema
    return TestClient(main.app)


# ------------------------------------------------------------- auth decision

def test_localhost_always_allowed(monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "")
    assert main._auth_decision(is_local=True, has_valid_token=False) is None
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    assert main._auth_decision(is_local=True, has_valid_token=False) is None


def test_lan_refused_without_token_configured(monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "")
    deny = main._auth_decision(is_local=False, has_valid_token=False)
    assert deny and deny[0] == 403


def test_lan_requires_valid_token(monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    assert main._auth_decision(is_local=False, has_valid_token=False)[0] == 401
    assert main._auth_decision(is_local=False, has_valid_token=True) is None


# ------------------------------------------------------------- /api/quick

def test_quick_gym_confirms_streak(client):
    r = client.post("/api/quick", json={"gym": True})
    assert r.status_code == 200
    body = r.json()
    assert "gym confirmed" in body["did"]
    assert "Streak" in body["message"] and "stool bank" in body["message"]


def test_quick_multi_field_routes_each(client, tmp_path, monkeypatch):
    r = client.post("/api/quick", json={"sleep": 7.5, "energy": 4, "workout": "mma", "steps": 9200})
    assert r.status_code == 200
    conn = db.connect()
    row = conn.execute("SELECT * FROM health_daily WHERE date = ?", (db.today(),)).fetchone()
    assert row["sleep_hours"] == 7.5 and row["energy"] == 4
    assert row["workout"] == "mma" and row["steps"] == 9200
    conn.close()


def test_quick_note_goes_to_activity(client):
    client.post("/api/quick", json={"note": "called Riverbend back"})
    conn = db.connect()
    row = conn.execute("SELECT notes FROM activity WHERE date = ?", (db.today(),)).fetchone()
    assert row and "Riverbend" in row["notes"]
    conn.close()


def test_quick_empty_payload_400(client):
    assert client.post("/api/quick", json={}).status_code == 400


def test_quick_energy_bounds(client):
    assert client.post("/api/quick", json={"energy": 9}).status_code == 422
