"""SPEC-v41 §5.2: the role-less goal-draft parser. A draft never writes, is
zero-tool and single-turn, and never trusts a model-invented metric_key
outside the pillar's own allowed list.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from agents import runner
from api import main
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_goal_draft_never_writes(client, tmp_path, monkeypatch):
    async def fake_reply(text, pillar):
        return (
            '{"name": "Join AKPSI", "shape": "milestone", "target": "", "unit": "", '
            '"per": "", "deadline": "2026-10-01", "metric_key": "", '
            '"first_steps": [], "hero": false}'
        )
    monkeypatch.setattr(main, "_goal_draft_model_reply", fake_reply)
    conn = db.connect()
    goals_before = conn.execute("SELECT COUNT(*) n FROM goals").fetchone()["n"]
    tasks_before = conn.execute("SELECT COUNT(*) n FROM tasks").fetchone()["n"]
    conn.close()

    r = client.post("/api/goals/draft", json={"text": "Join AKPSI by October", "pillar": "life"})
    assert r.status_code == 200

    conn = db.connect()
    assert conn.execute("SELECT COUNT(*) n FROM goals").fetchone()["n"] == goals_before
    assert conn.execute("SELECT COUNT(*) n FROM tasks").fetchone()["n"] == tasks_before
    conn.close()


def test_goal_draft_survives_a_markdown_fence(client, monkeypatch):
    """Verified live: the system prompt says "no markdown fences" and the
    model wraps its reply in one anyway often enough to need real handling."""
    async def fenced_reply(text, pillar):
        return (
            '```json\n{"name": "Join AKPSI", "shape": "milestone", "target": "", '
            '"unit": "", "per": "", "deadline": "2026-10-01", "metric_key": "", '
            '"first_steps": [], "hero": false}\n```'
        )
    monkeypatch.setattr(main, "_goal_draft_model_reply", fenced_reply)
    r = client.post("/api/goals/draft", json={"text": "Join AKPSI by October", "pillar": "life"})
    assert r.status_code == 200
    assert r.json()["name"] == "Join AKPSI"


def test_goal_draft_metric_is_pillar_scoped():
    draft = main._validate_goal_draft("life", {
        "name": "Steps today", "shape": "number", "target": "10000", "unit": "steps",
        "per": "", "deadline": "", "metric_key": "steps_today", "first_steps": [], "hero": False,
    })
    assert draft["metric_key"] == ""


def test_goal_draft_parser_is_zero_tool_single_turn_and_model_pinned(monkeypatch):
    class FakeResult:
        is_error = False
        result = (
            '{"name": "Join AKPSI", "shape": "milestone", "target": "", "unit": "", '
            '"per": "", "deadline": "2026-10-01", "metric_key": "", '
            '"first_steps": [], "hero": false}'
        )
    captured = {}

    def fake_options(**kwargs):
        captured.update(kwargs)
        return kwargs

    async def fake_query(*, prompt, options):
        captured["prompt"] = prompt
        yield FakeResult()

    monkeypatch.setattr(runner, "ClaudeAgentOptions", fake_options)
    monkeypatch.setattr(runner, "ResultMessage", FakeResult)
    monkeypatch.setattr(runner, "query", fake_query)
    monkeypatch.setattr(runner, "find_cli", lambda: None)

    out = asyncio.run(main._goal_draft_model_reply("Join AKPSI by October", "life"))

    assert captured["tools"] == []
    assert captured["mcp_servers"] == {}
    assert captured["max_turns"] == 1
    assert captured["model"] == main.GOAL_DRAFT_MODEL
    assert captured["max_budget_usd"] == main.GOAL_DRAFT_COST_CAP_USD
    assert "Join AKPSI" in captured["prompt"]
    assert "life" in out or "milestone" in out
