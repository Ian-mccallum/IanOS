"""Tests for Partner task API."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from api.main import app


def test_partner_task_crud():
    client = TestClient(app)
    assert client.get("/api/health").json()["features"]["partner_tasks"] is True

    created = client.post("/api/partner-tasks", json={
        "title": "Test task",
        "notes": "pytest",
    }).json()
    assert created["title"] == "Test task"
    assert created["done"] is False

    task_id = created["id"]
    updated = client.patch(f"/api/partner-tasks/{task_id}", json={"done": True}).json()
    assert updated["done"] is True

    client.delete(f"/api/partner-tasks/{task_id}")
    state = client.get("/api/state").json()
    assert not any(t["id"] == task_id for t in state["partner_tasks"])
