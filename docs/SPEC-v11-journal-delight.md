# ianOS v11. Journal Delight (one surface, phone + laptop, photo memory)

**Status:** approved direction from Ian (2026-08-06), superseding the
**laptop-only** and **separate Shutdown page** locks in SPEC-v8.
**Audience:** an implementing agent with no prior context. Read this file +
`docs/SPEC-v8-journal.md` (data/privacy foundation that still holds) +
`.claude/skills/osui/SKILL.md`. Verify greps in §0 before coding.
**Thesis:** Journal is the one place Ian *wants* to open at night, write freely,
drop a photo of the day, close with a committed exhale, then wander a private
album of his days. Ritual and look-back are co-equal. Delight is craft
(typography, photo placement, motion, sound): never prompts, never shame.

## Locked product decisions (Ian, 2026-08-06, do not relitigate)

| # | Decision |
|---|---|
| 1 | **Phone unlocked.** Journal is reachable on the LAN/PWA with a valid token, same as Notes. Agents still never see words/media. |
| 2 | **Ritual + memory, equal.** Composer and look-back get the same design love. |
| 3 | **Dual browse.** Timeline is a **photo grid** (days with media lead); open a day → full page. |
| 4 | **Strictly blank.** No prompts, mood taps, rotating questions, ambient writing cues. Delight = motion, type, photo, sound. |
| 5 | **One surface.** Shutdown merges into Journal. Write at top; look back below. `#shutdown` redirects to `#journal`. |
| 6 | **Bigger scope, phased.** Month calendar, multi-photo, year rewind ship in later phases; schema/API leave room. |
| 7 | **Responsive.** Phone: day cards. Laptop: full-width write stage (words \| photo) + mosaic album below. |
| 8 | **Subtle sound** on close (and soft UI ticks). Respects mute / `prefers-reduced-motion`. |

Copy follows `docs/ANTI-SLOP.md` (no em dashes, no marketing fluff).

## What v8 still owns (do not weaken)

- Blank & promptless body (placeholder `tonight…` only: not a prompt).
- One primary media file per entry in Phase A-C (multi-photo is Phase E).
- Zero shame: no breakable streak, no `--crit`, no "missed"/"skipped"/"failed".
- Privacy wall layers 2-3: `/api/state` excludes journal bodies/media; agents get
  only `agent_signal` counts; Share is the single text exit.
- `journal_day` 04:00 cutoff; server-dated creates; media extension whitelist +
  512 MB stream cap; entry-id media serving (no path traversal).
- Design law: the exhale is the reward; memory without metrics.

## What v11 overturns

| v8 lock | v11 |
|---|---|
| Laptop-only; `/api/journal*` 403 off-localhost even with token | Same auth as the rest of the API: localhost free; LAN needs `IANOS_API_TOKEN` |
| Separate `ShutdownPage` + `shutdown-mode` shell | One `JournalPage`; optional `journal-mode` dim while composing |
| `journal_available: _is_local(request)` | `journal_available: true` whenever the request is authorized |
| Phone "Laptop only" empty state | Removed. Journal works on phone |
| Nav hides Journal when unavailable | Journal always listed (auth already gates the API) |

---

## 0. Current state to verify first

```bash
grep -nA12 "async def _guard" api/main.py
grep -n "journal_available\|journal is laptop" api/main.py
grep -n "PAGES = \|PAGE_TITLES\|shutdown\|journal" dashboard/src/App.jsx
grep -n "journal\|shutdown" dashboard/src/components/Nav.jsx
grep -n "shutdown\|journal" dashboard/src/pages/CommandPage.jsx
grep -n "journal_available\|laptop-only" tests/test_*.py
grep -n "laptop-only\|journal is laptop" .claude/skills/osui/SKILL.md docs/PHONE.md
```

---

## 1. Privacy wall (revised. Phase A)

### Still load-bearing

1. **`/api/state` never includes** journal entries, bodies, media paths, or
   per-entry stats beyond what already exists elsewhere. SPA fetches journal
   only from `/api/journal*`.
2. **Agents:** no journal tool; only precomputed `agent_signal` (counts).
3. **Share:** text → `from_role='ian'` memo; media never shared.

### Overturned

**Remove** the special-case in `_guard` that 403s `/api/journal*` for
non-local clients. Journal rides the normal `_auth_decision`: localhost allowed;
LAN requires a valid bearer/cookie/query token.

### `journal_available`

```python
"journal_available": True,  # authorized callers only reach /api/state
```

Or derive "authorized" if you prefer, but never `_is_local(request)`. The flag
exists so older clients degrade; new UI treats Journal as always available.

### Tests to rewrite

- **Replace** `test_privacy_journal_403_off_localhost_even_with_token` with:
  - LAN + valid token → `GET /api/journal` **200**
  - LAN + missing/invalid token → **401/403** (same as `/api/state`)
  - Unshared sentinel still absent from `/api/state`
- Update `tests/test_phone_app.py`: phone/`X-Forwarded-For` + token →
  `journal_available` is **True**; remove assertions that expect the laptop
  explainer as the happy path.
- Update `tests/test_mobile_ui.py` / `test_notes.py` copy that claims
  laptop-only forever.
- Keep `test_privacy_runner_has_no_journal_tool`.

### Docs to update in the same PR

- `.claude/skills/osui/SKILL.md`, strike "journal is laptop-only, permanently"
- `docs/PHONE.md`, journal works on phone with token; still private from agents
- `IAN-SETUP.md` / `CLAUDE.md` if they still say laptop-only for journal
- Leave `docs/SPEC-v8-journal.md` intact as historical; this file is the new law

---

## 2. Experience, one surface (Phase B)

### Information architecture

```
#journal  (only Journal route that matters)
├── Composer (tonight)          ← was Shutdown
│   ├── blank textarea
│   ├── + photo / video (one)
│   └── Close the day
├── On this day (when present)
├── Browse
│   ├── phone (<900px): day cards
│   └── laptop (≥900px): photo days
└── Day detail (hash or in-page)
    └── full entries + media + edit/share/delete

#shutdown → redirect to #journal (compose focused)
```

### Composer (top of Journal)

- Same blank law: placeholder `tonight…`, no questions.
- When the textarea is focused (or body non-empty), add `journal-mode` to
  `.app-shell`, same dim as old `shutdown-mode` (opacity ~0.22 on nav/header).
  Leaving focus with empty body clears the class; after a successful close, keep
  a brief ma then clear.
- Media preview: larger on laptop (hero thumb under the box); compact on phone.
- Primary action **Close the day** in the thumb zone on phone (sticky bottom
  bar inside the composer, ≥44px, safe-area aware).
- Quiet privacy line stays: `Only you, the team sees only that you closed.`
- Already closed tonight: eyebrow `Day closed, add more if you like.` Same box.

### Close ritual (Teller + Adrià + Miyazaki)

Sequence (interruptible; skip to end under `prefers-reduced-motion`):

1. **Pledge**: button press, text settles (opacity breath).
2. **Turn**, soft expanding ring (~1.2s); **subtle close sound** (§4).
3. **Prestige**, confirmation line (`Day closed.` / rotate existing
   `CLOSE_LINES`); nights count rises; if a photo was attached, its thumbnail
   **flies into** the top of the browse list (layoutId / FLIP) as if slipped
   into an album.
4. **Ma**: ~1.2s stillness; then composer clears and browse is visible. No
   forced navigation.

Milestones (7 / 30 / 100 total nights): one extra soft particle burst, wonder,
not confetti cannons. Reduced motion: instant swap, no particles, no sound.

### Browse, phone: day cards

At `max-width: 899px`:

- Vertical list of **day cards** (~88-120px tall).
- Left (or full-bleed background): cover = first photo that day, or quiet
  gradient if text-only.
- Right/stack: `Tue · Jul 21`, one-line snippet (first entry, ~90 chars),
  optional small video badge.
- Tap → day detail.
- Month label separators (quiet). No gap markers for unclosed days.
- Targets ≥44px; no Edit/Share/Delete on the card (those live in day detail).

### Browse, laptop: photo days

At `min-width: 900px`:

- Journal uses the full main column.
- **Composer stage:** textarea and media sit **side by side** (words ~60%, photo
  panel ~40%). Writing area is tall (≥360px; ≥420px at 1280+). Photo preview
  fills the panel height so it is actually visible.
- Album mosaic stacks **below** the composer (2-up / 3-up), not beside a skinny rail.
- Click a day → detail with words + large media side-by-side when a photo exists.

### Photo grid mode (dual browse, locked #3)

Toggle in the browse header: **Days** | **Photos**.

- **Days** = day cards / photo days (above).
- **Photos** = masonry/grid of every entry that has `media_kind` set; tap opens
  that day (scroll to entry). Text-only entries omitted here, they live in Days.

Default: **Days**. Remember last choice in `localStorage['journal-browse']`.

### Day detail

- Full-screen-ish within `.page-content`: back chevron → browse.
- Date as title (`Tuesday · July 21`).
- All entries for that date (multiple thoughts OK).
- Media large; video `controls` `preload="metadata"` never autoplay.
- Per entry: Edit, media add/replace/remove, Share (confirm copy unchanged),
  Delete with **impossible undo** (soft remove + toast Undo 8s, no
  `window.confirm` for delete).
- On this day strip can appear here too when viewing "today" and prior years exist.

### Empty states

- No entries ever: composer only + quiet `Your record starts when you close
  tonight.` (no apology).
- Photos tab with no media: `Photos appear when a night has one.`

### Routing / nav

- Keep `'shutdown'` in `PAGES` only as a **redirect**: `usePage` or App render
  maps `shutdown` → `journal` and sets `location.hash = 'journal'`.
- Cmd+K: one entry "Journal" (include keywords `shutdown close tonight`); remove
  or alias the separate Shutdown row.
- Command evening nudge: `Close the day →` navigates `#journal` (optionally
  `?focus=1` or a ref callback to focus the textarea).
- Nav: Journal always shown; drop `journalAvailable` hide logic (or leave the
  prop always true for one release).

### App shell

- Replace `page === 'shutdown' ? ' shutdown-mode'` with a state/callback from
  Journal: `journalComposing` → `journal-mode` class (CSS can alias
  `.journal-mode` to the old `.shutdown-mode` rules).
- Swipe disable: treat `journal-mode` like old shutdown (don't swipe away mid-write).

---

## 3. API additions (Phase B-D)

### Existing endpoints, keep

All v8 `/api/journal*` routes remain. Phone clients use them with the cookie/token.

### New / extended

```
GET /api/journal?limit=&before_id=&view=entries|days
```

- Default `view=entries` (current shape) for back-compat.
- `view=days` returns `{ days: [{ date, snippet, cover_entry_id, cover_kind,
  entry_count, has_media }], stats, on_this_day }`, one row per closed date,
  cover = first entry that day with media else null. Enables photo days / cards
  without N+1.

```
GET /api/journal/month/{yyyy-mm}
```

- Returns `{ month, days: { "2026-08-01": { closed: bool, has_media: bool,
  entry_count }, ... } }` for every calendar day in that month.
- Closed days only carry truthy flags; unclosed days may be omitted or
  `{ closed: false }`: **UI never renders shame markers**; calendar only
  highlights closed days softly.

```
GET /api/journal/day/{date}
```

- Already exists; day detail uses it. Ensure it returns full entries + media
  fields.

### Multi-photo (Phase E, schema ready, not required for B)

When implementing Phase E:

```sql
CREATE TABLE IF NOT EXISTS journal_media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    media_path  TEXT NOT NULL,
    media_kind  TEXT NOT NULL CHECK (media_kind IN ('photo', 'video')),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

Until then, keep `journal_entries.media_path` / `media_kind` as the single
attachment. Phase E migrates existing rows into `journal_media` and leaves the
columns as a denormalized "cover" for list queries.

### Year rewind (Phase F, client-first)

- Ian-only, client-side reel of the year's cover photos + dates.
- No agent visibility. No share-out. Spec in a follow-up; leave a stub button
  hidden until ≥12 closed days with media (or behind a comment).

---

## 4. Sound (Phase C)

`dashboard/src/lib/journalSound.js`. Web Audio API, no asset files:

| Event | Sound |
|---|---|
| Close the day | Soft low sine exhale (~180-120Hz glide, ~400ms, low gain) |
| Photo attach | Tiny high tick (~2-3ms) |
| Undo restore | Soft upward tick |

Rules:

- `localStorage['journal-sound'] !== '0'` default on; toggle in Journal header
  (icon only, no settings page).
- Skip entirely if `matchMedia('(prefers-reduced-motion: reduce)')` **or**
  document/`navigator` indicates mute preferences if available.
- Never autoplay on page load. Only on Ian-initiated gestures.
- Gain ≤ 0.08, peripheral, not a notification.

---

## 5. Visual / motion law (osUI + delight)

- Mobile-first (375px). Laptop photo days are the enhancement.
- Motion budget: 200ms state, 320ms surface; close ring may run 1.2s once.
- Transform/opacity only. Honor `prefers-reduced-motion`.
- `--crit` banned. No completion %, no streak that can break, no word counts,
  no heatmaps that look like guilt calendars, month view shows soft dots on
  closed days only.
- Futuristic restraint (L8): deep near-black, one accent, hairline borders,
  generous ma. Photo is the texture; no purple glow chrome.
- Safe-area insets on sticky composer actions (L9).
- Existing `motion` package (already in Shutdown), reuse; do not add GSAP.

### Typography

- Body: existing UI sans for chrome; journal entry body gets slightly more
  generous `line-height` (1.65-1.75) and comfortable measure (~36-42rem on
  laptop).
- Dates: quiet mono or small-caps feel via letter-spacing, match ianOS tokens,
  don't invent a third font family unless already in `styles.css`.

---

## 6. Component map

```
dashboard/src/pages/JournalPage.jsx         : orchestrator (composer + browse + detail)
dashboard/src/components/journal/
  Composer.jsx                              : blank write + media + close
  DayCard.jsx                               : phone card
  PhotoDay.jsx                              : laptop hero day
  PhotoGrid.jsx                             : media-only grid
  DayDetail.jsx                             : full day
  MonthStrip.jsx                            . Phase D calendar jumper
  CloseRitual.jsx                           : ring + line + ma (optional extract)
dashboard/src/lib/journalSound.js
dashboard/src/styles.css                    : .journal-* / .journal-mode
```

Deprecate `ShutdownPage.jsx` after redirect works (delete file; update App
imports). Keep CSS class names `.shutdown-*` temporarily as aliases if needed,
then rename to `.journal-composer-*` in the same pass when touching styles.

---

## 7. Phased build order

| Phase | Deliverable | Done when |
|---|---|---|
| **A** | Phone unlock + test/doc rewrites | LAN+token 200; state still clean; docs not lying |
| **B** | One surface + day cards / photo days + day detail + `#shutdown` redirect | Usable on 375 and ≥900; ShutdownPage gone |
| **C** | Close ritual prestige (photo fly-in) + sound + impossible undo delete | Reduced-motion safe; sound toggle |
| **D** | Month endpoint + MonthStrip jumper | Jump to month; no shame empty cells |
| **E** | `journal_media` multi-photo | Multiple photos per entry; cover for lists |
| **F** | Year rewind reel | Client-only; gated until enough media |

Ship A→C in the first implementation pass. D can land if time; E/F scaffold in
spec only until called.

---

## 8. Acceptance criteria

- [ ] `pytest` green: privacy state tests, agent no-tool, **LAN+token journal 200**,
      invalid LAN token denied.
- [ ] Phone (375×667): composer, day cards, day detail, close, fold + thumb zone.
- [ ] Laptop (≥900): sticky composer + mosaic album; ≥1280 uses 3-up; detail splits media.
- [ ] Photos / Days toggle works; preference persists.
- [ ] `#shutdown` lands on Journal compose.
- [ ] Close: ring + sound + count; reduced motion = instant silent swap.
- [ ] Delete: toast Undo restores; no blocking confirm.
- [ ] Grep Journal surfaces for `missed|failed|broke|--crit` → zero.
- [ ] Unshared journal text/media absent from `/api/state`.
- [ ] `docs/PHONE.md` + osui skill no longer claim laptop-only journal.
- [ ] Cache-bust verify after build (service worker).

---

## 9. Non-goals (fences)

- Writing prompts, AI summaries, sentiment, "insights".
- Agent read access to journal text/media.
- Cloud sync of journal media off the Mac (LAN/PWA to the Mac is fine; iCloud
  backup of `data/journal/` is out of scope).
- Breakable streaks, heatmaps-as-guilt, word-count trophies.
- Autoplay video; background music.
- Replacing Notes or Memory with Journal.

---

## 10. Delight checklist (Teller / Adrià / Miyazaki)

- **Teller:** Close → photo lands in the album (prestige). Delete → Undo without
  asking first.
- **Adrià:** Layers on close, visual ring, sound, count, photo tuck, milestone
  particle.
- **Miyazaki:** Ma after close; empty nights are quiet absence; day cards feel
  like lived-in prints, not a SaaS feed.

---

## 11. References

- `docs/SPEC-v8-journal.md`, schema, media rules, agent_signal
- `docs/SPEC-v10-osui.md` + `.claude/skills/osui/SKILL.md`, mobile law
- `docs/SPEC-v12-lock-screen.md`, PWA Face ID / password before any UI
- `docs/PHONE.md`, phone install + journal on phone
- Existing `motion/react` usage in Journal composer / lock
- `tests/test_journal.py`, privacy suite to extend, not gut
