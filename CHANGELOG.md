# Changelog

All notable changes to ianOS are recorded here, newest first. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); dates are when a
change landed on `main`, not when work started.

This file starts with SPEC-v37. Everything before it (SPEC-v2 through v36)
shipped without a changelog entry — `git log` and the `docs/SPEC-vN-*.md`
files are the record for that history; CLAUDE.md's "Conventions & gotchas"
section links each one to what it shipped.

## 2026-09-01 — SPEC-v37: the agent rebuild

An audit found 870 tests proving every wall held and none proving any claim
about the agents was actually true: a dead APPROVE loop (proposals piled up
with no verb to act on them), a memory flywheel that never turned (the
archivist's weekly distillation was configured but never wired in), and an
interactive-agent surface (Ask sheet, inspect mode, rooms) built on a threat
model tuned for unattended nightly runs. `docs/SPEC-v37-agent-rebuild.md` is
the full spec; shipped in six phases, each its own commit.

### Added
- **Tiered agency.** A closed list of 13 Ring 1 reversible acts
  (`core/acts.py`) apply immediately, receipted (`agent_acts` table) and
  undoable in one tap from Command's new Receipts strip. Two new Ring 2
  proposal kinds, `goal_change` and `quota_rebaseline`, give the roster a
  verb it was missing.
- **The situation block.** Every nightly producer's prompt now opens with a
  precomputed status block (`core/situation.py`): season/capacity, hero
  goal, nearest deadlines, live quotas, expired-undecided goals, the full
  open-proposal ledger, and the last 24h of Ring 1 acts — the fix for the
  dead APPROVE loop.
- **The roster, reworked.** Ten active agents (was fifteen): advisor merged
  into watchdog (now Dumbledore), archivist retired in favor of a pure
  function, family/infra/publicist retired. Alfred Pennyworth (steward) is
  now the default agent. Role files carry no hardcoded dates or dollar
  figures anymore (`test_no_expired_dates_in_prompts`).
- **Memory: the ledger and the index.** `upsert_fact` now defaults to
  `verified=0`; `write_fact` requires resolvable evidence; `write_memo` at
  priority ≥2 requires a read this run. The archivist's weekly distillation
  became `core/ledger.py::distill()`, called every night. A new FTS5 memory
  index (`core/memory_index.py`, `search_memory` tool) gives every agent
  full-text recall over memos/briefs/notes/facts/school notes/proposals —
  explicitly recall-only, never a source of truth (`grounding: "recall_only"`
  on every result), and structurally excluded from every existing privacy
  wall (journal, health, school files).
- **The consult surface.** One chat surface replaces the Ask sheet, inspect
  mode, and hand-rolled rooms. A daytime thread is now genuinely attended
  (Plane B): real Claude Code tools (Read/Grep/Glob/Bash/WebSearch) behind
  new opt-in capability chips (Files, Workspace, Shell), gated by one runtime
  wall (`agents/consult_gate.py`) regardless of which chip is on. Fury can
  convene up to three other agents as real SDK subagents. Threads resume
  their actual native conversation instead of a quoted-summary cache. The
  chat panel is a portal into Command's grid (dock / expanded / full screen),
  not a separate overlay.
- **Money the CFO can actually see.** `read_accounts` gives cfo/wealth/chief
  the whole linked account set and a real computed net worth
  (`db.net_worth()`). The Money hero has its own refresh button
  (`POST /api/money/refresh`).
- **Health consent has a front door.** A one-time card on the Body page asks
  explicitly before physician/coach ever see a health log; the Roster now
  says so plainly instead of showing a stale timestamp.

### Fixed
- The runner no longer runs inside the web process; a crash there used to
  take a brief down with it, silently.
- A brief written at 21:30 was stamped with the night it ran, not the day it
  governs, so the "stale" indicator was wrong almost all day, every day.
  `briefs.governs_date` fixes it.
- `cash_position()` summed every transaction since the first CSV import ever
  (seeded demo rows included) with no time window — the exact shape of bug
  that turned two small balances into "~$81 months of runway". Now a real rolling
  30-day window over linked accounts only.
- Checking-balance freshness was hardcoded to a data source (`simplefin_chase`)
  that Plaid replaced months ago and that ingest marks permanently
  `disabled` — every checking balance therefore always read as stale. Now
  traced to the source that actually produced the number.
- Four seeded demo holdings rows ($7,420 combined, dated 2026-07-21) were
  never removed once real SnapTrade data arrived, producing a false cliff in
  any balance history view. Deleted.
- A finance sync failure was recorded to `ingest_log` and nowhere else — an
  entire SnapTrade drop-out (4 of 9 accounts) went unnoticed for days. Now
  writes one `system` memo on the first failure of a streak (shared with
  Canvas sync, not just finance).
- `role_stats()` counted `EXPIRED` proposals toward the "proposed" total its
  own docstring said it excluded — Watchdog's roster card read "31 proposed"
  when 13 of those had simply timed out unread.
- `REGISTERED_TOOLS` was missing all 13 Ring 1 act tools, so no real agent
  could ever call one — only direct test harness calls (Phase 2, caught
  during Phase 4 integration).
- Fury's live-state block read a nonexistent key off `portfolio_snapshot()`,
  silently dropping the portfolio from every net worth figure it ever cited
  (introduced in Phase 5, caught during Phase 6).
- `db.CHAT_CHIP_IDS` never gained "documents" or "web" when those chips
  shipped in SPEC-v27 — neither was ever actually toggleable via the API.

### Removed
- `run_interactive_role`, `/api/agent-invocations`, `/api/agent-commands`,
  `/api/agent-rooms`, `AskAgentSheet.jsx`, and the sequential-Haiku-children
  rooms path — superseded by the consult surface above.
- The old prior-turn quoted-history cache (`CHAT_PRIOR_*`,
  `_chat_prior_block`) as the primary chat memory mechanism — kept only as a
  fallback for when native session resume fails, now including both sides of
  the conversation (the old cache never quoted Ian's own messages).
