"""SPEC-v37 6.4 / Law A8: a role file carries policy, the run carries facts.
No date, quota, deadline or dollar figure may live in agents/roles/*.md or
agents/dossier.md -- current_situation() (SPEC-v37 6.1) injects them at run
time instead. This is the guard the audit's largest finding (scout.md still
saying "Quotas through Aug 9 ... ~19 weekdays left" months after it lapsed)
had no equivalent of.

Law A12: a guardrail that cannot fail proves nothing. A regex that only ever
runs against already-clean files never proves it can catch a dirty one, so
`_DATE_PATTERNS` is exercised directly against synthetic fixtures (both
literal dates AND dollar figures) before it is trusted against the real
role files and dossier.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = ROOT / "agents" / "roles"
DOSSIER = ROOT / "agents" / "dossier.md"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Two independent Law A8 violations, checked separately so a failure message
# says which one: a literal calendar date, or a literal dollar figure. Neither
# needs "is this in the past" arithmetic -- Law A8's ban is unconditional, not
# staleness-conditional; a role file naming a FUTURE date goes stale exactly
# as certainly, just later.
DATE_PATTERNS = {
    "ISO date (YYYY-MM-DD)": re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
    "month + day": re.compile(
        r"\b(?:" + "|".join(_MONTHS) + r")[a-z]*\.?\s+\d{1,2}\b"
    ),
}
DOLLAR_PATTERN = re.compile(r"\$\d")


def _active_role_files() -> list[Path]:
    """Only files an active role can actually be prompted with. A retired
    role's frozen prose (advisor.md, family.md, ...) is historical record,
    not a live prompt -- Law A8 governs what the model reads tonight."""
    from core.roles import load_role, role_names

    return [
        ROLES_DIR / f"{name}.md"
        for name in role_names()
        if load_role(name).get("active")
    ]


def _violations(text: str, patterns: dict[str, re.Pattern]) -> list[str]:
    hits = []
    for label, pattern in patterns.items():
        for match in pattern.finditer(text):
            hits.append(f"{label}: {match.group(0)!r}")
    return hits


# ------------------------------------------------------- prove the scanner works

def test_date_patterns_catch_a_synthetic_past_date():
    assert _violations("Client #1 must sign by Aug 15, 2026.", DATE_PATTERNS)
    assert _violations("school starts ~Aug 24 and collapses to 5 hrs/week", DATE_PATTERNS)
    assert _violations("Last updated: 2026-08-17.", DATE_PATTERNS)


def test_date_patterns_do_not_flag_relative_or_vague_time():
    clean = "Escalate as clocks run down: <14 days is urgent, <7 is a siren."
    assert not _violations(clean, DATE_PATTERNS)


def test_dollar_pattern_catches_a_synthetic_figure():
    assert _violations("Burn vs the $150/mo cap.", {"dollar figure": DOLLAR_PATTERN})


def test_dollar_pattern_does_not_flag_plain_prose():
    assert not _violations("Quote the cap the tool reports.", {"dollar figure": DOLLAR_PATTERN})


# ------------------------------------------------------------- the real guard

def test_no_expired_dates_in_prompts():
    """A role file or the dossier naming a date is a defect (SPEC-v37 6.4)."""
    failures = []
    for path in [*_active_role_files(), DOSSIER]:
        text = path.read_text()
        hits = _violations(text, DATE_PATTERNS)
        if hits:
            failures.append(f"{path.relative_to(ROOT)}: {hits}")
    assert not failures, "hardcoded date(s) found:\n" + "\n".join(failures)


def test_no_dollar_figures_in_prompts():
    """Same law, the other half: a dollar figure (the $150 cap, the $199/mo
    price) is exactly as prone to going stale as a date, and the audit found
    it repeated in three places before SPEC-v30's budget_categories fixed the
    cap specifically -- this closes the loop for role files generally."""
    failures = []
    for path in [*_active_role_files(), DOSSIER]:
        text = path.read_text()
        hits = _violations(text, {"dollar figure": DOLLAR_PATTERN})
        if hits:
            failures.append(f"{path.relative_to(ROOT)}: {hits}")
    assert not failures, "hardcoded dollar figure(s) found:\n" + "\n".join(failures)


def test_retired_role_files_are_not_scanned():
    """A retired role's prose is frozen history, not a live prompt (Law A8
    governs what the model reads tonight); a date in advisor.md's already-
    written body is not a new defect, and the earlier merge intentionally
    left the file's content untouched."""
    active = {p.name for p in _active_role_files()}
    assert "advisor.md" not in active
    assert "family.md" not in active
    assert "publicist.md" not in active
    assert "infra.md" not in active
    assert "archivist.md" not in active
