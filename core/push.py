"""Push the Day Command to Ian's phone, the one thing that must arrive even
when the Mac is asleep by morning.

Provider-agnostic on purpose: set ONE of these in .env and the nightly run uses it.

    IANOS_PUSH_TOPIC=<random-string>     # ntfy.sh, free, no account
    IANOS_PUSH_URL=https://…             # any webhook that accepts a POST body
    IANOS_PUSHOVER_TOKEN=… + IANOS_PUSHOVER_USER=…   # Pushover ($5 once, private)

Unset = no push, no error. Never raises: a failed push must never break a run.

Privacy note: on ntfy's public server anyone who guesses the topic can read it,
so keep the payload to the Day Command, never journal text or lead details.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from core.http import ssl_context

TIMEOUT = 8

def configured() -> str | None:
    """Which provider is set up, if any."""
    if os.environ.get("IANOS_PUSHOVER_TOKEN") and os.environ.get("IANOS_PUSHOVER_USER"):
        return "pushover"
    if os.environ.get("IANOS_PUSH_URL"):
        return "webhook"
    if os.environ.get("IANOS_PUSH_TOPIC"):
        return "ntfy"
    return None


def _post(url: str, data: bytes, headers: dict) -> bool:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context()) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def send(title: str, message: str) -> bool:
    """Fire-and-forget. Returns True only if the provider accepted it."""
    provider = configured()
    if not provider:
        return False
    message = (message or "").strip()[:500]

    if provider == "pushover":
        payload = urllib.parse.urlencode({
            "token": os.environ["IANOS_PUSHOVER_TOKEN"],
            "user": os.environ["IANOS_PUSHOVER_USER"],
            "title": title, "message": message,
        }).encode()
        return _post("https://api.pushover.net/1/messages.json", payload,
                     {"Content-Type": "application/x-www-form-urlencoded"})

    if provider == "webhook":
        return _post(os.environ["IANOS_PUSH_URL"],
                     json.dumps({"title": title, "message": message}).encode(),
                     {"Content-Type": "application/json"})

    topic = os.environ["IANOS_PUSH_TOPIC"].strip()
    base = os.environ.get("IANOS_NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    return _post(f"{base}/{topic}", message.encode("utf-8"),
                 {"Title": title, "Tags": "hexagon", "Content-Type": "text/plain"})
