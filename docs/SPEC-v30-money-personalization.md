# SPEC v30: Money, redesigned and personalized

Status: **decided, implementation next**. Born from a judge-panel workflow:
three independently-lensed proposals ("The Ledger," "Ledger," "Loadout"),
scored and synthesized by a fourth agent that re-verified every citation
against source rather than trusting the proposals. Winner: **Ledger**, with
one real capability ("Loadout"'s no-drag-dependency UI reasoning, and "The
Ledger"'s `budget_rules` table for personal-spend keyword matching) grafted
in. This document is my own synthesis on top of that judging, re-verified
again before writing it down, not a pass-through.

## Ian's own words, verbatim

"one page i really think needs to look better is the money section, it
hurts to look at. Both UX and UI need changes. i want it to feel like a
real money app thats been personalized to me. i want more customization for
that AS WELL." Confirmed via follow-up: all four customization mechanisms
below (not a subset), and a brainstorm-and-synthesize process rather than a
named reference app.

## The actual defect, verified against source

`.money-hero` (`styles.css:1338-1342`, background `rgba(251,191,36,.06)`,
border `rgba(251,191,36,.2)`, label `#fbbf24` at `:1349`) and
`.money-burn-hero` (`:1432-1436`, identical background/border, label
`#fbbf24` at `:1444-1450`) are **byte-identical**. Two cards claim equal
top-of-page weight. That is the literal mechanism behind "hurts to look
at," confirmed by direct comparison, not a vibe. Nested inside the net-worth
hero, `.money-hero-stats` (`MoneyPage.jsx:316-343`, CSS
`repeat(auto-fit,minmax(140px,1fr))` at `:1378-1392`) is a miniature
identical-stat-card grid, one level inside the very card meant to avoid
that anti-pattern (PRODUCT.md's own "identical stat-card grids" ban,
`:47`). `showDetails` (`MoneyPage.jsx:198-200`, gating `:439-500`) is one
boolean hiding three structurally unrelated things (Linked accounts,
Finance goals, Recent transactions) at once, so collapsing the transaction
list also hides whether Ian has cash. Every account row renders in flat
`var(--ink)` (`.money-symbol`, `styles.css:1506`), indistinguishable except
by reading institution names.

## Decided, not open

1. **All four customization mechanisms ship**: widget order/visibility,
   per-account color/icon, choosing the hero metric, and real user-editable
   budget categories replacing the hardcoded `$150/mo` business-burn cap.
2. **One hero, not two.** Amber wash becomes exclusive to whichever single
   metric Ian picks. Everything else demotes to normal weight.
3. **The cross-account net-worth trend line is explicitly deferred**, not
   dropped. `balance_snapshots` (`core/db.py:106-114`) is per-account only;
   summing across accounts by day needs new logic that correctly signs
   credit-card balances negative and only draws once every included
   account has overlapping snapshot dates. Ship it once that's built, don't
   ship a hand-wave chart. Everything below is real for v1; this one item
   is named and deferred on purpose.

## Architecture

### One `<MoneyHero>`, four data shapes, never a fifth card

Replace both hardcoded hero blocks (`MoneyPage.jsx:295-437`) with one
component. A `heroFor(metric, state)` selector maps `money_prefs.hero_metric`
into `{ label, value, sub, meter }`:

- `net_worth` (today's default, `netWorth` at `:216`): sub becomes one plain
  text line ("Portfolio $X · Cash $Y"), killing the nested stat-grid
  entirely, no `meter` (net worth has no cap, never fake a progress bar
  against nothing).
- `burn` (`burnNow`/`burnCap`, `:242-245`): today's burn-hero content
  verbatim (meter, category rows, month history), just gated behind "is
  this the chosen hero" instead of always-on.
- `cash` (`cashVal`, `:214`, already computed but only ever a hero-stat
  sub-cell, never a hero itself): the existing "below $1,000" floor warning
  folds into `sub` instead of a separate grid cell.
- `goal` (a chosen finance-domain goal): hoists `GoalRow`'s existing
  `Meter` call (`:186-187`) into hero position.

Whichever metric is **not** chosen keeps rendering in its ordinary
lower-page location, governed by `widgets_json` below. Nothing is ever
rendered twice; there is no fifth hero shape.

**Deliberately not reusing `goals.hero`** for the goal case, even though
it's verified safe today (`core/pillars.py:106-107` and
`core/plan.py:245-249` both hard-filter `domain='business'`, so a
`domain='finance'` hero flag is currently unread by anything). A dedicated
`hero_goal_id` column costs one integer and means Money's own display
choice can never silently start driving Plan/Command behavior if either of
those consumers is ever widened to other domains. Keep the two concepts
decoupled on purpose; a future implementer "helpfully" unifying them would
introduce spooky action at a distance.

### `showDetails` becomes per-widget, native `<details>`, one level up

Each of Linked accounts / Finance goals / Recent transactions becomes its
own independently-collapsible `<details>`, reusing the exact mechanism
already proven one level down on `.money-group` (`styles.css:1633-1647`),
with a persistent one-line summary (count + subtotal) visible even
collapsed. No new interaction pattern. The generic `<Card>` wrapper
(`MoneyPage.jsx:76-88`, reused verbatim at `:443,475,482,492`, PRODUCT.md's
named anti-reference) stays for genuinely list-shaped content, that's a
legitimate use; the fix is giving account rows identity color (below) so
the grid stops reading as one monotone stack, not eliminating `<Card>`
everywhere.

## Data model

### `money_prefs`, a new singleton row (the `chat_prefs` precedent)

```sql
CREATE TABLE IF NOT EXISTS money_prefs (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    hero_metric  TEXT NOT NULL DEFAULT 'net_worth'
                 CHECK (hero_metric IN ('net_worth','burn','cash','goal')),
    hero_goal_id INTEGER REFERENCES goals(id),
    widgets_json TEXT NOT NULL DEFAULT
      '[{"key":"accounts","visible":true},{"key":"goals","visible":true},
        {"key":"burn","visible":true},{"key":"transactions","visible":true}]',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
INSERT OR IGNORE INTO money_prefs (id) VALUES (1);
```

Mirrors `chat_prefs` (`core/db.py:540-545`, get/set at `:1444-1464`)
exactly: singleton via `CHECK (id=1)`, a real CHECK-constrained enum (zero
rebuild risk since this is a brand-new table, unlike widening an existing
column's CHECK). `widgets_json` is **one** array combining order and
visibility, not two separate arrays, specifically to avoid the desync risk
of an order array and a hidden array drifting apart. `get_money_prefs(conn)`
/ `set_money_prefs(conn, **fields)` mirror `get_chat_prefs`/
`set_chat_prefs_model`. API: `GET/PATCH /api/money/prefs`,
`Cache-Control: no-store`, mirroring `/api/chat/prefs`
(`api/main.py:2797-2816`) including its no-memo-on-patch behavior (a
reorder is as uninteresting to the memo feed as a model swap). Unknown
widget key: 422, matching the "unknown or inactive agent" convention
already at `api/main.py:2854`.

UI: a "Customize Money" `<Sheet variant="dialog">` from a gear affordance
beside the money eyebrow (`:303`). One row per widget: a visibility toggle
plus up/down arrow buttons, **deliberately not drag-and-drop** — confirmed
zero `draggable`/`onDragStart` usage anywhere in `dashboard/src` and exactly
four runtime dependencies in `package.json:12-18`, none a drag library.
`MoneyPage.jsx`'s hardcoded JSX order (`:439-500`) becomes a small
`[{key, render}]` array filtered/sorted by `widgets_json`.

### `financial_accounts` gains `color` and `icon`

Two columns, added via the existing additive-ALTER mechanism,
`_migrate_columns` (`core/db.py:660-684`, the same path that already added
`goals.hero`/`archived`) — **not** by editing the `CREATE TABLE` string
alone, which is a no-op against an already-created table on any installed
DB:

```
("financial_accounts", "color", "TEXT NOT NULL DEFAULT ''")
("financial_accounts", "icon",  "TEXT NOT NULL DEFAULT ''")
```

No DB-level CHECK. Validate server-side in Python (matching the real
`FACT_DOMAINS`-in-`create_fact` precedent, `api/main.py:992-993`): `color`
against ~8 curated hex values, specifically the **hex-only** subset of
`ROLE_COLORS` (`lib/agents.js:12-15`) — deliberately **not** the semantic
`var(--good)/var(--warn)/var(--crit)` entries also present in `ROLE_COLORS`,
because those carry real status meaning elsewhere on this exact page
(`burnLevel`/`utilLevel`, `:16-20`/`:41-45`) and reusing them for pure
account identity would violate PRODUCT.md's "urgency is earned, not
styled" principle. `icon` from a small closed glyph set. Unknown value:
422.

Write path: a narrow `set_account_appearance(conn, source, external_id, *,
color=None, icon=None)`, mirroring `set_chat_prefs_model`'s narrow-write
shape (`:1455-1464`), and **never** added to `upsert_financial_accounts`'s
explicit `ON CONFLICT ... DO UPDATE SET` column list (`:3163-3169`) — the
same write-boundary partition CLAUDE.md documents for `LEAD_SCRAPED_COLS` —
so the next Plaid/SimpleFIN/SnapTrade sync can never wipe it. API:
`PATCH /api/accounts/{source}/{external_id}/appearance`, beside the
existing `GET` (`:943`).

UI: an inline edit block inside `AccountSheet.jsx`'s `account-sheet-body`
(`:63-131`) — swatch strip + glyph strip + Save, no second nested sheet.
Consumption: `AccountRow` (`MoneyPage.jsx:139-174`) and `.money-group` rows
(`:442-472`) set `--account` the same way `RosterPage.jsx:23` sets
`--agent`, deriving `--account-soft`/`--account-line` at the identical
14%/34% `color-mix` ratios already proven at `styles.css:3005-3011`. The
balance number itself stays plain `var(--ink)` — color reads as identity,
never as a verdict on the balance.

### `budget_categories` + `budget_rules`, replacing the hardcoded cap

```sql
CREATE TABLE IF NOT EXISTS budget_categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    cap        REAL NOT NULL,
    categories TEXT NOT NULL DEFAULT '[]',  -- JSON array of transactions.category values
    color      TEXT DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS budget_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
```

Migration seeds exactly one row reproducing today's cap, so nothing
regresses on day one:

```sql
INSERT OR IGNORE INTO budget_categories (name, cap, categories)
VALUES ('Business burn', 150,
        '["ai","telecom","hosting","saas","domain","marketing","fees","legal"]');
```

That's `BUSINESS_CATEGORIES` (`core/db.py:603-605`) becoming row one of a
list Ian can add to, not a second parallel system living alongside the
Python set.

**`budget_rules` exists for personal spend, which today has almost nothing
to group.** `KEYWORD_CATEGORIES` (`ingest/categorize.py:3-14`) has exactly
11 entries, every one a business vendor (anthropic, twilio, railway,
namecheap, godaddy, google workspace, canva, fiverr, fedex office, il sec
of state, ilsos) — personal transactions overwhelmingly land as
`category=''`. Rules match only against `category=''` rows, using the same
lowercase-substring semantics `categorize()` already uses, so a personal
rule can never poach an already-categorized business transaction into a
personal bucket by keyword collision.

**A budget category groups existing categories; it never gets its own
categorizer.** `categorize()` keeps assigning `transactions.category`
exactly as today; `import_csv.py` stays the sole writer of that table per
the money-is-sacred law. `budget_categories.categories` and `budget_rules`
are a pure read-side aggregation and display layer over
`transactions.category`, computed at read time, never written back —
"every number must trace to a table row" (CLAUDE.md) holds literally, not
one column of `transactions` is ever mutated by this feature.

**The consumers get genuinely rewired, not left decorative.** Rewrite
`burn_by_month`/`month_burn_detail` (`core/db.py:3405-3427`, currently
hardcoded to the Python `BUSINESS_CATEGORIES` set) to sum against the
active `budget_categories` row(s) and read `cap` from the row. This touches
tested, load-bearing code (`_burn_this_month`, `core/metrics.py:46-50`, the
nightly cfo tripwire's metric resolver) — mitigate by keeping both
functions' return shape byte-identical and updating
`tests/test_metrics.py::test_resolve_goal_actuals_burn` to seed the
matching `budget_categories` row alongside the goal's existing
`target='150'`. Skipping this rewiring (as one of the three brainstormed
directions did) would mean editing "Business burn"'s cap in the new UI
silently does nothing to the real nightly enforcement or the tested metric
— a bug wearing a feature's clothes.

**A third, previously-unnoticed hardcoded copy of `150` must also go.**
Verified directly: `MoneyPage.jsx:16` (`function burnLevel(amount, cap =
150)`) and `MoneyPage.jsx:244` (`const burnCap = 150`) are a **third**
copy of this number, independent of both `BUSINESS_CATEGORIES` and the
goal's own `target` field. None of the three brainstormed directions caught
this one; the judge pass did. Once `budget_categories` exists, `/api/state`
must carry the active row's `cap`, and `MoneyPage.jsx` must read it from
state — otherwise editing the cap in the new UI changes real enforcement
while the on-screen meter keeps coloring against a stale hardcoded `150`.
**This is a required part of Phase 3 below, not an optional cleanup.**

Soft-delete via `archived`, matching `goals.archived`
(`core/db.py:671`) — not `partner_tasks`, which has no `archived` column (it
soft-deletes via `deleted_at`/`deleted_batch_id`, a different mechanism;
one of the three brainstormed directions cited a nonexistent
`partner_tasks.archived` precedent, corrected here).

UI: a `BudgetCategorySheet.jsx` (`Sheet.jsx` primitive, `variant="dialog"`)
with name/cap/color fields, a checklist of
`SELECT DISTINCT category FROM transactions WHERE category != ''` (Ian
picks from what actually exists, never free text that silently matches
nothing), and an add/remove list of keyword rules for the uncategorized
remainder. API: `GET/POST/PATCH /api/budget-categories`. None of this is
agent-facing, and none of it needs to be: it sits entirely on the "Ian's
own display/preference config" side of the money wall.
`NO_MONEY_PROPOSALS` (`agents/runner.py:72`) and `TRADE_VERBS` (`:242`)
stay untouched — nothing here writes a proposal or a trade, so they're
structurally irrelevant, not merely unweakened.

## Phases

### Phase 1: `money_prefs` + the single-hero redesign

- Migration: create `money_prefs`, seed the default row.
- Build `<MoneyHero>` with `heroFor()`, replacing the two hardcoded blocks.
- Kill the nested `.money-hero-stats` grid in favor of a plain text sub-line
  for the `net_worth` shape.
- Convert `showDetails` into per-widget `<details>` with always-visible
  summaries.
- `GET/PATCH /api/money/prefs`, the "Customize Money" Sheet, arrow-button
  reordering.

### Phase 2: account color/icon

- `_migrate_columns` additions to `financial_accounts`.
- `set_account_appearance`, excluded from `upsert_financial_accounts`'s
  `ON CONFLICT` set list.
- `PATCH /api/accounts/{source}/{external_id}/appearance`.
- Inline edit block in `AccountSheet.jsx`; `--account` custom property
  consumed by `AccountRow` and `.money-group` rows.

### Phase 3: budget categories (the biggest phase)

- `budget_categories` + `budget_rules` tables, seeded with today's cap.
- Rewire `burn_by_month`/`month_burn_detail` to read from the table.
- **Fix the JS-side hardcoded `150`** at `MoneyPage.jsx:16` and `:244` to
  read the active cap from `/api/state`. Do not ship Phase 3 without this;
  it's the difference between the feature working and silently not working.
- Update `tests/test_metrics.py::test_resolve_goal_actuals_burn` to seed
  the matching row.
- `BudgetCategorySheet.jsx`, `GET/POST/PATCH /api/budget-categories`.

### Phase 4 (deferred, not this round): cross-account net-worth trend

- Requires new logic to sign credit-card balances negative and align
  overlapping `balance_snapshots` dates across every included account.
  Ship only once that's built.

## Sequencing

Phase 1 first (delivers the actual "hurts to look at" fix and is the
foundation every other phase's UI hangs off), then 2 and 3 can proceed in
either order (disjoint files: `AccountSheet.jsx`/`financial_accounts` vs.
`budget_categories`/`core/metrics.py`/`MoneyPage.jsx`'s cap-reading). Each
phase gets its own verify pass; Phase 3 in particular touches tested,
agent-facing metric code and deserves the same rigor SPEC-v29's Phase 6
security review got.
