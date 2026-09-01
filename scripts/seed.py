"""Seed ianOS with multi-domain demo data. Run via `make seed`."""

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db

TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


# name, kind, target, unit, deadline, current, notes, domain, metric_key, hero, priority
GOALS = [
    ("Sign Clockwork client #1 ($199/mo)", "goal", "1", "client", "2026-08-15", "0",
     "School starts ~Aug 24.", "business", "clients_signed", 1, 0),
    ("Monthly burn under cap", "goal", "150", "$/mo", None, "",
     "Business spend from transactions.", "business", "burn_this_month", 0, 1),
    ("Audit calls per day", "quota", "20", "calls/day", "2026-08-09", "",
     "Cold audit calls.", "business", "audit_calls_today", 0, 2),
    ("Follow-ups per day", "quota", "10", "follow-ups/day", "2026-08-09", "",
     "Second-touch outreach.", "business", "follow_ups_today", 0, 3),
    ("Demos held per week", "quota", "3-5", "demos/week", "2026-08-09", "",
     "Live Clockwork demos.", "business", "demos_last_7d", 0, 4),
    ("File Illinois LLC", "deadline", "filed", "", "2026-07-17", "in progress",
     "LLC -> EIN -> A2P chain.", "business", "", 0, 5),
    ("Obtain EIN from IRS", "deadline", "obtained", "", "2026-07-24", "not started",
     "Blocked by LLC.", "business", "", 0, 6),
    ("Twilio A2P 10DLC campaign approved", "deadline", "approved", "", "2026-08-07", "not started",
     "Blocked by EIN.", "business", "", 0, 7),
    ("clockworkcrm.com domain renewal", "deadline", "renewed", "", "2027-03-02", "auto-renew on",
     "Namecheap.", "business", "", 0, 8),
    ("Portfolio net worth", "goal", "15000", "$", None, "",
     "Fidelity via SnapTrade or CSV.", "finance", "portfolio_value", 1, 0),
    ("Checking balance floor", "goal", "1000", "$", None, "",
     "Chase via SimpleFIN.", "finance", "checking_balance", 0, 1),
    ("Sleep 7+ hours/night", "quota", "7", "hours", None, "",
     "Avg over 7 days.", "health", "sleep_avg_7d", 0, 1),
    ("Work out 3x/week", "quota", "3", "sessions/week", None, "",
     "Gym or run.", "health", "workouts_this_week", 0, 1),
    ("Gym every weekday", "quota", "5", "weekdays", None, "",
     "Mon-Fri confirm on Body page.", "health", "gym_weekdays_this_week", 1, 0),
    ("Steps 8k/day", "quota", "8000", "steps", None, "",
     "Apple Health or manual.", "health", "steps_today", 0, 2),
    ("Weekly friend check-in", "quota", "1", "call/week", None, "",
     "Stay connected.", "personal", "", 0, 0),
    ("Renew passport", "deadline", "renewed", "", "2026-12-01", "not started",
     "Low urgency.", "personal", "", 0, 1),
]

PARTNER_TASKS = [
    ("Buy her flowers", ""),
    ("Go to the water park with her", "Water park, plan a day together"),
]

# Anniversary ~20 days out (yearly), so Hitch's tripwire fires on first boot.
_anniv = TODAY + timedelta(days=20)

# facts: (domain, topic, body, kind, date, recurs, verified)
# Personal placeholders are verified=0: the agents' first job is to get Ian to
# confirm or replace them. We invent no real personal data.
FACTS = [
    ("personal", "partner:anniversary",
     "SEEDED PLACEHOLDER. Ian: correct this date. Hitch treats it as unconfirmed.",
     "date", f"2023-{_anniv.month:02d}-{_anniv.day:02d}", "yearly", 0),
    ("personal", "partner:favorite-flowers",
     "SEEDED PLACEHOLDER. Ian: what does she actually like? (unconfirmed)",
     "preference", None, "", 0),
    ("personal", "family:sibling-1-birthday",
     "SEEDED PLACEHOLDER. Uncle Iroh must ask Ian for the real date.",
     "date", "2012-03-14", "yearly", 0),
    ("personal", "family:sibling-2-birthday",
     "SEEDED PLACEHOLDER. Uncle Iroh must ask Ian for the real date.",
     "date", "2014-09-22", "yearly", 0),
    ("personal", "family:sibling-3-birthday",
     "SEEDED PLACEHOLDER. Uncle Iroh must ask Ian for the real date.",
     "date", "2016-11-05", "yearly", 0),
    ("personal", "family:dog-vet-checkup",
     "SEEDED PLACEHOLDER. the dog's next vet checkup (unconfirmed).",
     "date", (TODAY + timedelta(days=45)).isoformat(), "", 0),
    ("college", "uiuc:fall-registration",
     "UNVERIFIED. Dumbledore must ask Ian. Fall course registration window.",
     "date", "2026-07-25", "", 0),
    ("college", "uiuc:fall-move-in",
     "UIUC fall move-in. placeholder date.",
     "date", "2026-08-19", "", 1),
    ("college", "uiuc:fafsa-2027",
     "UNVERIFIED. Dumbledore must ask Ian. FAFSA for the 2027 aid year.",
     "date", "2026-12-01", "", 0),
    ("business", "content:cadence",
     "Floor: 1 meaningful published item per week while school is out.",
     "rule", None, "", 1),
    ("health", "training:mix",
     "Target mix: 2 MMA, 3 lift, 1 soccer per week.",
     "rule", None, "", 1),
]

# content_log: (days_ago, platform, item, url, notes), note the gap in the last week.
CONTENT = [
    (20, "site", "Homepage refresh: new hero + Clockwork blurb", "https://ianmccallum.com", ""),
    (16, "site", "Sample Photography portfolio piece added", "", "client work as proof"),
    (11, "instagram", "Behind-the-scenes reel: audit call setup", "", ""),
    (9, "youtube", "Short: what an HVAC CRM demo looks like", "", "pipeline fuel"),
    # nothing in the last 7 days → Don Draper flags the gap.
]

# workout slug per days_ago; recent 4 days intentionally blank → Rocky's tripwire.
WORKOUT_BY_DAY = {10: "lift", 9: "mma", 8: "soccer", 7: "lift", 6: "mma", 5: "lift"}

TRANSACTIONS = [
    (33, "NAMECHEAP.COM clockworkcrm.com renewal", -12.98, "domain", "chase-checking"),
    (32, "SHELL OIL NAPERVILLE IL", -38.12, "gas", "chase-checking"),
    (30, "ANTHROPIC PBC API credits", -25.00, "ai", "chase-checking"),
    (29, "CHIPOTLE AURORA IL", -11.42, "food", "chase-checking"),
    (27, "GOOGLE WORKSPACE clockwork", -7.20, "saas", "chase-checking"),
    (25, "TWILIO INC autorecharge", -20.00, "telecom", "chase-checking"),
    (24, "APPLE.COM/BILL iCloud+", -2.99, "personal", "chase-checking"),
    (22, "RAILWAY CORP hobby plan", -5.00, "hosting", "chase-checking"),
    (20, "CANVA PRO monthly", -12.99, "saas", "chase-checking"),
    (19, "EBAY PAYOUT - RTX 3060 sale", 220.00, "income", "chase-checking"),
    (17, "FIVERR - clockwork logo design", -45.00, "marketing", "chase-checking"),
    (14, "TWILIO INC autorecharge", -20.00, "telecom", "chase-checking"),
    (14, "TWILIO INC autorecharge", -20.00, "telecom", "chase-checking"),
    (12, "SHELL OIL NAPERVILLE IL", -41.55, "gas", "chase-checking"),
    (9, "FEDEX OFFICE - audit flyer prints x100", -23.40, "marketing", "chase-checking"),
    (8, "RAILWAY CORP hobby plan", -5.00, "hosting", "chase-checking"),
    (6, "ANTHROPIC PBC API credits", -25.00, "ai", "chase-checking"),
    (3, "TWILIO INC autorecharge", -20.00, "telecom", "chase-checking"),
]

HOLDINGS = [
    ("AAPL", "Apple Inc", 12, 1800.0, 2280.0),
    ("VTI", "Vanguard Total Stock Market ETF", 8, 1600.0, 1840.0),
    ("MSFT", "Microsoft Corp", 5, 1500.0, 2100.0),
    ("Cash", "Money Market", 1, 1200.0, 1200.0),
]

HEALTH = [
    (10, 6.5, 7200, 1, 4), (9, 7.0, 8100, 0, 3), (8, 7.5, 9200, 1, 4),
    (7, 6.0, 6500, 1, 3), (6, 8.0, 11000, 0, 5), (5, 9.0, 4000, 0, 5),
    (4, 6.5, 7800, 1, 4), (3, 5.5, 5200, 0, 2), (2, 7.0, 8500, 1, 4),
    (1, 6.8, 7600, 0, 3),
]

CALENDAR = [
    (3, "09:00", "Riverbend demo call", "work", 60),
    (3, "14:00", "Audit calls block", "work", 120),
    (2, "07:00", "Gym", "health", 45),
    (2, "10:00", "Clockwork dev", "work", 180),
    (1, "18:00", "Dinner with family", "personal", 90),
]

ACTIVITY = [
    (10, 21, 10, 1, 6, "Demo w/ Hillcrest Heating."),
    (9, 18, 12, 0, 4, ""), (8, 22, 9, 1, 7, "Riverbend interested."),
    (7, 20, 11, 1, 5, ""), (6, 4, 2, 0, 1, "July 4th."),
    (5, 0, 0, 0, 0, "Day off."), (4, 8, 3, 0, 2, "A2P paperwork."),
    (3, 11, 6, 1, 3, "Riverbend. BEST demo."), (2, 5, 4, 0, 1, "Bad trade: building."),
    (1, 9, 5, 0, 2, "Riverbend callback."),
]

MEMOS = [
    ("scout", "funnel state", "Last 7d: 37 calls, 20 FU, 1 demo. Riverbend hottest lead."),
    ("cfo", "money state", "Burn {THIS_BURN} this month. Portfolio $7,420. Checking $2,341."),
    ("physician", "sleep debt", "Sleep avg 6.4h, below 7h quota. Correlates with post-July-4 call slump."),
    ("steward", "time audit", "42h work, 3h health, 8h personal last 7d. Friend check-in overdue."),
    ("watchdog", "deadline chain", "LLC due soon, still in progress. Chain gates Aug 15."),
    ("ian", "decision: proposal #1", "Proposal #1 cfo Cancel Canva → APPROVED."),
]

PROPOSALS = [
    ("cfo", "Cancel Canva Pro ($12.99/mo)", "Logo done. No use case.", "money", "APPROVED"),
    ("cfo", "Dispute duplicate Twilio $20 charge", "Two identical charges same day.", "money", "PENDING"),
    ("scout", "Block 9-11am daily for calls only", "Call volume collapsed post-July-4.", "task", "PENDING"),
    ("physician", "Sleep by 11pm: no screens after 10:30", "Sleep avg 6.4h dragging sales pace.", "health", "PENDING"),
]

BRIEF = """# Daily Brief: {YESTERDAY}

**Headline: Client #1 deadline approaching: funnel starving, sleep debt making it worse.**

## Day Command
`Riverbend pricing at 9am, file LLC before lunch, gym at 5, asleep by 11.`

## Focus
Business + Health this week: client deadline and sleep recovery.

## BUSINESS
- **Client #1**. OFF TRACK. 0/1 signed. Riverbend hot.
- **Burn**. AT RISK. ${THIS_BURN}/$150 this month.
- **Quotas**. OFF TRACK. Calls at 26% since July 4.
- **LLC chain**. AT RISK. Filing still in progress.

## FINANCE
- **Portfolio**. ON TRACK. $7,420 across 4 positions.
- **Checking**. ON TRACK. $2,341 (seed data, connect SimpleFIN for live).

## HEALTH
- **Sleep 7+h**. OFF TRACK. 6.4h avg last 7d.
- **Workouts 3x/wk**. AT RISK. 2 sessions last 7d.

## PERSONAL
- **Friend check-in**. NO DATA. No log this week.

## Tradeoffs
Sleep avg 6.4h + calls at 26% of quota, cross-domain drag. Fix sleep or accept missed quota.

## Top 3 moves for tomorrow
1. Riverbend pricing call at 9am.
2. File Illinois LLC before noon.
3. 20 audit calls before any code.

## Pending proposals
- #2 cfo: Dispute duplicate Twilio charge.
- #3 scout: Block 9-11am for calls.
- #4 physician: Sleep by 11pm rule.
"""


def main() -> None:
    conn = db.connect()
    cur = conn.cursor()
    tables = (
        "transactions", "memos", "proposals", "briefs", "goals", "activity",
        "health_daily", "calendar_events", "holdings", "focus_allocations",
        "ingest_log", "documents", "partner_tasks", "facts", "content_log",
    )
    for table in tables:
        if cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            cur.execute(f"DELETE FROM {table}")
            cur.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))

    for i, (days_ago, desc, amount, cat, acct) in enumerate(TRANSACTIONS):
        tx_date = d(days_ago)
        h = hashlib.sha256(f"{tx_date}|{desc}|{amount}|{acct}|{i}".encode()).hexdigest()[:16]
        cur.execute(
            "INSERT INTO transactions (date,description,amount,category,account,hash,source) VALUES (?,?,?,?,?,?,?)",
            (tx_date, desc, amount, cat, acct, h, "csv"),
        )

    for row in GOALS:
        cur.execute(
            """INSERT INTO goals (name,kind,target,unit,deadline,current_value,notes,
               domain,metric_key,hero,priority) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            row,
        )

    cur.execute("SELECT id, name FROM goals")
    by_name = {name: gid for gid, name in cur.fetchall()}
    llc = by_name.get("File Illinois LLC")
    ein = by_name.get("Obtain EIN from IRS")
    a2p = by_name.get("Twilio A2P 10DLC campaign approved")
    if llc and ein:
        cur.execute("UPDATE goals SET depends_on_goal_id=? WHERE id=?", (llc, ein))
    if ein and a2p:
        cur.execute("UPDATE goals SET depends_on_goal_id=? WHERE id=?", (ein, a2p))

    for days_ago, calls, fu, demos, convs, notes in ACTIVITY:
        cur.execute(
            "INSERT INTO activity (date,audit_calls,follow_ups,demos,conversations,notes) VALUES (?,?,?,?,?,?)",
            (d(days_ago), calls, fu, demos, convs, notes),
        )

    for days_ago, sleep, steps, wo, energy in HEALTH:
        workout = WORKOUT_BY_DAY.get(days_ago, "")
        workouts = 1 if workout else 0
        cur.execute(
            "INSERT INTO health_daily (date,sleep_hours,steps,workouts,workout,energy,source) VALUES (?,?,?,?,?,?,?)",
            (d(days_ago), sleep, steps, workouts, workout, energy, "seed"),
        )

    for days_ago, start, summary, cat, dur in CALENDAR:
        h = hashlib.sha256(f"{d(days_ago)}|{start}|{summary}".encode()).hexdigest()[:16]
        cur.execute(
            "INSERT INTO calendar_events (date,start_time,summary,category,duration_min,hash) VALUES (?,?,?,?,?,?)",
            (d(days_ago), start, summary, cat, dur, h),
        )

    as_of = d(0)
    for sym, desc, qty, cost, mv in HOLDINGS:
        h = hashlib.sha256(f"seed|{sym}|{as_of}".encode()).hexdigest()[:16]
        cur.execute(
            """INSERT INTO holdings (account,symbol,description,quantity,cost_basis,
               market_value,as_of_date,source,hash) VALUES (?,?,?,?,?,?,?,?,?)""",
            ("fidelity", sym, desc, qty, cost, mv, as_of, "seed", h),
        )

    months = {m["month"]: m["burn"] for m in db.burn_by_month(conn, 3)}
    this_month = TODAY.isoformat()[:7]
    fills = {"THIS_BURN": f"{months.get(this_month, 0):.2f}"}

    for i, (role, topic, body) in enumerate(MEMOS):
        for k, v in fills.items():
            body = body.replace("{" + k + "}", v)
        cur.execute(
            "INSERT INTO memos (from_role,topic,body,created_at) VALUES (?,?,?,?)",
            (role, topic, body, f"{d(1)} 21:3{i}:00"),
        )

    for role, action, reasoning, kind, status in PROPOSALS:
        decided = f"{d(1)} 21:45:00" if status != "PENDING" else None
        cur.execute(
            "INSERT INTO proposals (role,action,reasoning,kind,status,created_at,decided_at) VALUES (?,?,?,?,?,?,?)",
            (role, action, reasoning, kind, status, f"{d(1)} 21:35:00", decided),
        )

    brief_body = BRIEF.replace("{YESTERDAY}", d(1))
    for k, v in fills.items():
        brief_body = brief_body.replace("{" + k + "}", v)
    cur.execute(
        "INSERT INTO briefs (date,kind,body,day_command,created_at) VALUES (?,?,?,?,?)",
        (d(1), "daily", brief_body,
         "Riverbend pricing at 9am, file LLC before lunch, gym at 5, asleep by 11.",
         f"{d(1)} 21:40:00"),
    )

    week = db.sunday_of()
    cur.execute(
        "INSERT INTO focus_allocations (week_start,domains,goal_ids,rationale) VALUES (?,?,?,?)",
        (week, json.dumps(["business", "health"]), json.dumps([]),
         "Client #1 deadline + sleep debt recovery."),
    )

    db.update_ingest_log(conn, "snaptrade_fidelity", 4, json.dumps({"total": 7420}))
    db.update_ingest_log(conn, "simplefin_chase", 0, json.dumps({"balance": 2341.18, "as_of": d(0)}))
    db.update_ingest_log(conn, "apple_health", 10, "seed")
    db.update_ingest_log(conn, "calendar", 5, "seed")

    infra = Path(__file__).resolve().parent.parent / "data" / "infra_status.json"
    infra.parent.mkdir(exist_ok=True)
    infra.write_text(json.dumps({
        "railway": {"status": "up", "monthly_cost": 5.0, "last_deploy": d(2)},
        "clockworkcrm.com": {"status": "up", "ssl_expires": "2027-03-02"},
        "updated_at": d(0),
    }, indent=2))

    for title, notes in PARTNER_TASKS:
        cur.execute(
            "INSERT INTO partner_tasks (title, notes) VALUES (?, ?)",
            (title, notes),
        )

    for domain, topic, body, kind, fdate, recurs, verified in FACTS:
        cur.execute(
            """INSERT INTO facts (domain,topic,body,kind,date,recurs,source_role,verified)
               VALUES (?,?,?,?,?,?,?,?)""",
            (domain, topic, body, kind, fdate, recurs, "seed", verified),
        )

    for days_ago, platform, item, url, notes in CONTENT:
        cur.execute(
            "INSERT INTO content_log (date,platform,item,url,notes) VALUES (?,?,?,?,?)",
            (d(days_ago), platform, item, url, notes),
        )

    conn.commit()
    print(f"Seeded {db.DB_PATH}. 15-agent life OS ready ({len(FACTS)} facts, "
          f"{len(CONTENT)} content items). Run: make dev")


if __name__ == "__main__":
    main()
