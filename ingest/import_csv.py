"""Monthly bank/card CSV import."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from ingest.categorize import categorize

DATE_COLS = {"date", "transaction date", "posting date", "posted date"}
DESC_COLS = {"description", "desc", "details", "name", "merchant", "payee"}
AMOUNT_COLS = {"amount", "amt", "transaction amount"}
CATEGORY_COLS = {"category", "type"}
ACCOUNT_COLS = {"account", "account name", "card"}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y")


def pick(header_map: dict, names: set[str]) -> str | None:
    return next((header_map[n] for n in names if n in header_map), None)


def parse_date(raw: str) -> str:
    raw = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date: {raw!r}")


def parse_amount(raw: str) -> float:
    raw = raw.strip().replace("$", "").replace(",", "")
    if raw.startswith("(") and raw.endswith(")"):
        raw = "-" + raw[1:-1]
    return float(raw)


def import_file(path: Path) -> tuple[int, int]:
    conn = db.connect()
    inserted = skipped = 0
    occurrence: Counter = Counter()
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        date_col = pick(headers, DATE_COLS)
        desc_col = pick(headers, DESC_COLS)
        amount_col = pick(headers, AMOUNT_COLS)
        if not (date_col and desc_col and amount_col):
            sys.exit(f"CSV must have date/description/amount columns; found: {reader.fieldnames}")
        cat_col = pick(headers, CATEGORY_COLS)
        acct_col = pick(headers, ACCOUNT_COLS)

        for row in reader:
            try:
                tx_date = parse_date(row[date_col])
                amount = parse_amount(row[amount_col])
            except (ValueError, KeyError) as e:
                print(f"  skipping malformed row: {e}")
                continue
            desc = row[desc_col].strip()
            category = (row.get(cat_col) or "").strip().lower() if cat_col else ""
            category = category or categorize(desc)
            account = (row.get(acct_col) or "").strip() if acct_col else path.stem

            key = (tx_date, desc, amount, account)
            occurrence[key] += 1
            h = hashlib.sha256(
                f"{tx_date}|{desc}|{amount}|{account}|{occurrence[key]}".encode()
            ).hexdigest()[:16]
            try:
                conn.execute(
                    "INSERT INTO transactions (date, description, amount, category, account, hash, source) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (tx_date, desc, amount, category, account, h, "csv"),
                )
                inserted += 1
            except Exception:
                skipped += 1
    db.update_ingest_log(conn, "bank_csv", inserted, path.name)
    conn.commit()
    return inserted, skipped


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a bank/card CSV into ianOS")
    ap.add_argument("file", type=Path)
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no such file: {args.file}")
    inserted, skipped = import_file(args.file)
    print(f"Imported {inserted} transactions ({skipped} already present) from {args.file.name}")


if __name__ == "__main__":
    main()
