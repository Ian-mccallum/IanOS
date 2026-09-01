# ianOS v3. UX Overhaul Specification ("Calm Instrument")

**Status:** spacing/type tokens shipped; pillar navigation and Command redesign → see [SPEC v5](SPEC-v5-ian-personal-dashboard.md) (shipped 2026-07-20). **The mobile half of this spec is superseded by [SPEC-v10 osUI](SPEC-v10-osui.md)**, which re-authored the interface at 375px.
**Audience:** an implementing agent with no prior context. Every change is
concrete and file-scoped. Audit evidence was measured against the live app at
1440×900 on 2026-07-15.
**Scope:** `dashboard/src/**` only. No API, schema, or agent changes.

---

## 0. The diagnosis (why this spec exists)

The dashboard's color/mood is right, but the composition undermines it. Audit
findings, all measured (not vibes):

| # | Finding | Evidence |
|---|---------|----------|
| D1 | **No spacing system.** 14 distinct spacing values (2-32px, every even number) used interchangeably; `gap: 10px` vs `12px` vs `16px` appear at the same semantic level. | styles.css throughout |
| D2 | **No type scale.** ~15 font sizes incl. six 1px-apart steps (13/14/15/16/17/18). Hierarchy is flat because nothing is decisively bigger. | styles.css |
| D3 | **Page width lottery.** Content column jumps per page: home 920 → goals 1100 → inbox 920 → log 720 → money 720 → memory 1100 → partner 560. The content edge moves on every nav click. | measured |
| D4 | **Full-width eye ping-pong.** Goals rows put label far-left and value far-right of an 1100px row (~900px of gap); meters stretch edge-to-edge. Scanning a goal requires a full screen-width eye sweep per row. | measured |
| D5 | **Dead space.** Home: 296px empty right of content; brief text is 610px inside a 920px card. Hero card spends 159px of height on one sentence. | measured |
| D6 | **Five card vocabularies.** `.glass-card`, `.panel`, `.log-section`, `.proposal`, `.memo` each with its own padding (12×14, 16×18, 16, 20, 18×20, 24×26, 28×32) and chrome. | styles.css |
| D7 | **Four competing section-label styles** (`.section-label`, `.panel-tag`, `.money-eyebrow`, `.command-hero-label`): the uppercase-eyebrow-on-everything pattern. | styles.css |
| D8 | **Banned patterns (detector-confirmed):** side-stripe accent (`.day-command` `border-left: 3px`), gradient text ×2 (`.nav-title` L125, partner name L1085), layout-property animation (`.meter-fill` `transition: width` L626). | detect.mjs |
| D9 | **Invisible affordances.** `.edit-glyph` is `opacity: 0` until hover and 23×21px, goals look uneditable; unusable on touch. Focus ring is `rgba(accent, 0.2)`, effectively invisible for keyboard users. | styles.css L585-597, L462-466 |
| D10 | **Permanent form noise.** Every inbox proposal renders a full-width note input + two 35px buttons whether or not you're deciding it; 3 proposals = 3 identical dead form rows. | measured |
| D11 | **Unclamped memo bodies.** `.memo p` is `pre-wrap` with no clamp; real agent memos run 400-900 chars (Nick Fury's nightly memo), producing wall-of-text feeds. Seed data (≤72 chars) hides this. | App.jsx MemoFeed |
| D12 | **Redundancy.** Day Command renders in the home hero AND inside the brief markdown. Some pages stack page-title + panel-title + card-title three deep. | measured |
| D13 | **Contrast at the floor.** `--muted` (#6b7894) on `--bg` ≈ 4.5:1, passes on the page background but **fails on lighter glass surfaces**, where it's used for 11-12px labels. | computed |
| D14 | **Misc.** Sleep number input is 720px wide for a 3-char value; wellness "worked out" checkbox floats detached right; red `.nav-badge` (crit color) signals false urgency for routine pending counts. | measured |

Nielsen total from the audit: **23/40**, biggest losses on Consistency (1/4),
Recognition (2/4), Minimalism (2/4), Flexibility (2/4).

**Design principle for every decision below** (from PRODUCT.md): Ian reads this
at night in ≤2 minutes. Numbers are the interface. Urgency must be earned.
Chrome serves data. When in doubt, remove.

---

## 1. Design tokens (Phase A, foundation)

All changes land in `dashboard/src/styles.css` `:root`. **Do not change any
color values.** Add the following and then migrate every rule to them.

### 1.1 Spacing scale. 4px base, 7 steps

```css
--s1: 4px;   /* icon↔text, chip padding-y */
--s2: 8px;   /* related items in a row, chip gaps */
--s3: 12px;  /* items within a group (list rows, form fields) */
--s4: 16px;  /* card padding, group↔group inside a card */
--s5: 24px;  /* card↔card, section padding */
--s6: 32px;  /* section↔section, page top/bottom */
--s7: 48px;  /* page-level breathing room (rare) */
```

**Migration rule:** every existing `margin`/`padding`/`gap` maps to the nearest
step. 2→4 · 6→4 or 8 (judgment: tight pairs→4) · 10→8 or 12 (within-group→12) ·
14→16 · 18→16 · 20→24 · 26→24 · 28→32. After migration, `grep -E
"(gap|padding|margin)[^:]*: *[0-9]+px" styles.css` must only show scale values.

**The one ratio that matters:** space *within* a group ≤ half the space
*between* groups. Rows inside a goal section sit at `--s3`; sections separate at
`--s6`. Today they're 8 vs 16, too close to read as different levels.

### 1.2 Type scale. 6 steps + 2 numeric display sizes

```css
--t-xs:   12px;  /* meta, timestamps, chips, section labels */
--t-sm:   13px;  /* secondary body, memo/reasoning text */
--t-base: 14px;  /* primary body, the default */
--t-md:   16px;  /* card titles, prop-action, day command */
--t-lg:   20px;  /* page title (was 26), key figures */
--t-xl:   28px;  /* the single hero figure of a page */
--n-hero: 40px;  /* numeric hero only (goal-hero count), mono, tabular */
```

**Kill list:** 10px, 11px, 15px, 17px, 18px, 22px, 26px, `1.35rem`, `1.5rem`,
`2rem`, and the hero `clamp()`. Every one maps to a neighbor: 10/11→`--t-xs`,
15→`--t-base` or `--t-md` (titles up, body down), 17/18→`--t-md`,
22/26/1.35rem→`--t-lg`, 1.5rem/2rem→`--t-xl`. Fixed rem/px, no fluid type : 
this is product UI at a desk, not a marketing page.

**Weight rules:** hierarchy comes from *size + color*, not from sprinkling
`font-weight: 600` everywhere. Body text is 400. Titles 600. Nothing is 700
except the page's single hero figure. `--t-xs` labels use `--muted` +
`letter-spacing: 0.04em` and are the ONLY uppercase text in the app (see 1.4).

### 1.3 Layout constants

```css
--content-w: 920px;   /* ONE content width, every page */
--label-col: 180px;   /* left column for label+value rows (goals, money) */
--meter-w: 220px;     /* fixed meter width, meters never stretch full-bleed */
```

`.page-stack`, `.page-wide`, `.money-page` (720), `.partner-page` (560),
`.log-page` (720) all collapse to `max-width: var(--content-w)`. Delete the
per-page widths. The partner page keeps its own *internal* card design but sits
in the same column. **Acceptance:** navigating all 8 pages, the content's left
and right edges never move.

### 1.4 One label vocabulary

Keep exactly one small-label style, `.section-label` (rename usages):
`--t-xs`, 600, `--muted`, uppercase, `letter-spacing: 0.04em`,
`margin: 0 0 var(--s3)`. Migrate `.money-eyebrow`, `.command-hero-label`,
`.stat-pill-label`, `.panel-tag` (panel-tag keeps lowercase, it's metadata,
not a label; give it `--t-xs` `--muted` no-caps). Uppercase appears **only**
on `.section-label` and `.chip`, nowhere else.

### 1.5 One card vocabulary

`.card` = current `.glass-card` skin (border, radius 14, glass bg, blur,
shadow). Padding standardizes to `var(--s4) var(--s5)` (16×24, wait, no:
16 vertical, 20 horizontal reads better; use `--s4)` all around with `--s5`
horizontal on wide cards. **Decision: `padding: var(--s4) var(--s5)` =
16px 24px for page-level cards; `--s3 var(--s4)` = 12px 16px for list-item
cards (memo, proposal, fact, position).**

- `.panel`, `.log-section`, `.money-card` → become `.card` + a modifier for
  their accent border colors only.
- `.memo`, `.proposal`, `.fact-card`, `.stat-pill`, `.money-position` →
  `.card-item` (flat: `background: rgba(0,0,0,0.22)`, radius `--radius-sm`,
  border transparent → `--glass-border` on hover). List items are NOT glass
  cards, no blur, no shadow. Cards never nest inside cards with full chrome;
  a `.card-item` inside a `.card` is the only sanctioned nesting.

---

## 2. Global fixes (Phase A, continued)

### 2.1 Kill the banned patterns (detector findings)

1. `.day-command` (styles.css ~L989): delete `border-left: 3px solid` and the
   asymmetric radius. Replace: full `1px solid rgba(110,168,255,0.35)` border,
   radius `--radius-sm`, keep the tinted background. The tint + border carry
   the emphasis; the stripe goes.
2. `.nav-title` (~L125): delete the gradient/`background-clip: text`. Solid
   `color: var(--ink)`; the glowing `⬡` mark already carries brand color.
3. Partner name gradient (~L1085): same treatment, solid `--ink` (or the partner
   pink as a solid). No `background-clip: text` anywhere in the file.
4. `.meter-fill` (~L626): replace `transition: width` with
   `transform-origin: left; transition: transform 0.4s ease-out` and drive
   fill via `transform: scaleX(ratio)` (Meter component passes
   `style={{transform: `scaleX(${pct/100})`}}`, width stays 100%).

### 2.2 Focus, targets, and touch

- Focus ring: `outline: 2px solid var(--accent); outline-offset: 2px` : 
  solid, visible, offset so it never blends into the border. Applies to every
  interactive element.
- Minimum interactive target: 36px height desktop (buttons currently 35 : 
  bump `.btn` padding to `10px 16px`), 44px on the log page taps (already 85 ✅).
- `.edit-glyph`: never `opacity: 0`. Rest state `opacity: 0.45`, hover/focus
  `1`. Size min 28×28. It must be *findable*, not discovered by accident.

### 2.3 Contrast floor

`--muted` may only be used at `--t-xs`/`--t-sm` **on the page background or
`.card` glass**. On `.card-item` (lighter composite), meta text uses `--dim`.
Concretely: `.memo header`, `.money-txn-date`, `.fact-kind` switch from
`--muted` to `--dim`. (Zero color *values* change, only which token is used
where.)

### 2.4 Nav badge semantics

Red = breached/urgent only. `.nav-badge` default becomes accent-tinted
(`rgba(110,168,255,…)`, `--accent` text). It turns crit-red **only when** a
priority-3 memo from tonight or a deadline <7d exists (pass a `level` prop from
App state: `state.memos.some(m => m.priority === 3)`). The partner pink badge
stays pink.

---

## 3. Per-page restructuring (Phase B)

### 3.1 Home ("Command"), the 2-minute read

Current: hero sentence (159px) → 4 stat pills → brief card (with Day Command
repeated inside). Order is right; proportions and redundancy are wrong.

1. **Merge hero + stats into one `.card`:** Day Command as `--t-md` 600 text
   under a `.section-label` "Today's plan", then a **single row** of 4 stat
   items (not 4 bordered pills, remove per-pill borders; separate with `--s5`
   gaps and a 1px divider above). Label `--t-xs` muted over value `--t-lg`
   mono. Cuts ~80px of chrome and one card border.
2. **Strip `## Day Command` from the brief render:** in the `Md` component's
   consumer for the brief (HomePage), pre-process the body: drop the "Day
   Command" heading + its line (regex on the markdown before render). The hero
   is its home. (Agent-side prompt change is out of scope; strip in UI.)
3. **Brief card fills the column:** `.md { max-width: 68ch }` stays for
   *paragraphs*, but the card should not look 1/3 empty, set `.md` to center
   or, better, keep left-aligned and tighten the card to fit content:
   `.brief-card { max-width: fit-content; min-width: 100% }` is wrong, keep
   card full-width, and instead let brief *tables* span full card width while
   prose wraps at 68ch. Add `--s4` padding consistency.
4. Brief typography: `.md h2/h3` get `--t-md`/`--t-base` + `--s5` top margin
   (section separation *inside* the brief), `--s2` bottom. `.md p, .md li`
   at `--t-base` `--dim` with `--ink` strong. Line-height 1.6.
5. The stale chip ("outdated") moves from the card corner into the panel-tag
   position beside "Daily brief" and gains the warn color when stale, status
   should be readable at a glance, not `--t-xs` muted.

### 3.2 Goals, kill the ping-pong

The core fix: **a goal row becomes a fixed 3-zone grid** : 

```
grid-template-columns: minmax(0, 1fr) var(--meter-w) 140px;
/* name+context | meter (fixed 220px) | value, right-aligned mono */
```

- Name (`--t-base` `--ink`) with target/deadline context under it
  (`--t-xs` `--muted`), two-line left zone, so label and its meaning stay
  together instead of scattering across the row.
- Meter fixed at 220px, vertically centered. Never full-bleed.
- Value zone right-aligned mono `--t-base`; secondary stat (`57 last 7d`)
  under it at `--t-xs`.
- Row padding `--s3 0`, 1px `--glass-border` divider between rows (dividers,
  not floating rows, a table, because this IS a table).
- Deadline rows: same grid; meter zone holds the countdown chip; status text
  right zone.
- `.domain-zone` becomes a `.card` per domain (currently borderless zones with
  a 3px `domain-bar`, keep the bar, it's 16px tall and reads as a legend tick,
  not a side-stripe on a card).
- Burn block keeps its month history but the mini-track also gets `--meter-w`.
- Delete the magic `padding-right: 24px` (edit glyph gets its own 28px grid
  column on `.editable` rows instead of overlaying content).

### 3.3 Inbox, decisions, not forms

1. **Collapse the note input.** Default proposal card: header (id · codename ·
   kind · time) + action (`--t-md` 600) + reasoning (`--t-sm` `--dim`,
   clamped to 3 lines with an inline "more" toggle) + one row:
   `[Approve] [Reject] [+ note]`. Clicking "+ note" reveals the input
   (autofocused) above the buttons. Three cards → three clean decision rows,
   zero dead inputs.
2. **Weight the actions:** Approve becomes the filled action : 
   `background: rgba(74,222,128,0.15)`, border as today, weight 600. Reject
   stays ghost-outline. Same size (36px), different visual priority.
3. Decided history: keep, but as `--t-xs` single-line rows under a
   `.section-label` "Decided recently", not chip-per-row shouting.

### 3.4 Notes, a feed that survives real memos

1. `.memo p`: `display: -webkit-box; -webkit-line-clamp: 3` + "Show more"
   toggle when `scrollHeight > clientHeight` (component state per memo).
   Clamped by default; a 900-char Nick Fury memo becomes a 3-line entry.
2. Memo header: codename `--t-sm` 600 colored · topic `--t-xs` `--dim` ·
   time right `--t-xs`. Priority dot stays; **add the word** for P2/P3
   (`important` / `urgent` as a `--t-xs` colored text next to the dot) : 
   never color-alone.
3. Group by day: a `.section-label` date divider ("Tonight", "Yesterday",
   then dates): the feed currently runs all days together.
4. Filter buttons: keep, bump to 32px height, `--t-xs`.

### 3.5 Memory, triage, not a museum

1. **Unconfirmed first.** Two top-level groups: "Needs your confirmation"
   (warn-tinted `.section-label`, cards sorted by days_until) then "Confirmed"
   grouped by domain. The page's job is triage; today the placeholders hide
   in domain groups.
2. **Compact confirmed facts to single-line rows** (`.card-item`, `--s3`
   padding): topic mono `--t-sm` · body truncated 1 line · kind chip ·
   countdown chip · actions on hover. Click to expand. 133px × 11 uniform
   cards → ~44px rows; page drops from 1780px to ~900px.
3. Unconfirmed cards keep the fuller layout (they need reading) + the warn
   border they already have.

### 3.6 Money

1. Merge "Chase checking" (a whole card for one number) into the Personal
   finance hero card as a third stat (Net · Portfolio · Checking, one stat
   row, same pattern as home).
2. Position rows → `.card-item` treatment, `--s3` padding, divider list.
   Symbol + name left (name truncates), value + gain right, this page's
   two-zone rows are fine at 920 since rows are short; no meter zone needed.
3. Burn card: meter gets `--meter-w`; category breakdown rows use the goals
   3-zone grid for consistency.

### 3.7 Log

1. Wellness inputs: `max-width: 140px` for sleep (number), energy row as-is.
   The workout type joins as a segmented control (`mma · lift · soccer · run ·
   rest`) using the existing `.segmented` component: replacing the orphaned
   floating checkbox (the checkbox writes `workouts=1` today; segmented writes
   `workout=<type>` which the API already accepts).
2. Group: "Sales activity" card and "Wellness" card keep 2-card layout;
   inside each, field groups separate at `--s4`, fields within a group `--s3`.
3. Disabled buttons: `opacity: 0.45` + keep the border visible
   (`border-color: var(--glass-border)`) so the button doesn't vanish.

### 3.8 Partner

Keep its personality (it's the one page allowed to be soft). Only: same
`--content-w` column, token-scale spacing, no gradient text (2.1), and task
rows adopt `.card-item` padding so it matches the app's rhythm.

---

## 4. Micro-formatting rules (apply everywhere)

1. **Numbers are mono, text is sans**, already mostly true; enforce: any
   digit the user compares (money, counts, dates in tables) gets
   `font-family: var(--mono); font-variant-numeric: tabular-nums`.
2. **Timestamps right-aligned, `--t-xs`, `--dim`** in every list header.
3. **Chips:** one size (`--t-xs`, `2px 8px`, radius 4). Kill the 10px chip
   variants (`.money-cat`).
4. **Empty states:** already good (they teach), standardize to
   `.section-label` title + `--t-sm` `--dim` body, max 46ch, `--s6` padding.
5. **Ellipsis truncation** must always pair with `title` attr (memo-topic,
   money-position-name, money-txn-desc).
6. **No new uppercase**, no letter-spacing on body text, no font-weight: 700
   outside hero figures.

---

## 5. What does NOT change

- Every color token value, the aurora canvas, the grain overlay, glass blur.
- Nav rail structure, page set, routing, motion library and its durations.
- All API contracts and component logic (except the small interaction changes
  specified: note-input collapse, memo clamp, memory grouping, workout
  segmented control).
- The mobile breakpoint behavior (a later pass; but the token migration must
  not break it, re-test at 900px and 375px).

---

## 6. Build order & verification

**Phase A (tokens + globals):** 1.1-1.5, 2.1-2.4. Pure CSS + the Meter
transform change. Verify: detector clean
(`node ~/.claude/skills/impeccable/scripts/detect.mjs --json dashboard/src`
→ exit 0); grep gates from 1.1/1.2 pass; all 8 pages screenshot without layout
breakage at 1440 and 900.

**Phase B (per-page):** 3.1 → 3.2 → 3.3 → 3.4 → 3.5 → 3.6 → 3.7 → 3.8, one
commit each, screenshot before/after per page.

**Acceptance (whole spec):**
- [ ] One content width: left/right content edges identical across all 8 pages.
- [ ] Type audit: computed font sizes in the app ⊆ {12, 13, 14, 16, 20, 28, 40}.
- [ ] Spacing audit: all gaps/paddings ∈ {4, 8, 12, 16, 24, 32, 48}.
- [ ] Detector: zero findings.
- [ ] Keyboard walk: tab through inbox → visible focus ring on every stop;
      decide a proposal without the mouse.
- [ ] A 900-char memo renders as 3 lines + "Show more".
- [ ] Memory page: unconfirmed facts appear first; confirmed facts are
      single-line rows.
- [ ] Inbox: no visible text inputs until "+ note" is clicked.
- [ ] Goals: no meter wider than 220px; label/value never more than 400px apart.
- [ ] Contrast: no `--muted` text on `.card-item` surfaces.
- [ ] `make dev` + browser console clean on all pages.

**Non-goals:** dark/light theming, mobile-first redesign, new features,
keyboard-shortcut system (listed as future: `a`/`r` to decide focused
proposal, `1-9` page nav, worth a v3.1).
