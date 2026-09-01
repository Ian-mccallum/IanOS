"""Pure lead-pipeline derivations for ianOS (SPEC-v9, "The Line").

No network, no LLM, no model call anywhere in this module. The queue ordering
and the call script are deterministic functions of table rows, same posture as
``should_run()`` in the dispatcher and ``suggest_blocks()`` in core/plan.py.

Design law encoded here (see SPEC-v9): momentum (`heat`) is earned by DIALING,
never by the outcome of a dial. A no-answer advances a run exactly as much as a
booked demo. Ian controls whether he picks up the phone; he does not control
whether they answer. tests/test_leads.py asserts this.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from core import db
from core.pillars import MOVE_IN_DATE

# Ian's selling time collapses when school starts (~Aug 24, 2026). Used only for
# agent-facing runway math, never rendered to Ian as a countdown.
SCHOOL_START = "2026-08-24"

DAILY_QUOTA = 20          # audit calls/day, matches the 'Audit calls per day' quota goal
MAX_ATTEMPTS = 4          # after this many unanswered attempts a lead rests for good
REST_LADDER = (3, 5, 8)   # days a lead rests after 1st, 2nd, 3rd unanswered attempt
HEAT_MAX = 5
HEAT_IDLE_MINUTES = 4     # heat cools one step per this many idle minutes, silently

RUN_TARGETS = (5, 10, 20)  # 5 exists because on a bad day 5 is the whole win

# Outcomes that mean "nobody picked up", they advance attempts and start a rest.
_MISSED = ("no_answer", "voicemail", "gatekeeper")


# ------------------------------------------------------------------ phones

def norm_phone(raw: str | None) -> str:
    """US 10-digit key, or '' when the number is unusable.

    Extensions ('(773) 555-7600 ext. 1542') collapse to the base number: the
    digits after 'ext' are dropped before length checking.
    """
    if not raw:
        return ""
    text = re.split(r"(?i)\b(?:ext|x|extension)\b\.?", str(raw))[0]
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else ""


def pretty_phone(phone_norm: str) -> str:
    if len(phone_norm) != 10:
        return phone_norm
    return f"({phone_norm[:3]}) {phone_norm[3:6]}-{phone_norm[6:]}"


# ------------------------------------------------------------------- dates

def _to_date(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _to_dt(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def weekdays_between(start: str, end: str) -> int:
    a, b = _to_date(start), _to_date(end)
    if not a or not b or b <= a:
        return 0
    return sum(1 for i in range((b - a).days) if (a + timedelta(days=i)).weekday() < 5)


# ------------------------------------------------------------ market + rest

def market_priority(today: str | None = None, move_in: str = MOVE_IN_DATE) -> tuple[str, str]:
    """Before move-in Ian is in the Naperville-Aurora corridor, so north leads
    are the ones he can drive to. On and after move-in he is in Champaign and
    the southern list becomes the reachable one."""
    today = today or db.today()
    return ("south", "north") if today >= move_in else ("north", "south")


def rest_days(attempts: int) -> int:
    """A lead rests longer after each unanswered attempt. It never 'rots', the
    rest is silent and is never surfaced to Ian as lateness."""
    if attempts <= 0:
        return 0
    idx = min(attempts, len(REST_LADDER)) - 1
    return REST_LADDER[idx]


def is_resting(lead: dict, today: str | None = None) -> bool:
    today = today or db.today()
    nxt = lead.get("next_touch")
    if nxt and str(nxt) > today:
        return True
    last = _to_date(lead.get("last_touch"))
    if not last:
        return False
    due = last + timedelta(days=rest_days(int(lead.get("attempts") or 0)))
    return due > (_to_date(today) or date.today())


# ------------------------------------------------------------- transitions

def next_stage(stage: str, outcome: str, attempts: int = 0) -> str:
    """Deterministic transition table (SPEC-v9 §3)."""
    if outcome in _MISSED:
        return "parked" if attempts + 1 >= MAX_ATTEMPTS else "attempted"
    if outcome == "reached":
        return "reached"
    if outcome == "booked":
        return "demo"
    if outcome == "not_interested":
        return "lost"
    if outcome == "bad_number":
        return "parked"
    return stage or "new"


def activity_bumps(kind: str, outcome: str) -> dict[str, int]:
    """How one touch feeds the existing `activity` counters. This mapping is why
    no goal or metric in the repo had to change, audit_calls_today,
    follow_ups_today and demos_last_7d keep resolving, now off real events."""
    bumps: dict[str, int] = {}
    if outcome == "bad_number":
        return bumps                      # a dead number is not a call
    if kind == "follow_up":
        bumps["follow_ups"] = 1
    elif kind in ("call", "demo"):
        bumps["audit_calls"] = 1
    if outcome == "reached":
        bumps["conversations"] = 1
    elif outcome == "booked":
        bumps["demos"] = 1
        bumps["conversations"] = 1
    return bumps


# ----------------------------------------------------------------- the queue

def remaining_quota(conn, today: str | None = None) -> int:
    today = today or db.today()
    row = conn.execute("SELECT audit_calls FROM activity WHERE date = ?", (today,)).fetchone()
    done = (row["audit_calls"] if row else 0) or 0
    return max(0, DAILY_QUOTA - done)


def queue_reason(lead: dict, today: str | None = None) -> str:
    today = today or db.today()
    nxt = lead.get("next_touch")
    if nxt and str(nxt) <= today:
        return "promised callback"
    if lead.get("stage") == "reached":
        return "spoke before: no demo yet"
    if lead.get("stage") == "attempted":
        return f"attempt {int(lead.get('attempts') or 0) + 1}"
    tier = lead.get("tier")
    if tier == "A":
        return "tier A · proof of pain" if lead.get("miss_signal") else "tier A"
    if tier == "B":
        return "tier B · high value"
    return "tier C"


def call_queue(conn, today: str | None = None, limit: int | None = None) -> list[dict]:
    """THE ordering function. Tier D and parked leads never appear, at any limit.

    Bands (SPEC-v9 §3): 0 promised callbacks, 1 warm, 2 tier A, 3 tier B,
    4 second pass, 5 tier C.
    """
    today = today or db.today()
    rows = db.rows_to_dicts(conn.execute(
        "SELECT * FROM leads WHERE stage NOT IN ('won','lost','parked') AND tier != 'D'"
    ).fetchall())

    order = market_priority(today)

    def mrank(lead: dict) -> int:
        m = lead.get("market") or ""
        return order.index(m) if m in order else len(order)

    bands: dict[int, list[dict]] = {i: [] for i in range(6)}
    for lead in rows:
        nxt = lead.get("next_touch")
        if nxt and str(nxt) <= today:
            bands[0].append(lead)
            continue
        stage = lead.get("stage") or "new"
        if stage == "demo":
            continue                       # booked; only a due callback resurfaces it
        if stage == "reached":
            if not is_resting(lead, today):
                bands[1].append(lead)
            continue
        if stage == "new":
            tier = lead.get("tier")
            bands[2 if tier == "A" else 3 if tier == "B" else 5].append(lead)
            continue
        if stage == "attempted":
            if int(lead.get("attempts") or 0) < MAX_ATTEMPTS and not is_resting(lead, today):
                bands[4].append(lead)

    neg_total = lambda l: -int(l.get("total") or 0)  # noqa: E731
    bands[0].sort(key=lambda l: (str(l.get("next_touch") or ""), neg_total(l)))
    bands[1].sort(key=lambda l: (str(l.get("last_touch") or ""), neg_total(l)))
    bands[2].sort(key=neg_total)
    bands[3].sort(key=lambda l: (mrank(l), neg_total(l)))
    bands[4].sort(key=neg_total)
    bands[5].sort(key=lambda l: (mrank(l), neg_total(l)))

    out: list[dict] = []
    for b in range(6):
        for lead in bands[b]:
            lead["band"] = b
            lead["queue_reason"] = queue_reason(lead, today)
            lead["call_card"] = call_card(lead)
            out.append(lead)

    if limit is None:
        limit = remaining_quota(conn, today)
    return out[:max(0, int(limit))]


def due_callbacks(conn, today: str | None = None) -> list[dict]:
    """Return every actionable callback due by ``today``, quota-independent.

    ``call_queue`` intentionally caps a routine run at the remaining daily
    quota. A promised callback is a commitment, so consumers such as the
    attention compiler need a separate read path that cannot disappear when
    that routine quota reaches zero. Only fields needed to identify and
    explain the callback cross this boundary; contact details stay in the
    dedicated lead view.
    """
    today = today or db.today()
    rows = db.rows_to_dicts(conn.execute(
        """SELECT id, business_name, city, tier, total, stage, next_touch
           FROM leads
           WHERE next_touch IS NOT NULL AND next_touch <= ?
             AND stage NOT IN ('won','lost','parked') AND tier != 'D'
           ORDER BY next_touch, total DESC, id""",
        (today,),
    ).fetchall())
    for lead in rows:
        lead["queue_reason"] = queue_reason(lead, today)
    return rows


# ------------------------------------------------------------- the script

# Phrases the scraper swept reviews for. Used to find the ONE sentence worth
# quoting back, the raw Miss Signal is a ~200-char mid-sentence fragment that
# is unreadable aloud, and this hook has to be spoken on a live call.
_MISS_PHRASES = (
    "never called back", "never heard back", "no call back", "no callback",
    "didn't call back", "did not call back", "never returned", "never answered",
    "no response", "no answer", "unanswered", "unresponsive",
    "won't answer", "doesn't answer",
)


def _clean_quote(raw: str, max_len: int = 110) -> str:
    """Pull the readable sentence out of a Miss Signal review snippet.

    Miss Signal arrives fenced with '...' and clipped mid-WORD at BOTH ends, so
    quoting it verbatim hands Ian something he cannot say out loud on a live
    call. Locate the complaint phrase, snap to the sentence around it, and trim
    the scraper's partial word off whichever end we failed to snap.
    """
    original = str(raw or "").strip()
    clipped_start = original.startswith("...") or original.startswith("…")
    clipped_end = original.endswith("...") or original.endswith("…")
    text = re.sub(r"\s+", " ", original.strip(".…").strip())
    if not text:
        return ""

    low = text.lower()
    snapped = False          # found a sentence break BEFORE the phrase
    ended_clean = False      # found a sentence terminator AFTER it
    has_text_before = False
    frag = text
    for phrase in _MISS_PHRASES:
        i = low.find(phrase)
        if i == -1:
            continue
        starts = [text.rfind(p, 0, i) for p in ".!?"]
        start = max(starts) + 1 if max(starts) >= 0 else 0
        snapped = start > 0
        has_text_before = i > 0
        after = i + len(phrase)
        ends = [x for x in (text.find(p, after) for p in ".!?") if x != -1]
        ended_clean = bool(ends)
        end = min(ends) + 1 if ends else len(text)
        frag = text[start:end].strip(" ,;-")
        break

    # No sentence break before the phrase, so the fragment still opens with
    # whatever half-word the scraper cut ("Nd secured…"). Only drop it when
    # there was genuinely text before the phrase, otherwise the first word IS
    # the complaint ("never called back") and dropping it inverts the meaning.
    if clipped_start and not snapped and has_text_before and " " in frag:
        frag = frag.split(" ", 1)[1].strip(" ,;-")

    # Same problem at the tail: with no sentence terminator after the phrase we
    # inherit the scraper's mid-WORD cut ("...they over look everything, every
    # com"). Drop the stub, then any dangling connector, and trail off instead.
    if clipped_end and not ended_clean and " " in frag:
        frag = _trim_dangling_tail(frag)

    if len(frag) > max_len:
        # we cut at a space, so the final word is whole, only danglers to drop
        frag = _trim_dangling_tail(frag[:max_len].rsplit(" ", 1)[0], drop_stub=False)
    frag = frag.rstrip(".")            # the hook adds its own sentence break
    return frag[:1].upper() + frag[1:] if frag else ""


# Words a quote must not trail off on, they leave the sentence hanging open.
_DANGLING = {
    "and", "or", "but", "the", "a", "an", "to", "of", "with", "that", "for",
    "in", "on", "at", "my", "our", "their", "his", "her", "its", "is", "was",
    "were", "am", "are", "be", "been", "i", "we", "they", "he", "she", "it",
    "you", "every", "no", "not", "so", "as", "if", "when", "then", "this",
    "these", "those", "from", "by", "about", "into", "up", "out", "over",
    "after", "before", "because", "while", "which", "who", "had", "has",
    "have", "would", "could", "should", "did", "does", "do", "just", "very",
}


# Short words that can legitimately END a quote, so we don't mistake them for
# the scraper's mid-word cut.
_SHORT_ENDERS = {
    "me", "us", "it", "him", "her", "all", "out", "off", "up", "now", "yet",
    "too", "one", "two", "end", "job", "day", "way", "far", "ago", "new",
    "old", "own", "got", "few", "bad", "man", "guy", "car", "pay", "ask",
    "saw", "fix", "let", "see", "try", "use", "run", "won", "hot", "ac",
}


def _trim_dangling_tail(frag: str, drop_stub: bool = True) -> str:
    """Trim a quote so it ends somewhere a person can stop speaking.

    Whether the scraper cut mid-word is genuinely unknowable from the text, so
    `drop_stub` uses a length heuristic: in the real data every truncation stub
    is 1-3 characters ("every com", "receiving n", "reviews giv") while every
    legitimate ending is longer ("called back", "from them"). Set it False when
    we did the cutting ourselves and know the last word is whole.
    """
    words = frag.rstrip(" ,;-…").split()
    if not words:
        return frag
    last = words[-1].strip(",;:.").lower()
    if drop_stub and len(words) > 1 and len(last) <= 3 and last not in _SHORT_ENDERS:
        words.pop()
    while len(words) > 1 and words[-1].strip(",;:.").lower() in _DANGLING:
        words.pop()
    out = " ".join(words).rstrip(" ,;-")
    return f"{out}…" if out else frag


_OBJECTIONS = {
    "trades": [
        ("“we're fine”", "What happens to the call that comes in while you're under a sink?"),
        ("“send me an email”", "What address? I'll send it before we hang up."),
        ("“not the owner”", "No problem: when's {owner} usually in?"),
    ],
    "property": [
        ("“we're fine”", "Who picks up when a tenant's heat goes out at 9pm?"),
        ("“send me an email”", "What address? I'll send it before we hang up."),
        ("“not the owner”", "When's the best time to catch {owner}?"),
    ],
    "emergency": [
        ("“we're fine”", "You advertise 24/7, what happens to the 2am call?"),
        ("“send me an email”", "What address? I'll send it before we hang up."),
        ("“not the owner”", "When's {owner} around?"),
    ],
}


# Words that make a review quote unsafe to read back to the owner. A missed
# call is a problem you fix; "rude", "harassing" or a legal complaint is an
# accusation, and reading it aloud ends the call. Legal terms are worse still.
_UNQUOTABLE = (
    "rude", "harass", "scam", "fraud", "steal", "stole", "thief", "liar",
    "lied", "lawsuit", "sue ", "sued", "attorney", "legal department", "lawyer",
    "court", "bbb complaint", "racist", "threat", "abusive", "incompetent",
    "worst", "disgusting", "nightmare",
)

# The scraper's sweep also catches reviews where the CUSTOMER admits they were
# the unreachable one ("I was unresponsive to calls from the office"). Quoting
# that as evidence the business misses calls is simply false.
_SELF_REFERENTIAL = re.compile(
    r"\b(i|we) (was|were|am|are|had been) (un)?(responsive|reachable|available)"
    r"|\bmy fault\b|\bi never (called|answered|responded)", re.IGNORECASE)


def quote_is_readable(quote: str) -> bool:
    """Is this review safe to read back to the owner on a live call?

    Ian says these words out loud to a stranger. A false or hostile quote costs
    him the call and the relationship, so when in doubt we drop to a softer
    hook rather than risk it.
    """
    if not quote:
        return False
    low = quote.lower()
    if any(w in low for w in _UNQUOTABLE):
        return False
    return not _SELF_REFERENTIAL.search(quote)


def call_card(lead: dict) -> dict:
    """Compose the opener from the enrichment. Deterministic templating: never
    a model call. A model here would cost money per dial and add latency at the
    exact second Ian needs none, and enrich_prospects.py already did the
    reasoning (the `why` column).

    Always returns a usable card; never None, even for a bare row.
    """
    owner = (lead.get("owner_name") or "").strip()
    ask_for = owner or "whoever handles the phones"
    city = (lead.get("city") or "").strip()
    raw_quote = _clean_quote(lead.get("miss_signal"))
    # A quote Ian cannot safely say out loud is worse than no quote, the hook
    # falls through to the next-strongest evidence instead.
    quote = raw_quote if quote_is_readable(raw_quote) else ""
    claims = bool(lead.get("claims_247"))
    site = (lead.get("site_status") or "").strip().lower()
    rating = lead.get("rating")
    reviews = int(lead.get("reviews") or 0)

    where = f" here in {city}" if city else ""
    who = f"is {owner} around?" if owner else "who handles your phones?"
    opener = f"Hi, {who} I'm Ian, I'm local{where}."

    # Hook priority: strongest available evidence wins (SPEC-v9 §6).
    if quote and claims:
        hook = (f"You advertise 24/7, and a review says “{quote}”. "
                f"That's the thing I fix.")
        hook_kind = "promise_vs_proof"
    elif quote:
        hook = f"One of your reviews says “{quote}”. That's the thing I fix."
        hook_kind = "proof"
    elif claims:
        hook = "You promise 24/7, who actually picks up at 9pm on a Saturday?"
        hook_kind = "promise"
    elif site in ("none", "failed"):
        hook = ("You don't have a site up, so every lead you get is a phone call. "
                "What happens to the ones you miss?")
        hook_kind = "phone_only"
    elif rating is not None and rating < 4.3 and reviews >= 30:
        hook = (f"You're at {rating} across {reviews} reviews, usually that's "
                f"response time, not the work.")
        hook_kind = "rating"
    else:
        hook = "You're the size where one missed call is a real week."
        hook_kind = "size"

    segment = (lead.get("segment") or "trades").strip().lower()
    template = _OBJECTIONS.get(segment, _OBJECTIONS["trades"])
    objections = [{"trigger": t, "reply": r.format(owner=owner or "the owner")}
                  for t, r in template]

    return {
        "ask_for": ask_for,
        "open": opener,
        "hook": hook,
        "hook_kind": hook_kind,
        "ask": "Can I send you a two-minute audit of what your phone missed last week?",
        "evidence": quote,
        "objections": objections,
        "why": (lead.get("why") or "").strip(),
    }


# --------------------------------------------------------------- the run

def heat(touches: list[dict], now: datetime | None = None) -> int:
    """Run momentum, 0..HEAT_MAX.

    Counts EVERY touch in the run regardless of outcome, this is the load-
    bearing design law, not an oversight. Decays one step per HEAT_IDLE_MINUTES
    of silence; cooling is neutral and is never announced.
    """
    if not touches:
        return 0
    now = now or datetime.now()
    base = min(len(touches), HEAT_MAX)
    last = _to_dt(touches[-1].get("created_at"))
    if last is None:
        return base
    idle_min = max(0.0, (now - last).total_seconds() / 60)
    return max(0, base - int(idle_min // HEAT_IDLE_MINUTES))


def run_state(conn, run_id: int | None, today: str | None = None,
              now: datetime | None = None) -> dict | None:
    today = today or db.today()
    if not run_id:
        return None
    run = conn.execute("SELECT * FROM call_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        return None
    run = dict(run)
    touches = db.touches_for_run(conn, run_id)
    dialed = len(touches)
    outcomes = [t.get("outcome") for t in touches]
    return {
        **run,
        "dialed": dialed,
        "conversations": sum(1 for o in outcomes if o in ("reached", "booked")),
        "booked": sum(1 for o in outcomes if o == "booked"),
        "heat": heat(touches, now=now),
        "complete": dialed >= int(run.get("target") or 0),
        "remaining": max(0, int(run.get("target") or 0) - dialed),
    }


def run_summary(conn, run_id: int) -> dict:
    """Numbers only, no percentage, no comparison to yesterday (SPEC-v9 §7)."""
    touches = db.touches_for_run(conn, run_id)
    booked_ids = [t["lead_id"] for t in touches if t.get("outcome") == "booked"]
    callbacks = db.rows_to_dicts(conn.execute(
        "SELECT business_name, next_touch FROM leads WHERE next_touch IS NOT NULL "
        "AND next_touch >= date('now','localtime') ORDER BY next_touch LIMIT 3"
    ).fetchall())
    names = []
    for lid in booked_ids:
        lead = db.lead_by_id(conn, lid)
        if lead:
            names.append(lead["business_name"])
    return {
        "dialed": len(touches),
        "conversations": sum(1 for t in touches if t.get("outcome") in ("reached", "booked")),
        "booked": len(booked_ids),
        "booked_names": names,
        "callbacks": callbacks,
    }


def milestones(conn, run_id: int, lead: dict, outcome: str, today: str | None = None) -> list[str]:
    """Rare and earned. Drives one aurora bloom, never a stream of them."""
    today = today or db.today()
    out: list[str] = []
    state = run_state(conn, run_id, today)
    if state and state["dialed"] == int(state.get("target") or 0):
        out.append("run_complete")
    if outcome == "booked":
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM lead_touches WHERE date=? AND outcome='booked'", (today,)
        ).fetchone()
        if (row["n"] or 0) <= 1:
            out.append("first_demo_today")
    if (lead or {}).get("tier") == "A":
        out.append("tier_a_worked")
        left = conn.execute(
            "SELECT COUNT(*) AS n FROM leads WHERE tier='A' AND stage='new'"
        ).fetchone()
        if (left["n"] or 0) == 0:
            out.append("tier_a_cleared")
    return out


# ------------------------------------------------------- agent-facing stats

def runway(conn, today: str | None = None) -> dict:
    """Agent-facing only. Never rendered to Ian as a countdown (SPEC-v9 laws)."""
    today = today or db.today()
    wd = weekdays_between(today, SCHOOL_START)
    callable_left = conn.execute(
        "SELECT COUNT(*) AS n FROM leads WHERE stage NOT IN ('won','lost','parked') AND tier != 'D'"
    ).fetchone()["n"]
    reach = wd * DAILY_QUOTA
    pct = f"{round(reach / callable_left * 100)}%" if callable_left else "n/a"
    return {
        "weekdays_to_school": wd,
        "callable_remaining": callable_left,
        "reachable_at_quota": reach,
        "coverage_at_quota": pct,
    }


def pipeline_stats(conn, today: str | None = None) -> dict:
    today = today or db.today()
    due = conn.execute(
        "SELECT COUNT(*) AS n FROM leads WHERE next_touch = ? "
        "AND stage NOT IN ('won','lost','parked')", (today,)
    ).fetchone()["n"]
    overdue = conn.execute(
        "SELECT COUNT(*) AS n FROM leads WHERE next_touch < ? "
        "AND stage NOT IN ('won','lost','parked')", (today,)
    ).fetchone()["n"]
    recent = db.touches_since(conn, 7)
    reached = sum(1 for t in recent if t.get("outcome") in ("reached", "booked"))
    runs = conn.execute(
        "SELECT COUNT(*) AS n FROM call_runs WHERE date >= date('now','localtime','-7 days')"
    ).fetchone()["n"]
    return {
        "tier_counts": db.lead_counts_by(conn, "tier"),
        "stage_counts": db.lead_counts_by(conn, "stage"),
        "callbacks_due_today": due,
        "callbacks_overdue": overdue,
        "runs_last_7d": runs,
        "dials_last_7d": len(recent),
        "reached_rate_7d": f"{reached}/{len(recent)}",
        "runway": runway(conn, today),
        "next_5": [
            {"business_name": l["business_name"], "city": l["city"], "tier": l["tier"],
             "phone": l["phone"], "why": l["why"], "reason": l["queue_reason"]}
            for l in call_queue(conn, today, limit=5)
        ],
    }


# ------------------------------------------------------- back-test (Phase E)
# Did the enricher's model actually predict who answers and who books?
#
# This REPORTS. It never rewrites a tier or a score, scoring belongs to
# leads/enrich_prospects.py (SPEC-v9 non-goals). The output is evidence Ian
# feeds back into that scorer by hand.
#
# It is also deliberately not a dashboard: "no conversion analytics for Ian, if
# it can't change the next call it isn't on the page." This changes the MODEL,
# not the next call, so it lives in the terminal.

MIN_BACKTEST_DIALS = 30    # below this, report nothing but the count
TRUSTWORTHY_DIALS = 100    # below this, everything is labelled preliminary
MIN_GROUP = 15             # a band thinner than this is shown but never ranked

REACHED_OUTCOMES = ("reached", "booked")


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 3) if d else None


def _band(value: int, edges: tuple[int, ...]) -> str:
    """Label a score into a band, e.g. 0 / 1-3 / 4+."""
    lo = None
    for e in edges:
        if value < e:
            return f"{lo}-{e - 1}" if lo is not None and e - 1 > lo else f"{lo if lo is not None else 0}"
        lo = e
    return f"{edges[-1]}+"


def _group_stats(rows: list[dict], key) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(str(key(r)), []).append(r)
    out = []
    for name, rs in groups.items():
        dialed = len(rs)
        contacted = sum(1 for r in rs if r["contacted"])
        booked = sum(1 for r in rs if r["booked"])
        out.append({
            "group": name,
            "dialed": dialed,
            "contacted": contacted,
            "booked": booked,
            "contact_rate": _rate(contacted, dialed),
            "demo_rate": _rate(booked, dialed),
            "thin": dialed < MIN_GROUP,
        })
    return sorted(out, key=lambda g: g["group"])


def _worked_leads(conn) -> list[dict]:
    """Leads with at least one dial, tagged with what actually happened.

    A lead that was never called tells us nothing about the model and must not
    dilute the denominator.
    """
    rows = db.rows_to_dicts(conn.execute("SELECT * FROM leads").fetchall())
    touches: dict[int, list[dict]] = {}
    for t in db.rows_to_dicts(conn.execute(
            "SELECT * FROM lead_touches WHERE kind IN ('call','follow_up')").fetchall()):
        touches.setdefault(t["lead_id"], []).append(t)

    worked = []
    for r in rows:
        ts = touches.get(r["id"])
        if not ts:
            continue
        outcomes = {t["outcome"] for t in ts}
        r["dials"] = len(ts)
        r["contacted"] = bool(outcomes & set(REACHED_OUTCOMES))
        r["booked"] = "booked" in outcomes
        worked.append(r)
    return worked


def _separation(rows: list[dict], field: str) -> dict:
    """Mean score of leads Ian reached vs leads he didn't.

    This is the actually useful output: it says WHICH of fit/pain/reach is
    carrying the signal, so the weights in enrich_prospects.py can be tuned
    rather than guessed.
    """
    hit = [r[field] for r in rows if r["contacted"]]
    miss = [r[field] for r in rows if not r["contacted"]]
    if not hit or not miss:
        return {"field": field, "reached_mean": None, "missed_mean": None, "gap": None}
    hm, mm = sum(hit) / len(hit), sum(miss) / len(miss)
    return {
        "field": field,
        "reached_mean": round(hm, 2),
        "missed_mean": round(mm, 2),
        "gap": round(hm - mm, 2),
    }


def backtest(conn) -> dict:
    """Score the enricher's model against reality. Reports; never rewrites."""
    rows = _worked_leads(conn)
    dials = sum(r["dials"] for r in rows)
    base = {
        "leads_dialed": len(rows),
        "total_dials": dials,
        "contacted": sum(1 for r in rows if r["contacted"]),
        "booked": sum(1 for r in rows if r["booked"]),
        "min_for_signal": MIN_BACKTEST_DIALS,
        "min_for_confidence": TRUSTWORTHY_DIALS,
    }

    if len(rows) < MIN_BACKTEST_DIALS:
        return {
            **base,
            "status": "insufficient",
            "message": (f"Only {len(rows)} leads have been dialed. "
                        f"Need {MIN_BACKTEST_DIALS} before any rate means anything, "
                        f"{TRUSTWORTHY_DIALS} before it's worth acting on."),
        }

    by_tier = _group_stats(rows, lambda r: r["tier"])
    ranked = [g for g in by_tier if not g["thin"] and g["group"] in ("A", "B", "C")]
    ranked.sort(key=lambda g: g["group"])

    verdict, lift = "unclear", None
    if len(ranked) >= 2:
        rates = [g["contact_rate"] for g in ranked]
        if all(a >= b for a, b in zip(rates, rates[1:])):
            verdict = "ordering holds"
        elif all(a <= b for a, b in zip(rates, rates[1:])):
            verdict = "ORDERING INVERTED: better tiers answer less"
        else:
            verdict = "mixed"
        best, worst = ranked[0], ranked[-1]
        if worst["contact_rate"]:
            lift = round(best["contact_rate"] / worst["contact_rate"], 2)

    return {
        **base,
        "status": "ok" if len(rows) >= TRUSTWORTHY_DIALS else "preliminary",
        "message": ("" if len(rows) >= TRUSTWORTHY_DIALS else
                    f"PRELIMINARY: {len(rows)} leads dialed, want {TRUSTWORTHY_DIALS}. "
                    f"Directional only; do not reweight the scorer on this yet."),
        "by_tier": by_tier,
        "verdict": verdict,
        "tier_lift": lift,
        "by_pain": _group_stats(rows, lambda r: _band(r["pain"], (0, 1, 4))),
        "by_reach": _group_stats(rows, lambda r: _band(r["reach"], (0, 2, 4))),
        "by_fit": _group_stats(rows, lambda r: _band(r["fit"], (0, 1, 3))),
        "by_miss_signal": _group_stats(
            rows, lambda r: "has miss-signal" if r["miss_signal"] else "none"),
        "by_claims_247": _group_stats(
            rows, lambda r: "claims 24/7" if r["claims_247"] else "none"),
        "separation": [_separation(rows, f) for f in ("fit", "pain", "reach", "total")],
    }
