"""Sync Chase checking via SimpleFIN Bridge. Skips gracefully without SIMPLEFIN_ACCESS_URL."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from core.env import load_dotenv
from core.http import ssl_context
from ingest.categorize import categorize

import os

load_dotenv()

SOURCE = "simplefin_chase"
REQUIRED_ENV_KEYS = ("SIMPLEFIN_ACCESS_URL",)


class SimpleFINProtocolError(ValueError):
    """The provider returned a response that is unsafe to publish."""


def missing_config_keys() -> list[str]:
    """Return key names only; callers must never include credential values."""
    return [key for key in REQUIRED_ENV_KEYS if not os.environ.get(key, "").strip()]


def configured() -> bool:
    return not missing_config_keys()


def _auth_url(access_url: str) -> tuple[str, str | None]:
    """Split SimpleFIN access URL into base + basic auth token."""
    parsed = urllib.parse.urlparse(access_url)
    if parsed.username and parsed.password:
        base = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            base += f":{parsed.port}"
        base += parsed.path
        token = base64.b64encode(f"{parsed.username}:{parsed.password}".encode()).decode()
        return base, token
    return access_url.rstrip("/"), None


def fetch_accounts(access_url: str, start_date: str | None = None) -> dict:
    base, token = _auth_url(access_url)
    url = f"{base}/accounts?pending=1"
    if start_date:
        ts = int(date.fromisoformat(start_date).strftime("%s"))
        url += f"&start-date={ts}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        try:
            payload = json.loads(resp.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SimpleFINProtocolError("SimpleFIN returned invalid JSON") from exc
    return _validate_payload(payload)


def _validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise SimpleFINProtocolError("SimpleFIN response must be an object")
    accounts = payload.get("accounts")
    if accounts is None and "balance" in payload:
        accounts = payload["accounts"] = []
    if not isinstance(accounts, list):
        raise SimpleFINProtocolError("SimpleFIN response has neither accounts nor balance")
    if any(not isinstance(account, dict) for account in accounts):
        raise SimpleFINProtocolError("SimpleFIN account payload is malformed")
    return payload


def _is_duplicate(exc: sqlite3.IntegrityError) -> bool:
    return "unique constraint failed" in str(exc).lower()


def _finite_money(value, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SimpleFINProtocolError(f"SimpleFIN {field} is malformed") from exc
    if not math.isfinite(number):
        raise SimpleFINProtocolError(f"SimpleFIN {field} is malformed")
    return number


def sync(conn, access_url: str, days_back: int = 90, *, commit: bool = True) -> dict:
    start = (date.today() - timedelta(days=days_back)).isoformat()
    data = _validate_payload(fetch_accounts(access_url, start_date=start))
    inserted = 0
    balance = (
        _finite_money(data["balance"], "balance")
        if data.get("balance") is not None else None
    )
    accounts = data["accounts"]
    for acct in accounts:
        if acct.get("balance") is not None:
            balance = _finite_money(acct["balance"], "balance")
        account_name = acct.get("name") or acct.get("org", {}).get("name") or "chase-checking"
        transactions = acct.get("transactions", [])
        if not isinstance(transactions, list):
            raise SimpleFINProtocolError("SimpleFIN transactions payload is malformed")
        for txn in transactions:
            if not isinstance(txn, dict):
                raise SimpleFINProtocolError("SimpleFIN transaction payload is malformed")
            tx_date = date.fromtimestamp(txn["posted"]).isoformat() if txn.get("posted") else start
            amount = _finite_money(txn.get("amount", 0), "transaction amount")
            desc = (txn.get("description") or txn.get("payee") or "unknown").strip()
            category = categorize(desc)
            ext_id = txn.get("id") or ""
            h = hashlib.sha256(f"simplefin|{ext_id}|{tx_date}|{amount}|{desc}".encode()).hexdigest()[:20]
            try:
                conn.execute(
                    """INSERT INTO transactions
                       (date, description, amount, category, account, hash, source)
                       VALUES (?,?,?,?,?,?,?)""",
                    (tx_date, desc, amount, category, account_name, h, "simplefin"),
                )
                inserted += 1
            except sqlite3.IntegrityError as exc:
                if not _is_duplicate(exc):
                    raise
    if commit:
        conn.commit()
    return {"inserted": inserted, "balance": balance}


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync Chase checking from SimpleFIN")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()
    access_url = os.environ.get("SIMPLEFIN_ACCESS_URL", "").strip()
    if not configured():
        print("SKIP: SIMPLEFIN_ACCESS_URL not set in .env")
        print("  1. Subscribe at https://bridge.simplefin.org ($1.50/mo)")
        print("  2. Connect Chase checking → create Setup Token")
        print("  3. make setup-simplefin TOKEN=<token>")
        sys.exit(0)
    conn = db.connect()
    try:
        db.record_ingest_attempt(conn, SOURCE)
        result = sync(conn, access_url, args.days, commit=False)
        notes = json.dumps({"balance": result["balance"], "as_of": db.today()}) if result["balance"] is not None else ""
        db.record_ingest_success(conn, SOURCE, result["inserted"], notes)
        bal = result["balance"]
        bal_s = f"${bal:,.2f}" if bal is not None else "unknown"
        print(f"Chase sync: {result['inserted']} new transactions, balance {bal_s}")
    except urllib.error.HTTPError as e:
        conn.rollback()
        db.record_ingest_failure(conn, SOURCE, "auth" if e.code in (401, 403) else "provider_5xx" if e.code >= 500 else "protocol")
        print(f"SimpleFIN HTTP {e.code}")
        if e.code in (401, 403):
            print("Re-run: make setup-simplefin TOKEN=<new-token>")
        sys.exit(1)
    except urllib.error.URLError:
        conn.rollback()
        db.record_ingest_failure(conn, SOURCE, "network")
        print("SimpleFIN network error")
        sys.exit(1)
    except SimpleFINProtocolError:
        conn.rollback()
        db.record_ingest_failure(conn, SOURCE, "protocol")
        print("SimpleFIN protocol error")
        sys.exit(1)
    except Exception:
        conn.rollback()
        db.record_ingest_failure(conn, SOURCE, "protocol")
        print("SimpleFIN sync failed (protocol)")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
