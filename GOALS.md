# ianOS Goals. User Guide & Reference

**Version:** 2.0  
**Status:** Live (dashboard + API)  
**Last updated:** 2026-07-20  
**Audience:** Ian (daily use) + implementers extending metrics

Goals are the contract between Ian and the agents. Ian defines what matters; agents watch, memo, and propose, they never change goals on their own.

**Dashboard UX:** Goals live on **life pillar pages**, not a single Goals tab. See [SPEC v5](docs/SPEC-v5-ian-personal-dashboard.md) for navigation.

---

## Table of Contents

1. [Quick Start](#1-quick-start)
2. [The Three Kinds](#2-the-three-kinds)
3. [The Five Domains](#3-the-five-domains)
4. [Field Reference](#4-field-reference)
5. [Metric Keys (Auto-Actuals)](#5-metric-keys-auto-actuals)
6. [Status Colors](#6-status-colors)
7. [Hero Goals & Weekly Focus](#7-hero-goals--weekly-focus)
8. [Examples by Domain](#8-examples-by-domain)
9. [API Reference](#9-api-reference)
10. [How Agents Use Goals](#10-how-agents-use-goals)
11. [Adding a New Metric Key](#11-adding-a-new-metric-key)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Quick Start

### In the dashboard

1. Open `http://localhost:5173` (`make dev`)
2. Go to a **pillar page** (Beat the Clock, Body, Partner, School, Life, or Money)
3. Click **Add goal** → pick a template in the wizard (or "Start from scratch")
4. Fill in plain-English fields → save

Click the ✎ on any goal row to edit or delete. Advanced fields (kind, metric key, deadline chains) are under **More options** in the form.

**Cmd+K** jumps to any page or searches goals by name.

### Where goals live (pillars vs domains)

| Pillar (nav) | Goal `domain` | Examples |
|--------------|---------------|----------|
| Beat the Clock | `business` | Client #1, burn, quotas, LLC chain |
| Body | `health` | Gym weekdays, sleep, steps |
| Partner | `personal` + `#partner` in notes | Date night, flowers |
| School | `school` | Registration, move-in |
| Life | `personal` (not Partner-tagged) | Passport, friend check-in |
| Money | `finance` | Portfolio, checking floor |

`#goals` in the URL redirects to Beat the Clock for old bookmarks.

### Via API

```bash
curl -X POST http://localhost:8787/api/goals \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Read 2 books this month",
    "kind": "quota",
    "domain": "personal",
    "target": "2",
    "unit": "books",
    "metric_key": "",
    "notes": "Fiction + business mix"
  }'
```

Every create/update/delete writes a memo to the blackboard (`from_role: ian`) so agents know Ian changed the plan.

---

## 2. The Three Kinds

| Kind | Use when | Target means | Actual comes from |
|------|----------|--------------|-------------------|
| **goal** | Hit a number by a date (or ongoing) | The number to reach | `metric_key` auto-compute **or** manual `current_value` |
| **quota** | Repeatable daily/weekly cadence | Minimum count per period | `metric_key` auto-compute **or** manual |
| **deadline** | Binary milestone with a due date | Done-state label (`filed`, `renewed`, `approved`) | `current_value` text (`in progress`, `not started`, `done`) |

### Kind decision tree

```
Is it a one-time milestone with a due date?
  YES → deadline  (e.g. "File Illinois LLC" by 2026-07-17)
  NO  → Is it a repeating cadence (per day/week)?
          YES → quota  (e.g. "20 audit calls/day")
          NO  → goal   (e.g. "Portfolio net worth $15k")
```

---

## 3. The Five Domains

| Domain | Color | Pillar page | Typical goals | Primary agent |
|--------|-------|-------------|---------------|---------------|
| `business` | Amber | Beat the Clock | Clients, burn, quotas, LLC chain | scout, watchdog |
| `finance` | Green | Money | Portfolio, checking floor | cfo |
| `health` | Teal | Body | Sleep, gym streak, steps | physician |
| `school` | Blue | School | UIUC deadlines, move-in | advisor (Dumbledore) |
| `personal` | Purple | Partner or Life | Relationship rituals vs admin | steward, lovebird |

Domain status on pillar summaries = **worst status** among goals in that domain.

---

## 4. Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| **name** | Yes | Unique label. Agents quote this in memos and briefs. |
| **domain** | Yes | `business` \| `finance` \| `health` \| `personal` \| `school` |
| **kind** | Yes | `goal` \| `quota` \| `deadline` |
| **target** | Yes | Number or done-state string. Quotas: `3-5` uses the first number. |
| **unit** | No | Display suffix: `clients`, `$/mo`, `hours`, `steps` |
| **deadline** | No | `YYYY-MM-DD`. Required for meaningful T-minus on deadlines. |
| **current_value** | No | Manual progress. For deadlines: `not started`, `in progress`, `filed`, `renewed`, `done`. |
| **notes** | No | Context agents read. Put blockers, dependencies, and nuance here. |
| **metric_key** | No | Links to auto-computed actual (see §5). Blank = manual. |
| **hero** | No | One hero per domain. Shows largest in that zone. Clears other heroes in domain. |
| **priority** | No | Sort order within domain (lower = higher). Default 0. |
| **depends_on_goal_id** | No | Links a deadline to a parent deadline in the same domain. UI shows **Blocked by: {parent}** until the parent is done. Seed wires LLC → EIN → A2P. Set via GoalForm → More options → "Blocked until". |

---

## 5. Metric Keys (Auto-Actuals)

When `metric_key` is set, ianOS computes **actual** from SQLite instead of using `current_value`.

| metric_key | Source table | What it measures |
|------------|--------------|------------------|
| `burn_this_month` | `transactions` | Business spend this calendar month |
| `audit_calls_today` | `activity` | Today's audit calls |
| `follow_ups_today` | `activity` | Today's follow-ups |
| `demos_last_7d` | `activity` | Demos in last 7 days |
| `clients_signed` | `goals.current_value` | Parses int from hero client goal |
| `sleep_avg_7d` | `health_daily` | Avg sleep hours, 7-day window |
| `sleep_last_night` | `health_daily` | Last night's sleep |
| `steps_today` | `health_daily` | Today's step count |
| `workouts_this_week` | `health_daily` | Workout sessions this week |
| `gym_weekdays_this_week` | `health_daily` | Weekday gym confirms (Mon-Fri) via Body page |
| `energy_today` | `health_daily` | Energy 1-5 today |
| `portfolio_value` | `holdings` | Total Fidelity portfolio |
| `checking_balance` | ingest log / SimpleFIN | Chase checking balance |
| `work_hours_week` | `calendar_events` | Work-category hours, 7 days |

**Blank `metric_key`** → actual = `current_value`. Use for personal goals, deadline chains, and anything without a data pipeline yet.

**Invalid `metric_key`** → status becomes `NO DATA` (agents won't guess).

---

## 6. Status Colors

Computed by `core/metrics.py`, urgency is earned, not styled.

| Status | Meaning | Typical trigger |
|--------|---------|-----------------|
| **ON TRACK** | Green | At/above target, or deadline >14d away |
| **AT RISK** | Amber | 50-99% of quota, or deadline 7-14d |
| **OFF TRACK** | Red | Below 50% with deadline <14d, or past deadline |
| **NO DATA** | Gray | No ingest/log for 14+ days, or missing metric |

Special cases:
- **Burn goals** (`burn` in name): lower is better; over cap = AT RISK/OFF TRACK
- **Deadlines** with `current_value` in `done`, `filed`, `renewed`, `auto-renew on` → ON TRACK regardless of date

---

## 7. Hero Goals & Weekly Focus

### Hero (per domain)

- Check **HERO** on one goal per domain
- That goal renders largest in its zone (e.g. "Sign Clockwork client #1" in business)
- Setting a new hero clears the previous hero in the same domain

### Weekly focus (chief, Sundays)

The chief agent writes `focus_allocations` with up to 3 active domains and hero goal IDs. Off-focus goals dim on the dashboard except critical (OFF TRACK) deadlines.

Ian can influence focus by:
1. Setting heroes in domains that matter this week
2. Writing notes on goals explaining urgency
3. Running `make run-weekly` on Sunday

---

## 8. Examples by Domain

### Business

| Name | Kind | Target | metric_key | Notes |
|------|------|--------|------------|-------|
| Sign Clockwork client #1 | goal | 1 | clients_signed | Hero. School starts ~Aug 24. |
| Monthly burn under cap | goal | 150 | burn_this_month | Unit: $/mo |
| Audit calls per day | quota | 20 | audit_calls_today | Log via quick-add or `make log` |
| File Illinois LLC | deadline | filed | *(blank)* | current: `in progress` |

### Finance

| Name | Kind | Target | metric_key |
|------|------|--------|------------|
| Portfolio net worth | goal | 15000 | portfolio_value |
| Checking balance floor | goal | 1000 | checking_balance |

Requires `make sync-finance` or seed data.

### Health

| Name | Kind | Target | metric_key |
|------|------|--------|------------|
| Sleep 7+ hours/night | quota | 7 | sleep_avg_7d |
| Gym every weekday | quota | 5 | gym_weekdays_this_week |
| Work out 3x/week | quota | 3 | workouts_this_week |
| Steps 8k/day | quota | 8000 | steps_today |

Feed data via **Body page** gym confirm, `make log-wellness`, or `make import-health`.

### Personal / School

| Name | Kind | Target | domain | Notes |
|------|------|--------|--------|-------|
| Weekly friend check-in | quota | 1 | personal | Life pillar; manual `current_value` |
| Renew passport | deadline | renewed | personal | Life pillar |
| UIUC move-in ready | deadline | ready | school | School pillar; from facts |

Personal goals often use **blank metric_key**. Ian updates `current_value` when something happens. Relationship goals go on **Partner** with `#partner` in notes.

---

## 9. API Reference

Base URL: `http://localhost:8787` (local only, no auth today)

### `POST /api/goals`

Create a goal. Returns the full row.

```json
{
  "name": "string (required, unique)",
  "kind": "goal | quota | deadline",
  "domain": "business | finance | health | personal | school",
  "target": "string",
  "unit": "string",
  "deadline": "YYYY-MM-DD | null",
  "current_value": "string",
  "notes": "string",
  "metric_key": "string",
  "hero": false,
  "priority": 0,
  "depends_on_goal_id": null
}
```

**Errors:** `400` validation, `409` duplicate name.

### `PATCH /api/goals/{id}`

Partial update. Only sent fields change. Setting `hero: true` clears other heroes in domain.

### `DELETE /api/goals/{id}`

Removes goal. Writes memo. Returns `{"ok": true}`.

### `GET /api/state`

Returns all goals with computed `actual`, `actual_label`, `status`, `depends_on_name` (when chained), plus `goals_by_domain`, `domain_status`, `pillars`, and `gym` streak state.

### `POST /api/gym/confirm`

Marks today as a gym day (weekdays only). Returns updated `gym` object with `streak`, `confirmed_today`, `weekdays_this_week`.

### `POST /api/agents/run`

Triggers the nightly agent sequence from the dashboard (rate-limited). Use **Generate today's command** on Command: no terminal needed.

---

## 10. How Agents Use Goals

| Agent | Reads | Behavior |
|-------|-------|----------|
| scout | business goals + activity | Outreach pacing, quota gaps |
| cfo | finance goals + transactions | Burn, portfolio, checking |
| physician | health goals + health_daily | Sleep debt, workout streaks |
| steward | personal goals + calendar | Neglected personal items |
| watchdog | all deadlines | T-minus alerts, chain blockers |
| chief | all goals + focus | Day Command, cross-domain tradeoffs |

Agents **never** INSERT/UPDATE/DELETE goals. Ian owns the goal table.

After adding a goal, run `make run` (or wait for nightly) so agents pick it up.

---

## 11. Adding a New Metric Key

When Ian wants auto-actuals for a new data source:

1. Add resolver function in `core/metrics.py`:
   ```python
   def _my_metric(conn) -> tuple[float, str]:
       # return (numeric_actual, display_label)
       ...
   ```
2. Register in `METRIC_RESOLVERS`:
   ```python
   METRIC_RESOLVERS = { ..., "my_metric": _my_metric }
   ```
3. Create goals with `metric_key: "my_metric"`
4. Add test in `tests/test_metrics.py`

No dashboard change needed, metric_key is a free-text field.

---

## 12. Troubleshooting

| Problem | Fix |
|---------|-----|
| **Black screen** on load | Hard refresh (`Cmd+Shift+R`). If console shows `audit_calls` error, pull latest: `ActionStack` must handle `activity_today: null`. |
| Goal shows **NO DATA** | Set up ingest (`make sync-finance`, `make import-health`) or log manually |
| Duplicate name error | Goal names must be unique; rename or delete the old one |
| Actual doesn't update | Check `metric_key` spelling against §5 table |
| Agent ignores new goal | Run `make run`; check memo feed for "Ian added a … goal" |
| Finance goals empty | Add `SIMPLEFIN_ACCESS_URL` / SnapTrade keys, or `make seed` |
| Health goals stuck | `make log-wellness sleep=7 energy=4` or import Apple Health CSV |

### Health data without iPhone app (today)

```bash
# Manual
make log-wellness sleep=7.5 energy=4 workout=1

# Batch (Health Auto Export app → CSV)
make import-health FILE=~/Downloads/health_export.csv
```

For live HealthKit sync, see [SPEC-IPHONE.md](SPEC-IPHONE.md).

---

## Related docs

- [SPEC v5. Ian's Personal Dashboard](docs/SPEC-v5-ian-personal-dashboard.md), pillar nav, Command page, wizard
- [SPEC v7. Plan](docs/SPEC-v7-plan.md), the day calendar; your **hero business goal** and Day Command feed one-tap Plan blocks, and a plan block can link to a goal (`goal_id`)
- [SPEC-LIFE-OS.md](SPEC-LIFE-OS.md), full Life OS architecture
- [IAN-SETUP.md](IAN-SETUP.md), setup checklist
- [SPEC-IPHONE.md](SPEC-IPHONE.md), iPhone app + HealthKit path
- [PRODUCT.md](PRODUCT.md), design principles (agents propose, Ian approves)
