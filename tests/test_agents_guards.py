"""Agent hard-rule guards: wealth never trades, read_facts is domain-scoped."""

import asyncio
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from agents import runner


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _result_text(res: dict) -> str:
    return res["content"][0]["text"]


def test_wealth_cannot_propose_a_trade(conn):
    runner.RUN.update(role="wealth", conn=conn, role_domains=["finance"])
    res = asyncio.run(runner.create_proposal.handler(
        {"action": "Buy 10 shares of VOO", "reasoning": "cheap", "kind": "task"}))
    assert res.get("is_error") is True
    assert "BLOCKED" in _result_text(res)
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0


def test_wealth_can_propose_an_observation(conn):
    runner.RUN.update(role="wealth", conn=conn, role_domains=["finance"])
    res = asyncio.run(runner.create_proposal.handler(
        {"action": "Review your Fidelity cash sweep rate", "reasoning": "cash drag", "kind": "task"}))
    assert not res.get("is_error")
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1


def test_non_cfo_cannot_propose_money(conn):
    runner.RUN.update(role="lovebird", conn=conn, role_domains=["personal"])
    res = asyncio.run(runner.create_proposal.handler(
        {"action": "Spend $200 on a gift", "reasoning": "anniversary", "kind": "money"}))
    assert res.get("is_error") is True
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0


def test_read_facts_is_domain_scoped(conn):
    db.upsert_fact(conn, "personal", "partner:anniversary", "x", kind="date",
                   date="2020-08-05", recurs="yearly")
    db.upsert_fact(conn, "college", "uiuc:move-in", "y", kind="date", date="2026-08-20")
    runner.RUN.update(role="lovebird", conn=conn, role_domains=["personal"])
    res = asyncio.run(runner.read_facts.handler({}))
    payload = json.loads(_result_text(res))
    topics = [f["topic"] for f in payload["facts"]]
    assert "partner:anniversary" in topics
    assert all(not t.startswith("uiuc:") for t in topics)


# ------------------------------------------------ SPEC-v37 §8.4: read_accounts

def test_read_accounts_allowlisted_to_cfo_wealth_and_chief_only(conn):
    conn.execute(
        "INSERT INTO financial_accounts (source, external_id, institution, name, "
        "type, subtype, current_balance, as_of) VALUES (?,?,?,?,?,?,?,?)",
        ("plaid_chase", "checking1", "Chase", "Checking", "depository", "checking",
         500.0, "2026-09-01"),
    )
    conn.commit()
    for role, domains in (("cfo", ["finance"]), ("wealth", ["finance"]), ("chief", ["all"])):
        runner.RUN.update(role=role, conn=conn, role_domains=domains)
        res = asyncio.run(runner.read_accounts.handler({}))
        assert not res.get("is_error"), f"{role} should be able to read accounts"
        payload = json.loads(_result_text(res))
        assert payload["net_worth"] == 500.0
        assert payload["accounts"][0]["institution"] == "Chase"

    assert "read_accounts" not in runner.ALLOWLISTS["physician"]
    assert "read_accounts" not in runner.ALLOWLISTS["scout"]
    assert "read_accounts" in runner.ALL_TOOLS, (
        "must be in REGISTERED_TOOLS or no real agent could ever call it "
        "(the Phase 4 act_* precedent)"
    )


def test_write_fact_specialist_stays_in_own_domain(conn):
    # A finance agent trying to write a partner: (personal) fact is rejected.
    runner.RUN.update(role="wealth", conn=conn, role_domains=["finance"])
    res = asyncio.run(runner.write_fact.handler(
        {"topic": "partner:flowers", "body": "peonies", "kind": "preference"}))
    assert res.get("is_error") is True


def test_write_memo_rejects_bad_priority(conn):
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"])
    bad = asyncio.run(runner.write_memo.handler(
        {"topic": "t", "body": "b", "priority": 7}))
    assert bad.get("is_error") is True
    assert conn.execute("SELECT COUNT(*) FROM memos").fetchone()[0] == 0
    ok = asyncio.run(runner.write_memo.handler(
        {"topic": "t", "body": "b", "priority": 3}))
    assert not ok.get("is_error")
    row = conn.execute("SELECT priority FROM memos ORDER BY id DESC LIMIT 1").fetchone()
    assert row["priority"] == 3


def test_write_fact_date_requires_date(conn):
    runner.RUN.update(role="advisor", conn=conn, role_domains=["college"])
    memo_id = db.add_memo(conn, "advisor", "registration", "Registration opens November 3.")
    res = asyncio.run(runner.write_fact.handler(
        {"topic": "uiuc:reg", "body": "registration", "kind": "date"}))
    assert res.get("is_error") is True
    ok = asyncio.run(runner.write_fact.handler(
        {"topic": "uiuc:reg", "body": "registration", "kind": "date",
         "date": "2026-11-03", "source_memo_ids": [memo_id],
         "evidence": [{"source": f"memo:{memo_id}"}]}))
    assert not ok.get("is_error")


def test_write_fact_requires_real_memo_citations(conn):
    runner.RUN.update(role="advisor", conn=conn, role_domains=["college"])
    missing = asyncio.run(runner.write_fact.handler(
        {"topic": "uiuc:registration", "body": "Registration is open", "kind": "fact"}))
    assert missing.get("is_error") is True
    assert "source memo" in _result_text(missing)

    memo_id = db.add_memo(conn, "advisor", "registration", "Registration is open.")
    nonexistent = asyncio.run(runner.write_fact.handler(
        {"topic": "uiuc:registration", "body": "Registration is open", "kind": "fact",
         "source_memo_ids": [999999], "evidence": [{"source": f"memo:{memo_id}"}]}))
    assert nonexistent.get("is_error") is True
    assert "source memo" in _result_text(nonexistent)
    assert conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 0


# --------------------------------------------- The Line is read-only (v9 §9)

def _seed_lead(conn, **kw):
    from core import leads as leads_mod
    fields = {"business_name": "Lakeshore Heating", "tier": "A", "total": 16,
              "market": "north", "segment": "trades", "city": "Plainfield",
              "phone": "(630) 555-0142"}
    fields.update(kw)
    db.upsert_lead(conn, leads_mod.norm_phone(fields["phone"]), **fields)
    conn.commit()


def test_read_pipeline_is_limited_to_scout_and_chief(conn):
    _seed_lead(conn)
    for role in ("scout", "chief"):
        runner.RUN.update(role=role, conn=conn, role_domains=["business"])
        res = asyncio.run(runner.read_pipeline.handler({}))
        assert not res.get("is_error"), f"{role} should be able to read the pipeline"
        assert "tier_counts" in json.loads(_result_text(res))

    for role in ("cfo", "lovebird", "wealth", "archivist", "steward"):
        runner.RUN.update(role=role, conn=conn, role_domains=["finance"])
        res = asyncio.run(runner.read_pipeline.handler({}))
        assert res.get("is_error") is True, f"{role} must not see the pipeline"


def test_no_agent_tool_can_write_a_lead_stage_touch_or_run():
    """Ian owns every outcome. The guarantee is that no write tool EXISTS."""
    for name in runner.ALL_TOOLS:
        assert "lead" not in name or name == "read_pipeline"
    writers = {t for t in runner.ALL_TOOLS if t.startswith("write_") or t.startswith("create_")}
    assert writers == {"write_memo", "write_brief", "write_focus", "write_fact",
                       "write_health_insight", "create_proposal"}
    for allowed in runner.ALLOWLISTS.values():
        assert not any(t.startswith("write_lead") or t.endswith("_touch") for t in allowed)


def test_read_pipeline_reports_counts_not_run_behaviour(conn):
    """Agents see dials and outcomes, never 'he stopped after 4' (SPEC-v9 §9)."""
    _seed_lead(conn)
    runner.RUN.update(role="scout", conn=conn, role_domains=["business"])
    payload = json.loads(_result_text(asyncio.run(runner.read_pipeline.handler({}))))
    assert "heat" not in json.dumps(payload)
    assert "run_state" not in payload
    assert set(payload) >= {"tier_counts", "stage_counts", "callbacks_due_today",
                            "dials_last_7d", "runway", "next_5"}


def test_scout_allowlist_has_pipeline_and_no_write_path(conn):
    allowed = runner.ALLOWLISTS["scout"]
    assert "read_pipeline" in allowed
    assert runner.ALLOWLISTS["chief"] >= {"read_pipeline"}
    # scout may only ever memo, propose, or apply its two Ring 1 acts
    # (SPEC-v37 §4.4: activity.log, fact.flag_unverified) -- still no
    # writing counterpart on the pipeline itself. search_memory (§5.4) is a
    # read tool too, it just doesn't carry the read_ prefix.
    assert {t for t in allowed if not t.startswith("read_") and t != "search_memory"} == {
        "write_memo", "create_proposal", "act_activity_log", "act_fact_flag_unverified",
    }


def test_pipeline_prompt_lines_are_precomputed(conn):
    """Date math and counts happen in Python, never in the model."""
    _seed_lead(conn)
    text = runner._pipeline_lines(conn)
    assert "THE LINE" in text
    assert "Lakeshore Heating" in text          # the queue names the shop
    assert "weekdays" in text                # runway math already resolved
    # coverage arrives as a finished percentage, the model never divides
    assert re.search(r"\(\d+% coverage\)", text)


def test_pipeline_prompt_handles_an_empty_pipeline(conn):
    assert "no leads imported yet" in runner._pipeline_lines(conn)
