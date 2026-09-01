"""Log a published content item: the one-liner Don Draper (publicist) reads.

    make content platform=site item="Riverbend case study" url=https://... note="portfolio"
    # or directly:
    .venv/bin/python ingest/log_content.py -p site -i "Riverbend case study" -u https://... -n "portfolio"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def main() -> None:
    ap = argparse.ArgumentParser(description="Log a published content item")
    ap.add_argument("-p", "--platform", required=True, help="site | instagram | youtube | x | linkedin | ...")
    ap.add_argument("-i", "--item", required=True, help="what you published")
    ap.add_argument("-u", "--url", default="", help="link (optional)")
    ap.add_argument("-n", "--note", default="", help="context (optional)")
    ap.add_argument("--date", default=db.today(), help="YYYY-MM-DD (default: today)")
    args = ap.parse_args()

    if not args.platform.strip() or not args.item.strip():
        sys.exit("platform and item are required")

    conn = db.connect()
    row = db.add_content(conn, args.date, args.platform, args.item, args.url, args.note)
    print(f"{row['date']}: [{row['platform']}] {row['item']}"
          + (f": {row['url']}" if row["url"] else ""))
    conn.close()


if __name__ == "__main__":
    main()
