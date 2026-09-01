# ianOS on your phone

A real app icon on your home screen, opening full-screen, that **works with your
Mac asleep**. No App Store, no $99 developer program, no cloud bill. Total: $0.

Your Mac stays the server, so all 1,958 leads, your journal, and every memo stay
on your machine, nothing moves to anyone else's computer.

---

## Step 1: turn it on (on the Mac, once ever)

```bash
make phone
```

It generates a private token (once, into `.env`), builds the app, hands serving
to **launchd**, and prints the URL to install. You can close the terminal, the
server is not tied to it.

From then on ianOS is reachable **the whole time the Mac is awake**, and starts
again by itself after a reboot or a crash. Asleep, the phone falls back to its
cached view; on wake it reconnects with no action from you, because the
Tailscale address never changes.

```bash
make phone-status   # is it up? what does the log say?
make phone-off      # stop serving and leave the tailnet
```

## Step 2, install it (on the iPhone)

1. **Delete any old ianOS icon first.** iOS caches the address and artwork
   behind an installed icon, so re-adding on top of an old one keeps the old one.
2. Open **Safari**, not Chrome, and go to the URL `make phone` printed.
3. Tap **Share ⬆️ → Add to Home Screen → Add**.
4. Open ianOS from the home screen from now on. **No URL, no token, ever again** : 
   it remembers.

> Safari is required for the install step; Chrome on iOS can't add to the home
> screen. Give it one launch on wifi before relying on it offline, the service
> worker caches the shell on first run.

## Step 3. Tailscale (free, and it is not really optional)

Tailscale is usually sold as "reach your Mac from anywhere," and it does that.
But it fixes something more important: **iOS will not register a service worker
over plain `http://`.** On a LAN IP the app runs, but the offline cache and the
write queue silently don't, the whole "works with the Mac asleep" promise is off.
Tailscale gives you a real `https://` certificate, which makes it a secure
context, which turns the offline half of the app on.

1. Install [Tailscale](https://tailscale.com) (free personal plan) on **the Mac
   and the iPhone**, signed into the same account.
2. Enable HTTPS once, at
   [login.tailscale.com/admin/dns](https://login.tailscale.com/admin/dns) →
   **HTTPS Certificates → Enable**. (MagicDNS must be on; it is by default.)
3. Re-run `make phone`. It now prints an `https://<your-mac>.ts.net/?token=…`
   URL. Install *that* one to your home screen.

Nothing is exposed to the public internet: `tailscale serve` is tailnet-only,
i.e. only devices signed into your own account. ianOS never enables
`tailscale funnel`, which is the public one. `make phone-off` removes the tunnel.

> **Why the script self-checks the tunnel:** Tailscale connects to the app *from
> 127.0.0.1* on your phone's behalf. Loopback normally means "Ian, at his Mac" :
> no token needed, journal unlocked. So the API treats any request carrying
> proxy headers (`X-Forwarded-For`, `Tailscale-User-Login`, …) as remote no
> matter where it dials from, and `make phone` refuses to print the URL unless
> an unauthenticated request through the tunnel actually comes back `401`.

---

## Step 4. Lock screen (Face ID)

SPEC-v12 ([docs/SPEC-v12-lock-screen.md](SPEC-v12-lock-screen.md)). The
installed app shows a lock before any Command / Journal UI. This is a
**privacy curtain on the device**, not a replacement for the LAN token.

The lock shows the brand mark, a **Central Time** clock (12-hour + date),
then unlock.

**Password (always works):** `ianos`

**Face ID setup (once):**

1. You must be on the Tailscale **`https://`** install URL. Plain
   `http://192.168…` cannot use WebAuthn, so Face ID will not appear.
2. Open ianOS from the **home screen**.
3. Unlock with password `ianos`.
4. When asked **Enable Face ID**, tap it and approve the system sheet.
5. Next cold open (or after ~90s in the background): tap **Face ID**.

Mac localhost / Touch ID: same flow if the browser offers a platform
authenticator. Otherwise password only.

To reset Face ID enrollment on a device, clear site data for ianOS (or wipe
`localStorage` key `ianos.lock.cred.v1`) and unlock with the password again.

---

## Brand & icons

| Source | Role |
|---|---|
| `dashboard/public/ianOS.jpg` | App icon art (square). Regenerated into PNGs. |
| `dashboard/public/logo.png` | Site logo source (transparent wordmark). |
| `dashboard/public/logo-lockup.png` | Trimmed lockup used in nav, boot, lock (from `make icons`). |
| `dashboard/public/icons/*.png` | Favicon, apple-touch, 192/512, maskable 512. |

```bash
make icons    # or: .venv/bin/python scripts/make_icons.py
```

`make phone` always regenerates icons before the production build. Desktop
nav shows the lockup plus a **⌘K** chip that opens the command palette.

### Updating the app icon on the phone

iOS **freezes** home-screen artwork at install time. New PNGs on the server
do not refresh an already-installed icon.

1. `make phone` (rebuilds icons + dist).
2. **Delete** the old ianOS home-screen icon.
3. Open the Tailscale `https://…` URL in **Safari**.
4. Share → Add to Home Screen → Add.
5. Open from the new icon.

Pull-to-refresh updates the in-app UI only, not the home-screen icon.

---

## What happens when your Mac is asleep

This is the part that matters, and it's already handled:

| | |
|---|---|
| **Opening the app** | Loads instantly from cache. A banner says *"Showing your last synced view. 2h ago. Your Mac is asleep."*, you're never fooled by stale numbers. |
| **Tapping things** | Gym confirm, +1 calls, sleep, energy, notes are stored on the phone and replayed automatically the moment your Mac is reachable. You'll see *"synced 3 offline entries."* |
| **Nothing is lost** | Captures are stamped to the DAY, so a 2pm gym tap that syncs at 6pm still counts for today. |
| **Tomorrow's command** | Pushed to your phone at 21:30 while the Mac is awake (see below), it's on your lock screen even if the laptop never opens. |

What *doesn't* work asleep: anything needing live data, running The Line,
approving a proposal, fresh lead lists. Those wait until the Mac is up.

---

## Optional: get the Day Command pushed to your phone

Add **one** of these to `.env`, and the nightly run sends tomorrow's command at 21:30:

```bash
# Free, no account, install the "ntfy" app, subscribe to this exact topic
IANOS_PUSH_TOPIC=ianos-<make-this-long-and-random>

# Or private ($5 one-time): https://pushover.net
IANOS_PUSHOVER_TOKEN=...
IANOS_PUSHOVER_USER=...
```

**Privacy:** on ntfy's public server anyone who guesses your topic name can read
it, so make the topic long and random, and ianOS only ever pushes the Day
Command, never journal text or lead details. Pushover is the private option.

Unset both and nothing is pushed; no errors.

---

## Security

- **Localhost** (your Mac's own browser) needs no token, nothing changes for `make dev`.
- **Anything else** (your phone, or a stranger on dorm wifi) must present the token.
  Verified: a request without it gets `401`.
- **Your journal works on the phone** with the same token (SPEC-v11). Agents still
  never see the words or photos, only that you closed the day (unless you tap Share).
- **Lock screen (SPEC-v12)** is a client-side curtain (Face ID / password
  `ianos`). It does not replace the token; anyone who can hit the API
  still needs `IANOS_API_TOKEN`.
- The token lives in `.env`, which is gitignored.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Phone can't reach the URL | Same wifi? Mac awake? Is `make phone` still running? |
| "401" in the browser | Use the full URL *with* `?token=…` for the first visit. |
| App looks stale | That's the point, check the banner. It refreshes when the Mac is up. |
| Changed the dashboard code | Re-run `make phone` (it rebuilds), then pull-to-refresh twice on the phone. |
| New app icon / logo | `make icons` (or `make phone`), then **delete** the home-screen icon and Add to Home Screen again. iOS will not refresh artwork in place. |
| Want a fresh token | Delete the `IANOS_API_TOKEN` line from `.env`, run `make phone`, re-install. |
| No Face ID button | Need HTTPS (Tailscale). On LAN HTTP, use password `ianos`. |
| Face ID stopped working | Clear site data or delete `ianos.lock.cred.v1`, unlock with password, re-enable. |
| Stuck on lock after code change | Bust the SW cache (`?nocache=1`) or re-run `make phone`. |

## Keeping the Mac awake (worth doing in the dorm)

Plugged in on your desk, System Settings → Displays → Advanced → *Prevent
automatic sleeping on power adapter*. Then the app is live whenever you're on
wifi, and the offline layer is just insurance.
