"""SPEC-v18: the promise clock. Laws, not plumbing.

core/promises.py is pure over (rows, now), so every test here drives it with
a fixed clock, no network and no push provider.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, promises
from ingest import sync_btc

SENTINEL_IP = "203.0.113.77"


def row(**over):
    base = {
        "id": 1, "status": "new", "alerted_at": None,
        "name": "Mike Torres", "company": "Torres Plumbing",
        "email": "mike@example.com", "phone": "6305550142",
        "promised_by": "2026-08-14 14:00:00",
    }
    base.update(over)
    return base


# ------------------------------------------------------- law 4: the UTC trap

def test_promised_by_is_24h_later_in_local_time():
    """The test that would have caught a five-hour bug.

    received_at is UTC from the site; every other timestamp in this DB is
    naive local. The deadline must be exactly 24h after the instant, then
    expressed locally, not 24h after the UTC *string* read as local.
    """
    received = "2026-08-13T21:32:58.537Z"
    got = promises.promised_by(received)
    expected = (datetime(2026, 8, 13, 21, 32, 58, tzinfo=timezone.utc)
                + timedelta(hours=24)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    assert got == expected

    # And the elapsed REAL time is 24h whatever the local offset is, which is
    # the actual law: a timezone slip would show up here as 19h or 29h.
    # Tolerance is for the sub-second truncation in the stored format, not slop.
    delta = promises._parse_local(got).astimezone() - promises.parse_received(received)
    assert abs(delta - timedelta(hours=24)) < timedelta(seconds=1)


def test_promised_by_handles_offset_and_garbage():
    assert promises.promised_by("2026-08-13T21:32:58+00:00") is not None
    assert promises.promised_by("") is None
    assert promises.promised_by("not a date") is None
    # A bare timestamp with no zone is UTC by contract with the site.
    assert promises.parse_received("2026-08-13T21:32:58").tzinfo == timezone.utc


# ------------------------------------------------ law 5 + selection behaviour

def test_alerts_inside_the_lead_window_only():
    now = datetime(2026, 8, 14, 10, 0)          # 10:00, promise at 14:00
    assert len(promises.due_for_alert([row()], now)) == 1

    early = datetime(2026, 8, 14, 4, 0)          # 10h out, and quiet hours
    assert promises.due_for_alert([row()], early, quiet=False) == []


def test_expired_promise_still_alerts():
    """Late is better than silent: he would rather know he is over."""
    now = datetime(2026, 8, 14, 18, 0)           # 4h past the deadline
    assert len(promises.due_for_alert([row()], now)) == 1


def test_fire_once():
    now = datetime(2026, 8, 14, 10, 0)
    assert promises.due_for_alert([row(alerted_at="2026-08-14 10:00:00")], now) == []


def test_handled_rows_never_alert():
    now = datetime(2026, 8, 14, 10, 0)
    assert promises.due_for_alert([row(status="confirmed")], now) == []
    assert promises.due_for_alert([row(status="dismissed")], now) == []


def test_missing_promised_by_never_alerts():
    now = datetime(2026, 8, 14, 10, 0)
    assert promises.due_for_alert([row(promised_by=None)], now) == []


# ------------------------------------------------------------ law 6: quiet

def test_quiet_hours_defer_rather_than_drop():
    late = datetime(2026, 8, 14, 2, 0)           # 02:00, promise at 06:00
    r = row(promised_by="2026-08-14 06:00:00")
    assert promises.due_for_alert([r], late) == []          # silent at 2am
    morning = datetime(2026, 8, 14, 8, 30)                   # still unhandled
    assert len(promises.due_for_alert([r], morning)) == 1    # late but honest


def test_quiet_window_boundaries():
    assert promises.in_quiet_hours(datetime(2026, 8, 14, 21, 0)) is True
    assert promises.in_quiet_hours(datetime(2026, 8, 14, 7, 59)) is True
    assert promises.in_quiet_hours(datetime(2026, 8, 14, 8, 0)) is False
    assert promises.in_quiet_hours(datetime(2026, 8, 14, 20, 59)) is False


# --------------------------------------------------- law 7: the push payload

def test_push_payload_carries_name_and_time_only():
    now = datetime(2026, 8, 14, 10, 0)
    due = promises.due_for_alert([
        row(id=1, consent={"ip": SENTINEL_IP}, message="secret message body"),
        row(id=2, company="", name="Dana Whitfield",
            promised_by="2026-08-14 13:00:00"),
    ], now)
    title, body = promises.alert_text(due)
    blob = title + body
    assert "Torres Plumbing" in body and "Dana Whitfield" in body
    assert SENTINEL_IP not in blob
    assert "secret message body" not in blob
    assert "6305550142" not in blob          # no phone number
    assert "@" not in blob                   # no email address
    assert "2 promises" in title


def test_alert_text_caps_the_list():
    now = datetime(2026, 8, 14, 10, 0)
    rows = [row(id=i, company=f"Shop {i}") for i in range(6)]
    title, body = promises.alert_text(promises.due_for_alert(rows, now))
    assert "+2 more" in body
    assert "6 promises" in title


# ------------------------------------------------------ end to end, with a DB

@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def test_loader_stamps_promised_by_and_alerts_once(conn, monkeypatch):
    sent = []
    monkeypatch.setattr(sync_btc.push, "configured", lambda: "ntfy")
    monkeypatch.setattr(sync_btc.push, "send",
                        lambda t, b: (sent.append((t, b)), True)[1])
    # Quiet hours have their own tests; this one must not depend on the hour
    # the suite happens to run at.
    monkeypatch.setattr(promises, "in_quiet_hours", lambda *a, **k: False)

    received = (datetime.now(timezone.utc) - timedelta(hours=21)).isoformat()
    sync_btc.load_records(conn, [{
        "request_id": "req-promise-0001", "kind": "demo",
        "received_at_utc": received, "name": "Mike Torres",
        "company": "Torres Plumbing", "email": "mike@example.com",
        "phone": "6305550142", "topics": [], "windows": [], "consent": {},
    }])
    stored = conn.execute("SELECT promised_by, alerted_at FROM inbound_requests").fetchone()
    assert stored["promised_by"] and stored["alerted_at"] is None

    # 21h into a 24h promise, so 3h of runway: inside the 4h lead window.
    now = promises._parse_local(stored["promised_by"]) - timedelta(hours=3)
    out = sync_btc.alert_due(conn, now=now)
    assert out["alerted"] == 1 and len(sent) == 1

    again = sync_btc.alert_due(conn, now=now)
    assert again["alerted"] == 0 and len(sent) == 1      # fire-once held


def test_unconfigured_push_still_stamps(conn, monkeypatch):
    """Law 9: no provider is silence, not an exception."""
    monkeypatch.setattr(sync_btc.push, "configured", lambda: None)
    monkeypatch.setattr(promises, "in_quiet_hours", lambda *a, **k: False)
    now = datetime(2026, 8, 14, 10, 0)
    conn.execute(
        "INSERT INTO inbound_requests (request_id, kind, name, consent, "
        "received_at, promised_by) VALUES ('r1','demo','X','{}','x', ?)",
        ((now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),))
    conn.commit()
    out = sync_btc.alert_due(conn, now=now)
    assert out["alerted"] == 1 and out["pushed"] is False
    assert conn.execute("SELECT alerted_at FROM inbound_requests").fetchone()["alerted_at"]
