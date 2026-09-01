#!/usr/bin/env bash
# Serve the API on the LAN (for iPhone Shortcuts), token-gated.
set -e
cd "$(dirname "$0")/.."

if ! grep -q '^IANOS_API_TOKEN=' .env 2>/dev/null; then
  TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  echo "IANOS_API_TOKEN=$TOKEN" >> .env
  echo "Generated IANOS_API_TOKEN and appended to .env"
fi
TOKEN=$(grep '^IANOS_API_TOKEN=' .env | head -1 | cut -d= -f2-)
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<your-lan-ip>")

echo ""
echo "════════════════════════════════════════════════════════════"
echo " Phone capture: in your iPhone Shortcut, POST JSON to:"
echo "   URL:    http://$IP:8787/api/quick"
echo "   Header: Authorization: Bearer $TOKEN"
echo "   Body:   {\"gym\": true}   (or sleep / energy / workout / steps / note)"
echo " Laptop must be awake on the same wifi. See docs/SHORTCUTS.md."
echo "════════════════════════════════════════════════════════════"
echo ""

# stop any stale localhost API first
if stale=$(lsof -ti :8787 2>/dev/null); then kill $stale 2>/dev/null || true; sleep 0.5; fi
.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8787
