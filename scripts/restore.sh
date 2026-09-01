#!/usr/bin/env bash
# The restore (SPEC-v16 law 2): materialize a snapshot into a NEW timestamped
# folder and print the copy commands. Never writes into the live tree, because
# the moment you run a restore is the moment the live tree might hold the only
# surviving copy of something newer than the snapshot.
#
#   make restore                  # latest
#   SNAPSHOT=1a2b3c4d make restore
set -euo pipefail

ROOT="${IANOS_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
ENV_FILE="$ROOT/.env"

find_restic() {
  for c in "$(command -v restic || true)" /opt/homebrew/bin/restic /usr/local/bin/restic /usr/bin/restic; do
    [ -n "$c" ] && [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}
RESTIC="$(find_restic)" || { echo "restic not installed (brew install restic / apt install restic)" >&2; exit 1; }

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^[[:space:]]*$1=//p" "$ENV_FILE" | tail -1 || true; }
export RESTIC_REPOSITORY="${RESTIC_REPOSITORY:-$(env_get RESTIC_REPOSITORY)}"
export RESTIC_PASSWORD="${RESTIC_PASSWORD:-$(env_get RESTIC_PASSWORD)}"
export B2_ACCOUNT_ID="${B2_ACCOUNT_ID:-$(env_get B2_ACCOUNT_ID)}"
export B2_ACCOUNT_KEY="${B2_ACCOUNT_KEY:-$(env_get B2_ACCOUNT_KEY)}"

if [ -z "$RESTIC_REPOSITORY" ] || [ -z "$RESTIC_PASSWORD" ]; then
  echo "Not configured. On a NEW machine set RESTIC_REPOSITORY / RESTIC_PASSWORD" >&2
  echo "(+ B2_ACCOUNT_ID / B2_ACCOUNT_KEY) in the environment or in .env first." >&2
  echo "See docs/BACKUP.md, 'The disaster runbook'." >&2
  exit 2
fi

SNAP="${SNAPSHOT:-latest}"
TARGET="$HOME/ianos-restore-$(date '+%Y%m%d-%H%M%S')"

echo "Restoring snapshot '$SNAP' into: $TARGET"
"$RESTIC" restore "$SNAP" --target "$TARGET"

DB_RESTORED="$(find "$TARGET" -name ianos.db -type f | head -1)"
if [ -n "$DB_RESTORED" ]; then
  result="$(/usr/bin/env sqlite3 "$DB_RESTORED" 'PRAGMA integrity_check;')"
  echo "integrity_check: $result"
  [ "$result" = "ok" ] || { echo "!! restored DB failed integrity check; try an older SNAPSHOT=<id>" >&2; exit 1; }
fi

JOURNAL_RESTORED="$(find "$TARGET" -type d -name journal | head -1 || true)"
ENV_RESTORED="$(find "$TARGET" -name .env -type f | head -1 || true)"

cat <<EOF

Restored, verified, and NOT yet applied. To adopt it into a live checkout,
stop the server (make phone-off) and copy what you need:

  cp  "$DB_RESTORED" \\
      "$ROOT/data/ianos.db"
EOF
[ -n "$JOURNAL_RESTORED" ] && cat <<EOF
  rsync -a "$JOURNAL_RESTORED/" "$ROOT/data/journal/"
EOF
[ -n "$ENV_RESTORED" ] && cat <<EOF
  cp  "$ENV_RESTORED" "$ROOT/.env"     # only on a fresh machine
EOF
cat <<EOF

Then: make dev (or make phone) and check the dashboard.
The restore folder is yours to delete once you're satisfied.
EOF
