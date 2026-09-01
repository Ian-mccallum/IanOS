# ianOS iPhone App. Implementation Specification

**Version:** 1.0  
**Status:** Ready for implementation  
**Audience:** AI coder / implementer  
**Scope:** Native iOS companion app for ianOS. HealthKit ingest, quick-log, Day Command glance, goal CRUD, proposal approval. Mac remains agent HQ; phone becomes the daily input device.

**Prerequisites:** [SPEC-LIFE-OS.md](SPEC-LIFE-OS.md) (implemented), [GOALS.md](GOALS.md) (goals reference)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Why Native iOS](#2-why-native-ios)
3. [Apple Developer & Distribution](#3-apple-developer--distribution)
4. [Architecture Overview](#4-architecture-overview)
5. [Sync Modes](#5-sync-modes)
6. [HealthKit Integration](#6-healthkit-integration)
7. [Screen Specifications](#7-screen-specifications)
8. [Widgets & Live Activities](#8-widgets--live-activities)
9. [API Client](#9-api-client)
10. [Local Data Model](#10-local-data-model)
11. [Security & Privacy](#11-security--privacy)
12. [Design System](#12-design-system)
13. [Project Structure](#13-project-structure)
14. [Implementation Phases](#14-implementation-phases)
15. [Acceptance Criteria](#15-acceptance-criteria)
16. [Out of Scope (v1)](#16-out-of-scope-v1)

---

## 1. Executive Summary

### What we're building

A **SwiftUI iPhone app** (`ianOS`) that lets Ian:

1. **Read** today's Day Command, brief, and goal status in under 10 seconds
2. **Log** business activity and wellness in under 5 seconds
3. **Approve/reject** agent proposals from his pocket
4. **Add/edit goals** (same fields as dashboard, see GOALS.md)
5. **Sync HealthKit** sleep, steps, and workouts automatically: no CSV export ritual

Agents still run on Mac (`make run`). The phone is not a second brain; it's the **sensor + remote control**.

### What already exists (reuse, don't rebuild)

| Component | Location | iPhone uses |
|-----------|----------|-------------|
| FastAPI | `api/main.py` :8787 | HTTP client target |
| Goal CRUD | `POST/PATCH/DELETE /api/goals` | Same contract |
| Wellness log | `POST /api/wellness` | Same contract |
| Activity log | `POST /api/activity` | Same contract |
| Full state | `GET /api/state` | Brief, goals, proposals |
| Proposal decide | `POST /api/proposals/{id}/decide` | Same contract |
| Health schema | `health_daily` table | Sync target |
| Metrics engine | `core/metrics.py` | Server-side only |

### North star (mobile)

> Ian glances at Day Command before a sales call, logs a demo in the parking lot, and wakes up to sleep actuals already in ianOS, without opening his laptop.

### Non-negotiables (from PRODUCT.md)

1. Two-minute sessions, three taps max for any log action
2. Numbers are the interface. Day Command and hero metrics dominate
3. Agents propose; Ian approves, same loop as dashboard
4. Local-first, app works offline for logging; syncs when reachable
5. No third-party analytics or cloud account required for v1

---

## 2. Why Native iOS

| Approach | HealthKit | Background sync | Push/widgets | Verdict |
|----------|-----------|-----------------|--------------|---------|
| **SwiftUI + HealthKit** | Full | BGAppRefresh + observer queries | Native | **Chosen** |
| Capacitor/React Native | Plugin required | Fragile | Plugin | Reject |
| PWA | None | None | Limited | Reject for health |
| Shortcuts-only | Indirect | Manual | None | Complement, not app |

There is **no Apple Health REST API**. HealthKit is the only first-class path to live health data on iPhone.

---

## 3. Apple Developer & Distribution

### Ian's options (personal use)

| Tier | Cost | Devices | Cert lifetime | Use case |
|------|------|---------|---------------|----------|
| Free Apple ID | $0 | 1 (your iPhone) | ~7 days | Dev/prototype on own phone |
| Apple Developer Program | $99/year | 100 registered/year | 1 year | TestFlight, stable installs |
| App Store | $99/year | Unlimited public | 1 year | Future if desired |

**Recommendation:** Start with **free Apple ID + Xcode** for Phase 0-2. Upgrade to paid program when daily-driver stability matters (~7-day reinstall is annoying).

### Capabilities to enable

- HealthKit (read: sleep, steps, workouts, heart rate optional)
- Background Modes → Background fetch
- App Groups → share data with widget extension
- Push Notifications → Phase 4 (optional)

### Bundle ID

```
com.ianmccallum.ianos
```

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  iPhone: ianOS.app (SwiftUI)                               │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐ │
│  │ HealthKit   │  │ Local SQLite │  │ APIClient           │ │
│  │ Observer    │→ │ (pending     │→ │ Tailscale / LAN     │ │
│  │ Queries     │  │  sync queue) │  │ http://mac:8787     │ │
│  └─────────────┘  └──────────────┘  └─────────────────────┘ │
│  ┌─────────────┐  ┌──────────────┐                          │
│  │ Widget ext  │  │ Notifications│                          │
│  │ Day Command │  │ (Phase 4)    │                          │
│  └─────────────┘  └──────────────┘                          │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS or HTTP over Tailscale
┌──────────────────────────▼──────────────────────────────────┐
│  Mac: ianOS (existing)                                     │
│  FastAPI :8787 · SQLite data/ianos.db · make run (agents)   │
└─────────────────────────────────────────────────────────────┘
```

### Responsibility split

| Concern | iPhone | Mac |
|---------|--------|-----|
| HealthKit read | ✓ |: |
| Agent runs |: | ✓ |
| Goal storage (source of truth) | Mirror | ✓ |
| Quick-log queue | ✓ (offline) | Receives via API |
| Brief composition | Display | ✓ (chief) |
| Financial sync | Display only | ✓ (SimpleFIN/SnapTrade) |

---

## 5. Sync Modes

### Mode A: Home LAN (Phase 1, simplest)

- Mac runs `make dev` or API as launchd service
- iPhone on same Wi‑Fi hits `http://<mac-hostname>.local:8787`
- API CORS extended to allow iOS app (or app bypasses CORS, native URLSession)

**Mac API change required:**

```python
# api/main.py, add to allow_origins or use allow_origin_regex for LAN
allow_origins=["http://localhost:5173", "ianos://"],
# OR: allow_credentials + middleware that accepts LAN IPs in dev
```

Better: add optional `IANOS_API_TOKEN` env var; iPhone sends `Authorization: Bearer <token>`.

### Mode B: Tailscale (Phase 2, anywhere)

- Install Tailscale on Mac + iPhone
- iPhone hits `http://100.x.x.x:8787` (stable tailnet IP)
- No port forwarding, encrypted mesh VPN
- **Recommended daily-driver path**

### Mode C: iCloud / CloudKit sync (Phase 3, optional)

- Phone holds full SQLite replica
- CloudKit syncs `health_daily`, `activity`, pending logs
- Mac pulls via separate sync daemon
- Only needed if Mac is often offline; defer until Mode B proves insufficient

### Offline behavior

1. User logs activity/wellness → writes to local `pending_sync` table
2. On network restore, `SyncEngine` POSTs to Mac API
3. Conflict: server wins for goals/briefs; client wins for same-day health/activity (latest timestamp)
4. UI shows sync status dot: green (live), amber (queued), red (unreachable)

---

## 6. HealthKit Integration

### Read permissions (v1)

| HealthKit type | HKQuantity/Category | Maps to `health_daily` |
|----------------|---------------------|------------------------|
| Sleep Analysis | `HKCategoryTypeIdentifier.sleepAnalysis` | `sleep_hours` (sum asleep Core+Deep+REM) |
| Step Count | `HKQuantityTypeIdentifier.stepCount` | `steps` |
| Workout | `HKWorkoutType` | `workouts` (+1), `workout_mins` (duration) |

Optional v1.1: `activeEnergyBurned`, `heartRateVariabilitySDNN` (not in schema yet).

### Sync strategy

```swift
// On app launch + BGAppRefresh (~every 15-60 min)
1. Request authorization (once)
2. Observer query on sleep, steps, workouts
3. For each day since last_sync_date:
   - Aggregate sleep hours (handle timezone: America/Chicago)
   - Sum steps for calendar day
   - Count workouts, sum minutes
4. POST /api/wellness per day OR batch endpoint (see §9.4)
5. Store last_sync_date in UserDefaults
```

### Sleep aggregation rules

- Use **local calendar day** (Ian is US Central)
- Sum `asleep` samples only; exclude `inBed`
- If no data for a day, do not overwrite manual entries on server (use `replace: false`)

### Authorization UX

- Request on first visit to Health tab, not app launch
- Explain: "ianOS reads sleep and steps so physician agent can track your goals. Data stays on your devices."
- If denied: show manual log fallback (same as dashboard wellness strip)

### No write to HealthKit in v1

IanOS reads only. Workout logging goes to ianOS API, not HealthKit write.

---

## 7. Screen Specifications

### Tab bar (4 tabs)

| Tab | Icon | Purpose |
|-----|------|---------|
| **Command** | `sun.max` | Day Command + brief headline + domain status pills |
| **Goals** | `target` | Goals by domain, CRUD, hero toggle |
| **Log** | `plus.circle` | Business + wellness quick-log |
| **Inbox** | `tray` | Pending proposals + recent memos (collapsed) |

### 7.1 Command (home)

**Layout (top → bottom):**

1. **Day Command**, largest text, full width, domain accent border
2. **Domain pills**. BUSINESS / FINANCE / HEALTH / PERSONAL with status color
3. **Hero metrics row**, one number per focused domain (from `goals_by_domain` + heroes)
4. **Brief excerpt**, first 3 lines of today's brief, "Read full" expands
5. **Sync status**, last sync time, tap to force refresh

**Pull to refresh** → `GET /api/state`

**Empty state:** "No brief yet, run agents on Mac (`make run`)"

### 7.2 Goals

- Segmented control: domain filter (ALL | BUSINESS | FINANCE | HEALTH | PERSONAL)
- List rows: name, actual/target, status chip, T-minus if deadline
- Tap row → edit sheet (mirrors dashboard GoalForm fields)
- FAB **+** → new goal sheet
- Swipe delete with confirm

Field parity with [GOALS.md](GOALS.md) §4.

### 7.3 Log

Two sections, single screen, no navigation:

**Business** (horizontal steppers):
- Audit calls | Follow-ups | Demos | Conversations
- Optional note field
- **LOG** button → `POST /api/activity` (increment mode)

**Wellness**:
- Sleep hours (decimal stepper or picker)
- Energy 1-5 (segmented)
- Workout toggle + minutes
- **LOG** button → `POST /api/wellness`

Success: haptic + toast "Logged" + update local state.

### 7.4 Inbox

- Pending proposals first (from `state.proposals` where status=PENDING)
- Each card: agent role color, action, reasoning, APPROVE / REJECT
- Reject → optional note sheet
- Below: last 5 memos (read-only, tap to expand)

---

## 8. Widgets & Live Activities

### Widget: Day Command (Phase 3)

- **Small:** Day Command text only (truncated)
- **Medium:** Day Command + 2 hero metrics
- **Lock screen:** Day Command one line

Data via App Group shared `UserDefaults` or small SQLite; widget reads cached last `GET /api/state` response.

Refresh: `WidgetCenter.reloadTimelines` after successful sync.

### Live Activities (Phase 4, optional)

- Active only during Ian-set "focus block" (future)
- Shows current quota progress (calls today vs 20)
- Defer until Log tab is stable

### Push notifications (Phase 4)

| Trigger | Source | Message |
|---------|--------|---------|
| New brief ready | Mac webhook → APNs | "Day Command: …" |
| Proposal pending >24h | Mac cron | "3 proposals waiting" |
| OFF TRACK deadline | watchdog on Mac | "LLC filing T-3d" |

Requires: Mac-side `notify.py` posting to APNs. Out of v1 scope but spec the hook.

---

## 9. API Client

### Base configuration

```swift
struct APIConfig {
    var baseURL: URL          // UserDefaults: "http://100.x.x.x:8787"
    var token: String?        // Optional IANOS_API_TOKEN
}
```

### Endpoints used (v1)

| Method | Path | Body | Notes |
|--------|------|------|-------|
| GET | `/api/state` |: | Primary data fetch |
| POST | `/api/goals` | `GoalIn` | Create |
| PATCH | `/api/goals/{id}` | `GoalIn` partial | Update |
| DELETE | `/api/goals/{id}` |: | Delete |
| POST | `/api/activity` | `ActivityAdd` | Increment counts |
| POST | `/api/wellness` | `WellnessAdd` | Upsert today |
| POST | `/api/proposals/{id}/decide` | `{decision, note}` | Approve/reject |

### 9.1 Mac API additions (implement on Mac first)

**`GET /api/health`**, connectivity check
```json
{ "ok": true, "version": "1.0", "today": "2026-07-13" }
```

**`POST /api/wellness/batch`** (optional Phase 2), backfill HealthKit history
```json
{
  "days": [
    { "date": "2026-07-12", "sleep_hours": 7.2, "steps": 8400, "workouts": 1, "workout_mins": 45, "source": "healthkit" }
  ],
  "replace": false
}
```

**Auth middleware** (Phase 2):
- If `IANOS_API_TOKEN` set in `.env`, require `Authorization: Bearer <token>`
- If unset, behave as today (localhost trust model)

**CORS / bind:**
- `uvicorn api.main:app --host 0.0.0.0 --port 8787` for LAN/Tailscale
- Document in README, never expose raw to public internet without token

### 9.2 Swift models

Generate from existing Pydantic shapes or hand-write `Codable` structs matching `GET /api/state` response. Key types:

- `AppState`, `Goal`, `Proposal`, `Brief`, `HealthDaily`, `FocusAllocation`

### 9.3 Error handling

| HTTP | User message |
|------|--------------|
| Network unreachable | "Mac offline: saved locally" |
| 401 | "Check API token in Settings" |
| 409 | "Goal name already exists" |
| 5xx | "Server error: try again" |

---

## 10. Local Data Model

### `pending_sync` (SQLite via GRDB or SwiftData)

```sql
CREATE TABLE pending_sync (
    id INTEGER PRIMARY KEY,
    endpoint TEXT NOT NULL,
    body_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    retries INTEGER DEFAULT 0
);
```

### `state_cache`

```sql
CREATE TABLE state_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
```

Show cached state when offline. Stale badge if `fetched_at` > 4 hours.

---

## 11. Security & Privacy

1. **Health data** never leaves Ian's devices except Mac SQLite (his machine)
2. **No cloud backend** in v1. Tailscale encrypts transit
3. **API token** stored in iOS Keychain
4. **HealthKit** usage string: plain language, no tracking disclosure needed (no tracking)
5. **App Transport Security:** allow local network exception for `*.local` and Tailscale IPs in Info.plist
6. **Face ID** app lock for the **PWA** is shipped as SPEC-v12 (WebAuthn +
   password `ianos`). See `docs/SPEC-v12-lock-screen.md` and `docs/PHONE.md`.
   Native Swift Face ID (this document's Phase 4) remains a future native-app item.

---

## 12. Design System

Match dashboard mission-control aesthetic (PRODUCT.md):

| Token | Value | Use |
|-------|-------|-----|
| Background | `#0a0e14` | App background |
| Panel | `#121820` | Cards |
| Business | `#f59e0b` | Domain accent |
| Finance | `#22c55e` | Domain accent |
| Health | `#2dd4bf` | Domain accent |
| Personal | `#a78bfa` | Domain accent |
| ON TRACK | `#22c55e` | Status |
| AT RISK | `#f59e0b` | Status |
| OFF TRACK | `#ef4444` | Status |
| NO DATA | `#64748b` | Status |
| Font | SF Mono for numbers, SF Pro for prose | Instrumentation feel |

**Motion:** subtle scale on log success; no decorative animation.

**Haptics:** `.success` on log, `.warning` on reject proposal.

---

## 13. Project Structure

```
ios/
├── ianOS.xcodeproj
├── ianOS/
│   ├── ianOSApp.swift
│   ├── ContentView.swift
│   ├── Views/
│   │   ├── CommandView.swift
│   │   ├── GoalsView.swift
│   │   ├── GoalFormView.swift
│   │   ├── LogView.swift
│   │   └── InboxView.swift
│   ├── Services/
│   │   ├── APIClient.swift
│   │   ├── SyncEngine.swift
│   │   ├── HealthKitManager.swift
│   │   └── LocalStore.swift
│   ├── Models/
│   │   └── StateModels.swift
│   ├── Design/
│   │   └── Theme.swift
│   └── Resources/
│       ├── Info.plist
│       └── ianOS.entitlements
├── ianOSWidget/
│   └── DayCommandWidget.swift
└── README.md
```

---

## 14. Implementation Phases

### Phase 0: Mac API hardening (1 day)

- [ ] `GET /api/health`
- [ ] Bind `0.0.0.0`, document Tailscale setup
- [ ] Optional `IANOS_API_TOKEN` auth middleware
- [ ] `POST /api/wellness` accepts `date` field for backfill (extend `WellnessAdd`)

**Gate:** `curl http://<tailscale-ip>:8787/api/health` from phone browser

### Phase 1: Shell app + read-only (2-3 days)

- [ ] Xcode project, SwiftUI tab bar
- [ ] APIClient + Settings (base URL, token)
- [ ] CommandView from `GET /api/state`
- [ ] InboxView proposals (read-only first)

**Gate:** Day Command visible on phone over Tailscale

### Phase 2: Log + goals (2-3 days)

- [ ] LogView → activity + wellness POST
- [ ] Offline queue + SyncEngine
- [ ] GoalsView CRUD
- [ ] Pull to refresh

**Gate:** Log a demo from phone → visible on Mac dashboard after refresh

### Phase 3: HealthKit (2-3 days)

- [ ] HealthKitManager authorization + queries
- [ ] Daily aggregation → wellness POST (today)
- [ ] Backfill last 14 days on first connect
- [ ] Health goals show updated actuals on Mac

**Gate:** Sleep appears in dashboard without `make import-health`

### Phase 4: Widget + polish (2 days)

- [ ] Day Command widget (small + medium)
- [ ] App Group cache
- [x] Optional Face ID lock → **done for PWA** ([SPEC-v12](docs/SPEC-v12-lock-screen.md)); native Swift lock still open
- [ ] App icon + TestFlight build

**Gate:** Day Command on lock screen

### Phase 5: Notifications (optional, 1-2 days)

- [ ] Mac `scripts/notify_ios.py` → APNs
- [ ] New brief + stale proposal alerts

---

## 15. Acceptance Criteria

### AC-1: Connectivity
- [ ] App connects to Mac API over Tailscale
- [ ] Offline log queues and syncs on reconnect

### AC-2: Parity with dashboard
- [ ] All goal fields from GOALS.md editable on phone
- [ ] Proposal approve/reject matches dashboard behavior
- [ ] Activity increment semantics match `POST /api/activity`

### AC-3: HealthKit
- [ ] Sleep, steps, workouts sync without manual CSV
- [ ] Physician agent sees data on next `make run`
- [ ] Denied HealthKit → manual wellness log still works

### AC-4: Performance
- [ ] Cold launch to Day Command < 2s on cached state
- [ ] Log action < 3 taps
- [ ] No crash on airplane mode

### AC-5: Distribution
- [ ] Installs on Ian's iPhone via Xcode (free or paid account)
- [ ] Survives 24h normal use without reinstall (paid account)

---

## 16. Out of Scope (v1)

- Android app
- Agents running on phone
- Financial OAuth (SimpleFIN/SnapTrade) on phone. Mac only
- App Store public release
- Apple Watch companion
- HealthKit write
- Full brief editing on phone
- Calendar ingest on phone (Google Cal stays Mac-side)

---

## Appendix A: Tailscale setup (Ian)

```bash
# Mac
brew install tailscale
sudo tailscale up

# Note Mac tailnet IP
tailscale ip -4

# Run API reachable on tailnet
make api  # ensure --host 0.0.0.0

# iPhone: install Tailscale from App Store, same account
# Settings → base URL: http://100.x.x.x:8787
```

## Appendix B: HealthKit Info.plist keys

```xml
<key>NSHealthShareUsageDescription</key>
<string>ianOS reads sleep, steps, and workouts to track your health goals. Data syncs only to your Mac.</string>
<key>UIBackgroundModes</key>
<array>
  <string>fetch</string>
</array>
```

## Appendix C: Cost

| Item | Cost |
|------|------|
| Apple Developer (optional) | $99/year |
| Tailscale personal | $0 |
| APNs (Phase 5) | $0 |
| **Total v1** | **$0-99/year** |

---

## Related docs

- [GOALS.md](GOALS.md), goal fields, metric keys, examples
- [SPEC-LIFE-OS.md](SPEC-LIFE-OS.md). Mac Life OS architecture
- [PRODUCT.md](PRODUCT.md): design principles
