"""Import Clockwork's enriched prospect list into ianOS (SPEC-v9).

This loader is the ONLY bulk writer for the `leads` table, the same boundary
`import_csv.py` holds over `transactions`. It enforces three rules in code:

  1. Ian's state is untouchable. On a re-import (the scraper WILL run again)
     only scraped/scored columns refresh; stage, attempts, last_touch,
     next_touch and notes survive. Without this, re-scraping would wipe his
     call history.
  2. The scoring model belongs to enrich_prospects.py. Tier/Fit/Pain/Reach are
     imported verbatim and never recomputed here.
  3. Junk never reaches the call queue. Rows with no phone, an out-of-state
     address, or a kiosk/distributor name import as `parked`.

Usage:
    .venv/bin/python ingest/import_leads.py leads/enriched.csv --dry-run
    .venv/bin/python ingest/import_leads.py leads/enriched.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from core.leads import norm_phone

HOME_STATE = "IL"

# Unstaffed key-cutting kiosks inside hardware stores, and an HVAC parts
# distributor. None of them answers a phone or buys a CRM; 41 of the 53 rows
# would otherwise land in tiers B and C. ~2 days of dialing saved.
JUNK_NAMES = (
    "keyme",
    "minute key",
    "key center at the home depot",
    "johnstone supply",
)

STATE_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}")


def parse_state(address: str) -> str:
    m = STATE_RE.search(address or "")
    return m.group(1) if m else ""


def is_junk(name: str) -> bool:
    low = (name or "").strip().lower()
    return any(j in low for j in JUNK_NAMES)


def lead_key(phone_norm: str, name: str, address: str) -> str:
    """The row's identity for dedupe.

    Phone is the key when there is one (1,892 of 1,958 rows, zero collisions).
    Phoneless rows still need a STABLE key: `phone_norm` is UNIQUE, but SQLite
    permits unlimited NULLs in a unique column, so leaving them null would
    duplicate all 64 of them on every re-import. Hash name+address instead : 
    the same idempotency trick `import_csv.py` uses on transactions.
    """
    if phone_norm:
        return phone_norm
    seed = f"{name.strip().lower()}|{address.strip().lower()}"
    return "x" + hashlib.sha256(seed.encode()).hexdigest()[:15]


def _int(raw: str) -> int:
    try:
        return int(float(str(raw).strip()))
    except (ValueError, TypeError):
        return 0


def _float(raw: str):
    try:
        return float(str(raw).strip())
    except (ValueError, TypeError):
        return None


def row_to_lead(row: dict) -> tuple[str, dict, str]:
    """-> (phone_norm, column dict, park_reason or '')."""
    phone_raw = (row.get("Phone") or "").strip()
    phone_norm = norm_phone(phone_raw)
    name = (row.get("Business Name") or "").strip()
    address = (row.get("Address") or "").strip()
    state = parse_state(address)

    park = ""
    if not phone_norm:
        park = "no phone"
    elif state and state != HOME_STATE:
        park = f"out-of-market ({state})"
    elif is_junk(name):
        park = "kiosk/distributor"

    tier = (row.get("Tier") or "C").strip().upper()
    if tier not in ("A", "B", "C", "D"):
        tier = "C"

    fields = {
        "phone": phone_raw,
        "business_name": name,
        "owner_name": (row.get("Owner Name") or "").strip(),
        "email": (row.get("Email") or "").strip(),
        "city": (row.get("City") or "").strip(),
        "state": state,
        "market": (row.get("Market") or "").strip().lower(),
        "segment": (row.get("Segment") or "").strip().lower(),
        "service_type": (row.get("Service Type") or "").strip(),
        "tier": tier,
        "fit": _int(row.get("Fit")),
        "pain": _int(row.get("Pain")),
        "reach": _int(row.get("Reach")),
        "total": _int(row.get("Total")),
        "why": (row.get("Why") or "").strip(),
        "miss_signal": (row.get("Miss Signal") or "").strip(),
        "claims_247": 1 if (row.get("Claims 24/7") or "").strip().lower() == "yes" else 0,
        "rating": _float(row.get("Rating")),
        "reviews": _int(row.get("Reviews")),
        "website": (row.get("Website") or "").strip(),
        "site_status": (row.get("Site Status") or "").strip().lower(),
        "platform": (row.get("Platform") or "").strip().lower(),
        "address": address,
        "maps_url": (row.get("Maps URL") or "").strip(),
    }
    return phone_norm, fields, park


def import_file(path: Path, dry_run: bool = False) -> dict:
    conn = db.connect()
    stats: Counter = Counter()
    parked_reasons: Counter = Counter()
    seen_phones: set[str] = set()

    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            phone_norm, fields, park = row_to_lead(row)
            if not fields["business_name"]:
                stats["skipped_no_name"] += 1
                continue
            key = lead_key(phone_norm, fields["business_name"], fields["address"])
            if key in seen_phones:
                stats["dupe_in_file"] += 1
                continue
            seen_phones.add(key)

            if park:
                parked_reasons[park] += 1

            if dry_run:
                existing = db.lead_by_phone(conn, key)
                stats["updated" if existing else "inserted"] += 1
                if park:
                    stats["parked"] += 1
                continue

            new_row = {**fields, "source": path.name}
            if park:
                new_row["stage"] = "parked"
                new_row["notes"] = park
            _, created = db.upsert_lead(conn, key, **new_row)
            stats["inserted" if created else "updated"] += 1
            if created and park:
                stats["parked"] += 1

    if not dry_run:
        total = stats["inserted"] + stats["updated"]
        db.update_ingest_log(conn, "leads_csv", total, path.name)
        db.add_memo(
            conn, "system", "leads imported",
            f"{stats['inserted']} new, {stats['updated']} refreshed, "
            f"{stats['parked']} parked from {path.name}. "
            f"Ian's call state on existing rows was preserved.",
        )
        conn.commit()
    conn.close()
    return {"stats": dict(stats), "parked_reasons": dict(parked_reasons)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Import an enriched lead CSV into ianOS")
    ap.add_argument("file", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no such file: {args.file}")

    res = import_file(args.file, dry_run=args.dry_run)
    s = res["stats"]
    head = "DRY RUN, nothing written" if args.dry_run else "Imported"
    print(f"\n{head}: {args.file.name}")
    print(f"  new           {s.get('inserted', 0)}")
    print(f"  refreshed     {s.get('updated', 0)}")
    print(f"  parked        {s.get('parked', 0)}")
    for reason, n in sorted(res["parked_reasons"].items(), key=lambda x: -x[1]):
        print(f"      {reason:<26} {n}")
    if s.get("dupe_in_file"):
        print(f"  dupes in file {s['dupe_in_file']} (same phone twice, kept first)")
    if s.get("skipped_no_name"):
        print(f"  no name       {s['skipped_no_name']}")

    if not args.dry_run:
        conn = db.connect()
        tiers = db.lead_counts_by(conn, "tier")
        stages = db.lead_counts_by(conn, "stage")
        print(f"\n  tiers  {tiers}")
        print(f"  stages {stages}")
        conn.close()
    print()


if __name__ == "__main__":
    main()
