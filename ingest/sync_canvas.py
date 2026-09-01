"""Live scheduled pull of the Canvas calendar feed. Writes nothing itself.

SPEC-v32 Part C: this module only decides WHERE the bytes come from. It fetches
``CANVAS_ICS_URL`` (env only, a bearer secret: whoever holds it can read Ian's
whole term calendar), size-caps the body, and hands the resulting file to the
existing shared importer core (``ingest/import_canvas_calendar.import_file``),
which already does everything else: idempotent upsert by
``(provider, external_item_id)``, archiving what the feed dropped, and
recording its own ``school_sync_state`` success/failure/item_count. This
module also records each attempt on the shared ``ingest_log`` table (source
``"canvas_ics"``, the same ``record_ingest_attempt/success/failure`` helpers
every other loader uses), so Canvas freshness shows up next to every other
source instead of only inside the school subsystem. This file never
re-implements the importer's logic and never accepts the feed URL as an
argument, so it can never land in argv, logs, memos, ingest_log, or
``school_sync_state.last_error``.

Usage:
    .venv/bin/python ingest/sync_canvas.py
    .venv/bin/python ingest/sync_canvas.py --check-configured
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, school
from core.env import load_dotenv
from core.http import ssl_context
from ingest.canvas_ics import CanvasICSParseError
from ingest.import_canvas_calendar import DEFAULT_INVENTORY, import_file

load_dotenv()

REQUIRED_ENV_KEYS = ("CANVAS_ICS_URL",)
MAX_FETCH_BYTES = 5 * 1024 * 1024
_FETCH_TIMEOUT = 30

# core.db.record_ingest_failure enforces its own closed vocabulary
# (_SAFE_INGEST_ERRORS), distinct from core.school.SYNC_ERROR_CODES. Both are
# derived from the same exception, never from exception text or the URL.
INGEST_LOG_SOURCE = "canvas_ics"


class CanvasSyncTooLargeError(RuntimeError):
    """The feed body exceeded the safety byte cap before it touched disk."""


def missing_config_keys() -> list[str]:
    """Return key names only; callers must never include credential values."""
    return [key for key in REQUIRED_ENV_KEYS if not os.environ.get(key, "").strip()]


def configured() -> bool:
    return not missing_config_keys()


def fetch_ics_bytes(url: str) -> bytes:
    """Fetch the feed body with a hard byte cap. Never trust Content-Length alone.

    Reads at most ``MAX_FETCH_BYTES + 1`` bytes; a response that fills that
    buffer is rejected as too large before a single byte reaches disk.
    """
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT, context=ssl_context()) as resp:
        body = resp.read(MAX_FETCH_BYTES + 1)
    if len(body) > MAX_FETCH_BYTES:
        raise CanvasSyncTooLargeError("Canvas calendar feed exceeded the safety size cap")
    return body


def _classify(exc: Exception) -> str:
    """Map a failure to one of core.school.SYNC_ERROR_CODES.

    Never return exception text or a URL: only this closed code may cross into
    ``school_sync_state.last_error`` or any print/log statement.
    """
    if isinstance(exc, CanvasSyncTooLargeError):
        return "too_large"
    if isinstance(exc, CanvasICSParseError):
        return "parse"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, urllib.error.HTTPError):
        return "http_4xx" if 400 <= exc.code < 500 else "http_5xx"
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return "network"
    # An unexpected exception shape still must not leak text; the closest
    # honest bucket for "something about the fetched content was unusable"
    # is parse.
    return "parse"


def _ingest_log_code(exc: Exception) -> str:
    """Map a failure to one of core.db's ingest_log codes (network/auth/
    provider_5xx/protocol) -- a different closed vocabulary than
    ``_classify``'s ``SYNC_ERROR_CODES``. Mirrors the mapping ``sync_chase.py``
    already uses for the same exception shapes. Never returns exception text
    or a URL.
    """
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "auth"
        return "provider_5xx" if exc.code >= 500 else "protocol"
    if isinstance(exc, (urllib.error.URLError, OSError, TimeoutError)):
        return "network"
    return "protocol"


def sync(conn) -> dict:
    """Fetch the configured feed and hand it to the shared importer core."""
    url = os.environ.get("CANVAS_ICS_URL", "").strip()
    if not url:
        raise RuntimeError("CANVAS_ICS_URL is not configured")

    school.ensure_schema(conn)
    school.record_sync_attempt(conn)
    db.record_ingest_attempt(conn, INGEST_LOG_SOURCE)
    try:
        body = fetch_ics_bytes(url)
    except Exception as exc:
        code = _classify(exc)
        school.record_sync_failure(conn, code)
        db.record_ingest_failure(conn, INGEST_LOG_SOURCE, _ingest_log_code(exc))
        raise RuntimeError(code) from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "canvas_feed.ics"
        tmp_path.write_bytes(body)
        try:
            # import_file manages its own connection and already records
            # school_sync_state success/failure/item_count internally.
            report = import_file(tmp_path, DEFAULT_INVENTORY)
        except CanvasICSParseError as exc:
            school.record_sync_failure(conn, "parse")
            db.record_ingest_failure(conn, INGEST_LOG_SOURCE, "protocol")
            raise RuntimeError("parse") from exc
    db.record_ingest_success(
        conn, INGEST_LOG_SOURCE, report["imported"],
        f"{report['imported']} items, {report['archived']} archived",
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull the configured Canvas calendar feed and import it")
    ap.add_argument(
        "--check-configured", action="store_true",
        help="Refuse absent CANVAS_ICS_URL configuration without network access",
    )
    args = ap.parse_args()

    if args.check_configured:
        missing = missing_config_keys()
        if missing:
            print(f"Not configured: set {', '.join(missing)} in .env")
            raise SystemExit(1)
        print("Canvas sync configuration is complete")
        return

    if not configured():
        print("SKIP: CANVAS_ICS_URL not set in .env")
        raise SystemExit(0)

    conn = db.connect()
    try:
        report = sync(conn)
    except RuntimeError as exc:
        print(f"Canvas sync failed ({exc})")
        raise SystemExit(2)
    finally:
        conn.close()
    print(
        f"Canvas calendar synced: {report['imported']} items, {report['ignored']} ignored, "
        f"{report['archived']} archived, {report['courses']} courses seeded"
    )


if __name__ == "__main__":
    main()
