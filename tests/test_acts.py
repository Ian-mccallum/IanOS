"""SPEC-v37 §4: Ring 1 acts. The safety-critical laws this file asserts:

- Law A5 (test_ring1_act_writes_receipt): a failed receipt insert rolls back
  the act's own write too, not just itself -- an act with no receipt row is
  a bug, never a state the DB can land in.
- §4.2 (test_ring1_act_is_reversible): every act type's inverse restores the
  prior row exactly, including the edge case a naive design misses (undoing
  a goal.rebaseline that set a deadline on a goal that had none).
- §4.2 "Never Ring 1" (test_ring1_cannot_touch_forbidden): no act reaches
  money movement, leads, journal, health values, school completions,
  proposal decisions, verified=1 (forward), focus, or brief.
"""

from __future__ import annotations

import inspect
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import runner  # noqa: E402
from core import acts, attention, db, learning  # noqa: E402


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    c = db.connect()
    yield c
    c.close()


def _seed_goal(conn, name="Test goal", target="10", deadline=None, domain="business"):
    cur = conn.execute(
        "INSERT INTO goals (name, target, deadline, domain) VALUES (?, ?, ?, ?)",
        (name, target, deadline, domain),
    )
    conn.commit()
    return cur.lastrowid


def _seed_transaction(conn, category="", amount=-5.0, description="Coffee shop"):
    cur = conn.execute(
        "INSERT INTO transactions (date, description, amount, category) VALUES (?,?,?,?)",
        (db.today(), description, amount, category),
    )
    conn.commit()
    return cur.lastrowid


# --------------------------------------------------------------- Law A5

def test_ring1_act_writes_receipt(conn, monkeypatch):
    """An act with a failed receipt insert rolls back entirely: no note, no
    receipt, no memo -- not a note that exists with nothing to show for it."""
    def boom(*a, **k):
        raise RuntimeError("receipt insert failed")
    monkeypatch.setattr(db, "insert_agent_act", boom)

    with pytest.raises(RuntimeError):
        acts.note_create(conn, role="steward", plane="nightly", thread_id=None,
                          body="test note body")

    assert conn.execute("SELECT COUNT(*) n FROM notes").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) n FROM agent_acts").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) n FROM memos").fetchone()["n"] == 0


def test_ring1_act_writes_receipt_on_an_update_act_too(conn, monkeypatch):
    """Same law, but for an act that mutates an existing row rather than
    creating one: the mutation itself must not survive either."""
    tx_id = _seed_transaction(conn, category="dining")

    def boom(*a, **k):
        raise RuntimeError("receipt insert failed")
    monkeypatch.setattr(db, "insert_agent_act", boom)

    with pytest.raises(RuntimeError):
        acts.transaction_recategorize(conn, role="cfo", plane="nightly", thread_id=None,
                                       transaction_id=tx_id, category="business")

    assert db.get_transaction(conn, tx_id)["category"] == "dining"
    assert conn.execute("SELECT COUNT(*) n FROM agent_acts").fetchone()["n"] == 0


# ------------------------------------------------------ "Never Ring 1" (§4.2)

FORBIDDEN_ACTS = (
    "money.transfer", "money.send", "money.trade",
    "lead.stage", "lead.touch", "lead.run",
    "journal.write", "journal.share",
    "health.log", "health.value",
    "school.complete",
    "proposal.decide", "proposal.approve", "proposal.reject",
    "fact.verify",
    "focus.write",
    "brief.write",
)

ALL_ROLES = ("steward", "watchdog", "cfo", "scout", "coach", "physician",
             "lovebird", "wealth", "counsel", "chief")


def test_ring1_cannot_touch_forbidden():
    for role in ALL_ROLES:
        for act in FORBIDDEN_ACTS:
            assert not acts.ring1_allowed(role, act), f"{role} must never get {act}"
    assert set(acts.RING1_ACTS).isdisjoint(FORBIDDEN_ACTS)


def test_fact_flag_unverified_cannot_set_verified_to_one():
    """Not just a runtime check: the function has no argument that could
    carry a caller-supplied verified=1 through to the write."""
    sig = inspect.signature(acts.fact_flag_unverified)
    assert "verified" not in sig.parameters


def test_ring1_denies_a_role_without_the_grant(conn):
    with pytest.raises(acts.ActError):
        acts.gym_confirm(conn, role="cfo", plane="nightly", thread_id=None)


def test_unknown_plane_is_rejected(conn):
    with pytest.raises(acts.ActError):
        acts.note_create(conn, role="steward", plane="daytime", thread_id=None, body="x")
    assert conn.execute("SELECT COUNT(*) n FROM notes").fetchone()["n"] == 0


# ------------------------------------------------------------- plan_block

def test_plan_block_create_is_reversible(conn):
    today = db.today()
    out = acts.plan_block_create(conn, role="steward", plane="nightly", thread_id=None,
                                  date_=today, start_time="09:00", end_time="10:00",
                                  title="Deep work")
    block_id = out["result"]["id"]
    assert db.get_plan_block(conn, block_id) is not None

    acts.undo_act(conn, out["act_id"])
    assert db.get_plan_block(conn, block_id) is None


def test_plan_block_move_is_reversible(conn):
    today = db.today()
    block = db.create_plan_block(conn, today, "09:00", "10:00", "Original")
    out = acts.plan_block_move(conn, role="steward", plane="nightly", thread_id=None,
                                block_id=block["id"], date_=today,
                                start_time="11:00", end_time="12:00")
    assert db.get_plan_block(conn, block["id"])["start_time"] == "11:00"

    acts.undo_act(conn, out["act_id"])
    restored = db.get_plan_block(conn, block["id"])
    assert restored["start_time"] == "09:00" and restored["end_time"] == "10:00"


def test_plan_block_create_rejects_a_past_date(conn):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with pytest.raises(acts.ActError):
        acts.plan_block_create(conn, role="steward", plane="nightly", thread_id=None,
                                date_=yesterday, start_time="09:00", end_time="10:00",
                                title="Too late")


def test_plan_block_create_rejects_end_before_start(conn):
    with pytest.raises(acts.ActError):
        acts.plan_block_create(conn, role="steward", plane="nightly", thread_id=None,
                                date_=db.today(), start_time="10:00", end_time="09:00",
                                title="Backwards")


def test_plan_block_delete_is_reversible(conn):
    today = db.today()
    block = db.create_plan_block(conn, today, "09:00", "10:00", "To delete")
    out = acts.plan_block_delete(conn, role="steward", plane="nightly", thread_id=None,
                                  block_id=block["id"])
    assert db.get_plan_block(conn, block["id"]) is None

    acts.undo_act(conn, out["act_id"])
    restored = db.get_plan_block(conn, block["id"])
    assert restored is not None
    assert restored["id"] == block["id"]
    assert restored["title"] == "To delete"


# ------------------------------------------------------------------ note

def test_note_create_is_reversible(conn):
    out = acts.note_create(conn, role="steward", plane="nightly", thread_id=None,
                            body="Call the landlord")
    note_id = out["result"]["id"]
    assert db.note(conn, note_id)["deleted_at"] is None

    acts.undo_act(conn, out["act_id"])
    assert db.note(conn, note_id)["deleted_at"] is not None


# ------------------------------------------------------------ partner_task

def test_partner_task_create_is_reversible(conn):
    out = acts.partner_task_create(conn, role="steward", plane="nightly", thread_id=None,
                                  title="Pack lunch")
    task_id = out["result"]["id"]
    assert db.get_partner_task(conn, task_id) is not None

    acts.undo_act(conn, out["act_id"])
    assert db.get_partner_task(conn, task_id) is None


def test_partner_task_complete_is_reversible(conn):
    task = db.add_partner_task(conn, "Homework")
    out = acts.partner_task_complete(conn, role="steward", plane="nightly", thread_id=None,
                                    task_id=task["id"])
    assert db.get_partner_task(conn, task["id"])["done"] is True

    acts.undo_act(conn, out["act_id"])
    assert db.get_partner_task(conn, task["id"])["done"] is False


# --------------------------------------------------------------- gym.confirm

def test_gym_confirm_is_reversible(conn):
    out = acts.gym_confirm(conn, role="coach", plane="nightly", thread_id=None)
    today = db.today()
    row = conn.execute("SELECT gym_confirmed FROM health_daily WHERE date=?", (today,)).fetchone()
    assert row["gym_confirmed"] == 1
    assert conn.execute(
        "SELECT kind FROM streak_events WHERE date=?", (today,)
    ).fetchone()["kind"] == "confirm"

    acts.undo_act(conn, out["act_id"])
    row = conn.execute("SELECT gym_confirmed FROM health_daily WHERE date=?", (today,)).fetchone()
    assert row["gym_confirmed"] == 0
    assert conn.execute(
        "SELECT COUNT(*) n FROM streak_events WHERE date=?", (today,)
    ).fetchone()["n"] == 0


# -------------------------------------------------------------- activity.log

def test_activity_log_is_reversible(conn):
    today = db.today()
    out = acts.activity_log(conn, role="scout", plane="nightly", thread_id=None,
                             audit_calls=5, follow_ups=2)
    row = conn.execute("SELECT * FROM activity WHERE date=?", (today,)).fetchone()
    assert row["audit_calls"] == 5 and row["follow_ups"] == 2

    acts.undo_act(conn, out["act_id"])
    row = conn.execute("SELECT * FROM activity WHERE date=?", (today,)).fetchone()
    assert row["audit_calls"] == 0 and row["follow_ups"] == 0


def test_activity_log_rejects_negative_and_empty(conn):
    with pytest.raises(acts.ActError):
        acts.activity_log(conn, role="scout", plane="nightly", thread_id=None, audit_calls=-1)
    with pytest.raises(acts.ActError):
        acts.activity_log(conn, role="scout", plane="nightly", thread_id=None)


def test_activity_log_does_not_clobber_a_same_day_increment(conn):
    """Reversibility must not mean 'replace': two increments the same day
    both land, and undoing the second leaves the first standing."""
    acts.activity_log(conn, role="scout", plane="nightly", thread_id=None, audit_calls=3)
    out2 = acts.activity_log(conn, role="scout", plane="nightly", thread_id=None, audit_calls=4)
    today = db.today()
    assert conn.execute(
        "SELECT audit_calls FROM activity WHERE date=?", (today,)
    ).fetchone()["audit_calls"] == 7

    acts.undo_act(conn, out2["act_id"])
    assert conn.execute(
        "SELECT audit_calls FROM activity WHERE date=?", (today,)
    ).fetchone()["audit_calls"] == 3


# ------------------------------------------------------------------- goal

def test_goal_rebaseline_is_reversible_including_a_deadline_that_was_never_set(conn):
    """The edge case a naive undo misses: the goal started with NO deadline,
    so undo must clear it back to NULL, not merely leave the act's value."""
    goal_id = _seed_goal(conn, target="10", deadline=None)
    out = acts.goal_rebaseline(conn, role="watchdog", plane="nightly", thread_id=None,
                                goal_id=goal_id, target="20", deadline="2026-12-01")
    updated = db.get_goal(conn, goal_id)
    assert updated["target"] == "20" and updated["deadline"] == "2026-12-01"

    acts.undo_act(conn, out["act_id"])
    restored = db.get_goal(conn, goal_id)
    assert restored["target"] == "10"
    assert restored["deadline"] is None


def test_goal_rebaseline_never_touches_domain_or_hero(conn):
    goal_id = _seed_goal(conn, domain="business")
    conn.execute("UPDATE goals SET hero=1 WHERE id=?", (goal_id,))
    conn.commit()
    acts.goal_rebaseline(conn, role="watchdog", plane="nightly", thread_id=None,
                          goal_id=goal_id, target="99")
    after = db.get_goal(conn, goal_id)
    assert after["domain"] == "business"
    assert after["hero"] == 1


def test_goal_archive_is_reversible(conn):
    old_deadline = (date.today() - timedelta(days=20)).isoformat()
    goal_id = _seed_goal(conn, deadline=old_deadline)
    out = acts.goal_archive(conn, role="watchdog", plane="nightly", thread_id=None,
                             goal_id=goal_id)
    assert db.get_goal(conn, goal_id)["archived"] == 1

    acts.undo_act(conn, out["act_id"])
    assert db.get_goal(conn, goal_id)["archived"] == 0


def test_goal_archive_pins_both_edges_of_the_14_day_window(conn):
    """Law A12: a guardrail that can't fail proves nothing."""
    exactly_14 = (date.today() - timedelta(days=14)).isoformat()
    goal_a = _seed_goal(conn, name="exactly 14", deadline=exactly_14)
    with pytest.raises(acts.ActError):
        acts.goal_archive(conn, role="watchdog", plane="nightly", thread_id=None, goal_id=goal_a)

    just_over = (date.today() - timedelta(days=15)).isoformat()
    goal_b = _seed_goal(conn, name="15 days", deadline=just_over)
    acts.goal_archive(conn, role="watchdog", plane="nightly", thread_id=None, goal_id=goal_b)
    assert db.get_goal(conn, goal_b)["archived"] == 1


def test_goal_archive_rejects_when_a_dependent_is_still_unarchived(conn):
    base_id = _seed_goal(conn, name="base", deadline=(date.today() - timedelta(days=30)).isoformat())
    dep_id = _seed_goal(conn, name="dependent")
    conn.execute("UPDATE goals SET depends_on_goal_id=? WHERE id=?", (base_id, dep_id))
    conn.commit()
    with pytest.raises(acts.ActError):
        acts.goal_archive(conn, role="watchdog", plane="nightly", thread_id=None, goal_id=base_id)


# ----------------------------------------------------- transaction.recategorize

def test_transaction_recategorize_is_reversible(conn):
    tx_id = _seed_transaction(conn, category="dining")
    out = acts.transaction_recategorize(conn, role="cfo", plane="nightly", thread_id=None,
                                         transaction_id=tx_id, category="business")
    assert db.get_transaction(conn, tx_id)["category"] == "business"

    acts.undo_act(conn, out["act_id"])
    assert db.get_transaction(conn, tx_id)["category"] == "dining"


def test_transaction_recategorize_never_touches_amount_date_or_account(conn):
    tx_id = _seed_transaction(conn, category="dining", amount=-42.5)
    before = db.get_transaction(conn, tx_id)
    acts.transaction_recategorize(conn, role="cfo", plane="nightly", thread_id=None,
                                   transaction_id=tx_id, category="business")
    after = db.get_transaction(conn, tx_id)
    assert after["amount"] == before["amount"]
    assert after["date"] == before["date"]
    assert after["account"] == before["account"]
    assert after["hash"] == before["hash"]
    assert after["source"] == before["source"]


# ------------------------------------------------------- fact.flag_unverified

def test_fact_flag_unverified_is_reversible(conn):
    fact_id = db.upsert_fact(conn, "business", "test:topic", "some fact", verified=1)
    out = acts.fact_flag_unverified(conn, role="cfo", plane="nightly", thread_id=None,
                                     fact_id=fact_id)
    assert db.get_fact(conn, fact_id)["verified"] == 0

    acts.undo_act(conn, out["act_id"])
    assert db.get_fact(conn, fact_id)["verified"] == 1


# ----------------------------------------------------------- attention.snooze

def test_attention_snooze_is_reversible(conn):
    out = acts.attention_snooze(conn, role="steward", plane="nightly", thread_id=None,
                                 item_key="goal:1", days=3)
    assert "goal:1" in db.active_snooze_keys(conn)

    acts.undo_act(conn, out["act_id"])
    assert "goal:1" not in db.active_snooze_keys(conn)


def test_attention_snooze_undo_restores_a_prior_snooze_rather_than_clearing_it(conn):
    now = datetime.now()
    acts.attention_snooze(conn, role="steward", plane="nightly", thread_id=None,
                           item_key="goal:1", days=1, now=now)
    first_until = conn.execute(
        "SELECT snoozed_until FROM attention_snoozes WHERE item_key='goal:1'"
    ).fetchone()[0]

    out2 = acts.attention_snooze(conn, role="steward", plane="nightly", thread_id=None,
                                  item_key="goal:1", days=5, now=now)
    acts.undo_act(conn, out2["act_id"])
    restored = conn.execute(
        "SELECT snoozed_until FROM attention_snoozes WHERE item_key='goal:1'"
    ).fetchone()[0]
    assert restored == first_until


def test_attention_snooze_rejects_over_7_days(conn):
    with pytest.raises(acts.ActError):
        acts.attention_snooze(conn, role="steward", plane="nightly", thread_id=None,
                               item_key="goal:1", days=8)


def test_snoozed_item_excluded_from_attention(conn):
    # A fresh DB seeds a demo partner task, which is the (only) "partner_action"
    # candidate; whichever key it is, snoozing it must remove that kind
    # entirely from the ranked order.
    now = datetime.now()
    before = attention.compile_attention(conn, now)
    partner_keys = [c.key for c in before.ranked if c.kind == "partner_action"]
    assert len(partner_keys) == 1
    key = partner_keys[0]

    acts.attention_snooze(conn, role="steward", plane="nightly", thread_id=None,
                           item_key=key, days=3, now=now)
    after = attention.compile_attention(conn, now)
    assert not any(c.key == key for c in after.ranked)


# -------------------------------------------------------------- undo mechanics

def test_undo_is_not_available_twice(conn):
    out = acts.note_create(conn, role="steward", plane="nightly", thread_id=None, body="x")
    acts.undo_act(conn, out["act_id"])
    with pytest.raises(acts.ActError):
        acts.undo_act(conn, out["act_id"])


def test_undo_stamps_undone_at_and_writes_a_memo(conn):
    out = acts.note_create(conn, role="steward", plane="nightly", thread_id=None, body="x")
    acts.undo_act(conn, out["act_id"])
    receipt = db.get_agent_act(conn, out["act_id"])
    assert receipt["undone_at"] is not None
    assert conn.execute(
        "SELECT COUNT(*) n FROM memos WHERE topic='undo'"
    ).fetchone()["n"] == 1


def test_every_ring1_act_has_an_undo_handler():
    for act in acts.RING1_ACTS:
        assert act in acts._UNDO_HANDLERS, f"{act} has no undo handler"


def test_every_act_tool_is_registered_with_the_sdk_server():
    """A tool granted in ALLOWLISTS but absent from REGISTERED_TOOLS was
    never passed to create_sdk_mcp_server, so it silently does not exist for
    any real agent -- only a test calling `.handler(...)` directly (bypassing
    the SDK's own dispatch) could ever reach it. This is exactly the bug
    Phase 4's integration caught: all thirteen act_* tools were fully built,
    fully tested at the handler level, and fully unreachable in practice."""
    act_tool_names = {
        "act_plan_block_create", "act_plan_block_move", "act_plan_block_delete",
        "act_note_create", "act_partner_task_create", "act_partner_task_complete",
        "act_gym_confirm", "act_activity_log", "act_goal_rebaseline",
        "act_goal_archive", "act_transaction_recategorize",
        "act_fact_flag_unverified", "act_attention_snooze",
        "act_task_create", "act_task_complete", "act_learning_confirm",
    }
    assert act_tool_names <= runner.ALL_TOOLS
    registered_names = {t.name for t in runner.REGISTERED_TOOLS}
    assert act_tool_names <= registered_names


# --------------------------------------------------------------------- task

def test_task_create_is_reversible(conn):
    out = acts.task_create(conn, role="steward", plane="nightly", thread_id=None,
                            title="Renew parking")
    task_id = out["result"]["id"]
    assert db.get_task(conn, task_id) is not None
    assert db.get_task(conn, task_id)["priority"] == 0

    acts.undo_act(conn, out["act_id"])
    assert db.get_task(conn, task_id) is None


def test_task_complete_is_reversible(conn):
    row = db.create_task(conn, "Pack lunch")
    out = acts.task_complete(conn, role="steward", plane="nightly", thread_id=None,
                              task_id=row["id"])
    assert db.get_task(conn, row["id"])["done_at"] is not None

    acts.undo_act(conn, out["act_id"])
    assert db.get_task(conn, row["id"])["done_at"] is None


def test_task_create_capped_per_night(conn):
    acts.task_create(conn, role="steward", plane="nightly", thread_id=None,
                      title="a", already_created_tonight=0)
    acts.task_create(conn, role="steward", plane="nightly", thread_id=None,
                      title="b", already_created_tonight=1)
    with pytest.raises(acts.ActError):
        acts.task_create(conn, role="steward", plane="nightly", thread_id=None,
                          title="c", already_created_tonight=2)


def test_only_steward_may_apply_task_acts(conn):
    with pytest.raises(acts.ActError):
        acts.task_create(conn, role="watchdog", plane="nightly", thread_id=None, title="x")
    with pytest.raises(acts.ActError):
        acts.task_complete(conn, role="cfo", plane="nightly", thread_id=None, task_id=1)


# --------------------------------------------------------------- learning

def _seed_active_topic(conn, name="case interviews") -> int:
    learning.ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO learning_topics (name, status, origin, profile) "
        "VALUES (?, 'active', 'user', 'started three weeks ago')",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def test_learning_confirm_today_only(conn):
    # Arrange: an active topic with today's session row already written.
    # Act: confirm it through the Ring 1 act as tutor.
    # Assert: the session is completed and exactly one confirm event exists, no grace/reset.
    topic_id = _seed_active_topic(conn)
    today = db.today()
    learning.create_or_replace_session(conn, today, topic_id, "walk one case")
    acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)
    session = learning.get_session(conn, today)
    assert session["status"] == "completed"
    events = conn.execute("SELECT kind FROM learning_streak_events").fetchall()
    assert [e["kind"] for e in events] == ["confirm"]


def test_learning_confirm_requires_a_session_row(conn):
    # Arrange: an active topic but no session row for today.
    # Act/Assert: confirming raises ActError rather than creating one.
    _seed_active_topic(conn)
    with pytest.raises(acts.ActError):
        acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)


def test_learning_confirm_is_reversible(conn):
    # Arrange: a confirmed session.
    # Act: undo the act.
    # Assert: the session reopens and its confirm event is gone.
    topic_id = _seed_active_topic(conn)
    today = db.today()
    learning.create_or_replace_session(conn, today, topic_id, "walk one case")
    out = acts.learning_confirm(conn, role="tutor", plane="nightly", thread_id=None)
    acts.undo_act(conn, out["act_id"])
    session = learning.get_session(conn, today)
    assert session["status"] == "open"
    assert conn.execute("SELECT COUNT(*) n FROM learning_streak_events").fetchone()["n"] == 0


def test_ring1_denies_learning_confirm_to_other_roles(conn):
    # Arrange: nothing (the grant table is static).
    # Act/Assert: every role but tutor is refused learning.confirm.
    with pytest.raises(acts.ActError):
        acts.learning_confirm(conn, role="coach", plane="nightly", thread_id=None)
