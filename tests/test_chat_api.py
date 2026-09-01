"""SPEC-v25 daytime chat API contracts."""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner
from api import main
from core import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    monkeypatch.setattr(main, "_agent_execution_gate", main.AgentExecutionGate())
    monkeypatch.setattr(main, "_agent_invocation_started_at", 0.0)
    monkeypatch.setattr(main, "_agent_run_started_at", 0.0)
    monkeypatch.setattr(main, "_money_refresh_started_at", 0.0)
    return TestClient(main.app)


def _open_thread(client, model=None):
    payload = {} if model is None else {"model": model}
    response = client.post("/api/chat/threads", json=payload)
    assert response.status_code == 201
    return response.json()


def test_prefs_and_omitted_model_are_sonnet(client):
    prefs = client.get("/api/chat/prefs")
    assert prefs.status_code == 200
    assert prefs.headers["cache-control"] == "no-store"
    assert prefs.json()["default_model"] == runner.SONNET
    thread = _open_thread(client)
    assert thread["model"] == runner.SONNET
    # SPEC-v37 2.7: Files is granted by default on every new thread.
    assert thread["granted_chips"] == ["files"]
    assert thread["specialist_sonnet"] == 0


def test_prefs_and_omitted_role_are_steward(client):
    """SPEC-v37 3.5: Alfred (steward) is the default agent, not Fury."""
    prefs = client.get("/api/chat/prefs")
    assert prefs.json()["default_role"] == "steward"
    thread = _open_thread(client)
    assert thread["role"] == "steward"


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-sonnet-5"])
def test_closed_models_are_accepted(client, model):
    assert client.post("/api/chat/threads", json={"model": model}).status_code == 201


@pytest.mark.parametrize("model", [
    "claude-opus-4", "claude-sonnet-5-20250514", "", "haiku", "SONNET",
    "claude-haiku-4-5 ",
])
def test_unknown_models_are_422(client, model):
    assert client.post("/api/chat/threads", json={"model": model}).status_code == 422
    assert client.patch("/api/chat/prefs", json={"default_model": model}).status_code == 422


def _terminalize(turn_id, answer="Body text."):
    conn = db.connect()
    try:
        db.claim_agent_invocation(conn, turn_id)
        db.finish_agent_invocation_success(
            conn, turn_id,
            json.dumps({"version": 1, "verdict": "-", "body": answer, "next_action": "-"}),
            [], runner.SONNET, 1, 0.0,
        )
    finally:
        conn.close()


def test_turn_is_202_and_has_no_cooldown(client, monkeypatch):
    """SPEC-v26: cooldowns were metered-API insurance and are gone.

    Back-to-back sends are allowed the instant the previous turn is done, no
    timer involved. The only refusal is a turn still in flight.
    """
    started = []

    def _start(invocation_id):
        started.append(invocation_id)
        main._agent_execution_gate.release()

    monkeypatch.setattr(main, "_start_chat_turn_worker", _start)
    thread = _open_thread(client)
    first = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "What should I cut this week?",
    })
    assert first.status_code == 202
    assert first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["mode"] == "chat"
    assert body["role"] == "chief"
    assert body["model"] == runner.SONNET
    assert started == [body["id"]]

    # Still answering: refused for correctness, not for time.
    blocked = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "too soon",
    })
    assert blocked.status_code == 409

    # Done answering: allowed immediately, with the clock deliberately frozen
    # one second later to prove no cooldown is consulted.
    _terminalize(body["id"])
    monkeypatch.setattr(main, "_agent_invocation_started_at", 100.0)
    monkeypatch.setattr(main.time, "time", lambda: 101.0)
    follow = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "And the Capital One charge?",
    })
    assert follow.status_code == 202


def test_threads_for_different_agents_coexist(client, monkeypatch):
    """One open thread per agent: a CFO thread does not close a Fury thread."""
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda *_: None)
    fury = client.post("/api/chat/threads", json={"role": "chief"}).json()
    cfo = client.post("/api/chat/threads", json={"role": "cfo"}).json()
    assert fury["role"] == "chief"
    assert cfo["role"] == "cfo"
    assert client.get(f"/api/chat/threads/{fury['id']}").json()["status"] == "OPEN"
    assert client.get(f"/api/chat/threads/{cfo['id']}").json()["status"] == "OPEN"

    # A second thread for the same agent retires the first.
    fury2 = client.post("/api/chat/threads", json={"role": "chief"}).json()
    assert client.get(f"/api/chat/threads/{fury['id']}").json()["status"] == "CLOSED"
    assert client.get(f"/api/chat/threads/{fury2['id']}").json()["status"] == "OPEN"


@pytest.mark.parametrize("role", ["nope", "", "ian", "archivist_typo"])
def test_unknown_thread_agent_is_422(client, role):
    assert client.post("/api/chat/threads", json={"role": role}).status_code == 422


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-fable-5", "claude-haiku-4-5"])
def test_all_four_plan_models_are_accepted(client, model):
    created = client.post("/api/chat/threads", json={"model": model})
    assert created.status_code == 201
    assert created.json()["model"] == model


def test_granting_an_unconnected_chip_is_422(client):
    """Closes the SPEC-v25 review finding: the rule was UI-only."""
    thread = _open_thread(client)
    refused = client.patch(f"/api/chat/threads/{thread['id']}", json={
        "granted_chips": ["money"],
    })
    assert refused.status_code == 422
    assert "not connected" in refused.text
    # The refused patch must not have touched the thread's existing grants.
    assert client.get(f"/api/chat/threads/{thread['id']}").json()["granted_chips"] == ["files"]


def test_gate_busy_is_409_across_surfaces(client, monkeypatch):
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    assert main._agent_execution_gate.acquire() is True
    busy = client.post(f"/api/chat/threads/{thread['id']}/turns", json={"question": "hello"})
    assert busy.status_code == 409


def test_refresh_money_without_chip_is_422(client):
    thread = _open_thread(client)
    response = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "refresh my bank",
        "workflows": ["refresh_money"],
    })
    assert response.status_code == 422
    assert "Money chip is off" in response.text


def test_unknown_chip_and_workflow_are_422(client):
    thread = _open_thread(client)
    assert client.patch(f"/api/chat/threads/{thread['id']}", json={
        "granted_chips": ["plaid"],
    }).status_code == 422
    assert client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "hi",
        "workflows": ["send_email"],
    }).status_code == 422
    assert client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "hi",
        "model": runner.SONNET,
    }).status_code == 422


def test_specialists_reject_chief_and_unknown_roles(client):
    thread = _open_thread(client)
    assert client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "Should I call or rest?",
        "workflows": [{"kind": "consult_specialists", "roles": ["chief", "scout"]}],
    }).status_code == 400
    assert client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "Should I call or rest?",
        "workflows": [{"kind": "consult_specialists", "roles": ["not_a_role", "scout"]}],
    }).status_code == 400


def test_projection_hides_raw_prompt_and_state_excludes_chat(client, monkeypatch):
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    created = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "SECRET-CHAT-QUESTION",
    }).json()
    conn = db.connect()
    db.claim_agent_invocation(conn, created["id"])
    parsed = {
        "version": 1,
        "verdict": "Cut hosting.",
        "body": "Hosting is the line.",
        "next_action": "Open Money.",
        "evidence": ["Goals"],
        "numbers": [],
        "missing_access": [],
    }
    db.finish_agent_invocation_success(
        conn, created["id"],
        json.dumps(parsed, sort_keys=True, separators=(",", ":")),
        ["Goals"], runner.SONNET, 2, 0.04,
    )
    conn.close()

    detail = client.get(f"/api/chat/threads/{thread['id']}")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    payload = detail.json()
    turn = payload["turns"][0]
    assert turn["mode"] == "chat"
    assert turn["verdict"] == "Cut hosting."
    assert turn["question"] == "SECRET-CHAT-QUESTION"
    for forbidden in ("prompt", "tool_args", "tool_results", "transcript"):
        assert forbidden not in json.dumps(payload)

    state = client.get("/api/state")
    text = state.text
    assert "SECRET-CHAT-QUESTION" not in text
    assert "Cut hosting." not in text
    assert "granted_chips" not in text
    assert "chat_threads" not in text


def test_worker_validates_reply_and_does_not_write_memos(client, monkeypatch):
    def fake_run(*args, **kwargs):
        return {
            "ok": True,
            "answer": json.dumps({
                "body": "Hosting is the line.",
                "evidence": ["Goals"],
                "missing_access": [],
                "next_action": "Open Money.",
                "numbers": [],
                "verdict": "Cut hosting.",
                "version": 1,
            }, sort_keys=True, separators=(",", ":")),
            "evidence": ["Goals"],
            "parsed": {
                "body": "Hosting is the line.",
                "evidence": ["Goals"],
                "missing_access": [],
                "next_action": "Open Money.",
                "numbers": [],
                "verdict": "Cut hosting.",
                "version": 1,
            },
            "model": runner.SONNET,
            "turns": 2,
            "cost_usd": 0.02,
            "error_code": "",
        }

    monkeypatch.setattr(main, "_execute_chat_turn", fake_run)
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    created = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "What should I cut?",
    })
    assert created.status_code == 202
    invocation_id = created.json()["id"]
    main._run_chat_turn_worker(invocation_id)
    conn = db.connect()
    stored = db.get_agent_invocation(conn, invocation_id)
    memo_count = conn.execute("SELECT COUNT(*) AS n FROM memos").fetchone()["n"]
    conn.close()
    assert stored["status"] == "SUCCEEDED"
    assert stored["model"] == runner.SONNET
    assert json.loads(stored["answer"])["verdict"] == "Cut hosting."
    assert memo_count == 0


def test_chips_registry_has_stable_order(client):
    response = client.get("/api/chat/chips")
    assert response.status_code == 200
    chips = response.json()["chips"]
    ids = [chip["id"] for chip in chips]
    # School is a local, sanitized source available to Fury at an aggregate
    # level. Documents still filters out because Fury cannot read that
    # register. files/workspace/shell (SPEC-v37 §2.7 Plane B capability
    # chips) are "kind": "builtin" like web, so they're always offered.
    assert ids == ["money", "mail", "calendar", "school", "web", "files", "workspace", "shell"]
    assert all("token" not in json.dumps(chip).lower() for chip in chips)
    # The one source that leaves the machine is marked as such.
    web = next(chip for chip in chips if chip["id"] == "web")
    assert web["external"] is True
    assert all(chip["external"] is False for chip in chips if chip["id"] != "web")


def test_chips_are_filtered_to_what_the_agent_can_use(client):
    """A chip that would grant nothing is not offered (SPEC-v27 §2)."""
    counsel = [c["id"] for c in client.get("/api/chat/chips?role=counsel").json()["chips"]]
    assert "documents" in counsel, "counsel reads the document register"
    physician = [c["id"] for c in client.get("/api/chat/chips?role=physician").json()["chips"]]
    assert "money" not in physician, "a money chip on a physician thread grants nothing"
    # An unknown role falls back to Fury rather than erroring or leaking.
    assert client.get("/api/chat/chips?role=nope").status_code == 200


@pytest.mark.parametrize("effort", ["low", "medium", "high", "max"])
def test_all_effort_levels_round_trip(client, effort):
    created = client.post("/api/chat/threads", json={"effort": effort})
    assert created.status_code == 201
    assert created.json()["effort"] == effort


@pytest.mark.parametrize("effort", ["xhigh", "ultra", "", "HIGH"])
def test_unknown_effort_is_422(client, effort):
    assert client.post("/api/chat/threads", json={"effort": effort}).status_code == 422
    thread = _open_thread(client)
    assert client.patch(
        f"/api/chat/threads/{thread['id']}", json={"effort": effort},
    ).status_code == 422


def test_effort_defaults_to_high_and_is_patchable(client):
    thread = _open_thread(client)
    assert thread["effort"] == "high"
    patched = client.patch(f"/api/chat/threads/{thread['id']}", json={"effort": "max"})
    assert patched.status_code == 200
    assert client.get(f"/api/chat/threads/{thread['id']}").json()["effort"] == "max"


def _fake_chat_reply(*, verdict="-", body="ok", session_id=""):
    parsed = {"version": 1, "verdict": verdict, "body": body, "next_action": "-"}
    return {
        "ok": True,
        "answer": json.dumps(parsed, sort_keys=True, separators=(",", ":")),
        "evidence": [],
        "parsed": dict(parsed),
        "model": runner.HAIKU,
        "turns": 1,
        "cost_usd": 0.01,
        "error_code": "",
        "session_id": session_id,
        "specialists": [],
    }


def test_consult_specialists_workflow_passes_convened_through(client, monkeypatch):
    """SPEC-v37 §3.6: consult_specialists no longer runs a manual pre-loop of
    child agent_invocations -- the chosen roles ride straight through to
    run_chat_turn's own convened= kwarg, which convenes them as native SDK
    subagents inside its single query() call."""
    captured = {}

    def fake_execute(conn, question, **kwargs):
        captured.update(kwargs)
        return _fake_chat_reply(verdict="Rest.", body="Legs are cooked.")

    monkeypatch.setattr(main, "_execute_chat_turn", fake_execute)
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    created = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "Should I call or rest?",
        "workflows": [{"kind": "consult_specialists", "roles": ["scout", "cfo"]}],
    })
    assert created.status_code == 202
    main._run_chat_turn_worker(created.json()["id"])

    assert captured["convened"] == ["scout", "cfo"]
    conn = db.connect()
    stored = db.get_agent_invocation(conn, created.json()["id"])
    conn.close()
    assert stored["status"] == "SUCCEEDED"
    assert json.loads(stored["answer"])["verdict"] == "Rest."


def test_plain_turn_convenes_nobody(client, monkeypatch):
    captured = {}

    def fake_execute(conn, question, **kwargs):
        captured.update(kwargs)
        return _fake_chat_reply()

    monkeypatch.setattr(main, "_execute_chat_turn", fake_execute)
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    created = client.post(f"/api/chat/threads/{thread['id']}/turns", json={
        "question": "hi",
    })
    main._run_chat_turn_worker(created.json()["id"])
    assert captured["convened"] is None


def test_session_id_resumes_and_persists_across_turns(client, monkeypatch):
    """SPEC-v37 §7.4: the thread's stored sdk_session_id is handed back to
    run_chat_turn as session_id= on the next turn, and a session id the
    runner returns is persisted via db.set_chat_thread_session regardless of
    whether that particular turn's reply then succeeded or failed."""
    captured = {}

    def fake_execute(conn, question, **kwargs):
        captured.update(kwargs)
        return _fake_chat_reply(session_id="sdk-session-PRIVATE-1")

    monkeypatch.setattr(main, "_execute_chat_turn", fake_execute)
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)

    first = client.post(f"/api/chat/threads/{thread['id']}/turns", json={"question": "hi"})
    main._run_chat_turn_worker(first.json()["id"])
    assert captured["session_id"] is None  # nothing stored yet on the first turn

    conn = db.connect()
    stored_thread = db.get_chat_thread(conn, thread["id"])
    conn.close()
    assert stored_thread["sdk_session_id"] == "sdk-session-PRIVATE-1"
    # Never handed to the client: it is a server-internal continuity token.
    assert "sdk_session_id" not in client.get(f"/api/chat/threads/{thread['id']}").text
    assert "sdk-session-PRIVATE-1" not in client.get(f"/api/chat/threads/{thread['id']}").text

    second = client.post(f"/api/chat/threads/{thread['id']}/turns", json={"question": "and then?"})
    main._run_chat_turn_worker(second.json()["id"])
    assert captured["session_id"] == "sdk-session-PRIVATE-1"


def test_session_id_persists_even_when_the_turn_fails(client, monkeypatch):
    """A session can be created by the SDK even on a turn whose reply later
    fails validation; losing it would force every future turn on this
    thread back to the from-stored-turns fallback for no reason."""
    def fake_execute(conn, question, **kwargs):
        return {
            "ok": False, "answer": "", "evidence": [], "parsed": None,
            "model": runner.HAIKU, "turns": 1, "cost_usd": 0.01,
            "error_code": "invalid_reply", "session_id": "sdk-session-PRIVATE-2",
            "specialists": [],
        }

    monkeypatch.setattr(main, "_execute_chat_turn", fake_execute)
    monkeypatch.setattr(main, "_start_chat_turn_worker", lambda invocation_id: None)
    thread = _open_thread(client)
    created = client.post(f"/api/chat/threads/{thread['id']}/turns", json={"question": "hi"})
    main._run_chat_turn_worker(created.json()["id"])

    conn = db.connect()
    stored_turn = db.get_agent_invocation(conn, created.json()["id"])
    stored_thread = db.get_chat_thread(conn, thread["id"])
    conn.close()
    assert stored_turn["status"] == "FAILED"
    assert stored_thread["sdk_session_id"] == "sdk-session-PRIVATE-2"


def test_startup_recovers_stale_chat_work_and_prunes_old_terminal_rows(client):
    """Moved here from the now-deleted test_agent_invocations_api.py
    (SPEC-v37 deleted the Ask/Room API endpoints, not the generic
    agent_invocations startup recovery every kind of row rides on -- 'ask'
    is used here only because db.create_agent_invocation's mode CHECK still
    accepts it without standing up a whole chat thread; fail_stale_agent_
    invocations does not look at mode. A chat turn orphaned by a server
    restart must fail as 'interrupted' rather than hang QUEUED/RUNNING
    forever, and old terminal rows must still prune, identically."""
    conn = db.connect()
    stale = db.create_agent_invocation(conn, "chief", "ask", "stale question")
    old_terminal = db.create_agent_invocation(conn, "chief", "ask", "old terminal")
    db.claim_agent_invocation(conn, stale["id"])
    db.claim_agent_invocation(conn, old_terminal["id"])
    db.finish_agent_invocation_failure(conn, old_terminal["id"], "runner_error", "retry")
    conn.execute(
        "UPDATE agent_invocations SET started_at='2000-01-01 00:00:00' WHERE id=?",
        (stale["id"],),
    )
    conn.execute(
        "UPDATE agent_invocations SET created_at='2000-01-01 00:00:00', "
        "started_at='2000-01-01 00:00:00', finished_at='2000-01-01 00:00:00' "
        "WHERE id=?",
        (old_terminal["id"],),
    )
    conn.commit()
    conn.close()

    with TestClient(main.app) as startup_client:
        assert startup_client.get("/api/health").status_code == 200

    conn = db.connect()
    recovered = db.get_agent_invocation(conn, stale["id"])
    pruned = db.get_agent_invocation(conn, old_terminal["id"])
    conn.close()
    assert recovered["status"] == "FAILED"
    assert recovered["error_code"] == "interrupted"
    assert pruned is None
