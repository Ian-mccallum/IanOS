# SPEC v34: weekly rest days

Status: **proposed**. Supersedes SPEC-v6-the-corner.md §1 ("Bending streak,
grace stools") only. Every other phase of v6 (garden, phone capture, montage,
sleep hint) is unaffected and stays authoritative.

## 0. Why

Ian: "gym streak is inaccurate, have an option for weekends too, but give me
an option for two rest days." Decision (already made): a weekly rest-day
allowance, not a bigger stool bank.

The real bug SPEC-v6 shipped: earning a grace stool requires **5 CONSECUTIVE
confirmed weekdays**. Ian's real `streak_events` history has a handful of isolated confirms — never two days in a row, let
alone five. `bank` has been 0 every single day. Every miss since the feature
shipped has been a hard `reset`, never a `grace`. The "bending" streak has
been functionally identical to a plain reset-on-any-miss counter for exactly
the person it was built for: someone whose attendance is real but irregular.
That is the inaccuracy. "Earn forgiveness through perfection" is a contradiction
in terms for an low-friction design; the fix is to stop requiring it.

## 1. The new mechanic

Replace "bank a stool every 5 consecutive confirms" with **a fixed weekly
allowance that refills every week regardless of what happened the week
before**. Same event vocabulary, same table, same idempotency guarantee — only
the rule that chooses `grace` vs `reset` changes.

- **Settings** (new, singleton row, the `chat_prefs`/`money_prefs` pattern):
  `track_days_per_week` (5 = weekdays only, the default and today's exact
  tracked-day set; 7 = every day is trackable) and `rest_days_per_week`
  (0..6, default **2**). Both are Ian's own choice, never agent-written.
- **Tracked day**: under 5-day mode, Mon-Fri, exactly as today. Under 7-day
  mode, every day. A day outside the tracked set (Sat/Sun in 5-day mode)
  still never appears in `streak_events` at all — it is not "free", it does
  not exist for this feature, exactly like today.
- **Grace vs reset, per ISO-ish week** (this app's week starts Sunday —
  `db.sunday_of()` — reuse that convention, not a Monday-start ISO week):
  for a past tracked day with no `confirm` event, count how many `grace`
  events already exist THIS WEEK (from that week's Sunday up to, not
  including, this date). If that count is `< rest_days_per_week`: insert
  `grace` (streak holds, exactly like today's grace). If `>= rest_days_per_week`:
  insert `reset`. The count resets naturally every week because it is derived
  from events dated within the current week, not a persisted counter — this
  keeps the "truth is derivable, store events not tallies" law intact with
  zero new columns for the count itself.
- **Delete the stool bank.** `STOOL_EARN_EVERY`, `STOOL_MAX`, and the
  "toward_next_stool" counting are removed. `compute()`'s `stools` field
  becomes "rest days available in the CURRENT week so far" =
  `rest_days_per_week - (grace events already used this week)`, clamped to
  >= 0 — same shape the UI already reads (`gym.stools`), same stool glyphs,
  same "banked" visual language on BodyPage, just refilling weekly instead of
  earned by streak length. This is a two-line UI copy change
  ("earned every 5 shows" -> "N rest days this week"), not a UI rewrite.
- **`streak` itself is unchanged in shape**: still a plain count of
  consecutive tracked days that are `confirm` or `grace` (a `reset` zeroes
  it), replayed from events exactly as `compute()` does today. Only which
  days qualify as `grace` changes.
- **7-day mode enables weekend confirmation.** Today `confirm_gym()` itself
  never gates on weekday (verified: it will happily write any date) — the
  wall is entirely in `gym_streak_state()`'s hardcoded `range(5)` week array
  and BodyPage's `gym.is_weekday` button gate. Both must read the setting.

## 2. Data

`core/db.py` SCHEMA, one new table:

```sql
CREATE TABLE IF NOT EXISTS gym_prefs (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    track_days_per_week   INTEGER NOT NULL DEFAULT 5
                          CHECK (track_days_per_week IN (5, 7)),
    rest_days_per_week    INTEGER NOT NULL DEFAULT 2
                          CHECK (rest_days_per_week BETWEEN 0 AND 6),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
```

Single row, `id=1`, upserted. `db.gym_prefs(conn) -> dict` reads it, seeding
the default row on first read if absent (mirrors `chat_prefs`'s
"seed defaults on first read" pattern — check that module for the exact
idiom before inventing a new one). No migration needed for existing installs
beyond `CREATE TABLE IF NOT EXISTS`: this is a brand-new table, not an ALTER.

`core/streaks.py` changes (pure functions, still never imports `db`):
- `_is_tracked_day(d: date, track_days_per_week: int) -> bool` replaces
  `_is_weekday`.
- `compute(conn, today, *, track_days_per_week=5, rest_days_per_week=2)`:
  same replay loop, but a `grace` event's cost is no longer "decrement a
  persisted bank" — `stools` in the return dict is computed as described in
  §1, by counting this week's `grace` events among the rows already being
  replayed (no second query).
- `apply_grace(conn, today, *, track_days_per_week=5, rest_days_per_week=2)`:
  same shape, but the `kind = "grace" if bank > 0 else "reset"` line becomes
  `kind = "grace" if graces_this_week < rest_days_per_week else "reset"`,
  where `graces_this_week` is counted from events between that week's Sunday
  and the day before the miss being decided.
- Callers (`core/db.py`'s `gym_streak_state`, `agents/runner.py`'s nightly
  `apply_gym_grace` wrapper) read `db.gym_prefs(conn)` once and pass both
  numbers through. Neither function should re-read prefs internally — thread
  them as parameters, matching every other pure function in this module.

## 3. API

- `GET /api/gym/prefs` and `PATCH /api/gym/prefs` (`{track_days_per_week,
  rest_days_per_week}`, both optional, each validated against its CHECK
  before writing — a 422 on an invalid value, never a silent clamp).
- `gym_streak_state(conn)`'s `week` array is `range(track_days_per_week)`
  from that week's Sunday (5-day mode: Mon-Fri as today, unchanged order;
  7-day mode: Sun-Sat, all seven). `is_weekday` in the returned dict is
  renamed `is_tracked_day` (BodyPage already only uses it to gate the confirm
  button — rename the field, do not keep both).
- `/api/gym/confirm` is unchanged; it never gated on weekday and still
  shouldn't.
- `/api/state`'s `gym` block flows through `gym_streak_state` unchanged in
  wiring, only the underlying dict shape moves as described.

## 4. UI (BodyPage.jsx)

- A small settings affordance (a `Sheet` per SPEC-v29 — the one overlay
  primitive, popover on desktop / bottom sheet on phone) exposing the two
  numbers as a segmented control (5 or 7 tracked days) and a stepper (0-6
  rest days), backed by the new endpoint. Keep it out of the main hero; this
  is a once-in-a-while setting, not a daily surface.
- Rename the stool tooltip from "banked rest days, earned every 5 shows" to
  something reflecting the weekly refill (e.g. "rest days left this week").
- Remove the `gym.is_weekday` gate on the confirm button; gate on the
  renamed `gym.is_tracked_day` instead, so a 7-day-mode Saturday shows the
  same confirm button a Tuesday does.
- The week strip already renders `(gym.week || []).map(...)`; it needs no
  structural change to go from 5 to 7 columns, only a width/spacing check
  under `osui` — verify it does not overflow the 375px mobile frame in 7-day
  mode (7 day-cells vs 5 is a real width increase, check before shipping).
- Zero-shame law from SPEC-v6 §"Design laws" still applies without exception:
  no red, no "failed"/"missed"/"broke" copy anywhere in this surface, `reset`
  still frames as a fresh round, never failure.

## 5. Tests

- `core/streaks.py`: with `rest_days_per_week=2`, two misses in one week both
  grace, a third resets; the count resets on the following week's first miss
  (i.e. a reset in week 1 does not consume week 2's allowance — replay
  correctly resets the weekly grace count at the week boundary, not
  cumulatively). `track_days_per_week=7` grants grace/reset on a Saturday
  exactly as it would a Wednesday, and a `track_days_per_week=5` install
  never creates ANY event (confirm, grace, or reset) for a Saturday, matching
  today's behavior exactly. `rest_days_per_week=0` means every miss resets
  immediately (the strictest legal setting, still not a crash). Idempotent:
  running `apply_grace` twice for the same day inserts nothing the second
  time (existing law, must still hold).
- Migrate Ian's real fixture history (the sparse real confirm dates above) through the NEW default settings (5 tracked days, 2 rest days/week)
  and assert the resulting `streak`/`grace` counts are visibly more forgiving
  than the current shipped behavior — this is the regression test proving
  the actual bug is fixed, not just that new code runs.
- `core/db.py`: `gym_prefs` seeds sane defaults on first read; `PATCH
  /api/gym/prefs` rejects `track_days_per_week=6` (422) and accepts 5 or 7.
- `dashboard`: BodyPage's confirm button renders on a Saturday when
  `is_tracked_day` is true and hides it when false, replacing any assertion
  that used the old `is_weekday` field name.

## 6. Non-goals

- No change to `core/garden.py`, phone capture, the montage, or the
  sleep-aware Day Command hint — SPEC-v6 §§2-5 stand as shipped.
- No retroactive recomputation of historical `grace`/`reset` classifications
  when Ian changes his settings later — a settings change affects only
  future nightly runs; past events keep the classification they were given
  under whatever rule applied when they were written (consistent with
  events being an immutable log, not a derived cache to invalidate).
- No per-day custom rest-day scheduling ("always give me Wednesdays off");
  the allowance is a weekly count, not a calendar of specific pre-picked
  days. Revisit only if asked.
