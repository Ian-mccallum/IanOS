"""SPEC-v41 §4: Life's daily to-do. Rolling is a read, never a nightly write;
deletes are soft and restorable; the five HTTP endpoints write no memo (a
to-do is below the memo board's noise floor).
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from api import main
from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def test_tasks_roll_by_read_not_write(conn):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    row = db.create_task(conn, "Renew parking", due_date=yesterday)
    before = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone())

    open_rows = db.tasks_today(conn, date.today().isoformat())
    assert any(r["id"] == row["id"] for r in open_rows)

    after = dict(conn.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone())
    assert before == after


def test_task_needs_a_title(conn):
    with pytest.raises(ValueError):
        db.create_task(conn, "   ")


def test_done_task_leaves_today(conn):
    row = db.create_task(conn, "Call the dentist")
    db.set_task_done(conn, row["id"], True)
    assert row["id"] not in {r["id"] for r in db.tasks_today(conn, date.today().isoformat())}


def test_delete_is_soft_and_restorable(conn):
    row = db.create_task(conn, "Pack lunch")
    db.delete_task(conn, row["id"])
    assert db.get_task(conn, row["id"]) is None
    db.restore_task(conn, row["id"])
    assert db.get_task(conn, row["id"]) is not None


def test_no_task_memos(client, conn):
    before = conn.execute("SELECT COUNT(*) n FROM memos").fetchone()["n"]
    r = client.post("/api/tasks", json={"title": "Renew parking"})
    task_id = r.json()["id"]
    client.post(f"/api/tasks/{task_id}/done", json={})
    client.delete(f"/api/tasks/{task_id}")
    after = conn.execute("SELECT COUNT(*) n FROM memos").fetchone()["n"]
    assert after == before


def test_goal_draft_source_is_the_only_extra_source_the_api_accepts(client):
    r = client.post("/api/tasks", json={"title": "x", "source": "agent"})
    assert r.status_code == 422
    r = client.post("/api/tasks", json={"title": "x", "source": "goal_draft"})
    assert r.status_code == 200
