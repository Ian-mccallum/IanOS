#!/usr/bin/env bash
# Set up the installable phone app and keep it running for good.
#
# Serving is handed to launchd (com.ianos.serve), not to this shell, so ianOS is
# reachable from the phone the entire time the Mac is awake, including after a
# reboot, instead of only while a terminal window happens to be open.
#
# Two ways the phone can reach it, and they are NOT equivalent:
#
#   Tailscale (preferred) -> https://<mac>.ts.net , a real cert, so iOS calls
#     it a secure context and registers the service worker. That is the ONLY
#     way the offline cache and the write queue actually run on the phone, and
#     it works from campus, not just from home wifi.
#   LAN            -> http://192.168.x.x:8787, same wifi only, and iOS refuses
#     service workers over plain http, so "works with the Mac asleep" does not.
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PLIST="$HOME/Library/LaunchAgents/com.ianos.serve.plist"

# 1. token (generated once, reused forever)
if ! grep -q '^IANOS_API_TOKEN=' .env 2>/dev/null; then
  TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
  echo "IANOS_API_TOKEN=$TOKEN" >> .env
  echo "Generated IANOS_API_TOKEN → .env"
fi
TOKEN=$(grep '^IANOS_API_TOKEN=' .env | head -1 | cut -d= -f2-)

# The Apple Health Shortcut receives a distinct, endpoint-scoped credential.
# Do not print it here: Body reveals it only inside the authenticated PWA when
# Ian actively begins pairing. The installation id lets the server reject a
# copied health token used from a different phone.
if ! grep -q '^IANOS_HEALTH_INGEST_TOKEN=' .env 2>/dev/null; then
  HEALTH_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
  echo "IANOS_HEALTH_INGEST_TOKEN=$HEALTH_TOKEN" >> .env
  echo "Generated dedicated Apple Health capture credential."
fi
if ! grep -q '^IANOS_HEALTH_INGEST_INSTALLATION_ID=' .env 2>/dev/null; then
  HEALTH_INSTALLATION_ID=$(python3 -c "from uuid import uuid4; print(uuid4())")
  echo "IANOS_HEALTH_INGEST_INSTALLATION_ID=$HEALTH_INSTALLATION_ID" >> .env
  echo "Paired Apple Health capture to this iPhone installation."
fi

# 2. icons from brand sources (idempotent, cheap) + production build
.venv/bin/python scripts/make_icons.py
echo "Building dashboard…"
(cd dashboard && npm run build --silent)

# 3. hand serving to launchd. Any foreground server from an older `make phone`
#    is killed first, or it would hold the port and launchd would fight it.
mkdir -p data
if stale=$(lsof -ti :8787 2>/dev/null); then kill $stale 2>/dev/null || true; sleep 1; fi
sed "s|__IANOS_DIR__|$ROOT|g" ops/com.ianos.serve.plist > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

printf "Starting the always-on server"
for _ in $(seq 1 25); do
  if curl -sf -o /dev/null "http://127.0.0.1:8787/api/health"; then break; fi
  printf "."; sleep 0.4
done
echo
if ! curl -sf -o /dev/null "http://127.0.0.1:8787/api/health"; then
  echo "!! Server did not come up. Check $ROOT/data/serve.log"
  exit 1
fi

# 4. prefer Tailscale; fall back to the LAN and say so honestly
TS=""
for c in /Applications/Tailscale.app/Contents/MacOS/Tailscale \
         /usr/local/bin/tailscale /opt/homebrew/bin/tailscale; do
  [ -x "$c" ] && TS="$c" && break
done

URL=""; NOTE=""
if [ -n "$TS" ]; then
  DNSNAME=$("$TS" status --json 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))" 2>/dev/null || true)
  if [ -n "$DNSNAME" ]; then
    # Probe cert issuance with real paths: `tailscale cert` refuses to write to
    # /dev/null ("not a regular file"), which would look identical to "your
    # tailnet has HTTPS turned off" and silently drop us back to the LAN.
    CERTDIR=$(mktemp -d)
    CERT_OK=1
    "$TS" cert --cert-file "$CERTDIR/c.crt" --key-file "$CERTDIR/c.key" \
      "$DNSNAME" >/dev/null 2>&1 || CERT_OK=0
    rm -rf "$CERTDIR"
    if [ "$CERT_OK" = "1" ]; then
      "$TS" serve --bg 8787 >/dev/null 2>&1 || true
      # Self-check: the tunnel connects FROM loopback, and loopback normally
      # means "Ian at his Mac", no token, journal unlocked. Refuse to hand out
      # the URL unless the API demonstrably still treats it as a remote caller.
      CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DNSNAME/api/state" || echo 000)
      if [ "$CODE" = "401" ]; then
        URL="https://$DNSNAME/?token=$TOKEN"
        NOTE="Tailscale · works anywhere (campus, car, dorm) · offline cache ON"
      else
        "$TS" serve reset >/dev/null 2>&1 || true
        echo "!! Tailscale tunnel answered $CODE unauthenticated (expected 401)."
        echo "!! Refusing to expose it. Falling back to LAN."
      fi
    else
      NOTE="Tailscale is on but HTTPS certs are not enabled for your tailnet."
    fi
  fi
fi

if [ -z "$URL" ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<your-lan-ip>")
  URL="http://$IP:8787/?token=$TOKEN"
  [ -n "$NOTE" ] || NOTE="LAN only"
  NOTE="$NOTE
  Same-wifi only, and iOS won't cache it offline over plain http.
  To fix both: enable HTTPS at https://login.tailscale.com/admin/dns
  then re-run 'make phone'."
fi

cat <<BANNER

════════════════════════════════════════════════════════════════
  ianOS is now serving, and will keep serving whenever your Mac
  is awake, including after a reboot. You can close this window.

  TO INSTALL, on your iPhone:

    1. Delete any old ianOS icon from your home screen first.
       (iOS caches the old address and artwork.)

    2. Open SAFARI, not Chrome, and go to:

       $URL

    3. Tap  Share ⬆️  →  "Add to Home Screen"  →  Add.

    4. Open it from the home screen from now on.
       No URL, no token, ever again.

  $NOTE

  Turn it all off with:  make phone-off
════════════════════════════════════════════════════════════════

BANNER
