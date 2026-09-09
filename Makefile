# ianOS — personal agent headquarters
PY := .venv/bin/python

.PHONY: setup seed run run-weekly plan dev api ui log log-wellness content import import-leads import-leads-dry export-leads prep backtest import-health import-calendar import-canvas import-fidelity sync-chase sync-fidelity sync-plaid sync-finance connect-fidelity setup-simplefin schedule test clean plan api-lan sync-icloud sync-icloud-dry phone phone-off phone-status icons sync-btc sync-btc-dry sync-personal sync-inbound schedule-btc schedule-inbound schedule-btc-off schedule-inbound-off schedule-finance schedule-finance-off sync-canvas schedule-canvas schedule-canvas-off

## One-time setup: venv, deps, dashboard deps, seed data
setup:
	python3 -m venv .venv
	.venv/bin/pip install -q --upgrade pip
	.venv/bin/pip install -q -r requirements.txt
	cd dashboard && npm install --silent
	$(PY) scripts/seed.py
	@echo "ianOS ready. Try: make dev"

seed:
	$(PY) scripts/seed.py

run:
	$(PY) agents/runner.py

run-weekly:
	$(PY) agents/runner.py --weekly

## Dry run: print who the dispatcher would wake tonight (no agents run)
plan:
	$(PY) agents/runner.py --plan

## Serve the API on the LAN for iPhone Shortcuts (token-gated; see docs/SHORTCUTS.md)
api-lan:
	bash scripts/api_lan.sh

## Build + serve the installable phone app on one port (see docs/PHONE.md)
phone:
	bash scripts/phone.sh

## Stop the always-on server and take ianOS off the tailnet
phone-off:
	@launchctl unload ~/Library/LaunchAgents/com.ianos.serve.plist 2>/dev/null \
		&& echo "always-on server stopped" || echo "server was not installed"
	@rm -f ~/Library/LaunchAgents/com.ianos.serve.plist
	@for c in /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale /opt/homebrew/bin/tailscale; do \
		[ -x $$c ] && $$c serve reset && echo "tunnel off — ianOS is laptop-only again" && exit 0; \
	done; echo "tailscale not found; nothing to turn off"

## Is the phone server up? (and what does it say)
phone-status:
	@launchctl list | grep com.ianos.serve || echo "not installed — run make phone"
	@curl -sf -o /dev/null -w "  local  :8787 -> %{http_code}\n" http://127.0.0.1:8787/api/health || echo "  local  :8787 -> DOWN"
	@for c in /Applications/Tailscale.app/Contents/MacOS/Tailscale /usr/local/bin/tailscale; do \
		[ -x $$c ] && $$c serve status 2>/dev/null | head -3 && break; done
	@tail -3 data/serve.log 2>/dev/null || true

## Regenerate home-screen icons
icons:
	$(PY) scripts/make_icons.py

dev:
	bash scripts/dev.sh

api:
	.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8787 --reload

ui:
	cd dashboard && npm run dev

log:
	$(PY) ingest/log_activity.py -c $(or $(calls),0) -f $(or $(fu),0) -d $(or $(demos),0) -v $(or $(conv),0) -n "$(or $(note),)"

log-wellness:
	$(PY) ingest/log_wellness.py -s $(or $(sleep),) -e $(or $(energy),) -w $(or $(workout),0) -t "$(or $(type),)" -n "$(or $(note),)"

content:
	$(PY) ingest/log_content.py -p "$(platform)" -i "$(item)" -u "$(or $(url),)" -n "$(or $(note),)"

import:
	$(PY) ingest/import_csv.py $(FILE)

## Import the enriched prospect list into The Line (SPEC-v9).
## Safe to re-run after a re-scrape: refreshes scores, never touches call state.
## FILE defaults to leads/enriched.csv — the tier_*.csv files are views of it.
import-leads:
	$(PY) ingest/import_leads.py $(or $(FILE),leads/enriched.csv)

import-leads-dry:
	$(PY) ingest/import_leads.py $(or $(FILE),leads/enriched.csv) --dry-run

## Export leads back to CSV with real call history filled in, so
## enrich_prospects.py can re-run against reality. -> leads/exported.csv
export-leads:
	$(PY) ingest/export_leads.py $(if $(OUT),--out $(OUT),)

## Read the next calls (with full scripts) before you dial. make prep N=10
prep:
	$(PY) scripts/prep_calls.py -n $(or $(N),5)

## Did Fit/Pain/Reach actually predict who answers? Reports only — never
## rewrites a tier. Says "not enough data" until ~100 leads have been dialed.
backtest:
	$(PY) scripts/backtest_leads.py

import-health:
	$(PY) ingest/import_health.py $(FILE)

import-calendar:
	$(PY) ingest/import_calendar.py $(FILE)

## Import a downloaded Canvas calendar .ics snapshot into the School portal.
## This is local-file-only: never paste a Canvas feed URL, token, or password.
import-canvas:
	@test -n "$(FILE)" || (echo "Usage: make import-canvas FILE=/absolute/path/to/calendarfeed.ics"; exit 2)
	$(PY) ingest/import_canvas_calendar.py $(FILE)

## Reload data/fall_2026_school_seed.json alone (deadlines Canvas never sent).
## Touches the syllabus + schedule providers only; Canvas items are untouched.
sync-syllabus:
	$(PY) ingest/import_canvas_calendar.py --seed-only

## Pull the live Canvas calendar feed (needs CANVAS_ICS_URL in .env, SPEC-v32
## Part C). The feed URL is a bearer secret and never appears in argv, logs,
## or any agent-visible surface; make import-canvas remains for manual snapshots.
sync-canvas:
	$(PY) ingest/sync_canvas.py

import-fidelity:
	$(PY) ingest/import_fidelity.py $(FILE)

setup-simplefin:
	$(PY) ingest/setup_simplefin.py $(TOKEN)

sync-chase:
	$(PY) ingest/sync_chase.py

sync-fidelity:
	$(PY) ingest/sync_fidelity.py

sync-plaid:
	$(PY) ingest/sync_plaid.py

connect-fidelity:
	$(PY) ingest/sync_fidelity.py --connect

sync-finance:
	$(PY) ingest/sync_finance.py

## Two-way sync the day plan with iCloud (needs ICLOUD_* in .env; see SPEC-v7)
sync-icloud:
	$(PY) ingest/sync_icloud.py

sync-icloud-dry:
	$(PY) ingest/sync_icloud.py --dry-run

## Pull demo bookings + contact messages from beatyourclock.com (SPEC-v17)
sync-btc:
	$(PY) ingest/sync_btc.py

sync-btc-dry:
	$(PY) ingest/sync_btc.py --dry-run

## Pull messages from ianmccallum.com (SPEC-v19). Never creates a lead:
## these are correspondence, not Clockwork pipeline.
sync-personal:
	$(PY) ingest/sync_btc.py --source personal

## Pull every complete inbound seam independently (SPEC-v20). A missing
## optional personal seam is skipped; a partial credential pair fails visibly.
sync-inbound:
	$(PY) ingest/sync_btc.py --all-configured

## Pipe a connector JSON payload into the loader:  make sync-load source=gmail FILE=payload.json
sync-load:
	$(PY) ingest/from_connector.py --source $(source) --file $(FILE)

test:
	$(PY) -m pytest tests/ -q

## Rebuild the scrubbed public mirror in ../ianOS-public (local dir name only; the
## GitHub repo is Ian-mccallum/ianOS) and commit it there
## (SPEC-v39). Push from that directory. The script and its rule table stay private.
EXPORT_MSG ?= Refresh public mirror
export-public:
	$(PY) scripts/export_public.py --dest ../ianOS-public --commit --message "$(EXPORT_MSG)"

## Encrypted off-site backup (SPEC-v16, docs/BACKUP.md). Needs RESTIC_* in .env.
backup:
	bash scripts/backup.sh

backup-status:
	@bash scripts/backup.sh status

## Deep proof: re-read every byte + test-restore the DB + integrity_check
backup-verify:
	bash scripts/backup.sh verify

## Restore latest (or SNAPSHOT=<id>) into a NEW folder; never touches live data
restore:
	bash scripts/restore.sh

schedule:
	sed "s|__IANOS_DIR__|$(CURDIR)|g" ops/com.ianos.nightly.plist > ~/Library/LaunchAgents/com.ianos.nightly.plist
	launchctl unload ~/Library/LaunchAgents/com.ianos.nightly.plist 2>/dev/null || true
	launchctl load ~/Library/LaunchAgents/com.ianos.nightly.plist
	@echo "Scheduled: nightly agent run at 21:30"

## Pull every complete inbound seam every 15 min via launchd (SPEC-v20).
## schedule-btc remains an alias so existing muscle memory still works.
schedule-inbound schedule-btc:
	@$(PY) ingest/sync_btc.py --check-all-configured
	sed "s|__IANOS_DIR__|$(CURDIR)|g" ops/com.ianos.btcsync.plist > ~/Library/LaunchAgents/com.ianos.btcsync.plist
	launchctl unload ~/Library/LaunchAgents/com.ianos.btcsync.plist 2>/dev/null || true
	launchctl load ~/Library/LaunchAgents/com.ianos.btcsync.plist
	@echo "Scheduled: all configured inbound seams every 15 min"

schedule-inbound-off schedule-btc-off:
	@launchctl unload ~/Library/LaunchAgents/com.ianos.btcsync.plist 2>/dev/null \
		&& echo "Inbound sync unscheduled" || echo "was not scheduled"
	@rm -f ~/Library/LaunchAgents/com.ianos.btcsync.plist

## Refresh configured finance sources each morning. Refuses absent or partial
## credentials and prints missing key names only (SPEC-v20).
schedule-finance:
	@$(PY) ingest/sync_finance.py --check-configured
	sed "s|__IANOS_DIR__|$(CURDIR)|g" ops/com.ianos.financesync.plist > ~/Library/LaunchAgents/com.ianos.financesync.plist
	launchctl unload ~/Library/LaunchAgents/com.ianos.financesync.plist 2>/dev/null || true
	launchctl load ~/Library/LaunchAgents/com.ianos.financesync.plist
	@echo "Scheduled: configured finance sources each morning at 07:15"

schedule-finance-off:
	@launchctl unload ~/Library/LaunchAgents/com.ianos.financesync.plist 2>/dev/null \
		&& echo "Finance sync unscheduled" || echo "was not scheduled"
	@rm -f ~/Library/LaunchAgents/com.ianos.financesync.plist

## Pull the live Canvas calendar feed every 6 hours (SPEC-v32 Part C). Refuses
## when CANVAS_ICS_URL is unset, no plist installed.
schedule-canvas:
	@$(PY) ingest/sync_canvas.py --check-configured
	sed "s|__IANOS_DIR__|$(CURDIR)|g" ops/com.ianos.canvassync.plist > ~/Library/LaunchAgents/com.ianos.canvassync.plist
	launchctl unload ~/Library/LaunchAgents/com.ianos.canvassync.plist 2>/dev/null || true
	launchctl load ~/Library/LaunchAgents/com.ianos.canvassync.plist
	@echo "Scheduled: Canvas calendar feed every 6 hours"

schedule-canvas-off:
	@launchctl unload ~/Library/LaunchAgents/com.ianos.canvassync.plist 2>/dev/null \
		&& echo "Canvas sync unscheduled" || echo "was not scheduled"
	@rm -f ~/Library/LaunchAgents/com.ianos.canvassync.plist

## Nightly 21:45 backup via launchd. Refuses when unconfigured (SPEC-v16 law 8),
## so an unconfigured machine can never generate a nightly failure memo.
schedule-backup:
	@grep -q "^RESTIC_REPOSITORY=." .env 2>/dev/null || \
		{ echo "Not configured: add RESTIC_* to .env first (docs/BACKUP.md)"; exit 1; }
	sed "s|__IANOS_DIR__|$(CURDIR)|g" ops/com.ianos.backup.plist > ~/Library/LaunchAgents/com.ianos.backup.plist
	launchctl unload ~/Library/LaunchAgents/com.ianos.backup.plist 2>/dev/null || true
	launchctl load ~/Library/LaunchAgents/com.ianos.backup.plist
	@echo "Scheduled: nightly backup at 21:45"

clean:
	rm -f data/ianos.db data/ianos.db-wal data/ianos.db-shm
