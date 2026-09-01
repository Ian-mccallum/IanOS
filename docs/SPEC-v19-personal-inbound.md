# SPEC v19: personal inbound + bot verification

Two things at once, because they touch the same files: ianmccallum.com gains
a contact form that flows into ianOS, and both sites gain Cloudflare
Turnstile.

## Why this is not just "SPEC-v17 again"

The transport is solved and proven: KV holding pen, authenticated pull, ack,
idempotent loader. That half is close to copy-paste.

The part that needs thought is **where a personal inquiry belongs**, and the
answer is: nowhere near The Line.

`leads` is Clockwork's cold-call pipeline: 1,958 rows, scored Fit/Pain/Reach,
tiered, market-ranked. SPEC-v9's entire promise is the **ordering guarantee**
of that queue. A recruiter, a UIUC contact, a press email or someone saying
hi is not a lead. Letting personal inquiries create `leads` rows would
quietly corrupt the one thing The Line exists to protect, and it would do it
invisibly, one row at a time.

So: same seam, different destination, and **no lead row, ever**.

## Laws

1. **Personal inbound never writes `leads`.** No row created, none matched,
   none touched. A test asserts the lead count is unchanged across a personal
   sync. This is the whole reason the spec exists.
2. **`source` distinguishes the seams.** `inbound_requests.source` is
   `'btc' | 'personal'`, defaulting to `'btc'` so existing rows keep meaning
   what they meant. `lead_id` becomes genuinely optional.
3. **No promise clock on personal inbound.** beatyourclock.com/demo publicly
   promises "within 24 hours" and SPEC-v18 alerts on that. ianmccallum.com
   promises nothing, so `promised_by` stays NULL and the jeopardy push never
   fires for it. Inheriting an SLA nobody offered would manufacture urgency
   out of nothing, which is the opposite of this product's job.
4. **Personal inbound lands on the Inbox page, not the BtC tab.** `#inbox`
   already means "things awaiting your decision" (agent proposals). An
   inquiry is exactly that. The BtC tab stays Clockwork's.
5. **Turnstile fails OPEN on service error, CLOSED on a bot verdict.**
   `api/contact.js` in the btc repo carries the note that a failed submit is
   what got the A2P campaign rejected. A bot check that rejects a real person
   because Cloudflare had a blip recreates that exact failure. So: an
   explicit `success: false` from Cloudflare rejects; a timeout, a 5xx, or an
   unreachable verifier lets the submission through and logs
   `TURNSTILE_DEGRADED`. Bot spam is an annoyance; a lost lead is the thing
   we already paid for once.
6. **The visitor never sees a bot-check error.** Managed mode is invisible
   for humans. On an explicit bot verdict the handler returns the same
   success shape it always did and simply drops the record. A real person
   caught by a false positive gets a thank-you page and an email that reaches
   Ian by another route; a bot gets nothing and cannot tell.
7. **Turnstile secrets are server-side only.** The site key is public and
   belongs in the HTML; the secret key never leaves the serverless function.
   One pair per domain, no sharing.
8. **The EmailShield stays.** The arithmetic challenge that reveals the
   mailto address is what currently keeps the address out of scrapers, and
   some people would rather use their own mail client. The form is an
   addition, not a replacement.
9. **No autoresponse from the personal site.** btc sends one because it
   promises a 24-hour reply. A personal-site autoresponse would have to come
   from the Resend-verified `beatyourclock.com` sender, which is off-brand
   and confusing on a personal inquiry. The thank-you page is the
   confirmation; Ian replies himself.

## The personal site half (ianmccallum repo)

Static HTML, no framework, Vercel, CommonJS handlers (the root
`package.json` has no `"type": "module"`, same constraint as btc).

- **Form** on `contact.html`: name, email, message. Three fields, styled to
  the existing Vista/Frutiger Aero surface, sitting alongside the EmailShield
  rather than replacing it. Honeypot `_gotcha` (the btc precedent) plus the
  Turnstile widget. Native POST works with JS off; the inline script upgrades
  it to fetch + thank-you.
- **`api/contact.js`**: validates, verifies Turnstile, emails Ian, stores to
  KV. Notification only, no autoresponse (law 9). Sends from the
  Resend-verified `beatyourclock.com` sender because that domain is already
  verified and DMARC-aligned; verifying ianmccallum.com in Resend later is a
  clean upgrade, not a prerequisite.
- **`api/_ianos-store.js`** and **`api/ianos-inbox.js`**: copied from btc,
  unchanged except the record shape. Its own Upstash KV and its own
  `IANOS_SYNC_TOKEN`, so a leak on one site cannot read the other's queue.
- **`vercel.json`** already rewrites `/thank-you`; the page exists.

## The btc half

Turnstile added to the `/demo` and `/contact` forms and verified in both
handlers. Nothing else changes. `npm run check:a2p` must still pass, and the
consent fieldset is untouched.

## The ianOS half

- **Schema**: `inbound_requests.source TEXT NOT NULL DEFAULT 'btc'`, migrated
  via the existing `_migrate_columns` list.
- **Loader**: `ingest/sync_btc.py` generalizes to take a seam config
  (url, token, source) rather than duplicating a near-identical
  `sync_personal.py`. Personal records skip `match_or_create_lead` entirely
  (law 1) and skip `promised_by` (law 3). `make sync-personal` alongside
  `make sync-btc`; the 15-minute launchd job pulls both.
- **UI**: the Inbox page grows a section above the agent proposals for
  personal inquiries: name, email, the message, a Reply button (mailto) and
  a Dismiss. Same wilt-not-redden law, no `--crit`.
- **Agent visibility**: none, same as SPEC-v17.

## Tests

- a personal sync leaves `COUNT(*) FROM leads` unchanged (law 1)
- personal rows carry `source='personal'`, `lead_id IS NULL`,
  `promised_by IS NULL`, and never appear in `due_for_alert` (law 3)
- btc rows still get a lead and a promise (no regression)
- same payload twice changes zero rows, per seam
- Turnstile: explicit failure drops the record; a verifier timeout lets it
  through and logs (law 5). Tested against a stubbed verifier, no network.

## Ian's setup

1. Cloudflare account (free) → **Turnstile** → add two widgets, one per
   domain. Each gives a site key and a secret key.
2. Vercel, btc project: `TURNSTILE_SECRET`.
   Vercel, ianmccallum project: `TURNSTILE_SECRET`, `NOTIFY_TO`,
   `RESEND_API_KEY`, `IANOS_SYNC_TOKEN`, plus an Upstash KV connected.
3. ianOS `.env`: `PERSONAL_SYNC_URL` + `PERSONAL_SYNC_TOKEN`.

Site keys are public and get committed into the HTML; secrets never do.

## As built (2026-08-14)

All three halves shipped. 353 ianOS tests pass, 7 of them new.

Verified: a personal record loads with `source='personal'`, `lead_id IS
NULL`, `promised_by IS NULL`, leaves `COUNT(*) FROM leads` unchanged, never
appears in `due_for_alert`, and renders on Inbox while the BtC tab shows only
its own seam (checked live in the browser, both surfaces).

Turnstile's failure policy is unit-tested across all seven branches: only an
explicit bot verdict rejects; unconfigured, valid, duplicate token, missing
token, Cloudflare 5xx and a thrown fetch all allow. Both btc forms build
identically with and without a site key, and `check:a2p` passes in both
states.

Deviations from the plan above:

- **One loader, not two.** The spec hedged toward generalizing
  `sync_btc.py`; it does, via a `SEAMS` table. A second near-identical
  `sync_personal.py` would have meant two places to fix the next dedupe or
  consent bug.
- **The email template gained `brand`/`slipLabel`/`foot` parameters.** A
  personal inquiry arriving under a "BEAT THE CLOCK / DISPATCH SLIP" header
  telling Ian to confirm on the BtC tab was wrong on both counts. Defaults
  are unchanged, so btc renders exactly as before.
- **An absent consent record now prints nothing** rather than "not given".
  A seam that never offers SMS never offered a choice, so reporting a
  negative would be a lie of implication.

Still on Ian: Cloudflare site keys (one per domain), the Upstash KV and env
vars on the ianmccallum Vercel project, and `PERSONAL_SYNC_*` in ianOS
`.env`. Until then everything degrades silently to its pre-v19 behaviour.

## Out of scope

- Migrating either domain's DNS to Cloudflare. Turnstile needs an account,
  not a nameserver change.
- Turnstile on the assessment or waitlist forms. Same pattern when wanted.
- Any scoring, tiering or pipeline treatment of personal inquiries. They are
  correspondence, not leads, and that is the point.
