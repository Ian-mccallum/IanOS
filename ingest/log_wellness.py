"""Wellness quick-log CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def main() -> None:
    ap = argparse.ArgumentParser(description="Log today's wellness metrics")
    ap.add_argument("-s", "--sleep", type=float, default=None)
    ap.add_argument("-e", "--energy", type=int, default=None)
    ap.add_argument("-w", "--workout", type=int, default=0, help="workout count for today")
    ap.add_argument("-t", "--type", dest="workout_type", default="",
                    help="workout slug: mma | lift | soccer | run | rest")
    ap.add_argument("-n", "--note", default="")
    ap.add_argument("--steps", type=int, default=None)
    args = ap.parse_args()
    conn = db.connect()
    fields = {"source": "manual"}
    if args.sleep is not None:
        fields["sleep_hours"] = args.sleep
    if args.energy is not None:
        fields["energy"] = max(1, min(5, args.energy))
    if args.workout:
        fields["workouts"] = args.workout
    if args.workout_type:
        fields["workout"] = args.workout_type.strip().lower()
        if not args.workout:
            fields["workouts"] = 1        # logging a type implies a session
    if args.steps is not None:
        fields["steps"] = args.steps
    if args.note:
        fields["notes"] = args.note
    row = db.upsert_health(conn, db.today(), **fields)
    print(f"Wellness logged for {db.today()}: sleep={row.get('sleep_hours')} "
          f"energy={row.get('energy')} workouts={row.get('workouts')} type={row.get('workout') or '-'}")
    conn.close()


if __name__ == "__main__":
    main()
