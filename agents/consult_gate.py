"""SPEC-v37 Plane B runtime capability wall (agents/consult_gate.py).

> Law A2 -- One gate, in code. Every Plane B tool call passes through
> consult_gate() before it executes. Prompt text is never the boundary. A
> tool that is not explicitly allowed is denied, and the denial reason is
> returned to the model so it can adapt.

> Law A3 -- The database is never a file. No plane, no agent, no skill may
> open data/ianos.db as a file. Every read goes through an ianos MCP tool,
> because that is where domain scoping, the health wall, the journal wall
> and the pipeline read-only rule live.

This module is pure and stateless: it takes the finished, already-computed
`ianos_allow` set for a chat turn/role (built elsewhere via the existing
`chat_allow()` / `chat_write_allow()` machinery in `agents/runner.py`) and
returns two closures wiring the same decision logic into both SDK layers
Law A2 asks for -- `can_use_tool` and a `PreToolUse` hook -- "because a
capability wall with one implementation is a capability wall with one bug."

Deny by default. Nothing in here trusts the model's account of its own
intent (Law A4's sibling idea, applied here to tool calls instead of acts).
"""

from __future__ import annotations

import re
from pathlib import Path

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

ROOT = Path(__file__).resolve().parent.parent

# SPEC-v37 S2.4: "add_dirs = [ROOT, ROOT/"data"/"consult"]. Read is
# repo-wide; write is data/consult/** only."
CONSULT_ROOT = (ROOT / "data" / "consult").resolve()
CONSULT_SCRATCH = CONSULT_ROOT / "scratch"   # agent working files, pruned at 14 days
CONSULT_OUT = CONSULT_ROOT / "out"           # things Ian asked for: a CSV, a draft, a chart

# SPEC-v37 S2.5: absolute read denials, both planes, regardless of who asks.
_ENV_ROOT = ROOT
_JOURNAL_DIR = (ROOT / "data" / "journal").resolve()
_SCHOOL_DIR = (ROOT / "data" / "school").resolve()
_DB_DIR = (ROOT / "data").resolve()
_DB_BASENAME = "ianos.db"

# SPEC-v37 S2.6, copied verbatim from the spec's code block. Matched on the
# tool's bare name after the mcp__<server>__ prefix is stripped, so a
# reconnected server with a new id cannot smuggle a writer through.
CONNECTOR_WRITE_TOOLS = frozenset({
    # Gmail
    "send_message", "reply", "forward", "create_draft", "update_draft",
    "trash_message", "trash_thread", "untrash_message", "untrash_thread",
    "label_message", "label_thread", "unlabel_message", "unlabel_thread",
    "update_message_labels", "create_label", "update_label", "delete_label",
    "mark_message_spam", "mark_thread_spam",
    "unmark_message_spam", "unmark_thread_spam",
    "apply_sensitive_message_label", "apply_sensitive_thread_label",
    # Drive
    "create_file", "update_file", "copy_file", "trash_file",
    "share_file", "get_file_permissions",
})

# Built-ins that are never security-sensitive the way Read/Write/Bash/
# connectors are: Grep/Glob only report matches within whatever the Read
# gate already scopes, Skill loads packaged instructions, WebSearch is
# external-only with no local file access.
_ALWAYS_ALLOWED_BUILTINS = frozenset({"Grep", "Glob", "Skill", "WebSearch"})

# S2.4: Write/Edit/NotebookEdit share the same workspace-only path gate.
_PATH_WRITE_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})

# S2.6: "the allowlist is *_get_*, *_list_*, *_search_*, read_* and nothing
# else." A leading get_/list_/search_ is covered by the corresponding
# "*_x_*" pattern too, since '*' matches the empty string.
def _is_read_only_bare_name(bare: str) -> bool:
    return bool(
        bare.startswith("get_") or "_get_" in bare
        or bare.startswith("list_") or "_list_" in bare
        or bare.startswith("search_") or "_search_" in bare
        or bare.startswith("read_")
    )


# Pragmatic textual denylist for Bash, not a shell parser -- same style as
# core/school.py's quote_is_readable(). This gate's job is the path/secrets
# layer; network sandboxing for Bash is the caller's SandboxSettings (S2.2).
_BASH_SECRET_FRAGMENTS = (
    ".env",
    "data/journal",
    "data/school",
    "data/ianos.db",
)
_BASH_NETWORK_PATTERN = re.compile(
    r"\b(sudo|curl|wget|nc|netcat|ssh|scp|telnet)\b", re.IGNORECASE
)


def _split_mcp_tool(tool_name: str) -> tuple[str, str]:
    """Return (server_id, bare_name) for an mcp__<server>__<tool> name.

    Split on the first two '__' only, so a server id containing further
    underscores (a Drive/Gmail connector's generated id) does not truncate
    the bare tool name.
    """
    parts = tool_name.split("__", 2)
    if len(parts) == 3:
        return parts[1], parts[2]
    if len(parts) == 2:
        return parts[1], ""
    return "", tool_name


def _resolve(raw: object, base: Path = ROOT) -> Path | None:
    """Resolve a tool_input path argument against `base`, normalizing '..'
    and symlinks. Returns None rather than raising on anything unresolvable.
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = base / p
        return p.resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_env_file(path: Path) -> bool:
    # ".env" and ".env.*" at repo root only (S2.5).
    return path.parent == _ENV_ROOT and (path.name == ".env" or path.name.startswith(".env."))


def _is_db_file(path: Path) -> bool:
    # data/ianos.db, -wal and -shm companions (S2.5, Law A3).
    return path.parent == _DB_DIR and path.name.startswith(_DB_BASENAME)


def _read_gate(tool_input: dict) -> PermissionResultAllow | PermissionResultDeny:
    raw = tool_input.get("file_path")
    path = _resolve(raw)
    if path is None:
        return PermissionResultDeny(message="Read requires a resolvable file_path.")
    if _is_env_file(path):
        return PermissionResultDeny(
            message="Live credentials (Plaid, SnapTrade, iCloud, restic, B2, push, "
                    "OAuth) are never readable in a consult."
        )
    if _is_within(path, _JOURNAL_DIR):
        return PermissionResultDeny(
            message="The journal is a privacy wall (SPEC-v8/v11). No agent has ever "
                    "read it and none will."
        )
    if _is_within(path, _SCHOOL_DIR):
        return PermissionResultDeny(
            message="Private course files (SPEC-v36) are not agent-readable."
        )
    if _is_db_file(path):
        return PermissionResultDeny(
            message="The database is reachable only through ianos MCP tools."
        )
    if not _is_within(path, ROOT):
        return PermissionResultDeny(
            message="That path is outside the repo and not reachable in a consult."
        )
    return PermissionResultAllow()


def _path_gate(tool_input: dict) -> PermissionResultAllow | PermissionResultDeny:
    # NotebookEdit conventionally carries notebook_path; Write/Edit carry
    # file_path. Check both rather than assuming one key.
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    path = _resolve(raw)
    if path is None:
        return PermissionResultDeny(message="That path could not be resolved.")
    if not _is_within(path, CONSULT_ROOT):
        return PermissionResultDeny(
            message="Writes are only allowed inside data/consult/ (the consult "
                    "workspace)."
        )
    return PermissionResultAllow()


def _bash_gate(tool_input: dict) -> PermissionResultAllow | PermissionResultDeny:
    command = tool_input.get("command")
    if not command or not isinstance(command, str):
        return PermissionResultDeny(message="Bash requires a command.")
    lowered = command.lower()
    for fragment in _BASH_SECRET_FRAGMENTS:
        if fragment in lowered:
            return PermissionResultDeny(
                message="That command reaches a path this gate blocks: credentials, "
                        "the journal, school files, or the database."
            )
    if _BASH_NETWORK_PATTERN.search(command):
        return PermissionResultDeny(
            message="That command reaches outside the sandbox (network access or "
                    "privilege escalation) and consult_gate blocks it directly."
        )
    return PermissionResultAllow()


def _decide(
    tool_name: str, tool_input: dict, ianos_allow: frozenset[str]
) -> PermissionResultAllow | PermissionResultDeny:
    """The one decision function. Both `consult_gate` and the PreToolUse
    hook translate this into their own return shape -- never duplicate the
    branching (Law A2's "one gate, in code").
    """
    tool_input = tool_input or {}

    if tool_name in _ALWAYS_ALLOWED_BUILTINS:
        return PermissionResultAllow()

    if tool_name.startswith("mcp__"):
        server, bare = _split_mcp_tool(tool_name)
        if server == "ianos":
            if bare in ianos_allow:
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=f"{bare} is not allowed for this role in a consult."
            )
        # A connected MCP server that isn't ianos (Gmail, Calendar, Drive, ...).
        if bare in CONNECTOR_WRITE_TOOLS:
            return PermissionResultDeny(message="ianOS never writes to your accounts.")
        if _is_read_only_bare_name(bare):
            return PermissionResultAllow()
        return PermissionResultDeny(
            message=f"{bare or tool_name} is a new connector tool; only get_/list_/"
                    "search_/read_ tools are allowed in a consult."
        )

    if tool_name in _PATH_WRITE_TOOLS:
        return _path_gate(tool_input)

    if tool_name == "Read":
        return _read_gate(tool_input)

    if tool_name == "Bash":
        return _bash_gate(tool_input)

    return PermissionResultDeny(message=f"{tool_name} is not available in a consult.")


def make_consult_gate(*, ianos_allow):
    """Factory for `ClaudeAgentOptions.can_use_tool`.

    `ianos_allow` is the already-computed set of bare `ianos` MCP tool
    names allowed for this chat turn/role (the caller derives it via the
    existing `chat_allow()`/`chat_write_allow()` machinery in
    `agents/runner.py`). Returns an async closure matching the SDK's
    `can_use_tool(tool_name, tool_input, ctx)` signature.
    """
    allow = frozenset(ianos_allow)

    async def consult_gate(tool_name, tool_input, ctx):
        return _decide(tool_name, tool_input, allow)

    return consult_gate


def make_consult_pretooluse_hook(*, ianos_allow):
    """Factory for the second-layer `PreToolUse` hook (Law A2: "a capability
    wall with one implementation is a capability wall with one bug").

    Runs the identical `_decide` predicate `make_consult_gate` uses and
    translates the result into the hook's TypedDict return shape, rather
    than re-implementing the branching.
    """
    allow = frozenset(ianos_allow)

    async def consult_pretooluse_hook(input, tool_use_id, ctx):
        tool_name = input.get("tool_name", "")
        tool_input = input.get("tool_input") or {}
        decision = _decide(tool_name, tool_input, allow)
        if isinstance(decision, PermissionResultDeny):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": decision.message,
                }
            }
        return {}

    return consult_pretooluse_hook
