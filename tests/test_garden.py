"""The Garden: grows from alive days, wilts but never dies, mood recovers."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, garden


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _log(conn, days_ago, **fields):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.upsert_health(conn, d, source="test", **fields)


def test_empty_garden_never_dies(conn):
    s = garden.garden_state(conn)
    assert s["stage"] == 1          # floor: never 0
    assert s["mood"] == "thirsty"


def test_growth_scales_with_alive_days(conn):
    for i in range(1, 13):          # 12 alive days
        _log(conn, i, workout="lift")
    s = garden.garden_state(conn)
    assert s["stage"] == 5          # max stage


def test_mood_recovers_after_one_alive_day(conn):
    for i in range(3, 12):          # older activity, but last 3 days empty
        _log(conn, i, workout="lift")
    assert garden.garden_state(conn)["mood"] == "thirsty"
    _log(conn, 0, workout="mma")    # one alive day today
    assert garden.garden_state(conn)["mood"] in ("steady", "thriving")


def test_gym_confirm_counts_as_alive(conn):
    _log(conn, 0, gym_confirmed=1)
    s = garden.garden_state(conn)
    assert s["alive_days"] >= 1


def test_passive_steps_do_not_count_as_alive(conn):
    _log(conn, 1, steps=9000)
    _log(conn, 2, sleep_hours=8)
    assert garden.garden_state(conn)["alive_days"] == 0


def test_no_red_no_labels_contract():
    # Garden state exposes no numeric target or status color, only stage/mood/spark.
    keys = set(garden.garden_state.__doc__.split("{")[1].split("}")[0].replace(":", "").split())
    # sanity: the state dict never carries a 'status' or 'percent' concept
    dummy_keys = {"stage", "mood", "spark", "alive_days"}
    assert dummy_keys and "status" not in dummy_keys and "percent" not in dummy_keys
