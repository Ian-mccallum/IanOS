"""SPEC-v32 Part D: the Day Command sentence goes live.

Covers the plain-ALTER migration on `briefs`, the one write path for a live
refresh (`update_day_command`), the server-computed anchor in `write_brief`
(never trusted from the model), and the `/api/order/refresh` endpoint's
throttle/cap/rewrite-failure behaviour.

SAFETY: no test here ever lets `agents.runner.query` reach the real Anthropic
API. Tests that exercise `write_brief` monkeypatch `runner.query` with a fake
async generator (the tests/test_chat_runner.py precedent); tests that exercise
`/api/order/refresh` monkeypatch `main._rewrite_day_command` directly (the
tests/test_school.py `_school_study_model_reply` precedent) and never touch
`runner.query` at all.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from claude_agent_sdk import ResultMessage
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from api import main  # noqa: E402
from core import acts, attention, db  # noqa: E402
from core.roles import load_role  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    # The endpoint's cooldown timer is a module-level global by design (the
    # btc-sync precedent); reset it per test so one test's successful call
    # can't throttle the next test's first call.
    monkeypatch.setattr(main, "_order_refresh_started_at", 0.0)
    db.connect().close()
    return TestClient(main.app)


def _result(text: str, *, turns: int = 1, cost: float = 0.001, error: bool = False):
    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=8,
        is_error=error,
        num_turns=turns,
        session_id="test",
        total_cost_usd=cost,
        result=text,
    )


def _seed_deadline_goal(conn, name="Renew LLC", days_out=2):
    """Give the chief exactly one candidate: a deadline goal within GOAL_WINDOW."""
    deadline = (date.today() + timedelta(days=days_out)).isoformat()
    cur = conn.execute(
        """INSERT INTO goals (name, kind, target, deadline, domain, current_value)
           VALUES (?, 'deadline', '1', ?, 'business', '')""",
        (name, deadline),
    )
    conn.commit()
    return cur.lastrowid


def _top_chief_key(conn) -> str:
    result = attention.compile_attention(conn, datetime.now())
    chief_view = attention.agent_projection(result, "chief")
    return chief_view[0]["key"] if chief_view else ""


# --------------------------------------------------------------- core/db.py

def test_migration_adds_anchor_and_refreshes_columns_with_defaults(tmp_path):
    """A pre-v32 briefs table (no anchor_key/command_refreshes) migrates in
    place via plain ALTERs, and an existing row defaults to '' / 0."""
    path = tmp_path / "old.db"
    raw = sqlite3.connect(path)
    raw.execute(
        """CREATE TABLE briefs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            kind        TEXT NOT NULL DEFAULT 'daily' CHECK (kind IN ('daily', 'weekly')),
            body        TEXT NOT NULL,
            day_command TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE (date, kind)
        )"""
    )
    raw.execute(
        "INSERT INTO briefs (date, kind, body, day_command) VALUES (?, ?, ?, ?)",
        ("2026-01-01", "daily", "an old nightly brief body", "old sentence"),
    )
    raw.commit()

    assert "anchor_key" not in [r[1] for r in raw.execute("PRAGMA table_info(briefs)")]

    db._migrate_columns(raw)
    raw.commit()

    cols = {r[1] for r in raw.execute("PRAGMA table_info(briefs)")}
    assert "anchor_key" in cols
    assert "command_refreshes" in cols

    row = raw.execute(
        "SELECT anchor_key, command_refreshes, body FROM briefs WHERE date='2026-01-01'"
    ).fetchone()
    assert row[0] == ""
    assert row[1] == 0
    assert row[2] == "an old nightly brief body"  # untouched by the migration
    raw.close()


def test_update_day_command_increments_refreshes_and_preserves_body(conn):
    db.upsert_brief(conn, "2026-01-01", "daily", "nightly prose stays put",
                     "old sentence", "goal:1")
    db.update_day_command(conn, "2026-01-01", "daily", "new sentence", "goal:2")

    brief = db.latest_brief(conn)
    assert brief["day_command"] == "new sentence"
    assert brief["anchor_key"] == "goal:2"
    assert brief["command_refreshes"] == 1
    assert brief["body"] == "nightly prose stays put"  # untouched

    db.update_day_command(conn, "2026-01-01", "daily", "third sentence", "goal:3")
    brief2 = db.latest_brief(conn)
    assert brief2["command_refreshes"] == 2
    assert brief2["body"] == "nightly prose stays put"


def test_upsert_brief_resets_refreshes_on_a_full_nightly_rewrite(conn):
    """A fresh nightly brief naturally starts a new day: it's fine for the
    whole-brief upsert to reset command_refreshes back to 0."""
    db.upsert_brief(conn, "2026-01-01", "daily", "body one", "sentence one", "goal:1")
    db.update_day_command(conn, "2026-01-01", "daily", "refreshed sentence", "goal:2")
    assert db.latest_brief(conn)["command_refreshes"] == 1

    db.upsert_brief(conn, "2026-01-01", "daily", "body two", "sentence two", "goal:9")
    brief = db.latest_brief(conn)
    assert brief["body"] == "body two"
    assert brief["day_command"] == "sentence two"
    assert brief["anchor_key"] == "goal:9"
    assert brief["command_refreshes"] == 0


# ------------------------------------------------------------ write_brief

def test_write_brief_tool_schema_has_no_anchor_key_argument():
    """The chief is never trusted to report what it anchored on: the tool
    schema doesn't even offer the model a place to put one."""
    schema = runner.write_brief.input_schema
    assert "anchor_key" not in schema
    assert set(schema) == {"body", "day_command"}


def test_write_brief_anchor_is_server_computed_not_model_reported(conn, monkeypatch):
    """Even if the model somehow smuggled an anchor_key into its call, the
    stored anchor_key comes from an independent, server-side compile of the
    same deterministic attention order, never from the tool call."""
    goal_id = _seed_deadline_goal(conn)
    expected_key = f"goal:{goal_id}"
    assert _top_chief_key(conn) == expected_key  # sanity: our fixture worked

    role_meta = load_role("chief")

    async def fake_query(*, prompt, options):
        # Simulate the SDK's in-process MCP tool call: the model "calls"
        # write_brief, smuggling an anchor_key the schema doesn't accept.
        # dict extra keys are simply ignored by write_brief's args.get() reads.
        await runner.write_brief.handler({
            "body": "x" * 150,
            "day_command": "Renew the LLC before the deadline.",
            "anchor_key": "lie:not-the-real-anchor",
        })
        yield _result("brief written")

    monkeypatch.setattr(runner, "query", fake_query)

    result = asyncio.run(runner.run_role(role_meta, conn, "daily"))
    assert result["ok"] is True
    assert result["brief_written"] is True

    brief = db.latest_brief(conn)
    assert brief["anchor_key"] == expected_key
    assert brief["anchor_key"] != "lie:not-the-real-anchor"
    assert brief["day_command"] == "Renew the LLC before the deadline."


# --------------------------------------------------------- GET /api/state

def test_state_endpoint_never_calls_the_rewrite_or_the_sdk(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("GET /api/state must never call the model (Law 5)")

    monkeypatch.setattr(main, "_rewrite_day_command", forbidden)

    async def forbidden_query(*args, **kwargs):
        raise AssertionError("GET /api/state must never invoke runner.query")
        yield  # pragma: no cover

    monkeypatch.setattr(runner, "query", forbidden_query)

    resp = client.get("/api/state")
    assert resp.status_code == 200


# ----------------------------------------------------- POST /api/order/refresh

def test_order_refresh_501_when_auth_not_configured(client, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/api/order/refresh")
    assert resp.status_code == 501


def test_order_refresh_no_brief_today(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    called = []

    async def fake_rewrite(chief_candidates, old_sentence):
        called.append(True)
        return "should never run"

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": "no_brief_today"}
    assert called == []


def test_order_refresh_unchanged_when_anchor_already_matches(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        goal_id = _seed_deadline_goal(conn)
        expected_key = _top_chief_key(conn)
        assert expected_key == f"goal:{goal_id}"
        db.upsert_brief(conn, db.today(), "daily", "x" * 150, "old sentence", expected_key)
    finally:
        conn.close()

    called = []

    async def fake_rewrite(chief_candidates, old_sentence):
        called.append(True)
        return "should never run"

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "throttled": True, "reason": "unchanged"}
    assert called == []


def test_order_refresh_rewrites_on_genuine_mismatch(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        goal_id = _seed_deadline_goal(conn)
        expected_key = _top_chief_key(conn)
        db.upsert_brief(conn, db.today(), "daily", "x" * 150, "old sentence", "stale:key")
    finally:
        conn.close()

    calls = []

    async def fake_rewrite(chief_candidates, old_sentence):
        calls.append((chief_candidates, old_sentence))
        return "Renew the LLC today."

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"ok": True, "day_command": "Renew the LLC today."}
    assert len(calls) == 1

    conn = db.connect()
    try:
        brief = db.latest_brief(conn)
    finally:
        conn.close()
    assert brief["day_command"] == "Renew the LLC today."
    assert brief["anchor_key"] == expected_key == f"goal:{goal_id}"
    assert brief["command_refreshes"] == 1


def test_order_refresh_limit_blocks_regardless_of_staleness(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        _seed_deadline_goal(conn)
        db.upsert_brief(conn, db.today(), "daily", "x" * 150, "old sentence", "stale:key")
        # Drive command_refreshes to the cap via the real write path.
        for i in range(3):
            db.update_day_command(conn, db.today(), "daily", f"sentence {i}", "stale:key")
        assert db.latest_brief(conn)["command_refreshes"] == 3
    finally:
        conn.close()

    called = []

    async def fake_rewrite(chief_candidates, old_sentence):
        called.append(True)
        return "should never run"

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "throttled": True, "reason": "limit"}
    assert called == []


def test_order_refresh_cooldown_blocks_a_second_call_within_90_minutes(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        goal_id = _seed_deadline_goal(conn)
        db.upsert_brief(conn, db.today(), "daily", "x" * 150, "old sentence", "stale:key")
    finally:
        conn.close()

    calls = []

    async def fake_rewrite(chief_candidates, old_sentence):
        calls.append(True)
        return "First rewrite."

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    first = client.post("/api/order/refresh")
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json().get("throttled") is not True
    assert len(calls) == 1

    # The mismatch persists (anchor_key now matches goal:<id>, but nothing
    # else changed the underlying attention order), so a second call inside
    # the cooldown window must be throttled by cooldown specifically, not by
    # limit or unchanged.
    conn = db.connect()
    try:
        db.update_day_command(conn, db.today(), "daily", "First rewrite.",
                               "deliberately-different-key")
    finally:
        conn.close()

    second = client.post("/api/order/refresh")
    assert second.status_code == 200
    assert second.json() == {"ok": True, "throttled": True, "reason": "cooldown"}
    assert len(calls) == 1  # the fake rewrite was not called again


def test_order_refresh_failed_rewrite_leaves_old_sentence_standing(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        goal_id = _seed_deadline_goal(conn)
        db.upsert_brief(conn, db.today(), "daily", "x" * 150, "old sentence standing", "stale:key")
    finally:
        conn.close()

    async def fake_rewrite(chief_candidates, old_sentence):
        return None  # simulates an execution-claim or overlength rejection

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "reason": "rewrite_failed"}

    conn = db.connect()
    try:
        brief = db.latest_brief(conn)
    finally:
        conn.close()
    assert brief["day_command"] == "old sentence standing"
    assert brief["anchor_key"] == "stale:key"
    assert brief["command_refreshes"] == 0


def test_order_refresh_allows_a_weekly_brief_that_governs_today(client, monkeypatch):
    """SPEC-v37 §8.2: the endpoint's gate compares governs_date, not date,
    and no longer requires kind == 'daily' (Sunday writes a weekly, which
    used to make every Monday dead). A weekly brief governing today must be
    refreshable, and the write must land on the weekly row (date/kind taken
    from the brief `latest_brief` actually found), not a hardcoded
    (today, 'daily') pair."""
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fake")
    conn = db.connect()
    try:
        goal_id = _seed_deadline_goal(conn)
        expected_key = _top_chief_key(conn)
        db.upsert_brief(conn, db.today(), "weekly", "x" * 150, "old sentence",
                         "stale:key", governs_date=db.today())
    finally:
        conn.close()

    calls = []

    async def fake_rewrite(chief_candidates, old_sentence):
        calls.append((chief_candidates, old_sentence))
        return "Renew the LLC today."

    monkeypatch.setattr(main, "_rewrite_day_command", fake_rewrite)

    resp = client.post("/api/order/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("reason") != "no_brief_today"
    assert body == {"ok": True, "day_command": "Renew the LLC today."}
    assert len(calls) == 1

    conn = db.connect()
    try:
        brief = db.latest_brief(conn)
    finally:
        conn.close()
    assert brief["kind"] == "weekly"
    assert brief["day_command"] == "Renew the LLC today."
    assert brief["anchor_key"] == expected_key == f"goal:{goal_id}"
    assert brief["command_refreshes"] == 1


# ---------------------------------------------------------------------------
# SPEC-v37 §4.5: Ring 1 act receipts -- POST /api/acts/{id}/undo and the
# recent_acts projection on GET /api/state.
# ---------------------------------------------------------------------------

def _seed_act(conn) -> int:
    """A cheap, real Ring 1 act (note.create) with a working undo handler."""
    result = acts.note_create(conn, role="steward", plane="nightly", thread_id=None,
                               body="test note")
    return result["act_id"]


def test_undo_act_happy_path(client):
    conn = db.connect()
    try:
        act_id = _seed_act(conn)
    finally:
        conn.close()

    resp = client.post(f"/api/acts/{act_id}/undo")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["id"] == act_id
    assert body["undone_at"]


def test_undo_act_twice_is_400(client):
    conn = db.connect()
    try:
        act_id = _seed_act(conn)
    finally:
        conn.close()

    first = client.post(f"/api/acts/{act_id}/undo")
    assert first.status_code == 200

    second = client.post(f"/api/acts/{act_id}/undo")
    assert second.status_code == 400
    assert "already undone" in second.json()["detail"]


def test_undo_act_not_found_is_404(client):
    resp = client.post("/api/acts/999999/undo")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_state_includes_recent_acts_without_inverse_json(client):
    conn = db.connect()
    try:
        act_id = _seed_act(conn)
    finally:
        conn.close()

    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert "recent_acts" in body
    matches = [a for a in body["recent_acts"] if a["id"] == act_id]
    assert len(matches) == 1
    entry = matches[0]
    assert set(entry.keys()) == {
        "id", "role", "act", "target_kind", "target_id",
        "summary", "created_at", "undone_at",
    }
    assert entry["role"] == "steward"
    assert entry["act"] == "note.create"
    assert entry["undone_at"] is None
