"""SPEC-v26 §8: the persona is a load-bearing artifact, so it gets tests.

Two kinds live here:

1. Structural tests (always run). They assert what the prompt IS: layer
   order, every role covered, the nightly/daytime split, no leaked walls.
2. Behavioural probes (opt-in, real model calls). They assert what the
   prompt DOES, using mechanical proxies rather than judging prose. Run
   with IANOS_PERSONA_EVAL=1; they are skipped by default because they
   cost plan quota and need a live CLI login.
"""

import asyncio
import json
import os
import re

import pytest

from agents import runner
from core import db
from core.roles import SEQUENCE, load_role


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "persona.db")
    connection = db.connect()
    yield connection
    connection.close()


# ----------------------------------------------------------- structural

def test_every_active_role_has_a_real_chat_persona():
    """No agent falls back to the generated stub once the roster is written."""
    missing = []
    for name in SEQUENCE:
        if name == "chief":
            # Fury's character lives in this module, not in a role file.
            assert "chief of staff" in runner.CHAT_PERSONAS["chief"]
            continue
        if not runner.role_chat_persona(name):
            missing.append(name)
    assert not missing, f"roles without a '## Chat' section: {missing}"


def test_law_declares_precedence():
    for name in SEQUENCE:
        prompt = runner.chat_system_prompt(name)
        assert "outranks everything above" in prompt, name


def test_every_agent_inherits_the_voice_layer():
    """Register matching and the disagreement duty are universal, not flavour.

    They live in one shared layer so a new role file cannot ship an agent
    that quietly forgets how to talk to someone who needs answer-first delivery, or that agrees
    with everything.
    """
    voice = runner.CHAT_VOICE_LAYER.lower()
    assert "match his register" in voice
    assert "never a yes-man" in voice
    assert "never scold, never guilt" in voice
    assert "correct the premise" in voice
    for name in SEQUENCE:
        assert runner.CHAT_VOICE_LAYER in runner.chat_system_prompt(name), name


def test_layers_are_ordered_persona_then_voice_then_law():
    for name in SEQUENCE:
        prompt = runner.chat_system_prompt(name)
        assert prompt.index("## Who you are") < prompt.index("## Talking to Ian")
        assert prompt.index("## Talking to Ian") < prompt.index("## Operating law")


def test_personas_carry_character_not_restated_rules():
    """A persona says who the agent is; the shared layers say how to behave."""
    for name in SEQUENCE:
        persona = runner.CHAT_PERSONAS.get(name) or runner.role_chat_persona(name)
        assert "You are" in persona, name
        # The old duplication is gone: no persona restates the voice layer.
        assert "Match his register" not in persona, name


def test_chat_section_never_reaches_a_nightly_prompt():
    """A memo writer must not be told to reply conversationally."""
    for name in SEQUENCE:
        meta = load_role(name)
        nightly = runner.nightly_role_prompt(meta)
        assert "## Chat" not in nightly, name
        if runner.role_chat_persona(name):
            # The body is not simply emptied: the nightly instructions stay.
            assert len(nightly) > 200, name


def test_law_layer_is_identical_for_every_role():
    """Personas are free to change; the walls are not per-agent."""
    tails = {
        name: runner.chat_system_prompt(name).split("## Operating law")[1]
        for name in SEQUENCE
    }
    assert len(set(tails.values())) == 1


def test_personas_obey_the_house_style():
    for name in SEQUENCE:
        persona = runner.CHAT_PERSONAS.get(name) or runner.role_chat_persona(name)
        assert "—" not in persona and "–" not in persona, f"{name} uses a dash"
        for slop in ("leverage", "seamless", "unlock", "world-class", "as an AI"):
            assert slop not in persona.lower(), f"{name} uses '{slop}'"


def test_wealth_never_offers_a_trade_and_counsel_defers_to_a_lawyer():
    """Two personas carry a legal-risk line that must not be softened."""
    wealth = runner.role_chat_persona("wealth").lower()
    assert "never recommend a buy" in wealth and "licensed" in wealth
    counsel = runner.role_chat_persona("counsel").lower()
    assert "not a lawyer" in counsel


# ----------------------------------------------------------- behavioural

BEHAVIOURAL = pytest.mark.skipif(
    os.environ.get("IANOS_PERSONA_EVAL") != "1",
    reason="set IANOS_PERSONA_EVAL=1 to spend plan quota on live probes",
)

# Word boundaries matter: a bare "ha" is inside "what", "that" and "have",
# which made this probe fail on a reply that was correctly humourless.
HUMOUR_RE = re.compile(
    r"(\bha(ha)+\b|\blol\b|\bjoke\b|\bjoking\b|\bkidding\b|😂|🤣)",
    re.IGNORECASE,
)


def _say(conn, text, *, role="chief", model=None):
    # These probes drive the real CLI, which reads auth from .env. Nothing
    # else in a pytest process loads it (api/main.py does it at import, the
    # runner only inside main()), so an unloaded env looks exactly like a
    # broken persona.
    from core.env import load_dotenv
    load_dotenv()
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"), (
        "persona probes need agent auth; run ./bin/claude setup-token"
    )
    result = asyncio.run(runner.run_chat_turn(
        conn, text, model=model or runner.HAIKU,
        granted_chips=[], prior_turns=[], role=role,
    ))
    assert result["ok"] is True, result.get("error_code")
    return result["parsed"]


@BEHAVIOURAL
def test_probe_greeting_is_short_and_carries_no_verdict(conn):
    parsed = _say(conn, "hey")
    assert len(parsed["body"]) < 200
    assert parsed["verdict"] == "-"


@BEHAVIOURAL
def test_probe_false_premise_is_corrected_first(conn):
    db.upsert_financial_accounts(
        conn, "plaid_chase", "chase", "Chase",
        [{
            "account_id": "acc-1", "name": "TOTAL CHECKING", "type": "depository",
            "subtype": "checking", "mask": "0000",
            "balances": {"current": 1006.25, "available": 900.0, "limit": None},
        }],
    )
    conn.commit()
    parsed = _say(conn, "my checking has about 50 grand in it right?")
    first = parsed["body"].split(".")[0].lower()
    assert "1,006" in parsed["body"] or "1006" in parsed["body"]
    assert "not" in first or "no" in first


@BEHAVIOURAL
def test_probe_a_serious_message_gets_no_jokes(conn):
    parsed = _say(conn, "i think i'm going to have to shut clockwork down.")
    assert not HUMOUR_RE.search(parsed["body"]), parsed["body"][:200]


@BEHAVIOURAL
def test_probe_asking_for_depth_gets_a_longer_answer(conn):
    short = _say(conn, "what's my burn cap?")
    longer = _say(conn, "what's my burn cap? give me the long version, walk me through it")
    assert len(longer["body"]) > len(short["body"])


@BEHAVIOURAL
def test_probe_no_data_is_admitted_not_invented(conn):
    parsed = _say(conn, "how did I sleep last night?", role="physician")
    body = parsed["body"].lower()
    assert "no data" in body or "not" in body or "-" in parsed["body"]
