# ianOS v4. Connector Sync Specification ("Path A")

**Status:** approved direction: use Claude's built-in connectors (free with the
subscription) instead of paid third-party APIs wherever they fit.
**Audience:** an implementing agent with no prior context. Everything needed is
in this file plus the repo. Verified against the codebase 2026-07-16.
**Scope:** one loader CLI, three project slash commands, tests, docs. No agent,
schema-table, or dashboard changes (one optional Makefile target).

---

## 0. The architectural fact this spec is built on

Claude connectors (Gmail, Google Calendar, Google Drive, …) exist **inside a
Claude session**, an interactive `claude` run in this repo, or claude.ai. They
are NOT a standing API. `api/main.py` and the nightly `agents/runner.py` can
never call them directly.

Therefore the design is a **reader/writer seam**:

```
Claude session (has connectors)          ianOS (has the database)
┌──────────────────────────────┐         ┌────────────────────────────┐
│ /sync-calendar  /sync-gmail  │  JSON   │ ingest/from_connector.py   │
│ reads via connector,         │ ──────► │ validates, dedupes, writes │
│ shapes strict JSON           │  stdin  │ to the native tables       │
└──────────────────────────────┘         └────────────────────────────┘
```

- The Claude session is a **reader and shaper only**. It never writes SQL, never
  touches `data/ianos.db`, never edits files. Its entire output is JSON piped to
  the loader.
- The loader is the **only writer** and trusts nothing: it validates every
  record, enforces the hard rules in §3.4, and dedupes idempotently, running
  the same sync twice must change nothing.
- The dashboard needs zero changes: it already renders every table this fills
  (calendar → steward's time audit, facts → Memory page, documents → counsel's
  tripwire, memos → the feed).

Ian's ritual after this ships: open a terminal → `claude` → type
`/sync-calendar` (or `/sync-gmail`, `/sync-drive`) → watch the report → done.
Cost: subscription usage, effectively $0.

---

## 1. Recommended connectors for Ian (build the commands in this order)

| # | Connector | Feeds | Why it earns a slot |
|---|-----------|-------|---------------------|
| 1 | **Google Calendar** | `calendar_events` | Replaces the manual `.ics` export ritual entirely. Powers Alfred's (steward) time audit, clears the `personal` staleness flag, and gives Hitch/Iroh/Dumbledore real event context. Cleanest data, lowest risk, ship first. |
| 2 | **Gmail** | `facts` (dated), `documents` (references), `memos` | The intelligence jackpot: prospect replies for Dwight (scout), LLC/EIN/A2P confirmation emails for Hermione (watchdog), renewal/price-change notices for Belfort (cfo) as upcoming-cost facts, UIUC emails for Dumbledore. |
| 3 | **Google Drive** | `documents` | Any contract/agreement dropped in a `Clockwork/Contracts` folder becomes a `pending` document row, which **already trips Harvey Specter's tripwire** (`pending_documents()` in runner.py), waking counsel that night. |

**Explicitly skipped:** Notion, Slack, Linear, GitHub connectors (not in Ian's
stack); any bank/brokerage: **no such connector exists**; money stays on
`make import` CSV / SimpleFIN / SnapTrade.

**Ian's one-time setup (not automatable):** enable Gmail, Google Calendar, and
Google Drive in claude.ai → Settings → Connectors (or `/mcp` in an interactive
`claude` session) and complete the Google OAuth for each. The slash commands
fail with a clear "connector not enabled" message until then (§4.5).

---

## 2. Current-state facts the implementation must respect

Verify with these before coding (paths relative to repo root):

- `calendar_events` upserts via `db.upsert_calendar_event(**fields)`; dedup hash
  is `sha256(f"{date}|{start_time}|{summary}")[:20]`; categories are
  `work|health|personal` via keyword lists, mirror
  [ingest/import_calendar.py](../ingest/import_calendar.py) (`WORK_KW`,
  `HEALTH_KW`, `_categorize`). After loading, call
  `db.update_ingest_log(conn, "calendar", n, note)`: **the source name must be
  exactly `"calendar"`** because `metrics.stale_data_domains()` checks it to
  clear the `personal` stale flag.
- `facts` upserts via `db.upsert_fact(conn, domain, topic, body, kind, date,
  recurs, source_role, source_memo_ids, verified)`; `UNIQUE(domain, topic)`;
  topic namespaces route domains via `db.domain_for_topic()` (`partner:`/`family:`
  → personal, `uiuc:` → college, `market:` → finance, etc.). Dated facts drive
  dispatcher tripwires; `verified=0` facts surface in the Memory page's
  "Needs your confirmation" triage.
- `documents(name, path, kind, status, notes)` has **no insert helper yet** : 
  add `db.add_document(conn, name, path="", kind="contract", notes="") -> int`
  (status defaults `'pending'`). Dedup on (name, path): if a row with the same
  name+path exists, return its id, don't duplicate.
- `memos` via `db.add_memo(conn, from_role, topic, body, priority=1)`.
- `PROPOSAL_KINDS`, `FACT_DOMAINS`, `FACT_KINDS` constants live in `core/db.py`.
- Project slash commands = markdown files in `.claude/commands/` (directory does
  not exist yet); `/name` in a `claude` session runs `name.md` as the prompt.
- Tests live in `tests/` (pytest; fixture pattern: `monkeypatch db.DB_PATH` to
  `tmp_path`, see [tests/test_facts.py](../tests/test_facts.py)).

---

## 3. The loader: `ingest/from_connector.py`

### 3.1 Invocation

```bash
.venv/bin/python ingest/from_connector.py --source gmail  < payload.json
.venv/bin/python ingest/from_connector.py --source calendar --dry-run < payload.json
cat payload.json | make sync-load source=calendar          # optional Makefile sugar
```

- Reads ONE JSON document from stdin (or `--file path`). `--source` ∈
  `calendar|gmail|drive` (used for ingest_log + provenance notes).
- `--dry-run`: validate and print the per-record plan, write nothing, exit 0 on
  valid input.
- Exit codes: 0 = loaded (or valid dry-run), 1 = malformed JSON / schema
  violation (message names the record index and field), 2 = every record was
  rejected.

### 3.2 Payload schema

```json
{
  "records": [
    {"kind": "calendar_event", "date": "2026-07-18", "start_time": "09:00",
     "end_time": "10:00", "summary": "Riverbend demo", "category": ""},

    {"kind": "fact", "topic": "uiuc:tuition-due", "body": "Fall tuition due per bursar email 7/14",
     "fact_kind": "date", "date": "2026-08-10", "recurs": ""},

    {"kind": "document", "name": "Riverbend service agreement",
     "path": "drive://Clockwork/Contracts/riverbend.pdf",
     "doc_kind": "contract", "notes": "v2, sent by owner 7/15"},

    {"kind": "note", "topic": "email: Riverbend reply",
     "body": "Owner replied 7/15: wants pricing in writing before Friday."}
  ]
}
```

Per-kind validation (reject the record, not the batch; report rejects in the
summary):

| kind | required | rules |
|---|---|---|
| `calendar_event` | date, summary | date is ISO; times `HH:MM` or null; blank category → keyword `_categorize` (reuse import_calendar's, extracted or imported); compute `duration_min` from times when both present else 60; hash exactly as import_calendar does |
| `fact` | topic, body, fact_kind | fact_kind ∈ FACT_KINDS; `date` required iff fact_kind=`date` (ISO); recurs ∈ {"", "yearly"}; domain = `db.domain_for_topic(topic, "business")`; **`verified` is forced to 0** and `source_role` to `"connector-<source>"`: caller input for these fields is ignored |
| `document` | name | doc_kind default `contract`; dedup per §2 |
| `note` | topic, body | topic is force-prefixed `email: `/`calendar: `/`drive: ` per source if not already; body hard-truncated to 500 chars; **priority forced to 1**; `from_role="ian"`; dedup: skip if an identical (from_role, topic, body) memo exists within 7 days |

### 3.3 Output (the session relays this to Ian)

```
connector sync (gmail): 6 records → 2 facts (unverified), 1 document (pending), 2 notes, 1 rejected
  - rejected [3] fact "twilio-renewal": fact_kind=date requires a date
  facts need confirmation on the Memory page before agents trust them.
```

Also `db.update_ingest_log`: source `"calendar"` for calendar loads (see §2),
`"connector_gmail"` / `"connector_drive"` otherwise; note = summary counts.

### 3.4 Hard rules (enforced in the loader, not the prompt)

1. **Never writes `transactions`.** Email receipts are NOT bank data; the bank
   CSV/SimpleFIN is the single money source of truth (double-count risk).
   Recurring costs found in email become dated `facts` for the cfo instead.
   There is no code path from the loader to the transactions table.
2. **Connector facts are born unverified** (`verified=0`). Ian confirms on the
   Memory page before agents treat them as authoritative. No exceptions.
3. **Connector notes can't shout**: memo priority is pinned to 1; only agents
   and real deadlines earn P2/P3.
4. **Idempotent**: re-piping the same payload changes zero rows (hash/UNIQUE/
   lookback dedup per kind).
5. No goals, proposals, briefs, or holdings writes. The loader's table surface
   is exactly: calendar_events, facts, documents, memos, ingest_log.

---

## 4. The slash commands: `.claude/commands/`

Three markdown files. Each is a complete, self-contained prompt: a fresh
`claude` session with no other context must be able to execute it. Shared
skeleton for all three:

1. **Read-only pledge (top of every file):** "You are syncing data INTO ianOS.
   Use the <X> connector to READ only. Never send, reply, forward, modify,
   archive, delete, or create anything in the connected account. If a
   destructive action seems needed, stop and tell Ian instead."
2. Read + filter (per-command specifics below).
3. Shape the strict JSON of §3.2, include a copy of the record schemas inline
   in the command file so the session needs no other reference.
4. Write the JSON to a temp file, run the loader
   (`.venv/bin/python ingest/from_connector.py --source <x> --file <tmp>`),
   delete the temp file.
5. Relay the loader's report verbatim, plus one line telling Ian if anything
   needs action (e.g. "2 facts await confirmation on the Memory page").
6. **Failure modes:** if the connector is unavailable/not authorized, say
   exactly how to enable it (claude.ai → Settings → Connectors, or `/mcp`) and
   stop. If the loader exits non-zero, show its stderr; do not retry with
   loosened data.

### 4.1 `/sync-calendar` (`sync-calendar.md`)

- Window: past 7 days + next 21 days, primary calendar.
- Map every event → `calendar_event` records (leave category blank, the loader
  categorizes; exception: pass `category` through if the session is confident
  it's `work`/`health`).
- Additionally: any event that is clearly a birthday/anniversary/recurring
  personal date may ALSO be emitted as a dated `fact` with the right namespace
  (`family:`/`partner:`): it will land unverified for Ian to confirm.
- Do not emit `note` records from calendar unless an event was cancelled.

### 4.2 `/sync-gmail` (`sync-gmail.md`)

- Window: last 14 days, INBOX (skip spam/promotions categories).
- Extract ONLY these four signal types, ignore everything else:
  1. **Prospect replies**: senders matching HVAC/plumbing/contractor
     businesses or threads mentioning Clockwork/demo/audit → `note`
     (topic `email: <sender-business>`; body = one-sentence gist + date; never
     paste full email bodies).
  2. **Legal/registration confirmations**. IL Secretary of State, IRS/EIN,
     Twilio A2P → `note` + a dated `fact` when the email states a date
     (e.g. approval date, filing deadline).
  3. **Renewal / price-change notices**: domains, subscriptions, SaaS →
     dated `fact` (topic like `market:namecheap-renewal` or a business-domain
     slug; body includes the amount AS TEXT for cfo context). Never a
     transaction.
  4. **UIUC email**: bursar, registrar, housing, orientation → dated `fact`
     (`uiuc:` namespace) and/or `note`.
- Privacy: nothing from personal/private threads outside these four types; gist
  summaries only, ≤500 chars, no forwarded content, no addresses/links unless
  they ARE the signal (e.g. a deadline date).

### 4.3 `/sync-drive` (`sync-drive.md`)

- Look only in folders matching `Clockwork` / `Contracts` / `Legal` (ask Ian
  once and remember in the command file if none exist).
- New PDFs/docs that look like contracts/agreements/terms → `document` records
  (`path` = Drive URL). Do not download or quote contents. Harvey reads what
  Ian gives him later; this sync only registers that a document is pending.

---

## 5. Makefile + docs (small)

- Optional target:
  ```make
  ## Pipe a connector JSON payload into the loader:  make sync-load source=gmail FILE=payload.json
  sync-load:
  	$(PY) ingest/from_connector.py --source $(source) --file $(FILE)
  ```
- README: add a "Connector sync (free, via Claude)" subsection under the
  existing ingest rituals: the three slash commands, the one-time connector
  enablement, and the two-sentence architecture note (session reads, loader
  writes, Memory page confirms).
- IAN-SETUP.md: append a short optional section mirroring the README bit.

---

## 6. Tests: `tests/test_from_connector.py`

Follow the existing fixture pattern (`monkeypatch db.DB_PATH → tmp_path`).
Import and call the loader's `load(payload: dict, source: str, conn)` function
directly (structure the CLI so this pure function exists).

- [ ] calendar_event: valid record inserts; identical re-run inserts nothing
      (hash dedup); blank category gets keyword-categorized ("Riverbend demo
      call" → work); ingest_log source == `"calendar"`.
- [ ] fact: `verified` forced to 0 even when payload says `"verified": 1`;
      `source_role` == `"connector-gmail"`; fact_kind=date without date →
      rejected with index+field in the message; `partner:` topic lands domain
      personal.
- [ ] document: inserts with status `pending`; same (name, path) re-run doesn't
      duplicate; `runner.pending_documents()` tripwire fires with the row
      present (import the checker from agents.runner as test_dispatcher does).
- [ ] note: priority pinned to 1 despite payload `"priority": 3`; topic gets
      the `email: ` prefix; >500-char body truncated; identical note within 7
      days deduped.
- [ ] transactions guard: a record `{"kind": "transaction", ...}` is rejected;
      transactions row count stays 0.
- [ ] batch behavior: one bad record among three → other two load, exit 0,
      report lists the reject; all-bad batch → exit 2.
- [ ] `--dry-run` writes nothing (all table counts unchanged).

Regression: full suite (`make test`) stays green.

---

## 7. Acceptance criteria

- [ ] `pytest tests/test_from_connector.py` green; `make test` green.
- [ ] End-to-end without any connector (proves the seam): pipe a hand-written
      sample payload (commit it as `samples/connector_payload.json`) through
      the loader; verify on the live dashboard: calendar event visible in
      steward data, fact appears in Memory "Needs your confirmation",
      document row exists, note in the feed from "ian". Re-pipe it; verify
      zero new rows.
- [ ] `make plan` after loading a document shows counsel: `RUN (tripwire: 1
      document(s) pending review)`.
- [ ] The three command files exist in `.claude/commands/` and each contains:
      the read-only pledge, the JSON schema inline, the loader invocation, and
      the connector-not-enabled fallback text.
- [ ] README + IAN-SETUP.md updated.
- [ ] Loader has no code path writing transactions/goals/proposals/briefs
      (grep-verifiable: no such table names in its INSERT/UPDATE statements).

## 8. Non-goals

- **Path B** (MCP servers inside the nightly runner for unattended pulls) : 
  separate future spec; nothing here should preclude it.
- Auto-scheduling the sync (Claude scheduled routines could run `/sync-*`
  later; v2 once the manual ritual proves itself).
- Sending email, creating calendar events, writing to Drive, never.
- Parsing bank/receipt amounts into transactions, never (hard rule §3.4.1).
