# SPEC v24: money foundation

Status: **proposed**. Builds on the Plaid sync (commit 32db5e5), SPEC-v23
interactive agents, and the SPEC-v18 promise clock. Read `.claude/skills/data`
and `.claude/skills/osui` before implementing; both bind here.

## 0. Problem

The Money page shows blended totals from four sources but cannot answer the
questions Ian actually has: what is THIS account, what happened in it, what do
I owe on which card and when, and what does the CFO think about a specific
charge. Concretely:

- `transactions.account` is a free-text display name (`"Plaid account"`
  fallback in `sync_plaid.py`). Nothing joins a transaction to its
  `financial_accounts` row, so a per-account view cannot exist.
- `financial_accounts` holds only the CURRENT balance. No history, so no
  sparkline, no "HYSA grew $40 this month".
- The only transaction surface is `recent_transactions(conn, 45)` inside
  `/api/state`: 45 days, no paging, no filter, no search.
- SnapTrade is one "Connected portfolio" blob. Roth IRA, Robinhood, and
  Coinbase are different money with different jobs; the UI cannot show them
  apart, and SnapTrade accounts never enter the registry.
- Cards have `current_balance` and `credit_limit` (utilization is derivable)
  but no statement balance, due date, or minimum payment. A due date is a
  promise about to break; the promise clock exists and is not pointed at it.
- SPEC-v23 shipped `read_transactions`/`read_holdings` as interactive
  read-only tools, but there is no way to ask about a SPECIFIC row.

## 1. Laws

1. **The registry is the spine.** Every provider (Plaid, SnapTrade, SimpleFIN,
   CSV) publishes its accounts into `financial_accounts`. An account's
   identity is `(source, external_id)`; its display string is derived, never
   the join key.
2. **Single writer per seam stays.** `sync_plaid.py` alone writes Plaid rows,
   `sync_fidelity.py` alone writes SnapTrade rows. No loader gains another
   loader's tables (data law D2).
3. **Balances are events.** History is a snapshot table written
   idempotently by each account's own loader; state is derived (D3). Never
   store a computed trend.
4. **One read path per question** (D5). One `_txn_filter()` shared by the list
   endpoint and its count; `/api/state` keeps summaries only, never the full
   history (the `_leads_summary` precedent).
5. **AI inspect is SPEC-v23, narrowed.** An inspect is a transient, read-only
   invocation whose entity context is resolved server-side in Python. The
   browser sends an id, never a prompt. All seven v23 laws apply unchanged.
6. **No shame on money already spent.** Utilization and due dates may warn
   (they are actionable and alarming); a past purchase never gets a verdict
   color. `--crit` on Money is reserved for the burn cap, card debt, and
   overdue-shaped facts, exactly as today.

## 2. Schema (all changes in `SCHEMA` + `run_migrations` guards)

```sql
-- transactions: stable link to the registry
ALTER TABLE transactions ADD COLUMN account_key TEXT NOT NULL DEFAULT '';
-- '<source>:<external_id>' e.g. 'plaid_chase:AbC123'. '' = unlinked (CSV, legacy).
CREATE INDEX idx_transactions_account_key ON transactions(account_key, date);

-- holdings: same link, so brokerage accounts split
ALTER TABLE holdings ADD COLUMN account_key TEXT NOT NULL DEFAULT '';

-- balance history: events, one row per account per day, idempotent
CREATE TABLE IF NOT EXISTS balance_snapshots (
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    date          TEXT NOT NULL,           -- local date, boundary-converted
    current       REAL,
    available     REAL,
    UNIQUE(source, external_id, date)      -- never-NULL key (D4)
);

-- card liabilities: registry sidecar, Plaid liabilities product
CREATE TABLE IF NOT EXISTS card_liabilities (
    source             TEXT NOT NULL,
    external_id        TEXT NOT NULL,
    statement_balance  REAL,
    minimum_payment    REAL,
    due_date           TEXT,               -- local date
    apr                REAL,
    is_overdue         INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (source, external_id)
);
```

Writers: `sync_plaid.py` writes `balance_snapshots` + `card_liabilities` for
its items on every sync (`INSERT OR REPLACE` keyed on the UNIQUE). SnapTrade's
loader writes `balance_snapshots` + registers its accounts in
`financial_accounts` (`type='investment'`, subtype `roth`/`brokerage`/
`crypto` mapped from SnapTrade account meta). Run-twice test asserts zero new
rows on the second pass.

`account_key` population: `sync_plaid._transaction_values` already has
`account_id` in hand; emit `f"{source}:{account_id}"`. SnapTrade positions
likewise. CSV imports leave `''` and the UI shows them under "Unlinked".

## 3. API

```
GET /api/transactions?account_key=&category=&q=&month=&limit=50&offset=0
  -> {rows, total, sum_in, sum_out}      # one _txn_filter() for rows+total+sums
GET /api/accounts/{source}/{external_id}
  -> {account, liabilities?, snapshots_90d, recent_txns_20, holdings?}
```

`/api/state` changes: `financial_accounts` block gains SnapTrade rows and, for
cards, `utilization` + `due_date` + `minimum_payment` (computed fields, no new
polling weight). `recent_transactions` stays as-is for the summary strip.

Card due dates feed `core/promises.py`: a card with `due_date` within 5 days
and `statement_balance > 0` and no payment-shaped transaction since the
statement is a promise about to break. Fire-once via an `alerted_at` stamp
(SPEC-v18 law: stamp on fire, not success), 21:00-08:00 silent, push carries
"card due Fri, $340 minimum $35" and nothing else.

## 4. AI inspect (rides SPEC-v23)

New mode on the existing endpoint, same validation posture:

```
POST /api/agent-invocations
{"role": "cfo", "mode": "inspect",
 "entity": {"kind": "transaction", "id": 812},
 "question": ""}                          # optional, <=500 chars
```

- Allowed kinds: `transaction`, `account`, `holding`. Allowed roles: the
  entity's natural readers only (`cfo` for transactions/accounts, `wealth`
  for holdings), enforced server-side; the browser cannot pick another.
- The server resolves the entity into a precomputed context block, all
  Python, no model: the row itself, the merchant's 12-month history (count,
  total, cadence guess), the account's snapshot trend, category totals, and
  for cards the liability row. The role narrates; it never does date math
  (the `build_user_prompt` precedent).
- Everything else is v23 verbatim: transient, read-only tool intersection,
  never a memo, one at a time, 60s rate limit, bodies out of `/api/state`.

UI entry: an `Inspect` action on every transaction row, account sheet, and
position row. Opens `AskAgentSheet` prefilled with the entity chip and the
role glyph; the sheet's existing polling and failure states carry over.

## 5. UI (osui-bound; author at 375px first)

**Money home keeps one job: "am I okay."** Hero stays net worth + runway
badges. Below it, the account list becomes the primary surface, replacing the
"Connected portfolio" / "Connected cash & cards" split:

- Four groups: `Cash`, `Cards`, `Investments`, `Crypto` (group = mapped
  type/subtype). Each row: institution glyph, name + `••mask`, balance
  mono-right. Cards add a hairline utilization meter (warn >30%, crit >70%)
  and `due Fri` when a due date is inside 7 days. Groups collapse; a group
  header shows its subtotal so collapsed still answers "am I okay."
- Tapping a row opens the **account sheet** (bottom sheet, not a new tab: it
  does not earn one of the five slots). One screen, one job: this account.
  Balance, 90-day sparkline from `balance_snapshots`, then its last 20
  transactions (or positions for investment accounts), then `View all` into
  the history browser, `Inspect` in the sheet header. Cards show statement
  balance, minimum, due date, APR above the transactions.
- **History browser** (`#money-history`, behind More + reachable from any
  sheet): month-grouped infinite list from `GET /api/transactions`, filter
  chips (account, category), search. Month header: `in / out / net` mono.
  No charts here; it is a lookup surface, the `LeadList` precedent.
- Empty states say the next command in one line, no apology. All new writes
  are reads; nothing here queues offline.

Freshness: each group header inherits the per-source `finance_health` state
chip that exists today; a stale source marks its group, not the whole page.

## 6. Phases

1. **Link + registry** - `account_key` columns, SnapTrade into
   `financial_accounts`, migration guards, backfill Plaid txns by re-sync.
2. **Snapshots** - `balance_snapshots` writers in both loaders + run-twice
   idempotency tests.
3. **Browse API** - `_txn_filter()`, `GET /api/transactions`, account detail
   endpoint, `/api/state` computed card fields.
4. **UI** - grouped account list, account sheet, history browser.
5. **Cards** - Plaid liabilities pull, `card_liabilities`, utilization +
   due-date surfaces, promise-clock wiring.
6. **Inspect** - v23 mode + entity resolvers + `Inspect` entries.

Each phase ships alone. 1-3 are invisible; 4 is the visible payoff; 5 and 6
are independent of each other.

## 7. Tests that assert the laws

- `test_txn_account_link`: a synced Plaid transaction carries a non-empty
  `account_key` that joins to a registry row.
- `test_snapshots_idempotent`: sync twice, snapshot count unchanged.
- `test_state_carries_no_history`: `/api/state` payload contains no
  `balance_snapshots` and no transaction list beyond the 45-day summary.
- `test_txn_filter_shared`: list total equals count for every filter combo.
- `test_inspect_role_wall`: `wealth` + `transaction` entity is 422; browser
  role/model/tool overrides rejected (v23 suite extension).
- `test_card_promise_once`: due-date alert fires once, silent hours hold.

## Considered and cut

- **A `#money/<account>` hash page per account.** A sheet answers "this
  account" without nav-state complexity; L2 says disclosure before page.
- **Net-worth chart on the home page.** The sparkline lives in each sheet;
  the home page answers "am I okay," not "graph me." Revisit with intents.
- **Categorizer expansion.** Real personal categories matter but are their
  own spec once real descriptions accumulate; guessing keywords now is slop.
- **Coinbase-direct sync.** SnapTrade covers it; a second crypto seam is a
  second writer for the same data (D2 violation) until proven needed.
