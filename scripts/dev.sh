#!/usr/bin/env bash
# Start API (8787) + dashboard (5173) together; Ctrl-C stops both.
set -e
cd "$(dirname "$0")/.."

# Replace stale API from an old `make api` / manual uvicorn (no Partner routes).
if stale=$(lsof -ti :8787 2>/dev/null); then
  echo "Stopping stale API on :8787 (pid $stale)…"
  kill $stale 2>/dev/null || true
  sleep 0.5
fi

.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8787 --reload &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT

cd dashboard && npm run dev
