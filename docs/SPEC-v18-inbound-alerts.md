# SPEC v18: inbound alerts, keeping the promise

## Why this exists

The site prints a promise on `/demo`: **"Ian confirms one of your windows
within 24 hours."** The contact autoresponse makes the same one. Nothing in
either repo tracks that promise, and the notification that was supposed to
start the clock has been delivering to an address Ian does not read.

Measured, 2026-08-13, against his actual Gmail:

- The **autoresponse** to the submitter arrived 1 second after submission.
  Resend works, the domain is verified, the pipe is healthy.
- The **notification** to `contact@beatyourclock.com` has never arrived in
  the inbox he reads. Zero, ever, including spam and trash. The last inbound
  notification he actually received was **June 2025**, from the retired
  FormSubmit path.
- `ingest/sync_btc.py` **is not scheduled**. It runs only when the BtC tab
  mounts or he types `make sync-btc`, so ianOS cannot alert on something it
  has not yet been told exists.
- `core/push.py` is complete and tested (ntfy / Pushover / webhook) and
  **unconfigured**. Reaching his phone is a `.env` line, not a feature.

So this is one broken delivery, one missing schedule, and one unused
capability, not a missing notification system.

## The design idea

**Good news arrives quietly. A promise about to break arrives loudly.**

An alert at t=0 lands when Ian is least able to act (on a job, in class,
driving) and when it is least urgent (24 hours of slack). By the time he can
act it has scrolled away; the attention failure mode here is evaporation from
working memory, not ignorance. Piling more t=0 pings on that makes it worse,
and it contradicts the dispatcher law that nothing nags without cause.

But an inbound demo is also genuinely good news, and the first one deserves
to arrive. So the two channels split by meaning, not by source:

| Moment | Channel | Volume | Why |
|---|---|---|---|
| It happened | Email | every time | Good news, scannable, no action demanded |
| You have not handled it and the promise expires soon | Push | near zero | The only alert carrying information he does not already have |

Near-zero volume is the point: most requests get confirmed, so the jeopardy
push almost never fires, which is exactly what keeps it un-ignorable.

## Division of labour (the load-bearing asymmetry)

- **The site is always up and knows it happened.** It can only ever do t=0.
- **ianOS knows whether Ian acted.** Only ianOS can detect jeopardy. But it
  sleeps.
- **The `ianos:unacked` set is therefore a liveness signal, free.** A record
  still unacked hours later proves ianOS has not collected it, which is the
  one case ianOS cannot self-report. That, and only that, is when the site
  escalates.

## Laws

1. **Notification routing is configuration, not source.** The notify-to
   address moves to a Vercel env var (`NOTIFY_TO`, comma-separated, falling
   back to the current `contact@beatyourclock.com`). Ian's personal inbox
   never enters the repo, and changing where alerts land never needs a
   deploy. This is the whole bug being fixed; keep it changeable.
2. **The subject line is the notification.** On a phone lock screen the
   subject is all he sees. It carries the decision: who, what, and the
   windows. `[SMS OPT-IN]` stays, it is an A2P record-keeping signal.
3. **`promised_by` is stored, not derived at read time.** A deadline that
   recomputes from "now" cannot be alerted on exactly once.
4. **UTC/local is the trap on this seam.** `received_at` arrives from the
   site as UTC ISO (`...Z`); every other timestamp in this DB is naive
   localtime (`datetime('now','localtime')`). Computing `promised_by` by
   mixing them shifts every deadline five or six hours in Central and the
   bug is invisible until an alert fires at the wrong time. Convert once,
   store `promised_by` in the same naive-local form as its neighbours, and
   assert it in a test. (Note: `IANOS_TZ` exists in `.env` but no code reads
   it. Do not start now without also making `db.today()` honour it; local
   machine time is the de-facto standard here and consistency beats a
   half-migration.)
5. **Fire once per request, ever.** `alerted_at` is stamped when the push is
   sent. Without it, a check running every 15 minutes pushes 16 times an
   hour. This is the single most likely way this feature becomes a nag.
6. **Never push between 21:00 and 08:00 local.** A promise expiring at 06:00
   alerts at 08:00, late but honest. Waking him is a worse failure than a
   late alert, and an alert he silences at 3am trains him to silence all of
   them.
7. **Push payload is name and time only.** The ntfy topic is world-readable
   (`core/push.py` says so). Never the consent record, never the message
   body, never a phone number. The SPEC-v17 consent wall extends here
   unchanged.
8. **Detection is deterministic Python, never a model.** Same law as the
   dispatcher: `should_alert()` is pure and testable, costs $0, and runs on
   a timer. Only the chief's narration is ever a model call.
9. **Unconfigured stays silent.** No push provider, no schedule, no
   `NOTIFY_TO`: everything degrades to exactly today's behaviour, no errors.

## Phase 1: fix the delivery (5 minutes, do first)

`api/demo.js` + `api/contact.js`:

- `TO_EMAIL` becomes `notifyTo()`: reads `process.env.NOTIFY_TO`, splits on
  commas, falls back to `contact@beatyourclock.com`. Used in the Resend `to`
  array; FormSubmit fallback unchanged (it posts to a fixed hash).
- Subjects become decision-carrying:
  - demo: `DEMO · Torres Plumbing · Wed 7-10a or Thu 5-8p [SMS OPT-IN]`
  - contact: `MSG · Dana Whitfield · Integrations`
  - fall back to the person's name when company/interest is blank.
- `reply_to` already carries the submitter, so replying works from the phone.

Ian adds `NOTIFY_TO` in Vercel env. Nothing else changes. This alone
converts a dead pipeline into a working one and is most of the value.

## Phase 2: give ianOS eyes (30 minutes)

- **`ops/com.ianos.btcsync.plist`**, `StartInterval 900` (15 min), running
  `ingest/sync_btc.py`, logging to `data/btcsync.log`. launchd fires a
  missed interval on wake, so a closed lid self-heals. Installed by
  `make schedule-btc`, which **refuses when unconfigured** (the
  `schedule-backup` precedent) so an unprovisioned machine can never spam
  failure memos.
- **Push configured**: `IANOS_PUSH_TOPIC` in `.env`, long and random.
- The loader stays quiet on a zero-record pull; it already is.

At the end of Phase 2, ianOS knows about a booking within 15 minutes without
Ian opening anything, and can reach his phone. Nothing alerts yet.

## Phase 3: the jeopardy alert

Schema, on `inbound_requests`:

```sql
promised_by TEXT      -- received_at + 24h, naive local (law 4)
alerted_at  TEXT      -- set when the push fires; fire-once (law 5)
```

New pure module `core/promises.py`:

```python
def due_for_alert(rows, now, lead_hours=4, quiet=(21, 8)) -> list[dict]
```

Selects rows where `status='new'`, `alerted_at IS NULL`, and `promised_by` is
within `lead_hours`, then drops anything inside quiet hours. Pure over
`(rows, now)`, so the tests drive it with no clock and no network.

`sync_btc.py` gains a post-load step: after commit and ack, evaluate
`due_for_alert`, send one push covering all of them, stamp `alerted_at`.

Push copy, blunt, numbers first:

```
ianOS: promise expiring
Torres Plumbing by 2:00 PM · Dana Whitfield by 4:00 PM
```

## Phase 4 (conditional): the site's dead-man's switch

If a record sits in `ianos:unacked` beyond a threshold, ianOS has not
collected it and cannot possibly alert. The site emails instead.

**Verify before building:** Vercel's Hobby plan limits cron to roughly once
per day, which makes this a daily backstop rather than a 6-hour escalation.
A daily backstop is still worth having (it catches a laptop that died on
vacation) but do not spec an hourly escalation that the plan will not run.
Build this only after Phases 1 to 3 are live and only if Ian will be away
from the Mac for stretches.

## Tests (`tests/test_promises.py`)

- `promised_by` is exactly 24h after a UTC `received_at`, expressed in local
  time (law 4). This is the test that would have caught a five-hour bug.
- fire-once: two consecutive checks over the same row alert once (law 5)
- quiet hours: a promise expiring 06:00 does not alert at 02:00; it alerts at
  08:00 (law 6)
- confirmed and dismissed rows never alert
- the push payload contains no consent field, no message body, no phone
  (law 7), asserted with the SPEC-v17 sentinel
- unconfigured push: `due_for_alert` still computes, nothing is sent, no
  exception (law 9)

## Ian's setup

1. Vercel env: `NOTIFY_TO=<the inbox he actually reads>` then redeploy.
2. ianOS `.env`: `IANOS_PUSH_TOPIC=<long random>`, install the ntfy app,
   subscribe to that exact topic.
3. `make schedule-btc`.

## As built (2026-08-13)

Phases 1 to 3 shipped and verified. Phase 4 deliberately not built.

**Verified live:** a probe row with a promise expiring in 2 hours produced a
real push on the phone, stamped `alerted_at`, and the second run alerted 0
(fire-once held). `make schedule-btc` installs and the job runs on load.
347 tests pass, 13 of them new.

**Two bugs found while building, both pre-existing and both bigger than this
spec:**

- `core/push.py` used `urllib`, which verifies against the system trust
  store that macOS python builds leave empty. Every push died with
  `CERTIFICATE_VERIFY_FAILED` and `send()` returned `False`, so a
  misconfigured push and a working one were indistinguishable. **The nightly
  Day Command push in docs/PHONE.md would never have worked on this machine
  either.** Fixed with certifi's bundle (the one `requests` already relies
  on), falling back to system default when certifi is absent.
- `ingest/sync_chase.py` and `ingest/setup_simplefin.py` carry the identical
  bug. Not fixed here: that is the money write boundary, SimpleFIN is not
  currently configured so the fix cannot be verified against the live API,
  and widening a notification spec into the transactions seam is exactly the
  scope creep the data skill warns about. Filed separately.

**Deviations from the plan above:**

- The brainstorm proposed a dispatcher `TRIPWIRES` entry. Wrong mechanism:
  tripwires wake *agents* at 21:30, but a promise can expire at any hour.
  The check lives in the sync job instead, which is where the 15-minute
  cadence already is. Still deterministic Python, still $0.
- Rows created before this migration have `promised_by = NULL` and are
  excluded by `pending_promises`. The feature never retroactively alerts on
  requests that predate it, which is the correct behaviour and worth keeping.

## Out of scope, deliberately

- Confirming a demo by replying to the email. Tempting, and a whole inbound
  parsing surface; the phone card is two taps and already exists.
- Any digest, daily summary, or "you have N pending" counter. That is a
  backlog, and this product does not do backlogs.
- Alerting on anything other than a promise with a real deadline. If a future
  alert has no expiry, it does not belong in this system.
- SMS to Ian. He is registering A2P for outbound customer messaging; mixing
  his own ops alerts into that number muddies the campaign.
