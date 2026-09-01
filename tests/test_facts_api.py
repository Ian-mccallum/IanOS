"""Tests for facts API create."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import app
from core import db

client = TestClient(app)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def test_create_fact(conn):
    r = client.post("/api/facts", json={
        "domain": "personal",
        "topic": "ian:test-note",
        "body": "Remember to call mom",
        "kind": "fact",
        "verified": True,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["topic"] == "ian:test-note"
    assert data["body"] == "Remember to call mom"


def test_create_and_replace_fact_sources(conn):
    first_id = db.add_memo(conn, "ian", "memory", "The first source")
    second_id = db.add_memo(conn, "ian", "memory", "The second source")

    created = client.post("/api/facts", json={
        "domain": "personal",
        "topic": "ian:sourced-note",
        "body": "A sourced memory",
        "source_memo_ids": [first_id],
    })
    assert created.status_code == 200
    fact = created.json()
    assert fact["source_memo_ids"] == str(first_id)

    patched = client.patch(f"/api/facts/{fact['id']}", json={
        "source_memo_ids": [second_id],
    })
    assert patched.status_code == 200
    assert patched.json()["source_memo_ids"] == str(second_id)

    sources = client.get(f"/api/facts/{fact['id']}/sources")
    assert sources.status_code == 200
    assert sources.json() == {
        "fact_id": fact["id"],
        "sources": [{
            "id": second_id,
            "from_role": "ian",
            "topic": "memory",
            "body": "The second source",
            "created_at": sources.json()["sources"][0]["created_at"],
            "archived": False,
        }],
    }


def test_fact_sources_reject_missing_memo_and_unknown_fact(conn):
    rejected = client.post("/api/facts", json={
        "domain": "personal",
        "topic": "ian:bad-source",
        "body": "Should not persist",
        "source_memo_ids": [999999],
    })
    assert rejected.status_code == 400
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0

    missing = client.get("/api/facts/999999/sources")
    assert missing.status_code == 404
