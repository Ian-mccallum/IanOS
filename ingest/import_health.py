"""Apple Health / health export CSV import."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def _pick(headers: dict, candidates: set[str]) -> str | None:
    return next((headers[c] for c in candidates if c in headers), None)


def import_file(path: Path) -> int:
    conn = db.connect()
    count = 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        date_col = _pick(headers, {"date", "day"})
        sleep_col = _pick(headers, {"sleep analysis [hr]", "sleep", "sleep_hours", "sleep hours"})
        steps_col = _pick(headers, {"step count", "steps"})
        workout_col = _pick(headers, {"workout", "workouts", "exercise minutes"})
        if not date_col:
            sys.exit(f"CSV needs date column; found: {reader.fieldnames}")
        for row in reader:
            day = row[date_col].strip()[:10]
            fields = {"source": "apple_health"}
            if sleep_col and row.get(sleep_col):
                try:
                    fields["sleep_hours"] = float(row[sleep_col])
                except ValueError:
                    pass
            if steps_col and row.get(steps_col):
                try:
                    fields["steps"] = int(float(row[steps_col]))
                except ValueError:
                    pass
            if workout_col and row.get(workout_col):
                try:
                    v = float(row[workout_col])
                    fields["workouts"] = 1 if v > 0 else 0
                    fields["workout_mins"] = int(v)
                except ValueError:
                    pass
            if len(fields) > 1:
                db.upsert_health(conn, day, **fields)
                count += 1
    db.update_ingest_log(conn, "apple_health", count, path.name)
    return count


def main() -> None:
    ap = argparse.ArgumentParser(description="Import Apple Health CSV")
    ap.add_argument("file", type=Path)
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no such file: {args.file}")
    n = import_file(args.file)
    print(f"Imported {n} health days from {args.file.name}")


if __name__ == "__main__":
    main()
