"""Print the next calls with their full scripts, so Ian can read ahead.

    make prep            # the next 5
    make prep N=10

The Line already puts the script on screen the moment a card mounts, but the
hardest call of any session is the first one, and the dread lives in the minutes
BEFORE it, not during. Reading the run cold, away from the app, removes the
only real unknown. Nothing here writes anything or opens a run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, leads

BAR = "─" * 70


def main() -> None:
    ap = argparse.ArgumentParser(description="Read the next calls before dialing")
    ap.add_argument("-n", "--count", type=int, default=5)
    args = ap.parse_args()

    conn = db.connect()
    try:
        queue = leads.call_queue(conn, limit=args.count)
    finally:
        conn.close()

    if not queue:
        print("\n  The line is clear, nothing queued right now.\n")
        return

    print(f"\n  Next {len(queue)} calls. Read them, then go.\n")
    for i, lead in enumerate(queue, 1):
        card = lead["call_card"]
        meta = " · ".join(filter(None, [lead["city"], lead["service_type"]]))
        print(BAR)
        print(f"{i}. {lead['business_name']}   [{lead['tier']}]  {meta}")
        print(f"   DIAL  {lead['phone']}      ASK FOR  {card['ask_for']}")
        print(f"   WHY   {lead['queue_reason']}")
        if card["evidence"]:
            print(f"\n   THEIR OWN REVIEW\n     “{card['evidence']}”")
        print(f"\n   YOU:  {card['open']}")
        print(f"   YOU:  {card['hook']}")
        print(f"   YOU:  {card['ask']}")
        print("\n   IF THEY SAY")
        for o in card["objections"]:
            print(f"     {o['trigger']:<22} {o['reply']}")
        print()

    print(BAR)
    print("  Skip costs nothing. Esc leaves. Every outcome undoes for 8 seconds.")
    print("  The run counts dials, not pickups.\n")


if __name__ == "__main__":
    main()
