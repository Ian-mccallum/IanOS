---
name: data
description: "ianOS data-layer work: the binding law for the SQLite schema, core/db.py, migrations, ingest loaders, write boundaries, idempotency, privacy walls, and backups. Use whenever creating or altering a table or column, writing or changing anything that INSERTs/UPDATEs/DELETEs, adding an ingest source or sync, touching leads/facts/journal/notes data, doing backup or restore work, or deciding where new data should live. Also use before giving any agent a new read tool. Not for pure UI work with no data surface (that is the osui skill)."
---

# The data law of ianOS

One SQLite file, `data/ianos.db`, is Ian's entire life: 1,958 leads with real
call history, every journal entry, every memo, the money. Code is replaceable
and lives in git; this file is neither. Every law below exists because
breaking it loses or leaks some of that.

**Read `core/db.py` before believing anything here about a column, and read
the relevant spec (`docs/SPEC-v*.md`) before touching a feature's tables.**
A spec records intent; the source is the fact.

## The laws

**D1. One file, no ORM, schema in one place.** The whole schema is the
`SCHEMA` string in `core/db.py`, applied on `connect()`. Changing a table =
edit `SCHEMA` **and** add an idempotent guard in `run_migrations` (probe with
`_has_column`, then `ALTER`), because existing DBs never re-run `CREATE TABLE`.
No SQLAlchemy, no second schema source, ever.

**D2. Every source has exactly ONE writer, and the boundary is code.**

| Data | Only writer | The rule it enforces |
|---|---|---|
| `transactions`, `holdings` | `ingest/import_csv.py`, `sync_chase.py`, `sync_fidelity.py` | Money is sacred; the connector loader must never gain access |
| `leads` (bulk) | `ingest/import_leads.py` | Re-import refreshes `LEAD_SCRAPED_COLS` only; `stage/attempts/last_touch/next_touch/notes` are Ian's and survive every re-scrape |
| Connector seam | `ingest/from_connector.py` | Table surface is exactly `calendar_events, facts, documents, memos, ingest_log`; facts born `verified=0` |
| iCloud CalDAV | `ingest/sync_icloud.py` | Writes only the "ianOS Plan" calendar; remote wins; deletes leave tombstones |
| `streak_events` grace/reset | the nightly run | Idempotent; the UI writes only `confirm` |
| Journal media files | the `/api/journal` upload route | Extension whitelist, served by entry id, no path traversal |
| `inbound_requests` | `ingest/sync_btc.py` (both seams) | Ack only after a durable write; `source='personal'` never touches `leads`; consent is walled |
| `poop_log` | the `/api/poop` routes (Ian's taps) | No agent tool and no Ring 1 act writes it; `day` is stamped at the tap, never derived from `logged_at` |
| `school_items` (`syllabus` provider) | `data/fall_2026_school_seed.json` via `make sync-syllabus` | `seed_inventory` archives any syllabus item the file no longer lists, so a hand-inserted row is erased on the next load |

A new data source gets a new loader that owns it, never a widened existing
one. Agents never write tables directly: they have tools, tools have
allowlists, and money/trade guards live inside the tool functions
(`NO_MONEY_PROPOSALS`, `TRADE_VERBS`), not in prompts.

**D3. Events, not tallies.** `streak_events` and `lead_touches` store what
happened; state (`stage`, `attempts`, streak length) is derived. This is what
makes undo honest: delete the event, rebuild the state from what remains,
never decrement a counter and hope. New "did X happen" data follows this
shape.

**D4. Idempotency is a requirement, not a nicety.** Re-running any loader on
the same input changes zero rows. The tools: content hashes
(`calendar_events.hash`, `lead_key()`), `UNIQUE(date, kind)` on briefs
(re-running a day replaces), collapsing duplicate PENDING proposals. The
sharp edge: **SQLite allows unlimited NULLs in a UNIQUE column.** A nullable
key silently duplicates on every re-import; `phone_norm` gets a
`x<sha256[:15]>` hash instead of NULL for exactly this reason. A dedupe key
must never be NULL.

**D5. One read path per question.** `all_goals()` is the single place the
`archived` filter lives, which is why archiving a goal removes it from the
dashboard, metrics, pillars and every agent in one edit. `_lead_filter()` is
shared by `list_leads` and `count_leads` so the pager total cannot drift from
the rows. A new query for an existing question goes through the existing
path; a new question gets one function that everything calls.

**D6. The privacy walls (do not weaken, tests assert them).**

- **Journal**: bodies and media never appear in `/api/state`, and no agent
  tool reaches them. Agents get one precomputed `agent_signal` line (counts,
  never words). Only an explicit Share turns text into a memo.
- **Notes**: `read_notes` is read-only, allowlisted to `chief` + `archivist`,
  enforced twice (allowlist AND `NOTE_READERS` inside the tool). No writing
  counterpart exists.
- **Pipeline**: `read_pipeline` same pattern (`PIPELINE_READERS`, scout +
  chief). Run/heat data is deliberately withheld: agents see dials and
  outcomes, never "he stopped after 4".
- **The log** (`poop_log`): counts, the 7-day average and the Bristol mix ride
  `read_health`, so they inherit its health-AI consent gate. The `note`
  column does not: writing Ian types about himself follows the journal/notes
  wall, not the sensor rule. Values live on `no-store` `/api/poop` routes,
  never in `/api/state`.
- **Facts**: `read_facts` is code-scoped to the agent's own domains; an agent
  cannot request another domain's memory. Connector/seed facts are born
  `verified=0` and stay untrusted until Ian confirms.
- **Consent-grade data** (SMS consent records, anything legally load-bearing):
  never in `/api/state` (polled every 15s, cached by the phone's service
  worker), never in memos or facts, never in a push notification (the ntfy
  topic is world-readable).
- **Interactive cache (SPEC-v23 / v25):** `agent_invocations`, `chat_prefs`,
  and `chat_threads` never enter `/api/state` or any agent reader. Chat does
  not write memos, facts, briefs, or focus. File in Inbox is a human tap that
  records an inert proposal as `role='ian'`. `read_mail` is a filtered reader
  of already-synced notes/facts; it is not on any nightly or Ask allowlist.
- **The call queue is a wall too.** `leads` is Clockwork's scored, tiered
  pipeline and SPEC-v9's promise is its *ordering*. Inbound from a personal
  site (`source='personal'`) never creates or matches a lead. A recruiter in
  the call queue corrupts it invisibly, one row at a time, and no test would
  catch it unless you write the one that counts rows (SPEC-v19).

The shape of every wall: a read tool with no writing counterpart, an
allowlist enforced a second time inside the tool, and a test that fails if
the wall thins.

**D7. Domains are inconsistent by design.** `goals` CHECK allows
`business|health|personal|finance|school`; facts use
`business|finance|health|personal|college|legal`. `college` and `school` both
exist. Check `DOMAINS` vs `FACT_DOMAINS` in `core/db.py` before assuming;
topic namespaces route via `NAMESPACE_DOMAINS` / `domain_for_topic()`.

**D8. Backups (SPEC-v16).** The DB is snapshotted with `VACUUM INTO`, never
file-copied: it runs WAL and a raw copy taken mid-write is silently corrupt.
Restore (`scripts/restore.sh`) materializes into a NEW folder and never
writes into the live tree. restic carries only non-git state; git backs up
code. A failed scheduled run writes a `system` memo (the role-crash
precedent). Unconfigured is exit 2 plus a scheduling refusal. The engine is
bash + restic + sqlite3 only, so it moves to the Linux Framework laptop with
the systemd timer in `docs/BACKUP.md`. `RESTIC_PASSWORD` in `.env` must also
exist in the password manager and on paper; losing it makes every backup
permanently unreadable, by design.

**D9. New on-disk data must be claimed by the backup.** The DB rides free
(new tables are inside the file), but a new gitignored directory (the next
`data/journal/`) is **unprotected until added to the `paths` array in
`scripts/backup.sh`**. Creating one and not claiming it recreates the exact
"exists in one place on Earth" problem SPEC-v16 closed.

## Traps that have actually shipped or been caught here

| Trap | What happens | Rule |
|---|---|---|
| NULLable dedupe key in a UNIQUE column | 64 phoneless leads would duplicate on every re-import | Hash a stable identity into the key; never NULL (D4) |
| Importing `tier_*.csv` alongside `enriched.csv` | The tier files are a partition of enriched (A+B+C+D = 1,958); importing both doubles every lead | One canonical input per loader |
| Re-import refreshing every column | The scraper runs again and wipes Ian's call history | `LEAD_SCRAPED_COLS` whitelist; Ian's state is untouchable (D2) |
| Raw `cp` of `ianos.db` for a "backup" | WAL means the copy can be mid-write corrupt, and it looks fine until restore day | `VACUUM INTO`, or `make backup` which does it (D8) |
| `trap on_err ERR` without `set -E` in bash | The trap silently never fires inside functions; the backup failed with no memo | `set -Eeuo pipefail` when a trap must fire in functions |
| launchd job calling a brew-installed binary | launchd's PATH is bare; the nightly job dies on `command not found` | Resolve binaries explicitly (`backup.sh`/`phone.sh` precedent) |
| launchd job whose program is `/bin/bash`, repo under `~/Desktop` | TCC denies it the protected folder, so it exits 126 BEFORE the script runs and the script's own ERR trap cannot write the failure memo. The backup was dead 29 days while every other job worked, because they all exec `.venv/bin/python` | Launch through a binary that already has the grant and `exec` into bash; TCC responsibility survives the exec. And never let "it writes a memo on failure" be the only signal, since it cannot cover a failure to start |
| SQLite booleans reaching React | `0 && <Pin/>` renders a literal `0` in the UI | Coerce with `!!` at every boolean-ish column (shared with osui) |
| Trusting connector facts | Sync writes a wrong birthday; agents repeat it forever | Born `verified=0`; agents trust only what Ian confirmed (D6) |
| A goal query bypassing `all_goals()` | Archived goals resurface in one surface and not others | Single read path (D5) |
| Testing against the real B2 repo | A test could prune or pollute the only off-site copy | Tests use a throwaway local `RESTIC_REPOSITORY` (see `tests/test_backup.py`) |
| A stable key derived from LIST POSITION | The school seed's `known_major_dates` entries get `milestone-{position}` when they carry no `id`, and `school_item_completions` is keyed on it. Inserting one entry mid-list re-keys every later item and orphans its completions | Give every entry an explicit `id`; a dedupe key must not move when its neighbours do (D4) |
| A LIKE search that does not escape `%` and `_` | Typing a single `%` returned every row, which reads as a broken search rather than as SQL | Escape the wildcards and pass `ESCAPE`, so a typed wildcard searches for itself |
| A client-side filter over a truncated projection | Notebook search filtered a 280-character `preview`, so a word written later in a lecture never matched though the SQL could find it | Search where the full text is (the server), and return the match context so the hit is visible |
| A client-supplied timestamp accepted as-is | A backfilled log carrying a timezone lands among naive-local rows and every comparison against it is off by the offset | Refuse an aware value at the boundary and store naive local like its neighbours (`_poop_backfill_at`) |
| Mixing a UTC timestamp with the DB's naive-local ones | `received_at` arrives UTC from the site; every deadline computed off it landed ~5h wrong, and nothing looked broken until an alert fired at the wrong hour | Convert once at the boundary, store local like its neighbours, and test the elapsed interval (SPEC-v18 law 4) |
| `CREATE INDEX` on a column that only exists after a CHECK rebuild | SCHEMA `CREATE TABLE IF NOT EXISTS` leaves the old `agent_invocations` table; `CREATE INDEX ... (thread_id)` then fails before `run_migrations` can add the column | Put indexes that depend on migrated columns in `run_migrations`, after the rebuild (`idx_agent_invocations_thread`, `idx_transactions_account_key`) |
| A recurring job that re-fires on every tick | A 15-minute sync with no fire-once guard pushes 16 alerts an hour | Stamp the row (`alerted_at`) when it fires, not when it succeeds |
| `set -e` without `-E` in a bash job with an ERR trap | The trap never fires inside a function, so the failure memo is silently skipped | `set -Eeuo pipefail` whenever a trap must survive into functions |

## Verifying data work (in this order)

1. `make test` (or one file: `.venv/bin/python -m pytest tests/test_X.py -q`).
   Tests here assert the laws, not the implementation: write the test that
   fails when the wall thins or the loader double-imports.
2. Test conventions: `monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")`
   then `db.connect()` gives a real-schema throwaway DB; `TestClient(main.app)`
   for API paths. Loaders get `--dry-run` runs against fixture files.
3. Idempotency check is mandatory for loader changes: run it twice, assert
   zero new rows the second time.
4. For destructive-looking operations on the real DB: don't. `make clean` +
   `make seed` gives a fresh demo DB; the real one is restorable via
   `make restore` but you should never be the reason that's needed.
5. After backup-engine changes: `.venv/bin/python -m pytest tests/test_backup.py -q`,
   then `make backup && make backup-verify` against the real repo once.

## When adding a table or data source

- **Who is the one writer?** Name it before writing schema. If the answer is
  "several places", the design is wrong (D2).
- **Events or state?** If it records occurrences, store events and derive
  (D3). Plan for undo on day one.
- **What is the dedupe key,** and can it ever be NULL? (D4)
- **Who may read it?** If an agent should: a read-only tool, an allowlist
  entry, a reader-set constant inside the tool, and no writing counterpart.
  If it is private or consent-grade: keep it out of `/api/state` and add the
  wall test (D6).
- **Does `/api/state` carry it?** Summary blocks (`_leads_summary` precedent),
  never the full rows, the SPA polls every 15s.
- **Is it on disk outside the DB?** Add the directory to `.gitignore` AND to
  `scripts/backup.sh` paths in the same commit (D9).
- **Will it reach the public mirror?** Everything in a private commit is
  exported to the public `ianOS` repo by `scripts/export_public.py`
  (SPEC-v39). Real
  data belongs in gitignored paths (`data/`, `leads/*.csv`, `.env`); a
  tracked fixture, seed, or spec that quotes a real name, balance, room,
  or credential needs a substitution rule or an exclusion in that script
  before it is committed.
- **Domain semantics**: check D7 before reusing `school`/`college` etc.
- Update `SCHEMA`, `run_migrations`, the spec (or write one), and CLAUDE.md's
  table list.
