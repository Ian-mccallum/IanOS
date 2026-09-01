"""Source-aware Apple Health snapshots: replace, replay, and privacy walls."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner
from api import main
from core import db, garden, health


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def _central_day() -> str:
    return datetime.now(ZoneInfo(health.HEALTH_TIMEZONE)).date().isoformat()


def _stamp(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _measurement(
    metric: str,
    value: float | int,
    *,
    record_key: str,
    finality: str = "final",
    day: str | None = None,
    stamp: str | None = None,
) -> dict:
    timestamp = stamp or _stamp()
    units = {
        "sleep_hours": "hours",
        "steps": "count",
        "workouts": "count",
        "workout_mins": "minutes",
    }
    return {
        "metric": metric,
        "local_day": day or _central_day(),
        "value": value,
        "unit": units[metric],
        "source_record_key": record_key,
        "observed_at": timestamp,
        "as_of": timestamp,
        "finality": finality,
    }


def _snapshot(
    snapshot_id: str,
    measurements: list[dict],
    *,
    capture_kind: str = "activity_final",
    captured_at: str | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "source": "apple_health_shortcuts",
        "installation_id": "test-phone-1",
        "snapshot_id": snapshot_id,
        "capture_kind": capture_kind,
        "captured_at": captured_at or _stamp(),
        "timezone": health.HEALTH_TIMEZONE,
        "measurements": measurements,
    }


def _health_row() -> dict:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT * FROM health_daily WHERE date=?", (_central_day(),)
        ).fetchone()
        return dict(row or {})
    finally:
        conn.close()


def test_snapshot_replay_and_semantic_duplicate_never_increment(client):
    stamp = _stamp()
    payload = _snapshot("activity-1", [
        _measurement("steps", 7123, record_key="steps-day-v1", stamp=stamp),
        _measurement("workouts", 1, record_key="workouts-day-v1", stamp=stamp),
        _measurement("workout_mins", 48, record_key="mins-day-v1", stamp=stamp),
    ], captured_at=stamp)

    first = client.post("/api/health/snapshots", json=payload)
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["status"] == "accepted"
    assert _health_row()["steps"] == 7123

    replay = client.post("/api/health/snapshots", json=payload)
    assert replay.status_code == 200
    assert replay.json()["status"] == "replayed"

    duplicate = dict(payload, snapshot_id="activity-duplicate")
    duplicate_response = client.post("/api/health/snapshots", json=duplicate)
    assert duplicate_response.status_code == 200
    assert duplicate_response.json()["status"] == "updated"
    assert _health_row()["steps"] == 7123

    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_daily_measurements").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()[0] == 2
    finally:
        conn.close()


def test_remote_health_capture_uses_only_the_paired_health_token(client, monkeypatch):
    """A Shortcut credential cannot become the broad ianOS phone credential."""
    monkeypatch.setattr(main, "API_TOKEN", "phone-app-secret")
    monkeypatch.setattr(main, "HEALTH_INGEST_TOKEN", "health-capture-secret")
    monkeypatch.setattr(main, "HEALTH_INGEST_INSTALLATION_ID", "paired-iphone-1")
    payload = _snapshot("paired-snapshot", [
        _measurement("steps", 7123, record_key="paired-steps-v1"),
    ])
    remote_base = {"x-forwarded-for": "100.64.0.9"}

    # The existing PWA token is deliberately not accepted at the health route.
    broad = client.post(
        "/api/health/snapshots",
        json=payload,
        headers={**remote_base, "authorization": "Bearer phone-app-secret"},
    )
    assert broad.status_code == 401

    # A captured health token is constrained to its paired installation id.
    wrong_installation = client.post(
        "/api/health/snapshots",
        json=payload,
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert wrong_installation.status_code == 403

    paired = dict(payload, installation_id="paired-iphone-1")
    accepted = client.post(
        "/api/health/snapshots",
        json=paired,
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert accepted.status_code == 200

    connection_test = client.post(
        "/api/health/snapshots/test",
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert connection_test.status_code == 200
    assert connection_test.headers["cache-control"] == "no-store"
    assert connection_test.json()["status"] == "ready"

    # Pairing values are available only through the already-authenticated PWA
    # route, never through broad state or the health test response.
    setup = client.get(
        "/api/health/setup",
        headers={**remote_base, "authorization": "Bearer phone-app-secret"},
    )
    assert setup.status_code == 200
    assert setup.headers["cache-control"] == "no-store"
    assert setup.json()["capture_token"] == "health-capture-secret"
    assert setup.json()["progress_path"] == "/api/health/snapshots/progress"
    assert "health-capture-secret" not in client.get(
        "/api/state",
        headers={**remote_base, "authorization": "Bearer phone-app-secret"},
    ).text


def test_shortcut_activity_progress_is_scoped_replay_safe_and_private(client, monkeypatch):
    """A two-field Shortcut summary reaches the canonical partial-data path."""
    monkeypatch.setattr(main, "API_TOKEN", "phone-app-secret")
    monkeypatch.setattr(main, "HEALTH_INGEST_TOKEN", "health-capture-secret")
    monkeypatch.setattr(main, "HEALTH_INGEST_INSTALLATION_ID", "paired-iphone-1")
    remote_base = {"x-forwarded-for": "100.64.0.9"}
    body = {"capture_id": "1f6e28b8-883e-4f5f-9a1f-7674b2678ecf", "steps": 4011}

    # The broad PWA credential must remain useless at the Shortcut-only route.
    broad = client.post(
        "/api/health/snapshots/progress",
        json=body,
        headers={**remote_base, "authorization": "Bearer phone-app-secret"},
    )
    assert broad.status_code == 401
    assert broad.headers["cache-control"] == "no-store"

    accepted = client.post(
        "/api/health/snapshots/progress",
        json=body,
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "no-store"
    assert accepted.json() == {
        "status": "accepted",
        "source_key": "apple_health_shortcuts",
        "capture_kind": "activity_progress",
        "affected_days": [_central_day()],
        "metrics": ["steps"],
    }
    assert "4011" not in accepted.text

    today = client.get("/api/health/today")
    assert today.status_code == 200
    assert today.json()["steps"] == 4011
    assert today.json()["activity_finality"] == "partial"

    # Reusing a run ID is a transport retry, not a second step measurement.
    replay = client.post(
        "/api/health/snapshots/progress",
        json=body,
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "replayed"

    collision = client.post(
        "/api/health/snapshots/progress",
        json={**body, "steps": 4012},
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert collision.status_code == 409
    assert collision.headers["cache-control"] == "no-store"
    assert "4012" not in collision.text

    invalid = client.post(
        "/api/health/snapshots/progress",
        json={"capture_id": "invalid-step", "steps": 150001},
        headers={**remote_base, "authorization": "Bearer health-capture-secret"},
    )
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "no-store"
    assert "150001" not in invalid.text


def test_final_revision_wins_and_partial_does_not_replace_final(client):
    stamp = _stamp()
    final = _snapshot("final-1", [
        _measurement("steps", 3400, record_key="steps-final-v1", stamp=stamp),
    ], captured_at=stamp)
    assert client.post("/api/health/snapshots", json=final).status_code == 200

    partial_stamp = _stamp(1)
    partial = _snapshot("progress-1", [
        _measurement("steps", 4100, record_key="steps-progress", finality="partial", stamp=partial_stamp),
    ], capture_kind="activity_progress", captured_at=partial_stamp)
    assert client.post("/api/health/snapshots", json=partial).status_code == 200
    assert _health_row()["steps"] == 3400

    revised_stamp = _stamp(2)
    revised = _snapshot("final-2", [
        _measurement("steps", 6321, record_key="steps-final-v2", stamp=revised_stamp),
    ], captured_at=revised_stamp)
    assert client.post("/api/health/snapshots", json=revised).status_code == 200
    assert _health_row()["steps"] == 6321


def test_sensor_snapshot_preserves_manual_energy_and_does_not_grow_garden(client):
    assert client.post("/api/wellness", json={"energy": 4}).status_code == 200
    stamp = _stamp()
    payload = _snapshot("sleep-1", [
        _measurement("sleep_hours", 7.5, record_key="sleep-day-v1", stamp=stamp),
    ], capture_kind="sleep_final", captured_at=stamp)
    assert client.post("/api/health/snapshots", json=payload).status_code == 200
    row = _health_row()
    assert row["energy"] == 4
    assert row["sleep_hours"] == 7.5

    conn = db.connect()
    try:
        # Energy is an intentional manual check-in. A source snapshot itself
        # adds no extra Garden progress or spark.
        before = garden.garden_state(conn)
        assert before["alive_days"] == 1
        assert before["spark"] is False
    finally:
        conn.close()


def test_health_views_are_no_store_and_broad_state_has_no_sensor_values(client):
    stamp = _stamp()
    payload = _snapshot("activity-views", [
        _measurement("steps", 8123, record_key="steps-view-v1", stamp=stamp),
    ], captured_at=stamp)
    assert client.post("/api/health/snapshots", json=payload).status_code == 200

    status = client.get("/api/health/status")
    today = client.get("/api/health/today")
    history = client.get("/api/health/history?range=7")
    state = client.get("/api/state")
    assert all(response.headers["cache-control"] == "no-store" for response in (status, today, history))
    assert today.json()["steps"] == 8123
    assert "measurements" not in today.json()
    assert "snapshot_id" not in json.dumps(today.json())
    assert state.status_code == 200
    assert "wellness_today" not in state.json()
    assert "steps" not in state.json()["health_status"]
    assert "montage" not in state.json()


def test_invalid_future_snapshot_is_rejected_without_health_rows(client):
    future = _stamp(3600)
    payload = _snapshot("future-1", [
        _measurement("steps", 42, record_key="steps-future", stamp=future),
    ], captured_at=future)
    response = client.post("/api/health/snapshots", json=payload)
    assert response.status_code == 422
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_snapshots").fetchone()[0] == 0
    finally:
        conn.close()


def test_health_ai_requires_explicit_consent_and_uses_private_output(client):
    conn = db.connect()
    token = runner._RUN_CONTEXT.set({
        **runner._new_run_state(),
        "role": "physician",
        "conn": conn,
        "role_domains": ["health"],
    })
    try:
        assert db.health_ai_sharing_enabled(conn) is False
        assert "read_health" not in runner.agent_allowlist("physician", conn)
        blocked = asyncio.run(runner.read_health.handler({}))
        assert blocked.get("is_error") is True

        prefs = db.set_health_ai_sharing(conn, True, "v35-health-ai-1")
        assert prefs["share_health_with_ai"] == 1
        allowed = runner.agent_allowlist("physician", conn)
        assert {"read_health", "write_health_insight"} <= allowed
        assert not (allowed & runner.HEALTH_GENERIC_WRITERS)
        # act_gym_confirm is coach's Ring 1 grant alone (SPEC-v37 §4.4);
        # physician has none, and consent turning on must never hand it one
        # via the shared HEALTH_AGENT_ROLES restore path.
        assert "act_gym_confirm" not in allowed
        assert "read_health" not in runner.agent_allowlist("chief", conn)
        assert runner.chat_write_allow("physician") == set()

        saved = asyncio.run(runner.write_health_insight.handler({
            "kind": "pattern", "body": "Sleep timing was steady across 7 days.", "sample_size": 7,
        }))
        assert not saved.get("is_error")
        assert conn.execute("SELECT COUNT(*) FROM health_insights").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0
    finally:
        runner._RUN_CONTEXT.reset(token)
        conn.close()


def test_coach_gets_gym_confirm_only_once_health_sharing_is_on(client):
    """SPEC-v37 §4.4: coach's one Ring 1 grant is gym.confirm, and like every
    other health write it stays behind the consent wall until Ian turns
    sharing on -- the dispatcher already skips coach entirely until then, but
    the allowlist itself must not grant it early either."""
    conn = db.connect()
    try:
        assert db.health_ai_sharing_enabled(conn) is False
        assert "act_gym_confirm" not in runner.agent_allowlist("coach", conn)

        db.set_health_ai_sharing(conn, True, "v35-health-ai-1")
        assert "act_gym_confirm" in runner.agent_allowlist("coach", conn)
    finally:
        conn.close()


def test_historic_health_artifacts_are_excluded_from_every_general_model_reader(client):
    """Old shared Coach/Physician output cannot bypass the new consent wall."""
    conn = db.connect()
    token = runner._RUN_CONTEXT.set({
        "role": "chief",
        "conn": conn,
        "brief_kind": "daily",
        "memos_written": 0,
        "health_insights_written": 0,
        "brief_written": False,
        "role_domains": ["all"],
        "interactive_read_sources": set(),
    })
    try:
        db.add_memo(conn, "physician", "sleep", "PRIVATE-SLEEP-7H-29M")
        db.add_memo(conn, "coach", "montage: legacy", "PRIVATE-TRAINING-DETAIL")
        db.add_memo(conn, "scout", "calls", "SAFE-SALES-CONTEXT")
        db.upsert_fact(
            conn,
            "health",
            "training:legacy",
            "PRIVATE-HEALTH-FACT",
            source_role="coach",
        )
        db.upsert_fact(
            conn,
            "business",
            "decision:launch",
            "SAFE-BUSINESS-FACT",
            source_role="scout",
        )

        memo_payload = asyncio.run(runner.read_memos.handler({}))
        fact_payload = asyncio.run(runner.read_facts.handler({}))
        memo_text = memo_payload["content"][0]["text"]
        fact_text = fact_payload["content"][0]["text"]
        assert "SAFE-SALES-CONTEXT" in memo_text
        assert "PRIVATE-SLEEP-7H-29M" not in memo_text
        assert "PRIVATE-TRAINING-DETAIL" not in memo_text
        assert "SAFE-BUSINESS-FACT" in fact_text
        assert "PRIVATE-HEALTH-FACT" not in fact_text

        # Turning consent on for a dedicated health role does not widen a
        # Chief's existing memo/fact access to historic health artifacts.
        db.set_health_ai_sharing(conn, True, "v35-health-ai-1")
        assert "PRIVATE-SLEEP-7H-29M" not in asyncio.run(
            runner.read_memos.handler({})
        )["content"][0]["text"]
        assert "PRIVATE-HEALTH-FACT" not in asyncio.run(
            runner.read_facts.handler({})
        )["content"][0]["text"]

        # The broad PWA state is likewise clean, while Body can deliberately
        # request its old local reflection through the no-store health route.
        broad_state = client.get("/api/state")
        private_body = client.get("/api/health/insights")
        assert "PRIVATE-SLEEP-7H-29M" not in broad_state.text
        assert "PRIVATE-TRAINING-DETAIL" not in broad_state.text
        assert "PRIVATE-HEALTH-FACT" not in broad_state.text
        assert "montage" not in broad_state.json()
        assert private_body.headers["cache-control"] == "no-store"
        assert "PRIVATE-TRAINING-DETAIL" in private_body.text
    finally:
        runner._RUN_CONTEXT.reset(token)
        conn.close()


def test_chief_prompt_omits_local_health_capacity_details(client):
    conn = db.connect()
    try:
        db.upsert_health(conn, _central_day(), sleep_hours=5.0, source="test")
        db.add_memo(conn, "physician", "sleep", "PRIVATE-SLEEP-PROMPT")
        db.set_health_ai_sharing(conn, True, "v35-health-ai-1")

        prompt = runner.build_user_prompt("chief", "daily", conn)
        assert "SLEEP DEBT" not in prompt
        assert "PRIVATE-SLEEP-PROMPT" not in prompt
        assert "last night 5.0h" not in prompt
        assert "Sleep avg 5.0h" not in prompt
    finally:
        conn.close()
