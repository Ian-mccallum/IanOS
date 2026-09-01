# SPEC-v12: Lock screen (Face ID + password)

**Status:** shipped (2026-08).

A client-side privacy curtain for the installed ianOS PWA. Not network auth.
The LAN token still gates the API. This gate keeps the UI blank until Ian
unlocks on this device.

Operator how-to: [PHONE.md](PHONE.md) Step 4. Brand / home-screen icons: same
doc, "Updating the app icon."

---

## Why

Phone on a desk, hand a friend the device, open Journal by accident: the
installed app is a real surface with real life in it. Face ID (WebAuthn
platform authenticator) is the primary unlock. Password `ianos` is the
always-available manual path when biometrics are unavailable, not enrolled,
or fail.

This is **not** a substitute for Tailscale HTTPS or `IANOS_API_TOKEN`.

---

## Non-goals

- Server-side password verification
- Encrypting SQLite or journal files at rest
- Silent Face ID with zero tap (iOS requires a user gesture for WebAuthn)
- Locking `localhost` differently from phone (same curtain everywhere)

---

## Feel

One screen, one job: unlock.

- Deep near-black + Aurora (same shell atmosphere as boot)
- **Huge** brand lockup (`logo-lockup.png`)
- Clock in **America/Chicago**, **12-hour** US format with seconds + AM/PM
- Full date under the clock (`weekday, month day`)
- One primary action in the thumb zone
- No apology copy. Failures soften (`--warn`); never `--crit`
- Motion: 200ms / 320ms, respect `prefers-reduced-motion`
- Safe-area insets mandatory (osUI L9)

---

## Flows

### Cold open / re-lock

1. Shell paints Aurora + lock (no Command, **no `/api/state` poll** yet).
2. If a platform credential is enrolled and WebAuthn is available:
   primary CTA is **Face ID** (label adapts: Face ID / Touch ID / Biometrics).
3. Else password field is primary.
4. Success → session marked unlocked → `fetchState` begins → app shell.

### First Face ID enroll

After a successful password unlock, if biometrics are available and no
credential is stored yet, offer **Enable Face ID** once. Decline is fine;
password keeps working. Enroll is a WebAuthn `create()` with
`authenticatorAttachment: 'platform'` and `userVerification: 'required'`.

### Background re-lock

If the document is hidden for **≥ 90 seconds**, clear the unlock session and
drop in-memory state. Brief app switches do not nag. Killing the PWA clears
`sessionStorage`, so the next open is locked.

### Manual password

Constant `ianos`. Compared client-side as
`SHA-256("ianos.lock.v1|" + input)` against a baked hash in `lib/lock.js`.
Never sent to the API. Never logged. The literal secret does not appear in
`lock.js` (tests assert this).

---

## Architecture

| Piece | Role |
|---|---|
| `dashboard/src/lib/lock.js` | capability checks, WebAuthn create/get, password verify, session + bg re-lock |
| `dashboard/src/components/LockScreen.jsx` | full-bleed lock UI (clock + date + CTAs) |
| `App.jsx` | gate: lock before boot/state; start refresh only when unlocked; clear state on re-lock |
| localStorage `ianos.lock.cred.v1` | credential id (base64) after enroll |
| sessionStorage `ianos.lock.session.v1` | unlock flag for this browsing session |
| `tests/test_lock_screen.py` | static gates (modules wired, hash contract, no `--crit` on lock CSS) |

**Trust model:** WebAuthn success with `userVerification` is the biometric
gate. There is no server attestation check: Face ID *is* the check. The
password is a local shared secret on a single-user device.

**Secure context:** WebAuthn requires HTTPS or localhost. On plain LAN
`http://192.168…` Face ID is unavailable → password only. Tailscale HTTPS
is already required for the service worker ([PHONE.md](PHONE.md)).

---

## Operator checklist (for Face ID to work)

1. ianOS installed from an **`https://`** Tailscale URL (`make phone`), not LAN HTTP.
2. Open from the **home screen** (standalone), not a Safari tab (tab works on
   HTTPS too, but the product target is the PWA).
3. Unlock once with password `ianos`.
4. Tap **Enable Face ID** when offered; approve the system sheet.
5. Next open: tap Face ID → scan.

If Face ID never appears: insecure context, or the device has no platform
authenticator, or enroll was skipped. Password still unlocks.

---

## Design law

- osUI L1-L9 apply. Lock is phone-first.
- `--crit` banned on this surface.
- Zero-value pixels banned: no "secured by WebAuthn" subtitle.
- Does not weaken journal agent privacy; it adds a human-facing curtain.

## Related

- [PHONE.md](PHONE.md): install, Tailscale, lock setup, icon refresh
- [SPEC-v11-journal-delight.md](SPEC-v11-journal-delight.md): journal on phone
- [SPEC-v10-osui.md](SPEC-v10-osui.md): mobile UI law
- `SPEC-IPHONE.md` Phase 4 "optional Face ID" is superseded for the **PWA** by this
  spec (native Swift Face ID remains a future native-app item)
