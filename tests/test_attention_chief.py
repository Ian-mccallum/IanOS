"""SPEC-v21: the chief sees compiler order without gaining private sources."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import db  # noqa: E402


NOW = datetime(2026, 8, 14, 9, 0)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def test_chief_digest_preserves_compiler_order_without_private_sources(conn):
    conn.execute(
        """INSERT INTO leads (phone_norm, business_name, tier, stage, next_touch)
           VALUES ('6305550199', 'Riverbend Locksmith', 'A', 'attempted', '2026-08-14')"""
    )
    conn.execute(
        """INSERT INTO inbound_requests
           (request_id, kind, source, status, received_at, promised_by,
            email, phone, message, consent)
           VALUES ('private-request', 'demo', 'btc', 'new', '2026-08-13T10:00:00Z',
                   '2026-08-14 10:00:00', 'private@example.com', '6305550100',
                   'private message', 'private consent')"""
    )
    conn.execute(
        "INSERT INTO partner_tasks (title) VALUES ('Private Partner reservation')"
    )
    conn.commit()

    digest = runner._attention_digest(conn, NOW)

    assert "=== DETERMINISTIC ATTENTION ORDER ===" in digest
    assert "1. [due] Call Riverbend Locksmith: callback promised for Aug 14" in digest
    assert "Anchor the normal Day Command on item 1" in digest
    for private in (
        "private@example.com", "6305550100", "private message", "private consent",
        "Private Partner reservation",
    ):
        assert private not in digest


def test_chief_prompt_includes_the_compiler_digest_and_anchor_rule(conn, monkeypatch):
    monkeypatch.setattr(runner, "_attention_digest", lambda _conn: "DIGEST FROM COMPILER")

    prompt = runner.build_user_prompt("chief", "daily", conn)

    assert "DIGEST FROM COMPILER" in prompt
