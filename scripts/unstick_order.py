"""Unstick the Order: archive the dead LLC->EIN->A2P chain, sweep stale proposals.

OPERATOR SCRIPT. This deliberately runs against the REAL `data/ianos.db` via
`db.connect()`, and does NOT monkeypatch `db.DB_PATH` the way test code or
throwaway scripts must (see CLAUDE.md's "db.connect() hardcodes DB_PATH"
warning: that warning is for scripts that should NOT touch real data. This
one is the opposite case: a one-off, idempotent operator fix that is meant to
touch Ian's real data, on purpose, when run with --apply).

Context (docs/SPEC-v32-live-order.md section 3, "A1"): goal 6 ("File Illinois
LLC") is already archived. Two goals depend on it and are stuck at the top of
the Order: goal 7 "Obtain EIN from IRS" (depends_on_goal_id=6) and goal 8
"Twilio A2P 10DLC campaign approved" (depends_on_goal_id=7). Ian's decision,
already made: archive 7 and 8 too, so the dashboard stops surfacing a dead
chain. Separately, `db.expire_stale_proposals` is already merged and wired
into the nightly sequence, but the 29 real PENDING proposals that predate the
fix need a one-time sweep.

Usage:
    .venv/bin/python scripts/unstick_order.py            # dry run, prints report
    .venv/bin/python scripts/unstick_order.py --apply     # actually writes

Idempotent: a second --apply run finds both goals already archived and no
stale proposals left, and changes nothing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db

TARGET_GOAL_NAMES = (
    "Obtain EIN from IRS",
    "Twilio A2P 10DLC campaign approved",
)


def run(conn, *, apply: bool) -> dict:
    """Archive the two stuck goals and sweep stale proposals.

    Takes an already-open connection so this is fully testable against a
    monkeypatched `db.DB_PATH` without ever touching the real file. A dry run
    (`apply=False`) is a true no-op: it performs no INSERT/UPDATE/DELETE.
    """
    rows = conn.execute(
        "SELECT id, name, archived FROM goals WHERE name IN (?, ?)",
        TARGET_GOAL_NAMES,
    ).fetchall()
    found_by_name = {row["name"]: row for row in rows}

    goals_archived: list[str] = []
    goals_already_archived: list[str] = []
    goals_not_found: list[str] = []

    for name in TARGET_GOAL_NAMES:
        row = found_by_name.get(name)
        if row is None:
            goals_not_found.append(name)
            continue
        if row["archived"]:
            goals_already_archived.append(name)
            continue
        if apply:
            conn.execute("UPDATE goals SET archived=1 WHERE id=?", (row["id"],))
        goals_archived.append(name)

    if apply and goals_archived:
        names = " and ".join(goals_archived)
        db.add_memo(
            conn,
            "ian",
            "business chain paused for the semester",
            f"business chain (LLC->EIN->A2P) paused for the semester - "
            f"archived {names}, will restart deliberately",
            commit=False,
        )

    if apply:
        conn.commit()
        n_expired = db.expire_stale_proposals(conn)
    else:
        cutoff = (
            datetime.now() - timedelta(days=db.PROPOSAL_EXPIRY_DAYS)
        ).strftime("%Y-%m-%d %H:%M:%S")
        n_expired = conn.execute(
            "SELECT COUNT(*) FROM proposals WHERE status='PENDING' AND created_at <= ?",
            (cutoff,),
        ).fetchone()[0]

    return {
        "goals_archived": goals_archived,
        "goals_already_archived": goals_already_archived,
        "goals_not_found": goals_not_found,
        "proposals_expired": n_expired,
        "apply": apply,
    }


def _print_report(report: dict) -> None:
    mode = "APPLY" if report["apply"] else "DRY RUN"
    print(f"\n  unstick_order.py — {mode}\n")
    print(f"  goals archived this run:      {report['goals_archived'] or '-'}")
    print(f"  goals already archived:       {report['goals_already_archived'] or '-'}")
    print(f"  goals not found:              {report['goals_not_found'] or '-'}")
    print(f"  proposals expired:            {report['proposals_expired']}")
    print()
    if not report["apply"]:
        print("  Nothing was written. Re-run with --apply to make it real.\n")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Archive the dead LLC->EIN->A2P chain and sweep stale proposals."
    )
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()

    conn = db.connect()
    try:
        report = run(conn, apply=args.apply)
    finally:
        conn.close()

    _print_report(report)


if __name__ == "__main__":
    main()
