"""All urllib integrations share one verified TLS boundary."""

from __future__ import annotations

import base64
import builtins
import ssl

from core import http, push
from ingest import setup_simplefin, sync_chase


class _Response:
    def __init__(self, body: bytes = b"{}", status: int = 200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return self._body


def test_push_passes_shared_ssl_context(monkeypatch):
    context = ssl.create_default_context()
    seen = {}
    monkeypatch.setattr(push, "ssl_context", lambda: context)

    def fake_urlopen(request, **kwargs):
        seen.update(kwargs)
        return _Response()

    monkeypatch.setattr(push.urllib.request, "urlopen", fake_urlopen)

    assert push._post("https://example.test/hook", b"payload", {}) is True
    assert seen["context"] is context


def test_chase_fetch_passes_shared_ssl_context(monkeypatch):
    context = ssl.create_default_context()
    seen = {}
    monkeypatch.setattr(sync_chase, "ssl_context", lambda: context)

    def fake_urlopen(request, **kwargs):
        seen.update(kwargs)
        return _Response(b'{"accounts": []}')

    monkeypatch.setattr(sync_chase.urllib.request, "urlopen", fake_urlopen)

    assert sync_chase.fetch_accounts("https://example.test/access") == {"accounts": []}
    assert seen["context"] is context


def test_simplefin_claim_passes_shared_ssl_context(monkeypatch):
    context = ssl.create_default_context()
    seen = {}
    monkeypatch.setattr(setup_simplefin, "ssl_context", lambda: context)

    def fake_urlopen(request, **kwargs):
        seen.update(kwargs)
        return _Response(b"https://user:password@example.test/access")

    monkeypatch.setattr(setup_simplefin.urllib.request, "urlopen", fake_urlopen)
    token = base64.b64encode(b"https://example.test/claim").decode()

    assert setup_simplefin.claim_token(token).startswith("https://")
    assert seen["context"] is context


def test_ssl_context_prefers_certifi_bundle(monkeypatch):
    sentinel = object()
    calls = []
    http.ssl_context.cache_clear()
    monkeypatch.setattr(http.ssl, "create_default_context",
                        lambda **kwargs: calls.append(kwargs) or sentinel)

    assert http.ssl_context() is sentinel
    assert calls == [{"cafile": __import__("certifi").where()}]
    assert http.ssl_context() is sentinel
    assert len(calls) == 1
    http.ssl_context.cache_clear()


def test_ssl_context_falls_back_to_system_trust(monkeypatch):
    sentinel = object()
    calls = []
    real_import = builtins.__import__

    def without_certifi(name, *args, **kwargs):
        if name == "certifi":
            raise ImportError("certifi unavailable")
        return real_import(name, *args, **kwargs)

    http.ssl_context.cache_clear()
    monkeypatch.setattr(builtins, "__import__", without_certifi)
    monkeypatch.setattr(http.ssl, "create_default_context",
                        lambda **kwargs: calls.append(kwargs) or sentinel)

    assert http.ssl_context() is sentinel
    assert calls == [{}]
    http.ssl_context.cache_clear()
