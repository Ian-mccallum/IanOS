"""Pure ingest freshness policy.

No clock, environment, database, or notification access lives here. Callers
inject source status, configuration, and ``now`` so every surface applies the
same 48-hour rule.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

STALE_AFTER_HOURS = 48


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _age_hours(value: str | None, now: datetime) -> float | None:
    then = _timestamp(value)
    if then is None:
        return None
    # SQLite stores local naive time. Tests and future callers may inject aware
    # ISO timestamps, so compare like with like without guessing a timezone.
    compare_now = now
    if then.tzinfo is None and compare_now.tzinfo is not None:
        compare_now = compare_now.replace(tzinfo=None)
    elif then.tzinfo is not None and compare_now.tzinfo is None:
        then = then.replace(tzinfo=None)
    return max(0.0, (compare_now - then).total_seconds() / 3600)


def evaluate(status: Mapping | None, configured: bool, now: datetime,
             stale_after_hours: int = STALE_AFTER_HOURS) -> str:
    """Return ``disabled|never|healthy|degraded|stale`` for one source."""
    if not configured:
        return "disabled"

    row = status or {}
    success_age = _age_hours(row.get("last_success") or row.get("last_import"), now)
    attempt_age = _age_hours(row.get("last_attempt"), now)
    failures = int(row.get("consecutive_failures") or 0)

    if success_age is None:
        if attempt_age is not None and attempt_age >= stale_after_hours:
            return "stale"
        return "never"
    if success_age >= stale_after_hours:
        return "stale"

    # Ages are each normalized against the injected clock, avoiding a direct
    # comparison between legacy naive SQLite timestamps and aware ISO input.
    unresolved_attempt = bool(
        attempt_age is not None and success_age is not None
        and attempt_age < success_age
    )
    if failures > 0 or unresolved_attempt:
        return "degraded"
    return "healthy"


def evaluate_sources(statuses: Mapping[str, Mapping | None],
                     configured: Mapping[str, bool], now: datetime,
                     stale_after_hours: int = STALE_AFTER_HOURS) -> dict[str, dict]:
    """Evaluate sources and project only API-safe operational metadata."""
    result: dict[str, dict] = {}
    for source in configured:
        status = statuses.get(source) or {}
        result[source] = {
            "state": evaluate(status, configured[source], now, stale_after_hours),
            "last_success": status.get("last_success") or status.get("last_import"),
            "last_attempt": status.get("last_attempt"),
            "consecutive_failures": int(status.get("consecutive_failures") or 0),
        }
    return result
