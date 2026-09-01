"""BtC inbound sync: the ONLY writer on the beatyourclock.com seam (SPEC-v17).

Pulls unacked demo bookings + contact messages from the site's holding pen
(api/ianos-inbox on Vercel), matches or creates the lead, writes
`inbound_requests`, COMMITS, and only then acks, so a crash between write and
ack just re-delivers into an INSERT OR IGNORE. At-least-once delivery plus an
idempotent loader: nothing is lost across sleep, a dead week, or a laptop
migration.

    .venv/bin/python ingest/sync_btc.py                    # BTC pull + load + ack
    .venv/bin/python ingest/sync_btc.py --all-configured   # every configured seam
    .venv/bin/python ingest/sync_btc.py --dry-run           # BTC validate, no writes/ack

Hard rules (enforced here, not in prompts):
  * Lead identity: phone_norm first, then exact email, then a hashed key so
    phone_norm is never NULL (the import_leads lesson).
  * NEVER touches tier/fit/pain/reach/miss_signal on any lead, matched or
    created: scoring belongs to enrich_prospects.py.
  * The consent block lands only in inbound_requests.consent. The system memo
    announcing arrivals carries names, never consent, message bodies, or phone.
  * Unconfigured (.env lacks BTC_SYNC_URL/BTC_SYNC_TOKEN) is exit 2 with
    instructions, the plan-sync precedent.

Exit codes: 0 = synced (even zero-new) · 1 = network/protocol failure ·
2 = no configured seam.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, promises, push
from core.env import load_dotenv
from core.leads import norm_phone

VALID_KINDS = ("demo", "contact")

# The two seams. One loader, because they differ only in where they pull from
# and whether the record is a lead: duplicating this file for a second site
# would mean two places to fix the next dedupe or consent bug (SPEC-v19).
SEAMS = {
    "btc": {
        "site": "beatyourclock.com", "surface": "BtC tab",
        "url_var": "BTC_SYNC_URL", "token_var": "BTC_SYNC_TOKEN",
        "memo_topic": "btc-inbound",
    },
    "personal": {
        "site": "ianmccallum.com", "surface": "Inbox",
        "url_var": "PERSONAL_SYNC_URL", "token_var": "PERSONAL_SYNC_TOKEN",
        "memo_topic": "personal-inbound",
    },
}


class Reject(Exception):
    """One record failed validation; the batch continues (from_connector pattern)."""


def _clean(rec: dict, field: str, max_len: int = 2000) -> str:
    return str(rec.get(field) or "").strip()[:max_len]


def validate(rec: dict) -> dict:
    """Normalize one site record into an insert-ready dict. Raises Reject."""
    if not isinstance(rec, dict):
        raise Reject("record is not an object")
    request_id = _clean(rec, "request_id", 64)
    if len(request_id) < 8:
        raise Reject("missing/short request_id")
    kind = _clean(rec, "kind", 16)
    if kind not in VALID_KINDS:
        raise Reject(f"kind must be one of {VALID_KINDS}")
    email = _clean(rec, "email", 200)
    name = _clean(rec, "name", 200)
    if not email and not name:
        raise Reject("record carries neither email nor name")

    topics = rec.get("topics") or []
    windows = rec.get("windows") or []
    if not isinstance(topics, list) or not isinstance(windows, list):
        raise Reject("topics/windows must be lists")

    received = _clean(rec, "received_at_utc", 40) or db.today()

    return {
        "request_id": request_id,
        "kind": kind,
        "name": name,
        "company": _clean(rec, "company", 200),
        "email": email,
        "phone": _clean(rec, "phone", 40),
        "topics": json.dumps([str(t)[:100] for t in topics][:10]),
        "windows": json.dumps([
            {"date": str(w.get("date") or "")[:10] or None,
             "window": str(w.get("window") or "")[:20],
             "label": str(w.get("label") or "")[:120]}
            for w in windows if isinstance(w, dict)
        ][:3]),
        "interest": _clean(rec, "interest", 200),
        "message": _clean(rec, "message", 5000),
        "consent": json.dumps(rec.get("consent") or {}),
        "received_at": received,
        # Stored, not derived: a deadline recomputed from "now" cannot be
        # alerted on exactly once (SPEC-v18 law 3).
        "promised_by": promises.promised_by(received),
    }


def _hashed_key(email: str, name: str) -> str:
    """Stable never-NULL phone_norm for a phoneless inbound lead (D4).
    Same trick as import_leads.lead_key, keyed on what an inbound has."""
    seed = f"{email.strip().lower()}|{name.strip().lower()}"
    return "x" + hashlib.sha256(seed.encode()).hexdigest()[:15]


def match_or_create_lead(conn, rec: dict) -> int:
    """Phone first, then email, then create. The payoff case: Ian cold-called
    them Tuesday, they booked on the site Thursday; it must be the same row."""
    phone_norm = norm_phone(rec["phone"]) if rec["phone"] else ""
    if phone_norm:
        row = conn.execute(
            "SELECT id FROM leads WHERE phone_norm=?", (phone_norm,)).fetchone()
        if row:
            return row["id"]
    if rec["email"]:
        row = conn.execute(
            "SELECT id FROM leads WHERE email != '' AND lower(email)=lower(?) "
            "ORDER BY id LIMIT 1", (rec["email"],)).fetchone()
        if row:
            return row["id"]

    # New lead. Scoring columns keep their defaults (tier C, zeros): scoring
    # is enrich_prospects.py's job and an inbound never fabricates one.
    key = phone_norm or _hashed_key(rec["email"], rec["name"])
    cur = conn.execute(
        """INSERT INTO leads (phone_norm, phone, business_name, owner_name,
                              email, source)
           VALUES (?, ?, ?, ?, ?, 'beatyourclock.com')""",
        (key, rec["phone"], rec["company"] or rec["name"], rec["name"],
         rec["email"]),
    )
    return cur.lastrowid


def load_records(conn, records: list, dry_run: bool = False,
                 source: str = "btc") -> dict:
    """Validate + write a batch. Returns counts and the ids safe to ack.
    Pure function over (conn, records): the tests drive this directly.

    `source` decides the two things that separate the seams (SPEC-v19):
    a personal inquiry never gets a leads row, and never gets a promise
    clock, because ianmccallum.com makes no public 24-hour promise.
    """
    loaded, deduped, rejected, ackable, names = 0, 0, [], [], []
    for rec in records:
        try:
            clean = validate(rec)
        except Reject as e:
            rejected.append(f"{(rec or {}).get('request_id', '?')}: {e}")
            continue
        clean["source"] = source
        if source != "btc":
            # Correspondence, not a lead. No match, no create, no deadline.
            clean["lead_id"] = None
            clean["promised_by"] = None
        if dry_run:
            exists = conn.execute(
                "SELECT 1 FROM inbound_requests WHERE request_id=?",
                (clean["request_id"],)).fetchone()
            deduped, loaded = deduped + bool(exists), loaded + (not bool(exists))
            continue
        if source == "btc":
            clean["lead_id"] = match_or_create_lead(conn, clean)
        if db.insert_inbound(conn, clean):
            loaded += 1
            names.append(f"{clean['name'] or clean['email']}"
                         f"{' (' + clean['company'] + ')' if clean['company'] else ''}")
        else:
            deduped += 1
        ackable.append(clean["request_id"])

    if not dry_run:
        if loaded:
            seam = SEAMS[source]
            db.add_memo(conn, "system", seam["memo_topic"],
                        f"{loaded} new from {seam['site']}: {', '.join(names[:5])}"
                        f"{' …' if len(names) > 5 else ''}. On the {seam['surface']}.",
                        priority=2)
        conn.commit()   # durable BEFORE ack; a crash here just re-delivers
    return {"loaded": loaded, "deduped": deduped, "rejected": rejected,
            "ackable": ackable}


# ------------------------------------------------------------- network edge

def _config_state(source: str) -> tuple[str, tuple[str, str] | None]:
    """Return configured | absent | partial without ever exposing a token."""
    seam = SEAMS[source]
    url = os.environ.get(seam["url_var"], "").strip()
    token = os.environ.get(seam["token_var"], "").strip()
    if url and token:
        return "configured", (url, token)
    if url or token:
        return "partial", None
    return "absent", None


def _config(source: str = "btc") -> tuple[str, str] | None:
    return _config_state(source)[1]


def configured_seams() -> list[str]:
    """Complete inbound seams only; optional absent seams stay quiet."""
    return [source for source in SEAMS if _config_state(source)[0] == "configured"]


def _config_error(source: str) -> str:
    seam = SEAMS[source]
    return f"partial_config:{seam['url_var']}+{seam['token_var']}"


def _error_code(exc: Exception) -> str:
    """Small, credential-safe process vocabulary for scheduled reports."""
    try:
        import requests
        if isinstance(exc, requests.RequestException):
            return "network"
    except ImportError:  # pragma: no cover - requests is a direct dependency
        pass
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "protocol"
    if isinstance(exc, RuntimeError):
        return "configuration"
    return "unexpected"


def _counts(report: dict) -> dict:
    """A scheduled report is operational metadata, never inbound contents."""
    return {
        "loaded": int(report.get("loaded", 0)),
        "deduped": int(report.get("deduped", 0)),
        "rejected": len(report.get("rejected", [])),
        "acked": int(report.get("acked", 0)),
    }


def fetch_records(url: str, token: str) -> list:
    import requests
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not isinstance(body, dict) or not isinstance(body.get("records"), list):
        raise ValueError("malformed response: no records list")
    return body["records"]


def ack_records(url: str, token: str, ids: list[str]) -> int:
    import requests
    if not ids:
        return 0
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json={"ack": ids}, timeout=15)
    r.raise_for_status()
    return int(r.json().get("acked", 0))


def alert_due(conn, now=None) -> dict:
    """The jeopardy push (SPEC-v18): fire when a promise is about to break and
    Ian has not handled it. Deterministic, no model, $0. Runs after the pull so
    a request that arrived 20 hours ago can alert on the very sync that fetched
    it. Silence when nothing is due is the normal case and the point."""
    now = now or datetime.now()
    due = promises.due_for_alert(db.pending_promises(conn), now)
    if not due:
        return {"alerted": 0}
    title, body = promises.alert_text(due)
    sent = push.send(title, body) if push.configured() else False
    # Stamp regardless of delivery: retrying a push every 15 minutes for a
    # promise that is already late is the nag this product bans, and the card
    # is on the BtC tab either way.
    db.mark_alerted(conn, [r["id"] for r in due])
    return {"alerted": len(due), "pushed": sent}


def sync(conn, dry_run: bool = False, source: str = "btc") -> dict:
    cfg = _config(source)
    if not cfg:
        raise RuntimeError("not configured")
    url, token = cfg
    records = fetch_records(url, token)
    report = load_records(conn, records, dry_run=dry_run, source=source)
    if not dry_run:
        report["acked"] = ack_records(url, token, report["ackable"])
        # The promise clock only exists on the btc seam; a personal inquiry
        # has no public deadline to be late on (SPEC-v19 law 3).
        if source == "btc":
            report.update(alert_due(conn))
    return report


def sync_all(dry_run: bool = False) -> dict:
    """Run each fully configured inbound seam independently.

    Each source receives its own connection and transaction boundary. A failed
    BtC pull therefore cannot leave personal correspondence uncollected (and
    vice versa); each individual `sync()` still commits before acknowledging.
    """
    reports: list[dict] = []
    complete: list[str] = []
    for source in SEAMS:
        state, _cfg = _config_state(source)
        if state == "configured":
            complete.append(source)
        elif state == "partial":
            reports.append({
                "source": source,
                "status": "failed",
                "counts": {},
                "error_code": _config_error(source),
            })
        else:
            reports.append({
                "source": source,
                "status": "skipped",
                "counts": {},
                "error_code": None,
            })

    for source in complete:
        conn = None
        try:
            conn = db.connect()
            result = sync(conn, dry_run=dry_run, source=source)
            reports.append({
                "source": source,
                "status": "ok",
                "counts": _counts(result),
                "error_code": None,
            })
        except Exception as exc:
            reports.append({
                "source": source,
                "status": "failed",
                "counts": {},
                "error_code": _error_code(exc),
            })
        finally:
            if conn is not None:
                conn.close()

    # Stable seam order makes launchd output predictable and testable.
    reports.sort(key=lambda report: list(SEAMS).index(report["source"]))
    return {
        "reports": reports,
        "configured": len(complete),
        "failed": sum(report["status"] == "failed" for report in reports),
    }


def all_configured_exit_code(report: dict) -> int:
    """CLI/scheduler contract: quiet absence is code 2; any fault is code 1."""
    if report["failed"]:
        return 1
    return 0 if report["configured"] else 2


def check_all_configured() -> dict:
    """Validate scheduler configuration without touching either website."""
    reports = []
    for source in SEAMS:
        state, _cfg = _config_state(source)
        reports.append({
            "source": source,
            "status": "ok" if state == "configured" else ("failed" if state == "partial" else "skipped"),
            "counts": {},
            "error_code": _config_error(source) if state == "partial" else None,
        })
    return {
        "reports": reports,
        "configured": sum(report["status"] == "ok" for report in reports),
        "failed": sum(report["status"] == "failed" for report in reports),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--source", choices=sorted(SEAMS),
                      help="which site to pull from (default: btc)")
    mode.add_argument("--all-configured", action="store_true",
                      help="sync every seam with a complete URL/token pair")
    mode.add_argument("--check-all-configured", action="store_true",
                      help="validate scheduler credentials without a network call")
    args = ap.parse_args()

    load_dotenv()
    if args.check_all_configured:
        report = check_all_configured()
        for item in report["reports"]:
            print(f"{item['source']}: {item['status']}"
                  + (f" ({item['error_code']})" if item["error_code"] else ""))
        return all_configured_exit_code(report)

    if args.all_configured:
        report = sync_all(dry_run=args.dry_run)
        for item in report["reports"]:
            counts = item["counts"]
            detail = (
                f"loaded {counts['loaded']} · deduped {counts['deduped']} · "
                f"rejected {counts['rejected']} · acked {counts['acked']}"
                if counts else item["error_code"] or "not configured"
            )
            print(f"{item['source']}: {item['status']} · {detail}")
        return all_configured_exit_code(report)

    source = args.source or "btc"
    state, _cfg = _config_state(source)
    if state != "configured":
        seam = SEAMS[source]
        if state == "partial":
            print(f"Partial configuration: set both {seam['url_var']} and {seam['token_var']}.",
                  file=sys.stderr)
        else:
            print(f"Not configured. Add to ianOS/.env (see docs/SPEC-v17-btc-inbound.md):\n"
                  f"  {seam['url_var']}=https://www.{seam['site']}/api/ianos-inbox\n"
                  f"  {seam['token_var']}=<same token as IANOS_SYNC_TOKEN on Vercel>",
                  file=sys.stderr)
        return 2

    conn = db.connect()
    try:
        report = sync(conn, dry_run=args.dry_run, source=source)
    except Exception as exc:
        print(f"sync failed: {_error_code(exc)}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    tag = "DRY RUN · " if args.dry_run else ""
    print(f"{tag}loaded {report['loaded']} · deduped {report['deduped']}"
          f" · rejected {len(report['rejected'])}"
          + (f" · acked {report.get('acked', 0)}" if not args.dry_run else "")
          + (f" · alerted {report['alerted']}" if report.get("alerted") else ""))
    for line in report["rejected"]:
        print(f"  rejected: {line}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
