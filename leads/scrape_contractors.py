#!/usr/bin/env python3
"""
scrape_contractors.py, build a Naperville/Aurora contractor prospect list for
Clockwork sales, using the official Google Places API (New).

Why the API and not HTML scraping: Places API returns name + PHONE + website +
rating + review count legally and reliably. Rating & review count are your
"leaky shop" signal, so this beats scraping on data quality too.

Outputs growth/contractor_leads.csv, sorted best-prospect first, with headers
that drop straight into Clockwork's "Bring Your Book" CSV import.

── One-time setup (~3 min, free at this volume) ──────────────────────────────
  1. https://console.cloud.google.com/  ->  create a project
  2. "APIs & Services" -> "Enable APIs" -> enable **Places API (New)**
  3. "Credentials" -> "Create credentials" -> "API key" -> copy it
  4. Put the key in growth/.env (copy growth/.env.example -> growth/.env):
        GOOGLE_PLACES_API_KEY=paste_key_here
     (.env is gitignored, so the key never gets committed. Or just
      `export GOOGLE_PLACES_API_KEY=...` in the terminal instead of a file.)
  (Billing must be enabled on the project, but ~100 calls costs pennies and
   sits inside Google's monthly free credit. This whole run is one-time.)

── Run ───────────────────────────────────────────────────────────────────────
        python3 growth/scrape_contractors.py

Edit TRADES and TOWNS below to widen or narrow the sweep, each combo is one
search. Re-run any time; results are deduped by phone number.
"""

import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

def _load_env_file(path: str) -> None:
    """Load KEY=VALUE lines from a .env file into the environment (no deps).

    An already-exported real env var wins over the file (setdefault).
    """
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

API_KEY = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Each trade x town pair is one search. Add/remove freely.
TRADES = [
    "HVAC contractor",
    "air conditioning repair",
    "furnace repair",
    "plumber",
    "electrician",
    "roofing contractor",
]
TOWNS = [
    "Naperville IL",
    "Aurora IL",
    "Bolingbrook IL",
    "Plainfield IL",
    "Wheaton IL",
    "Lisle IL",
    "Downers Grove IL",
]

# Only ask Google for the fields we use (cheaper + faster).
FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.formattedAddress",
        "places.googleMapsUri",
        "nextPageToken",
    ]
)


def _post(body: dict) -> dict:
    req = urllib.request.Request(
        SEARCH_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": API_KEY,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def search(query: str):
    """Yield place dicts for one text query, paging through up to ~60 results."""
    body = {"textQuery": query, "pageSize": 20, "regionCode": "US"}
    for _ in range(3):  # 3 pages max in the Places API (New)
        data = _post(body)
        for place in data.get("places", []):
            yield place
        token = data.get("nextPageToken")
        if not token:
            break
        time.sleep(2)  # the page token needs a moment to become valid
        body = {"textQuery": query, "pageSize": 20, "regionCode": "US", "pageToken": token}


def norm_phone(p: str) -> str:
    return re.sub(r"\D", "", p or "")


def city_from_address(addr: str) -> str:
    # "123 Main St, Naperville, IL 60540, USA" -> "Naperville"
    parts = [x.strip() for x in (addr or "").split(",")]
    return parts[-3] if len(parts) >= 3 else ""


def score_prospect(rating, reviews, has_site: bool, has_phone: bool):
    """Higher score = better cold prospect (established but 'leaky')."""
    score, signals = 0, []
    if reviews is not None and 15 <= reviews <= 150:
        score += 2
        signals.append("right-size shop")
    if rating is not None and 3.6 <= rating <= 4.6:
        score += 1
        signals.append("active reviews")
    if not has_site:
        score += 1
        signals.append("no website")
    if not has_phone:
        score -= 5  # unreachable = not a prospect
        signals.append("NO PHONE")
    return score, "; ".join(signals)


def main() -> None:
    if not API_KEY:
        sys.exit("Set GOOGLE_PLACES_API_KEY first, see the setup notes at the top of this file.")

    seen: set[str] = set()
    rows: list[dict] = []

    for trade in TRADES:
        for town in TOWNS:
            query = f"{trade} in {town}"
            try:
                before = len(rows)
                for place in search(query):
                    name = (place.get("displayName") or {}).get("text", "").strip()
                    phone = (place.get("nationalPhoneNumber") or "").strip()
                    key = norm_phone(phone) or name.lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)

                    rating = place.get("rating")
                    reviews = place.get("userRatingCount")
                    site = (place.get("websiteUri") or "").strip()
                    addr = (place.get("formattedAddress") or "").strip()
                    prio, signal = score_prospect(rating, reviews, bool(site), bool(phone))

                    rows.append(
                        {
                            "Business Name": name,
                            "Phone": phone,
                            "Email": "",
                            "City": city_from_address(addr),
                            "Service Type": trade,
                            "Website": site,
                            "Rating": rating if rating is not None else "",
                            "Reviews": reviews if reviews is not None else "",
                            "Address": addr,
                            "Maps URL": place.get("googleMapsUri", ""),
                            "Priority": prio,
                            "Signal": signal,
                        }
                    )
                print(f"  {query}: +{len(rows) - before} new  ({len(rows)} total)")
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                print(f"  ! {query}: HTTP {e.code}: {detail}")
            except Exception as e:  # keep the sweep going on any single failure
                print(f"  ! {query}: {e}")

    if not rows:
        sys.exit(
            "\nNo results. Usually means the API key is missing billing, or "
            "'Places API (New)' isn't enabled yet. Check the setup notes up top."
        )

    rows.sort(key=lambda r: r["Priority"], reverse=True)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contractor_leads.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with_phone = sum(1 for r in rows if r["Phone"])
    print(f"\nWrote {len(rows)} contractors -> {out_path}")
    print(f"{with_phone} have phone numbers, that's your mystery-shop list.")
    print("Top of the file = best-priority prospects. Start there.")


if __name__ == "__main__":
    main()
