# ianOS v6: "The Corner" (low-friction dorm health)

**Status:** ALL PHASES SHIPPED. 2026-07-21. 75 tests green. Live-verified:
grace holds the chain (5 confirms → miss → streak 6, not 0), garden renders
6 stages with no red/labels, `/api/quick` routes every field, token middleware
gates the LAN, and a real coach run produced a 76-word four-beat montage.
**Original approved direction from Ian's brainstorm (2026-07-21).**
**Audience:** an implementing agent with no prior context. Read this file + the
repo; verify every "current state" claim with the greps given before coding.
**Thesis:** Ian is a freshman living in a UIUC dorm (move-in in the fall,
see `core/pillars.py MOVE_IN_DATE`). Health tracking survives ONLY if capture is
zero-or-one tap, misses never reset progress to zero, and rewards pay out as
delight/story rather than numbers. Four features, one loop:

1. **Bending streak**, grace "corner stools" so a missed day never kills the chain.
2. **The Garden**, a living visual on the Body page that grows/wilts from data.
3. **Phone capture**, iPhone Shortcuts → API over dorm wifi (token-gated).
4. **The Montage**. Rocky's Sunday 150-word training-montage recap.

Plus one small brain: **sleep-aware day command** (House reshapes tomorrow
instead of shaming yesterday).

**Design laws (apply to every decision):**
- Zero shame. No red for a missed workout; wilt, never die; forgive by default.
- Zero typing where possible; one tap otherwise.
- Delight is committed or absent (Teller): every reward moment fully animated,
  `prefers-reduced-motion` honored everywhere.
- Everything computed from existing tables; no new manual rituals.

---

## 0. Current state to verify first

```bash
grep -n "gym" api/main.py | head          # existing /api/gym/confirm + streak calc
grep -n "gym" core/*.py | head           # where streak state lives
head -60 core/pillars.py                  # pillar model, MOVE_IN_DATE
sed -n '1,90p' dashboard/src/pages/BodyPage.jsx   # current streak UI + confirm
grep -n "workout" core/db.py | head       # health_daily has workout slug column
grep -n "coach\|physician" agents/runner.py | head  # tiers, tripwires
ls docs/SPEC-IPHONE.md 2>/dev/null        # prior iPhone/HealthKit intent
```

Facts assumed by this spec (fix the spec against reality if a grep disagrees):
gym confirm endpoint + weekday streak exist and BodyPage renders them; wellness
logging via `POST /api/wellness` (sleep/energy/workout slug); coach (Rocky,
tripwire tier) and physician (House, daily) run via the dispatcher; briefs have
a Day Command; API binds 127.0.0.1 via `scripts/dev.sh`.

---

## 1. Bending streak, grace stools (Phase A)

### Mechanic (exact rules, implement in `core/streaks.py`, pure functions)

- Streak counts **weekdays with a gym confirm** (existing rule stands; weekends
  are free, as today).
- **Earning:** every 5 consecutive confirmed weekdays earns **1 corner stool**,
  max bank of **2**. Earned at confirm time.
- **Spending (automatic):** when a weekday passes with no confirm and a stool is
  banked, the nightly run spends one stool, marks the day `graced`, and the
  streak continues. No stool → streak resets, but the UI frames it as a new
  round ("Round 2 starts Monday"), never as failure.
- **Truth is derivable:** store events, not tallies, new table
  `streak_events(id, date UNIQUE, kind CHECK(kind IN ('confirm','grace','reset')), created_at)`;
  streak/stools are computed by `core/streaks.compute(conn, today)` →
  `{streak, stools, graced_dates, last_event}`. Migrate the existing streak
  storage to this (write a one-time migration from whatever `/api/gym/confirm`
  writes today; keep that endpoint's contract).
- Grace is applied by the **dispatcher/nightly run** (a pure-Python step before
  agents, alongside tripwires. NOT an LLM decision), and Rocky's wake prompt
  gets `You spent a stool for yesterday. Say so like a corner-man; zero shame.`

### API + UI

- `GET /api/gym` (or extend `/api/state.gym`) now returns
  `{streak, stools, week: [{date,label,confirmed,graced,future}], confirmed_today, is_weekday}`.
- BodyPage: stools render as 0-2 small stool glyphs beside the streak number
  with a title ("a banked rest day, earned every 5 shows"); a `graced` day in
  the week strip shows a distinct mark (◐, `--warn`-tinted, never `--crit`).
- Confirm button delight (Adrià layers, reuse `motion` lib + existing tokens):
  press → spring scale → checkmark draws in → streak number springs up →
  every 5th confirm, the new stool *slides onto the bench* and the toast reads
  "Stool earned. Bank: N." Milestone confirms (streak 10/25/50) get a one-off
  particle burst (extend the existing `.gym-burst`). All gated on
  `useReducedMotion` (instant swap, no particles).

### Tests: `tests/test_streaks.py`
- 5 confirms → 1 stool; 10 → 2; 11th earns nothing (bank cap).
- Miss with stool → graced, streak continues, stool decremented.
- Miss with no stool → reset event; compute() returns streak reflecting new round.
- Weekend misses never grace/reset. Idempotent nightly application (running the
  grace step twice for the same date inserts nothing).

---

## 2. The Garden (Phase B)

A single generative organism on the Body page. **Never a guilt object.**

- **State fn** `core/garden.py: garden_state(conn, today) -> {stage: 0..5, mood: 'thriving'|'steady'|'thirsty', spark: bool}`
  computed from the last 14 days: stage from count of "alive days" (gym confirm
  OR any wellness log OR ≥8k steps), mood from the last 3 days, `spark` true on
  a day that set a 14-day best. Pure + unit-tested (`tests/test_garden.py`,
  table-driven).
- **Rendering:** inline SVG component `dashboard/src/components/Garden.jsx` : 
  a hand-drawn-feeling plant with 6 growth stages (stage = which paths render),
  drawn in existing palette vars only. Mood maps to subtle animation:
  thriving = slow leaf sway (breathing variant, ~4s), steady = still,
  thirsty = a single drooped leaf + slightly desaturated (CSS filter): **no
  red, no text nagging**. `spark` fires one firefly particle (once per mount).
  Reduced motion: static SVG per stage/mood.
- **Ma (Miyazaki):** the garden sits beside the streak hero with generous
  `--s6` spacing and NO label, no tooltip, no number. Ian is told once (in the
  Montage §4 copy and IAN-SETUP) that it reflects his last two weeks; after
  that it's simply *there*.
- Wilting floor: stage never drops below 1 and mood recovers after any single
  alive day. The plant cannot die, that's the point.

---

## 3. Phone capture over dorm wifi (Phase C)

Goal: log from the lock screen without opening the laptop lid. The laptop must
be on the same wifi (dorm reality: usually asleep in the room, capture also
degrades gracefully, see "offline path").

### Security first (dorm wifi is shared, never ship unauthenticated LAN)
- New optional env `IANOS_API_TOKEN`. When set, FastAPI middleware requires
  `Authorization: Bearer <token>` on every `POST/PATCH/DELETE` (GETs from
  localhost stay open; GETs from non-localhost also require the token). When
  unset, the API refuses to bind non-localhost (assert in startup if host !=
  127.0.0.1 and no token).
- `scripts/dev.sh` unchanged (localhost). New `make api-lan`: generates a token
  into `.env` if absent, binds `0.0.0.0:8787`, prints the phone-setup line:
  `http://<lan-ip>:8787` + token.
- Tests: request without token → 401; with token → 200; localhost GET → 200.

### Shortcuts contract
- New endpoint `POST /api/quick` accepting the minimal union Shortcuts sends:
  `{"gym": true}` → gym confirm · `{"sleep": 7.5}` · `{"energy": 4}` ·
  `{"workout": "mma"}` · `{"steps": 9200}` · `{"note": "..."}` (→ activity
  note). One endpoint so one Shortcut handles everything; responds with a
  short human line the Shortcut can show as a notification ("Streak 12 · stool
  bank 2 · garden thriving"), capture WITH a reward payload (Teller: the
  notification is the prestige).
- Docs: `docs/SHORTCUTS.md`, step-by-step for three shortcuts (Gym ✓ /
  Sleep / Note), including Health-app automation ("when sleep sample is added
  → POST"). Reference SPEC-IPHONE.md as prior art; this supersedes its capture
  section, not its HealthKit-app ambitions.
- **Offline path:** if the laptop is unreachable, the Shortcut appends to a
  Notes/​file inbox and `docs/SHORTCUTS.md` documents the catch-up: paste into
  a `claude` session → it replays via `/api/quick`. (No new code required.)

---

## 4. The Montage (Phase D)

- **When:** Sundays, as part of coach's weekly pass (change coach frontmatter
  `tier: tripwire` → `tier: weekly, day: sun` *keeping* its existing tripwires
 : the dispatcher already supports weekly+tripwire).
- **Input (code-computed, injected into coach's Sunday prompt):** the week's
  streak events, workout mix, sleep avg, steps best, garden stage delta, and
  last week's montage title (from facts), coach narrates, never computes.
- **Output contract (in coach.md):** one memo, topic `montage: <title>`,
  priority 1, ≤150 words, structure: cold-open line → the comeback moment
  (name the actual day) → freeze-frame (ONE number) → "next week's opponent"
  (one concrete focus). Rocky voice, zero shame, no emoji spam. Also
  `write_fact` topic `training:last-montage` (title + one line) so montages
  form a saga.
- **Surfacing:** BodyPage gets a "This week's montage" card (collapsed to the
  title line; tap to read, minimalism rules from v5 stand). The chief may
  quote the montage title in Sunday's brief but never the whole thing.
- **Model:** haiku (montage quality comes from the injected numbers + prompt,
  not model size). Revisit only if flat after 3 weeks.

---

## 5. Sleep-aware day command (Phase E, small)

- Extend `metrics.compute_tradeoff_hints` (or the chief prompt builder) with a
  code-computed `sleep_debt` hint: last night < 6h or 3-day avg < 6.5h →
  hint "Sleep debt: last night Xh. Day command should schedule demanding work
  after 10am and gym in the afternoon; do not schedule a 7am anything."
- House's daily prompt gets the same numbers with instruction: adapt, don't
  scold, propose the *reshaped* plan, never a lecture.
- Test: seed a 5h night, run chief prompt builder, assert the hint text is
  present (string test, no LLM).

---

## 6. Acceptance criteria

- [ ] `pytest` green including new `test_streaks.py`, `test_garden.py`, token
      middleware tests, `/api/quick` tests (each field routes correctly; bad
      payload 400; response contains streak line).
- [ ] Simulated fortnight (seed script or test): confirms Mon-Fri ×2 → streak
      10, stools 2; skip a Tuesday → graced, streak continues; skip two more
      with empty bank → reset event and UI copy shows "Round 2".
- [ ] BodyPage in browser: stools visible, graced day renders ◐, confirm
      delight sequence plays and is fully static under reduced motion.
- [ ] Garden renders all 6 stages (storybook-style test page or prop-forcing in
      dev) with no red anywhere and no text labels.
- [ ] `make api-lan` without token in `.env` generates one; `curl` from another
      device with token succeeds, without token → 401.
- [ ] One real Sunday run (or forced `--role coach --weekly`) produces a
      montage memo ≤150 words with the four beats, and BodyPage shows it
      collapsed-by-default.
- [ ] Zero-shame audit: grep UI strings for the words "failed", "missed",
      "broke" in Body/streak/garden surfaces → none; `--crit` color absent
      from streak/garden components.
- [ ] Nothing new added to Ian's daily required actions (capture is optional
      sugar on top of the existing confirm button).

## 7. Non-goals

- Wearable integrations beyond Apple Health/Shortcuts; calorie/macro logging
  by hand; any food photo analysis (revisit as a `/sync` command later).
- Dining-hall menu copilot: **future spec**: UIUC NetNutrition scraping needs
  endpoint verification; do not build speculatively. Listed here so the idea
  isn't lost: nightly menu fetch → "3 plays at the dining hall" in the brief.
- NFC-tag logging, body-double timer, social-battery tracking (future sparks).
- Public sharing of montages/garden; competitive/leaderboard mechanics: the
  only opponent is last week's Ian.
- Exposing the API beyond the LAN (no tunnels, no port-forwarding).

## 8. Build order

A (streak engine + migration + tests) → B (garden fn + SVG) → C (token
middleware + /api/quick + SHORTCUTS.md) → D (montage) → E (sleep hint) →
acceptance sweep → update IAN-SETUP.md ("set up your three Shortcuts",
"what the plant means") and README. Commit per phase.
