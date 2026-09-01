"""Load ianOS/.env into os.environ (gitignored). Shared by API, agents, ingest."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _clean_value(v: str) -> str:
    """Strip a trailing inline `# comment` (hash preceded by whitespace, outside
    quotes) and surrounding quotes. Prevents pasted example comments from being
    glued onto a value, e.g. `ICLOUD_APP_PASSWORD=abcd-...   # note`."""
    quote = None
    for i, ch in enumerate(v):
        if ch in ("'", '"') and quote is None:
            quote = ch
        elif ch == quote:
            quote = None
        elif ch == "#" and quote is None and i > 0 and v[i - 1] in " \t":
            v = v[:i]
            break
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1]
    return v


def load_dotenv() -> None:
    envfile = ROOT / ".env"
    if not envfile.exists():
        return
    for line in envfile.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), _clean_value(v))


def write_env(key: str, value: str) -> None:
    """Persist one local secret without ever printing it.

    `.env` is the existing single-user secret store for connector credentials.
    Keys are deliberately constrained so an API client cannot rewrite arbitrary
    environment entries through a connector setup endpoint.
    """
    if not key or not key.replace("_", "").isalnum() or "=" in value or "\n" in value:
        raise ValueError("invalid environment entry")
    envfile = ROOT / ".env"
    lines = envfile.read_text().splitlines() if envfile.exists() else []
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{prefix}{value}"
            break
    else:
        lines.append(f"{prefix}{value}")
    envfile.write_text("\n".join(lines) + "\n")
    os.environ[key] = value
