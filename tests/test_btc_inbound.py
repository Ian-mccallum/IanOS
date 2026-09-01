"""SPEC-v17 BtC inbound: the laws, not the plumbing.

The loader's network edge is two tiny functions; everything else is
load_records(conn, records), driven here directly with fake site payloads.
"""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from api import main
from ingest import sync_btc

# A sentinel that must never leak out of the consent wall.
SENTINEL_IP = "203.0.113.77"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    return TestClient(main.app)


def record(**over):
    base = {
        "request_id": "req-aaaaaaaa-0001",
        "kind": "demo",
        "received_at_utc": "2026-08-11T18:00:00Z",
        "name": "Mike Torres",
        "company": "Torres Plumbing",
        "email": "mike@example.com",
        "phone": "(630) 555-0142",
        "topics": ["Missed-call recovery"],
        "windows": [{"date": "2026-08-12", "window": "morning",
                     "label": "Wed, Aug 12 · Morning 7–10"}],
        "consent": {"granted": True, "phone": "(630) 555-0142",
                    "ip": SENTINEL_IP, "disclosure_text": "By checking this box..."},
    }
    base.update(over)
    return base


def seed_lead(conn, **over):
    fields = {"phone_norm": "6305550142", "phone": "(630) 555-0142",
              "business_name": "Torres Plumbing", "email": "",
              "tier": "A", "fit": 3, "pain": 2, "reach": 1, "total": 6,
              "miss_signal": "never called back"}
    fields.update(over)
    cols = ", ".join(fields)
    conn.execute(f"INSERT INTO leads ({cols}) VALUES ({','.join('?'*len(fields))})",
                 tuple(fields.values()))
    conn.commit()
    return conn.execute("SELECT id FROM leads ORDER BY id DESC LIMIT 1").fetchone()["id"]


# --------------------------------------------------------------- idempotency

def test_same_payload_twice_changes_zero_rows(client):
    conn = db.connect()
    r1 = sync_btc.load_records(conn, [record()])
    r2 = sync_btc.load_records(conn, [record()])
    assert (r1["loaded"], r1["deduped"]) == (1, 0)
    assert (r2["loaded"], r2["deduped"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) c FROM inbound_requests").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"] == 1
    # deduped ids are still ackable: a crash between write and ack must drain
    assert r2["ackable"] == [record()["request_id"]]
    conn.close()


def test_rejected_records_continue_and_are_not_acked(client):
    conn = db.connect()
    out = sync_btc.load_records(conn, [
        {"request_id": "x", "kind": "demo"},          # short id
        record(kind="waitlist"),                       # unknown kind
        record(request_id="req-bbbbbbbb-0002"),        # good
    ])
    assert out["loaded"] == 1
    assert len(out["rejected"]) == 2
    assert out["ackable"] == ["req-bbbbbbbb-0002"]     # bad rows stay in KV
    conn.close()


# ------------------------------------------------------------ the consent wall

def test_consent_never_reaches_api_state(client):
    conn = db.connect()
    sync_btc.load_records(conn, [record()])
    conn.close()
    state = client.get("/api/state").json()
    blob = json.dumps(state)
    assert SENTINEL_IP not in blob
    assert "disclosure_text" not in blob
    assert state["inbound"]["pending"][0]["name"] == "Mike Torres"


# ------------------------------------------------------------- lead identity

def test_phone_match_merges_onto_existing_lead(client):
    conn = db.connect()
    lead_id = seed_lead(conn)
    out = sync_btc.load_records(conn, [record()])
    assert out["loaded"] == 1
    row = conn.execute("SELECT lead_id FROM inbound_requests").fetchone()
    assert row["lead_id"] == lead_id
    assert conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"] == 1
    conn.close()


def test_email_match_merges_when_no_phone(client):
    conn = db.connect()
    lead_id = seed_lead(conn, phone_norm="6305550199", phone="",
                        email="Mike@example.com")
    sync_btc.load_records(conn, [record(phone="")])   # email only, case differs
    assert conn.execute("SELECT lead_id FROM inbound_requests").fetchone()["lead_id"] == lead_id
    conn.close()


def contact_record(**over):
    """A message has no topics/windows and no phone by default (the /contact
    form only requires name+email+message); it exercises the branch every
    demo-only test above skips."""
    base = {
        "request_id": "req-cccccccc-0003",
        "kind": "contact",
        "received_at_utc": "2026-08-11T20:00:00Z",
        "name": "Dana Whitfield",
        "email": "dana@example.com",
        "phone": "",
        "topics": [],
        "windows": [],
        "interest": "Integrations",
        "message": "Do you integrate with ServiceTitan? We have 6 techs.",
        "consent": {"granted": False, "ip": SENTINEL_IP},
    }
    base.update(over)
    return base


def test_contact_kind_loads_and_appears_in_state(client):
    conn = db.connect()
    out = sync_btc.load_records(conn, [contact_record()])
    assert out["loaded"] == 1
    lead = conn.execute("SELECT phone_norm, source FROM leads").fetchone()
    assert lead["phone_norm"].startswith("x")   # law 6: phoneless never NULL
    conn.close()

    state = client.get("/api/state").json()
    assert SENTINEL_IP not in json.dumps(state)         # law 4 for contact too
    req = state["inbound"]["pending"][0]
    assert req["kind"] == "contact"
    assert req["message"].startswith("Do you integrate")
    assert req["windows"] == [] and req["topics"] == []


def test_contact_same_payload_twice_changes_zero_rows(client):
    conn = db.connect()
    sync_btc.load_records(conn, [contact_record()])
    out = sync_btc.load_records(conn, [contact_record()])
    assert (out["loaded"], out["deduped"]) == (0, 1)
    assert conn.execute("SELECT COUNT(*) c FROM inbound_requests").fetchone()["c"] == 1
    conn.close()


def test_contact_dismiss_works(client):
    conn = db.connect()
    sync_btc.load_records(conn, [contact_record()])
    inbound_id = conn.execute("SELECT id FROM inbound_requests").fetchone()["id"]
    conn.close()
    res = client.post(f"/api/inbound/{inbound_id}/dismiss")
    assert res.status_code == 200
    conn = db.connect()
    assert conn.execute("SELECT status FROM inbound_requests").fetchone()["status"] == "dismissed"
    conn.close()


def test_phoneless_create_never_leaves_phone_norm_null(client):
    conn = db.connect()
    sync_btc.load_records(conn, [record(phone="")])
    lead = conn.execute("SELECT * FROM leads").fetchone()
    assert lead["phone_norm"] is not None and lead["phone_norm"].startswith("x")
    conn.close()


def test_inbound_never_mutates_scoring(client):
    conn = db.connect()
    lead_id = seed_lead(conn)
    sync_btc.load_records(conn, [record()])
    lead = db.lead_by_id(conn, lead_id)
    assert (lead["tier"], lead["fit"], lead["pain"], lead["reach"], lead["total"]) \
        == ("A", 3, 2, 1, 6)
    assert lead["miss_signal"] == "never called back"
    conn.close()


# ----------------------------------------------------------- confirm / dismiss

def test_confirm_books_through_existing_machinery(client):
    conn = db.connect()
    sync_btc.load_records(conn, [record()])
    inbound_id = conn.execute("SELECT id FROM inbound_requests").fetchone()["id"]
    conn.close()

    res = client.post(f"/api/inbound/{inbound_id}/confirm", json={"date": "2026-08-12"})
    assert res.status_code == 200, res.text

    conn = db.connect()
    lead = conn.execute("SELECT * FROM leads").fetchone()
    assert lead["stage"] == "demo"
    assert lead["next_touch"] == "2026-08-12"
    touch = conn.execute("SELECT * FROM lead_touches").fetchone()
    assert (touch["kind"], touch["outcome"]) == ("demo", "booked")
    act = conn.execute("SELECT * FROM activity WHERE date=?", (db.today(),)).fetchone()
    assert act["demos"] == 1 and act["conversations"] == 1
    assert conn.execute("SELECT status FROM inbound_requests").fetchone()["status"] == "confirmed"
    conn.close()

    # Confirming twice is a 400, not a second touch.
    assert client.post(f"/api/inbound/{inbound_id}/confirm",
                       json={"date": "2026-08-12"}).status_code == 400


def test_dismiss_leaves_the_lead_untouched(client):
    conn = db.connect()
    lead_id = seed_lead(conn)
    sync_btc.load_records(conn, [record()])
    inbound_id = conn.execute("SELECT id FROM inbound_requests").fetchone()["id"]
    conn.close()

    assert client.post(f"/api/inbound/{inbound_id}/dismiss").status_code == 200
    conn = db.connect()
    lead = db.lead_by_id(conn, lead_id)
    assert lead["stage"] == "new" and lead["last_touch"] is None
    assert conn.execute("SELECT COUNT(*) c FROM lead_touches").fetchone()["c"] == 0
    conn.close()


# ------------------------------------------------------------- configuration

def test_sync_endpoint_501_when_unconfigured(client, monkeypatch):
    monkeypatch.delenv("BTC_SYNC_URL", raising=False)
    monkeypatch.delenv("BTC_SYNC_TOKEN", raising=False)
    assert client.post("/api/btc/sync").status_code == 501


def test_state_reports_unconfigured(client, monkeypatch):
    monkeypatch.delenv("BTC_SYNC_URL", raising=False)
    monkeypatch.delenv("BTC_SYNC_TOKEN", raising=False)
    assert client.get("/api/state").json()["inbound"]["configured"] is False


# ------------------------------------------- SPEC-v19: the personal seam

def personal_record(**over):
    base = {
        "request_id": "req-personal-0001",
        "kind": "contact",
        "source": "personal",
        "received_at_utc": "2026-08-14T18:00:00Z",
        "name": "Dana Whitfield",
        "email": "dana@example.com",
        "message": "Are you taking freelance work this fall?",
    }
    base.update(over)
    return base


def test_personal_inbound_never_touches_leads(client):
    """SPEC-v19 law 1, the reason the spec exists. The call queue's ordering
    guarantee is the whole feature; a recruiter entering it corrupts that
    invisibly, one row at a time."""
    conn = db.connect()
    seed_lead(conn)                                   # an existing real lead
    before = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]

    out = sync_btc.load_records(conn, [personal_record()], source="personal")
    assert out["loaded"] == 1

    after = conn.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
    assert after == before                            # no row created
    row = conn.execute("SELECT * FROM inbound_requests").fetchone()
    assert row["lead_id"] is None                     # and none linked
    assert row["source"] == "personal"
    conn.close()


def test_personal_inbound_has_no_promise_clock(client):
    """Law 3: ianmccallum.com makes no 24-hour promise, so nothing may be
    late on it and the jeopardy push must never fire for these."""
    from datetime import datetime
    from core import promises
    conn = db.connect()
    sync_btc.load_records(conn, [personal_record()], source="personal")
    row = conn.execute("SELECT * FROM inbound_requests").fetchone()
    assert row["promised_by"] is None
    assert db.pending_promises(conn) == []
    assert promises.due_for_alert(
        [dict(row)], datetime(2026, 8, 15, 10, 0)) == []
    conn.close()


def test_btc_seam_still_gets_lead_and_promise(client):
    """The personal seam must not have quietly disabled the btc one."""
    conn = db.connect()
    sync_btc.load_records(conn, [record()], source="btc")
    row = conn.execute("SELECT * FROM inbound_requests").fetchone()
    assert row["source"] == "btc"
    assert row["lead_id"] is not None
    assert row["promised_by"] is not None
    conn.close()


def test_seams_dedupe_independently(client):
    conn = db.connect()
    sync_btc.load_records(conn, [record()], source="btc")
    sync_btc.load_records(conn, [personal_record()], source="personal")
    again = sync_btc.load_records(conn, [personal_record()], source="personal")
    assert again["deduped"] == 1 and again["loaded"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM inbound_requests").fetchone()["c"] == 2
    conn.close()


def test_personal_consent_wall_holds(client):
    """The wall is source-agnostic: no seam leaks a consent record."""
    conn = db.connect()
    sync_btc.load_records(
        conn, [personal_record(consent={"ip": SENTINEL_IP})], source="personal")
    conn.close()
    assert SENTINEL_IP not in json.dumps(client.get("/api/state").json())


def test_state_exposes_source_so_surfaces_can_split(client):
    """Without source in the summary both surfaces render everything."""
    conn = db.connect()
    sync_btc.load_records(conn, [record()], source="btc")
    sync_btc.load_records(conn, [personal_record()], source="personal")
    conn.close()
    pending = client.get("/api/state").json()["inbound"]["pending"]
    assert {p["source"] for p in pending} == {"btc", "personal"}
