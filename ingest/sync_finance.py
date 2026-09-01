"""Run every configured finance source independently and record its health."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, freshness, push
from core.env import load_dotenv
from ingest import sync_chase, sync_fidelity, sync_plaid

import os

load_dotenv()


def _is_absent(module) -> bool:
    return len(module.missing_config_keys()) == len(module.REQUIRED_ENV_KEYS)


def configuration_errors() -> list[str]:
    """Return safe messages containing missing key names, never values."""
    errors: list[str] = []
    for label, module in (("SimpleFIN", sync_chase), ("SnapTrade", sync_fidelity)):
        missing = module.missing_config_keys()
        if missing and not _is_absent(module):
            errors.append(f"{label} partial configuration; missing: {', '.join(missing)}")
    plaid_missing = sync_plaid.plaid.missing_config_keys()
    if plaid_missing and len(plaid_missing) < len(sync_plaid.plaid.APP_ENV_KEYS):
        errors.append(f"Plaid partial configuration; missing: {', '.join(plaid_missing)}")
    if (not sync_chase.configured() and not sync_fidelity.configured()
            and not any(sync_plaid.plaid.item_configured(key) for key in sync_plaid.plaid.ITEM_KEYS)
            and not errors):
        errors.append(
            "No finance source configured; add SIMPLEFIN_ACCESS_URL or "
            "SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY, or link Plaid"
        )
    return errors


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "auth"
        return "provider_5xx" if exc.code >= 500 else "protocol"
    if isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError)):
        return "network"
    if isinstance(exc, (sync_chase.SimpleFINProtocolError,
                        sync_fidelity.SnapTradeProtocolError,
                        sync_plaid.PlaidSyncError, sync_plaid.plaid.PlaidProtocolError,
                        sync_plaid.plaid.PlaidConfigurationError,
                        json.JSONDecodeError, ValueError, KeyError, TypeError)):
        return "protocol"
    if isinstance(exc, sync_plaid.plaid.PlaidHTTPError):
        if exc.status in (401, 403):
            return "auth"
        return "provider_5xx" if exc.status >= 500 else "protocol"
    status = getattr(exc, "status", None) or getattr(exc, "status_code", None)
    if status in (401, 403):
        return "auth"
    if isinstance(status, int) and status >= 500:
        return "provider_5xx"
    # Never persist or print provider exception text; it may include a URL or
    # response body. Unknown failures receive the nearest safe classification.
    return "protocol"


def _sync_one(conn, label: str, source: str, loader) -> dict:
    db.record_ingest_attempt(conn, source)
    try:
        result = loader()
        row_count = int(result["inserted"] if "inserted" in result else result["positions"])
        if source == sync_chase.SOURCE:
            balance = result.get("balance")
            notes = json.dumps({"balance": balance, "as_of": db.today()}) if balance is not None else ""
        elif source == sync_fidelity.SOURCE:
            notes = f"{row_count} positions"
        else:
            notes = f"{result.get('accounts', 0)} accounts"
        # The loader left source writes pending. This commit publishes source
        # data and the corresponding success timestamp as one transaction.
        db.record_ingest_success(conn, source, row_count, notes)
        return {"source": label, "status": "ok", "rows": row_count}
    except Exception as exc:
        conn.rollback()
        code = _classify_error(exc)
        db.record_ingest_failure(conn, source, code)
        return {"source": label, "status": "failed", "error": code}


def _stale_alert(conn, configured_sources: dict[str, bool], now: datetime | None = None) -> list[str]:
    """Claim and send one generic aggregate alert for a stale incident."""
    if not push.configured():
        return []
    now = now or datetime.now()
    stale = []
    for source, is_configured in configured_sources.items():
        state = freshness.evaluate(db.ingest_status(conn, source), is_configured, now)
        if state == "stale":
            stale.append(source)
    claimed = db.claim_stale_ingest_alerts(conn, stale)
    if not claimed:
        return []
    labels = {
        sync_chase.SOURCE: "SimpleFIN",
        sync_fidelity.SOURCE: "SnapTrade",
        "plaid_chase": "Plaid Chase",
        "plaid_capital_one": "Plaid Capital One",
    }
    source_names = ", ".join(labels.get(source, source) for source in claimed)
    push.send(
        "ianOS finance data is stale",
        f"No successful finance refresh within 48 hours: {source_names}. Checked {now.isoformat(timespec='minutes')}.",
    )
    return claimed


def _run_configured_source(label: str, source: str, loader) -> dict:
    conn = db.connect()
    try:
        return _sync_one(conn, label, source, lambda: loader(conn))
    finally:
        conn.close()


def _record_partial_configuration(label: str, source: str) -> dict:
    conn = db.connect()
    try:
        db.record_ingest_attempt(conn, source)
        db.record_ingest_failure(conn, source, "protocol")
        return {"source": label, "status": "failed", "error": "configuration"}
    finally:
        conn.close()


def run() -> list[dict]:
    reports: list[dict] = []
    if sync_chase.configured():
        access_url = os.environ["SIMPLEFIN_ACCESS_URL"].strip()
        reports.append(_run_configured_source(
            "SimpleFIN", sync_chase.SOURCE,
            lambda conn: sync_chase.sync(conn, access_url, commit=False),
        ))
    elif _is_absent(sync_chase):
        reports.append({"source": "SimpleFIN", "status": "skipped"})
    else:
        reports.append(_record_partial_configuration("SimpleFIN", sync_chase.SOURCE))

    if sync_fidelity.configured():
        reports.append(_run_configured_source(
            "SnapTrade", sync_fidelity.SOURCE,
            lambda conn: sync_fidelity.sync_holdings(conn, commit=False),
        ))
    elif _is_absent(sync_fidelity):
        reports.append({"source": "SnapTrade", "status": "skipped"})
    else:
        reports.append(_record_partial_configuration("SnapTrade", sync_fidelity.SOURCE))

    if sync_plaid.plaid.configured():
        for item_key, label in sync_plaid.ITEM_LABELS.items():
            source = sync_plaid.source_for(item_key)
            if sync_plaid.plaid.item_configured(item_key):
                reports.append(_run_configured_source(
                    f"Plaid {label}", source,
                    lambda conn, key=item_key: sync_plaid.sync_item(conn, key, commit=False),
                ))
            else:
                reports.append({"source": f"Plaid {label}", "status": "skipped"})

    # Alert evaluation/claim gets its own clean transaction boundary too.
    alert_conn = db.connect()
    try:
        _stale_alert(alert_conn, {
            sync_chase.SOURCE: sync_chase.configured(),
            sync_fidelity.SOURCE: sync_fidelity.configured(),
            "plaid_chase": sync_plaid.plaid.item_configured("chase"),
            "plaid_capital_one": sync_plaid.plaid.item_configured("capital_one"),
        })
    finally:
        alert_conn.close()
    return reports


def main() -> None:
    ap = argparse.ArgumentParser(description="Sync all configured finance sources independently")
    ap.add_argument(
        "--check-configured", action="store_true",
        help="Refuse absent or partial finance configuration without network access",
    )
    args = ap.parse_args()
    if args.check_configured:
        errors = configuration_errors()
        if errors:
            for error in errors:
                print(error)
            raise SystemExit(1)
        print("Finance source configuration is complete")
        return

    reports = run()
    for report in reports:
        if report["status"] == "ok":
            print(f"{report['source']}: ok ({report['rows']} rows)")
        elif report["status"] == "skipped":
            print(f"{report['source']}: skipped (not configured)")
        else:
            print(f"{report['source']}: failed ({report['error']})")
    raise SystemExit(1 if any(r["status"] == "failed" for r in reports) else 0)


if __name__ == "__main__":
    main()
