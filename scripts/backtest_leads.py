"""Back-test Clockwork's lead scoring against what actually happened (SPEC-v9 E).

    make backtest

Answers one question: **does the Fit/Pain/Reach model actually predict who
answers the phone and who books a demo?** If tier A answers no more often than
tier C, the ordering, which is the whole product, is wrong, and the weights in
`leads/enrich_prospects.py` need changing.

This prints a report and changes nothing. Scoring belongs to the enricher; ianOS
never rewrites a tier. It is also deliberately terminal-only: the dashboard
shows no conversion analytics, because a win-rate chart cannot change the next
call, and looking at one mid-run would only add weight to a dial.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, leads


def _pct(v):
    return "-" if v is None else f"{v * 100:>5.1f}%"


def _table(title: str, groups: list[dict], note: str = "") -> None:
    print(f"\n  {title}")
    if note:
        print(f"    {note}")
    print(f"    {'group':<18}{'dialed':>7}{'reached':>9}{'demos':>7}"
          f"{'contact':>10}{'demo':>8}")
    for g in groups:
        flag = "  (thin)" if g["thin"] else ""
        print(f"    {g['group']:<18}{g['dialed']:>7}{g['contacted']:>9}{g['booked']:>7}"
              f"{_pct(g['contact_rate']):>10}{_pct(g['demo_rate']):>8}{flag}")


def main() -> None:
    conn = db.connect()
    try:
        r = leads.backtest(conn)
    finally:
        conn.close()

    print("\n" + "=" * 72)
    print("  THE LINE, back-test of Fit/Pain/Reach against reality")
    print("=" * 72)
    print(f"\n  Leads dialed : {r['leads_dialed']}")
    print(f"  Total dials  : {r['total_dials']}")
    print(f"  Reached      : {r['contacted']}")
    print(f"  Demos booked : {r['booked']}")

    if r["status"] == "insufficient":
        print(f"\n  NOT ENOUGH DATA YET.\n  {r['message']}")
        print("\n  Nothing here is worth reading until then, a contact rate off a")
        print("  handful of calls is noise, and tuning the scorer on noise is worse")
        print("  than leaving it alone.\n")
        return

    if r["message"]:
        print(f"\n  ⚠ {r['message']}")

    _table("BY TIER: the ordering guarantee itself", r["by_tier"])
    print(f"\n    verdict: {r['verdict']}"
          + (f" · tier lift {r['tier_lift']}x" if r["tier_lift"] else ""))
    if r["verdict"].startswith("ORDERING INVERTED"):
        print("    → The queue is actively ranking the wrong leads first.")
        print("      Re-weight score_row() in leads/enrich_prospects.py before dialing more.")

    _table("BY PAIN, evidence they're losing calls now", r["by_pain"])
    _table("BY REACH, can you get to a decision-maker", r["by_reach"])
    _table("BY FIT, right size, no competitor", r["by_fit"])
    _table("MISS SIGNAL, a review proving they miss calls", r["by_miss_signal"])
    _table("CLAIMS 24/7", r["by_claims_247"])

    print("\n  WHICH COMPONENT CARRIES THE SIGNAL")
    print("    (mean score of leads you reached vs leads you didn't)")
    print(f"    {'field':<10}{'reached':>10}{'missed':>10}{'gap':>8}")
    for s in sorted(r["separation"], key=lambda s: -(s["gap"] or 0)):
        if s["gap"] is None:
            print(f"    {s['field']:<10}{'-':>10}{'-':>10}{'-':>8}")
            continue
        print(f"    {s['field']:<10}{s['reached_mean']:>10}{s['missed_mean']:>10}"
              f"{s['gap']:>8}")
    print("\n    A large positive gap means that component is predictive, raise its")
    print("    weight. A gap near zero means it is dead weight in the score.")
    print("\n  This report changes nothing. Edit score_row() in")
    print("  leads/enrich_prospects.py, re-run it, then `make import-leads`.\n")


if __name__ == "__main__":
    main()
