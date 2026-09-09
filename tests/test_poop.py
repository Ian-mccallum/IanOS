"""Body's log: the laws, not the implementation.

Every test here fails if a rule the feature was designed around gets thinned:
events instead of tallies, a soft delete that Undo can reach, a day stamped at
the tap rather than at the sync, one writer, and the note wall in front of the
two agents that can read anything about it at all.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


# ------------------------------------------------------------------ the table

def test_the_count_is_derived_from_rows_never_stored(conn):
    """D3. There is no counter column to drift, so an undo cannot leave one
    behind: the day's number is COUNT(*) over the rows that survive."""
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(poop_log)")}
    assert not {"count", "total", "tally"} & columns, (
        "poop_log stores a tally; the count must always be derived from rows"
    )
    for _ in range(3):
        db.log_poop(conn, day="2026-09-09")
    assert db.poop_state(conn, "2026-09-09")["today_count"] == 3


def test_delete_is_soft_and_undo_restores_the_same_row(conn):
    """osUI: a swipe or a mistap is one thumb-slip away, so the delete must be
    reversible and must bring the same id back, not a fresh log."""
    entry = db.log_poop(conn, day="2026-09-09", bristol=4, note="fine")
    db.delete_poop(conn, entry["id"])
    assert db.poop_state(conn, "2026-09-09")["today_count"] == 0
    assert db.get_poop(conn, entry["id"]) is None

    restored = db.restore_poop(conn, entry["id"])
    assert restored["id"] == entry["id"]
    assert restored["bristol"] == 4 and restored["note"] == "fine"
    assert db.poop_state(conn, "2026-09-09")["today_count"] == 1


def test_the_day_is_stamped_at_the_tap_not_at_the_write(conn):
    """The gym-confirm law: a 2pm tap on a sleeping Mac that syncs at 6pm
    still belongs to the day it happened."""
    db.log_poop(conn, day="2026-09-07")
    assert db.poop_state(conn, "2026-09-07")["today_count"] == 1
    assert db.poop_state(conn, "2026-09-09")["today_count"] == 0


def test_bristol_is_optional_and_bounded(conn):
    plain = db.log_poop(conn, day="2026-09-09")
    assert plain["bristol"] is None and plain["note"] == ""
    for bad in (0, 8, -1, 3.5):
        with pytest.raises(ValueError):
            db.log_poop(conn, day="2026-09-09", bristol=bad)
    assert db.update_poop(conn, plain["id"], bristol=6)["bristol"] == 6
    assert db.update_poop(conn, plain["id"], bristol=None)["bristol"] is None


def test_the_rail_reports_zero_days_instead_of_skipping_them(conn):
    """D5: one read path, and it must not make a caller guess which dates a
    sparse table left out."""
    db.log_poop(conn, day="2026-09-09")
    db.log_poop(conn, day="2026-09-06")
    rail = db.poop_daily_counts(conn, 7, today_iso="2026-09-09")
    assert [d["day"] for d in rail] == [
        "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06",
        "2026-09-07", "2026-09-08", "2026-09-09",
    ]
    assert [d["count"] for d in rail] == [0, 0, 0, 1, 0, 0, 1]


# ---------------------------------------------------------------- the writers

def test_no_agent_tool_writes_this_table():
    """One writer (D2): Ian's taps, through the API. Ring 1's act list is a
    closed set and the log is deliberately not in it."""
    from core import acts

    assert not [a for a in acts.RING1_ACTS if "poop" in a], (
        "a Ring 1 act writes the log; logging is Ian's tap, not an agent's"
    )
    runner_src = (ROOT / "agents" / "runner.py").read_text(encoding="utf-8")
    assert "log_poop" not in runner_src and "db.update_poop" not in runner_src, (
        "an agent tool writes poop_log"
    )


def test_agents_see_the_counts_and_never_the_note():
    """Counts and Bristol ride read_health's existing consent gate. `note` is
    Ian's own writing about himself, which follows the journal/notes wall."""
    runner_src = (ROOT / "agents" / "runner.py").read_text(encoding="utf-8")
    start = runner_src.index('@tool("read_health"')
    body = runner_src[start:runner_src.index("@tool", start + 10)]
    assert "bowel_log" in body, "read_health does not carry the log at all"
    for leaked in ('"note"', "poop[\"entries\"]", "'entries'"):
        assert leaked not in body, f"read_health exposes note text via {leaked}"
    # And the gate itself is still the first thing the tool checks.
    assert body.index("HEALTH_AI_READERS") < body.index("bowel_log")


def test_the_log_is_not_in_the_polled_state(conn):
    """/api/state is polled every 15s and cached by the phone's service
    worker; the sensor values are kept off it and so is this."""
    main_src = (ROOT / "api" / "main.py").read_text(encoding="utf-8")
    state_src = main_src[main_src.index('@app.get("/api/state")'):]
    state_src = state_src[:state_src.index("\n@app.")]
    assert "poop" not in state_src


# -------------------------------------------------------------------- the API

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.connect().close()
    from fastapi.testclient import TestClient

    from api import main

    return TestClient(main.app)


def test_a_tap_logs_and_returns_the_fresh_day(client):
    r = client.post("/api/poop", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["entry"]["bristol"] is None
    assert body["state"]["today_count"] == 1
    assert len(body["state"]["rail"]) == 7


def test_the_log_is_never_cached(client):
    for path in ("/api/poop/today", "/api/poop"):
        r = client.post(path, json={}) if path == "/api/poop" else client.get(path)
        assert r.headers.get("cache-control") == "no-store", path


def test_an_out_of_range_bristol_is_refused(client):
    assert client.post("/api/poop", json={"bristol": 9}).status_code == 422
    assert client.post("/api/poop", json={"bristol": 7}).status_code == 200


def test_delete_then_restore_round_trips_through_the_api(client):
    entry_id = client.post("/api/poop", json={}).json()["entry"]["id"]
    assert client.delete(f"/api/poop/{entry_id}").json()["state"]["today_count"] == 0
    restored = client.post(f"/api/poop/{entry_id}/restore", json={})
    assert restored.json()["state"]["today_count"] == 1
    assert client.delete("/api/poop/9999").status_code == 404


def test_a_replayed_offline_tap_does_not_log_twice(client):
    """SPEC-v20: the queue replays the same mutation identity, so a lost
    response must not become a second poop."""
    headers = {
        "X-ianOS-Mutation-Id": "11111111-1111-4111-8111-111111111111",
        "X-ianOS-Effective-Date": "2026-09-09",
        "X-ianOS-Captured-At": "2026-09-09T14:32:00-05:00",
    }
    first = client.post("/api/poop", json={}, headers=headers)
    second = client.post("/api/poop", json={}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.headers.get("X-ianOS-Replayed") == "1"
    assert second.json()["state"]["today_count"] == 1
    assert first.json()["entry"]["day"] == "2026-09-09"


# --------------------------------------------------------------- the backfill
# Forgetting at 10am and remembering at 6pm is the normal case, so the entry
# must be able to carry the time it actually happened.

def test_a_backfill_keeps_its_own_time_and_day(client):
    from datetime import datetime, timedelta

    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    r = client.post("/api/poop", json={"logged_at": f"{yesterday} 10:00:00", "bristol": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["entry"]["logged_at"] == f"{yesterday} 10:00:00"
    assert body["entry"]["day"] == yesterday
    assert body["entry"]["bristol"] == 3
    # The panel shows one day; a backfill of another must not replace it.
    assert body["state"]["day"] != yesterday
    assert body["state"]["today_count"] == 0
    assert [d for d in body["state"]["rail"] if d["day"] == yesterday][0]["count"] == 1


def test_a_backfill_earlier_today_counts_today(client):
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    body = client.post("/api/poop", json={"logged_at": f"{today} 00:05:00"}).json()
    assert body["entry"]["day"] == today
    assert body["state"]["today_count"] == 1


def test_a_log_cannot_be_in_the_future_or_ancient(client):
    from datetime import datetime, timedelta

    ahead = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    old = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    assert client.post("/api/poop", json={"logged_at": ahead}).status_code == 422
    assert client.post("/api/poop", json={"logged_at": old}).status_code == 422
    assert client.post("/api/poop", json={"logged_at": "not a time"}).status_code == 422


def test_a_backfill_stays_naive_local_like_its_neighbours(client):
    """SPEC-v18 law 4: one aware timestamp among naive-local rows shifts every
    comparison by the offset and nothing looks broken until it matters."""
    from datetime import datetime

    aware = datetime.now().astimezone().replace(microsecond=0).isoformat()
    assert client.post("/api/poop", json={"logged_at": aware}).status_code == 422
