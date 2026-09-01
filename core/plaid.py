"""Small, read-only Plaid HTTP client for ianOS.

Tokens are deliberately supplied from the process environment rather than
stored in SQLite.  SQLite retains only item identity and transaction cursors.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from core.env import write_env
from core.http import ssl_context

APP_ENV_KEYS = ("PLAID_CLIENT_ID", "PLAID_SECRET")
ITEM_KEYS = ("chase", "capital_one")
HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidConfigurationError(ValueError):
    """Local configuration cannot safely make a Plaid request."""


class PlaidProtocolError(ValueError):
    """A provider payload cannot safely be published."""


class PlaidHTTPError(RuntimeError):
    """Provider failure with only a safe status code retained."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"Plaid HTTP {status}")


def token_env_key(item_key: str) -> str:
    if item_key not in ITEM_KEYS:
        raise PlaidConfigurationError("unknown Plaid item")
    return f"PLAID_ACCESS_TOKEN_{item_key.upper()}"


def missing_config_keys() -> list[str]:
    return [key for key in APP_ENV_KEYS if not os.environ.get(key, "").strip()]


def configured() -> bool:
    return not missing_config_keys()


def item_configured(item_key: str) -> bool:
    return configured() and bool(os.environ.get(token_env_key(item_key), "").strip())


def access_token(item_key: str) -> str:
    key = token_env_key(item_key)
    token = os.environ.get(key, "").strip()
    if not token:
        raise PlaidConfigurationError(f"{key} is not configured")
    return token


def _host() -> str:
    environment = os.environ.get("PLAID_ENV", "production").strip().lower()
    host = HOSTS.get(environment)
    if not host:
        raise PlaidConfigurationError("PLAID_ENV must be sandbox or production")
    return host


def post(path: str, payload: dict) -> dict:
    """Call Plaid without logging provider bodies, tokens, or credentials."""
    if not configured():
        raise PlaidConfigurationError("Plaid app credentials are incomplete")
    body = {
        "client_id": os.environ["PLAID_CLIENT_ID"].strip(),
        "secret": os.environ["PLAID_SECRET"].strip(),
        **payload,
    }
    request = urllib.request.Request(
        f"{_host()}{path}",
        data=json.dumps(body, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, context=ssl_context(), timeout=45) as response:
            parsed = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        # Provider messages can contain institution metadata; callers only need
        # a safe classification/status.
        raise PlaidHTTPError(exc.code) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PlaidProtocolError("Plaid response unavailable") from exc
    if not isinstance(parsed, dict):
        raise PlaidProtocolError("Plaid response must be an object")
    return parsed


def create_link_token(item_key: str) -> str:
    token_env_key(item_key)  # closed item-key validation
    payload: dict = {
        "client_name": "ianOS",
        "country_codes": ["US"],
        "language": "en",
        "products": ["transactions", "liabilities"],
        "user": {"client_user_id": "ianos-local"},
    }
    redirect_uri = os.environ.get("PLAID_REDIRECT_URI", "").strip()
    if redirect_uri:
        payload["redirect_uri"] = redirect_uri
    response = post("/link/token/create", payload)
    link_token = response.get("link_token")
    if not isinstance(link_token, str) or not link_token.strip():
        raise PlaidProtocolError("Plaid link token is missing")
    return link_token


def exchange_public_token(item_key: str, public_token: str) -> dict:
    key = token_env_key(item_key)
    if not isinstance(public_token, str) or not public_token.strip() or len(public_token) > 2048:
        raise PlaidProtocolError("Plaid public token is invalid")
    response = post("/item/public_token/exchange", {"public_token": public_token.strip()})
    access = response.get("access_token")
    item_id = response.get("item_id")
    if not isinstance(access, str) or not access or not isinstance(item_id, str) or not item_id:
        raise PlaidProtocolError("Plaid item exchange is malformed")
    write_env(key, access)
    return {"item_id": item_id}


def accounts(item_key: str) -> list[dict]:
    response = post("/accounts/get", {"access_token": access_token(item_key)})
    rows = response.get("accounts")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PlaidProtocolError("Plaid accounts response is malformed")
    return rows


def liabilities(item_key: str) -> dict:
    response = post("/liabilities/get", {"access_token": access_token(item_key)})
    rows = response.get("accounts")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PlaidProtocolError("Plaid liabilities response is malformed")
    return response


def item(item_key: str) -> dict:
    response = post("/item/get", {"access_token": access_token(item_key)})
    record = response.get("item")
    if not isinstance(record, dict) or not isinstance(record.get("item_id"), str):
        raise PlaidProtocolError("Plaid item response is malformed")
    return record


def transactions_sync(item_key: str, cursor: str) -> dict:
    response = post("/transactions/sync", {
        "access_token": access_token(item_key),
        "cursor": cursor,
        "count": 500,
    })
    for field in ("added", "modified", "removed"):
        if not isinstance(response.get(field), list):
            raise PlaidProtocolError("Plaid transactions response is malformed")
    if not isinstance(response.get("next_cursor"), str):
        raise PlaidProtocolError("Plaid transactions cursor is missing")
    if not isinstance(response.get("has_more"), bool):
        raise PlaidProtocolError("Plaid transactions pagination is malformed")
    return response
