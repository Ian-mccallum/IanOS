"""Export the leads table back to CSV, with real call history filled in.

The scraper's own `enriched.csv` already carries empty call-log columns
(`Call 1 Date`, `Answered?`, `Outcome`, `Next Step`, `Notes`, …). This writes
them for real, so the file round-trips:

    scrape -> enrich -> ianOS (Ian dials) -> export -> enrich --no-fetch -> ianOS

That closes the loop `enrich_prospects.py` was always shaped for, and it gives
`scripts/backtest_leads.py` (SPEC-v9 Phase E) something to score the model
against. Six extra `ianOS *` columns carry state the original schema has no
room for; `enrich_prospects.py` ignores unknown columns.

Usage:
    .venv/bin/python ingest/export_leads.py                       # -> leads/exported.csv
    .venv/bin/python ingest/export_leads.py --out /tmp/leads.csv
    .venv/bin/python ingest/export_leads.py --worked-only         # only leads Ian has touched
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db

ROOT = Path(__file__).resolve().parent.parent

# The enriched.csv column order, so a re-run of enrich_prospects.py sees the
# shape it expects. Trailing 'ianOS *' columns are additive.
COLUMNS = [
    "Tier", "Total", "Fit", "Pain", "Reach", "Why", "Market", "Segment",
    "Business Name", "Owner Name", "Phone", "Email", "City", "Service Type",
    "Miss Signal", "Claims 24/7", "Rating", "Reviews", "Website", "Site Status",
    "Platform", "Address", "Maps URL",
    "Call 1 Date", "Call 1 Time", "Answered?", "Outcome", "Call 2 Date",
    "Next Step", "Notes",
    "ianOS Stage", "ianOS Attempts", "ianOS Dials", "ianOS Reached",
    "ianOS Demo", "ianOS Last Touch",
]

ANSWERED = ("reached", "booked")


def _row(lead: dict, touches: list[dict]) -> dict:
    calls = [t for t in touches if t["kind"] in ("call", "follow_up")]
    calls.sort(key=lambda t: t["id"])
    first = calls[0] if calls else None
    second = calls[1] if len(calls) > 1 else None
    # The outcome that matters is the best one reached, not the newest, a demo
    # booked on call 2 is not erased by a no-answer on call 3.
    best = ""
    for t in calls:
        if t["outcome"] == "booked":
            best = "booked"
            break
        if t["outcome"] == "reached":
            best = "reached"
        elif not best and t["outcome"]:
            best = t["outcome"]

    notes = " | ".join(filter(None, [
        (lead.get("notes") or "").strip(),
        *[t["note"].strip() for t in calls if (t.get("note") or "").strip()],
    ]))

    return {
        "Tier": lead["tier"], "Total": lead["total"], "Fit": lead["fit"],
        "Pain": lead["pain"], "Reach": lead["reach"], "Why": lead["why"],
        "Market": lead["market"], "Segment": lead["segment"],
        "Business Name": lead["business_name"], "Owner Name": lead["owner_name"],
        "Phone": lead["phone"], "Email": lead["email"], "City": lead["city"],
        "Service Type": lead["service_type"], "Miss Signal": lead["miss_signal"],
        "Claims 24/7": "yes" if lead["claims_247"] else "",
        "Rating": lead["rating"] if lead["rating"] is not None else "",
        "Reviews": lead["reviews"] if lead["reviews"] is not None else "",
        "Website": lead["website"], "Site Status": lead["site_status"],
        "Platform": lead["platform"], "Address": lead["address"],
        "Maps URL": lead["maps_url"],
        "Call 1 Date": (first or {}).get("date", ""),
        "Call 1 Time": ((first or {}).get("created_at") or "")[11:16],
        "Answered?": "" if not first else ("yes" if best in ANSWERED else "no"),
        "Outcome": best,
        "Call 2 Date": (second or {}).get("date", ""),
        "Next Step": lead.get("next_touch") or "",
        "Notes": notes,
        "ianOS Stage": lead["stage"],
        "ianOS Attempts": lead["attempts"],
        "ianOS Dials": len(calls),
        "ianOS Reached": 1 if best in ANSWERED else 0,
        "ianOS Demo": 1 if best == "booked" else 0,
        "ianOS Last Touch": lead.get("last_touch") or "",
    }


def export(out: Path, worked_only: bool = False) -> dict:
    conn = db.connect()
    try:
        leads = db.rows_to_dicts(conn.execute(
            "SELECT * FROM leads ORDER BY "
            "CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END, "
            "total DESC, id"
        ).fetchall())
        by_lead: dict[int, list[dict]] = {}
        for t in db.rows_to_dicts(conn.execute("SELECT * FROM lead_touches").fetchall()):
            by_lead.setdefault(t["lead_id"], []).append(t)

        rows, worked = [], 0
        for lead in leads:
            touches = by_lead.get(lead["id"], [])
            if touches:
                worked += 1
            elif worked_only:
                continue
            rows.append(_row(lead, touches))

        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        return {"written": len(rows), "worked": worked, "total": len(leads)}
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Export ianOS leads (with call history) to CSV")
    ap.add_argument("--out", type=Path, default=ROOT / "leads" / "exported.csv")
    ap.add_argument("--worked-only", action="store_true",
                    help="only leads with at least one touch")
    args = ap.parse_args()

    res = export(args.out, worked_only=args.worked_only)
    print(f"\nWrote {res['written']} rows to {args.out}")
    print(f"  {res['worked']} of {res['total']} leads have call history")
    if not res["worked"]:
        print("  (no calls logged yet: the call-log columns are all empty)")
    print()


if __name__ == "__main__":
    main()
