"""SPEC-v22 one-level Partner hierarchy, semantics, and receipt contracts."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import main  # noqa: E402
from core import attention, db, partner, pillars, plan  # noqa: E402


FIXTURES = Path(__file__).parent / "fixtures" / "partner_semantics.json"
NOW = datetime(2026, 8, 17, 9, 0)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def receipt_headers(mutation_id: str | None = None) -> dict[str, str]:
    return {
        "X-ianOS-Mutation-Id": mutation_id or str(uuid4()),
        "X-ianOS-Captured-At": "2026-08-17T09:00:00.000Z",
        "X-ianOS-Effective-Date": "2026-08-17",
    }


def test_shared_semantics_fixtures():
    cases = json.loads(FIXTURES.read_text())
    for case in cases:
        rows = case["rows"]
        expected = case["expected"]
        groups = partner.group_tasks(rows)
        actual_groups = [
            {
                "parent_id": group.parent["id"],
                "child_ids": [child["id"] for child in group.children],
                "complete": partner.group_complete(group.parent, group.children),
            }
            for group in groups
        ]
        assert actual_groups == expected["groups"], case["name"]
        assert [row["id"] for row in partner.actionable_tasks(rows)] == expected["actionable_ids"], case["name"]
        assert partner.open_count(rows) == expected["open_count"], case["name"]
        nxt = partner.next_action(rows)
        assert (nxt["id"] if nxt else None) == expected["next_action_id"], case["name"]


def test_semantics_reject_active_orphan_or_second_level():
    with pytest.raises(ValueError, match="no active top-level parent"):
        partner.group_tasks([{"id": 2, "parent_id": 1, "done": False}])
    with pytest.raises(ValueError, match="no active top-level parent"):
        partner.group_tasks([
            {"id": 1, "parent_id": None, "done": False},
            {"id": 2, "parent_id": 1, "done": False},
            {"id": 3, "parent_id": 2, "done": False},
        ])


def test_legacy_migration_is_idempotent_and_archived_history_prevents_reseed(tmp_path, monkeypatch):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        """CREATE TABLE partner_tasks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               title TEXT NOT NULL,
               notes TEXT NOT NULL DEFAULT '',
               done INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
               completed_at TEXT
           )"""
    )
    legacy.execute("INSERT INTO partner_tasks (title) VALUES ('Historical row')")
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(db, "DB_PATH", path)

    first = db.connect()
    columns = {row[1] for row in first.execute("PRAGMA table_info(partner_tasks)")}
    assert {"parent_id", "deleted_at", "deleted_batch_id"} <= columns
    assert db.all_partner_tasks(first)[0]["parent_id"] is None
    db.archive_partner_task(first, 1, "legacy-archive")
    first.close()

    second = db.connect()  # reruns SCHEMA + every migration safely
    try:
        indexes = {row[1] for row in second.execute("PRAGMA index_list(partner_tasks)")}
        assert "idx_partner_active_parent_done" in indexes
        assert db.all_partner_tasks(second) == []
        assert second.execute("SELECT COUNT(*) FROM partner_tasks").fetchone()[0] == 1
    finally:
        second.close()


def test_valid_child_creation_and_hierarchy_rejections(conn):
    parent = db.add_partner_task(conn, "Plan the date")
    child = db.add_partner_task(conn, "Choose a restaurant", parent_id=parent["id"])
    assert child["parent_id"] == parent["id"]

    with pytest.raises(db.PartnerHierarchyConflict, match="cannot have children"):
        db.add_partner_task(conn, "Nested step", parent_id=child["id"])
    with pytest.raises(db.PartnerTaskNotFound, match="parent task not found"):
        db.add_partner_task(conn, "Missing parent", parent_id=999_999)

    next_id = conn.execute("SELECT seq + 1 FROM sqlite_sequence WHERE name='partner_tasks'").fetchone()[0]
    with pytest.raises(db.PartnerHierarchyConflict, match="parent itself"):
        db.add_partner_task(conn, "Self parent", parent_id=next_id)

    db.archive_partner_task(conn, parent["id"], "parent-gone")
    with pytest.raises(db.PartnerTaskNotFound, match="parent task not found"):
        db.add_partner_task(conn, "Archived parent", parent_id=parent["id"])


def test_parent_id_is_immutable_and_patch_reads_active_rows_only(conn):
    parent = db.add_partner_task(conn, "Parent")
    child = db.add_partner_task(conn, "Child", parent_id=parent["id"])
    other = db.add_partner_task(conn, "Other")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE partner_tasks SET parent_id = ? WHERE id = ?",
            (other["id"], child["id"]),
        )
    conn.rollback()

    db.archive_partner_task(conn, child["id"], "child-gone")
    assert db.update_partner_task(conn, child["id"], title="Changed while hidden") is None
    hidden = conn.execute("SELECT title FROM partner_tasks WHERE id = ?", (child["id"],)).fetchone()
    assert hidden["title"] == "Child"


def test_active_read_keeps_checked_parent_adjacent_to_open_child(conn):
    parent = db.add_partner_task(conn, "Parent")
    child = db.add_partner_task(conn, "Open child", parent_id=parent["id"])
    later = db.add_partner_task(conn, "Later root")
    db.update_partner_task(conn, parent["id"], done=True)

    ids = [row["id"] for row in db.all_partner_tasks(conn)]
    assert ids.index(child["id"]) == ids.index(parent["id"]) + 1
    assert ids.index(child["id"]) < ids.index(later["id"])


def test_archive_parent_stamps_only_active_subtree_and_restore_preserves_rows(conn):
    parent = db.add_partner_task(conn, "Plan date")
    old_child = db.add_partner_task(conn, "Old hidden step", parent_id=parent["id"])
    live_child = db.add_partner_task(conn, "Live step", parent_id=parent["id"])
    db.update_partner_task(conn, live_child["id"], done=True)
    before = dict(conn.execute(
        "SELECT id, parent_id, done, created_at, completed_at FROM partner_tasks WHERE id = ?",
        (live_child["id"],),
    ).fetchone())

    db.archive_partner_task(conn, old_child["id"], "older-child-batch")
    result = db.archive_partner_task(conn, parent["id"], "parent-batch")
    assert result["archived_ids"] == [parent["id"], live_child["id"]]
    active_ids = {row["id"] for row in db.all_partner_tasks(conn)}
    assert active_ids.isdisjoint({parent["id"], old_child["id"], live_child["id"]})
    batches = {
        row["id"]: row["deleted_batch_id"]
        for row in conn.execute(
            "SELECT id, deleted_batch_id FROM partner_tasks WHERE id IN (?, ?, ?)",
            (parent["id"], old_child["id"], live_child["id"]),
        )
    }
    assert batches == {
        parent["id"]: "parent-batch",
        old_child["id"]: "older-child-batch",
        live_child["id"]: "parent-batch",
    }

    restored = db.restore_partner_archive(conn, "parent-batch")
    assert [row["id"] for row in restored] == [parent["id"], live_child["id"]]
    after = dict(conn.execute(
        "SELECT id, parent_id, done, created_at, completed_at FROM partner_tasks WHERE id = ?",
        (live_child["id"],),
    ).fetchone())
    assert after == before
    assert conn.execute(
        "SELECT deleted_at FROM partner_tasks WHERE id = ?", (old_child["id"],)
    ).fetchone()[0] is not None


def test_child_restore_waits_for_archived_parent(conn):
    parent = db.add_partner_task(conn, "Parent")
    child = db.add_partner_task(conn, "Child", parent_id=parent["id"])
    db.archive_partner_task(conn, child["id"], "child-batch")
    db.archive_partner_task(conn, parent["id"], "parent-batch")

    with pytest.raises(db.PartnerHierarchyConflict, match="parent outcome"):
        db.restore_partner_archive(conn, "child-batch")
    assert conn.execute(
        "SELECT deleted_batch_id FROM partner_tasks WHERE id = ?", (child["id"],)
    ).fetchone()[0] == "child-batch"

    db.restore_partner_archive(conn, "parent-batch")
    restored = db.restore_partner_archive(conn, "child-batch")
    assert [row["id"] for row in restored] == [child["id"]]


def test_api_hierarchy_status_codes_and_validation_leave_no_receipts(client):
    parent = client.post("/api/partner-tasks", json={"title": "Parent"}).json()
    child = client.post(
        "/api/partner-tasks", json={"title": "Child", "parent_id": parent["id"]}
    ).json()

    nested = client.post(
        "/api/partner-tasks",
        json={"title": "Nested", "parent_id": child["id"]},
        headers=receipt_headers(),
    )
    missing = client.post(
        "/api/partner-tasks",
        json={"title": "Missing", "parent_id": 999_999},
        headers=receipt_headers(),
    )
    reparent = client.patch(
        f"/api/partner-tasks/{child['id']}",
        json={"parent_id": None},
        headers=receipt_headers(),
    )
    assert nested.status_code == 409
    assert missing.status_code == 404
    assert reparent.status_code == 409

    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_api_create_archive_restore_replay_is_exactly_once(client):
    parent_headers = receipt_headers()
    parent_body = {"title": "Plan the date", "notes": "Friday"}
    parent = client.post("/api/partner-tasks", json=parent_body, headers=parent_headers)
    assert client.post(
        "/api/partner-tasks", json=parent_body, headers=parent_headers
    ).headers["X-ianOS-Replayed"] == "1"
    parent_row = parent.json()

    child_headers = receipt_headers()
    child_body = {"title": "Book the table", "parent_id": parent_row["id"]}
    child = client.post("/api/partner-tasks", json=child_body, headers=child_headers)
    assert child.status_code == 200
    assert client.post(
        "/api/partner-tasks", json=child_body, headers=child_headers
    ).headers["X-ianOS-Replayed"] == "1"

    archive_headers = receipt_headers()
    archived = client.delete(
        f"/api/partner-tasks/{parent_row['id']}", headers=archive_headers,
    )
    archive_replay = client.delete(
        f"/api/partner-tasks/{parent_row['id']}", headers=archive_headers,
    )
    assert archived.json() == {
        "ok": True,
        "archive_batch_id": archive_headers["X-ianOS-Mutation-Id"],
        "archived_ids": [parent_row["id"], child.json()["id"]],
    }
    assert archive_replay.json() == archived.json()
    assert archive_replay.headers["X-ianOS-Replayed"] == "1"

    restore_headers = receipt_headers()
    restored = client.post(
        f"/api/partner-tasks/archive/{archived.json()['archive_batch_id']}/restore",
        json={},
        headers=restore_headers,
    )
    restore_replay = client.post(
        f"/api/partner-tasks/archive/{archived.json()['archive_batch_id']}/restore",
        json={},
        headers=restore_headers,
    )
    assert [row["id"] for row in restored.json()["restored"]] == archived.json()["archived_ids"]
    assert restore_replay.json() == restored.json()
    assert restore_replay.headers["X-ianOS-Replayed"] == "1"

    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic='partner task added'").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic='partner task removed'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic='partner task restored'").fetchone()[0] == 1
    finally:
        conn.close()


def test_archive_and_restore_failures_are_atomic_with_receipts(client, monkeypatch):
    task = client.post("/api/partner-tasks", json={"title": "Keep me"}).json()

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(db, "store_mutation_receipt", fail_receipt)
    no_raise = TestClient(main.app, raise_server_exceptions=False)
    failed = no_raise.delete(
        f"/api/partner-tasks/{task['id']}", headers=receipt_headers(),
    )
    assert failed.status_code == 500

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT deleted_at FROM partner_tasks WHERE id = ?", (task["id"],)
        ).fetchone()
        assert row["deleted_at"] is None
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic='partner task removed'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()

    archived = client.delete(f"/api/partner-tasks/{task['id']}").json()
    failed_restore = no_raise.post(
        f"/api/partner-tasks/archive/{archived['archive_batch_id']}/restore",
        json={},
        headers=receipt_headers(),
    )
    assert failed_restore.status_code == 500
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT deleted_at FROM partner_tasks WHERE id = ?", (task["id"],)
        ).fetchone()
        assert row["deleted_at"] is not None
        assert conn.execute("SELECT COUNT(*) FROM memos WHERE topic='partner task restored'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_headerless_compatibility_still_commits_domain_write_and_memo_atomically(client, monkeypatch):
    def fail_memo(*_args, **_kwargs):
        raise RuntimeError("memo write failed")

    monkeypatch.setattr(db, "add_memo", fail_memo)
    no_raise = TestClient(main.app, raise_server_exceptions=False)
    response = no_raise.post("/api/partner-tasks", json={"title": "Must roll back"})
    assert response.status_code == 500

    conn = db.connect()
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM partner_tasks WHERE title='Must roll back'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_stale_patch_and_new_archive_target_active_rows_only(client):
    task = client.post("/api/partner-tasks", json={"title": "Archive me"}).json()
    archived = client.delete(f"/api/partner-tasks/{task['id']}")
    assert archived.status_code == 200

    patch = client.patch(
        f"/api/partner-tasks/{task['id']}",
        json={"title": "Changed while hidden"},
        headers=receipt_headers(),
    )
    second_archive = client.delete(
        f"/api/partner-tasks/{task['id']}", headers=receipt_headers(),
    )
    assert patch.status_code == 404
    assert second_archive.status_code == 404

    conn = db.connect()
    try:
        assert conn.execute(
            "SELECT title FROM partner_tasks WHERE id = ?", (task["id"],)
        ).fetchone()[0] == "Archive me"
        assert conn.execute("SELECT COUNT(*) FROM mutation_receipts").fetchone()[0] == 0
    finally:
        conn.close()


def test_state_pillar_plan_and_attention_share_actionable_meaning(client):
    conn = db.connect()
    try:
        for row in db.all_partner_tasks(conn):
            db.update_partner_task(conn, row["id"], done=True)
        parent = db.add_partner_task(conn, "Outcome")
        child = db.add_partner_task(conn, "Actual next step", parent_id=parent["id"])
        db.update_partner_task(conn, parent["id"], done=True)
        rows = db.all_partner_tasks(conn)

        focus = db.current_focus(conn)
        computed = pillars.compute_pillars(
            conn, [], focus, rows, {"portfolio": None}, db.gym_streak_state(conn),
        )
        assert computed["partner"]["detail"] == "1 open"
        assert computed["partner"]["status"] == "ON TRACK"
        assert "partner" in [item["key"] for item in plan.suggest_blocks(conn, "2026-08-17")]

        preloaded = {
            "active_promises": [], "due_callbacks": [], "plan_blocks": [],
            "goals": [], "pending_proposals": [], "gym": {"confirmed_today": True},
            "lead_queue": [], "activity": {"audit_calls": 20, "follow_ups": 10},
            "partner_tasks": rows, "stale_domains": [],
        }
        candidate = next(
            item for item in attention.collect_candidates(conn, NOW, preloaded=preloaded)
            if item.kind == "partner_action"
        )
        assert candidate.ref_id == child["id"]
    finally:
        conn.close()

    state = client.get("/api/state").json()
    assert state["partner_summary"] == {"open_count": 1, "next_task_id": child["id"]}
