"""Journal (SPEC-v8 Phase A): pure fns, API round-trip, media, and, above all : 
the privacy wall (nothing reaches /api/state or the LAN except an explicit share)."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, journal  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    from api import main as apimain
    monkeypatch.setattr(apimain, "JOURNAL_DIR", tmp_path / "journal")
    from fastapi.testclient import TestClient
    return TestClient(apimain.app), apimain


# ---------------------------------------------------------------- journal_day

@pytest.mark.parametrize("iso, expected", [
    ("2026-07-22T23:59:00", "2026-07-22"),  # late night, still today
    ("2026-07-22T00:40:00", "2026-07-21"),  # after midnight → yesterday
    ("2026-07-22T04:00:00", "2026-07-22"),  # 4am boundary → today
    ("2026-07-22T03:59:00", "2026-07-21"),  # 3:59am → still yesterday
])
def test_journal_day(iso, expected):
    assert journal.journal_day(datetime.fromisoformat(iso)) == expected


# ---------------------------------------------------------- stats / agent_signal

def test_stats_rolling_count(conn):
    db.create_journal_entry(conn, "2026-07-22", "today")
    db.create_journal_entry(conn, "2026-07-20", "two days ago")
    db.create_journal_entry(conn, "2026-07-10", "outside the 7d window")
    assert journal.journal_stats(conn, "2026-07-22") == {
        "closed_today": True, "nights_closed_total": 3, "nights_closed_7d": 2}


def test_agent_signal_has_no_text_or_media(conn):
    db.create_journal_entry(conn, "2026-07-22", "SECRET words")
    db.update_journal_entry(conn, 1, media_path="data/journal/x.jpg", media_kind="photo")
    sig = journal.agent_signal(conn, "2026-07-22")
    assert sig == {"closed_today": True, "nights_closed_7d": 1,
                   "nights_closed_total": 1, "days_since_last_close": 0}
    assert "body" not in sig and "media_path" not in sig


def test_agent_signal_days_since(conn):
    db.create_journal_entry(conn, "2026-07-18", "four days ago")
    sig = journal.agent_signal(conn, "2026-07-22")
    assert sig["closed_today"] is False and sig["days_since_last_close"] == 4


def test_on_this_day_previous_years_only(conn):
    db.create_journal_entry(conn, "2025-07-22", "last year")
    db.create_journal_entry(conn, "2024-07-22", "two years ago")
    db.create_journal_entry(conn, "2026-07-21", "different day")
    assert [e["date"] for e in journal.on_this_day(conn, "2026-07-22")] == \
        ["2025-07-22", "2024-07-22"]


# ---------------------------------------------------------------- API round-trip

def test_api_create_list_patch_delete(client):
    c, _ = client
    entry = c.post("/api/journal", json={"body": "  what a day  "}).json()["entry"]
    assert entry["body"] == "what a day"          # trimmed, server-dated
    eid = entry["id"]
    assert c.get("/api/journal").json()["stats"]["closed_today"] is True
    assert c.post("/api/journal", json={"body": "   "}).status_code == 400
    assert c.patch(f"/api/journal/{eid}", json={"body": "edited"}).json()["body"] == "edited"
    assert c.delete(f"/api/journal/{eid}").json() == {"ok": True}
    assert c.get("/api/journal").json()["entries"] == []


# ---------------------------------------------------------------- media

def test_api_media_upload_serve_replace_delete(client):
    c, apimain = client
    eid = c.post("/api/journal", json={"body": "with a photo"}).json()["entry"]["id"]
    assert c.post(f"/api/journal/{eid}/media",
                  files={"file": ("x.exe", b"nope", "application/octet-stream")}).status_code == 400
    up = c.post(f"/api/journal/{eid}/media",
                files={"file": ("sunset.jpg", b"\xff\xd8fakejpg", "image/jpeg")})
    assert up.status_code == 200 and up.json()["media_kind"] == "photo"
    mp = up.json()["media_path"]
    assert (apimain.ROOT / mp).exists()
    got = c.get(f"/api/journal/media/{eid}")
    assert got.status_code == 200 and got.content == b"\xff\xd8fakejpg"
    up2 = c.post(f"/api/journal/{eid}/media",
                 files={"file": ("clip.mp4", b"fakemp4", "video/mp4")})
    assert up2.json()["media_kind"] == "video"
    assert not (apimain.ROOT / mp).exists()       # old file replaced/removed
    c.delete(f"/api/journal/{eid}/media")
    assert c.get(f"/api/journal/media/{eid}").status_code == 404


def test_api_media_no_media_is_404(client):
    c, _ = client
    eid = c.post("/api/journal", json={"body": "no photo"}).json()["entry"]["id"]
    assert c.get(f"/api/journal/media/{eid}").status_code == 404


def test_api_media_too_large_413(client, monkeypatch):
    c, apimain = client
    monkeypatch.setattr(apimain, "_JOURNAL_MEDIA_MAX", 4)
    eid = c.post("/api/journal", json={"body": "big"}).json()["entry"]["id"]
    assert c.post(f"/api/journal/{eid}/media",
                  files={"file": ("big.jpg", b"0123456789", "image/jpeg")}).status_code == 413
    assert c.get(f"/api/journal/media/{eid}").status_code == 404   # partial cleaned up, no media


def test_api_delete_entry_unlinks_media(client):
    c, apimain = client
    eid = c.post("/api/journal", json={"body": "doomed"}).json()["entry"]["id"]
    mp = c.post(f"/api/journal/{eid}/media",
                files={"file": ("p.jpg", b"jpg", "image/jpeg")}).json()["media_path"]
    assert (apimain.ROOT / mp).exists()
    c.delete(f"/api/journal/{eid}")
    assert not (apimain.ROOT / mp).exists()


# ---------------------------------------------------------------- share

def test_api_share_makes_one_ian_memo(client):
    c, _ = client
    e = c.post("/api/journal", json={"body": "please act on this"}).json()["entry"]
    assert c.post(f"/api/journal/{e['id']}/share").json()["ok"] is True
    memos = [m for m in c.get("/api/state").json()["memos"] if m["body"] == "please act on this"]
    assert len(memos) == 1 and memos[0]["from_role"] == "ian"
    assert memos[0]["topic"] == f"journal {e['date']}"
    c.post(f"/api/journal/{e['id']}/share")   # idempotent
    memos2 = [m for m in c.get("/api/state").json()["memos"] if m["body"] == "please act on this"]
    assert len(memos2) == 1


# ---------------------------------------------------------------- PRIVACY WALL

def test_privacy_unshared_body_and_media_absent_from_state(client):
    c, _ = client
    eid = c.post("/api/journal", json={"body": "ZZSENTINELZZ private thoughts"}).json()["entry"]["id"]
    mp = c.post(f"/api/journal/{eid}/media", files={"file": ("p.jpg", b"jpg", "image/jpeg")}).json()["media_path"]
    state = c.get("/api/state").text
    assert "ZZSENTINELZZ" not in state          # words never leak
    assert mp not in state                      # the media path never leaks
    assert "journal_entries" not in state       # the entries are not in state at all


def test_privacy_shared_body_appears_once_as_memo(client):
    c, _ = client
    e = c.post("/api/journal", json={"body": "SHAREDZZ act please"}).json()["entry"]
    c.post(f"/api/journal/{e['id']}/share")
    assert c.get("/api/state").text.count("SHAREDZZ") == 1   # exactly once, as the memo


def test_privacy_journal_lan_ok_with_token(client, monkeypatch):
    """SPEC-v11: phone + valid token can read the journal; bad token still denied."""
    c, apimain = client
    monkeypatch.setattr(apimain, "API_TOKEN", "tok")
    remote = {"x-forwarded-for": "100.64.0.9"}
    assert c.get("/api/journal", headers={**remote, "Authorization": "Bearer tok"}).status_code == 200
    assert c.get("/api/journal",
                 headers={**remote, "Authorization": "Bearer wrong"}).status_code in (401, 403)
    assert c.get("/api/health", headers={**remote, "Authorization": "Bearer tok"}).status_code == 200


def test_privacy_runner_has_no_journal_tool():
    src = (Path(__file__).resolve().parent.parent / "agents" / "runner.py").read_text()
    assert "read_journal" not in src        # Phase A adds NO journal tool
    assert '"journal"' not in src           # no allowlist/tool key (Phase D adds only agent_signal)


def test_journal_days_view(client):
    c, _ = client
    eid = c.post("/api/journal", json={"body": "night one"}).json()["entry"]["id"]
    c.post(f"/api/journal/{eid}/media", files={"file": ("p.jpg", b"jpg", "image/jpeg")})
    days = c.get("/api/journal?view=days").json()["days"]
    assert len(days) >= 1
    assert days[0]["has_media"] is True
    assert days[0]["cover_entry_id"] == eid
    assert "night one" in days[0]["snippet"]


def test_journal_month(client):
    c, _ = client
    e = c.post("/api/journal", json={"body": "aug night"}).json()["entry"]
    month = e["date"][:7]
    data = c.get(f"/api/journal/month/{month}").json()
    assert data["month"] == month
    assert data["days"][e["date"]]["closed"] is True
    assert c.get("/api/journal/month/nope").status_code == 400
