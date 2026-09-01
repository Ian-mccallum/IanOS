"""Plan engine (SPEC-v7 Phase A): pure derivations + API round-trip.

Pure functions (is_sailed, next_free_slot, overpack_warning) need no DB.
suggest_blocks + adherence + the API hit a temp SQLite via a monkeypatched
DB_PATH. No network, no iCloud, no LLM anywhere.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, plan  # noqa: E402

# Deterministic reference days.
WEEKDAY = "2026-07-21"   # Tuesday
WEEKEND = "2026-07-18"   # Saturday


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _blk(start, end, status="planned"):
    return {"start_time": start, "end_time": end, "status": status}


# ---------------------------------------------------------------- is_sailed

@pytest.mark.parametrize("block, today, now, expected", [
    ({"status": "planned", "date": "2026-07-20", "end_time": "10:00"}, "2026-07-21", "08:00", True),   # past day
    ({"status": "planned", "date": "2026-07-21", "end_time": "09:00"}, "2026-07-21", "09:30", True),   # today, ended
    ({"status": "planned", "date": "2026-07-21", "end_time": "09:00"}, "2026-07-21", "08:30", False),  # today, not yet
    ({"status": "planned", "date": "2026-07-21", "end_time": "09:00"}, "2026-07-21", "09:00", True),   # boundary end==now
    ({"status": "done", "date": "2026-07-01", "end_time": "10:00"}, "2026-07-21", "23:59", False),     # done never sails
    ({"status": "planned", "date": "2026-07-22", "end_time": "09:00"}, "2026-07-21", "23:59", False),  # future day
])
def test_is_sailed(block, today, now, expected):
    assert plan.is_sailed(block, today, now) is expected


# ------------------------------------------------------------ next_free_slot

def test_next_free_slot_empty_day():
    assert plan.next_free_slot([], [], 60, "08:00") == ("08:00", "09:00")


def test_next_free_slot_rounds_up_to_15():
    assert plan.next_free_slot([], [], 60, "08:07") == ("08:15", "09:15")


def test_next_free_slot_floor_is_6am():
    assert plan.next_free_slot([], [], 30, "05:00") == ("06:00", "06:30")


def test_next_free_slot_skips_commitment():
    commit = [{"start_time": "09:00", "end_time": "10:00"}]
    assert plan.next_free_slot([], commit, 60, "08:30") == ("10:00", "11:00")


def test_next_free_slot_skips_existing_block():
    assert plan.next_free_slot([_blk("08:00", "09:00")], [], 30, "08:00") == ("09:00", "09:30")


def test_next_free_slot_ignores_all_day_commitment():
    # all-day rows carry no times and must not block the ribbon
    assert plan.next_free_slot([], [{"start_time": None, "end_time": None}], 60, "08:00") == ("08:00", "09:00")


def test_next_free_slot_clamps_at_22():
    start, _ = plan.next_free_slot([], [], 60, "23:00")
    assert start == "22:00"


# ------------------------------------------------------------ overpack_warning

def test_overpack_none_under_limits():
    blocks = [_blk("06:00", "06:30"), _blk("07:00", "07:30"), _blk("08:00", "08:30"),
              _blk("09:00", "09:30"), _blk("10:00", "10:30")]  # 5 blocks, 150 min
    assert plan.overpack_warning(blocks) is None


def test_overpack_warns_over_5_blocks():
    blocks = [_blk(f"{h:02d}:00", f"{h:02d}:30") for h in range(6, 12)]  # 6 blocks
    assert plan.overpack_warning(blocks) is not None


def test_overpack_warns_over_6_hours():
    blocks = [_blk("06:00", "09:00"), _blk("10:00", "13:30")]  # 6.5h across 2 blocks
    assert plan.overpack_warning(blocks) is not None


def test_overpack_ignores_done_blocks():
    blocks = [_blk(f"{h:02d}:00", f"{h:02d}:30", "done") for h in range(6, 14)]  # 8 done
    assert plan.overpack_warning(blocks) is None


# ------------------------------------------------------------- suggest_blocks

def test_suggest_calls_and_gym_on_empty_weekday(conn):
    # fresh DB: no brief, no hero, no activity, gym unconfirmed; partner tasks seeded
    keys = [s["key"] for s in plan.suggest_blocks(conn, WEEKDAY)]
    assert keys == ["calls", "gym", "partner"]


def test_suggest_caps_at_four_in_priority_order(conn):
    conn.execute("INSERT INTO briefs (date, kind, body, day_command) VALUES (?, 'daily', ?, ?)",
                 (WEEKDAY, "brief body", "do the thing"))
    conn.execute("INSERT INTO goals (name, kind, target, domain, hero) VALUES (?, 'goal', '1', 'business', 1)",
                 ("Sign client #1",))
    conn.commit()
    keys = [s["key"] for s in plan.suggest_blocks(conn, WEEKDAY)]
    assert keys == ["command", "hero", "calls", "gym"]  # partner dropped by the 4-cap


def test_suggest_hero_carries_goal_name_and_id(conn):
    conn.execute("INSERT INTO goals (name, kind, target, domain, hero) VALUES (?, 'goal', '1', 'business', 1)",
                 ("Sign client #1",))
    conn.commit()
    hero = next(s for s in plan.suggest_blocks(conn, WEEKDAY) if s["key"] == "hero")
    assert hero["title"] == "Deep work: Sign client #1"
    assert hero["goal_id"] is not None


def test_suggest_no_gym_on_weekend(conn):
    assert "gym" not in [s["key"] for s in plan.suggest_blocks(conn, WEEKEND)]


def test_suggest_no_calls_when_quota_met(conn):
    conn.execute("INSERT INTO activity (date, audit_calls) VALUES (?, 25)", (WEEKDAY,))
    conn.commit()
    assert "calls" not in [s["key"] for s in plan.suggest_blocks(conn, WEEKDAY)]


# --------------------------------------------------------------- adherence

def test_plan_adherence_7d(conn):
    today = "2026-07-21"
    db.create_plan_block(conn, "2026-07-20", "09:00", "10:00", "A")
    b = db.create_plan_block(conn, "2026-07-21", "09:00", "10:00", "B")
    db.update_plan_block(conn, b["id"], status="done")
    db.create_plan_block(conn, "2026-07-10", "09:00", "10:00", "old")  # outside window
    assert plan.plan_adherence_7d(conn, today) == {"planned": 1, "done": 1}


# ---------------------------------------------------------------- API layer

def test_api_plan_block_roundtrip(conn):
    from api import main as apimain

    row = apimain.add_plan_block(apimain.PlanBlockIn(
        date="2026-07-21", start_time="09:00", end_time="10:00", title="  Call block  "))
    assert row["status"] == "planned"
    assert row["title"] == "Call block"  # trimmed
    bid = row["id"]

    done = apimain.patch_plan_block(bid, apimain.PlanBlockUpdate(status="done"))
    assert done["status"] == "done"

    # simulate a prior iCloud sync so delete must leave a tombstone
    conn.execute("UPDATE plan_blocks SET caldav_uid = 'uid-1' WHERE id = ?", (bid,))
    conn.commit()

    apimain.remove_plan_block(bid)
    assert db.get_plan_block(conn, bid) is None
    assert conn.execute(
        "SELECT 1 FROM plan_tombstones WHERE caldav_uid = 'uid-1'"
    ).fetchone() is not None


def test_api_rejects_unsnapped_time(conn):
    from fastapi import HTTPException
    from api import main as apimain
    with pytest.raises(HTTPException):
        apimain.add_plan_block(apimain.PlanBlockIn(
            date="2026-07-21", start_time="09:07", end_time="10:00", title="x"))


def test_api_rejects_end_before_start(conn):
    from fastapi import HTTPException
    from api import main as apimain
    with pytest.raises(HTTPException):
        apimain.add_plan_block(apimain.PlanBlockIn(
            date="2026-07-21", start_time="10:00", end_time="09:00", title="x"))


def test_api_accepts_any_length_block(conn):
    # blocks longer than the UI's presets (e.g. a 4-hour deep-work marathon) are valid
    from api import main as apimain
    row = apimain.add_plan_block(apimain.PlanBlockIn(
        date="2026-07-24", start_time="09:00", end_time="13:00", title="Deep work marathon"))
    assert row["start_time"] == "09:00" and row["end_time"] == "13:00"


def test_api_day_shape(conn):
    from api import main as apimain
    apimain.add_plan_block(apimain.PlanBlockIn(
        date="2026-07-21", start_time="09:00", end_time="10:00", title="Call block"))
    day = apimain.get_day(date="2026-07-21")
    assert day["date"] == "2026-07-21"
    assert len(day["blocks"]) == 1
    assert "sailed" in day["blocks"][0]
    assert set(day["icloud"].keys()) == {"configured", "last_sync"}
    assert isinstance(day["suggestions"], list)


# ------------------------------------------------------- SPEC-v15: day bounds

def test_day_bounds_default_window():
    assert plan.day_bounds([], []) == (6 * 60, 23 * 60)


def test_day_bounds_widen_for_early_block():
    # The API accepts 00:00-23:59 but the ribbon rendered 06:00-23:00, so an
    # early block saved, returned 200, and rendered off-grid (SPEC-v15 C2).
    blocks = [{"start_time": "05:00", "end_time": "06:00"}]
    assert plan.day_bounds(blocks, []) == (5 * 60, 23 * 60)


def test_day_bounds_widen_for_late_block():
    blocks = [{"start_time": "23:00", "end_time": "23:45"}]
    assert plan.day_bounds(blocks, []) == (6 * 60, 24 * 60)


def test_day_bounds_widen_for_commitment():
    commits = [{"start_time": "04:30", "end_time": "05:30"}]
    assert plan.day_bounds([], commits) == (4 * 60, 23 * 60)


def test_day_bounds_ignores_all_day_commitment_without_times():
    assert plan.day_bounds([], [{"start_time": None, "end_time": None}]) == (6 * 60, 23 * 60)


# -------------------------------------------------------- SPEC-v15: quick add

@pytest.mark.parametrize("text,now,expected", [
    ("gym 7", "06:00", ("gym", "07:00", "08:00")),
    # Same words, later in the day: 07:00 has passed, so it can only mean tonight.
    ("gym 7", "09:00", ("gym", "19:00", "20:00")),
    ("deep work 2h @ 9", "07:00", ("deep work", "09:00", "11:00")),
    ("call block 30m 2pm", "09:00", ("call block", "14:00", "14:30")),
    ("partner dinner 6-8", "09:00", ("partner dinner", "18:00", "20:00")),
    ("standup 9:15-9:30", "08:00", ("standup", "09:15", "09:30")),
    ("deep work 90m", "09:00", ("deep work", "09:00", "10:30")),
    ("lunch 12", "09:00", ("lunch", "12:00", "13:00")),
    ("read 11-1", "08:00", ("read", "11:00", "13:00")),
    ("call block 1.5h at 14:30", "09:00", ("call block", "14:30", "16:00")),
])
def test_parse_quick_add(text, now, expected):
    got = plan.parse_quick_add(text, now)
    assert got is not None, text
    assert (got["title"], got["start_time"], got["end_time"]) == expected


@pytest.mark.parametrize("text", ["", "   ", "7", "9pm", "12-1"])
def test_parse_quick_add_rejects_empty_and_lone_times(text):
    # A lone time fragment is not a plan; without the guard a bare hour became
    # a block literally titled "7".
    assert plan.parse_quick_add(text, "09:00") is None


def test_parse_quick_add_keeps_words_made_of_time_letters():
    got = plan.parse_quick_add("map", "09:00")
    assert got is not None and got["title"] == "map"


def test_parse_quick_add_defaults_to_next_free_slot():
    blocks = [{"start_time": "09:00", "end_time": "10:00"}]
    got = plan.parse_quick_add("deep work", "09:00", blocks=blocks)
    assert got["start_time"] == "10:00" and got["end_time"] == "11:00"


def test_parse_quick_add_never_returns_end_before_start():
    for text in ["a 11-1", "b 9-9", "c 23-1"]:
        got = plan.parse_quick_add(text, "08:00")
        if got:
            assert got["end_time"] > got["start_time"], text
