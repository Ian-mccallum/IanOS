"""Sync personal brokerage holdings via SnapTrade.

SnapTrade Personal keys identify their owner directly and use only a client ID
and consumer key.  Commercial keys additionally require a user ID and secret.
The signed HTTP path below supports both modes while the stable SDK catches up
with Personal authentication.
"""

from __future__ import annotations

import argparse
from base64 import b64encode
import hashlib
import hmac
import json
import math
import os
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from core.env import load_dotenv
from core.http import ssl_context

load_dotenv()

SOURCE = "snaptrade_fidelity"
APP_ENV_KEYS = ("SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY")
USER_ENV_KEYS = ("SNAPTRADE_USER_ID", "SNAPTRADE_USER_SECRET")
# Kept as the complete known key set for configuration reporting and callers
# that clear the connector environment in tests.
REQUIRED_ENV_KEYS = APP_ENV_KEYS + USER_ENV_KEYS


class SnapTradeProtocolError(ValueError):
    """The provider result is incomplete or unsafe to publish."""


def missing_config_keys() -> list[str]:
    """Return missing key names only; never expose credential values.

    A Personal key needs only the two app keys. A Commercial configuration is
    valid only when both per-user keys are present. An entirely absent source
    returns the full known set so the orchestrator can distinguish "absent"
    from "partially configured" without knowing credential values.
    """
    present = {
        key: bool(os.environ.get(key, "").strip())
        for key in REQUIRED_ENV_KEYS
    }
    if not any(present.values()):
        return list(REQUIRED_ENV_KEYS)
    missing_app = [key for key in APP_ENV_KEYS if not present[key]]
    if missing_app:
        return missing_app + [key for key in USER_ENV_KEYS if not present[key]]
    user_count = sum(present[key] for key in USER_ENV_KEYS)
    if user_count == 1:
        return [key for key in USER_ENV_KEYS if not present[key]]
    return []


def configured() -> bool:
    return not missing_config_keys()


def _finite_number(value, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SnapTradeProtocolError(f"SnapTrade {field} is malformed") from exc
    if not math.isfinite(number):
        raise SnapTradeProtocolError(f"SnapTrade {field} is malformed")
    return number


def _has_snaptrade_config() -> bool:
    return configured()


def _has_snaptrade_app() -> bool:
    return all(os.environ.get(key, "").strip() for key in APP_ENV_KEYS)


def _commercial_auth() -> bool:
    return all(os.environ.get(key, "").strip() for key in USER_ENV_KEYS)


def _request_json(path: str, *, body: dict | None = None):
    """Make one signed SnapTrade request in Personal or Commercial context."""
    query_items = [
        ("clientId", os.environ["SNAPTRADE_CLIENT_ID"]),
        ("timestamp", str(int(time.time()))),
    ]
    if _commercial_auth():
        query_items.extend([
            ("userId", os.environ["SNAPTRADE_USER_ID"]),
            ("userSecret", os.environ["SNAPTRADE_USER_SECRET"]),
        ])
    query = urlencode(query_items)
    signature_payload = json.dumps(
        {"content": None if not body else body, "path": path, "query": query},
        separators=(",", ":"),
        sort_keys=True,
    )
    signature = b64encode(hmac.new(
        os.environ["SNAPTRADE_CONSUMER_KEY"].encode(),
        signature_payload.encode(),
        hashlib.sha256,
    ).digest()).decode()
    encoded_body = None
    headers = {"Accept": "application/json", "Signature": signature}
    if body:
        encoded_body = json.dumps(body, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    request = Request(
        f"https://api.snaptrade.com{path}?{query}",
        data=encoded_body,
        headers=headers,
        method="POST" if encoded_body is not None else "GET",
    )
    with urlopen(request, context=ssl_context(), timeout=30) as response:
        return json.loads(response.read())


def _get_client():
    from snaptrade_client import SnapTrade
    return SnapTrade(
        consumer_key=os.environ["SNAPTRADE_CONSUMER_KEY"],
        client_id=os.environ["SNAPTRADE_CLIENT_ID"],
    )


def connect() -> None:
    if not _has_snaptrade_app():
        print("SKIP: Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY in .env")
        print("  Register at https://snaptrade.com → create app → copy credentials")
        sys.exit(0)
    if missing_config_keys():
        print("SKIP: SnapTrade configuration is partial in .env")
        return
    user_id = os.environ.get("SNAPTRADE_USER_ID", "").strip()
    user_secret = os.environ.get("SNAPTRADE_USER_SECRET", "").strip()
    if not user_id:
        portal = _request_json(
            "/api/v1/snapTrade/login",
            body={
                "broker": "FIDELITY",
                "connectionType": "read",
                "immediateRedirect": True,
                "customRedirect": "http://localhost:8787/api/snaptrade/callback",
            },
        )
    else:
        client = _get_client()
        # Registration is retained only for an explicitly Commercial setup.
        # Personal keys must never create a second SnapTrade user.
        if not user_secret:
            print("SKIP: SNAPTRADE_USER_SECRET is missing from .env")
            return
        portal = client.authentication.login_snap_trade_user(
            user_id=user_id,
            user_secret=user_secret,
            broker="FIDELITY",
            immediate_redirect=True,
            custom_redirect="http://localhost:8787/api/snaptrade/callback",
        ).body
    url = portal.get("redirectURI") or portal.get("redirectUri") or str(portal)
    print(f"\nOpen this URL to connect Fidelity (read-only):\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print("After OAuth completes, run: make sync-fidelity")


def _infer_subtype(acct_name: str) -> str:
    """Best-effort subtype guess from the account display name alone.

    SnapTrade does not expose a normalized account subtype the way Plaid
    does, and this repo has no live-connected account to inspect real
    naming conventions yet. This heuristic should be revisited once Ian
    actually connects Robinhood/Coinbase/Fidelity via SnapTrade and real
    account names/metadata can be observed.
    """
    name_lower = acct_name.lower()
    if "roth" in name_lower or "ira" in name_lower:
        return "roth"
    if "crypto" in name_lower or "coinbase" in name_lower:
        return "crypto"
    return "brokerage"


def sync_holdings(conn, *, allow_empty: bool = False, commit: bool = True) -> dict:
    accounts = _request_json("/api/v1/accounts")
    positions_out = []
    accounts_out = []
    as_of = db.today()
    account_rows = accounts
    if account_rows is None:
        raise SnapTradeProtocolError("SnapTrade accounts response is malformed")
    if not isinstance(account_rows, list):
        raise SnapTradeProtocolError("SnapTrade accounts response must be a list")
    for acct in account_rows:
        if not isinstance(acct, dict):
            raise SnapTradeProtocolError("SnapTrade account payload is malformed")
        acct_id = acct.get("id") or acct.get("account_id")
        acct_name = acct.get("name") or acct.get("number") or "fidelity"
        if not acct_id:
            raise SnapTradeProtocolError("SnapTrade account is missing an id")
        try:
            pos_resp = _request_json(f"/api/v1/accounts/{acct_id}/positions/all")
        except Exception as e:
            raise SnapTradeProtocolError(f"positions unavailable for {acct_name}") from e
        position_rows = pos_resp.get("results") if isinstance(pos_resp, dict) else None
        if position_rows is None or not isinstance(position_rows, list):
            raise SnapTradeProtocolError(f"positions response malformed for {acct_name}")
        account_key = f"snaptrade:{acct_id}"
        account_balance = 0.0
        for p in position_rows:
            if not isinstance(p, dict):
                raise SnapTradeProtocolError(f"position payload malformed for {acct_name}")
            symbol_obj = p.get("instrument") or {}
            if not isinstance(symbol_obj, dict):
                raise SnapTradeProtocolError(f"symbol payload malformed for {acct_name}")
            symbol = symbol_obj.get("symbol") or symbol_obj.get("raw_symbol") or "?"
            desc = symbol_obj.get("description") or p.get("description") or symbol
            qty = _finite_number(p.get("units") or p.get("quantity") or 0, "quantity")
            price = p.get("price")
            mv = (
                _finite_number(price, "price") * qty
                if price is not None
                else _finite_number(p.get("market_value") or 0, "market value")
            )
            cost = p.get("cost_basis")
            book_value = p.get("book_value")
            cost_basis = (
                _finite_number(cost, "average purchase price") * qty
                if cost is not None
                else _finite_number(book_value, "book value") if book_value is not None else None
            )
            h = hashlib.sha256(f"{acct_id}|{symbol}|{as_of}".encode()).hexdigest()[:20]
            rounded_mv = round(mv, 2)
            account_balance += rounded_mv
            positions_out.append({
                "account": str(acct_name),
                "account_key": account_key,
                "symbol": symbol,
                "description": desc,
                "quantity": qty,
                "cost_basis": cost_basis,
                "market_value": rounded_mv,
                "hash": h,
            })
        # SnapTrade's raw account object has no confirmed balance field
        # (unlike Plaid's `balances.current`), so the sum of this account's
        # own position market values, computed above, is the source of
        # truth for its balance in the registry and the daily snapshot.
        accounts_out.append({
            "account_id": str(acct_id),
            "name": str(acct_name),
            "type": "investment",
            "subtype": _infer_subtype(str(acct_name)),
            "mask": "",
            "balances": {
                "current": round(account_balance, 2),
                "available": None,
                "limit": None,
            },
            "iso_currency_code": "USD",
        })
    if not positions_out:
        status = db.ingest_status(conn, SOURCE)
        already_known_empty = bool(
            status and status.get("last_success") and status.get("row_count") == 0
        )
        if (db.latest_holdings(conn, "snaptrade") and not already_known_empty
                and not allow_empty):
            raise SnapTradeProtocolError(
                "SnapTrade returned an empty portfolio over a previous nonempty snapshot; "
                "use --allow-empty only after verifying the account was intentionally emptied"
            )
        # An empty snapshot has no holding row to persist. The atomic success
        # marker with row_count=0 is current state; historical holdings remain
        # available for audit and portfolio_snapshot() honors that marker.
        if commit:
            conn.commit()
        return {"positions": 0, "total": 0}
    # A single stable item_key ("fidelity") groups every SnapTrade-sourced
    # account together, so re-syncs correctly replace stale accounts via
    # upsert_financial_accounts's own DELETE...NOT IN behavior. Registry and
    # snapshot writes land in the same uncommitted transaction as the
    # holdings replace below, so `commit` still gates them atomically.
    db.upsert_financial_accounts(conn, "snaptrade", "fidelity", "SnapTrade", accounts_out, as_of=as_of)
    for acct_out in accounts_out:
        db.record_balance_snapshot(
            conn, source="snaptrade", external_id=acct_out["account_id"],
            date=as_of, current=acct_out["balances"]["current"], available=None,
        )
    n = db.replace_holdings_snapshot(conn, as_of, positions_out, "snaptrade", commit=commit)
    return {"positions": n, "total": round(sum(p["market_value"] for p in positions_out), 2)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync connected brokerage portfolio via SnapTrade")
    ap.add_argument("--connect", action="store_true", help="Start Fidelity OAuth flow")
    ap.add_argument(
        "--allow-empty", action="store_true",
        help="Publish a verified, intentionally empty connected portfolio",
    )
    args = ap.parse_args()
    if args.connect:
        connect()
        return
    if not configured():
        print("SKIP: SnapTrade credentials not complete in .env")
        print("  Personal: set SNAPTRADE_CLIENT_ID + SNAPTRADE_CONSUMER_KEY")
        print("  Commercial: also set SNAPTRADE_USER_ID + SNAPTRADE_USER_SECRET")
        sys.exit(0)
    conn = None
    try:
        conn = db.connect()
        db.record_ingest_attempt(conn, SOURCE)
        result = sync_holdings(conn, allow_empty=args.allow_empty, commit=False)
        db.record_ingest_success(conn, SOURCE, result["positions"], f"{result['positions']} positions")
        print(f"SnapTrade sync: {result['positions']} positions")
    except ImportError:
        if conn is not None:
            conn.rollback()
            db.record_ingest_failure(conn, SOURCE, "protocol")
        print("SnapTrade sync failed: snaptrade-python-sdk is not installed")
        sys.exit(1)
    except SnapTradeProtocolError:
        if conn is not None:
            conn.rollback()
            db.record_ingest_failure(conn, SOURCE, "protocol")
        print("SnapTrade sync failed (protocol)")
        sys.exit(1)
    except Exception:
        if conn is not None:
            conn.rollback()
            db.record_ingest_failure(conn, SOURCE, "protocol")
        print("SnapTrade sync failed (protocol)")
        print("Re-run: make connect-fidelity")
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
