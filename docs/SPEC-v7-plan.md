# ianOS v7: "Plan" (low-friction daily calendar, iCloud two-way)

**Status:** approved direction from Ian's brainstorm (2026-07-21).
**Audience:** an implementing agent with no prior context. Read this file + the
repo; verify every "current state" claim with the greps in §0 before coding.
**Thesis:** Ian's brain fails in the 16-hour desert between the Day Command and
bedtime: task-initiation paralysis, time blindness, now-vs-not-now collapse. The
fix is a **present-tense surface**, a day canvas where placing an intention is
one tap, *now* is always visible, and a block that passes unfinished **wilts,
never bleeds**. The plan lives in ianOS and two-way syncs with a dedicated
**"ianOS Plan"** calendar in Ian's iCloud (his real calendar home), so blocks
appear natively on his iPhone. Journaling is **NOT in this spec**, it is
SPEC-v8 (see §7 non-goals; one decision is pre-recorded there).

**Design laws (apply to every decision):**
- Zero shame. A past unfinished block is "sailed", rendered softened, never
  red, never labeled "missed/overdue/late/failed". `--crit` is banned on this page.
- Zero typing where possible; one tap otherwise. Suggestions beat blank fields.
- Delight is committed or absent: completion is fully animated;
  `prefers-reduced-motion` gets an instant swap. No half-hearted transitions.
- Truth is derivable: store minimal state ('planned'|'done'); "sailed" and all
  aggregates are computed, never stored.
- Ian's existing events are sacred: ianOS **writes only** to the "ianOS Plan"
  calendar. All other iCloud calendars are read-only commitments.
- The UI never shows an adherence %, streak, or completion stat for blocks.
  Plan-vs-actual is agent-side signal only (§4).

---

## 0. Current state to verify first

```bash
grep -n "calendar_events" core/db.py | head        # existing read-only commitments table
grep -nA6 "def upsert_calendar_event" core/db.py   # hash-conflict upsert to reuse
grep -n "_categorize" ingest/import_calendar.py    # summary → work|health|personal
grep -n "PAGES = " dashboard/src/App.jsx           # hash-router page list
grep -n "LINKS = " dashboard/src/components/Nav.jsx  # nav entries + MOBILE_PRIMARY
grep -n "features" api/main.py | head              # /api/health feature flags
grep -n "_agent_run_lock\|COOLDOWN" api/main.py    # lock+cooldown pattern to copy
grep -n "read_calendar" agents/runner.py           # steward's calendar tool
grep -n "_is_stale\|stale_data_domains" core/metrics.py  # freshness by ingest_log source
cat .env.example                                    # env conventions
```

Facts assumed (fix this spec against reality if a grep disagrees):
`calendar_events(date, start_time "HH:MM", end_time, summary, category,
duration_min, hash UNIQUE)` exists and is fed by the connector /.ics import;
the dashboard is hash-routed via `PAGES` in `App.jsx` with 15s `/api/state`
polling; `/api/agents/run` shows the lock + cooldown pattern; steward freshness
runs off `ingest_log` source `'calendar'`; times are local strings, dates ISO.

---

## 1. Plan engine (Phase A, works with zero iCloud config)

### Schema (append to `SCHEMA` in `core/db.py`)

```sql
CREATE TABLE IF NOT EXISTS plan_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,                 -- YYYY-MM-DD
    start_time  TEXT NOT NULL,                 -- "HH:MM", 15-min snapped
    end_time    TEXT NOT NULL,                 -- must be > start_time
    title       TEXT NOT NULL,
    goal_id     INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','done')),
    caldav_uid  TEXT UNIQUE,                   -- null until first push
    caldav_etag TEXT,
    synced_at   TEXT,                          -- null = never synced
    updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_plan_date ON plan_blocks(date);

CREATE TABLE IF NOT EXISTS plan_tombstones (
    caldav_uid TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

Only two statuses, by design. 'sailed' (end passed, still 'planned') and
'moved' (edited times) are **derived**, never stored. Every API write sets
`updated_at` explicitly, sync compares `updated_at > synced_at` to know what
to push.

### `core/plan.py`, pure functions (all unit-tested, no network, no LLM)

```python
def is_sailed(block: dict, today: str, now_hhmm: str) -> bool
    # status=='planned' and (date < today or (date == today and end_time <= now_hhmm))

def suggest_blocks(conn, date: str) -> list[dict]
    # Max 4 chips, fixed priority order, each {key, title, duration_min, goal_id}:
    # 1. brief exists for `date`            → {"key":"command",  "title":"Day Command",            90, None}
    # 2. hero business goal exists          → {"key":"hero",     "title":"Deep work: <goal name>", 90, goal.id}
    # 3. activity.audit_calls today < 20    → {"key":"calls",    "title":"Call block",             60, None}
    # 4. weekday and gym not confirmed      → {"key":"gym",      "title":"Gym",                    60, None}
    # 5. any open partner_tasks               → {"key":"partner",    "title":"Partner time",             45, None}
    # (first four that qualify, in this order)

def next_free_slot(blocks, commitments, duration_min, now_hhmm) -> tuple[str, str]
    # earliest 15-min boundary >= max(now, "06:00") whose [start, start+duration)
    # overlaps no block and no timed commitment; fallback: right after the last
    # occupied minute; never returns a start past "22:00" (then clamp to 22:00).

def overpack_warning(blocks) -> str | None
    # >5 'planned' blocks OR >6h total planned → 
    # "That's a lot for one day. Champions pick 3.", else None.

def plan_adherence_7d(conn, today: str) -> dict
    # {"planned": n, "done": n} over the last 7 days. AGENT-ONLY (§4); never
    # rendered in the UI.
```

### API (`api/main.py`, same conn/finally style as existing endpoints)

```
GET  /api/day?date=YYYY-MM-DD      (default: today)
  → {date, is_today, blocks: [ ...row + goal_name + sailed ],
     commitments: [calendar_events rows for date, all_day = start_time is null],
     suggestions: suggest_blocks(...), overpack: str|null,
     icloud: {configured: bool, last_sync: str|null}}

POST   /api/plan/blocks            {date, start_time, end_time, title, goal_id?}
PATCH  /api/plan/blocks/{id}       partial: title/date/start_time/end_time/status/goal_id
DELETE /api/plan/blocks/{id}       if row.caldav_uid: INSERT INTO plan_tombstones first
POST   /api/plan/sync              (§3; 501 {"detail":"iCloud not configured"} when unset)
```

Validation: `end_time > start_time`, ISO date, non-empty title, times snap to
15 min (reject otherwise, 400). **Overlaps are allowed**: reality is messy;
the canvas renders them side-by-side. `/api/health` features gains
`"plan": true, "icloud_sync": <bool of env set>`.

Every create/delete writes a blackboard memo from `"ian"` (matching goals
endpoints), e.g. `("ian", "plan", 'Ian planned "Call block" 09:00-10:00')` : 
create and delete only, not edits (noise discipline).

### Tests: `tests/test_plan.py`
Table-driven: sailed derivation (past day, today-before-end, today-after-end,
done never sails); each suggestion rule fires and respects order + max 4;
next_free_slot skips commitments, snaps, clamps at 22:00; overpack boundary
(5 blocks ok, 6 warns; 6h boundary); API round-trip create→patch→delete with
tombstone row appearing; 15-min snap rejection.

---

## 2. The day canvas (Phase B: `dashboard/src/pages/PlanPage.jsx`)

### Routing/nav (exact edits)
- `App.jsx`: add `'plan'` to `PAGES`; `PAGE_TITLES.plan = ['Plan', 'Your day, one block at a time']`; render `<PlanPage state={state} refresh={refresh} toast={toast} />`.
- `Nav.jsx LINKS`: `{ id: 'plan', label: 'Plan', short: 'Plan', icon: '▤', section: 'top' }`
  directly after `home`. `MOBILE_PRIMARY = ['home', 'plan', 'btc', 'partner']`
  (body's gym confirm already lives on Command's ActionStack; School/Life/Money
  join `MOBILE_MORE`, keep `body` first in MOBILE_MORE).
- CommandPalette: pages list gains Plan (follow however it sources pages).

### Layout
- Header: 7 day-chips centered on today (`‹ Mon 20 · TUE 21 · Wed 22 ›` style),
  tap to switch; a "Today" chip appears when viewing another day. No month grid.
- All-day commitments render as quiet chips above the ribbon.
- Vertical time ribbon **06:00-23:00**, hour gridlines, auto-scrolls so *now*
  sits in the upper third on mount (today only).
- **Two layers:** commitments (subdued, non-interactive, `--muted` border,
  category-tinted at low alpha) behind/beside plan blocks (interactive, solid,
  goal-domain-tinted when `goal_id` set, `--accent` otherwise). Overlapping
  items share the column width side-by-side (simple flex split, max 3 columns).
- **Now-line:** 1px `--accent` line + small dot at the current minute, updated
  by a 60s interval (client clock), `aria-hidden`, no pulse under reduced
  motion (no pulse at all, it's a position, not an alarm).
- **Next chip:** sticky under the header when today has a future item:
  `Next: <title> · in 40m`. Computed client-side from blocks+commitments.
- Fetch: `GET /api/day` on mount and on date change; re-fetch after every
  mutation; piggyback the existing 15s polling only for today.

### Interactions (NO drag-and-drop, hard non-goal, §7)
- Tap empty ribbon space → creation sheet pre-filled with that 15-min slot,
  60-min duration, the ≤4 suggestion chips on top (tap chip = title+duration
  +goal filled), title input, **Start AND End** `<input type="time" step="900">`
  pickers, duration presets [30m|1h|1.5h|2h|3h|4h], Save. **Blocks may be any
  length**, the presets are shortcuts, not limits; the API only enforces
  `end > start` on the 15-min grid. Tapping a suggestion chip in the *header*
  zone creates instantly at `next_free_slot`, zero further taps.
- Tap a block → action sheet: **Done** (primary) · Edit (title + Start/End, so a
  block's length is editable, not just its position) · Tomorrow · Delete.
  Focus-trapped, Esc closes.
- **Done delight:** checkmark draws in, block settles (scale 1→1.03→1, slight
  saturate), toast `Block done · <title>`. When the last planned block of today
  completes: one particle burst (reuse the existing burst pattern) + toast
  `Clean sweep.` Reduced motion: instant checkmark, no particles.
- **Sailed rendering:** opacity .55, desaturated, title unstruck, **no label,
  no icon, no color shift toward red**. Tapping it still offers Done ("done
  late" is just done) and Move ("tomorrow" one-tap option in Move).
- Overpack: when `/api/day.overpack` is set, show the copy once as a quiet
  inline line under the header, never a modal, never blocking.

### A11y
Blocks are `<button>`s, `aria-label="<title>, 09:00 to 10:00, planned|done"`;
ribbon is keyboard-tabbable in time order; sheets focus-trap and restore focus;
day-chips are a `role="tablist"`. All colors from existing CSS vars only.

---

## 3. iCloud two-way sync (Phase C: `ingest/sync_icloud.py`)

### Setup & env (`.env.example` additions)

```
# iCloud CalDAV: two-way sync of the ianOS Plan calendar
# Generate an app-specific password at appleid.apple.com → Sign-In & Security
ICLOUD_USERNAME=
ICLOUD_APP_PASSWORD=
ICLOUD_CALDAV_URL=https://caldav.icloud.com/
IANOS_TZ=America/Chicago
```

`requirements.txt`: `caldav>=1.6`. Password must never be logged or echoed.

### Connection

```python
client = caldav.DAVClient(url, username=..., password=...)
principal = client.principal()
cals = principal.calendars()
plan_cal = next((c for c in cals if c.name == "ianOS Plan"), None)
if plan_cal is None:
    try: plan_cal = principal.make_calendar(name="ianOS Plan")
    except Exception: sys.exit('Create a calendar named "ianOS Plan" in the '
                               'Calendar app, then rerun make sync-icloud.')
others = [c for c in cals if c.name != "ianOS Plan"]
```

### Engine: testable seam (no network in the logic functions)

```python
WINDOW = (today - 7 days, today + 30 days)

def push_blocks(conn, plan_cal) -> dict:
    # 1. tombstones: for each plan_tombstones row, event_by_uid → .delete()
    #    (NotFoundError → fine); then DELETE the tombstone row.
    # 2. new: rows in WINDOW with caldav_uid IS NULL →
    #    uid = f"ianos-block-{id}-{secrets.token_hex(4)}@ianos.local"
    #    plan_cal.save_event(dtstart=<tz-aware datetime via ZoneInfo(IANOS_TZ)>,
    #                        dtend=..., summary=title_out(row), uid=uid)
    #    store uid, etag if retrievable (else null), synced_at=now.
    # 3. dirty: rows where updated_at > synced_at → event_by_uid, rewrite
    #    DTSTART/DTEND/SUMMARY, save; update etag+synced_at.
    # title_out(row): "✓ " + title when status=='done' else title.

def pull_blocks(conn, plan_cal) -> dict:
    # events = plan_cal.search(start=..., end=..., event=True)   # no expand
    # skip any event carrying an RRULE (count as skipped_recurring).
    # For each event uid:
    #   - in plan_tombstones → ignore (it is being deleted).
    #   - unknown uid → INSERT plan_blocks (phone-created; parse "✓ " prefix →
    #     status='done', strip prefix), set uid/etag/synced_at.
    #   - known uid, remote etag != stored → REMOTE WINS unconditionally:
    #     overwrite local date/times/title/status from the event. This is the
    #     single conflict rule; do not implement merge logic.
    # Known uids in WINDOW absent from remote → deleted on phone → DELETE local row.

def pull_commitments(conn, others) -> dict:
    # for each calendar: search(WINDOW, event=True, expand=True)  # expands RRULEs
    # upsert into calendar_events with hash = sha256(f"{date}|{start}|{summary}")
    #   .hexdigest()[:20]  (identical scheme to ingest/import_calendar.py),
    # category via ingest.import_calendar._categorize, duration computed.
    # update_ingest_log(conn, "calendar", n, "icloud")  ← keeps steward's
    # staleness logic working unchanged.

def sync(conn, connect=connect) -> dict   # orchestrates, returns the report
```

CLI: `python ingest/sync_icloud.py [--dry-run]` prints the report; `Makefile`
gains `sync-icloud:`. Also log `update_ingest_log(conn, "icloud_plan", ...)`.

### `POST /api/plan/sync`
Copy the `/api/agents/run` lock + cooldown pattern, cooldown **120s**, but run
sync **inline** in the request (it takes seconds) and return the report. Within
cooldown → `{ok: true, throttled: true}` (200, not 429, the UI auto-fires it
on Plan mount and must not toast an error). Env unset → 501. The Plan page
shows a small `Sync` button + `last_sync` line only when
`/api/health.features.icloud_sync` is true.

### Tests: `tests/test_icloud_sync.py`
`FakeCalendar` implementing `search/save_event/event_by_uid/delete` in memory.
Cover: new local → pushed with uid; local edit → pushed; phone-created →
inserted locally; phone edit (etag change) → remote wins; phone delete →
local delete; **local delete → tombstone → remote delete → no resurrection on
the next pull** (the classic trap, test the full cycle); "✓ " round-trip both
directions; RRULE event in plan calendar skipped; commitments upsert idempotent
(second run changes zero rows).

---

## 4. Agent visibility (Phase D: signal, not surveillance)

- `read_calendar` tool (agents/runner.py): response gains
  `"plan_blocks_7d": db.recent_plan_blocks(conn, 7)` and
  `"plan_adherence_7d": plan.plan_adherence_7d(...)`, raw rows + one
  code-computed aggregate, per house rules. No new tool, no allowlist changes
  (steward/chief/lovebird/advisor/family already hold `read_calendar`).
- steward mandate (`agents/roles/steward.md`): add one rule: "If plan blocks
  exist, compare planned vs done **without shame framing**: a repeatedly
  re-planned block is a task-initiation signal; propose making it tomorrow's
  FIRST block, never propose 'try harder'."
- chief prompt builder: if tomorrow (or today) has plan blocks, append a
  precomputed line listing them so the Day Command can reference real times.
- CommandPage: when today has a future block, the hero shows one quiet line
  `Next: <title> at HH:MM` (link → #plan). Nothing else changes on Command.

---

## 5. Acceptance criteria

- [ ] `pytest` green including `test_plan.py` and `test_icloud_sync.py`; all
      sync tests pass with the fake, no network in CI.
- [ ] With **no** ICLOUD_* env: Plan page fully works local-only; sync button
      absent; `/api/plan/sync` → 501.
- [ ] Browser: tap empty slot → sheet with suggestions → save → block renders;
      header suggestion chip creates at next free slot with zero further taps;
      Done plays the full delight sequence and is instant under reduced motion.
- [ ] A block whose end passed renders softened with **no label and no red**;
      grep PlanPage + styles for "missed", "overdue", "late", "failed",
      `--crit` → zero hits.
- [ ] No adherence %, completion count, or streak appears anywhere on Plan.
- [ ] Real device pass: `make sync-icloud` creates "ianOS Plan" in iCloud; a
      block made in ianOS appears on the iPhone within one sync; an event
      created in that calendar on the phone appears in ianOS; deleting in ianOS
      removes it from the phone and it does **not** resurrect on the next sync.
- [ ] Ian's other iCloud calendars are never written to (code writes only via
      `plan_cal`; verify no `save_event` call sites on `others`).
- [ ] Mobile 375px: canvas, sheets, and day-chips all usable.

## 6. Build order

A (schema + core/plan.py + API + tests) → B (PlanPage canvas + nav) →
C (CalDAV engine + fake-server tests + real-device pass) → D (agent visibility
+ Command "Next" line) → acceptance sweep → update README, GOALS.md
cross-reference, IAN-SETUP.md ("create your app-specific password"), CLAUDE.md
layout section. Commit per phase.

## 7. Non-goals (fences, not suggestions)

- **Journaling**. SPEC-v8. One decision is already made and recorded here so
  v8 inherits it: agents get structured signal (mood, plan-vs-actual, tags);
  raw journal text stays private unless Ian explicitly shares an entry.
  `plan_blocks.status` stays minimal on purpose, v8 adds reactions to blocks.
- Drag-and-drop, block resize handles, jank trap; the sheet moves blocks.
- Recurring plan blocks (RRULE authoring), week/month grid views, multi-day
  events on the ribbon (all-day chips only).
- Google Calendar in any form, the connector `/sync-calendar` path still
  exists but is not part of this feature; no OAuth app, ever, for v7.
- Push notifications/reminders (iCloud sync gives native iOS alerts for free
  if Ian sets an alert on the calendar, document, don't build).
- Any UI stat about completion rate; any "behind schedule" messaging.
- Timers/focus sessions: that's a future "Now" spec, not this one.
