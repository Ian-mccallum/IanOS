"""Private draft detail and deliberately lossy proposal state projections."""

import json
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


def _proposal(*, reversibility="hard_to_reverse", attachment=True) -> int:
    conn = db.connect()
    goal_id = conn.execute(
        "INSERT INTO goals (name, kind, target, domain) VALUES (?, 'deadline', ?, 'business')",
        ("UIUC form deadline", "filed"),
    ).lastrowid
    conn.commit()
    draft = ({
        "version": 1,
        "type": "email_draft",
        "to_label": "Partner",
        "subject": "A private subject",
        "body": "DRAFT-BODY-PRIVATE-7781",
    } if attachment else None)
    proposal_id = db.add_proposal(
        conn,
        "chief",
        "Review the filing plan",
        "The deadline needs a decision.",
        "task",
        attachment=draft,
        metadata={
            "urgency": "time_sensitive",
            "due_at": "2030-08-20T14:00:00",
            "reversibility": reversibility,
            "evidence": [{"source": f"goal:{goal_id}"}],
        },
        allowed_read_tools={"read_goals"},
        role_domains=["business"],
    )
    conn.close()
    return proposal_id


def test_state_hides_draft_content_and_detail_is_no_store(client):
    proposal_id = _proposal()

    state_response = client.get("/api/state")
    assert state_response.status_code == 200
    assert "DRAFT-BODY-PRIVATE-7781" not in state_response.text
    assert "attachment_json" not in state_response.text
    assert "evidence_json" not in state_response.text
    summary = next(
        item for item in state_response.json()["pending_proposals"]
        if item["id"] == proposal_id
    )
    assert summary["has_attachment"] is True
    assert summary["attachment_type"] == "email_draft"
    assert summary["urgency"] == "time_sensitive"
    assert summary["due_at"] == "2030-08-20T14:00:00"
    assert summary["reversibility"] == "hard_to_reverse"
    assert summary["evidence"] == ["UIUC form deadline"]
    assert "attachment" not in summary

    detail_response = client.get(f"/api/proposals/{proposal_id}")
    assert detail_response.status_code == 200
    assert detail_response.headers["cache-control"] == "no-store"
    detail = detail_response.json()
    assert detail["attachment"] == {
        "version": 1,
        "type": "email_draft",
        "to_label": "Partner",
        "subject": "A private subject",
        "body": "DRAFT-BODY-PRIVATE-7781",
    }
    assert detail["evidence"] == ["UIUC form deadline"]
    assert "attachment_json" not in detail
    assert "evidence_json" not in detail


def test_decision_requires_hard_confirmation_and_projects_response(client):
    proposal_id = _proposal()
    blocked = client.post(f"/api/proposals/{proposal_id}/decide", json={
        "decision": "approve", "note": "",
    })
    assert blocked.status_code == 409
    conn = db.connect()
    assert db.get_proposal(conn, proposal_id)["status"] == "PENDING"
    conn.close()

    approved = client.post(f"/api/proposals/{proposal_id}/decide", json={
        "decision": "approve",
        "note": "confirmed in the explicit second step",
        "confirmed_hard_to_reverse": True,
    })
    assert approved.status_code == 200
    assert approved.headers["cache-control"] == "no-store"
    body = approved.json()
    assert body["status"] == "APPROVED"
    assert body["attachment"]["body"] == "DRAFT-BODY-PRIVATE-7781"
    assert "attachment_json" not in body
    assert "evidence_json" not in body

    state = client.get("/api/state")
    assert "DRAFT-BODY-PRIVATE-7781" not in state.text
    recent = next(
        item for item in state.json()["recent_decisions"]
        if item["id"] == proposal_id
    )
    assert recent["has_attachment"] is True
    assert "attachment" not in recent


def test_hard_proposal_rejection_needs_no_confirmation(client):
    proposal_id = _proposal(attachment=False)
    response = client.post(f"/api/proposals/{proposal_id}/decide", json={
        "decision": "reject", "note": "not now",
    })
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_corrupt_raw_attachment_never_crosses_detail_or_state(client):
    conn = db.connect()
    cur = conn.execute(
        """INSERT INTO proposals
           (role, action, reasoning, kind, attachment_type, attachment_json)
           VALUES ('chief', 'Review', 'Reason', 'task', 'email_draft', ?)""",
        (json.dumps({"type": "email_draft", "secret": "CORRUPT-PRIVATE-9012"}),),
    )
    conn.commit()
    proposal_id = cur.lastrowid
    conn.close()

    detail = client.get(f"/api/proposals/{proposal_id}")
    assert detail.status_code == 200
    assert detail.json()["attachment"] is None
    assert detail.json()["has_attachment"] is False
    assert "CORRUPT-PRIVATE-9012" not in detail.text
    assert "CORRUPT-PRIVATE-9012" not in client.get("/api/state").text


def test_proposal_detail_404_and_decision_extras_rejected(client):
    assert client.get("/api/proposals/999999").status_code == 404
    proposal_id = _proposal(attachment=False)
    assert client.post(f"/api/proposals/{proposal_id}/decide", json={
        "decision": "reject", "note": "", "send": True,
    }).status_code == 422
