# Manual phone capture: iPhone Shortcuts → ianOS

Log gym / sleep / a note from your lock screen without opening the laptop lid.
The laptop must be awake on the same wifi. Everything is optional sugar on top
of the dashboard's Confirm-gym button, miss a sync and nothing breaks.

## One-time setup

1. On the Mac, in the ianOS folder:
   ```
   make api-lan
   ```
   It generates a token into `.env` (once), prints your laptop's LAN IP + the
   bearer token, and serves the API on the wifi. Leave it running (or add it to
   `make dev` when you want phone capture).

2. It prints something like:
   ```
   URL:    http://192.168.1.x:8787/api/quick
   Header: Authorization: Bearer <token>
   ```

## The three manual shortcuts (iPhone → Shortcuts app → new Shortcut → "Get Contents of URL")

For each: **Method** POST · **Request Body** JSON · add a **Header**
`Authorization` = `Bearer <token>`.

- **Gym ✓**. Body `{"gym": true}`. Add to your Lock Screen / Home Screen.
- **Sleep**. Body `{"sleep": <Ask Each Time, Number>}`.
- **Note**. Body `{"note": "<Ask Each Time, Text>"}`.

You can send any combination in one call:
`{"gym": true, "sleep": 7.5, "energy": 4, "workout": "mma", "steps": 9200, "note": "..."}`

**Show the reward:** after the URL step, add "Show Notification" with the
Shortcut's result: the API replies with a line like
`Streak 12 · stool bank 2 · garden thriving`. That notification IS the payoff.

### Apple Watch automation is a separate route

Do **not** point a scheduled Apple Health automation at `/api/quick`. That
endpoint is intentionally for tiny, manual actions and can increment a manual
workout log. The source-aware Apple Watch path uses
`POST /api/health/snapshots`, stable snapshot identities, and replacement
semantics so a retry cannot inflate a day.

### Secure v35 pairing test (Apple Health → ianOS)

Ian's ianOS Phone PWA and Tailscale route are already installed. This is not a
phone-installation guide. After pulling a health-capture update, run `make
phone` once on the Mac to restart the private server and create the dedicated
health credential. It does not require reinstalling the Home Screen app.

On the **installed ianOS app on the iPhone**, go to **Body → Set up capture**.
The setup Sheet supplies the private test endpoint, a live activity endpoint,
a health-only capture token, and the paired installation ID. It never exposes
the broad ianOS app token.

Create the small connection test in Shortcuts:

1. Create a shortcut named **ianOS Health test**.
2. Add **Get Contents of URL** and paste the copied test endpoint.
3. Set its method to **POST**.
4. Add header `Authorization` with value `Bearer <copied health capture token>`.
5. Add **Show Result** and run it.

`ready` means the Shortcut reached ianOS through the private route. The test
writes **no health data**. Do not put the token in a URL, note, or generic
shortcut; it can reach only `/api/health/snapshots` and is tied to the one
paired installation ID.

### First real capture: today's Steps

Keep this in the **same** `ianOS Health Sync` Shortcut; it will eventually
contain sleep, steps, and workouts, not one Shortcut per metric.

1. Add **Find Health Samples**: Type = **Steps**, Start Date = **Today**,
   Group By = **Day**, and leave Limit off. Add **Get Details of Health
   Sample** = **Value**. A Quick Look should now show the total from Health,
   not one tiny raw step sample.
2. In the request body below, use Shortcuts' built-in **Current Date**
   variable for the run ID. It changes each time the Shortcut runs; do not
   type an ID yourself.
3. Add **Get Contents of URL** using the copied **Live activity endpoint**.
   Set Method = **POST** and header `Authorization` = `Bearer <Health capture
   token>`.
4. Set Request Body = **JSON** and add these fields using Shortcuts' blue
   Magic Variable picker (do not type the brackets):

   | JSON key | Value |
   | --- | --- |
   | `capture_id` | the built-in Current Date variable |
   | `steps` | the Value from Get Details of Health Sample |

5. Add **Show Result**. `accepted` means ianOS saved today's clearly-labelled
   in-progress step total; `replayed` means a safe retry, not a duplicate.

The Shortcut sends only the aggregate number. The server supplies the paired
installation, Central time, current date, provenance, and idempotency envelope
before it reaches the canonical snapshot writer. It never calls `/api/quick`.

The same Shortcut will later add the daily `Find Health Samples` summaries for
sleep and workouts. Exact Health action fields vary by iOS version and must be
tested on Ian's actual iPhone before enabling a daily automation. Until that
real-device validation is complete, do not call a scheduled workflow automatic
or use `/api/quick` for sensor data.

## Security

- Localhost (the dashboard on your Mac) is fully trusted, no token needed there.
- The LAN endpoint refuses every request without the bearer token, and refuses
  all LAN access entirely if `IANOS_API_TOKEN` is unset. Dorm wifi is shared;
  this keeps your data private. Never expose the API beyond the LAN (no tunnels).

## Offline path (laptop asleep)

If the laptop is unreachable, capture into a note instead: keep a "quick add to
ianOS" note on your phone and jot `gym`, `sleep 7`, etc. Later, in a `claude`
session in the repo, paste it and say "replay these into ianOS via /api/quick" : 
it will POST each one. No data lost, no code needed.
