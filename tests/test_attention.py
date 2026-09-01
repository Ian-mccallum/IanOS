"""SPEC-v21 attention compiler: deterministic order and privacy walls."""

from __future__ import annotations

import json
import sys
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import attention, db, leads  # noqa: E402


NOW_MORNING = datetime(2026, 8, 14, 9, 0)  # Friday
NOW_EVENING = datetime(2026, 8, 14, 18, 0)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    connection = db.connect()
    yield connection
    connection.close()


def empty_preloaded(**updates):
    values = {
        "active_promises": [],
        "due_callbacks": [],
        "plan_blocks": [],
        "goals": [],
        "pending_proposals": [],
        "gym": {"confirmed_today": True},
        "lead_queue": [],
        "activity": {"audit_calls": leads.DAILY_QUOTA, "follow_ups": 10},
        "partner_tasks": [],
        "stale_domains": [],
        "goal_lookup": {},
        "school_items": [],
        "school_meetings": [],
    }
    values.update(updates)
    return values


def candidate(key: str, kind: str, band: int, *, due_at=None, source_order=0):
    return attention.Candidate(
        key=key,
        kind=kind,
        label=key,
        reason=f"reason {key}",
        route="more",
        interaction="navigate",
        ref_id=None,
        band=band,
        due_at=due_at,
        source_order=source_order,
        stable_order=key,
        evidence=(attention.Evidence("test", "key", key),),
        audiences=frozenset({"public", "chief"}),
        push_policy=None,
    )


def test_contract_is_frozen_and_rejects_aware_time_or_unknown_interactions():
    item = candidate("x", "gym", 2)
    with pytest.raises(FrozenInstanceError):
        item.label = "changed"
    with pytest.raises(ValueError, match="timezone-naive"):
        candidate("aware", "callback", 1, due_at=NOW_MORNING.replace(tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="unsupported interaction"):
        attention.Candidate(
            **{**item.__dict__, "key": "bad", "interaction": "POST /api/delete"}
        )
    with pytest.raises(ValueError, match="not allowlisted"):
        attention.Candidate(
            **{
                **item.__dict__,
                "key": "bad-field",
                "interaction": "activity_increment",
                "ref_id": "notes",
            }
        )


def test_ranking_bands_due_time_and_duplicates_are_deterministic():
    rows = [
        candidate("maintenance", "stale_source", 3),
        candidate("routine", "gym", 2),
        candidate("soon-late", "goal_deadline", 1, due_at=NOW_MORNING + timedelta(days=2)),
        candidate("breach", "callback", 0, due_at=NOW_MORNING - timedelta(days=1)),
        candidate("soon-early", "goal_deadline", 1, due_at=NOW_MORNING + timedelta(days=1)),
    ]
    first = attention.rank_candidates(rows, NOW_MORNING)
    second = attention.rank_candidates(list(reversed(rows)), NOW_MORNING)
    assert [item.key for item in first] == [
        "breach", "soon-early", "soon-late", "routine", "maintenance"
    ]
    assert [item.key for item in second] == [item.key for item in first]
    with pytest.raises(ValueError, match="duplicate attention"):
        attention.rank_candidates([rows[0], rows[0]], NOW_MORNING)


@pytest.mark.parametrize(
    "now, expected",
    [
        (NOW_MORNING, ["gym", "call_run", "follow_up_capture", "proposal_decision", "partner_action"]),
        (NOW_EVENING, ["proposal_decision", "partner_action", "call_run", "follow_up_capture", "gym"]),
    ],
)
def test_routine_session_order_matches_product(now, expected):
    rows = [candidate(kind, kind, 2, source_order=i) for i, kind in enumerate(reversed(expected))]
    assert [item.kind for item in attention.rank_candidates(rows, now)] == expected


def test_collection_assigns_bands_routes_and_real_labels(conn):
    preloaded = empty_preloaded(
        active_promises=[{
            "id": 1,
            "status": "new",
            "source": "btc",
            "promised_by": "2026-08-14 08:30:00",
            "email": "private@example.com",
            "phone": "6305550100",
            "message": "private message",
            "consent": "private consent",
        }],
        due_callbacks=[{
            "id": 2,
            "business_name": "Riverbend Locksmith",
            "next_touch": "2026-08-14",
            "stage": "attempted",
            "tier": "A",
        }],
        plan_blocks=[{
            "id": 3,
            "date": "2026-08-14",
            "start_time": "08:30",
            "end_time": "09:30",
            "title": "Write the proposal",
            "status": "planned",
        }],
        goals=[{
            "id": 4,
            "kind": "deadline",
            "name": "File school form",
            "domain": "school",
            "deadline": "2026-08-15",
            "current_value": "",
            "archived": 0,
        }],
        pending_proposals=[{
            "id": 5,
            "status": "PENDING",
            "created_at": "2026-08-12 08:00:00",
            "action": "private action detail",
        }],
        gym={"confirmed_today": False},
        partner_tasks=[{"id": 6, "title": "Make the reservation", "done": False}],
        stale_domains=["finance"],
        activity={"audit_calls": leads.DAILY_QUOTA, "follow_ups": 0},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    by_key = {item.key: item for item in result.ranked}

    assert by_key["promise:1"].band == 0
    assert by_key["lead:2"].band == 1
    assert by_key["plan:3"].band == 1
    assert by_key["goal:4"].route == "school"
    assert by_key["proposal:5"].band == 1
    assert by_key["gym:2026-08-14"].interaction == "gym_confirm"
    assert by_key["partner:6"].label == "For Partner: Make the reservation"
    assert by_key["stale:finance"].band == 3
    assert by_key["activity:follow_ups:2026-08-14"].ref_id == "follow_ups"
    assert by_key["lead:2"].label == "Call Riverbend Locksmith"


@pytest.mark.parametrize("domain, route", [
    ("business", "btc"),
    ("health", "body"),
    ("finance", "money"),
    ("school", "school"),
    ("personal", "life"),
])
def test_goal_deadline_uses_existing_pillar_route(conn, domain, route):
    preloaded = empty_preloaded(goals=[{
        "id": 42,
        "kind": "deadline",
        "name": "Real deadline",
        "domain": domain,
        "deadline": "2026-08-15",
        "current_value": "",
        "archived": 0,
    }])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.route == route


def test_goal_blocked_by_archived_parent_lands_at_band_3(conn):
    preloaded = empty_preloaded(
        goals=[{
            "id": 7, "kind": "deadline", "name": "EIN", "domain": "business",
            "deadline": "2026-08-15", "current_value": "", "archived": 0,
            "depends_on_goal_id": 6,
        }],
        goal_lookup={6: {"id": 6, "name": "LLC filing", "archived": 1, "current_value": "filed"}},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.band == 3
    assert "LLC filing" in result.next.reason
    assert result.next.due_at is None


def test_goal_blocked_by_not_done_parent_lands_at_band_3(conn):
    preloaded = empty_preloaded(
        goals=[{
            "id": 8, "kind": "deadline", "name": "A2P", "domain": "business",
            "deadline": "2026-08-15", "current_value": "", "archived": 0,
            "depends_on_goal_id": 6,
        }],
        goal_lookup={6: {"id": 6, "name": "LLC filing", "archived": 0, "current_value": "in progress"}},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.band == 3
    assert "LLC filing" in result.next.reason


def test_goal_unblocked_when_parent_is_done_and_not_archived(conn):
    preloaded = empty_preloaded(
        goals=[{
            "id": 7, "kind": "deadline", "name": "EIN", "domain": "business",
            "deadline": "2026-08-01", "current_value": "", "archived": 0,
            "depends_on_goal_id": 6,
        }],
        goal_lookup={6: {"id": 6, "name": "LLC filing", "archived": 0, "current_value": "filed"}},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.band == 0
    assert result.next.band != 3


def test_goal_without_dependency_is_unaffected(conn):
    preloaded = empty_preloaded(goals=[{
        "id": 42, "kind": "deadline", "name": "Real deadline", "domain": "business",
        "deadline": "2026-08-15", "current_value": "", "archived": 0,
    }])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.band == 1
    assert result.next.reason == "due Aug 15"


def test_goal_with_missing_parent_is_unblocked(conn):
    preloaded = empty_preloaded(
        goals=[{
            "id": 7, "kind": "deadline", "name": "EIN", "domain": "business",
            "deadline": "2026-08-15", "current_value": "", "archived": 0,
            "depends_on_goal_id": 999,
        }],
        goal_lookup={},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    assert result.next is not None
    assert result.next.band == 1


def test_proposal_candidates_cap_at_three_oldest():
    rows = [
        {"id": 1, "status": "PENDING", "created_at": "2026-08-05 09:00:00"},
        {"id": 2, "status": "PENDING", "created_at": "2026-08-01 09:00:00"},
        {"id": 3, "status": "PENDING", "created_at": "2026-08-10 09:00:00"},
        {"id": 4, "status": "PENDING", "created_at": "2026-08-02 09:00:00"},
        {"id": 5, "status": "PENDING", "created_at": "2026-08-14 09:00:00"},
    ]
    out = attention._proposal_candidates(rows, NOW_MORNING)
    keys = {item.key for item in out}
    assert keys == {"proposal:2", "proposal:4", "proposal:1"}


def test_callbacks_ignore_quota_while_routine_calls_do_not(conn):
    preloaded = empty_preloaded(
        due_callbacks=[{
            "id": 10,
            "business_name": "Callback Co",
            "next_touch": "2026-08-14",
            "stage": "attempted",
            "tier": "C",
        }],
        lead_queue=[{
            "id": 11,
            "business_name": "Routine Co",
            "stage": "new",
            "tier": "A",
            "queue_reason": "tier A",
        }],
        activity={"audit_calls": leads.DAILY_QUOTA, "follow_ups": 10},
    )
    keys = {item.key for item in attention.collect_candidates(conn, NOW_MORNING, preloaded=preloaded)}
    assert "lead:10" in keys
    assert "lead:11" not in keys


def test_completed_archived_handled_and_future_rows_disappear(conn):
    preloaded = empty_preloaded(
        active_promises=[
            {"id": 1, "status": "confirmed", "source": "btc", "promised_by": "2026-08-14 10:00:00"},
            {"id": 2, "status": "new", "source": "btc", "promised_by": "2026-08-15 10:00:00"},
        ],
        due_callbacks=[
            {"id": 3, "business_name": "Won", "next_touch": "2026-08-14", "stage": "won", "tier": "A"},
            {"id": 4, "business_name": "Future", "next_touch": "2026-08-15", "stage": "new", "tier": "A"},
        ],
        plan_blocks=[{
            "id": 5, "date": "2026-08-14", "start_time": "08:00", "end_time": "09:00",
            "title": "Done", "status": "done",
        }],
        goals=[{
            "id": 6, "kind": "deadline", "name": "Done goal", "domain": "business",
            "deadline": "2026-08-14", "current_value": "done", "archived": 0,
        }, {
            "id": 7, "kind": "deadline", "name": "Archived", "domain": "business",
            "deadline": "2026-08-14", "current_value": "", "archived": 1,
        }, {
            "id": 8, "kind": "deadline", "name": "Far future", "domain": "business",
            "deadline": "2026-09-14", "current_value": "", "archived": 0,
        }],
        pending_proposals=[{"id": 9, "status": "APPROVED", "created_at": "2026-08-01 09:00:00"}],
        partner_tasks=[{"id": 10, "title": "Done", "done": True}],
    )
    assert attention.collect_candidates(conn, NOW_MORNING, preloaded=preloaded) == []


def test_public_agent_and_push_projections_are_narrow_and_order_preserving(conn):
    private_values = [
        "private@example.com", "6305550100", "secret message", "consent blob", "journal body",
    ]
    preloaded = empty_preloaded(
        active_promises=[{
            "id": 1, "status": "new", "source": "btc", "promised_by": "2026-08-14 10:00:00",
            "email": private_values[0], "phone": private_values[1], "message": private_values[2],
            "consent": private_values[3], "journal": private_values[4],
        }],
        pending_proposals=[{
            "id": 2, "status": "PENDING", "created_at": "2026-08-10 09:00:00",
            "action": "secret proposal action",
        }],
        partner_tasks=[{"id": 3, "title": "private Partner task text", "done": False}],
        gym={"confirmed_today": False},
    )
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    public = attention.public_projection(result)
    chief = attention.agent_projection(result, "chief")
    pushed = attention.push_projection(next(item for item in result.ranked if item.kind == "inbound_promise"))

    assert public["next"] == attention._project(result.ranked[0])
    assert len(public["items"]) <= 3
    assert set(public["next"]) == {
        "key", "kind", "label", "reason", "route", "interaction", "due_at", "urgency"
    }
    assert [item["key"] for item in chief] == [
        item.key for item in result.ranked if "chief" in item.audiences
    ]
    assert not any(item["kind"] in {"inbound_promise", "partner_action"} for item in chief)
    assert pushed == ("ianOS: promise expiring", "A booking confirmation is due by 10:00 AM.")
    assert attention.push_projection(next(item for item in result.ranked if item.kind == "gym")) is None

    serialized = json.dumps({"public": public, "chief": chief, "push": pushed})
    for private in [*private_values, "secret proposal action", "private Partner task text"]:
        # Partner text is intentionally public but may never enter chief/push; test
        # it separately instead of pretending Command cannot show its own task.
        if private == "private Partner task text":
            assert private not in json.dumps({"chief": chief, "push": pushed})
        else:
            assert private not in serialized
    assert not any("evidence" in item for item in [public["next"], *public["items"], *chief])


def test_compilation_performs_zero_writes(conn):
    before = conn.total_changes
    result = attention.compile_attention(conn, NOW_MORNING)
    assert isinstance(result, attention.AttentionResult)
    assert conn.total_changes == before
    assert not conn.in_transaction


def test_large_lead_fixture_is_linear_enough_and_stable(conn):
    queue = [
        {
            "id": index,
            "business_name": f"Lead {index}",
            "stage": "new",
            "tier": "A",
            "queue_reason": "tier A",
        }
        for index in range(1, 1959)
    ]
    preloaded = empty_preloaded(
        lead_queue=queue,
        activity={"audit_calls": 0, "follow_ups": 10},
    )
    first = attention.public_projection(attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded))
    second = attention.public_projection(attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded))
    assert first == second
    assert first["next"]["key"] == "lead:1"


def test_active_promise_read_is_alert_independent_and_privacy_narrow(conn):
    conn.execute(
        """INSERT INTO inbound_requests
           (request_id, kind, source, status, received_at, promised_by, alerted_at,
            email, phone, message, consent)
           VALUES ('r1', 'demo', 'btc', 'new', '2026-08-13T12:00:00Z',
                   '2026-08-14 10:00:00', '2026-08-14 06:00:00',
                   'private@example.com', '6305550100', 'secret', 'consent')"""
    )
    conn.commit()
    rows = db.active_promises(conn)
    assert len(rows) == 1
    assert rows[0]["alerted_at"] is not None
    assert not ({"email", "phone", "message", "consent"} & set(rows[0]))


def test_due_callback_read_ignores_daily_quota(conn):
    conn.execute(
        """INSERT INTO leads
           (phone_norm, business_name, tier, stage, next_touch)
           VALUES ('6305550100', 'Owed Callback', 'A', 'attempted', '2026-08-14')"""
    )
    conn.execute(
        "INSERT INTO activity (date, audit_calls) VALUES ('2026-08-14', ?)",
        (leads.DAILY_QUOTA,),
    )
    conn.commit()
    assert leads.call_queue(conn, "2026-08-14") == []
    assert [row["business_name"] for row in leads.due_callbacks(conn, "2026-08-14")] == [
        "Owed Callback"
    ]


def test_school_item_due_within_48h_is_band_1(conn):
    due_at = NOW_MORNING + timedelta(hours=24)
    preloaded = empty_preloaded(school_items=[{
        "id": 1, "course_code": "BUS 120", "title": "Checkpoint 1",
        "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "kind": "assignment", "done": False,
    }])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    by_key = {item.key: item for item in result.ranked}
    assert by_key["school:1"].band == 1
    assert by_key["school:1"].route == "school"
    assert by_key["school:1"].label == "BUS 120 - Checkpoint 1"


def test_school_item_47h59m_past_due_is_band_0_and_names_the_choice(conn):
    due_at = NOW_MORNING - timedelta(hours=47, minutes=59)
    preloaded = empty_preloaded(school_items=[{
        "id": 2, "course_code": "SPAN 210", "title": "Reading response",
        "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "kind": "assignment", "done": False,
    }])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    by_key = {item.key: item for item in result.ranked}
    assert by_key["school:2"].band == 0
    assert "cross it off" in by_key["school:2"].reason


def test_school_item_48h01m_past_due_is_absent(conn):
    due_at = NOW_MORNING - timedelta(hours=48, minutes=1)
    preloaded = empty_preloaded(school_items=[{
        "id": 3, "course_code": "SPAN 210", "title": "Old reading response",
        "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "kind": "assignment", "done": False,
    }])
    keys = {item.key for item in attention.collect_candidates(conn, NOW_MORNING, preloaded=preloaded)}
    assert "school:3" not in keys


def test_school_item_5_days_out_is_band_2_routine(conn):
    due_at = NOW_MORNING + timedelta(days=5)
    preloaded = empty_preloaded(school_items=[{
        "id": 4, "course_code": "ACCY 200", "title": "Problem set 3",
        "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "kind": "assignment", "done": False,
    }])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    by_key = {item.key: item for item in result.ranked}
    assert by_key["school:4"].band == 2


def _meeting(item_id, start, end, course_code="SPAN 210", kind="lecture", location="Hall 149"):
    return {
        "school_item_id": item_id,
        "calendar_event_id": None,
        "course_code": course_code,
        "course_name": "Data Analytics",
        "kind": kind,
        "title": f"{course_code} {kind}",
        "start_at": start.strftime("%Y-%m-%dT%H:%M"),
        "end_at": end.strftime("%Y-%m-%dT%H:%M"),
        "location": location,
        "existing_session_id": None,
        "closed_at": None,
    }


def test_meeting_starting_in_1h_is_present_band_1(conn):
    start = NOW_MORNING + timedelta(hours=1)
    end = start + timedelta(hours=1)
    preloaded = empty_preloaded(school_meetings=[_meeting(101, start, end)])
    result = attention.compile_attention(conn, NOW_MORNING, preloaded=preloaded)
    by_key = {item.key: item for item in result.ranked}
    assert by_key["schoolmeet:101"].band == 1
    assert by_key["schoolmeet:101"].route == "school"


def test_meeting_starting_in_3h_is_absent(conn):
    start = NOW_MORNING + timedelta(hours=3)
    end = start + timedelta(hours=1)
    preloaded = empty_preloaded(school_meetings=[_meeting(102, start, end)])
    keys = {item.key for item in attention.collect_candidates(conn, NOW_MORNING, preloaded=preloaded)}
    assert "schoolmeet:102" not in keys


def test_meeting_from_yesterday_is_absent(conn):
    start = NOW_MORNING - timedelta(days=1)
    end = start + timedelta(hours=1)
    preloaded = empty_preloaded(school_meetings=[_meeting(103, start, end)])
    keys = {item.key for item in attention.collect_candidates(conn, NOW_MORNING, preloaded=preloaded)}
    assert "schoolmeet:103" not in keys


def test_morning_routine_ranks_call_run_before_school_item():
    rows = [
        candidate("school-1", "school_item", 2),
        candidate("call-1", "call_run", 2),
    ]
    ranked = attention.rank_candidates(rows, NOW_MORNING)
    assert [item.kind for item in ranked] == ["call_run", "school_item"]


def test_evening_routine_ranks_school_item_before_call_run():
    rows = [
        candidate("school-1", "school_item", 2),
        candidate("call-1", "call_run", 2),
    ]
    ranked = attention.rank_candidates(rows, NOW_EVENING)
    assert [item.kind for item in ranked] == ["school_item", "call_run"]
