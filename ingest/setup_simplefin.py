"""SimpleFIN setup: exchange one-time Setup Token for persistent Access URL."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.env import ROOT, load_dotenv
from core.http import ssl_context

DEFAULT_HOST = "https://bridge.simplefin.org"


def claim_token(setup_token: str, api_host: str = DEFAULT_HOST) -> str:
    """Decode setup token and POST to claim endpoint."""
    claim_url = base64.b64decode(setup_token.strip()).decode().strip()
    if not claim_url.startswith("http"):
        raise ValueError("invalid setup token: decode failed")
    req = urllib.request.Request(claim_url, method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
        access_url = resp.read().decode().strip()
    if not access_url.startswith("http"):
        raise ValueError(f"unexpected claim response: {access_url[:80]}")
    return access_url


def write_env(key: str, value: str) -> None:
    env_path = ROOT / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Claim SimpleFIN setup token for Chase sync")
    ap.add_argument("token", nargs="?", help="Setup token from bridge.simplefin.org")
    ap.add_argument("--token", dest="token_flag", help="Setup token (alt flag)")
    args = ap.parse_args()
    token = args.token_flag or args.token
    if not token:
        sys.exit("Usage: make setup-simplefin TOKEN=<setup-token-from-bridge>")
    try:
        access_url = claim_token(token)
    except (urllib.error.URLError, ValueError) as e:
        sys.exit(f"SimpleFIN claim failed: {e}")
    write_env("SIMPLEFIN_ACCESS_URL", access_url)
    print("SIMPLEFIN_ACCESS_URL saved to .env")
    print("Run: make sync-chase")


if __name__ == "__main__":
    main()
