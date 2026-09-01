"""Connector sync loader: the ONLY writer on the Claude-connector seam.

A Claude session (which has the Gmail/Calendar/Drive connectors) READS and
shapes a strict JSON payload; this CLI validates, dedupes, and writes it into
the native ianOS tables. See docs/SPEC-v4-connector-sync.md.

    .venv/bin/python ingest/from_connector.py --source gmail < payload.json
    .venv/bin/python ingest/from_connector.py --source calendar --dry-run --file payload.json

Payload: {"records": [ {"kind": "calendar_event"|"fact"|"document"|"note", ...} ]}

Hard rules (enforced here, not in prompts):
  * NEVER writes transactions: bank CSV/SimpleFIN is the money source of truth.
  * Connector facts are born unverified (verified=0), whatever the payload says.
  * Connector notes are pinned to priority 1, synced email can't shout.
  * Idempotent: re-piping the same payload changes zero rows.
  * Table surface is exactly: calendar_events, facts, documents, memos, ingest_log.

Exit codes: 0 = loaded (or valid --dry-run) · 1 = malformed payload · 2 = every
record rejected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from ingest.import_calendar import _categorize

SOURCES = ("calendar", "gmail", "drive")
NOTE_PREFIXES = ("email: ", "calendar: ", "drive: ")
NOTE_PREFIX_FOR_SOURCE = {"gmail": "email: ", "calendar": "calendar: ", "drive": "drive: "}
NOTE_BODY_MAX = 500
KINDS = ("calendar_event", "fact", "document", "note")


class Reject(Exception):
    """A single record failed validation; the batch continues."""


def _iso_date(value, field: str) -> str:
    if not isinstance(value, str):
        raise Reject(f"{field} must be an ISO date string (YYYY-MM-DD)")
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise Reject(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}")


def _hhmm(value, field: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise Reject(f"{field} must be 'HH:MM' or null")
    try:
        datetime.strptime(value.strip(), "%H:%M")
    except ValueError:
        raise Reject(f"{field} must be 'HH:MM' or null, got {value!r}")
    return value.strip()


def _text(rec: dict, field: str, required: bool = True) -> str:
    val = str(rec.get(field) or "").strip()
    if required and not val:
        raise Reject(f"missing required field '{field}'")
    return val


# ------------------------------------------------------------- per-kind loads
# Each returns a status string: "loaded" | "deduped".

def _load_calendar_event(rec: dict, source: str, conn, dry_run: bool) -> str:
    day = _iso_date(rec.get("date"), "date")
    summary = _text(rec, "summary")
    start = _hhmm(rec.get("start_time"), "start_time")
    end = _hhmm(rec.get("end_time"), "end_time")
    category = str(rec.get("category") or "").strip().lower() or _categorize(summary)
    if start and end:
        s = datetime.strptime(f"{day} {start}", "%Y-%m-%d %H:%M")
        e = datetime.strptime(f"{day} {end}", "%Y-%m-%d %H:%M")
        duration = max(0, int((e - s).total_seconds() / 60))
    else:
        duration = 60
    # hash matches ingest/import_calendar.py exactly (start may be None)
    h = hashlib.sha256(f"{day}|{start}|{summary}".encode()).hexdigest()[:20]
    exists = conn.execute("SELECT 1 FROM calendar_events WHERE hash = ?", (h,)).fetchone()
    if dry_run:
        return "deduped" if exists else "loaded"
    db.upsert_calendar_event(conn, date=day, start_time=start, end_time=end,
                             summary=summary, category=category,
                             duration_min=duration, hash=h)
    conn.commit()
    return "deduped" if exists else "loaded"


def _load_fact(rec: dict, source: str, conn, dry_run: bool) -> str:
    topic = _text(rec, "topic")
    body = _text(rec, "body")
    fact_kind = _text(rec, "fact_kind")
    if fact_kind not in db.FACT_KINDS:
        raise Reject(f"fact_kind must be one of {', '.join(db.FACT_KINDS)}")
    recurs = str(rec.get("recurs") or "").strip().lower()
    if recurs not in ("", "yearly"):
        raise Reject("recurs must be '' or 'yearly'")
    fact_date = None
    if fact_kind == "date":
        if not rec.get("date"):
            raise Reject("fact_kind=date requires a date")
        fact_date = _iso_date(rec.get("date"), "date")
    elif rec.get("date"):
        fact_date = _iso_date(rec.get("date"), "date")
    domain = db.domain_for_topic(topic, "business")
    existing = conn.execute(
        "SELECT body, kind, date, recurs FROM facts WHERE domain=? AND topic=?",
        (domain, topic),
    ).fetchone()
    identical = existing and (existing["body"], existing["kind"],
                              existing["date"], existing["recurs"]) == (body, fact_kind, fact_date, recurs)
    if dry_run:
        return "deduped" if identical else "loaded"
    # verified and source_role are FORCED, payload input for them is ignored.
    db.upsert_fact(conn, domain, topic, body, kind=fact_kind, date=fact_date,
                   recurs=recurs, source_role=f"connector-{source}", verified=0)
    return "deduped" if identical else "loaded"


def _load_document(rec: dict, source: str, conn, dry_run: bool) -> str:
    name = _text(rec, "name")
    path = str(rec.get("path") or "").strip()
    doc_kind = str(rec.get("doc_kind") or "contract").strip()
    notes = str(rec.get("notes") or "").strip()
    exists = conn.execute(
        "SELECT 1 FROM documents WHERE name = ? AND path = ?", (name, path)
    ).fetchone()
    if dry_run:
        return "deduped" if exists else "loaded"
    db.add_document(conn, name, path=path, kind=doc_kind, notes=notes)
    return "deduped" if exists else "loaded"


def _load_note(rec: dict, source: str, conn, dry_run: bool) -> str:
    topic = _text(rec, "topic")
    body = _text(rec, "body")[:NOTE_BODY_MAX]
    if not topic.startswith(NOTE_PREFIXES):
        topic = NOTE_PREFIX_FOR_SOURCE.get(source, "email: ") + topic
    dup = conn.execute(
        """SELECT 1 FROM memos WHERE from_role='ian' AND topic=? AND body=?
           AND created_at >= datetime('now', 'localtime', '-7 days')""",
        (topic, body),
    ).fetchone()
    if dup:
        return "deduped"
    if not dry_run:
        db.add_memo(conn, "ian", topic, body, priority=1)  # priority pinned
    return "loaded"


LOADERS = {
    "calendar_event": _load_calendar_event,
    "fact": _load_fact,
    "document": _load_document,
    "note": _load_note,
}

REPORT_NOUN = {
    "calendar_event": "calendar events",
    "fact": "facts (unverified)",
    "document": "documents (pending)",
    "note": "notes",
}


def load(payload: dict, source: str, conn, dry_run: bool = False) -> dict:
    """Validate + load a payload. Returns counts and per-record rejects.

    Raises ValueError on a malformed top-level payload (CLI exit 1)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError('payload must be {"records": [...]}')
    if source not in SOURCES:
        raise ValueError(f"source must be one of {', '.join(SOURCES)}")

    loaded: dict[str, int] = {}
    deduped: dict[str, int] = {}
    rejected: list[tuple[int, str, str]] = []

    for i, rec in enumerate(payload["records"]):
        if not isinstance(rec, dict):
            rejected.append((i, "?", "record must be an object"))
            continue
        kind = str(rec.get("kind") or "").strip()
        if kind not in KINDS:
            rejected.append((i, kind or "?", f"unsupported kind (allowed: {', '.join(KINDS)})"))
            continue
        try:
            status = LOADERS[kind](rec, source, conn, dry_run)
        except Reject as e:
            rejected.append((i, kind, str(e)))
            continue
        (loaded if status == "loaded" else deduped)[kind] = \
            (loaded if status == "loaded" else deduped).get(kind, 0) + 1

    n_loaded = sum(loaded.values())
    if not dry_run and n_loaded:
        log_source = "calendar" if source == "calendar" else f"connector_{source}"
        parts = [f"{n} {REPORT_NOUN[k]}" for k, n in loaded.items()]
        db.update_ingest_log(conn, log_source, n_loaded, "; ".join(parts))

    return {"loaded": loaded, "deduped": deduped, "rejected": rejected,
            "n_loaded": n_loaded, "dry_run": dry_run}


def format_report(result: dict, source: str) -> str:
    bits = [f"{n} {REPORT_NOUN[k]}" for k, n in result["loaded"].items()]
    bits += [f"{n} deduped" for n in [sum(result["deduped"].values())] if n]
    bits += [f"{len(result['rejected'])} rejected" for _ in [1] if result["rejected"]]
    total = sum(result["loaded"].values()) + sum(result["deduped"].values()) + len(result["rejected"])
    head = "dry-run: " if result["dry_run"] else ""
    lines = [f"{head}connector sync ({source}): {total} records → " + (", ".join(bits) or "nothing to load")]
    for idx, kind, reason in result["rejected"]:
        lines.append(f"  - rejected [{idx}] {kind}: {reason}")
    if result["loaded"].get("fact"):
        lines.append("  facts need confirmation on the Memory page before agents trust them.")
    if result["loaded"].get("document"):
        lines.append("  pending documents wake Harvey Specter (counsel) on the next run.")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Load a connector JSON payload into ianOS")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--file", type=Path, help="read payload from a file instead of stdin")
    ap.add_argument("--dry-run", action="store_true", help="validate + report, write nothing")
    args = ap.parse_args()

    raw = args.file.read_text() if args.file else sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"malformed JSON: {e}")

    conn = db.connect()
    try:
        result = load(payload, args.source, conn, dry_run=args.dry_run)
    except ValueError as e:
        sys.exit(f"malformed payload: {e}")
    finally:
        conn.close()

    print(format_report(result, args.source))
    had_any = bool(payload.get("records"))
    all_rejected = had_any and not result["n_loaded"] and not sum(result["deduped"].values())
    sys.exit(2 if all_rejected else 0)


if __name__ == "__main__":
    main()
