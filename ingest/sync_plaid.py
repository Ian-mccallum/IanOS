"""Read-only Plaid sync for Chase and Capital One bank/card accounts."""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, plaid
from core.env import load_dotenv
from ingest.categorize import categorize

load_dotenv()

ITEM_LABELS = {"chase": "Chase", "capital_one": "Capital One"}


class PlaidSyncError(ValueError):
    """A Plaid payload cannot safely change local financial records."""


def source_for(item_key: str) -> str:
    if item_key not in ITEM_LABELS:
        raise PlaidSyncError("unknown Plaid item")
    return f"plaid_{item_key}"


def _finite(value, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PlaidSyncError(f"Plaid {field} is malformed") from exc
    if not math.isfinite(number):
        raise PlaidSyncError(f"Plaid {field} is malformed")
    return number


def _optional_float(value) -> float | None:
    """Best-effort numeric coercion for liabilities fields: bad/missing data
    yields None rather than raising, matching this file's defensive style."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _card_apr(aprs) -> float | None:
    """Plaid returns a list of APR objects; prefer purchase_apr, else fall
    back to the first entry's percentage, defensively."""
    if not isinstance(aprs, list):
        return None
    candidates = [entry for entry in aprs if isinstance(entry, dict)]
    if not candidates:
        return None
    chosen = next((entry for entry in candidates if entry.get("apr_type") == "purchase_apr"), candidates[0])
    return _optional_float(chosen.get("apr_percentage"))


def _transaction_values(item_key: str, transaction: dict, account_names: dict[str, str]) -> tuple[str, dict]:
    transaction_id = str(transaction.get("transaction_id") or "").strip()
    account_id = str(transaction.get("account_id") or "").strip()
    if not transaction_id or not account_id:
        raise PlaidSyncError("Plaid transaction is missing an id")
    try:
        transaction_date = date.fromisoformat(str(transaction.get("date") or "")).isoformat()
    except ValueError as exc:
        raise PlaidSyncError("Plaid transaction date is malformed") from exc
    description = str(transaction.get("merchant_name") or transaction.get("name") or "unknown").strip()
    if not description:
        description = "unknown"
    # Plaid treats money leaving an account as positive; ianOS stores expenses
    # as negative so existing burn calculations stay correct.
    amount = -_finite(transaction.get("amount"), "transaction amount")
    return transaction_id, {
        "date": transaction_date,
        "description": description,
        "amount": amount,
        "category": categorize(description),
        "account": account_names.get(account_id, "Plaid account"),
        "account_key": f"{source_for(item_key)}:{account_id}",
        "hash": hashlib.sha256(f"plaid|{item_key}|{transaction_id}".encode()).hexdigest()[:20],
        "source": source_for(item_key),
    }


def _ensure_item(conn, item_key: str) -> dict:
    existing = db.plaid_item(conn, item_key)
    if existing:
        return existing
    record = plaid.item(item_key)
    item_id = str(record.get("item_id") or "").strip()
    if not item_id:
        raise PlaidSyncError("Plaid item is missing an id")
    db.upsert_plaid_item(
        conn, item_key, item_id,
        institution_id=str(record.get("institution_id") or ""),
        institution_name=ITEM_LABELS[item_key],
    )
    return db.plaid_item(conn, item_key) or {}


def sync_item(conn, item_key: str, *, commit: bool = True) -> dict:
    source = source_for(item_key)
    if not plaid.item_configured(item_key):
        raise plaid.PlaidConfigurationError("Plaid item is not configured")
    item = _ensure_item(conn, item_key)
    account_rows = plaid.accounts(item_key)
    account_names = {
        str(account.get("account_id")): str(account.get("name") or "Plaid account")
        for account in account_rows if isinstance(account, dict) and account.get("account_id")
    }

    initial_cursor = str(item.get("cursor") or "")
    cursor = initial_cursor
    added: list[dict] = []
    modified: list[dict] = []
    removed: list[dict] = []
    while True:
        page = plaid.transactions_sync(item_key, cursor)
        added.extend(page["added"])
        modified.extend(page["modified"])
        removed.extend(page["removed"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break

    institution = str(item.get("institution_name") or ITEM_LABELS[item_key])
    db.upsert_financial_accounts(conn, source, item_key, institution, account_rows, as_of=db.now())
    snapshot_date = db.today()
    for account in account_rows:
        if not isinstance(account, dict):
            continue
        external_id = str(account.get("account_id") or "").strip()
        if not external_id:
            continue
        balances = account.get("balances")
        if not isinstance(balances, dict):
            continue
        try:
            current = float(balances["current"]) if balances.get("current") is not None else None
            available = float(balances["available"]) if balances.get("available") is not None else None
        except (TypeError, ValueError, KeyError):
            continue
        db.record_balance_snapshot(conn, source, external_id, snapshot_date, current, available)

    # Liabilities is a separate Plaid product that existing items may not have
    # granted (Link was originally requested with only "transactions"). Only
    # bother asking when a credit account is present, and never let a failure
    # here touch the transactions/snapshots work already done above.
    has_credit_account = any(
        isinstance(account, dict) and str(account.get("type") or "") == "credit"
        for account in account_rows
    )
    if has_credit_account:
        try:
            liabilities_response = plaid.liabilities(item_key)
            for entry in liabilities_response.get("liabilities", {}).get("credit", []):
                if not isinstance(entry, dict):
                    continue
                account_id = str(entry.get("account_id") or "").strip()
                if not account_id:
                    continue
                due_date = entry.get("next_payment_due_date")
                db.upsert_card_liabilities(
                    conn, source, account_id,
                    statement_balance=_optional_float(entry.get("last_statement_balance")),
                    minimum_payment=_optional_float(entry.get("minimum_payment_amount")),
                    due_date=str(due_date) if due_date else None,
                    apr=_card_apr(entry.get("aprs")),
                    is_overdue=bool(entry.get("is_overdue")),
                )
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see comment above
            print(f"liabilities not available for {item_key} (product may not be linked): {type(exc).__name__}")

    inserted = 0
    for transaction in [*added, *modified]:
        if not isinstance(transaction, dict):
            raise PlaidSyncError("Plaid transaction payload is malformed")
        pending_id = str(transaction.get("pending_transaction_id") or "").strip()
        if pending_id:
            db.remove_plaid_transaction(conn, item_key, pending_id)
        transaction_id, values = _transaction_values(item_key, transaction, account_names)
        inserted += int(db.upsert_plaid_transaction(conn, item_key, transaction_id, values))
    for transaction in removed:
        if not isinstance(transaction, dict) or not str(transaction.get("transaction_id") or "").strip():
            raise PlaidSyncError("Plaid removed transaction payload is malformed")
        db.remove_plaid_transaction(conn, item_key, str(transaction["transaction_id"]))
    db.update_plaid_cursor(conn, item_key, cursor)
    if commit:
        conn.commit()
    return {"inserted": inserted, "accounts": len(account_rows), "removed": len(removed)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync connected Plaid bank/card items")
    parser.add_argument("--item", choices=plaid.ITEM_KEYS, help="Sync only one connected item")
    args = parser.parse_args()
    keys = (args.item,) if args.item else plaid.ITEM_KEYS
    any_failed = False
    for item_key in keys:
        if not plaid.item_configured(item_key):
            print(f"{ITEM_LABELS[item_key]}: skipped (not linked)")
            continue
        conn = db.connect()
        try:
            source = source_for(item_key)
            db.record_ingest_attempt(conn, source)
            result = sync_item(conn, item_key, commit=False)
            db.record_ingest_success(conn, source, result["inserted"], f"{result['accounts']} accounts")
            print(f"{ITEM_LABELS[item_key]}: ok ({result['inserted']} new transactions)")
        except (plaid.PlaidConfigurationError, plaid.PlaidProtocolError, PlaidSyncError):
            conn.rollback()
            db.record_ingest_failure(conn, source_for(item_key), "protocol")
            print(f"{ITEM_LABELS[item_key]}: failed (configuration or protocol)")
            any_failed = True
        except plaid.PlaidHTTPError as exc:
            conn.rollback()
            code = "auth" if exc.status in (401, 403) else "provider_5xx" if exc.status >= 500 else "protocol"
            db.record_ingest_failure(conn, source_for(item_key), code)
            print(f"{ITEM_LABELS[item_key]}: failed ({code})")
            any_failed = True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            conn.rollback()
            db.record_ingest_failure(conn, source_for(item_key), "network")
            print(f"{ITEM_LABELS[item_key]}: failed (network)")
            any_failed = True
        finally:
            conn.close()
    raise SystemExit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
