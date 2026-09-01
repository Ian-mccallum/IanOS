"""iCloud two-way CalDAV sync for the day plan (SPEC-v7 Phase C).

ianOS WRITES only to a dedicated "ianOS Plan" calendar; every OTHER iCloud
calendar is read as read-only "commitments". The engine functions operate on a
tiny calendar interface (events_in / create / update / delete) so they unit-test
against FakeCalendar with no network. Only connect() and ICloudCalendar touch the
caldav library, imported lazily, so the test suite needs neither credentials nor
a caldav install.

Two rules keep it honest:
  * Conflict: on pull, the REMOTE (phone) wins. One rule, no merge logic.
  * Delete safety: a locally-deleted synced block leaves a plan_tombstone, so the
    next pull deletes it remotely instead of re-importing it (the resurrection trap).

    .venv/bin/python ingest/sync_icloud.py            # full two-way sync
    .venv/bin/python ingest/sync_icloud.py --dry-run  # connect + counts, no writes
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db
from core.env import load_dotenv
from ingest.import_calendar import _categorize

PLAN_CALENDAR_NAME = "ianOS Plan"
WINDOW_BACK = 7
WINDOW_FWD = 30


# ---------------------------------------------------------------- pure helpers

def _title_out(title: str, status: str) -> str:
    """A done block carries a leading check so the phone shows it too."""
    return f"✓ {title}" if status == "done" else title


def _parse_title(summary: str) -> tuple[str, str]:
    """Remote summary → (title, status). Leading '✓ ' means done."""
    s = (summary or "").strip()
    if s.startswith("✓ "):
        return s[2:].strip(), "done"
    return s, "planned"


def _dur_min(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    a = int(start[:2]) * 60 + int(start[3:5])
    b = int(end[:2]) * 60 + int(end[3:5])
    return max(0, b - a)


def _commit_hash(date_s: str, start: str | None, summary: str) -> str:
    # Same scheme as ingest/import_calendar so Google + iCloud commitments dedupe.
    return hashlib.sha256(f"{date_s}|{start}|{summary}".encode()).hexdigest()[:20]


def _window(today: date) -> tuple[str, str]:
    return ((today - timedelta(days=WINDOW_BACK)).isoformat(),
            (today + timedelta(days=WINDOW_FWD)).isoformat())


# ---------------------------------------------------------------- fake (tests)

class FakeCalendar:
    """In-memory calendar implementing the sync interface. Records are dicts:
    {uid, etag, summary, date, start, end, recurring}. Test-only."""

    def __init__(self):
        self._events: dict[str, dict] = {}
        self._seq = 0
        self.deleted: list[str] = []

    def _next_etag(self) -> str:
        self._seq += 1
        return f"etag-{self._seq}"

    def events_in(self, start_date, end_date, expand=False):
        return [dict(r) for r in self._events.values()
                if start_date <= r["date"] <= end_date]

    def create(self, rec) -> str:
        r = dict(rec)
        r.setdefault("recurring", False)
        r["etag"] = self._next_etag()
        self._events[r["uid"]] = r
        return r["etag"]

    def update(self, rec) -> str:
        r = dict(self._events.get(rec["uid"], {}))
        r.update(rec)
        r.setdefault("recurring", False)
        r["etag"] = self._next_etag()
        self._events[r["uid"]] = r
        return r["etag"]

    def delete(self, uid) -> None:
        self.deleted.append(uid)
        self._events.pop(uid, None)

    # --- test helpers simulating phone-side changes -------------------------
    def phone_put(self, uid, summary, date_s, start, end, recurring=False):
        self._events[uid] = {"uid": uid, "summary": summary, "date": date_s,
                             "start": start, "end": end, "recurring": recurring,
                             "etag": self._next_etag()}

    def phone_delete(self, uid):
        self._events.pop(uid, None)


# ---------------------------------------------------------------- engine

def push_blocks(conn, plan_cal, w_start: str, w_end: str) -> dict:
    """Local → remote: apply tombstones, create new blocks, update edited ones."""
    deleted_remote = pushed_new = pushed_dirty = 0

    for row in conn.execute("SELECT caldav_uid FROM plan_tombstones").fetchall():
        try:
            plan_cal.delete(row["caldav_uid"])
        except Exception:
            continue  # delete failed. KEEP the tombstone so pull still skips it
                      # (no resurrection) and the next sync retries.
        conn.execute("DELETE FROM plan_tombstones WHERE caldav_uid=?", (row["caldav_uid"],))
        deleted_remote += 1
    conn.commit()

    new_rows = conn.execute(
        "SELECT * FROM plan_blocks WHERE caldav_uid IS NULL AND date BETWEEN ? AND ?",
        (w_start, w_end),
    ).fetchall()
    for r in new_rows:
        uid = f"ianos-block-{r['id']}-{secrets.token_hex(4)}@ianos.local"
        etag = plan_cal.create({
            "uid": uid, "summary": _title_out(r["title"], r["status"]),
            "date": r["date"], "start": r["start_time"], "end": r["end_time"],
        })
        conn.execute("UPDATE plan_blocks SET caldav_uid=?, caldav_etag=?, synced_at=? WHERE id=?",
                     (uid, etag, db.now(), r["id"]))
        pushed_new += 1
    conn.commit()

    dirty_rows = conn.execute(
        "SELECT * FROM plan_blocks WHERE caldav_uid IS NOT NULL AND synced_at IS NOT NULL "
        "AND updated_at > synced_at AND date BETWEEN ? AND ?", (w_start, w_end),
    ).fetchall()
    for r in dirty_rows:
        etag = plan_cal.update({
            "uid": r["caldav_uid"], "summary": _title_out(r["title"], r["status"]),
            "date": r["date"], "start": r["start_time"], "end": r["end_time"],
        })
        conn.execute("UPDATE plan_blocks SET caldav_etag=?, synced_at=? WHERE id=?",
                     (etag, db.now(), r["id"]))
        pushed_dirty += 1
    conn.commit()

    return {"pushed_new": pushed_new, "pushed_dirty": pushed_dirty, "deleted_remote": deleted_remote}


def pull_blocks(conn, plan_cal, w_start: str, w_end: str) -> dict:
    """Remote → local: import phone-created blocks, let the phone win edits,
    delete blocks the phone removed. Remote always wins; never a merge."""
    pulled_new = pulled_updated = deleted_local = skipped = 0
    tomb = {r["caldav_uid"] for r in conn.execute("SELECT caldav_uid FROM plan_tombstones").fetchall()}
    remote = plan_cal.events_in(w_start, w_end, expand=False)
    remote_uids = set()

    for rec in remote:
        # Plan blocks are single, timed events. Skip recurring / all-day.
        if rec.get("recurring") or not rec.get("start") or not rec.get("end"):
            skipped += 1
            continue
        uid = rec["uid"]
        remote_uids.add(uid)
        if uid in tomb:
            continue  # being deleted this run; don't re-import
        title, status = _parse_title(rec["summary"])
        existing = conn.execute("SELECT * FROM plan_blocks WHERE caldav_uid=?", (uid,)).fetchone()
        if existing is None:
            ts = db.now()   # updated_at == synced_at so a pulled block isn't re-pushed
            conn.execute(
                "INSERT INTO plan_blocks (date, start_time, end_time, title, status, "
                "caldav_uid, caldav_etag, synced_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (rec["date"], rec["start"], rec["end"], title, status, uid,
                 rec.get("etag"), ts, ts))
            pulled_new += 1
        elif existing["caldav_etag"] != rec.get("etag"):
            ts = db.now()   # keep updated_at == synced_at so this doesn't re-push
            conn.execute(
                "UPDATE plan_blocks SET date=?, start_time=?, end_time=?, title=?, status=?, "
                "caldav_etag=?, synced_at=?, updated_at=? WHERE caldav_uid=?",
                (rec["date"], rec["start"], rec["end"], title, status,
                 rec.get("etag"), ts, ts, uid))
            pulled_updated += 1
    conn.commit()

    local = conn.execute(
        "SELECT id, caldav_uid FROM plan_blocks WHERE caldav_uid IS NOT NULL "
        "AND date BETWEEN ? AND ?", (w_start, w_end),
    ).fetchall()
    for r in local:
        if r["caldav_uid"] not in remote_uids and r["caldav_uid"] not in tomb:
            conn.execute("DELETE FROM plan_blocks WHERE id=?", (r["id"],))
            deleted_local += 1
    conn.commit()

    return {"pulled_new": pulled_new, "pulled_updated": pulled_updated,
            "deleted_local": deleted_local, "skipped_recurring": skipped}


def pull_commitments(conn, others, w_start: str, w_end: str) -> dict:
    """Read-only: every other calendar's events become calendar_events rows."""
    n = 0
    for cal in others:
        try:
            recs = cal.events_in(w_start, w_end, expand=True)
        except Exception:
            continue   # a calendar we can't read contributes no commitments
        for rec in recs:
            summary = rec.get("summary") or "event"
            start, end = rec.get("start"), rec.get("end")
            db.upsert_calendar_event(
                conn, date=rec["date"], start_time=start, end_time=end, summary=summary,
                category=_categorize(summary), duration_min=_dur_min(start, end),
                hash=_commit_hash(rec["date"], start, summary))
            n += 1
    conn.commit()
    if others:
        db.update_ingest_log(conn, "calendar", n, "icloud")
    return {"commitments": n}


def sync(conn, connect_fn=None) -> dict:
    """Orchestrate one full two-way pass. connect_fn is injected in tests."""
    connect_fn = connect_fn or connect
    w_start, w_end = _window(date.today())
    plan_cal, others = connect_fn()
    report: dict = {}
    report.update(push_blocks(conn, plan_cal, w_start, w_end))
    report.update(pull_blocks(conn, plan_cal, w_start, w_end))
    report.update(pull_commitments(conn, others, w_start, w_end))
    db.update_ingest_log(conn, "icloud_plan",
                         report["pushed_new"] + report["pushed_dirty"], "sync")
    return report


# ---------------------------------------------------------------- real caldav

class ICloudCalendar:
    """Adapter over a caldav.Calendar. Not unit-tested (needs a real account);
    validated by the manual device pass in SPEC-v7 §5."""

    def __init__(self, cal):
        self._cal = cal

    def events_in(self, start_date, end_date, expand=False):
        # iCloud shards accounts across hosts (pXX-caldav.icloud.com); some
        # calendars return cross-host event URLs the library can't join. Degrade
        # gracefully: a calendar we can't read yields no commitments, never a crash.
        start = datetime.fromisoformat(f"{start_date}T00:00:00")
        end = datetime.fromisoformat(f"{end_date}T23:59:59")
        try:
            found = list(self._cal.search(start=start, end=end, event=True, expand=expand))
        except Exception:
            try:
                found = list(self._cal.events())
            except Exception:
                return []
        out = []
        for ev in found:
            try:
                rec = _event_to_rec(ev)
            except Exception:
                rec = None
            if rec:
                out.append(rec)
        return out

    def create(self, rec) -> str | None:
        saved = self._cal.save_event(_rec_to_ics(rec))
        try:
            return saved.etag
        except Exception:
            return None

    def update(self, rec) -> str | None:
        try:
            ev = self._cal.event_by_uid(rec["uid"])
            ev.data = _rec_to_ics(rec)
            ev.save()
            return ev.etag
        except Exception:
            try:
                saved = self._cal.save_event(_rec_to_ics(rec))
                return saved.etag
            except Exception:
                return None

    def delete(self, uid) -> None:
        # event_by_uid() trips iCloud's host-sharding quirk; instead find the
        # event in the calendar listing (the read path that works) and delete
        # that object. Raises if the delete is attempted and fails, so the caller
        # keeps the tombstone. Not-found = already gone = success.
        try:
            events = list(self._cal.events())
        except Exception:
            events = list(self._cal.search(event=True))
        for ev in events:
            try:
                comp = ev.icalendar_component
            except Exception:
                continue
            if comp is not None and str(comp.get("uid", "")).strip() == uid:
                ev.delete()
                return


def _tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(os.environ.get("IANOS_TZ", "America/Chicago"))


def _fmt_dt(dt, tz):
    if dt is None:
        return None, None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz)
        return dt.date().isoformat(), f"{dt.hour:02d}:{dt.minute:02d}"
    if isinstance(dt, date):
        return dt.isoformat(), None   # all-day
    return None, None


def _event_to_rec(ev):
    try:
        comp = ev.icalendar_component
    except Exception:
        return None
    uid = str(comp.get("uid", "")).strip()
    if not uid:
        return None
    tz = _tz()
    dtstart = comp.get("dtstart")
    dtend = comp.get("dtend")
    date_s, start = _fmt_dt(dtstart.dt if dtstart else None, tz)
    _, end = _fmt_dt(dtend.dt if dtend else None, tz)
    etag = getattr(ev, "etag", None) or hashlib.sha256((ev.data or "").encode()).hexdigest()[:16]
    return {"uid": uid, "summary": str(comp.get("summary", "") or ""), "date": date_s,
            "start": start, "end": end, "recurring": comp.get("rrule") is not None,
            "etag": etag}


def _rec_to_ics(rec) -> bytes:
    import icalendar
    tz = _tz()
    d = rec["date"]
    y, mo, da = int(d[:4]), int(d[5:7]), int(d[8:10])
    start = datetime(y, mo, da, int(rec["start"][:2]), int(rec["start"][3:5]), tzinfo=tz)
    end = datetime(y, mo, da, int(rec["end"][:2]), int(rec["end"][3:5]), tzinfo=tz)
    cal = icalendar.Calendar()
    cal.add("prodid", "-//ianOS//plan//EN")
    cal.add("version", "2.0")
    ev = icalendar.Event()
    ev.add("uid", rec["uid"])
    ev.add("summary", rec["summary"])
    ev.add("dtstart", start)
    ev.add("dtend", end)
    cal.add_component(ev)
    return cal.to_ical()


def connect():
    """Real connection. Returns (plan_calendar_adapter, [other_adapters])."""
    load_dotenv()
    user = os.environ.get("ICLOUD_USERNAME", "").strip()
    pw = os.environ.get("ICLOUD_APP_PASSWORD", "").strip()
    url = os.environ.get("ICLOUD_CALDAV_URL", "https://caldav.icloud.com/").strip()
    if not user or not pw:
        raise RuntimeError("ICLOUD_USERNAME and ICLOUD_APP_PASSWORD must be set in .env")
    try:
        import caldav
    except ImportError as e:
        raise RuntimeError("caldav not installed: run: pip install caldav") from e
    client = caldav.DAVClient(url=url, username=user, password=pw)
    cals = client.principal().calendars()
    plan = next((c for c in cals if (c.name or "") == PLAN_CALENDAR_NAME), None)
    if plan is None:
        try:
            plan = client.principal().make_calendar(name=PLAN_CALENDAR_NAME)
        except Exception as e:
            raise RuntimeError(
                f'Could not create the "{PLAN_CALENDAR_NAME}" calendar. Make it once in '
                f'the Calendar app, then rerun make sync-icloud. ({e})') from e
    others = [ICloudCalendar(c) for c in cals if (c.name or "") != PLAN_CALENDAR_NAME]
    return ICloudCalendar(plan), others


def main() -> None:
    ap = argparse.ArgumentParser(description="iCloud two-way sync for the day plan")
    ap.add_argument("--dry-run", action="store_true",
                    help="connect and report pending counts without writing")
    args = ap.parse_args()
    load_dotenv()
    conn = db.connect()
    try:
        if args.dry_run:
            plan_cal, _ = connect()
            w_start, w_end = _window(date.today())
            new = conn.execute("SELECT COUNT(*) FROM plan_blocks WHERE caldav_uid IS NULL "
                               "AND date BETWEEN ? AND ?", (w_start, w_end)).fetchone()[0]
            dirty = conn.execute("SELECT COUNT(*) FROM plan_blocks WHERE caldav_uid IS NOT NULL "
                                 "AND updated_at > synced_at AND date BETWEEN ? AND ?",
                                 (w_start, w_end)).fetchone()[0]
            tombs = conn.execute("SELECT COUNT(*) FROM plan_tombstones").fetchone()[0]
            remote = len(plan_cal.events_in(w_start, w_end))
            print(f"dry-run: would push {new} new + {dirty} edited, delete {tombs} remote; "
                  f'"{PLAN_CALENDAR_NAME}" currently has {remote} event(s)')
            return
        report = sync(conn)
        print("iCloud sync: " + ", ".join(f"{k}={v}" for k, v in report.items()))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
