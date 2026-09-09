"""The state endpoint compiles one compact attention view from reused reads."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_state_compiles_attention_once_from_reused_reads(client, monkeypatch):
    calls = {"queue": 0, "compile": 0, "project": 0}
    captured = {}
    result = object()
    projection = {
        "next": {
            "key": "proposal:7",
            "kind": "proposal",
            "label": "Decide proposal #7",
            "reason": "waiting 2 days",
            "route": "inbox",
            "interaction": {"type": "proposal_decision", "ref_id": 7},
            "due_at": None,
            "urgency": "due",
        },
        "items": [],
    }

    def fake_queue(_conn, today=None, limit=None):
        calls["queue"] += 1
        assert today
        assert limit is None
        return []

    def fake_compile(_conn, now, *, preloaded=None):
        calls["compile"] += 1
        captured["now"] = now
        captured["preloaded"] = preloaded
        return result

    def fake_projection(got, limit=4):
        calls["project"] += 1
        assert got is result
        assert limit == 4
        return projection

    monkeypatch.setattr(main.leads_mod, "call_queue", fake_queue)
    monkeypatch.setattr(main.attention, "compile_attention", fake_compile)
    monkeypatch.setattr(main.attention, "public_projection", fake_projection)

    response = client.get("/api/state")
    assert response.status_code == 200
    body = response.json()
    assert body["attention"] == projection
    assert calls == {"queue": 1, "compile": 1, "project": 1}

    preloaded = captured["preloaded"]
    assert set(preloaded) == {
        "goals", "gym", "partner_tasks", "tasks", "lead_queue", "due_callbacks",
        "plan_blocks", "pending_proposals", "stale_domains",
        "active_promises", "activity", "school_items", "school_meetings",
    }
    assert preloaded["goals"] == body["goals"]
    assert preloaded["gym"] == body["gym"]
    assert preloaded["partner_tasks"] == body["partner_tasks"]
    assert preloaded["tasks"] == body["tasks_today"]
    assert preloaded["lead_queue"] == []
    assert preloaded["pending_proposals"] == body["pending_proposals"]
    assert preloaded["stale_domains"] == body["stale_domains"]
    assert preloaded["activity"] == body["activity_today"]
    # SPEC-v32 B: the school snapshot is computed once and reused for both
    # the compiler's preload and the response's own "school" key.
    assert preloaded["school_items"] == body["school"]["upcoming"]
    assert preloaded["school_meetings"] == body["school"]["next_meetings"]


def test_state_attention_projection_is_compact_and_private(client):
    conn = db.connect()
    for number in range(6):
        db.add_proposal(
            conn,
            "chief",
            f"Proposal {number} private@example.com",
            "private reasoning must stay internal",
            "task",
        )
    conn.close()

    attention = client.get("/api/state").json()["attention"]
    records = ([attention["next"]] if attention["next"] else []) + attention["items"]

    assert len(records) <= 4
    for item in records:
        assert set(item) == {
            "key", "kind", "label", "reason", "route", "interaction",
            "due_at", "urgency",
        }
        assert "evidence" not in item
        assert "audiences" not in item
        assert "push_policy" not in item
        assert "private reasoning" not in str(item)
