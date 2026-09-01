"""Journal derivations (SPEC-v8 / v11). Pure, no network, no LLM.

The privacy law: agent-facing code reads entry DATES only. The single
agent-facing function, `agent_signal()`, returns counts and booleans, never
`body`, never `media_path`. Text/media stay behind `/api/journal*` (LAN-token
OK on phone; never in `/api/state`).

No streak: `journal_stats` reports a rolling count that cannot reset, so there is
nothing to "break" and nothing to shame (SPEC-v8 zero-shame law).
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta

JOURNAL_DAY_CUTOFF_HOUR = 4   # 00:00-03:59 still belongs to yesterday


def journal_day(now: datetime) -> str:
    """The day an entry written at `now` belongs to. Before 04:00 local it is the
    PREVIOUS calendar day, closing the day at 12:40am closes *today*, not tomorrow.
    The server always computes this; the client never sends a date."""
    d = now.date()
    if now.hour < JOURNAL_DAY_CUTOFF_HOUR:
        d = d - timedelta(days=1)
    return d.isoformat()


def is_closed(conn, date: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM journal_entries WHERE date = ? LIMIT 1", (date,)
    ).fetchone() is not None


def _closed_dates(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT date FROM journal_entries").fetchall()}


def journal_stats(conn, today: str) -> dict:
    """Ian-facing counts. A rolling 7-day count + a monotonic total, no streak,
    nothing that can break."""
    dates = _closed_dates(conn)
    week = {(_date.fromisoformat(today) - timedelta(days=i)).isoformat() for i in range(7)}
    return {
        "closed_today": today in dates,
        "nights_closed_total": len(dates),
        "nights_closed_7d": len(dates & week),
    }


def agent_signal(conn, today: str) -> dict:
    """EXACTLY what agents may ever see about the journal: counts + booleans, never
    text, never media. Do not add a `body` or `media_path` key here, ever."""
    stats = journal_stats(conn, today)
    last = conn.execute(
        "SELECT MAX(date) FROM journal_entries WHERE date <= ?", (today,)
    ).fetchone()[0]
    days_since = (_date.fromisoformat(today) - _date.fromisoformat(last)).days if last else None
    return {
        "closed_today": stats["closed_today"],
        "nights_closed_7d": stats["nights_closed_7d"],
        "nights_closed_total": stats["nights_closed_total"],
        "days_since_last_close": days_since,
    }


def on_this_day(conn, today: str) -> list[dict]:
    """Full entry rows from the same month-day in PREVIOUS years, the look-back
    payoff. Ian-only surface (served via /api/journal, never in `/api/state`)."""
    rows = conn.execute(
        "SELECT * FROM journal_entries "
        "WHERE strftime('%m-%d', date) = strftime('%m-%d', ?) AND date < ? "
        "ORDER BY date DESC",
        (today, today),
    ).fetchall()
    return [dict(r) for r in rows]


def journal_days(conn, limit: int = 60, before_date: str | None = None) -> list[dict]:
    """One row per closed date for photo-day / day-card browse (SPEC-v11).
    Cover = first entry that day with media, else None. Snippet = first body."""
    params: list = []
    where = ""
    if before_date:
        where = "WHERE date < ?"
        params.append(before_date)
    dates = [
        r[0] for r in conn.execute(
            f"""SELECT DISTINCT date FROM journal_entries {where}
                ORDER BY date DESC LIMIT ?""",
            (*params, int(limit)),
        ).fetchall()
    ]
    out = []
    for d in dates:
        entries = [
            dict(r) for r in conn.execute(
                "SELECT * FROM journal_entries WHERE date = ? ORDER BY id", (d,)
            ).fetchall()
        ]
        if not entries:
            continue
        cover = next((e for e in entries if e.get("media_kind")), None)
        out.append({
            "date": d,
            "snippet": (entries[0].get("body") or "")[:120],
            "entry_count": len(entries),
            "has_media": cover is not None,
            "cover_entry_id": cover["id"] if cover else None,
            "cover_kind": cover["media_kind"] if cover else "",
        })
    return out


def journal_month(conn, yyyy_mm: str) -> dict:
    """Soft month map for calendar jumper, closed days only carry flags.
    UI must never shame empty cells (SPEC-v11)."""
    try:
        y, m = map(int, yyyy_mm.split("-"))
        first = _date(y, m, 1)
    except (ValueError, TypeError) as e:
        raise ValueError("month must be YYYY-MM") from e
    if m == 12:
        last = _date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = _date(y, m + 1, 1) - timedelta(days=1)
    rows = conn.execute(
        """SELECT date,
                  COUNT(*) AS entry_count,
                  SUM(CASE WHEN media_kind != '' THEN 1 ELSE 0 END) AS media_count
           FROM journal_entries
           WHERE date >= ? AND date <= ?
           GROUP BY date""",
        (first.isoformat(), last.isoformat()),
    ).fetchall()
    days = {
        r[0]: {
            "closed": True,
            "entry_count": r[1],
            "has_media": (r[2] or 0) > 0,
        }
        for r in rows
    }
    return {"month": yyyy_mm, "days": days}
