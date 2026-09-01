"""Phone app: auth paths a browser can actually use, manifest, push config."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, push
from api import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


# ------------------------------------------------------- browser-usable auth

class _Req:
    """Minimal stand-in for a Starlette request."""
    def __init__(self, headers=None, query=None, cookies=None, host="127.0.0.1"):
        self.headers = headers or {}
        self.query_params = query or {}
        self.cookies = cookies or {}
        self.client = SimpleNamespace(host=host)


def test_token_accepted_from_bearer_query_or_cookie():
    # Shortcuts use a header; a browser NAVIGATION can only use ?token=, and
    # every later request uses the cookie we hand back.
    assert main._presented_token(_Req(headers={"authorization": "Bearer abc"})) == "abc"
    assert main._presented_token(_Req(query={"token": "abc"})) == "abc"
    assert main._presented_token(_Req(cookies={main.TOKEN_COOKIE: "abc"})) == "abc"
    assert main._presented_token(_Req()) == ""


def test_lan_still_refused_without_a_token(monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "")
    assert main._auth_decision(is_local=False, has_valid_token=False)[0] == 403
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    assert main._auth_decision(is_local=False, has_valid_token=False)[0] == 401
    assert main._auth_decision(is_local=False, has_valid_token=True) is None


def test_localhost_needs_nothing(monkeypatch):
    monkeypatch.setattr(main, "API_TOKEN", "secret")
    assert main._auth_decision(is_local=True, has_valid_token=False) is None


def test_a_proxied_request_is_never_treated_as_local():
    """Tailscale `serve` dials the app FROM 127.0.0.1 on the phone's behalf.

    If loopback alone meant "local", the tunnel would silently hand every
    tailnet device an unauthenticated session AND open the journal. A forwarded
    request is remote, whatever address it arrives from.
    """
    local = _Req(headers={})
    assert main._is_local(local) is True                       # a real local browser

    for header in ("x-forwarded-for", "x-forwarded-proto", "forwarded",
                   "tailscale-user-login"):
        proxied = _Req(headers={header: "anything"})
        assert main._is_local(proxied) is False, f"{header} must revoke local trust"
        # …and the guard therefore still demands a token and hides the journal
        assert main._auth_decision(is_local=False, has_valid_token=False) is not None


def test_state_over_a_tunnel_journal_with_token(client, monkeypatch):
    """SPEC-v11: tunnel + valid token reaches journal; bodies still private from state."""
    monkeypatch.setattr(main, "API_TOKEN", "tok123")
    remote = {"x-forwarded-for": "100.64.0.9", "authorization": "Bearer tok123"}
    r = client.get("/api/state", headers=remote)
    assert r.status_code == 200
    assert r.json()["journal_available"] is True
    assert client.get("/api/journal", headers=remote).status_code == 200


# ------------------------------------------------------------------ manifest

def test_manifest_is_installable(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    m = r.json()
    assert m["display"] == "standalone"          # launches without browser chrome
    assert m["start_url"].startswith("/")
    sizes = {i["sizes"] for i in m["icons"]}
    assert "192x192" in sizes and "512x512" in sizes
    assert any(i.get("purpose") == "maskable" for i in m["icons"])


def test_manifest_start_url_carries_token(client, monkeypatch):
    # iOS may give the installed app its own cookie jar, it must be able to
    # authenticate itself on first launch with no typing.
    monkeypatch.setattr(main, "API_TOKEN", "tok123")
    m = client.get("/manifest.webmanifest").json()
    assert "token=tok123" in m["start_url"]


def test_state_advertises_journal_availability(client):
    assert client.get("/api/state").json()["journal_available"] is True
    assert "journal_available" in client.get("/api/state").json()


def test_phone_ui_shows_journal():
    """SPEC-v11: Journal is a first-class phone surface (token-gated by the API)."""
    nav = (Path(__file__).resolve().parent.parent
           / "dashboard" / "src" / "components" / "Nav.jsx").read_text()
    assert "journal" in nav
    app = (Path(__file__).resolve().parent.parent
           / "dashboard" / "src" / "App.jsx").read_text()
    assert "JournalPage" in app


def test_the_server_is_installed_to_survive_a_crash_and_a_reboot():
    """`make phone` must hand serving to launchd, not to the terminal it ran in : 
    otherwise closing the window silently takes the phone app offline."""
    root = Path(__file__).resolve().parent.parent
    plist = (root / "ops" / "com.ianos.serve.plist").read_text()
    assert "<key>KeepAlive</key>" in plist and "<key>RunAtLoad</key>" in plist
    assert "com.ianos.serve" in plist
    assert "8787" in plist

    sh = (root / "scripts" / "phone.sh").read_text()
    assert "com.ianos.serve.plist" in sh and "launchctl load" in sh
    # and it must NOT block on a foreground server
    assert "exec .venv/bin/uvicorn" not in sh


def test_icons_exist_on_disk():
    icons = Path(__file__).resolve().parent.parent / "dashboard" / "public" / "icons"
    for name in ("icon-180.png", "icon-192.png", "icon-512.png",
                 "icon-maskable-512.png", "favicon-64.png"):
        p = icons / name
        assert p.exists(), f"missing {name}, run make icons"
        assert p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"


def test_brand_sources_and_lockup_exist():
    public = Path(__file__).resolve().parent.parent / "dashboard" / "public"
    assert (public / "ianOS.jpg").exists(), "app icon source missing"
    assert (public / "logo.png").exists(), "site logo source missing"
    lockup = public / "logo-lockup.png"
    assert lockup.exists(), "missing logo-lockup.png, run make icons"
    assert lockup.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_make_icons_writes_expected_sizes(tmp_path, monkeypatch):
    """Regenerating from brand sources must emit every PWA size + lockup."""
    from PIL import Image

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    import make_icons as mi

    # Point outputs at a temp tree so the test never clobber live assets.
    public = tmp_path / "public"
    icons = public / "icons"
    public.mkdir()
    Image.open(root / "dashboard" / "public" / "ianOS.jpg").save(public / "ianOS.jpg")
    Image.open(root / "dashboard" / "public" / "logo.png").save(public / "logo.png")
    monkeypatch.setattr(mi, "PUBLIC", public)
    monkeypatch.setattr(mi, "ICON_SRC", public / "ianOS.jpg")
    monkeypatch.setattr(mi, "LOGO_SRC", public / "logo.png")
    monkeypatch.setattr(mi, "OUT", icons)
    monkeypatch.setattr(mi, "LOCKUP", public / "logo-lockup.png")

    assert mi.main() == 0
    for name, size in (("icon-180.png", 180), ("icon-192.png", 192),
                       ("icon-512.png", 512), ("icon-maskable-512.png", 512),
                       ("favicon-64.png", 64)):
        img = Image.open(icons / name)
        assert img.size == (size, size)
        assert img.format == "PNG"
    lock = Image.open(public / "logo-lockup.png")
    assert lock.mode == "RGBA"
    assert lock.width > lock.height  # horizontal wordmark, not the square canvas
    # Maskable safe-zone pad: corner pixels match the near-black PAD colour.
    mask = Image.open(icons / "icon-maskable-512.png").convert("RGBA")
    assert mask.getpixel((0, 0))[:3] == mi.PAD[:3]


# ---------------------------------------------------------------------- push

def test_push_is_off_unless_configured(monkeypatch):
    for k in ("IANOS_PUSH_TOPIC", "IANOS_PUSH_URL",
              "IANOS_PUSHOVER_TOKEN", "IANOS_PUSHOVER_USER"):
        monkeypatch.delenv(k, raising=False)
    assert push.configured() is None
    assert push.send("t", "m") is False          # silent no-op, never raises


def test_push_provider_precedence(monkeypatch):
    monkeypatch.setenv("IANOS_PUSH_TOPIC", "abc")
    assert push.configured() == "ntfy"
    monkeypatch.setenv("IANOS_PUSH_URL", "https://example.com/hook")
    assert push.configured() == "webhook"
    monkeypatch.setenv("IANOS_PUSHOVER_TOKEN", "t")
    monkeypatch.setenv("IANOS_PUSHOVER_USER", "u")
    assert push.configured() == "pushover"


def test_push_never_raises_on_a_dead_endpoint(monkeypatch):
    monkeypatch.delenv("IANOS_PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("IANOS_PUSH_URL", raising=False)
    monkeypatch.setenv("IANOS_PUSH_TOPIC", "ianos-test")
    monkeypatch.setenv("IANOS_NTFY_SERVER", "http://127.0.0.1:1")  # nothing listening
    assert push.send("ianOS", "day command") is False


# --------------------------------------------------------- service worker file

def test_service_worker_ships_and_guards_writes():
    sw = (Path(__file__).resolve().parent.parent
          / "dashboard" / "public" / "sw.js").read_text()
    # writes must never be served from cache, the offline queue owns them
    assert "request.method !== 'GET'" in sw
    assert "X-ianOS-Cached" in sw           # UI can tell you the data is stale
    assert "/api/state" in sw


def test_a_sleeping_mac_behind_a_tunnel_counts_as_offline():
    """Tailscale `serve` answers 502 while the Mac sleeps, the request SUCCEEDS,
    so a bare .catch() never fires. Without this the phone shows an error where
    it should show the last snapshot, and a queued tap is thrown away instead."""
    root = Path(__file__).resolve().parent.parent / "dashboard"
    sw = (root / "public" / "sw.js").read_text()
    api = (root / "src" / "lib" / "api.js").read_text()

    for src, name in ((sw, "sw.js"), (api, "api.js")):
        assert "GATEWAY_DOWN" in src, f"{name} ignores gateway errors"
        for code in ("502", "503", "504"):
            assert code in src, f"{name} does not treat {code} as offline"
    # the write path must queue on a gateway error, not throw it at the user
    assert "if (GATEWAY_DOWN.has(r.status)) return unreachable()" in api
