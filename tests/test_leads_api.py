"""The Line API (SPEC-v9 Phase B): touch → stage + activity, and the undo.

The undo test is load-bearing: if it drifts, Ian's quota counters stop matching
the calls he actually made, and every downstream metric (audit_calls_today,
demos_last_7d, the chief's brief) silently lies.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.main import app  # noqa: E402
from core import db, leads  # noqa: E402

client = TestClient(app)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed(conn, **kw):
    fields = {"business_name": "Lakeshore Heating", "tier": "A", "total": 16,
              "market": "north", "segment": "trades", "city": "Plainfield",
              "phone": "(630) 555-0142", "owner_name": "Sam",
              "miss_signal": "...never called back...", "claims_247": 1}
    fields.update(kw)
    lead_id, _ = db.upsert_lead(conn, leads.norm_phone(fields["phone"]), **fields)
    conn.commit()
    return lead_id


def _activity(conn, field="audit_calls"):
    row = conn.execute("SELECT * FROM activity WHERE date=?", (db.today(),)).fetchone()
    return (row[field] if row else 0) or 0


# ----------------------------------------------------------------- queue

def test_queue_returns_composed_call_cards(conn):
    _seed(conn)
    r = client.get("/api/leads/queue")
    assert r.status_code == 200
    body = r.json()
    assert body["remaining_quota"] == leads.DAILY_QUOTA
    lead = body["queue"][0]
    assert lead["business_name"] == "Lakeshore Heating"
    assert lead["queue_reason"] == "tier A · proof of pain"
    card = lead["call_card"]
    assert card["ask_for"] == "Sam"
    assert card["hook_kind"] == "promise_vs_proof"
    assert len(card["objections"]) == 3


def test_queue_excludes_tier_d_and_parked(conn):
    _seed(conn, business_name="Skip", tier="D", phone="(630) 555-9001")
    _seed(conn, business_name="Parked", tier="B", phone="(630) 555-9002", stage="parked")
    names = [l["business_name"] for l in client.get("/api/leads/queue").json()["queue"]]
    assert "Skip" not in names and "Parked" not in names


# ------------------------------------------------------------- the touch

def test_no_answer_advances_stage_and_bumps_audit_calls(conn):
    lead_id = _seed(conn)
    r = client.post(f"/api/leads/{lead_id}/touch",
                    json={"kind": "call", "outcome": "no_answer", "duration_s": 12})
    assert r.status_code == 200
    body = r.json()
    assert body["lead"]["stage"] == "attempted"
    assert body["lead"]["attempts"] == 1
    assert body["lead"]["last_touch"] == db.today()
    assert _activity(conn, "audit_calls") == 1


def test_booked_sets_demo_bumps_demos_and_writes_a_memo(conn):
    lead_id = _seed(conn)
    r = client.post(f"/api/leads/{lead_id}/touch",
                    json={"kind": "call", "outcome": "booked", "note": "Tues 2pm"})
    assert r.json()["lead"]["stage"] == "demo"
    assert _activity(conn, "demos") == 1
    assert _activity(conn, "audit_calls") == 1
    memos = db.recent_memos(conn, days=1)
    assert any("booked a demo with Lakeshore Heating" in m["body"] for m in memos)


def test_no_answer_writes_no_memo(conn):
    """20 no-answer memos a day would drown the blackboard."""
    lead_id = _seed(conn)
    client.post(f"/api/leads/{lead_id}/touch", json={"kind": "call", "outcome": "no_answer"})
    assert db.recent_memos(conn, days=1) == []


def test_callback_sets_next_touch_and_promotes_to_band_zero(conn):
    lead_id = _seed(conn, tier="C", total=1)
    _seed(conn, business_name="Tier A", tier="A", total=17, phone="(630) 555-9003")
    client.post(f"/api/leads/{lead_id}/touch",
                json={"kind": "call", "outcome": "gatekeeper", "next_touch": db.today()})
    q = client.get("/api/leads/queue").json()["queue"]
    assert q[0]["business_name"] == "Lakeshore Heating"
    assert q[0]["queue_reason"] == "promised callback"


def test_bad_kind_and_outcome_are_rejected(conn):
    lead_id = _seed(conn)
    assert client.post(f"/api/leads/{lead_id}/touch",
                       json={"kind": "smoke_signal", "outcome": ""}).status_code == 400
    assert client.post(f"/api/leads/{lead_id}/touch",
                       json={"kind": "call", "outcome": "ghosted"}).status_code == 400


# -------------------------------------------------------------- the undo

def test_undo_reverses_touch_stage_and_activity(conn):
    """LOAD-BEARING. All three writes must come back, or the quota lies."""
    lead_id = _seed(conn)
    touch = client.post(f"/api/leads/{lead_id}/touch",
                        json={"kind": "call", "outcome": "not_interested"}).json()["touch"]
    assert client.get(f"/api/leads/{lead_id}").json()["stage"] == "lost"
    assert _activity(conn, "audit_calls") == 1

    r = client.delete(f"/api/leads/touches/{touch['id']}")
    assert r.status_code == 200
    lead = client.get(f"/api/leads/{lead_id}").json()
    assert lead["stage"] == "new"
    assert lead["attempts"] == 0
    assert lead["touches"] == []
    assert _activity(conn, "audit_calls") == 0


def test_undo_of_booked_restores_demos_counter(conn):
    lead_id = _seed(conn)
    touch = client.post(f"/api/leads/{lead_id}/touch",
                        json={"kind": "call", "outcome": "booked"}).json()["touch"]
    assert _activity(conn, "demos") == 1
    client.delete(f"/api/leads/touches/{touch['id']}")
    assert _activity(conn, "demos") == 0
    assert _activity(conn, "conversations") == 0


def test_undo_rebuilds_state_from_remaining_touches(conn):
    """Undoing the 2nd of 3 attempts must leave the lead consistent, not guessed."""
    lead_id = _seed(conn)
    ids = []
    for _ in range(3):
        ids.append(client.post(f"/api/leads/{lead_id}/touch",
                               json={"kind": "call", "outcome": "no_answer"}).json()["touch"]["id"])
    assert client.get(f"/api/leads/{lead_id}").json()["attempts"] == 3
    client.delete(f"/api/leads/touches/{ids[1]}")
    after = client.get(f"/api/leads/{lead_id}").json()
    assert after["attempts"] == 2
    assert after["stage"] == "attempted"
    assert _activity(conn, "audit_calls") == 2


def test_undo_of_missing_touch_is_404(conn):
    assert client.delete("/api/leads/touches/99999").status_code == 404


# ---------------------------------------------------------------- runs

def test_run_lifecycle(conn):
    lead_id = _seed(conn)
    run = client.post("/api/runs", json={"target": 5}).json()["run"]
    assert run["dialed"] == 0 and run["remaining"] == 5

    client.post(f"/api/leads/{lead_id}/touch",
                json={"kind": "call", "outcome": "reached", "run_id": run["id"]})
    cur = client.get("/api/runs/current").json()["run"]
    assert cur["dialed"] == 1
    assert cur["conversations"] == 1

    done = client.post(f"/api/runs/{run['id']}/end").json()
    assert done["summary"]["dialed"] == 1
    assert client.get("/api/runs/current").json()["run"] is None


def test_run_target_must_be_a_real_size(conn):
    assert client.post("/api/runs", json={"target": 7}).status_code == 400


def test_run_complete_fires_a_milestone(conn):
    lead_id = _seed(conn)
    run = client.post("/api/runs", json={"target": 5}).json()["run"]
    last = None
    for _ in range(5):
        last = client.post(f"/api/leads/{lead_id}/touch",
                           json={"kind": "call", "outcome": "no_answer",
                                 "run_id": run["id"]}).json()
    assert "run_complete" in last["milestones"]


# ---------------------------------------------------------------- state

def test_state_carries_a_summary_not_the_rows(conn):
    _seed(conn)
    body = client.get("/api/state").json()
    assert "leads" in body
    summary = body["leads"]
    assert summary["next_lead"]["business_name"] == "Lakeshore Heating"
    assert summary["tier_a_left"] == 1
    # the fat endpoint must never ship the lead table
    assert "queue" not in summary
    assert not isinstance(summary.get("next_lead"), list)


def test_health_advertises_leads(conn):
    assert client.get("/api/health").json()["features"]["leads"] is True


def test_patch_rejects_an_invalid_stage(conn):
    lead_id = _seed(conn)
    assert client.patch(f"/api/leads/{lead_id}", json={"stage": "vibing"}).status_code == 400
    assert client.patch(f"/api/leads/{lead_id}", json={"stage": "won"}).status_code == 200


# ------------------------------------------------- the list (Phase D)

def test_list_total_respects_the_search_term(conn):
    """The count and the rows must use the SAME filter, or the pager lies and
    'more →' walks into an empty page."""
    _seed(conn, business_name="Naperville Roofing", city="Naperville", tier="B",
          phone="(630) 555-8001")
    _seed(conn, business_name="Naperville HVAC", city="Naperville", tier="B",
          phone="(630) 555-8002")
    for i in range(10):
        _seed(conn, business_name=f"Aurora Co {i}", city="Aurora", tier="B",
              phone=f"(630) 555-81{i:02d}")

    everything = client.get("/api/leads?tier=B").json()
    assert everything["total"] == 12

    filtered = client.get("/api/leads?tier=B&q=naperville").json()
    assert filtered["total"] == 2, "total must count the search, not just the tier"
    assert len(filtered["leads"]) == 2
    assert filtered["total"] == len(filtered["leads"])


def test_list_filters_compose(conn):
    _seed(conn, business_name="North A", city="Aurora", tier="A", market="north",
          phone="(630) 555-8201")
    _seed(conn, business_name="South A", city="Champaign", tier="A", market="south",
          phone="(217) 555-8202")
    _seed(conn, business_name="North B", city="Aurora", tier="B", market="north",
          phone="(630) 555-8203")

    assert client.get("/api/leads?tier=A").json()["total"] == 2
    assert client.get("/api/leads?market=north").json()["total"] == 2
    assert client.get("/api/leads?tier=A&market=north").json()["total"] == 1
    assert client.get("/api/leads?q=champaign").json()["total"] == 1


def test_list_paging_is_stable_and_terminates(conn):
    for i in range(30):
        _seed(conn, business_name=f"Shop {i:02d}", tier="C", total=i,
              phone=f"(630) 555-83{i:02d}")
    first = client.get("/api/leads?limit=25&offset=0").json()
    second = client.get("/api/leads?limit=25&offset=25").json()
    assert first["total"] == second["total"] == 30
    assert len(first["leads"]) == 25 and len(second["leads"]) == 5
    ids = [l["id"] for l in first["leads"]] + [l["id"] for l in second["leads"]]
    assert len(set(ids)) == 30, "paging must not repeat or drop a lead"


def test_list_includes_parked_but_the_queue_never_does(conn):
    """The list is a look-up surface, it shows everything, including what the
    queue deliberately hides."""
    _seed(conn, business_name="Parked Co", tier="A", stage="parked",
          phone="(630) 555-8400")
    assert client.get("/api/leads?stage=parked").json()["total"] == 1
    names = [l["business_name"] for l in client.get("/api/leads/queue").json()["queue"]]
    assert "Parked Co" not in names
