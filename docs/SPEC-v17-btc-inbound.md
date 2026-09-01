# SPEC v17: BtC inbound (demo + contact sync)

Two repos, one feature: when someone books a demo or sends a message on
beatyourclock.com, it lands in the ianOS BtC tab, matched to the lead Ian may
already have been calling, with one tap to confirm a window.

## Why pull, not push

ianOS is architecturally never public: `tailscale funnel` is banned
(docs/PHONE.md), and the API treats any forwarded request as remote precisely
so a tunnel can never inherit localhost trust. Even a public ianOS would not
fix the real constraint: the Mac sleeps, and a push fired at a sleeping (or
mid-migration) laptop is a lost booking. So the site holds bookings durably
and ianOS collects them whenever it is awake: at-least-once delivery + an
idempotent loader = nothing lost across sleep, a dead week, or the Framework
migration. Bonus: a queryable record of every request instead of a pile of
emails.

## Laws

1. **Email stays the source of truth on the site.** The store write happens
   after delivery, is awaited with a hard timeout (Vercel kills detached
   promises), and can never fail the visitor's submission. A store failure is
   a `*_STORE_FAILED` console line beside the existing `*_DELIVERY_FAILED`.
2. **Ack-based draining, not timestamp cursors.** The site returns everything
   unacked; ianOS acks ids only after its own durable write + commit. Clock
   skew can't lose a record; a crash between write and ack just re-delivers,
   and the loader's idempotency (D4) absorbs it.
3. **`request_id` is minted on the site** (`crypto.randomUUID()`), carried in
   the email body, the KV record, and `inbound_requests.request_id UNIQUE`.
   One id reconciles all three by hand if anything ever looks off.
4. **The consent record is walled, immediately.** It is legally load-bearing
   for A2P registration. In ianOS it lives only in `inbound_requests.consent`:
   never in `/api/state` (polled 15s, cached by the phone SW), never in memos,
   facts, or push notifications, and no agent tool reads this table (data-law
   D6). A test asserts the wall.
5. **Inbound never fabricates a score.** A booking matched or created in
   `leads` never sets/edits `tier/fit/pain/reach/total/miss_signal`: scoring
   belongs to `enrich_prospects.py` (SPEC-v9). A created lead keeps tier C
   default and enters through band logic naturally; the inbound card, not the
   queue, is its surface until confirmed.
6. **Lead identity: phone first, then email, then hash.** `phone_norm` when a
   phone exists; else match by exact email; else create with
   `lead_key()`-style `x<sha256(email|name)[:15]>` so `phone_norm` is never
   NULL (D4). The payoff case: Ian cold-called Tuesday, they booked Thursday,
   it must merge onto the same row.
7. **Confirming a window is one tap and writes through existing machinery:**
   a `lead_touches` row (`kind='demo'`, `outcome='booked'`) + `next_touch` =
   the confirmed date. `next_stage` moves the lead, `activity_bumps` feeds
   `demos_last_7d`, band 0 resurfaces it that morning. No new metric code.
8. **The site side degrades to today's behavior.** No KV env vars → store
   silently skips (the `RESEND_API_KEY` precedent); ianOS unconfigured →
   `sync_btc.py` exits 2 with instructions and `/api/btc/sync` returns 501
   (the plan-sync precedent).
9. **UI is osui law.** The card sits above The Line's brief (a promise with a
   24h fuse outranks the cold queue). `--crit` banned; a request older than
   24h wilts, never reddens; no countdown timer.

## The site half (btc repo)

- **Store**: Vercel KV (Upstash Redis) via plain `fetch` to
  `KV_REST_API_URL` + `KV_REST_API_TOKEN`, no new dependency (the repo's
  zero-dep fetch style). Keys: `ianos:rec:<request_id>` (JSON, 60-day TTL as
  a safety net) + set `ianos:unacked`. Ack = `SREM` + `DEL`. Email remains
  the site-side archive.
- **Endpoints** (`api/ianos-inbox.js`): `GET` returns
  `{records: [...]}` for all unacked (capped 200), `POST {ack: [ids]}`
  drains. Bearer auth via `IANOS_SYNC_TOKEN` env; `Cache-Control: no-store`.
  This is the most sensitive URL on the site (it serves consent records):
  401 without the token, no CORS.
- **Handlers**: `api/demo.js` and `api/contact.js` gain ~15 lines each:
  mint `request_id`, include it in the email HTML, `await` the store write
  with a 2s AbortController inside try/catch.
- **Record shape** (both kinds):

```json
{
  "request_id": "uuid", "kind": "demo" | "contact",
  "received_at_utc": "ISO", "name": "", "company": "", "email": "",
  "phone": "", "topics": [], "windows": [{"date": "2026-08-12",
  "window": "morning", "label": "Tue, Aug 12 · Morning 8-11am"}],
  "interest": "", "message": "", "consent": { ...full A2P record }
}
```

- **ISO windows**: `demo.astro` checkbox values become
  `YYYY-MM-DD|<window>|<label>` (script-regenerated dates already exist);
  the handler parses into the structured form. Without this ianOS cannot set
  `next_touch` or place a plan block; the display label rides along.

## The ianOS half

- **Schema** (`inbound_requests`): `request_id TEXT UNIQUE`, `kind` CHECK
  demo|contact, `lead_id` FK nullable, `status` CHECK
  `new|confirmed|dismissed`, person fields, `topics`/`windows`/`consent` as
  JSON text, `message`, `received_at`, timestamps. Index on `status`.
- **Loader** (`ingest/sync_btc.py`): the ONLY writer for this seam (D2).
  GET → validate each record (Reject-and-continue, the `from_connector`
  pattern) → match/create lead (law 6) → INSERT OR IGNORE by `request_id` →
  commit → ack exactly the ids written. A memo from `system` announces new
  arrivals (count + names, never consent). `.env`: `BTC_SYNC_URL`,
  `BTC_SYNC_TOKEN`.
- **API**: `POST /api/btc/sync` (lock + 120s cooldown + 200-on-throttle +
  501 unconfigured, verbatim plan-sync pattern); `/api/state` gains an
  `inbound` summary block (pending rows, consent stripped, capped);
  `POST /api/inbound/{id}/confirm {date}` (law 7) and
  `POST /api/inbound/{id}/dismiss`.
- **Sync cadence**: piggyback, no new daemon: the dashboard fires
  `/api/btc/sync` opportunistically (cooldown makes it cheap) the way plan
  sync does, plus `make sync-btc` for the terminal.
- **UI**: card on `BeatTheClockPage` above The Line: name, company, kind,
  topics/message first line, the windows as tappable chips (confirm) and a
  quiet dismiss. Wilt after 24h (law 9).
- **Agent visibility**: none in v1. If the chief should ever name an inbound
  demo in the Day Command, that is a precomputed line in
  `build_user_prompt`, never a new tool. Consent never crosses (law 4).

## Tests (`tests/test_btc_inbound.py`)

- same payload twice → zero new rows (D4)
- consent absent from `/api/state` and from the inbound summary (law 4)
- phone match merges; email match merges; phoneless create leaves
  `phone_norm` non-NULL (law 6)
- inbound never mutates tier/fit/pain/reach on an existing lead (law 5)
- confirm writes touch + next_touch + stage in one transaction; dismiss
  leaves the lead untouched
- unconfigured: loader exit 2, endpoint 501 (law 8)

## Ian's setup (once, ~3 min)

1. Vercel dashboard → Storage → create KV → connect to the btc project
   (adds `KV_REST_API_URL`/`KV_REST_API_TOKEN` automatically).
2. Generate `IANOS_SYNC_TOKEN` (long random), add to Vercel env AND to
   ianOS `.env` as `BTC_SYNC_TOKEN`, plus
   `BTC_SYNC_URL=https://www.beatyourclock.com/api/ianos-inbox`.
3. Redeploy the site; `make sync-btc` in ianOS to prove the loop.

## Out of scope, deliberately

- Auto-creating plan blocks from confirmed windows (Ian confirms; a later
  spec may place the block).
- Syncing assessment/waitlist forms (same pattern when wanted).
- Any dashboard analytics on inbound volume (conversion charts stay banned).

## As built (2026-08-12)

Built and verified end-to-end with a real submission through the live site:
pulled, matched into a new lead, shown on the BtC card, confirmed through
`_touch_and_advance` (stage → `demo`, `activity.demos`/`conversations`
bumped correctly), then undone through the app's own touch-reversal endpoint
to clean up the test data, with activity counters landing back at zero. The
consent wall held (verified against `/api/state`) throughout.

Two deviations from the plan above, both operational rather than design:

- The KV store is **Upstash Redis**, provisioned through Vercel's Storage
  tab rather than the "Vercel KV" product this spec assumed (Vercel retired
  that branding). No code changed: Upstash's connect flow injects the same
  `KV_REST_API_URL`/`KV_REST_API_TOKEN` env var names `_ianos-store.js`
  already read.
- Getting the site to deploy at all surfaced two pre-existing bugs in the
  btc repo, unrelated to this feature: `vercel.json`'s build command never
  installed the `@btc/whiteprint` workspace link, and three lockfiles across
  the monorepo confused npm's optional-dependency resolution for a native
  build tool. Both are fixed and documented in the btc repo's own
  [README.md](https://github.com/Ian-mccallum/beatyourclock/blob/main/README.md)
  rather than here, since they're deploy-pipeline facts, not sync-feature
  facts.
