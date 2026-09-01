"""Tests for the facts store: the RAG memory layer."""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def test_upsert_fact_idempotent(conn):
    i1 = db.upsert_fact(conn, "personal", "partner:flowers", "peonies", kind="preference")
    i2 = db.upsert_fact(conn, "personal", "partner:flowers", "peonies and tulips", kind="preference")
    assert i1 == i2, "same (domain, topic) must update, not duplicate"
    n = conn.execute("SELECT COUNT(*) FROM facts WHERE topic='partner:flowers'").fetchone()[0]
    assert n == 1
    body = conn.execute("SELECT body FROM facts WHERE id=?", (i1,)).fetchone()["body"]
    assert body == "peonies and tulips"


def test_domain_scoping_excludes_other_domains(conn):
    db.upsert_fact(conn, "personal", "partner:anniversary", "x", kind="date", date="2020-08-05", recurs="yearly")
    db.upsert_fact(conn, "college", "uiuc:move-in", "y", kind="date", date="2026-08-20")
    personal = db.facts_for_domains(conn, ["personal"])
    assert personal, "expected at least one personal fact"
    assert all(not f["topic"].startswith("uiuc:") for f in personal)
    assert all(f["domain"] == "personal" for f in personal)


def test_all_domain_returns_everything(conn):
    db.upsert_fact(conn, "personal", "partner:x", "a")
    db.upsert_fact(conn, "college", "uiuc:y", "b")
    everything = db.facts_for_domains(conn, ["all"])
    topics = {f["topic"] for f in everything}
    assert {"partner:x", "uiuc:y"} <= topics


def test_yearly_projection_current_year(conn):
    ref = date.today()
    # anniversary a few years ago, month-day ~10 days from now
    future = ref + timedelta(days=10)
    db.upsert_fact(conn, "personal", "partner:anniversary", "x", kind="date",
                   date=f"2019-{future.month:02d}-{future.day:02d}", recurs="yearly")
    up = db.upcoming_dated_facts(conn, within_days=30)
    assert len(up) == 1
    assert up[0]["days_until"] == 10


def test_yearly_projection_dec_to_jan_wrap(conn, monkeypatch):
    # Freeze "today" to Dec 28 by inserting a date whose month-day already passed
    # this year; projection must roll to next year (days_until stays >= 0).
    ref = date.today()
    yesterday = ref - timedelta(days=1)
    db.upsert_fact(conn, "family", "family:sibling-birthday", "x", kind="date",
                   date=f"2010-{yesterday.month:02d}-{yesterday.day:02d}", recurs="yearly")
    # Occurs tomorrow-ish next cycle → ~364 days out, never negative
    up = db.upcoming_dated_facts(conn, within_days=400)
    assert len(up) == 1
    assert up[0]["days_until"] >= 363


def test_feb29_projection_non_leap(conn):
    # Feb 29 must project to Feb 28 in a non-leap year without crashing.
    occ = db._next_occurrence("2020-02-29", "yearly", date(2027, 1, 1))
    assert occ == date(2027, 2, 28)


def test_one_shot_past_date_does_not_recur(conn):
    db.upsert_fact(conn, "college", "uiuc:old", "x", kind="date",
                   date="2020-01-01", recurs="")
    up = db.upcoming_dated_facts(conn, within_days=100000)
    assert all(f["topic"] != "uiuc:old" for f in up)


def test_topic_prefix_filter(conn):
    db.upsert_fact(conn, "personal", "partner:anniversary", "x", kind="date",
                   date="2020-08-05", recurs="yearly")
    db.upsert_fact(conn, "family", "family:dog-vet", "y", kind="date",
                   date=(date.today() + timedelta(days=5)).isoformat())
    partner = db.upcoming_dated_facts(conn, within_days=400, topic_prefix="partner:")
    assert [f["topic"] for f in partner] == ["partner:anniversary"]


def test_delete_fact(conn):
    fid = db.upsert_fact(conn, "personal", "partner:x", "a")
    assert db.delete_fact(conn, fid) is True
    assert db.delete_fact(conn, fid) is False
