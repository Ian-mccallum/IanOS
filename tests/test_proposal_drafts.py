"""SPEC-v23 inert proposal drafts and verified decision metadata."""

import asyncio
import json
import sqlite3

import pytest

from agents import runner
from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def _seed_evidence(conn):
    goal_id = conn.execute(
        "INSERT INTO goals (name, target, domain) VALUES ('File UIUC form', 'done', 'school')"
    ).lastrowid
    fact_id = db.upsert_fact(
        conn, "college", "uiuc:form-deadline", "Due soon", verified=1,
    )
    personal_fact_id = db.upsert_fact(
        conn, "personal", "partner:flowers", "Peonies", verified=1,
    )
    document_id = conn.execute(
        "INSERT INTO documents (name, kind) VALUES ('Client agreement', 'contract')"
    ).lastrowid
    conn.commit()
    return goal_id, fact_id, personal_fact_id, document_id


ATTACHMENTS = [
    {
        "version": 1,
        "type": "email_draft",
        "to_label": "Partner",
        "subject": "Saturday",
        "body": "Would you like to get dinner Saturday?",
    },
    {
        "version": 1,
        "type": "message_draft",
        "to_label": "Dad",
        "body": "Can we talk after dinner?",
    },
    {
        "version": 1,
        "type": "document_outline",
        "title": "Clockwork launch note",
        "body": "1. Customer problem\n2. Product proof\n3. Next step",
    },
]


def test_legacy_proposals_migrate_with_safe_additive_defaults(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.executescript("""
        CREATE TABLE proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'task' CHECK (kind IN ('money','task')),
            status TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','APPROVED','REJECTED')),
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            decided_at TEXT
        );
        INSERT INTO proposals (role,action,reasoning,kind)
        VALUES ('scout','Call the next lead','Pipeline priority','task');
    """)
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(db, "DB_PATH", path)

    connection = db.connect()
    try:
        proposal = db.pending_proposals(connection)[0]
        assert proposal["attachment"] is None
        assert proposal["attachment_type"] == ""
        assert proposal["urgency"] == "normal"
        assert proposal["due_at"] is None
        assert proposal["reversibility"] == "reversible"
        assert proposal["evidence"] == []
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(proposals)")}
        assert {
            "attachment_type", "attachment_json", "urgency", "due_at",
            "reversibility", "evidence_json",
        } <= columns
    finally:
        connection.close()


@pytest.mark.parametrize("attachment", ATTACHMENTS, ids=lambda value: value["type"])
def test_valid_drafts_round_trip_as_parsed_plain_text(conn, attachment):
    proposal_id = db.add_proposal(
        conn, "steward", f"Review {attachment['type']}", "Draft for approval", "task",
        attachment=attachment,
    )
    proposal = db.get_proposal(conn, proposal_id)
    assert proposal["attachment"] == attachment
    assert proposal["attachment_type"] == attachment["type"]
    assert "attachment_json" not in proposal
    raw = conn.execute(
        "SELECT attachment_json FROM proposals WHERE id=?", (proposal_id,)
    ).fetchone()[0]
    assert raw == json.dumps(
        attachment, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )


@pytest.mark.parametrize("attachment", [
    "not an object",
    {"version": 2, "type": "message_draft", "to_label": "Dad", "body": "Hi"},
    {"version": 1, "type": "unknown", "body": "Hi"},
    {"version": 1, "type": "message_draft", "to_label": "Dad", "body": "Hi", "send": True},
    {"version": 1, "type": "message_draft", "to_label": "dad@example.com", "body": "Hi"},
    {"version": 1, "type": "message_draft", "to_label": "Dad", "body": "<b>Hi</b>"},
    {"version": 1, "type": "message_draft", "to_label": "Dad", "body": "Hi\x00there"},
    {"version": 1, "type": "message_draft", "to_label": "Dad", "body": "x" * 4001},
    {"version": 1, "type": "document_outline", "title": "Missing body"},
])
def test_malformed_unknown_active_and_excess_draft_content_is_rejected(conn, attachment):
    with pytest.raises(ValueError):
        db.add_proposal(
            conn, "steward", "Review a draft", "Draft for approval", "task",
            attachment=attachment,
        )


def test_money_attachment_and_hard_default_cannot_be_bypassed(conn):
    with pytest.raises(ValueError, match="money proposals cannot"):
        db.add_proposal(
            conn, "cfo", "Review a purchase", "Cost evidence", "money",
            attachment={"type": "unknown"},
        )
    with pytest.raises(ValueError, match="must be hard_to_reverse"):
        db.add_proposal(
            conn, "cfo", "Review a purchase", "Cost evidence", "money",
            metadata={"reversibility": "reversible"},
        )
    for kind in ("money", "legal", "health"):
        proposal_id = db.add_proposal(
            conn, "cfo", f"Review {kind}", "Needs a decision", kind,
        )
        assert db.get_proposal(conn, proposal_id)["reversibility"] == "hard_to_reverse"


def _tool_payload(result):
    return json.loads(result["content"][0]["text"])


def test_money_and_trade_guards_run_before_attachment_validation(conn):
    invalid_attachment = {"type": "unknown", "send": True}
    runner.RUN.update(role="lovebird", conn=conn, role_domains=["personal"])
    blocked_money = asyncio.run(runner.create_proposal.handler({
        "action": "Spend $200 on a gift",
        "reasoning": "Anniversary",
        "kind": "money",
        "attachment": invalid_attachment,
    }))
    assert blocked_money["is_error"] is True
    assert "BLOCKED" in blocked_money["content"][0]["text"]
    assert "attachment" not in blocked_money["content"][0]["text"]

    runner.RUN.update(role="wealth", conn=conn, role_domains=["finance"])
    blocked_trade = asyncio.run(runner.create_proposal.handler({
        "action": "Buy 10 shares of VOO",
        "reasoning": "Cheap",
        "kind": "task",
        "attachment": invalid_attachment,
    }))
    assert blocked_trade["is_error"] is True
    assert "BLOCKED" in blocked_trade["content"][0]["text"]
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0


def test_metadata_evidence_permissions_domains_labels_and_verification(conn):
    goal_id, fact_id, personal_fact_id, document_id = _seed_evidence(conn)
    due = "2026-08-20T09:30:00"
    metadata = {
        "urgency": "time_sensitive",
        "due_at": due,
        "evidence": [{"source": f"goal:{goal_id}"}],
    }
    proposal_id = db.add_proposal(
        conn, "advisor", "File the UIUC form", "Deadline is near", "task",
        metadata=metadata,
        allowed_read_tools={"read_goals", "read_facts"},
        role_domains=["college"],
    )
    proposal = db.get_proposal(conn, proposal_id)
    assert proposal["urgency"] == "time_sensitive"
    assert proposal["due_at"] == due
    assert proposal["evidence"] == [{
        "source": f"goal:{goal_id}", "label": "File UIUC form",
    }]
    assert "evidence_json" not in proposal

    with pytest.raises(ValueError, match="labels are server-owned"):
        db.add_proposal(
            conn, "advisor", "Caller label", "Must reject", "task",
            metadata={"evidence": [{"source": f"goal:{goal_id}", "label": "Fake"}]},
            allowed_read_tools={"read_goals"}, role_domains=["college"],
        )
    with pytest.raises(ValueError, match="permission context"):
        db.add_proposal(
            conn, "advisor", "No permission context", "Must reject", "task",
            metadata={"evidence": [{"source": f"goal:{goal_id}"}]},
        )
    with pytest.raises(ValueError, match="cannot cite goal"):
        db.add_proposal(
            conn, "archivist", "Cite a goal", "Not readable", "task",
            metadata={"evidence": [{"source": f"goal:{goal_id}"}]},
            allowed_read_tools={"read_facts", "read_notes"}, role_domains=["all"],
        )
    with pytest.raises(ValueError, match="outside its domains"):
        db.add_proposal(
            conn, "advisor", "Cite personal fact", "Not in domain", "task",
            metadata={"evidence": [{"source": f"fact:{personal_fact_id}"}]},
            allowed_read_tools={"read_facts"}, role_domains=["college"],
        )
    with pytest.raises(ValueError, match="cannot cite document"):
        db.add_proposal(
            conn, "scout", "Cite a document", "Not readable", "task",
            metadata={"evidence": [{"source": f"document:{document_id}"}]},
            allowed_read_tools={"read_goals"}, role_domains=["business"],
        )

    conn.execute("UPDATE facts SET verified=0 WHERE id=?", (fact_id,))
    conn.commit()
    with pytest.raises(ValueError, match="does not exist"):
        db.add_proposal(
            conn, "advisor", "Cite unverified fact", "Not verified", "task",
            metadata={"evidence": [{"source": f"fact:{fact_id}"}]},
            allowed_read_tools={"read_facts"}, role_domains=["college"],
        )


@pytest.mark.parametrize("metadata", [
    {"urgency": "time_sensitive", "due_at": "2026-08-20T09:30:00"},
    {"urgency": "time_sensitive", "evidence": []},
    {"urgency": "urgent"},
    {"due_at": "2026-08-20T09:30:00Z"},
    {"due_at": "2026-08-20T09:30:00.500"},
    {"due_at": "2026-08-20 09:30:00"},
    {"reversibility": "irreversible"},
    {"evidence": [{"source": "memo:1"}]},
    {"extra": True},
])
def test_metadata_grammar_is_closed(conn, metadata):
    with pytest.raises(ValueError):
        db.add_proposal(
            conn, "scout", "Invalid metadata", "Must reject", "task",
            metadata=metadata, allowed_read_tools={"read_goals"}, role_domains=["business"],
        )


def test_pending_dedupe_includes_canonical_attachment_and_metadata(conn):
    goal_id, *_ = _seed_evidence(conn)
    metadata = {"evidence": [{"source": f"goal:{goal_id}"}]}
    first, created = db.add_proposal(
        conn, "scout", "Send follow-up", "Lead asked", "task",
        attachment=ATTACHMENTS[1], metadata=metadata,
        allowed_read_tools={"read_goals"}, role_domains=["business"],
        return_created=True,
    )
    duplicate, duplicate_created = db.add_proposal(
        conn, "scout", "Send follow-up", "Lead asked", "task",
        attachment=dict(ATTACHMENTS[1]), metadata=metadata,
        allowed_read_tools={"read_goals"}, role_domains=["business"],
        return_created=True,
    )
    changed_attachment = dict(ATTACHMENTS[1], body="Different draft")
    changed, changed_created = db.add_proposal(
        conn, "scout", "Send follow-up", "Lead asked", "task",
        attachment=changed_attachment, metadata=metadata,
        allowed_read_tools={"read_goals"}, role_domains=["business"],
        return_created=True,
    )
    assert (duplicate, duplicate_created) == (first, False)
    assert changed_created is True
    assert changed != first


def test_pending_sort_is_time_due_then_hard_then_newest(conn):
    goal_id, *_ = _seed_evidence(conn)
    permissions = {"read_goals"}

    normal_old = db.add_proposal(conn, "scout", "normal old", "r", "task")
    normal_new = db.add_proposal(conn, "scout", "normal new", "r", "task")
    hard_old = db.add_proposal(conn, "counsel", "hard old", "r", "legal")
    hard_new = db.add_proposal(conn, "physician", "hard new", "r", "health")
    late = db.add_proposal(
        conn, "scout", "time late", "r", "task",
        metadata={
            "urgency": "time_sensitive", "due_at": "2026-09-01T12:00:00",
            "evidence": [{"source": f"goal:{goal_id}"}],
        }, allowed_read_tools=permissions, role_domains=["business"],
    )
    early = db.add_proposal(
        conn, "scout", "time early", "r", "task",
        metadata={
            "urgency": "time_sensitive", "due_at": "2026-08-20T12:00:00",
            "evidence": [{"source": f"goal:{goal_id}"}],
        }, allowed_read_tools=permissions, role_domains=["business"],
    )
    assert [proposal["id"] for proposal in db.pending_proposals(conn)] == [
        early, late, hard_new, hard_old, normal_new, normal_old,
    ]


def test_malformed_stored_json_is_never_projected_and_decision_has_no_side_effect(conn):
    proposal_id = db.add_proposal(conn, "scout", "Review draft", "r", "task")
    conn.execute(
        """UPDATE proposals
           SET attachment_type='email_draft', attachment_json='{not-json',
               urgency='time_sensitive', due_at='bad', reversibility='unknown',
               evidence_json='[{"source":"goal:999999","label":"caller"}]'
           WHERE id=?""",
        (proposal_id,),
    )
    conn.commit()
    proposal = db.get_proposal(conn, proposal_id)
    assert proposal["attachment"] is None
    assert proposal["attachment_type"] == ""
    assert proposal["urgency"] == "normal"
    assert proposal["due_at"] is None
    assert proposal["reversibility"] == "reversible"
    assert proposal["evidence"] == []
    assert "attachment_json" not in proposal and "evidence_json" not in proposal

    decided = db.decide_proposal(conn, proposal_id, "approve")
    assert decided["status"] == "APPROVED"
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 1
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(proposals)")}
    assert not ({"send_state", "provider", "address", "webhook"} & columns)
