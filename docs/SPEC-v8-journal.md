# ianOS v8: "Shutdown" (nightly reflection journal + daily memory)

**Status:** approved direction from Ian's brainstorm (2026-07-22), revised same
day after architectural analysis + a goal update from Ian.
**Audience:** an implementing agent with no prior context. Read this file + the
repo; verify every "current state" claim with the greps in §0 before coding.
**Thesis:** every night Ian closes the day: he writes freely about what he did
and how he felt, attaches **one photo or video** from the day, and the entry
joins a private timeline he can **look back on**, what did I do on any given
day, what was last Tuesday like, what happened on this day last year. It is a
reflection ritual AND a life record. The words and media are for Ian and Ian
only; agents never see them. What agents DO see is a single boolean: *"Ian
closed the day"*, plus shame-free counts.

Locked product decisions (from Ian, do not relitigate):
- **Blank page.** No prompts, no rotating questions, no mood taps, no imposed
  fields. His words carry the "what I did / how I felt".
- **One photo/video per entry**, optional, uploaded from the laptop (file
  picker / drag-drop; AirDrop-to-Mac is the phone bridge).
- **Memory is a core goal.** Entries persist forever, are browsable by day, and
  resurface via "On this day". (This supersedes the earlier offload-only
  framing, retrieval is IN.)
- **Evening Shutdown ritual.** A gentle nightly nudge; the day's closing bookend.
- **Laptop only.** No phone endpoints, no voice/dictation (non-goals).
- **Private from agents, readable by Ian.** Agents get only the boolean +
  counts; a single entry's TEXT reaches the blackboard only if Ian taps Share
  (media is never shared).

**Design laws (apply to every decision):**
- **Blank & promptless.** One empty box. Never suggest what to write.
- **Privacy is structural, not promised.** Journal text/media never appear in
  `/api/state`, in any agent tool payload, or in any prompt, enforced in code
  and by tests. `/api/journal*` is **localhost-only even when the LAN token is
  active** (the journal is laptop-only by product decision, so this costs nothing).
- **Zero shame.** No streak that can "break": the signal is a rolling count that
  cannot reset. A day without an entry renders as quiet blankness in the
  timeline, never a gap marker, never red. `--crit` is banned on every
  Shutdown/Journal surface, as are the words "missed", "skipped", "failed".
- **The exhale is the reward.** Closing the day is one committed, satisfying
  gesture; fully animated; `prefers-reduced-motion` gets an instant swap.
- **Memory without metrics.** Look-back is a timeline of days, not a dataset:
  no charts, no word counts, no sentiment, no completion percentages.

---

## 0. Current state to verify first

```bash
grep -nA8 "def _auth_decision\|async def _guard" api/main.py   # LAN token middleware, journal must be EXEMPT from its allowances
grep -n "def health\b\|features" api/main.py | head            # feature flags
grep -n "PAGES = \|PAGE_TITLES" dashboard/src/App.jsx           # hash router
grep -n "LINKS = \|MOBILE_PRIMARY\|MOBILE_MORE" dashboard/src/components/Nav.jsx
grep -n "PAGES = " dashboard/src/components/CommandPalette.jsx  # Cmd+K page list
grep -n 'add_memo(conn, "ian"' api/main.py | head               # share mechanism target
grep -nB2 -A6 'role == "physician"' agents/runner.py            # boolean-signal injection point
grep -n "journal" core/db.py                                    # only PRAGMA journal_mode: no collision
grep -n "data/" .gitignore                                      # data/ is NOT blanket-ignored → must add data/journal/
grep -n "prefers-reduced-motion\|glass-card" dashboard/src/styles.css | head
```

Facts assumed (fix this spec if a grep disagrees): the v6 `_guard` middleware
lets ANY route be reached from the LAN with a valid `IANOS_API_TOKEN` bearer : 
so without an explicit exemption the journal would be readable off-laptop; the
dashboard is hash-routed via `PAGES` with 15s `/api/state` polling;
`db.add_memo(conn, "ian", topic, body)` is how Ian's words reach the blackboard;
the physician (Dr. House) gets precomputed lines in `build_user_prompt`;
`python-multipart` is importable (pin it in requirements anyway); dates are ISO
local strings.

---

## 1. Data + privacy (Phase A, the walls before the windows)

### Schema (append to `SCHEMA` in `core/db.py`)

```sql
CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,                 -- the day being closed (journal_day, §below)
    body        TEXT NOT NULL,
    media_path  TEXT NOT NULL DEFAULT '',      -- relative to ROOT, e.g. data/journal/2026/07/12-a3f2.jpg
    media_kind  TEXT NOT NULL DEFAULT '' CHECK (media_kind IN ('', 'photo', 'video')),
    shared      INTEGER NOT NULL DEFAULT 0,    -- 1 once Ian sends the TEXT to the agents
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);
```

Multiple entries per date are allowed (a second thought before bed is fine);
each entry carries at most ONE media file. A date is **"closed"** iff it has
≥1 entry, derived, never stored. Add `data/journal/` to `.gitignore` (data/ is
NOT blanket-ignored, verify with the §0 grep).

### `core/journal.py`, pure functions (unit-tested, no network, no LLM)

```python
JOURNAL_DAY_CUTOFF_HOUR = 4   # 00:00-03:59 still belongs to yesterday

def journal_day(now: datetime) -> str
    # The day an entry written at `now` belongs to. Before 04:00 local, it's the
    # PREVIOUS calendar day, an student closing his day at 12:40am is
    # closing *today's* day, not tomorrow's. The API and the nudge both use this;
    # the client never sends a date.

def is_closed(conn, date: str) -> bool
    # EXISTS(SELECT 1 FROM journal_entries WHERE date = ?)

def journal_stats(conn, today: str) -> dict
    # For Ian's UI: {"closed_today": bool, "nights_closed_total": int,
    #                "nights_closed_7d": 0..7}
    # NO streak. A rolling 7-day count cannot break, so there is nothing to
    # forgive and nothing to shame. nights_closed_total is monotonic.

def agent_signal(conn, today: str) -> dict
    # EXACTLY what agents may see, counts only, never text, never media:
    # {"closed_today": bool, "nights_closed_7d": int,
    #  "nights_closed_total": int, "days_since_last_close": int | None}

def on_this_day(conn, today: str) -> list[dict]
    # Entries from the same month-day in PREVIOUS years (full rows, Ian-only
    # surface): WHERE strftime('%m-%d', date) = strftime('%m-%d', ?) AND date < ?
```

`agent_signal` must never return, log, or embed `body` or `media_path`.

### DB helpers (`core/db.py`)

`create_journal_entry(conn, date, body)`, `journal_entry(conn, id)`,
`recent_journal(conn, limit=30, before_id=None)` (reverse-chron page for the
timeline), `journal_for_date(conn, date)`, `update_journal_entry(conn, id,
**fields)`, allowed fields `body, media_path, media_kind, shared`, and it MUST
set `updated_at = now()` explicitly (SQLite won't) : 
`delete_journal_entry(conn, id)` (also unlink the media file if present).

### API (`api/main.py`)

```
GET    /api/journal?limit=30&before_id=  → {entries, stats, on_this_day}
GET    /api/journal/day/{date}           → {entries: journal_for_date(...)}
POST   /api/journal                      {body} → create (date = journal_day(now)); returns {entry, stats}
PATCH  /api/journal/{id}                 {body?} → edit text (bumps updated_at)
DELETE /api/journal/{id}                 → delete entry + its media file
POST   /api/journal/{id}/media           multipart file → attach/replace the entry's ONE media
GET    /api/journal/media/{id}           → stream the entry's media (FileResponse)
DELETE /api/journal/{id}/media           → remove media, keep the entry
POST   /api/journal/{id}/share           → opt-in: TEXT becomes a from_role='ian' memo
```

Rules an implementer must not improvise on:
- `POST /api/journal`: reject empty/whitespace body (400). Server computes the
  date via `journal.journal_day(datetime.now())`, ignore any client date.
- **Media upload:** accept extensions `jpg jpeg png heic webp gif` (→ `photo`)
  and `mp4 mov webm` (→ `video`), case-insensitive; anything else 400. Max size
  **512 MB**; stream to disk with `shutil.copyfileobj` (never read into memory);
  if the streamed size exceeds the cap, delete the partial file and return 413.
  Save to `data/journal/<YYYY>/<MM>/<entry_id>-<secrets.token_hex(4)>.<ext>`
  (mkdir parents). Replacing media deletes the old file first. Store the
  ROOT-relative path + kind on the entry.
- **Media serving:** look up the entry by numeric id and serve ITS stored path
  via `FileResponse`, never accept a client-supplied path (no traversal
  surface). 404 if the entry has no media.
- `POST .../share`: set `shared=1` and `db.add_memo(conn, "ian",
  f"journal {entry_date}", body)`. Text only, media is NEVER shared.
  Idempotent: second share is a no-op. This is the single path words reach agents.
- `/api/health` features gains `"journal": true`.
- `requirements.txt`: add `python-multipart>=0.0.9`.

### The privacy wall (load-bearing; all three layers required)

1. **Middleware:** in `_guard`, any request whose path starts with
   `/api/journal` from a non-local host is rejected **403 even with a valid
   bearer token**, the LAN token (used by v6 phone capture) must not unlock
   the journal. Localhost behaves normally.
2. **State:** `/api/state` must not include journal entries, stats, bodies, or
   media paths. The SPA fetches journal data only from `/api/journal*`.
3. **Agents:** journaling adds NO tool to `runner.py`'s `ALL_TOOLS`/`ALLOWLISTS`.
   The only agent-facing surface is the precomputed `agent_signal(...)` line
   (§4). The share endpoint is the single, explicit, Ian-initiated exception : 
   and it moves text into the *memos* table rather than exposing the journal.

### Tests: `tests/test_journal.py`

- `journal_day`: 23:59 → today; 00:40 → yesterday; 04:00 → today (boundary).
- `is_closed` / `journal_stats` / `agent_signal`: counts correct; rolling 7-day
  window; serialized `agent_signal` contains no `body` and no `media_path` key.
- `on_this_day`: same month-day previous years only; today's year excluded.
- API round-trip: create (server-dated) → list → patch body (updated_at bumps)
  → delete (unlinks media file from disk).
- Media: upload jpg → kind `photo`, file exists under `data/journal/`; upload
  `.exe` → 400; replace deletes the old file; serve returns 200 with bytes;
  entry-without-media serve → 404; DELETE media keeps the entry.
- Share: sets `shared=1`, creates exactly ONE `from_role='ian'` memo with topic
  `journal <date>` and matching body; second share no-ops (still one memo).
- **Privacy tests (the point of Phase A):**
  (a) seed an UNSHARED entry with a sentinel word + media → the sentinel and
  the media path appear NOWHERE in `/api/state`'s JSON;
  (b) a SHARED entry's text appears in state exactly once, as a memo (by design);
  (c) simulate a LAN client (non-local host header/client) with a valid token →
  `GET /api/journal` and `GET /api/journal/media/{id}` both 403;
  (d) `grep -n "journal" agents/runner.py` resolves only to the `agent_signal`
  injection, no tool, no allowlist entry (encode as a source-scan assertion).

---

## 2. Shutdown: the nightly close (Phase B: `dashboard/src/pages/ShutdownPage.jsx`)

A **mode**, not a busy page: entering it dims the shell and the day gently ends.

### Routing, nav, and the dim
- `App.jsx`: add `'shutdown'` AND `'journal'` to `PAGES`;
  `PAGE_TITLES.shutdown = ['Shutdown', 'Close the day']`,
  `PAGE_TITLES.journal = ['Journal', 'Only you can read this']`.
- **The dim is a class, not a modal:** when `page === 'shutdown'`, add
  `shutdown-mode` to the `.app-shell` div; CSS lowers nav/header opacity and
  deepens the backdrop. Leaving the page removes it.
- `Nav.jsx`: ONE nav entry: `{ id: 'journal', label: 'Journal', short: 'Jrnl',
  icon: '☾', section: 'system' }` (+ append to `MOBILE_MORE`). Shutdown is
  reached from the Journal page's "Close tonight →" button, the Command nudge,
  and Cmd+K. Add BOTH pages to `CommandPalette`'s `PAGES` list
  (`journal: 'journal diary memory look back'`, `shutdown: 'shutdown close the
  day tonight'`).
- **Evening nudge (the habit engine):** on Command, after 21:00 local, if
  `journal_day(now)` isn't closed, render one quiet dismissible line : 
  `Close the day →` (links `#shutdown`). Dismissal writes
  `localStorage['shutdown-nudge:<date>'] = '1'` so the 15s poll can't resurrect
  it; it returns tomorrow. Never a modal, never red. Command already fetches
  nothing new: add `closed_today` cheaply by having the nudge call
  `GET /api/journal?limit=1` once on mount after 21:00 only.

### The surface
- Dimmed shell; one centered blank `<textarea>`, autofocused, generous
  line-height, faint placeholder `tonight…` and nothing else. No stats, no nav
  chrome, no color.
- Beneath the box: **`+ photo / video`** (hidden `<input type="file"
  accept="image/*,video/*">`); picking a file shows a small thumbnail (or
  `<video preload="metadata">`) with an ✕ to remove before saving. One file.
- One **`Close the day`** button (disabled until non-whitespace text). On press:
  `POST /api/journal` then, if a file is staged, `POST .../{id}/media`.
- Always-visible quiet line: `🔒 Only you, the team sees only that you closed
  the day.`
- **Close delight (committed):** text settles → a slow exhale (soft expanding
  ring, ~1.2s, motion lib + existing tokens) → resolve to "**Day closed.**" with
  `N nights closed` rising gently, media thumbnail tucked into the line like a
  photo slipped into an album. Milestones (7/30/100 total) get one extra
  particle. **Reduced motion: instant swap, no particles.**
- Already closed? Show "**Day closed: add more if you like.**" over the same
  blank box (appends another entry).

### A11y
Textarea labeled "tonight's journal, private to you"; file input labeled;
focus moves to the confirmation; buttons are real `<button>`s. Existing CSS
vars only; no `--crit`.

---

## 3. Journal, the memory (Phase C: `dashboard/src/pages/JournalPage.jsx`)

Where Ian looks back. Private, calm, and genuinely browsable: this page is a
first-class goal, not an afterthought.

- **Header:** `N nights closed` (monotonic, never shames) + **`Close tonight →`**
  button (→ `#shutdown`).
- **"On this day" strip:** when `on_this_day` returns entries, a quiet card at
  the top: `On this day, 2025 : ` with the entry (and media). Absent when empty.
  This is the look-back payoff; keep it gentle, not gamified.
- **Timeline:** reverse-chronological day cards: date heading (`Tue · Jul 21`),
  the entry text, the photo (tap → full-size overlay) or video
  (`<video controls preload="metadata">`, never autoplay). Month separators as
  quiet labels. Days with no entry simply don't appear: **no gap markers, no
  "missed" placeholders**.
- **Paging:** initial 30 via `GET /api/journal`; a `More…` button uses
  `before_id` cursor. A small month `<input type="month">` jumper fetches that
  month's days via `journal_for_date` iteration server-side or a month query : 
  keep it simple: `GET /api/journal?limit=200` capped is acceptable v1 if the
  jumper is deferred; do not build a calendar heatmap.
- **Per entry:** Edit (inline textarea → PATCH), Delete (confirm once), media
  add/replace/remove (same endpoints), and **Share text with the team** : 
  confirm copy: "This sends tonight's words to your agents as a note from you.
  Your photo/video is never shared." → `POST .../share`; a shared entry shows a
  small `shared` tag.
- Empty state: "Nothing here yet. Close tonight to start your record." No guilt.

---

## 4. Agent visibility (Phase D, a boolean, never words, never pixels)

- `build_user_prompt` (physician): inject one precomputed line from
  `journal.agent_signal(...)`: `Journal: closed the day {nights_closed_7d} of
  the last 7 nights (total {total}). His words and photos are private, you
  cannot read them; never ask for their contents.` If `days_since_last_close`
  ≥ 4, append: `He hasn't closed the day in {k} days, a gentle wellbeing nudge
  is fair; never pry.`
- Chief gets the same single line (tone context for the brief), nothing more.
- No new tool, no allowlist change, no schema exposure. Shared text arrives as
  ordinary `from_role='ian'` memos, which agents already read.

---

## 5. Acceptance criteria

- [ ] `pytest` green including `test_journal.py`; the four privacy tests (§1)
      all pass, including the LAN-with-valid-token 403.
- [ ] `data/journal/` is gitignored; `git status` stays clean after an upload.
- [ ] Browser: after 21:00 unclosed → quiet "Close the day →" on Command;
      dismiss survives the 15s poll; gone once closed; returns next evening.
- [ ] Shutdown dims the shell (class toggle, not modal); write → attach photo →
      Close plays the exhale → "Day closed." with the count; **fully static
      under reduced motion**. An entry at 00:40 lands on the *previous* day.
- [ ] Journal timeline shows day cards with media; video plays on tap, never
      autoplays; "On this day" appears only when a prior-year entry exists;
      days without entries render nothing (no markers).
- [ ] Share: text-only memo `journal <date>` appears once; media never leaves
      `/api/journal/media/*`. Grep Shutdown/Journal surfaces + styles for
      `missed`, `failed`, `broke`, `--crit` → zero hits. No streak number, no
      chart, no word count anywhere.
- [ ] Mobile 375px: Shutdown box, upload, and timeline usable.

## 6. Build order

A (schema + `.gitignore` + `core/journal.py` + API + **middleware exemption +
privacy tests**) → B (Shutdown mode + nudge + upload) → C (Journal timeline +
On-this-day + share) → D (physician/chief line) → acceptance sweep → README,
IAN-SETUP.md ("your nightly Shutdown"), CLAUDE.md. Commit per phase.

## 7. Non-goals (fences, not suggestions)

- **Prompts, rotating questions, mood taps/fields, tags**, the page is blank by
  law; his words carry the feeling.
- **Any agent access to journal text or media** beyond the explicit per-entry
  text Share. No read-tool, no `/api/state` inclusion, no summarization, no
  sentiment, no "insights".
- **Analytics**: no charts, heatmaps, word counts, or completion stats. The
  timeline is a memory, not a dataset.
- **Streaks**, the rolling count cannot break; do not add one that can.
- **Phone/voice capture, LAN journal access, cloud/iCloud sync of entries or
  media**, laptop-local only this version (AirDrop is the phone→laptop bridge).
- **Media processing**: no thumbnail generation, transcoding, EXIF parsing, or
  image editing; store and serve the original file, nothing else.
- **Multiple media per entry**, albums, or galleries, one file per entry.
- **Ephemerality/auto-delete**: entries persist; deletion is manual, per entry.

## 8. Future sparks (not now)
Month-jump calendar view; a year-end "rewind" reel (Ian-only, client-side);
carry-forward line seeding tomorrow's Command; phone capture once laptop-only
proves too narrow.
