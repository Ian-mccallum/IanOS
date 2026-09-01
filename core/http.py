"""Shared HTTPS trust configuration for urllib clients."""

from __future__ import annotations

import ssl
from functools import lru_cache


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """Return one reusable TLS context, preferring certifi's CA bundle."""
    try:
        import certifi
    except ImportError:  # pragma: no cover - exercised with an import shim
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())
