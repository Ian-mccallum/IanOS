"""Frictionless daily activity logging: the one-liner scout depends on.

    make log calls=12 fu=5 demos=1
    # or directly:
    .venv/bin/python ingest/log_activity.py -c 12 -f 5 -d 1 -n "Riverbend wants pricing"

Counts INCREMENT today's row (log as you go); --set overwrites instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def main() -> None:
    ap = argparse.ArgumentParser(description="Log today's sales activity")
    ap.add_argument("-c", "--calls", type=int, default=0, help="audit calls made")
    ap.add_argument("-f", "--followups", type=int, default=0, help="follow-ups done")
    ap.add_argument("-d", "--demos", type=int, default=0, help="demos held")
    ap.add_argument("-v", "--conversations", type=int, default=0, help="real conversations")
    ap.add_argument("-n", "--note", default="", help="freeform note (leads, context)")
    ap.add_argument("--set", action="store_true", help="overwrite today's row instead of incrementing")
    ap.add_argument("--date", default=db.today(), help="YYYY-MM-DD (default: today)")
    args = ap.parse_args()

    conn = db.connect()
    row = db.log_activity(conn, args.date, args.calls, args.followups, args.demos,
                          args.conversations, args.note, replace=args.set)
    print(f"{row['date']}: {row['audit_calls']} calls · {row['follow_ups']} follow-ups · "
          f"{row['demos']} demos · {row['conversations']} conversations"
          + (f" · note: {row['notes']}" if row["notes"] else ""))
    print("Quota: 20 calls/day · 10 follow-ups/day · 3-5 demos/week")


if __name__ == "__main__":
    main()
