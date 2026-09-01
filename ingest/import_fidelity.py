"""Fidelity positions CSV fallback."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


def parse_positions(path: Path) -> list[dict]:
    positions = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = {h.strip().lower(): h for h in (reader.fieldnames or [])}
        sym_col = next((headers[k] for k in headers if k in ("symbol", "ticker")), None)
        desc_col = next((headers[k] for k in headers if k in ("description", "security description")), None)
        qty_col = next((headers[k] for k in headers if "quantity" in k), None)
        val_col = next((headers[k] for k in headers if "current value" in k or k == "market value"), None)
        cost_col = next((headers[k] for k in headers if "cost basis" in k), None)
        if not sym_col:
            sys.exit(f"CSV needs Symbol column; found: {reader.fieldnames}")
        for row in reader:
            symbol = (row.get(sym_col) or "").strip()
            if not symbol or symbol.lower() in ("cash", "pending activity"):
                continue
            qty = float((row.get(qty_col) or "0").replace(",", "").replace("$", "") or 0)
            mv_raw = row.get(val_col) or row.get(cost_col) or "0"
            mv = float(str(mv_raw).replace(",", "").replace("$", "") or 0)
            cost = None
            if cost_col and row.get(cost_col):
                try:
                    cost = float(str(row[cost_col]).replace(",", "").replace("$", ""))
                except ValueError:
                    pass
            desc = (row.get(desc_col) or symbol).strip()
            as_of = db.today()
            h = hashlib.sha256(f"csv|{symbol}|{as_of}".encode()).hexdigest()[:20]
            positions.append({
                "account": "fidelity",
                "symbol": symbol,
                "description": desc,
                "quantity": qty,
                "cost_basis": cost,
                "market_value": mv,
                "hash": h,
            })
    return positions


def main() -> None:
    ap = argparse.ArgumentParser(description="Import Fidelity positions CSV")
    ap.add_argument("file", type=Path)
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"no such file: {args.file}")
    positions = parse_positions(args.file)
    conn = db.connect()
    n = db.replace_holdings_snapshot(conn, db.today(), positions, "csv")
    db.update_ingest_log(conn, "snaptrade_fidelity", n, f"{n} positions from CSV")
    total = sum(p["market_value"] for p in positions)
    print(f"Imported {n} Fidelity positions (${total:,.2f}) from {args.file.name}")
    conn.close()


if __name__ == "__main__":
    main()
