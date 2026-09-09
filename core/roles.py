"""Role file loading: frontmatter + prompt body. Shared by runner and API.

A role file is `agents/roles/<id>.md` with optional `---` frontmatter:

    ---
    role: cfo
    codename: Jordan Belfort
    persona: money-obsessed wolf, permanently defanged
    active: true
    tier: daily            # daily | weekly | tripwire
    day: sun               # only for tier: weekly (mon..sun)
    domains: finance       # comma-separated; scopes read_facts
    seasons: term,break    # optional, comma-separated (SPEC-v37 6.2); absent = every season
    ---

Internal ids (the filename stem / `role:`) NEVER change, they are foreign keys
in memos/proposals history. Codename + persona are display-only.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = ROOT / "agents" / "roles"

# Canonical nightly execution order (producers -> synthesizers -> chief last).
# The dispatcher decides who actually runs each night; this is the sequence.
# SPEC-v37 3: archivist, family, publicist, infra and advisor retired --
# family's tripwire moved to steward, advisor merged into watchdog, the other
# two have no successor. Retired roles stay loadable (all_roles() appends any
# .md file not in SEQUENCE) so their history keeps rendering on the Roster.
SEQUENCE = [
    "scout", "cfo", "wealth", "physician", "coach", "steward",
    "lovebird", "watchdog", "tutor", "counsel", "chief",
]

VALID_FACT_DOMAINS = {
    "business", "finance", "health", "personal", "college", "legal", "all",
}


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split leading `---` frontmatter from the markdown body.

    maxsplit=2 keeps any `---` horizontal rules inside the body intact.
    """
    if not text.startswith("---"):
        return {}, text.strip()
    _, fm, body = text.split("---", 2)
    meta: dict = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body.strip()


def load_role(name: str) -> dict:
    """Load one role file into a dict the runner and API both consume."""
    raw, body = _parse_frontmatter((ROLES_DIR / f"{name}.md").read_text())
    domains = [d.strip() for d in (raw.get("domains", "") or "").split(",") if d.strip()]
    # SPEC-v37 6.2: absent/empty means every season (no restriction), the
    # backward-compatible default for every role file that predates seasons.
    seasons = [s.strip().lower() for s in (raw.get("seasons", "") or "").split(",") if s.strip()]
    return {
        "name": name,
        "role": raw.get("role", name),
        "codename": (raw.get("codename") or "").strip(),
        "persona": (raw.get("persona") or "").strip(),
        "tier": (raw.get("tier") or "daily").strip().lower(),
        "day": (raw.get("day") or "").strip().lower()[:3],
        "domains": domains or ["business"],
        "seasons": seasons,
        "active": str(raw.get("active", "true")).lower() != "false",
        "model": raw.get("model"),
        "prompt": body,
    }


def role_names() -> list[str]:
    return sorted(p.stem for p in ROLES_DIR.glob("*.md"))


def all_roles() -> list[dict]:
    """Every role, ordered by SEQUENCE (unknown files appended alphabetically)."""
    names = role_names()
    ordered = [n for n in SEQUENCE if n in names] + [n for n in names if n not in SEQUENCE]
    return [load_role(n) for n in ordered]
