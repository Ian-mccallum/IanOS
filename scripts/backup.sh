#!/usr/bin/env bash
# The backup engine (SPEC-v16). Subcommands: run (default) | status | verify.
#
# Laws enforced here, not in docs:
#   * The DB is snapshotted with VACUUM INTO, never file-copied (WAL mode).
#   * A failed scheduled run becomes a `system` memo, never a silent log line.
#   * Unconfigured is exit 2 with instructions, the /api/plan/sync precedent.
#   * Nothing Mac-shaped: bash + restic + sqlite3, identical on the Framework.
#
# launchd (and systemd) run with a bare PATH, so restic is resolved explicitly,
# the same way phone.sh hunts for tailscale.
#
# -E matters: without errtrace the ERR trap does not fire inside functions,
# and every step here lives in one, so a failure would skip the memo (law 4).
set -Eeuo pipefail

CODE_ROOT="$(cd "$(dirname "$0")/.." && pwd)"   # where core/ lives
ROOT="${IANOS_ROOT:-$CODE_ROOT}"                # whose data/ and .env we back up
ENV_FILE="$ROOT/.env"
DB="$ROOT/data/ianos.db"
STAGE="$ROOT/data/backup/staging"
LAST_OK="$ROOT/data/backup/last_success"
STEP="starting"

find_restic() {
  for c in "$(command -v restic || true)" /opt/homebrew/bin/restic /usr/local/bin/restic /usr/bin/restic; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}
RESTIC="$(find_restic)" || { echo "restic not installed (brew install restic / apt install restic)" >&2; exit 1; }

# .env values fill the gaps; a real environment variable always wins (tests,
# one-off overrides). Parsed, not sourced: .env is data, not a script.
env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -1 || true; }
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-$(env_get RESTIC_REPOSITORY)}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:-$(env_get RESTIC_PASSWORD)}"
export B2_ACCOUNT_ID="${B2_ACCOUNT_ID:-$(env_get B2_ACCOUNT_ID)}"
export B2_ACCOUNT_KEY="${B2_ACCOUNT_KEY:-$(env_get B2_ACCOUNT_KEY)}"

if [ -z "$RESTIC_REPOSITORY" ] || [ -z "$RESTIC_PASSWORD" ]; then
  cat >&2 <<'EOF'
Backup is not configured. Add to ianOS/.env (see docs/BACKUP.md):

  RESTIC_REPOSITORY=b2:<bucket>:ianos     # or a path, e.g. /Volumes/Backup/ianos-restic
  RESTIC_PASSWORD=<long random, ALSO in your password manager and on paper>
  B2_ACCOUNT_ID=<keyID>                   # B2 only
  B2_ACCOUNT_KEY=<applicationKey>         # B2 only
EOF
  exit 2
fi

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# Law 4: no silent failure. The memo goes through core.db so it lands on the
# dashboard exactly like a crashed agent's would. Best-effort on purpose: a
# broken venv must not mask the original backup error.
fail_memo() {
  IANOS_ROOT="$ROOT" IANOS_CODE_ROOT="$CODE_ROOT" BACKUP_STEP="$STEP" \
    "$ROOT/.venv/bin/python" - <<'PY' 2>/dev/null || true
import os, sys
from pathlib import Path
sys.path.insert(0, os.environ["IANOS_CODE_ROOT"])
from core import db
db.DB_PATH = Path(os.environ["IANOS_ROOT"]) / "data" / "ianos.db"
conn = db.connect()
db.add_memo(conn, "system", "backup",
            f"Nightly backup FAILED at step: {os.environ.get('BACKUP_STEP','?')}. "
            "Run `make backup` to retry, `make backup-status` for detail. "
            "Log: data/backup.log", priority=2)
conn.close()
PY
}
on_err() { log "FAILED at step: $STEP"; fail_memo; }
trap on_err ERR
trap 'rm -rf "$STAGE"' EXIT

cmd_run() {
  STEP="probing repository"
  # First contact with a fresh bucket/folder: initialize it exactly once.
  "$RESTIC" cat config >/dev/null 2>&1 || { STEP="initializing repository"; "$RESTIC" init; }

  STEP="snapshotting the database (VACUUM INTO)"
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  /usr/bin/env sqlite3 "$DB" "VACUUM INTO '$STAGE/ianos.db'"

  STEP="collecting paths"
  paths=("$STAGE/ianos.db")
  [ -d "$ROOT/data/journal" ]   && paths+=("$ROOT/data/journal")
  [ -d "$ROOT/data/notes" ]     && paths+=("$ROOT/data/notes")
  [ -d "$ROOT/data/school" ]    && paths+=("$ROOT/data/school")
  [ -d "$ROOT/data/documents" ] && paths+=("$ROOT/data/documents")
  # SPEC-v37 §2.4/§10: data/consult/out/ is where a consult can leave Ian
  # something he asked for (a CSV, a draft, a chart). D9: new on-disk data
  # must be claimed by the backup the same day it's created, or it exists in
  # exactly one place on Earth until someone remembers.
  [ -d "$ROOT/data/consult" ]   && paths+=("$ROOT/data/consult")
  [ -f "$ENV_FILE" ]            && paths+=("$ENV_FILE")
  while IFS= read -r csv; do paths+=("$csv"); done \
    < <(find "$ROOT/leads" -maxdepth 1 -name '*.csv' 2>/dev/null)

  STEP="uploading snapshot"
  "$RESTIC" backup --tag ianos "${paths[@]}"

  STEP="pruning old snapshots"
  "$RESTIC" forget --prune --keep-daily 7 --keep-weekly 5 --keep-monthly 12 >/dev/null

  STEP="checking repository"
  "$RESTIC" check >/dev/null

  date '+%Y-%m-%d %H:%M:%S' > "$LAST_OK"
  log "OK"
}

cmd_status() {
  trap - ERR   # status never writes memos
  echo "repository : $RESTIC_REPOSITORY"
  if [ -f "$LAST_OK" ]; then echo "last success: $(cat "$LAST_OK")"; else echo "last success: never"; fi
  echo "snapshots  :"
  "$RESTIC" snapshots --compact | tail -8
}

cmd_verify() {
  STEP="deep check (read all data)"
  "$RESTIC" check --read-data

  STEP="test restore"
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/ianos-verify.XXXXXX")"
  "$RESTIC" restore latest --target "$tmp" --include '*/ianos.db' >/dev/null
  restored="$(find "$tmp" -name ianos.db | head -1)"
  [ -n "$restored" ] || { echo "no ianos.db in latest snapshot" >&2; exit 1; }

  STEP="integrity check"
  result="$(/usr/bin/env sqlite3 "$restored" 'PRAGMA integrity_check;')"
  echo "integrity_check: $result"
  [ "$result" = "ok" ] || exit 1
  echo "row counts (restored snapshot):"
  /usr/bin/env sqlite3 "$restored" \
    "SELECT '  leads: '||COUNT(*) FROM leads; \
     SELECT '  journal_entries: '||COUNT(*) FROM journal_entries; \
     SELECT '  memos: '||COUNT(*) FROM memos;"
  rm -rf "$tmp"
  log "verify OK"
}

case "${1:-run}" in
  run)    cmd_run ;;
  status) cmd_status ;;
  verify) cmd_verify ;;
  *) echo "usage: backup.sh [run|status|verify]" >&2; exit 64 ;;
esac
