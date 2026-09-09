"""SPEC-v38: the tutor-scoped tool surface in agents/runner.py --
chat_write_learning_profile (§4) and, once Phase 3 lands, nightly topic
rotation (§5)."""

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import db, learning  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed_clarifying(conn, name="python") -> int:
    learning.ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES (?, 'clarifying', 'user')",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def test_chat_write_learning_profile_activates_topic(conn):
    # Arrange: a clarifying topic and a fake RUN context pointed at it.
    # Act: call the tool with a real profile.
    # Assert: the topic flips to active and carries the new profile text.
    topic_id = _seed_clarifying(conn)
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor"})
    try:
        out = asyncio.run(runner.chat_write_learning_profile.handler(
            {"topic_id": topic_id, "profile": "beginner, wants to drill market sizing"}
        ))
    finally:
        runner._RUN_CONTEXT.reset(token)
    assert out.get("is_error") is not True
    row = learning.get_topic(conn, topic_id)
    assert row["status"] == "active"
    assert "market sizing" in row["profile"]


def test_chat_write_learning_profile_keeps_active_topic_active(conn):
    # Arrange: an already-active topic (a follow-up profile update).
    # Act: call the tool again with a revised profile.
    # Assert: it stays active and the profile text updates.
    learning.ensure_schema(conn)
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin, profile) "
        "VALUES ('python', 'active', 'user', 'old profile')"
    ).lastrowid
    conn.commit()
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor"})
    try:
        asyncio.run(runner.chat_write_learning_profile.handler(
            {"topic_id": topic_id, "profile": "revised profile"}
        ))
    finally:
        runner._RUN_CONTEXT.reset(token)
    row = learning.get_topic(conn, topic_id)
    assert row["status"] == "active"
    assert row["profile"] == "revised profile"


def test_chat_write_learning_profile_rejects_missing_topic(conn):
    # Arrange: no topics at all.
    # Act: call the tool against a nonexistent topic id.
    # Assert: an error, no row created.
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor"})
    try:
        out = asyncio.run(runner.chat_write_learning_profile.handler(
            {"topic_id": 999, "profile": "anything"}
        ))
    finally:
        runner._RUN_CONTEXT.reset(token)
    assert out.get("is_error") is True


def test_chat_write_learning_profile_rejects_empty_profile(conn):
    # Arrange: a clarifying topic.
    # Act: call the tool with a blank profile.
    # Assert: an error, and the topic stays clarifying.
    topic_id = _seed_clarifying(conn)
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor"})
    try:
        out = asyncio.run(runner.chat_write_learning_profile.handler(
            {"topic_id": topic_id, "profile": "   "}
        ))
    finally:
        runner._RUN_CONTEXT.reset(token)
    assert out.get("is_error") is True
    assert learning.get_topic(conn, topic_id)["status"] == "clarifying"


# --------------------------------------------------------------- rotation

def test_clarifying_topic_generates_no_task(conn):
    # Arrange: one clarifying topic and one active topic.
    # Act: select tonight's topic.
    # Assert: only the active one is ever eligible.
    _seed_clarifying(conn, "ai")
    active_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('python', 'active', 'user')"
    ).lastrowid
    conn.commit()
    picked = runner._select_learning_topic(conn)
    assert picked["id"] == active_id


def test_zero_active_topics_is_not_an_error(conn):
    # Arrange: no topics at all.
    # Act: select tonight's topic.
    # Assert: None, not an exception.
    assert runner._select_learning_topic(conn) is None


def test_least_recently_featured_topic_is_picked(conn):
    # Arrange: two active topics, one featured yesterday, one never featured.
    # Act: select tonight's topic.
    # Assert: the never-featured one wins (NULL sorts first).
    learning.ensure_schema(conn)
    a = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('a', 'active', 'user')"
    ).lastrowid
    b = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('b', 'active', 'user')"
    ).lastrowid
    conn.commit()
    learning.create_or_replace_session(conn, "2026-08-30", a, "did a rep")
    picked = runner._select_learning_topic(conn)
    assert picked["id"] == b


def test_archived_topic_generates_no_task(conn):
    # Arrange: one archived topic, no active topic.
    # Act: select tonight's topic.
    # Assert: archived is never eligible either, same as clarifying.
    learning.ensure_schema(conn)
    conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('old habit', 'archived', 'user')"
    )
    conn.commit()
    assert runner._select_learning_topic(conn) is None


def test_write_learning_task_targets_tomorrow_for_the_selected_topic(conn):
    # Arrange: an active topic, RUN pointed at it as tonight's topic.
    # Act: write tonight's task through the real tool.
    # Assert: tomorrow's session row carries the new task_prompt.
    learning.ensure_schema(conn)
    topic_id = conn.execute(
        "INSERT INTO learning_topics (name, status, origin) VALUES ('python', 'active', 'user')"
    ).lastrowid
    conn.commit()
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor", "learning_topic_id": topic_id})
    try:
        out = asyncio.run(runner.write_learning_task.handler({"task_prompt": "write a decorator"}))
    finally:
        runner._RUN_CONTEXT.reset(token)
    assert out.get("is_error") is not True
    tomorrow = (date.fromisoformat(db.today()) + timedelta(days=1)).isoformat()
    row = learning.get_session(conn, tomorrow)
    assert row["task_prompt"] == "write a decorator"
    assert row["topic_id"] == topic_id


def test_write_learning_task_with_no_topic_errors(conn):
    # Arrange: RUN with no learning_topic_id set (the "nothing to rotate" night).
    # Act/Assert: writing a task errors rather than guessing a topic.
    token = runner._RUN_CONTEXT.set({"conn": conn, "role": "tutor", "learning_topic_id": None})
    try:
        out = asyncio.run(runner.write_learning_task.handler({"task_prompt": "anything"}))
    finally:
        runner._RUN_CONTEXT.reset(token)
    assert out.get("is_error") is True
