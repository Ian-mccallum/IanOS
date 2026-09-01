"""Source-aware daily health snapshots for SPEC-v35.

This module intentionally owns the automated-sensor write seam. Existing
manual wellness routes can keep their compatibility behavior while scheduled
Apple Health summaries enter here as replacement snapshots, never counters.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from core import db

HEALTH_TIMEZONE = "America/Chicago"
APPLE_HEALTH_SHORTCUTS = "apple_health_shortcuts"
SUPPORTED_SOURCES = frozenset({APPLE_HEALTH_SHORTCUTS})
SUPPORTED_METRICS = frozenset({"sleep_hours", "steps", "workouts", "workout_mins"})
METRIC_COLUMNS = {
    "sleep_hours": "sleep_hours",
    "steps": "steps",
    "workouts": "workouts",
    "workout_mins": "workout_mins",
}
SOURCE_LABELS = {
    APPLE_HEALTH_SHORTCUTS: "Apple Watch",
    "manual": "Manual entry",
    "legacy_import": "Imported health record",
}


class HealthSnapshotConflict(ValueError):
    """A source reused an identity for a different measurement."""


class HealthSnapshotValidationError(ValueError):
    """A caller reached the domain layer with an invalid health envelope."""


def _canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                     allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_datetime(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise HealthSnapshotValidationError(f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HealthSnapshotValidationError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise HealthSnapshotValidationError(f"{field} must include a timezone")
    return parsed


def _parse_day(value: str, field: str = "local_day") -> date:
    if not isinstance(value, str):
        raise HealthSnapshotValidationError(f"{field} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise HealthSnapshotValidationError(f"{field} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise HealthSnapshotValidationError(f"{field} must be YYYY-MM-DD")
    return parsed


def _source_label(source_key: str) -> str:
    return SOURCE_LABELS.get(source_key, source_key.replace("_", " ").title())


def _validate_measurement(item: dict[str, Any], captured: datetime) -> dict[str, Any]:
    metric = item.get("metric_key") or item.get("metric")
    if metric not in SUPPORTED_METRICS:
        raise HealthSnapshotValidationError("unsupported health metric")
    local_day = _parse_day(item.get("local_day") or item.get("day"))
    value = item.get("value_num", item.get("value"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HealthSnapshotValidationError("measurement value must be numeric")
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        raise HealthSnapshotValidationError("measurement value must be finite")

    bounds = {
        "sleep_hours": (0.0, 18.0),
        "steps": (0.0, 150000.0),
        "workouts": (0.0, 20.0),
        "workout_mins": (0.0, 1440.0),
    }
    minimum, maximum = bounds[metric]
    if value < minimum or value > maximum or (metric != "sleep_hours" and value != int(value)):
        raise HealthSnapshotValidationError("measurement value is out of range")
    if metric == "sleep_hours" and value <= 0:
        raise HealthSnapshotValidationError("sleep_hours must be greater than zero")

    finality = item.get("finality")
    if finality not in {"partial", "final"}:
        raise HealthSnapshotValidationError("finality must be partial or final")
    unit = item.get("unit")
    expected_units = {
        "sleep_hours": "hours",
        "steps": "count",
        "workouts": "count",
        "workout_mins": "minutes",
    }
    if unit != expected_units[metric]:
        raise HealthSnapshotValidationError("measurement unit is invalid")

    source_record_key = item.get("source_record_key")
    if not isinstance(source_record_key, str) or not source_record_key.strip():
        raise HealthSnapshotValidationError("source_record_key is required")
    if len(source_record_key.strip()) > 240:
        raise HealthSnapshotValidationError("source_record_key is too long")

    observed_at = _parse_datetime(item.get("observed_at") or captured.isoformat(), "observed_at")
    as_of = _parse_datetime(item.get("as_of") or captured.isoformat(), "as_of")
    if as_of > captured + timedelta(minutes=10):
        raise HealthSnapshotValidationError("as_of cannot be after captured_at")

    window_start = item.get("window_start")
    window_end = item.get("window_end")
    if window_start is not None:
        _parse_datetime(window_start, "window_start")
    if window_end is not None:
        _parse_datetime(window_end, "window_end")
    if window_start and window_end and _parse_datetime(window_end, "window_end") < _parse_datetime(window_start, "window_start"):
        raise HealthSnapshotValidationError("window_end must follow window_start")

    return {
        "metric_key": metric,
        "local_day": local_day.isoformat(),
        "value_num": int(value) if metric != "sleep_hours" else value,
        "unit": unit,
        "source_record_key": source_record_key.strip(),
        "observed_at": observed_at.isoformat(),
        "as_of": as_of.isoformat(),
        "window_start": _parse_datetime(window_start, "window_start").isoformat() if window_start else None,
        "window_end": _parse_datetime(window_end, "window_end").isoformat() if window_end else None,
        "finality": finality,
        "quality": "partial" if finality == "partial" else "valid",
    }


def normalize_snapshot(payload: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Validate and canonicalize a normalized v1 snapshot envelope.

    This is deliberately usable by HTTP and future inbox workers, so neither
    transport gets subtly different date, range, or idempotency behavior.
    """
    if not isinstance(payload, dict):
        raise HealthSnapshotValidationError("snapshot body must be an object")
    if payload.get("schema_version") != 1:
        raise HealthSnapshotValidationError("schema_version must be 1")
    source_key = payload.get("source_key") or payload.get("source")
    if source_key not in SUPPORTED_SOURCES:
        raise HealthSnapshotValidationError("unsupported health source")
    installation_id = payload.get("installation_id")
    snapshot_id = payload.get("snapshot_id")
    capture_kind = payload.get("capture_kind")
    timezone_name = payload.get("timezone")
    if not isinstance(installation_id, str) or not installation_id.strip() or len(installation_id.strip()) > 120:
        raise HealthSnapshotValidationError("installation_id is required")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip() or len(snapshot_id.strip()) > 120:
        raise HealthSnapshotValidationError("snapshot_id is required")
    if capture_kind not in {"sleep_final", "activity_final", "activity_progress", "history_backfill"}:
        raise HealthSnapshotValidationError("unsupported health capture kind")
    if timezone_name != HEALTH_TIMEZONE:
        raise HealthSnapshotValidationError(f"timezone must be {HEALTH_TIMEZONE}")
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise HealthSnapshotValidationError("timezone is invalid") from exc

    captured = _parse_datetime(payload.get("captured_at"), "captured_at")
    local_today = today or datetime.now(ZoneInfo(timezone_name)).date()
    now_value = datetime.now(ZoneInfo(timezone_name))
    if captured.astimezone(ZoneInfo(timezone_name)) > now_value + timedelta(minutes=10):
        raise HealthSnapshotValidationError("captured_at cannot be in the future")
    measurements_raw = payload.get("measurements")
    if not isinstance(measurements_raw, list) or not measurements_raw or len(measurements_raw) > 8:
        raise HealthSnapshotValidationError("snapshot needs 1 to 8 measurements")
    measurements = [_validate_measurement(item, captured) for item in measurements_raw]
    seen = set()
    for item in measurements:
        key = (item["local_day"], item["metric_key"])
        if key in seen:
            raise HealthSnapshotValidationError("snapshot may contain one value per day and metric")
        seen.add(key)
        age = (local_today - _parse_day(item["local_day"])).days
        if item["finality"] == "final" and age < 0:
            raise HealthSnapshotValidationError("final measurements cannot be future dated")
        if age > 35:
            raise HealthSnapshotValidationError("measurements may be at most 35 days old")
        if item["finality"] == "partial" and item["local_day"] != local_today.isoformat():
            raise HealthSnapshotValidationError("partial measurements must be for today")
        if capture_kind == "sleep_final" and item["metric_key"] != "sleep_hours":
            raise HealthSnapshotValidationError("sleep_final may contain sleep_hours only")
        if capture_kind in {"activity_final", "activity_progress"} and item["metric_key"] == "sleep_hours":
            raise HealthSnapshotValidationError("activity snapshots cannot contain sleep_hours")
        if capture_kind == "activity_progress" and item["finality"] != "partial":
            raise HealthSnapshotValidationError("activity_progress must be partial")
        if capture_kind in {"activity_final", "history_backfill"} and item["finality"] != "final":
            raise HealthSnapshotValidationError("final activity snapshots require final measurements")

    canonical = {
        "schema_version": 1,
        "source_key": source_key,
        "installation_id": installation_id.strip(),
        "snapshot_id": snapshot_id.strip(),
        "capture_kind": capture_kind,
        "captured_at": captured.isoformat(),
        "timezone": timezone_name,
        "measurements": sorted(measurements, key=lambda item: (
            item["local_day"], item["metric_key"], item["source_record_key"],
        )),
    }
    return canonical


def _ensure_source(conn, source_key: str) -> None:
    conn.execute(
        """INSERT INTO health_sources (source_key, display_label, enabled)
           VALUES (?, ?, 1)
           ON CONFLICT(source_key) DO UPDATE SET enabled=1""",
        (source_key, _source_label(source_key)),
    )
    for metric in SUPPORTED_METRICS:
        conn.execute(
            """INSERT OR IGNORE INTO health_metric_source_policy (metric_key, source_key)
               VALUES (?, ?)""",
            (metric, source_key),
        )


def _measurement_hash(source_key: str, installation_id: str, item: dict[str, Any]) -> str:
    return _canonical_hash({
        "source_key": source_key,
        "installation_id": installation_id,
        "metric_key": item["metric_key"],
        "local_day": item["local_day"],
        "value_num": item["value_num"],
        "unit": item["unit"],
        "as_of": item["as_of"],
        "finality": item["finality"],
        "window_start": item["window_start"],
        "window_end": item["window_end"],
    })


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    return _canonical_hash({
        "source_key": snapshot["source_key"],
        "installation_id": snapshot["installation_id"],
        "capture_kind": snapshot["capture_kind"],
        "captured_at": snapshot["captured_at"],
        "timezone": snapshot["timezone"],
        "measurements": snapshot["measurements"],
    })


def _active_override(conn, local_day: str, metric_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, value_num, created_at FROM health_overrides
           WHERE local_day=? AND metric_key=? AND revoked_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (local_day, metric_key),
    ).fetchone()
    return dict(row) if row else None


def _final_measurement(conn, local_day: str, metric_key: str) -> dict[str, Any] | None:
    policy = conn.execute(
        "SELECT source_key FROM health_metric_source_policy WHERE metric_key=?",
        (metric_key,),
    ).fetchone()
    if policy is None:
        return None
    row = conn.execute(
        """SELECT m.*
           FROM health_daily_measurements m
           WHERE m.source_key=? AND m.local_day=? AND m.metric_key=?
             AND m.finality='final' AND m.quality='valid'
           ORDER BY m.as_of DESC, m.id DESC
           LIMIT 1""",
        (policy["source_key"], local_day, metric_key),
    ).fetchone()
    return dict(row) if row else None


def _project_metric(conn, local_day: str, metric_key: str) -> None:
    override = _active_override(conn, local_day, metric_key)
    measurement = None if override else _final_measurement(conn, local_day, metric_key)
    column = METRIC_COLUMNS[metric_key]
    conn.execute("INSERT OR IGNORE INTO health_daily (date) VALUES (?)", (local_day,))

    if override:
        value = override["value_num"]
        source_key = "manual_override"
        quality = "manual"
        finality = "final"
        measurement_id = None
    elif measurement:
        value = measurement["value_num"]
        source_key = measurement["source_key"]
        quality = measurement["quality"]
        finality = measurement["finality"]
        measurement_id = measurement["id"]
    else:
        conn.execute(
            "DELETE FROM health_daily_projection_fields WHERE local_day=? AND metric_key=?",
            (local_day, metric_key),
        )
        return

    if metric_key in {"steps", "workouts", "workout_mins"}:
        value = int(value)
    conn.execute(
        f"UPDATE health_daily SET {column}=?, source='derived_health_projection' WHERE date=?",
        (value, local_day),
    )
    conn.execute(
        """INSERT INTO health_daily_projection_fields
           (local_day, metric_key, measurement_id, source_key, quality, finality, resolved_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
           ON CONFLICT(local_day, metric_key) DO UPDATE SET
             measurement_id=excluded.measurement_id,
             source_key=excluded.source_key,
             quality=excluded.quality,
             finality=excluded.finality,
             resolved_at=excluded.resolved_at""",
        (local_day, metric_key, measurement_id, source_key, quality, finality),
    )


def ingest_snapshot(conn, payload: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    """Write a normalized snapshot inside the caller's transaction.

    The same snapshot id is a transport retry. Equivalent measurements under a
    different snapshot id are domain duplicates. Neither can increment a
    daily total because all automated values are source-owned replacements.
    """
    snapshot = normalize_snapshot(payload, today=today)
    source_key = snapshot["source_key"]
    installation_id = snapshot["installation_id"]
    snapshot_hash = _snapshot_hash(snapshot)
    _ensure_source(conn, source_key)

    existing = conn.execute(
        """SELECT id, content_hash FROM health_snapshots
           WHERE source_key=? AND installation_id=? AND snapshot_id=?""",
        (source_key, installation_id, snapshot["snapshot_id"]),
    ).fetchone()
    if existing is not None:
        if existing["content_hash"] != snapshot_hash:
            raise HealthSnapshotConflict("snapshot id was reused with different health data")
        return {
            "status": "replayed",
            "source_key": source_key,
            "capture_kind": snapshot["capture_kind"],
            "affected_days": sorted({item["local_day"] for item in snapshot["measurements"]}),
            "metrics": sorted({item["metric_key"] for item in snapshot["measurements"]}),
        }

    cursor = conn.execute(
        """INSERT INTO health_snapshots
           (source_key, installation_id, snapshot_id, capture_kind, captured_at,
            timezone, content_hash, measurement_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (source_key, installation_id, snapshot["snapshot_id"], snapshot["capture_kind"],
         snapshot["captured_at"], snapshot["timezone"], snapshot_hash,
         len(snapshot["measurements"])),
    )
    snapshot_db_id = int(cursor.lastrowid)
    affected: set[tuple[str, str]] = set()
    inserted = 0

    for item in snapshot["measurements"]:
        semantic_hash = _measurement_hash(source_key, installation_id, item)
        same = conn.execute(
            "SELECT id FROM health_daily_measurements WHERE source_key=? AND semantic_hash=?",
            (source_key, semantic_hash),
        ).fetchone()
        if same is not None:
            continue
        record = conn.execute(
            """SELECT semantic_hash FROM health_daily_measurements
               WHERE source_key=? AND source_installation_id=?
                 AND source_record_key=? AND metric_key=?""",
            (source_key, installation_id, item["source_record_key"], item["metric_key"]),
        ).fetchone()
        if record is not None:
            if record["semantic_hash"] != semantic_hash:
                raise HealthSnapshotConflict("source record key was reused with different health data")
            continue
        conn.execute(
            """INSERT INTO health_daily_measurements
               (snapshot_id, source_key, source_installation_id, source_record_key,
                local_day, metric_key, value_num, unit, observed_at, as_of,
                window_start, window_end, finality, quality, semantic_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (snapshot_db_id, source_key, installation_id, item["source_record_key"],
             item["local_day"], item["metric_key"], item["value_num"], item["unit"],
             item["observed_at"], item["as_of"], item["window_start"], item["window_end"],
             item["finality"], item["quality"], semantic_hash),
        )
        inserted += 1
        if item["finality"] == "final":
            affected.add((item["local_day"], item["metric_key"]))

    for local_day, metric_key in affected:
        _project_metric(conn, local_day, metric_key)

    conn.execute(
        """UPDATE health_sources
           SET last_capture_at=?, enabled=1
           WHERE source_key=?""",
        (snapshot["captured_at"], source_key),
    )
    db.record_ingest_success(conn, source_key, inserted,
                             json.dumps({"capture_kind": snapshot["capture_kind"]},
                                        separators=(",", ":")), commit=False)
    return {
        "status": "accepted" if inserted else "updated",
        "source_key": source_key,
        "capture_kind": snapshot["capture_kind"],
        "affected_days": sorted({item["local_day"] for item in snapshot["measurements"]}),
        "metrics": sorted({item["metric_key"] for item in snapshot["measurements"]}),
    }


def _hours_since(value: str | None, now_value: datetime | None = None) -> float:
    if not value:
        return float("inf")
    try:
        when = _parse_datetime(value, "captured_at")
    except HealthSnapshotValidationError:
        try:
            when = datetime.strptime(value[:19], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=ZoneInfo(HEALTH_TIMEZONE)
            )
        except ValueError:
            return float("inf")
    now_dt = now_value or datetime.now(ZoneInfo(HEALTH_TIMEZONE))
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=ZoneInfo(HEALTH_TIMEZONE))
    return (now_dt - when.astimezone(now_dt.tzinfo)).total_seconds() / 3600


def health_status(conn, *, now_value: datetime | None = None) -> dict[str, Any]:
    """Safe operational status only, suitable for broad app state."""
    source = conn.execute(
        """SELECT * FROM health_sources
           WHERE enabled=1 ORDER BY last_capture_at DESC, configured_at DESC LIMIT 1"""
    ).fetchone()
    if source is None:
        return {
            "state": "not_configured",
            "configured": False,
            "source_label": "Apple Watch",
            "sleep_coverage_7d": 0,
            "sleep_coverage_28d": 0,
            "review_count": 0,
        }

    source_dict = dict(source)
    latest = conn.execute(
        """SELECT captured_at FROM health_snapshots
           WHERE source_key=? ORDER BY captured_at DESC, id DESC LIMIT 1""",
        (source_dict["source_key"],),
    ).fetchone()
    captured_at = latest["captured_at"] if latest else None
    if not captured_at:
        state = "awaiting_first_snapshot"
    elif _hours_since(captured_at, now_value) <= 30:
        state = "fresh"
    else:
        state = "late"

    today_value = (now_value or datetime.now(ZoneInfo(HEALTH_TIMEZONE))).date()
    def coverage(days: int) -> int:
        start = (today_value - timedelta(days=days - 1)).isoformat()
        row = conn.execute(
            """SELECT COUNT(DISTINCT local_day) AS n
               FROM health_daily_projection_fields
               WHERE metric_key='sleep_hours' AND finality='final'
                 AND quality='valid' AND local_day >= ?""",
            (start,),
        ).fetchone()
        return int(row["n"] if row else 0)

    return {
        "state": state,
        "configured": True,
        "source_key": source_dict["source_key"],
        "source_label": source_dict["display_label"],
        "last_accepted_capture": captured_at,
        "sleep_coverage_7d": coverage(7),
        "sleep_coverage_28d": coverage(28),
        "review_count": 0,
    }


def _measurement_provenance(conn, local_day: str, metric_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT p.source_key, p.finality, p.quality, m.as_of, m.observed_at,
                  m.window_start, m.window_end
           FROM health_daily_projection_fields p
           LEFT JOIN health_daily_measurements m ON m.id=p.measurement_id
           WHERE p.local_day=? AND p.metric_key=?""",
        (local_day, metric_key),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["source_label"] = _source_label(item["source_key"])
    return item


def _recent_sleep(conn) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    row = conn.execute(
        """SELECT p.local_day, h.sleep_hours
           FROM health_daily_projection_fields p
           JOIN health_daily h ON h.date=p.local_day
           WHERE p.metric_key='sleep_hours' AND p.finality='final'
           ORDER BY p.local_day DESC LIMIT 1"""
    ).fetchone()
    if row is None:
        legacy = conn.execute(
            """SELECT date AS local_day, sleep_hours FROM health_daily
               WHERE sleep_hours IS NOT NULL ORDER BY date DESC LIMIT 1"""
        ).fetchone()
        if legacy is None:
            return None, None
        return dict(legacy), None
    data = dict(row)
    return data, _measurement_provenance(conn, data["local_day"], "sleep_hours")


def health_today_view(conn, *, now_value: datetime | None = None) -> dict[str, Any]:
    """Narrow no-store Body payload, never a raw source-level export."""
    status = health_status(conn, now_value=now_value)
    local_today = (now_value or datetime.now(ZoneInfo(HEALTH_TIMEZONE))).date().isoformat()
    daily = db.health_for_day(conn, local_today) or {}
    sleep, sleep_provenance = _recent_sleep(conn)

    partial_rows = conn.execute(
        """SELECT metric_key, value_num, as_of, source_key
           FROM health_daily_measurements
           WHERE local_day=? AND finality='partial' AND quality='partial'
           ORDER BY as_of DESC, id DESC""",
        (local_today,),
    ).fetchall()
    partial: dict[str, dict[str, Any]] = {}
    for row in partial_rows:
        row_dict = dict(row)
        partial.setdefault(row_dict["metric_key"], row_dict)

    activity_day = local_today
    activity_finality = "partial" if partial else "final"
    if partial:
        steps = partial.get("steps", {}).get("value_num")
        workouts = partial.get("workouts", {}).get("value_num")
        workout_mins = partial.get("workout_mins", {}).get("value_num")
        activity_as_of = max((value["as_of"] for value in partial.values()), default=None)
    else:
        activity_row = daily
        if not any(activity_row.get(key) is not None for key in ("steps", "workouts", "workout_mins")):
            prior = conn.execute(
                """SELECT date, steps, workouts, workout_mins FROM health_daily
                   WHERE date < ? AND (steps IS NOT NULL OR workouts > 0 OR workout_mins > 0)
                   ORDER BY date DESC LIMIT 1""",
                (local_today,),
            ).fetchone()
            if prior:
                activity_row = dict(prior)
                activity_day = activity_row["date"]
        steps = activity_row.get("steps")
        workouts = activity_row.get("workouts")
        workout_mins = activity_row.get("workout_mins")
        activity_as_of = None

    sleep_values = conn.execute(
        """SELECT h.sleep_hours FROM health_daily_projection_fields p
           JOIN health_daily h ON h.date=p.local_day
           WHERE p.metric_key='sleep_hours' AND p.finality='final'
             AND p.quality='valid'
           ORDER BY p.local_day DESC LIMIT 7"""
    ).fetchall()
    sleep_average = (
        round(sum(float(row["sleep_hours"]) for row in sleep_values) / len(sleep_values), 1)
        if sleep_values else None
    )
    source_key = (sleep_provenance or {}).get("source_key") or status.get("source_key")
    return {
        "status": status,
        "sleep_hours": sleep.get("sleep_hours") if sleep else None,
        "sleep_day": sleep.get("local_day") if sleep else None,
        "sleep_avg_7d": sleep_average,
        "sleep_coverage_7d": status["sleep_coverage_7d"],
        "sleep_window_start": (sleep_provenance or {}).get("window_start"),
        "sleep_window_end": (sleep_provenance or {}).get("window_end"),
        "steps": int(steps) if steps is not None else None,
        "workouts": int(workouts) if workouts is not None else None,
        "workout_mins": int(workout_mins) if workout_mins is not None else None,
        "activity_day": activity_day if any(value is not None for value in (steps, workouts, workout_mins)) else None,
        "activity_as_of": activity_as_of,
        "activity_finality": activity_finality,
        "energy": daily.get("energy"),
        "manual_workout": daily.get("workout") or None,
        "source_key": source_key,
        "source_label": _source_label(source_key) if source_key else "Manual entry",
        "captured_at": (sleep_provenance or {}).get("as_of") or status.get("last_accepted_capture"),
        "provenance": {
            "sleep_hours": sleep_provenance,
            "steps": _measurement_provenance(conn, activity_day, "steps") if activity_day else None,
            "workouts": _measurement_provenance(conn, activity_day, "workouts") if activity_day else None,
            "workout_mins": _measurement_provenance(conn, activity_day, "workout_mins") if activity_day else None,
        },
    }


def health_history_view(conn, days: int = 7) -> dict[str, Any]:
    """Small daily trend payload. It excludes raw source observations."""
    bounded_days = max(7, min(28, int(days)))
    end = datetime.now(ZoneInfo(HEALTH_TIMEZONE)).date()
    rows = []
    for offset in range(bounded_days - 1, -1, -1):
        day = (end - timedelta(days=offset)).isoformat()
        row = db.health_for_day(conn, day) or {}
        sleep_provenance = _measurement_provenance(conn, day, "sleep_hours")
        rows.append({
            "day": day,
            "sleep_hours": row.get("sleep_hours"),
            "energy": row.get("energy"),
            "source_key": (sleep_provenance or {}).get("source_key"),
            "source_label": (sleep_provenance or {}).get("source_label"),
        })
    return {"days": rows, "coverage": health_status(conn)["sleep_coverage_7d" if bounded_days == 7 else "sleep_coverage_28d"]}


def health_insights_view(conn, limit: int = 6) -> dict[str, Any]:
    """Private, no-store Body payload for health-only reflections.

    ``legacy_montage`` is a read-only compatibility projection for historic
    Coach output. It is intentionally absent from broad app state and generic
    memo readers; a later migration can move those rows into health_insights
    without changing this dedicated Body contract.
    """
    legacy = db.latest_montage(conn)
    legacy_montage = None
    if legacy:
        legacy_montage = {
            "title": legacy.get("title") or "Weekly reflection",
            "body": legacy.get("body") or "",
            "created_at": legacy.get("created_at"),
        }
    return {
        "insights": db.recent_health_insights(conn, limit=limit),
        "legacy_montage": legacy_montage,
    }
