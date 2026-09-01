# SPEC v20: integrity and operations before autonomy

Status: **proposed**. Extends SPEC-v16 through SPEC-v19 and the data law.
This ships before Partner steps, the attention compiler, or interactive agents.

## 0. Why this exists

ianOS has the right product instinct: the phone should still accept a small
action when the Mac is asleep, agents should leave a useful record, and a
scheduled seam should heal after a closed lid wakes. The implementation has
four gaps that make more autonomy unsafe:

1. The offline queue gives each item a client-only id, but never sends it to
   FastAPI. If the server commits and the response is lost, replay applies the
   same POST, PATCH, DELETE, or counter increment again.
2. `facts.source_memo_ids` exists, but `write_fact` cannot receive citations.
   `compact_memos()` then physically deletes the source evidence.
3. `sync_btc.py` owns both inbound seams, but launchd calls its BTC default.
   Personal correspondence is therefore only collected when someone opens the
   relevant UI or runs a command manually.
4. Finance freshness is a passive 48-hour display calculation. There is no
   schedule, last-failure record, or fire-once recovery alert. The two
   SimpleFIN `urllib` call sites also miss the certifi trust-store workaround
   already proven in `core/push.py`.

This is not a cleanup sprint. It establishes the safety properties on which
the three fronts depend: an action happens once, a conclusion remains
auditable, every configured inbound seam is actually collected, and important
data can truthfully say when it stopped arriving.

## 1. Binding laws

1. **Every browser write that may replay has a server-visible mutation id.**
   A queue item is not idempotent because its body resembles a daily action.
   The server must durably recognize the exact mutation before the browser can
   safely forget it.
2. **The business change and its receipt commit together.** A response cannot
   say completed unless the receipt and row changes share one SQLite
   transaction. A response lost after that commit is replayed from the
   receipt, not performed again.
3. **A daily capture belongs to the day it was tapped.** Replaying a 23:55
   action after midnight must not move it to tomorrow.
4. **Compaction archives evidence, it never destroys it.** Normal reading can
   hide old memos; fact citations must still resolve to the original records.
5. **One seam loader, one all-configured schedule.** `sync_btc.py` remains the
   only inbound writer. A configured seam may fail independently, but no
   configured seam is silently omitted by the timer.
6. **Last success and last attempt are different facts.** A zero-row successful
   sync is fresh. A failed attempt must not masquerade as success or overwrite
   the last successful timestamp.
7. **A stale-data alert fires once per continuous incident.** It contains the
   source and time only, never transactions, balances, inbound messages,
   consent, tokens, or credentials.
8. **Unconfigured remains quiet.** Missing optional credentials do not create
   a repeated error, memo, or push. Schedulers refuse when no source in their
   domain is configured.

## 2. Phase A: durable mutation receipts

### 2.1 Scope

Convert every current `queueable: true` dashboard mutation:

| Route family | Current caller |
|---|---|
| `POST /api/gym/confirm` | Command and Body |
| `POST /api/activity` | Action Stack and App quick controls |
| `POST /api/wellness` | App quick controls |
| `POST`, `PATCH`, `DELETE /api/partner-tasks` | Partner |

All future queueable writes use the same helper. Interactive agent requests,
lead operations, proposal decisions, note edits, and uploads remain
nonqueueable because they require a current server response.

### 2.2 Schema and migration

Add this table in `core/db.py`'s single `SCHEMA` string. `connect()` applies
this `CREATE TABLE IF NOT EXISTS` for new and existing databases; keep
`run_migrations` for additive columns and data backfills only, never as a
second schema source:

```sql
CREATE TABLE IF NOT EXISTS mutation_receipts (
    mutation_id  TEXT PRIMARY KEY,
    operation    TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    effective_date TEXT,
    captured_at  TEXT,
    status_code  INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    applied_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mutation_receipts_applied
    ON mutation_receipts(applied_at);
```

New `mutation_id` values are UUIDs generated once by the client. `request_hash` is the
SHA-256 of canonical JSON containing operation, semantic body, and effective
date. It is a safety check, not a secret. Do not expire receipts: the expected
write volume is tiny, while a long-sleeping installed PWA can replay a very old
queue item. Permanent receipts are the only honest exactly-once guarantee.

### 2.3 API contract and transaction boundary

Queueable calls generate their identity before the first network attempt and
send all three headers on the first attempt and every replay:

```http
X-ianOS-Mutation-Id: <uuid>
X-ianOS-Captured-At: 2026-08-15T23:55:14.921Z
X-ianOS-Effective-Date: 2026-08-15
```

The effective date is computed from the device's local calendar at tap time.
It applies to gym, activity, and wellness; Partner preserves server timestamps
but retains the same receipt. The generic wrapper starts `BEGIN IMMEDIATE`
before the receipt lookup, then does this in one transaction:

1. Look up `mutation_id`.
2. If found with a different operation or request hash, roll back and return
   409. Never
   apply the body under a reused id.
3. If found with the same request hash, return its stored status and parsed
   response exactly. Do not emit a second memo or increment a counter.
4. If absent, run the route's mutation closure and insert its 2xx receipt in
   the **same transaction**. Return the newly produced response.

The implementation must not call existing helpers that issue their own
`commit()` inside this transaction. Add an explicit `commit: bool = True`
option, or private noncommitting helpers, for the scoped writers (`add_memo`,
activity, wellness, gym confirmation, and Partner mutations). The API owns the
outer transaction. This is the condition that makes a receipt real rather
than merely a duplicate detector after the fact.

For one installed-service-worker release, routes retain their existing behavior
when the mutation header is absent. New dashboard bundles always send it.
Validation errors remain ordinary 4xx responses and are not receipted. Only
400, 404, 409, and 422 become dead-letter items. Authentication/permission
errors (401/403), timeout 408, rate-limit 429, 5xx, and network failures keep
the same mutation id in the queue because they may recover.

### 2.4 Dashboard contract

`dashboard/src/lib/offline.js` migrates queue records to v2 on read. An
existing v1 timestamp/random `id` is retained as a bridge-safe legacy mutation
id accepted by the server during the one-release compatibility window; do not
claim it is a UUID. Its `at` ISO timestamp becomes `captured_at`, and the
browser derives `effective_date` from that instant in the device's local
timezone. During that window, server validation accepts only UUIDs or the
known legacy timestamp/random shape, never an arbitrary identifier. New v2
records use UUIDs. Every v2 record preserves `mutation_id`,
`captured_at`, and `effective_date` alongside path, method, and body.
`dashboard/src/lib/api.js`
creates those values before the first attempted queueable fetch, passes them
to the immediate request and, if needed, to `enqueue`. `flush()` forwards the
same headers. It never invents a new id while retrying.

The queue is still oldest-first and stops at a network or 5xx failure. Add a
module-level/Web Locks flush guard so reconnect, visibility, and manual flush
cannot replay the first item concurrently. Move a 409 or terminal 4xx to a
visible dead-letter list with its safe response detail. Never silently drop an
item or silently truncate the oldest records when storage is full. Existing
optimistic Partner rows reconcile against the stored server response after a
successful flush.

### 2.5 Acceptance tests

- First request commits task plus receipt; identical retry returns the same
  task and creates one row/memo only.
- Simulate commit followed by a lost client response, replay with the same id,
  and assert exactly one activity increment, gym event, Partner task change, and
  memo.
- Reuse an id with a changed body or operation and get 409 with no mutation.
- Verify pending queue serialization survives reload and preserves the id.
- Verify a legacy v1 id and timestamp migrate without loss and replay with
  date derived in the browser's local timezone.
- Verify a tap captured before midnight and replayed after midnight affects
  its captured date.
- Verify a terminal 4xx becomes visible dead-letter state, while a 5xx stays
  queued, and storage-full fails visibly without losing an older action.

## 3. Phase B: provenance-preserving memo compaction

### 3.1 Schema

Add to `memos`:

```sql
archived          INTEGER NOT NULL DEFAULT 0,
archived_at       TEXT,
archived_into_id  INTEGER REFERENCES memos(id) ON DELETE SET NULL
```

Add a normalized citation relation:

```sql
CREATE TABLE IF NOT EXISTS fact_sources (
    fact_id  INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    memo_id  INTEGER NOT NULL REFERENCES memos(id) ON DELETE RESTRICT,
    added_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (fact_id, memo_id)
);
CREATE INDEX IF NOT EXISTS idx_memos_active_created
    ON memos(archived, created_at);
CREATE INDEX IF NOT EXISTS idx_fact_sources_memo
    ON fact_sources(memo_id);
```

Keep `facts.source_memo_ids` only as a compatibility projection, not the
canonical relation. Backfill valid legacy integer ids idempotently; report
missing historic sources as `legacy, no source retained` rather than inventing
evidence. Every fact read derives `source_memo_ids` from `fact_sources`, and
every fact write synchronizes the serialized compatibility value in the same
transaction until the old column is absent from all reads. The two may never
drift. Do not rebuild the facts table or change its domain rules.

### 3.2 One read path for active versus archived records

`recent_memos(..., include_archived=False)` becomes the single active-memo
read path and includes `archived=0`. `memo_count()`, the state endpoint, and
`read_memos` all use it. `latest_montage()` is deliberately an exception: it
is a persistent Body artifact and must include archived coach montage memos,
or move to its own durable record before compaction changes. Add an explicit
evidence helper that fetches a
bounded, ordered list of memo ids regardless of archive state. It is used by
the fact-detail endpoint only, never injected into `/api/state`.

The fact detail contract is:

```http
GET /api/facts/{fact_id}/sources
→ { "fact_id": 12, "sources": [{"id": 91, "from_role": "archivist",
    "topic": "...", "body": "...", "created_at": "...", "archived": true}] }
```

This is on-demand because state is polled and service-worker cached. It gives
Ian an audit trail without turning all historical conversation into the normal
phone payload.

### 3.3 Fact writes and compaction

Extend `upsert_fact` and the `write_fact` tool schema with
`source_memo_ids: list[int] | None`. `None` preserves existing links;
a nonempty list validates unique, existing memo ids and replaces the fact's
links in the same transaction. An agent-created fact requires at least one
citation. Only a deliberate Ian/API path may clear citations with an empty
list. The tool never trusts a prose citation.

`compact_memos()` changes its final operation from `DELETE` to a transactional
archive update. It writes every compacted summary without committing, then
marks its old active sources `archived=1`, records `archived_at`, and points
`archived_into_id` at the summary. One transaction commits the group. A second
run selects zero archived rows. Original bodies and ids remain available to
facts that cite them.

The Archivist role prompt should say plainly: cite durable conclusions with
memo ids, do not write a fact from an unsupported memory, and archive only
after the summary is committed.

### 3.4 Acceptance tests

- A cited fact keeps its original source ids after compaction.
- Evidence lookup returns an archived cited memo with the original body.
- Normal memo feed no longer returns archived rows.
- A second compaction changes zero original rows and does not duplicate a
  summary.
- Invalid, duplicate, or nonexistent source ids are rejected by `write_fact`.
- `ON DELETE RESTRICT` protects a cited memo from accidental physical deletion.

## 4. Phase C: inbound completeness and common TLS

### 4.1 One all-configured inbound command

Keep `ingest/sync_btc.py` and its `SEAMS` map. Add:

```text
--all-configured    Sync every seam with both URL and token set.
```

`--source` and `--all-configured` are mutually exclusive. `sync_all()`
determines complete seam pairs first, rejects a partial URL/token pair as a
configuration error, and invokes each configured source with its own database
connection and transaction. It reports `{source, status, counts, error_code}`
for each source. One network or protocol failure cannot prevent the other
configured seam from being pulled. If no seam is configured it returns exit 2;
if any configured seam fails it returns exit 1 after attempting the rest.

Retain `--source btc` and `--source personal` for diagnosis and manual use.
Add `make sync-inbound` for `--all-configured`; retain `sync-btc` and
`sync-personal` aliases so existing muscle memory does not break.

Update the existing `com.ianos.btcsync` launchd job to pass
`--all-configured`. Keeping the label avoids a remove/reinstall surprise.
`make schedule-btc` is renamed in its user-facing copy to `schedule-inbound`
and retained as an alias. It requires at least one complete inbound seam, not
specifically BTC. It fails early on a partial credential pair. A missing
optional personal seam is a skip, never a failed timer run. The FastAPI
`/api/btc/sync` endpoint stays BTC-only, so opening the BtC tab never fetches
personal correspondence.

### 4.2 Shared TLS boundary

Create `core/http.py` with one cached `ssl_context()` function: certifi's
bundle when available, system default otherwise. `core/push.py`,
`ingest/sync_chase.py`, and `ingest/setup_simplefin.py` import it. Every
`urllib.request.urlopen` call receives `context=ssl_context()`.

The module contains no request policy, retry logic, credentials, or business
writer. It only solves macOS Python trust-store consistency. `requests` use in
the inbound loader is unchanged. Add `certifi` explicitly to
`requirements.txt`; do not rely on a transitive install from `requests`.

### 4.3 Acceptance tests

- An `--all-configured` run calls both configured seams and leaves either
  unconfigured seam untouched.
- A personal record remains correspondence: it creates no lead and has no
  promise clock, even when scheduled with BTC.
- BTC still acks only after its durable write; the all-seam wrapper preserves
  this per-seam ordering.
- One seam failure still executes the other and returns a nonzero final code.
- All three `urllib` call sites receive the shared TLS context.

## 5. Phase D: finance health, not finance nagging

### 5.1 Ingest status data

Extend `ingest_log` additively:

```sql
last_attempt         TEXT,
last_success         TEXT,
last_error           TEXT NOT NULL DEFAULT '',
consecutive_failures INTEGER NOT NULL DEFAULT 0,
stale_alerted_at     TEXT
```

Backfill `last_attempt` and `last_success` from the current compatibility
success timestamp, `last_import`. `record_ingest_success()` remains the one
success path: it updates `last_import`, `last_attempt`, and `last_success`,
clears the error/failure count, and clears `stale_alerted_at` so a later
incident may alert once. `record_ingest_attempt(source)` commits before network
work begins, so a killed or hung process is observable. On failure,
`record_ingest_failure(source, error_code)` updates only error/failure count.
It never changes `last_import` or `last_success`.

Do not put credentials, a provider response, a transaction description, or a
balance in `last_error`. Examples are `network`, `auth`, `provider_5xx`, and
`protocol`.

### 5.2 Scheduled orchestration

Before scheduling, harden the source writers. SimpleFIN rejects a malformed
response with neither accounts nor balance and catches only duplicate-key
`sqlite3.IntegrityError`, never every database exception. SnapTrade stages
every account before replacing the snapshot; a position-fetch failure or an
unexpectedly empty portfolio when a previous nonempty one exists fails that
source rather than publishing a partial portfolio as current. Source data and
success status commit together. A deliberate `sync_fidelity.py --allow-empty`
path is the only way to accept a legitimate transition to no holdings.

Then create `ingest/sync_finance.py`, an orchestrator only. It runs every
configured source independently through `sync_chase.sync()` and
`sync_fidelity.sync_holdings()`, records health, and emits a concise process
report. It must not write transactions or holdings itself. Expose public
`configured()` helpers in the two source modules instead of reaching into
private environment checks. Rewire `make sync-finance` to this orchestrator;
the current Make dependency chain stops after Chase fails and would otherwise
bypass independent-source execution and health recording.

Add `ops/com.ianos.financesync.plist` with `RunAtLoad` and a local morning
`StartCalendarInterval`, then `make schedule-finance` and
`make schedule-finance-off`. Installation refuses when neither source is
configured **or** either source has a partial credential set. Its error names
missing key names only, never their values. An entirely absent optional source
is reported as skipped, not failed.

### 5.3 Freshness evaluator and UI

Add a pure `core/freshness.py` that turns ingest status, source configuration,
and injected `now` into `disabled | never | healthy | degraded | stale`. A
configured finance source is stale after 48 hours since last success. A source
with no success stays `never` until its first attempt has remained unresolved
for 48 hours. A recent failed attempt with a success inside 48 hours is
degraded and does not page Ian; two manual attempts minutes apart must not
manufacture a stale incident. Before sending, claim every `stale_alerted_at IS
NULL` source in a short `BEGIN IMMEDIATE` transaction by stamping it, then send
the aggregate push. This prevents overlapping manual, RunAtLoad, and scheduled
runs from duplicating a page. Delivery failure still leaves the claim stamped,
matching the product's no-nag policy. A later success clears it.

`metrics.finance_state()` and `stale_data_domains()` consume this one
evaluator. `/api/state` exposes only per-source state, last successful time,
attempt time, and failure count. It does not expose raw error text or
financial data in a push. The finance surface makes a stale source visible
without turning it red into a personal verdict.

### 5.4 Daily external dead-man switch

After local scheduled ingestion is reliable, add a separate Vercel cron in the
BTC site repository only. On the Hobby plan it is a daily backstop, not an
hourly SLA monitor. BTC makes a public response-time promise; the personal
site does not, so its correspondence does not manufacture urgency. The
authenticated cron route checks unacknowledged holding-pen records older than
30 hours, sends one generic email through a dedicated `IANOS_DEADMAN_TO`
configuration, and claims each record with a Redis `SET NX` fire-once marker.
Markers use a 60-day TTL. Ack deletes its marker. If Resend rejects or fails,
release just-claimed markers so the next daily run can retry. The email names
the site and age only, never the contact message, phone, consent, or booking
details.

Protect the route with Vercel's `CRON_SECRET` bearer authorization, returning
401 before any KV read for a missing or wrong secret. It returns count-only
JSON with `Cache-Control: no-store`; it does not pull the ianOS database,
mutate leads, or attempt a second loader. It only catches the case where the
Mac is absent long enough that ianOS cannot alert itself. A daily Hobby cron
can fire almost 24 hours after the 30-hour threshold, so the worst case is
roughly 54 hours after receipt. This is a backstop, never a precise SLA.

### 5.5 Acceptance tests

- A successful zero-row sync refreshes `last_import`.
- A failed sync preserves the prior `last_import`, stamps `last_attempt`, and
  stores only a classified error.
- A malformed SimpleFIN response or partial/empty SnapTrade result cannot
  replace the last known-good money data.
- At 48 hours a continuous stale incident pushes once; another scheduler tick
  pushes zero times; a success clears the incident; a new later outage can
  alert once again.
- Unconfigured SimpleFIN/SnapTrade creates no push and a schedule command
  refuses if neither source is configured.
- Finance state uses one freshness result across stale-domain, checking, and
  portfolio surfaces.
- Dead-man tests reject wrong/missing `CRON_SECRET`, skip fresh records, send
  one aggregate alert for old records, release claims after Resend failure,
  delete markers on ack, and prove consent/message/phone sentinels never enter
  body, subject, response, or logs.

## 6. Delivery order and non-goals

1. Mutation receipts and their tests.
2. Memo archive/provenance migration and tests.
3. All-configured inbound schedule plus shared TLS.
4. Finance health and schedule.
5. Only then the product-facing specs v21 through v23.

This spec does not introduce an event bus, a second ianOS database, a Redis
service for ianOS, a job queue, background model execution, a generic
notification center, or a finance transaction writer. The BTC site's existing
holding-pen KV may use an atomic Redis-style claim for its own external
dead-man marker. Each larger addition would expand the blast radius while the
current one-file architecture already has the correct seams.
