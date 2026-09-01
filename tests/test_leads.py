"""The Line (SPEC-v9 Phase A): phone keys, import safety, queue order, the run.

Everything here is pure Python against a temp SQLite. No network, no LLM.

Two tests are load-bearing and should never be relaxed:
  * test_reimport_preserves_ian_state, the scraper will run again; if this
    breaks, a re-scrape silently destroys his call history.
  * test_heat_is_earned_by_dialing_not_outcome, if this breaks, the feature has
    become a shame machine (SPEC-v9 design law).
"""

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, leads  # noqa: E402
from ingest import import_leads  # noqa: E402

TODAY = "2026-07-28"        # a Tuesday
BEFORE_MOVE_IN = "2026-08-18"
AFTER_MOVE_IN = "2026-08-19"

CSV_COLS = [
    "Tier", "Total", "Fit", "Pain", "Reach", "Why", "Market", "Segment",
    "Business Name", "Owner Name", "Phone", "Email", "City", "Service Type",
    "Miss Signal", "Claims 24/7", "Rating", "Reviews", "Website", "Address",
    "Maps URL", "Site Status", "Platform",
]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _row(**kw):
    base = {c: "" for c in CSV_COLS}
    base.update({"Tier": "C", "Total": "3", "Fit": "1", "Pain": "1", "Reach": "1",
                 "Market": "north", "Segment": "trades",
                 "Address": "1 Main St, Naperville, IL 60540"})
    base.update(kw)
    return base


def _write_csv(tmp_path, rows, name="enriched.csv"):
    p = tmp_path / name
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return p


def _add(conn, **kw):
    """Insert a lead directly, bypassing the CSV path."""
    fields = {"business_name": "Test Co", "tier": "C", "total": 3,
              "market": "north", "segment": "trades", "phone": "(630) 555-0100"}
    fields.update(kw)
    phone = leads.norm_phone(fields.get("phone")) or f"999{conn.total_changes:07d}"
    lead_id, _ = db.upsert_lead(conn, phone, **fields)
    state = {k: kw[k] for k in ("stage", "attempts", "last_touch", "next_touch", "notes")
             if k in kw}
    if state:
        cols = ", ".join(f"{k}=?" for k in state)
        conn.execute(f"UPDATE leads SET {cols} WHERE id=?", (*state.values(), lead_id))
    conn.commit()
    return lead_id


# ------------------------------------------------------------- 1. norm_phone

@pytest.mark.parametrize("raw, expected", [
    ("(630) 555-0142", "6305550142"),
    ("630-555-0142", "6305550142"),
    ("16305550142", "6305550142"),
    ("+1 (630) 555-0142", "6305550142"),
    ("(773) 555-7600 ext. 1542", "7735557600"),
    ("(855) 555-7669 ext. 5", "8555557669"),
    ("", ""),
    (None, ""),
    ("555-0142", ""),          # too short
    ("not a phone", ""),
])
def test_norm_phone(raw, expected):
    assert leads.norm_phone(raw) == expected


# ------------------------------------------------------------- 2 & 3. import

def test_import_is_idempotent(conn, tmp_path):
    path = _write_csv(tmp_path, [
        _row(**{"Business Name": "Alpha HVAC", "Phone": "(630) 555-0001"}),
        _row(**{"Business Name": "Beta Plumbing", "Phone": "(630) 555-0002"}),
    ])
    import_leads.import_file(path)
    import_leads.import_file(path)
    assert db.count_leads(conn) == 2


def test_import_is_idempotent_for_phoneless_rows(conn, tmp_path):
    """phone_norm is UNIQUE, but SQLite allows unlimited NULLs, without a
    synthetic key these 64-odd rows duplicate on every single re-import."""
    path = _write_csv(tmp_path, [
        _row(**{"Business Name": "No Phone Co", "Phone": "",
                "Address": "9 Elm St, Aurora, IL 60505"}),
        _row(**{"Business Name": "Also No Phone", "Phone": "",
                "Address": "11 Oak St, Aurora, IL 60505"}),
        _row(**{"Business Name": "Has Phone", "Phone": "(630) 555-7777"}),
    ])
    import_leads.import_file(path)
    import_leads.import_file(path)
    import_leads.import_file(path)
    assert db.count_leads(conn) == 3
    assert db.count_leads(conn, stage="parked") == 2


def test_two_phoneless_rows_at_the_same_address_stay_distinct(conn, tmp_path):
    """The synthetic key hashes name+address, so a shared address is fine."""
    path = _write_csv(tmp_path, [
        _row(**{"Business Name": "Suite A Roofing", "Phone": "",
                "Address": "100 Main St, Aurora, IL 60505"}),
        _row(**{"Business Name": "Suite B Plumbing", "Phone": "",
                "Address": "100 Main St, Aurora, IL 60505"}),
    ])
    import_leads.import_file(path)
    assert db.count_leads(conn) == 2


def test_reimport_preserves_ian_state(conn, tmp_path):
    """LOAD-BEARING. A re-scrape must never destroy call history."""
    path = _write_csv(tmp_path, [
        _row(**{"Business Name": "Alpha HVAC", "Phone": "(630) 555-0001",
                "Tier": "C", "Total": "3"}),
    ])
    import_leads.import_file(path)
    lead = db.lead_by_phone(conn, "6305550001")
    conn.execute(
        "UPDATE leads SET stage='reached', attempts=2, last_touch=?, "
        "next_touch=?, notes='asked for a callback' WHERE id=?",
        (TODAY, "2026-08-01", lead["id"]),
    )
    conn.commit()

    # the scraper re-runs and re-scores this lead upward
    path2 = _write_csv(tmp_path, [
        _row(**{"Business Name": "Alpha HVAC Inc", "Phone": "(630) 555-0001",
                "Tier": "A", "Total": "14", "Owner Name": "Dana"}),
    ], name="enriched2.csv")
    import_leads.import_file(path2)

    after = db.lead_by_phone(conn, "6305550001")
    assert after["stage"] == "reached"
    assert after["attempts"] == 2
    assert after["last_touch"] == TODAY
    assert after["next_touch"] == "2026-08-01"
    assert after["notes"] == "asked for a callback"
    # ...and the scored/scraped columns DID refresh
    assert after["tier"] == "A"
    assert after["total"] == 14
    assert after["owner_name"] == "Dana"
    assert after["business_name"] == "Alpha HVAC Inc"


# ------------------------------------------------------- 4. junk + geography

def test_out_of_state_and_junk_are_parked_and_never_queued(conn, tmp_path):
    path = _write_csv(tmp_path, [
        _row(**{"Business Name": "Hillside Properties, LLC", "Phone": "(217) 555-8036",
                "Tier": "A", "Total": "17",
                "Address": "1800 W 17th St, Bloomington, IN 47404"}),
        _row(**{"Business Name": "KeyMe Locksmiths", "Phone": "(630) 555-0003",
                "Tier": "B", "Total": "8"}),
        _row(**{"Business Name": "Johnstone Supply", "Phone": "(630) 555-0004",
                "Tier": "C"}),
        _row(**{"Business Name": "No Phone Co", "Phone": "", "Tier": "C"}),
        _row(**{"Business Name": "Good Shop", "Phone": "(630) 555-0005", "Tier": "A",
                "Total": "12"}),
    ])
    import_leads.import_file(path)

    parked = {r["business_name"]: r["notes"]
              for r in db.list_leads(conn, stage="parked", limit=99)}
    assert "Hillside Properties, LLC" in parked
    assert parked["Hillside Properties, LLC"].startswith("out-of-market")
    assert parked["KeyMe Locksmiths"] == "kiosk/distributor"
    assert parked["Johnstone Supply"] == "kiosk/distributor"
    assert parked["No Phone Co"] == "no phone"

    queued = [l["business_name"] for l in leads.call_queue(conn, TODAY, limit=50)]
    assert queued == ["Good Shop"]


# ------------------------------------------------------------ 5. tier D

def test_tier_d_never_enters_the_queue(conn):
    _add(conn, business_name="Skip Me", tier="D", total=9, phone="(630) 555-0010")
    _add(conn, business_name="Call Me", tier="C", total=1, phone="(630) 555-0011")
    for limit in (1, 5, 50, 500):
        names = [l["business_name"] for l in leads.call_queue(conn, TODAY, limit=limit)]
        assert "Skip Me" not in names


# ------------------------------------------------------------ 6. band order

def test_due_callback_outranks_tier_a(conn):
    _add(conn, business_name="Tier A Lead", tier="A", total=17, phone="(630) 555-0020")
    _add(conn, business_name="Promised", tier="C", total=0, phone="(630) 555-0021",
         stage="attempted", attempts=1, next_touch=TODAY)
    q = leads.call_queue(conn, TODAY, limit=10)
    assert q[0]["business_name"] == "Promised"
    assert q[0]["queue_reason"] == "promised callback"
    assert q[1]["business_name"] == "Tier A Lead"


def test_band_order_a_before_b_before_c(conn):
    _add(conn, business_name="C lead", tier="C", total=9, phone="(630) 555-0030")
    _add(conn, business_name="A lead", tier="A", total=10, phone="(630) 555-0031")
    _add(conn, business_name="B lead", tier="B", total=13, phone="(630) 555-0032")
    names = [l["business_name"] for l in leads.call_queue(conn, TODAY, limit=10)]
    assert names == ["A lead", "B lead", "C lead"]


# --------------------------------------------------------- 7. market flip

def test_market_priority_flips_on_move_in():
    assert leads.market_priority(BEFORE_MOVE_IN) == ("north", "south")
    assert leads.market_priority(AFTER_MOVE_IN) == ("south", "north")


def test_queue_respects_market_priority(conn):
    _add(conn, business_name="South B", tier="B", total=8, market="south",
         phone="(217) 555-0040")
    _add(conn, business_name="North B", tier="B", total=8, market="north",
         phone="(630) 555-0041")
    before = [l["business_name"] for l in leads.call_queue(conn, BEFORE_MOVE_IN, limit=10)]
    after = [l["business_name"] for l in leads.call_queue(conn, AFTER_MOVE_IN, limit=10)]
    assert before == ["North B", "South B"]
    assert after == ["South B", "North B"]


# ------------------------------------------------ 8 & 9. attempts and rest

def test_no_answer_bumps_audit_calls_and_starts_a_rest():
    assert leads.activity_bumps("call", "no_answer") == {"audit_calls": 1}
    assert leads.next_stage("new", "no_answer", attempts=0) == "attempted"
    assert leads.rest_days(1) == 3
    assert leads.rest_days(2) == 5
    assert leads.rest_days(3) == 8


def test_resting_lead_is_not_queued(conn):
    yesterday = "2026-07-27"
    _add(conn, business_name="Resting", tier="B", total=8, phone="(630) 555-0050",
         stage="attempted", attempts=1, last_touch=yesterday)
    assert leads.call_queue(conn, TODAY, limit=10) == []
    # ...but it returns once the rest expires
    later = "2026-08-05"
    assert [l["business_name"] for l in leads.call_queue(conn, later, limit=10)] == ["Resting"]


def test_fourth_unanswered_attempt_parks_the_lead(conn):
    assert leads.next_stage("attempted", "no_answer", attempts=3) == "parked"
    _add(conn, business_name="Exhausted", tier="B", total=8, phone="(630) 555-0060",
         stage="attempted", attempts=4, last_touch="2026-01-01")
    assert leads.call_queue(conn, TODAY, limit=10) == []


# --------------------------------------------------------- 10. booked demo

def test_booked_sets_demo_stage_and_bumps_demos():
    assert leads.next_stage("reached", "booked") == "demo"
    bumps = leads.activity_bumps("call", "booked")
    assert bumps["demos"] == 1
    assert bumps["audit_calls"] == 1


def test_bad_number_is_not_a_call():
    assert leads.activity_bumps("call", "bad_number") == {}
    assert leads.next_stage("new", "bad_number") == "parked"


def test_follow_up_bumps_follow_ups_not_audit_calls():
    bumps = leads.activity_bumps("follow_up", "no_answer")
    assert bumps == {"follow_ups": 1}


# ------------------------------------------------------------- 11. quota cap

def test_queue_caps_at_remaining_quota(conn):
    for i in range(30):
        _add(conn, business_name=f"Lead {i}", tier="C", total=1,
             phone=f"(630) 555-{1000 + i:04d}")
    assert leads.remaining_quota(conn, TODAY) == leads.DAILY_QUOTA
    assert len(leads.call_queue(conn, TODAY)) == leads.DAILY_QUOTA

    db.log_activity(conn, TODAY, audit_calls=leads.DAILY_QUOTA)
    assert leads.remaining_quota(conn, TODAY) == 0
    assert leads.call_queue(conn, TODAY) == []


# ------------------------------------------------------- 14. the call script

def test_call_card_hook_priority():
    both = leads.call_card({"business_name": "X", "miss_signal": "...never called back...",
                            "claims_247": 1, "city": "Aurora", "owner_name": "Sam"})
    assert both["hook_kind"] == "promise_vs_proof"
    # the quote is sentence-cased for reading aloud, so compare case-insensitively
    assert "never called back" in both["hook"].lower()
    assert both["ask_for"] == "Sam"
    assert "Sam" in both["open"]

    proof = leads.call_card({"business_name": "X", "miss_signal": "...no response at all..."})
    assert proof["hook_kind"] == "proof"

    promise = leads.call_card({"business_name": "X", "claims_247": 1})
    assert promise["hook_kind"] == "promise"

    site = leads.call_card({"business_name": "X", "site_status": "failed"})
    assert site["hook_kind"] == "phone_only"

    rating = leads.call_card({"business_name": "X", "rating": 3.9, "reviews": 60})
    assert rating["hook_kind"] == "rating"


@pytest.mark.parametrize("raw, expected", [
    # the whole snippet IS the complaint, never drop a word off either end.
    # The trailing … is honest: the source review does continue past the clip.
    ("...never called back...", "Never called back…"),
    # a sentence boundary exists, so snap to it and drop the clipped opener
    ("...st office has so mail. Had to call several times and no answer from them...",
     "Had to call several times and no answer from them…"),
    # no boundary, but text before the phrase, drop the scraper's half-word
    ("...nd secured when they left. There was no response...", "There was no response…"),
    # a clean sentence end needs no ellipsis (and the trailing '.' is stripped
    # because the hook template supplies its own sentence break)
    ("...nd secured. There was no response. They never fixed it...",
     "There was no response"),
    ("", ""),
    (None, ""),
])
def test_clean_quote_is_speakable(raw, expected):
    """The hook is read aloud on a live call, a mid-word fragment is unusable."""
    assert leads._clean_quote(raw) == expected


@pytest.mark.parametrize("raw, ends_with", [
    # real stubs from the scraper: 1-3 chars, dropped
    ("...they over look everything, every com...", "everything…"),
    ("...emails going unanswered or receiving n...", "receiving…"),
    ("...to email with no response bu...", "response…"),
    ("...got a hold of them. Scheduled appointment and...", "appointment…"),
    # a real word of 4+ chars is NOT a stub and must survive
    ("...calls and emails going unanswered from them...", "from them…"),
])
def test_clean_quote_trims_the_scrapers_mid_word_tail(raw, ends_with):
    """~10% of Miss Signal values are cut mid-word at the end. Ian cannot read
    'they over look everything, every com' out loud on a live call."""
    assert leads._clean_quote(raw).endswith(ends_with)


def test_clean_quote_truncates_long_reviews():
    long_review = "..." + ("the tech was late and rude " * 12) + " no answer ever..."
    out = leads._clean_quote(long_review)
    assert len(out) <= 111
    assert out.endswith("…")
    assert "." not in out[-2:]


def test_call_card_always_usable_for_a_bare_row():
    card = leads.call_card({})
    assert card is not None
    assert card["hook"]
    assert card["open"]
    assert card["ask"]
    assert card["ask_for"] == "whoever handles the phones"
    assert len(card["objections"]) == 3


def test_call_card_objections_match_segment():
    prop = leads.call_card({"segment": "property", "owner_name": "Pat"})
    assert any("tenant" in o["reply"] for o in prop["objections"])
    assert any("Pat" in o["reply"] for o in prop["objections"])
    emerg = leads.call_card({"segment": "emergency"})
    assert any("2am" in o["reply"] for o in emerg["objections"])


# ------------------------------------------- 13 & 15. THE DESIGN-LAW TESTS

def test_heat_is_earned_by_dialing_not_outcome(conn):
    """LOAD-BEARING. Heat must not distinguish a no-answer from a booked demo.

    If this ever fails, the game rewards an outcome Ian does not control and the
    feature has become a shame machine. See SPEC-v9 design laws.
    """
    now = datetime(2026, 7, 28, 10, 0, 0)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")

    misses = [{"outcome": "no_answer", "created_at": stamp} for _ in range(3)]
    wins = [{"outcome": "booked", "created_at": stamp} for _ in range(3)]
    mixed = [{"outcome": o, "created_at": stamp}
             for o in ("no_answer", "booked", "not_interested")]

    assert leads.heat(misses, now=now) == leads.heat(wins, now=now) == 3
    assert leads.heat(mixed, now=now) == 3
    assert leads.heat([], now=now) == 0


def test_heat_decays_with_idle_time_and_never_below_zero():
    now = datetime(2026, 7, 28, 10, 0, 0)
    old = (now - timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M:%S")
    touches = [{"outcome": "no_answer", "created_at": old} for _ in range(3)]
    assert leads.heat(touches, now=now) == 1          # 3 - (9 // 4) = 1
    ancient = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    assert leads.heat([{"outcome": "reached", "created_at": ancient}], now=now) == 0


def test_heat_does_not_leak_between_runs(conn):
    lead_id = _add(conn, business_name="Lead", tier="C", phone="(630) 555-0070")
    run1 = db.start_run(conn, TODAY, target=5)
    for _ in range(3):
        db.add_touch(conn, lead_id, TODAY, "call", "no_answer", run_id=run1["id"])
    conn.commit()
    assert leads.run_state(conn, run1["id"], TODAY)["dialed"] == 3

    db.end_run(conn, run1["id"])
    run2 = db.start_run(conn, TODAY, target=5)
    state2 = leads.run_state(conn, run2["id"], TODAY)
    assert state2["dialed"] == 0
    assert state2["heat"] == 0


# ---------------------------------------------------------- run mechanics

def test_run_state_counts_and_completion(conn):
    lead_id = _add(conn, business_name="Lead", tier="C", phone="(630) 555-0080")
    run = db.start_run(conn, TODAY, target=2)
    db.add_touch(conn, lead_id, TODAY, "call", "no_answer", run_id=run["id"])
    conn.commit()
    st = leads.run_state(conn, run["id"], TODAY)
    assert st["dialed"] == 1 and st["remaining"] == 1 and st["complete"] is False

    db.add_touch(conn, lead_id, TODAY, "call", "booked", run_id=run["id"])
    conn.commit()
    st = leads.run_state(conn, run["id"], TODAY)
    assert st["complete"] is True
    assert st["booked"] == 1
    assert st["conversations"] == 1


def test_start_run_reuses_an_open_run(conn):
    a = db.start_run(conn, TODAY, target=10)
    b = db.start_run(conn, TODAY, target=20)
    assert a["id"] == b["id"]


# --------------------------------------------------------------- runway

def test_runway_is_agent_facing_math(conn):
    for i in range(10):
        _add(conn, business_name=f"L{i}", tier="B", phone=f"(630) 556-{2000 + i:04d}")
    r = leads.runway(conn, TODAY)
    assert r["callable_remaining"] == 10
    assert r["weekdays_to_school"] == leads.weekdays_between(TODAY, leads.SCHOOL_START)
    assert r["weekdays_to_school"] > 0


# =================================================== Phase D. CSV re-export

def _dial(conn, lead_id, outcome, day=TODAY, kind="call"):
    db.add_touch(conn, lead_id, day, kind, outcome)
    lead = db.lead_by_id(conn, lead_id)
    db.update_lead(conn, lead_id,
                   stage=leads.next_stage(lead["stage"], outcome, lead["attempts"]),
                   last_touch=day,
                   attempts=lead["attempts"] + (1 if outcome in ("no_answer", "voicemail",
                                                                "gatekeeper") else 0))
    conn.commit()


def test_export_round_trips_the_enricher_columns(conn, tmp_path):
    from ingest import export_leads
    lead_id = _add(conn, business_name="Alpha HVAC", tier="A", total=14,
                   phone="(630) 555-0201", city="Aurora")
    _dial(conn, lead_id, "no_answer")
    _dial(conn, lead_id, "booked")

    out = tmp_path / "exported.csv"
    res = export_leads.export(out)
    assert res["written"] == 1 and res["worked"] == 1

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    row = rows[0]
    # the enricher's own schema is preserved so it can re-run on this file
    for col in ("Tier", "Total", "Fit", "Pain", "Reach", "Why", "Business Name", "Phone"):
        assert col in row
    assert row["Tier"] == "A"
    assert row["Call 1 Date"] == TODAY
    assert row["Call 2 Date"] == TODAY
    assert row["Answered?"] == "yes"
    assert row["Outcome"] == "booked"
    assert row["ianOS Dials"] == "2"
    assert row["ianOS Demo"] == "1"
    assert row["ianOS Stage"] == "demo"


def test_export_best_outcome_survives_a_later_no_answer(conn, tmp_path):
    """A demo booked on call 2 is not erased by a no-answer on call 3."""
    from ingest import export_leads
    lead_id = _add(conn, business_name="Beta Co", phone="(630) 555-0202")
    _dial(conn, lead_id, "no_answer")
    _dial(conn, lead_id, "booked")
    _dial(conn, lead_id, "no_answer")
    out = tmp_path / "e.csv"
    export_leads.export(out)
    row = list(csv.DictReader(out.open(encoding="utf-8")))[0]
    assert row["Outcome"] == "booked"
    assert row["Answered?"] == "yes"


def test_export_worked_only_filters_untouched_leads(conn, tmp_path):
    from ingest import export_leads
    worked = _add(conn, business_name="Worked", phone="(630) 555-0203")
    _add(conn, business_name="Never called", phone="(630) 555-0204")
    _dial(conn, worked, "reached")
    out = tmp_path / "e.csv"
    res = export_leads.export(out, worked_only=True)
    assert res["written"] == 1 and res["total"] == 2
    assert list(csv.DictReader(out.open(encoding="utf-8")))[0]["Business Name"] == "Worked"


def test_export_leaves_call_columns_empty_when_nothing_was_dialed(conn, tmp_path):
    from ingest import export_leads
    _add(conn, business_name="Untouched", phone="(630) 555-0205")
    out = tmp_path / "e.csv"
    export_leads.export(out)
    row = list(csv.DictReader(out.open(encoding="utf-8")))[0]
    assert row["Call 1 Date"] == "" and row["Answered?"] == "" and row["Outcome"] == ""
    assert row["ianOS Dials"] == "0"


# ================================================= Phase E: the back-test

def _population(conn, tier, n, contact_rate, start, pain=0, reach=0):
    """Dial n leads of a tier, letting `contact_rate` of them answer."""
    hits = round(n * contact_rate)
    for i in range(n):
        lid = _add(conn, business_name=f"{tier}{start + i}", tier=tier,
                   total=pain + reach, pain=pain, reach=reach,
                   phone=f"(630) {700 + start // 100:03d}-{start + i:04d}")
        _dial(conn, lid, "reached" if i < hits else "no_answer")


def test_backtest_refuses_to_report_on_a_thin_sample(conn):
    _population(conn, "A", 5, 1.0, 1000)
    r = leads.backtest(conn)
    assert r["status"] == "insufficient"
    assert r["leads_dialed"] == 5
    assert "by_tier" not in r          # no rates at all, not even tempting ones
    assert "30" in r["message"]


def test_backtest_detects_a_model_that_works(conn):
    _population(conn, "A", 40, 0.50, 1000)
    _population(conn, "B", 40, 0.25, 2000)
    _population(conn, "C", 40, 0.10, 3000)
    r = leads.backtest(conn)
    assert r["status"] == "ok"           # 120 dialed > TRUSTWORTHY_DIALS
    assert r["verdict"] == "ordering holds"
    assert r["tier_lift"] == 5.0         # 0.50 / 0.10
    by_tier = {g["group"]: g for g in r["by_tier"]}
    assert by_tier["A"]["contact_rate"] == 0.5
    assert by_tier["C"]["contact_rate"] == 0.1
    assert not any(g["thin"] for g in r["by_tier"])


def test_backtest_flags_an_inverted_ordering(conn):
    """The failure that matters: the queue ranking the wrong leads first."""
    _population(conn, "A", 40, 0.10, 1000)
    _population(conn, "B", 40, 0.25, 2000)
    _population(conn, "C", 40, 0.50, 3000)
    r = leads.backtest(conn)
    assert r["verdict"].startswith("ORDERING INVERTED")


def test_backtest_marks_preliminary_between_the_two_thresholds(conn):
    _population(conn, "A", 20, 0.5, 1000)
    _population(conn, "B", 20, 0.3, 2000)
    r = leads.backtest(conn)
    assert r["status"] == "preliminary"
    assert "do not reweight" in r["message"]


def test_backtest_separation_finds_the_predictive_component(conn):
    """pain should separate reached from missed; fit (all zero) should not."""
    for i in range(50):
        lid = _add(conn, business_name=f"hi{i}", tier="B", pain=6, fit=0,
                   phone=f"(630) 801-{i:04d}")
        _dial(conn, lid, "reached")
    for i in range(50):
        lid = _add(conn, business_name=f"lo{i}", tier="B", pain=0, fit=0,
                   phone=f"(630) 802-{i:04d}")
        _dial(conn, lid, "no_answer")
    sep = {s["field"]: s for s in leads.backtest(conn)["separation"]}
    assert sep["pain"]["gap"] == 6.0     # perfectly predictive
    assert sep["fit"]["gap"] == 0.0      # dead weight


def test_backtest_ignores_leads_that_were_never_dialed(conn):
    """An uncalled lead tells us nothing and must not dilute the denominator."""
    _population(conn, "A", 35, 1.0, 1000)
    for i in range(500):
        _add(conn, business_name=f"cold{i}", tier="A", phone=f"(630) 901-{i:04d}")
    r = leads.backtest(conn)
    assert r["leads_dialed"] == 35
    assert {g["group"]: g["dialed"] for g in r["by_tier"]} == {"A": 35}
    assert r["by_tier"][0]["contact_rate"] == 1.0


def test_backtest_marks_thin_groups_and_excludes_them_from_the_verdict(conn):
    _population(conn, "A", 40, 0.5, 1000)
    _population(conn, "B", 40, 0.2, 2000)
    _population(conn, "C", 3, 1.0, 3000)     # 3 calls, 100%, pure noise
    r = leads.backtest(conn)
    thin = {g["group"]: g["thin"] for g in r["by_tier"]}
    assert thin["C"] is True and thin["A"] is False
    # C's fake 100% must not flip the verdict
    assert r["verdict"] == "ordering holds"


def test_backtest_never_mutates_a_tier_or_score(conn):
    """Scoring belongs to enrich_prospects.py. This reports and nothing else."""
    _population(conn, "A", 35, 0.1, 1000)
    before = db.rows_to_dicts(conn.execute(
        "SELECT id, tier, fit, pain, reach, total FROM leads ORDER BY id").fetchall())
    leads.backtest(conn)
    after = db.rows_to_dicts(conn.execute(
        "SELECT id, tier, fit, pain, reach, total FROM leads ORDER BY id").fetchall())
    assert before == after


# ------------------------------------- quotes Ian can safely say out loud

@pytest.mark.parametrize("quote, readable", [
    ("Called three times, never heard back", True),
    ("No answer for phone or message", True),
    # accusations, not missed-call complaints: reading these ends the call
    ("They are unresponsive, rude, harassing", False),
    ("This company is a scam", False),
    ("No response from them or their legal department", False),
    ("I had to get an attorney involved", False),
    # the CUSTOMER admits they were the unreachable one, quoting it is false
    ("There were times when I was unresponsive to calls from the office", False),
    ("I never answered when they called", False),
    ("", False),
])
def test_quote_is_readable(quote, readable):
    assert leads.quote_is_readable(quote) is readable


def test_unsafe_quote_falls_through_to_a_softer_hook():
    """A quote Ian cannot say out loud is worse than no quote at all."""
    hostile = leads.call_card({
        "business_name": "X", "claims_247": 1, "rating": 1.4, "reviews": 40,
        "miss_signal": "...they are unresponsive, rude, harassing and awful...",
    })
    assert hostile["hook_kind"] != "promise_vs_proof"
    assert "rude" not in hostile["hook"]
    assert "harassing" not in hostile["hook"]

    self_ref = leads.call_card({
        "business_name": "Y", "claims_247": 1,
        "miss_signal": "...there were times when I was unresponsive to calls...",
    })
    assert self_ref["hook_kind"] == "promise"      # not quoted back as their fault
    assert "unresponsive" not in self_ref["hook"]


def test_a_clean_missed_call_quote_still_gets_quoted():
    card = leads.call_card({
        "business_name": "Z", "claims_247": 1,
        "miss_signal": "...called three times and never heard back...",
    })
    assert card["hook_kind"] == "promise_vs_proof"
    assert "never heard back" in card["hook"].lower()
