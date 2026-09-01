"""SPEC-v37 §8.2 (brief date semantics) and §8.3 (voice law reaches the
brief). The audit's finding: a brief written in the evening was stamped with
the night it ran, so `briefIsToday` (`brief.date === today`) went false at
midnight and stayed false until the next evening run, essentially all day.

SAFETY: no test here lets `agents.runner.query` reach the real Anthropic API.
`write_brief` is exercised via `runner.write_brief.handler(...)` inside a
fake async generator monkeypatched onto `runner.query`, the
tests/test_day_command_live.py precedent.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import db  # noqa: E402
from core.roles import load_role  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _result(text: str):
    from claude_agent_sdk import ResultMessage
    return ResultMessage(
        subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
        num_turns=1, session_id="test", total_cost_usd=0.001, result=text,
    )


class _FrozenDatetime(datetime):
    """A `datetime` subclass so isinstance checks elsewhere still pass, with
    `.now()` pinned for a run at a chosen wall-clock time (Law A12: pin the
    clock, don't leave the window free to never fail)."""
    _frozen: datetime

    @classmethod
    def now(cls, tz=None):
        return cls._frozen


class _FrozenDate(date):
    _frozen: date

    @classmethod
    def today(cls):
        return cls._frozen


def _freeze(monkeypatch, when: datetime) -> None:
    """Pin both clocks a nightly write_brief call touches: `runner.datetime`
    (governs_date, computed from the wall-clock hour) and `db.date` (`date`,
    stamped via `db.today()`), so the test proves the two columns actually
    diverge for an evening run instead of relying on whatever day it happens
    to be run on."""
    frozen_dt = type("_FrozenDT", (_FrozenDatetime,), {"_frozen": when})
    frozen_d = type("_FrozenD", (_FrozenDate,), {"_frozen": when.date()})
    monkeypatch.setattr(runner, "datetime", frozen_dt)
    monkeypatch.setattr(db, "date", frozen_d)


# ---------------------------------------------------------- brief_governs_date

def test_brief_governs_date_before_noon_is_today():
    """A manual daytime run (e.g. `make run` at 9am catching up) governs the
    day it ran, the same day Ian is about to spend."""
    now = datetime(2026, 8, 31, 11, 59, 59)
    assert db.brief_governs_date(now) == "2026-08-31"


def test_brief_governs_date():
    """The audit's exact case: a brief written at 21:30 is tomorrow's, and
    the noon edge itself already tips over (SPEC-v37 §8.2, Law A12: pin both
    edges of the window, not just the illustrative example)."""
    assert db.brief_governs_date(datetime(2026, 8, 31, 12, 0, 0)) == "2026-09-01"
    assert db.brief_governs_date(datetime(2026, 8, 31, 21, 30, 0)) == "2026-09-01"


def test_upsert_brief_defaults_governs_date_to_brief_date(conn):
    """Callers that never heard of governs_date (every existing seed/test
    call site) keep their old, correct behaviour: it falls back to the row's
    own date instead of landing blank and permanently 'stale'."""
    db.upsert_brief(conn, "2026-08-31", "daily", "x" * 150, "old sentence")
    row = dict(conn.execute("SELECT * FROM briefs").fetchone())
    assert row["governs_date"] == "2026-08-31"


def test_write_brief_stores_the_computed_governs_date(conn, monkeypatch):
    """End to end: a chief run at 21:30 writes a brief whose `date` is today
    (when it ran) but whose `governs_date` is tomorrow (what it's for), so
    the frontend's `briefIsToday` check (which now compares `governs_date`)
    stays true through the whole day it governs instead of flipping stale at
    midnight."""
    _freeze(monkeypatch, datetime(2026, 8, 31, 21, 30, 0))

    async def fake_query(*, prompt, options):
        await runner.write_brief.handler({
            "body": "x" * 150,
            "day_command": "Call the top lead before noon.",
        })
        yield _result("brief written")

    monkeypatch.setattr(runner, "query", fake_query)
    role_meta = load_role("chief")
    result = asyncio.run(runner.run_role(role_meta, conn, "daily"))
    assert result["brief_written"] is True

    brief = db.latest_brief(conn)
    assert brief["governs_date"] == "2026-09-01"
    assert brief["date"] != brief["governs_date"]


# --------------------------------------------------------------- em dashes

def test_brief_has_no_em_dash(conn, monkeypatch):
    """Anti-slop is enforced in code inside write_brief itself, not merely
    asked for in the chief's prompt (SPEC-v37 §8.3): models emit them
    regardless. A dash between digits is a range and stays a hyphen."""
    async def fake_query(*, prompt, options):
        await runner.write_brief.handler({
            "body": ("Everything hangs on the filing—EIN, Twilio. " * 5)[:160],
            "day_command": "Call leads 2—3 before the panel—it matters.",
        })
        yield _result("brief written")

    monkeypatch.setattr(runner, "query", fake_query)
    role_meta = load_role("chief")
    result = asyncio.run(runner.run_role(role_meta, conn, "daily"))
    assert result["brief_written"] is True

    brief = db.latest_brief(conn)
    assert "—" not in brief["body"] and "–" not in brief["body"]
    assert "—" not in brief["day_command"] and "–" not in brief["day_command"]
    # A dash between digits is a range, not punctuation.
    assert "2-3" in brief["day_command"]


# ------------------------------------------------- SPEC-v37 §8.6: dispatcher line

def test_dispatch_summary_reaches_the_stored_brief_never_the_body(conn, monkeypatch):
    """Computed in run_sequence, handed to run_role, picked up by write_brief
    -- never something the model wrote or could rephrase, and kept off
    `body` on purpose (a mechanical status line mixed into the chief's own
    prose reads as slop the moment anyone notices it)."""
    async def fake_query(*, prompt, options):
        await runner.write_brief.handler({
            "body": "x" * 150,
            "day_command": "Do the thing.",
        })
        yield _result("brief written")

    monkeypatch.setattr(runner, "query", fake_query)
    role_meta = load_role("chief")
    result = asyncio.run(runner.run_role(
        role_meta, conn, "daily", dispatch_summary="5 of 10 woke; 2 off; 3 out of season.",
    ))
    assert result["brief_written"] is True
    brief = db.latest_brief(conn)
    assert brief["dispatch_summary"] == "5 of 10 woke; 2 off; 3 out of season."
    assert "5 of 10 woke" not in brief["body"]


def test_dispatch_summary_defaults_to_empty_for_every_other_role(conn, monkeypatch):
    """Only chief's write_brief call is ever handed a real dispatch_summary
    (run_sequence's own call site); every other role's RUN context defaults
    to '', matching what a memo-only run would ever want to reference."""
    token = runner._RUN_CONTEXT.set({
        "role": "scout", "conn": conn, "brief_kind": "daily",
        "memos_written": 0, "health_insights_written": 0, "brief_written": False,
        "role_domains": ["business"], "reads_this_run": set(),
    })
    try:
        assert runner.RUN.get("dispatch_summary") in (None, "")
    finally:
        runner._RUN_CONTEXT.reset(token)
