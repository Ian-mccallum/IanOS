"""Exactly-once browser mutations: receipt + business change share one commit."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main  # noqa: E402
from core import db  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def receipt_headers(mutation_id: str | None = None, *, day: str = "2025-12-31") -> dict[str, str]:
    return {
        "X-ianOS-Mutation-Id": mutation_id or str(uuid4()),
        "X-ianOS-Captured-At": f"{day}T23:55:14.921Z",
        "X-ianOS-Effective-Date": day,
    }


def test_activity_retry_replays_one_committed_change_and_receipt(client):
    headers = receipt_headers()
    body = {"audit_calls": 2, "notes": "called back"}

    first = client.post("/api/activity", json=body, headers=headers)
    second = client.post("/api/activity", json=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers["X-ianOS-Replayed"] == "1"
    assert second.json() == first.json()

    conn = db.connect()
    try:
        row = conn.execute("SELECT audit_calls, notes FROM activity WHERE date = ?", ("2025-12-31",)).fetchone()
        assert dict(row) == {"audit_calls": 2, "notes": "called back"}
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 1
    finally:
        conn.close()


def test_bridge_accepts_the_precise_legacy_queue_id(client):
    headers = receipt_headers("1735680000000-abc123")
    first = client.post("/api/activity", json={"audit_calls": 1}, headers=headers)
    replay = client.post("/api/activity", json={"audit_calls": 1}, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["X-ianOS-Replayed"] == "1"


def test_reused_mutation_id_never_applies_a_changed_body_or_operation(client):
    headers = receipt_headers()
    assert client.post("/api/activity", json={"audit_calls": 1}, headers=headers).status_code == 200

    changed = client.post("/api/activity", json={"audit_calls": 2}, headers=headers)
    other_operation = client.post("/api/gym/confirm", json={}, headers=headers)
    assert changed.status_code == 409
    assert other_operation.status_code == 409

    conn = db.connect()
    try:
        assert conn.execute("SELECT audit_calls FROM activity WHERE date = ?", ("2025-12-31",)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM health_daily WHERE date = ?", ("2025-12-31",)).fetchone()[0] == 0
    finally:
        conn.close()


def test_captured_day_applies_to_gym_and_wellness_not_replay_day(client):
    captured_day = "2024-12-31"
    gym = client.post("/api/gym/confirm", json={}, headers=receipt_headers(day=captured_day))
    wellness = client.post(
        "/api/wellness",
        json={"sleep_hours": 7.5, "workout_mins": 45},
        headers=receipt_headers(day=captured_day),
    )

    assert gym.status_code == 200
    assert wellness.status_code == 200
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT gym_confirmed, sleep_hours, workout_mins FROM health_daily WHERE date = ?",
            (captured_day,),
        ).fetchone()
        assert dict(row) == {"gym_confirmed": 1, "sleep_hours": 7.5, "workout_mins": 45}
    finally:
        conn.close()


def test_partner_retry_creates_one_task_and_one_memo(client):
    headers = receipt_headers()
    body = {"title": "Book the flowers", "notes": "Friday"}

    first = client.post("/api/partner-tasks", json=body, headers=headers)
    replay = client.post("/api/partner-tasks", json=body, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["X-ianOS-Replayed"] == "1"
    assert replay.json()["id"] == first.json()["id"]

    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM partner_tasks WHERE title = ?", (body["title"],)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic = 'partner task added'").fetchone()[0] == 1
    finally:
        conn.close()


def test_partner_patch_and_delete_replay_without_second_memos(client):
    task = client.post("/api/partner-tasks", json={"title": "Confirm dinner"}).json()
    patch_headers = receipt_headers()
    patched = client.patch(f"/api/partner-tasks/{task['id']}", json={"done": True}, headers=patch_headers)
    patch_replay = client.patch(f"/api/partner-tasks/{task['id']}", json={"done": True}, headers=patch_headers)
    delete_headers = receipt_headers()
    deleted = client.delete(f"/api/partner-tasks/{task['id']}", headers=delete_headers)
    delete_replay = client.delete(f"/api/partner-tasks/{task['id']}", headers=delete_headers)

    assert patched.status_code == 200
    assert patch_replay.headers["X-ianOS-Replayed"] == "1"
    assert deleted.status_code == 200
    assert delete_replay.headers["X-ianOS-Replayed"] == "1"
    conn = db.connect()
    try:
        archived = conn.execute(
            "SELECT deleted_at FROM partner_tasks WHERE id = ?", (task["id"],)
        ).fetchone()
        assert archived is not None and archived["deleted_at"] is not None
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic = 'partner task finished'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic = 'partner task removed'").fetchone()[0] == 1
    finally:
        conn.close()


def test_receipt_failure_rolls_back_the_business_change(client, monkeypatch):
    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(db, "store_mutation_receipt", fail_receipt)
    no_raise_client = TestClient(main.app, raise_server_exceptions=False)
    response = no_raise_client.post(
        "/api/activity",
        json={"audit_calls": 1},
        headers=receipt_headers(),
    )

    assert response.status_code == 500
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM activity WHERE date = ?", ("2025-12-31",)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_partial_mutation_headers_are_rejected_but_legacy_requests_still_work(client):
    partial = client.post(
        "/api/activity",
        json={"audit_calls": 1},
        headers={"X-ianOS-Mutation-Id": str(uuid4())},
    )
    legacy = client.post("/api/activity", json={"audit_calls": 1})

    assert partial.status_code == 400
    assert legacy.status_code == 200


def test_empty_or_mixed_mutation_headers_never_opt_out_of_receipts(client):
    all_empty = client.post(
        "/api/activity",
        json={"audit_calls": 1},
        headers={
            "X-ianOS-Mutation-Id": "",
            "X-ianOS-Captured-At": "",
            "X-ianOS-Effective-Date": "",
        },
    )
    mixed = client.post(
        "/api/activity",
        json={"audit_calls": 1},
        headers={
            "X-ianOS-Mutation-Id": str(uuid4()),
            "X-ianOS-Captured-At": "",
            "X-ianOS-Effective-Date": "2025-12-31",
        },
    )

    assert all_empty.status_code == 400
    assert mixed.status_code == 400
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_non_finite_wellness_is_rejected_before_a_receipt_or_health_row(client):
    headers = {**receipt_headers(), "Content-Type": "application/json"}
    response = client.post("/api/wellness", content='{"sleep_hours":1e400}', headers=headers)

    assert response.status_code == 422
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM health_daily").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()
