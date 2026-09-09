"""SQLite layer for ianOS. One database, small helpers, no ORM."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from core import streaks

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "ianos.db"

DOMAINS = ("business", "health", "personal", "finance", "school")
PROPOSAL_KINDS = ("money", "task", "legal", "health", "personal",
                  # SPEC-v37 §4.3: the two new Ring 2 kinds the dead APPROVE
                  # loop was missing a verb for.
                  "goal_change", "quota_rebaseline")
DONE_STATES = {"filed", "obtained", "approved", "renewed", "done", "complete", "signed", "1"}

# Physician and Coach used the global memo board before the v35 health privacy
# boundary existed. Keep that historic material out of broad app state and any
# remote-agent reader; new health analysis belongs in health_insights instead.
PRIVATE_HEALTH_MEMO_ROLES = frozenset({"physician", "coach"})

# SPEC-v23 evidence is an enum, not model-authored prose. The database applies
# this final wall even when a caller bypasses the runner and API sanitizers.
AGENT_INVOCATION_EVIDENCE_LABELS = frozenset({
    "Goals", "Transactions", "Portfolio holdings", "Sales activity",
    "Health log", "Calendar and plan", "Weekly focus", "Document register",
    "Infrastructure status", "Agent memos", "Long-term facts",
    "Publishing log", "The Line", "Notes", "Mail", "School portal",
    "Class notes", "Memory search",
})

# SPEC-v25. Closed model enum; must stay identical to agents.runner HAIKU/SONNET.
# SPEC-v26: subscription auth means marginal dollar cost is $0, so the enum
# widens to the full plan. It stays CLOSED so a fat-fingered model string
# cannot become a silent default; quota discipline lives in the defaults.
CHAT_MODELS = frozenset({
    "claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5", "claude-fable-5",
})
CHAT_DEFAULT_MODEL = "claude-sonnet-5"
# SPEC-v37 3.5: Alfred is who you talk to when you don't want to think about
# which agent to talk to. Was "chief" (Fury); Fury stays reachable by name.
CHAT_DEFAULT_ROLE = "steward"
# SPEC-v27: reasoning effort, guiding thinking depth. 'xhigh' is deliberately
# absent: it falls back silently on most models, so it would be a control that
# sometimes lies about what it did.
CHAT_EFFORTS = frozenset({"low", "medium", "high", "max"})
CHAT_DEFAULT_EFFORT = "high"
# "documents" and "web" were added to agents.runner's CHAT_CHIP_ORDER by
# SPEC-v27 but never added here, so canonical_granted_chips() rejected them
# with a 422 the whole time: neither chip was ever actually toggleable. Fixed
# here as part of SPEC-v37 §2.7 alongside adding three new Plane B capability
# chips: "files"/"workspace"/"shell" are real Claude Code tool grants
# (Read/Grep/Glob, Write/Edit, Bash), scoped and gated by
# agents/consult_gate.py, not ianOS domain reads. §2.7 also lists Mail/
# Calendar/Drive capability chips (a live connector-tool grant, distinct from
# the existing "mail"/"calendar" ianOS-domain chips below); those three are
# deliberately not built here, since this codebase has no existing mechanism
# for wiring a connected Gmail/Calendar/Drive MCP server into a non-
# interactively-spawned CLI subprocess -- shipping the toggle without it
# would grant nothing (an osui L3 zero-value control).
CHAT_CHIP_IDS = (
    "money", "mail", "calendar", "school", "documents", "web",
    "files", "workspace", "shell",
)
# Source chips a new thread for this role opens with, on top of "files".
# Only roles whose beat is unreadable without the chip belong here.
CHAT_DEFAULT_CHIPS_BY_ROLE = {"watchdog": ("school",)}
CHAT_THREAD_STATUSES = ("OPEN", "CLOSED")
CHAT_TURNS_PER_THREAD = 200
# Chat is a conversation, not a consult log: a memory that resets weekly
# reads as broken. Ask and inspect keep the shorter window.
CHAT_RETENTION_DAYS = 30
CHAT_PRIOR_TURN_WINDOW = 12
# SPEC-v40 §4: memory and Compact. A summary is Compact's bounded output;
# these bound what it covers, when it fires on its own, and how much of it a
# new thread with the same agent receives.
CHAT_SUMMARY_CHARS = 1200            # one thread's stored summary
CHAT_COMPACT_MIN_TURNS = 4           # succeeded turns since the last summary before Compact is offered
CHAT_COMPACT_AUTO_TURNS = 40         # turns since the last summary that trigger Compact on their own
CHAT_CROSS_THREAD_SUMMARIES = 3      # earlier same-role threads a new thread hears about
CHAT_CROSS_SUMMARY_CHARS = 600       # each, in the prompt
CHAT_CROSS_SUMMARY_BUDGET = 2000     # all of them together

# SPEC-v30. Closed enums for the Money page's own display preferences
# (money_prefs). Ian's config only, never agent-facing.
MONEY_HERO_METRICS = frozenset({"net_worth", "burn", "cash", "goal"})
MONEY_HERO_DEFAULT = "net_worth"
MONEY_WIDGET_KEYS = frozenset({"accounts", "goals", "burn", "transactions"})
MONEY_WIDGETS_DEFAULT = (
    {"key": "accounts", "visible": True},
    {"key": "goals", "visible": True},
    {"key": "burn", "visible": True},
    {"key": "transactions", "visible": True},
)

# Facts store: domains are app-validated (not DB-constrained) so 'college'/'legal'
# work without a goals-table rebuild. Topic namespaces map to a home domain.
FACT_DOMAINS = ("business", "finance", "health", "personal", "college", "legal")
FACT_KINDS = ("fact", "preference", "date", "rule")
NAMESPACE_DOMAINS = {
    "partner": "personal", "family": "personal", "uiuc": "college",
    "content": "business", "training": "health", "market": "finance",
    "learning": "personal",
}


def domain_for_topic(topic: str, default: str) -> str:
    """A namespaced topic ('partner:anniversary') routes to its home domain."""
    ns = topic.split(":", 1)[0].strip().lower() if ":" in topic else ""
    return NAMESPACE_DOMAINS.get(ns, default)

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    description TEXT NOT NULL,
    amount      REAL NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    account     TEXT NOT NULL DEFAULT '',
    hash        TEXT UNIQUE,
    source      TEXT NOT NULL DEFAULT 'csv'
);

-- Read-only account metadata and balances from bank aggregators. Access tokens
-- never belong in SQLite; Plaid tokens stay in the gitignored local .env file.
CREATE TABLE IF NOT EXISTS financial_accounts (
    source            TEXT NOT NULL,
    external_id       TEXT NOT NULL,
    item_key          TEXT NOT NULL DEFAULT '',
    institution       TEXT NOT NULL DEFAULT '',
    name              TEXT NOT NULL DEFAULT '',
    type              TEXT NOT NULL DEFAULT '',
    subtype           TEXT NOT NULL DEFAULT '',
    mask              TEXT NOT NULL DEFAULT '',
    current_balance   REAL,
    available_balance REAL,
    credit_limit      REAL,
    currency          TEXT NOT NULL DEFAULT 'USD',
    as_of             TEXT,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_financial_accounts_source ON financial_accounts(source, type, subtype);

-- Daily balance history per account (SPEC-v24), for trend lines and liquidity
-- tracking. One row per (source, external_id, date); record_balance_snapshot
-- upserts it, so a same-day re-sync changes zero rows.
CREATE TABLE IF NOT EXISTS balance_snapshots (
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,
    date          TEXT NOT NULL,
    current       REAL,
    available     REAL,
    UNIQUE(source, external_id, date)
);
CREATE INDEX IF NOT EXISTS idx_balance_snapshots_account ON balance_snapshots(source, external_id, date);

-- Current credit-card liability state per account (SPEC-v24). Like
-- financial_accounts, this mirrors current provider state and is not an
-- event log. due_cards_for_alert() reads it to find upcoming payments;
-- alerted_at is the fire-once guard, stamped on fire, never on success.
CREATE TABLE IF NOT EXISTS card_liabilities (
    source             TEXT NOT NULL,
    external_id        TEXT NOT NULL,
    statement_balance  REAL,
    minimum_payment    REAL,
    due_date           TEXT,
    apr                REAL,
    is_overdue         INTEGER NOT NULL DEFAULT 0,
    alerted_at         TEXT,
    updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (source, external_id)
);

-- One cursor per Plaid Item. The matching access token is intentionally kept
-- only in .env under PLAID_ACCESS_TOKEN_<ITEM_KEY>.
CREATE TABLE IF NOT EXISTS plaid_items (
    item_key          TEXT PRIMARY KEY,
    item_id           TEXT NOT NULL UNIQUE,
    institution_id    TEXT NOT NULL DEFAULT '',
    institution_name  TEXT NOT NULL DEFAULT '',
    cursor            TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Maps Plaid's mutable transaction identity to the durable ianOS transaction
-- row so modified/removed entries do not create duplicate spend records.
CREATE TABLE IF NOT EXISTS plaid_transaction_rows (
    item_key       TEXT NOT NULL REFERENCES plaid_items(item_key) ON DELETE CASCADE,
    transaction_id TEXT NOT NULL,
    transaction_row_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    PRIMARY KEY (item_key, transaction_id)
);

CREATE TABLE IF NOT EXISTS memos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_role  TEXT NOT NULL,
    topic      TEXT NOT NULL,
    body       TEXT NOT NULL,
    priority   INTEGER NOT NULL DEFAULT 1,   -- 0=FYI 1=normal 2=important 3=urgent
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    -- Compaction preserves the original row as auditable evidence. The active
    -- feed excludes archived rows; fact_sources may still reference them.
    archived         INTEGER NOT NULL DEFAULT 0,
    archived_at      TEXT,
    archived_into_id INTEGER REFERENCES memos(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS briefs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'daily' CHECK (kind IN ('daily', 'weekly')),
    body        TEXT NOT NULL,
    day_command TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (date, kind)
);

CREATE TABLE IF NOT EXISTS goals (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL UNIQUE,
    kind               TEXT NOT NULL DEFAULT 'goal'
                       CHECK (kind IN ('goal', 'quota', 'deadline')),
    target             TEXT NOT NULL,
    unit               TEXT NOT NULL DEFAULT '',
    deadline           TEXT,
    current_value      TEXT NOT NULL DEFAULT '',
    notes              TEXT NOT NULL DEFAULT '',
    domain             TEXT NOT NULL DEFAULT 'business'
                       CHECK (domain IN ('business', 'health', 'personal', 'finance')),
    metric_key         TEXT NOT NULL DEFAULT '',
    depends_on_goal_id INTEGER REFERENCES goals(id),
    hero               INTEGER NOT NULL DEFAULT 0,
    priority           INTEGER NOT NULL DEFAULT 0,
    archived           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT NOT NULL UNIQUE,
    audit_calls   INTEGER NOT NULL DEFAULT 0,
    follow_ups    INTEGER NOT NULL DEFAULT 0,
    demos         INTEGER NOT NULL DEFAULT 0,
    conversations INTEGER NOT NULL DEFAULT 0,
    notes         TEXT NOT NULL DEFAULT ''
);

-- SPEC-v20. A browser-generated mutation id is durable proof that a replay
-- already changed the database. Receipts are intentionally permanent: an
-- installed PWA can wake up with a very old queued tap.
CREATE TABLE IF NOT EXISTS mutation_receipts (
    mutation_id   TEXT PRIMARY KEY,
    operation     TEXT NOT NULL,
    request_hash  TEXT NOT NULL,
    effective_date TEXT,
    captured_at   TEXT,
    status_code   INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    applied_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_mutation_receipts_applied
    ON mutation_receipts(applied_at);

CREATE TABLE IF NOT EXISTS health_daily (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL UNIQUE,
    sleep_hours  REAL,
    steps        INTEGER,
    workouts     INTEGER NOT NULL DEFAULT 0,
    workout_mins INTEGER NOT NULL DEFAULT 0,
    workout      TEXT NOT NULL DEFAULT '',
    energy       INTEGER CHECK (energy IS NULL OR (energy BETWEEN 1 AND 5)),
    weight_lbs   REAL,
    notes        TEXT NOT NULL DEFAULT '',
    source       TEXT NOT NULL DEFAULT 'manual'
);

-- SPEC-v35. health_daily remains the legacy-compatible daily projection. The
-- source-level records below are authoritative so an Apple snapshot cannot
-- erase manual energy, notes, or a future Oura source's provenance.
CREATE TABLE IF NOT EXISTS health_sources (
    source_key       TEXT PRIMARY KEY,
    display_label    TEXT NOT NULL,
    enabled          INTEGER NOT NULL DEFAULT 1,
    configured_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    last_capture_at  TEXT,
    CHECK (enabled IN (0, 1))
);

CREATE TABLE IF NOT EXISTS health_metric_source_policy (
    metric_key  TEXT PRIMARY KEY,
    source_key  TEXT NOT NULL REFERENCES health_sources(source_key),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS health_snapshots (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key        TEXT NOT NULL REFERENCES health_sources(source_key),
    installation_id   TEXT NOT NULL,
    snapshot_id       TEXT NOT NULL,
    capture_kind      TEXT NOT NULL,
    captured_at       TEXT NOT NULL,
    timezone          TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    measurement_count INTEGER NOT NULL DEFAULT 0,
    received_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (source_key, installation_id, snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_health_snapshots_source_capture
    ON health_snapshots(source_key, captured_at DESC);

CREATE TABLE IF NOT EXISTS health_daily_measurements (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id            INTEGER REFERENCES health_snapshots(id) ON DELETE SET NULL,
    source_key             TEXT NOT NULL REFERENCES health_sources(source_key),
    source_installation_id TEXT NOT NULL,
    source_record_key      TEXT NOT NULL,
    local_day              TEXT NOT NULL,
    metric_key             TEXT NOT NULL,
    value_num              REAL NOT NULL,
    unit                   TEXT NOT NULL,
    observed_at            TEXT NOT NULL,
    as_of                  TEXT NOT NULL,
    window_start           TEXT,
    window_end             TEXT,
    finality               TEXT NOT NULL CHECK (finality IN ('partial', 'final')),
    quality                TEXT NOT NULL DEFAULT 'valid'
                           CHECK (quality IN ('valid', 'partial', 'manual',
                                              'legacy_import', 'conflict',
                                              'quarantined')),
    semantic_hash          TEXT NOT NULL,
    created_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (source_key, source_installation_id, source_record_key, metric_key),
    UNIQUE (source_key, semantic_hash)
);
CREATE INDEX IF NOT EXISTS idx_health_measurements_lookup
    ON health_daily_measurements(source_key, local_day, metric_key, finality, as_of DESC);

CREATE TABLE IF NOT EXISTS health_daily_projection_fields (
    local_day       TEXT NOT NULL,
    metric_key      TEXT NOT NULL,
    measurement_id  INTEGER REFERENCES health_daily_measurements(id) ON DELETE SET NULL,
    source_key      TEXT NOT NULL,
    quality         TEXT NOT NULL,
    finality        TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (local_day, metric_key)
);

CREATE TABLE IF NOT EXISTS health_overrides (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    local_day   TEXT NOT NULL,
    metric_key  TEXT NOT NULL,
    value_num   REAL NOT NULL,
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_health_overrides_active
    ON health_overrides(local_day, metric_key, revoked_at);

-- Explicit consent must be a durable user preference, never an environment
-- flag. It defaults off so no health row can leave through a remote model.
CREATE TABLE IF NOT EXISTS health_ai_prefs (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    share_health_with_ai   INTEGER NOT NULL DEFAULT 0 CHECK (share_health_with_ai IN (0, 1)),
    consent_version        TEXT NOT NULL DEFAULT '',
    consented_at           TEXT,
    updated_at             TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS health_insights (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'pattern',
    body        TEXT NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    dismissed_at TEXT
);

-- Body's plainest log. Events, not tallies (D3): the day's count is always
-- COUNT(*) over live rows, never a stored number, so an undo is a soft
-- delete and the count rebuilds itself. `day` is stamped at the tap, not
-- derived from logged_at, so a 2pm tap that syncs from the phone at 6pm
-- still counts for the day it happened (the gym-confirm precedent).
-- `bristol` and `note` are the optional second beat and stay NULL/'' for a
-- one-tap log; nothing on this table is ever required.
CREATE TABLE IF NOT EXISTS poop_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    logged_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    bristol    INTEGER CHECK (bristol IS NULL OR bristol BETWEEN 1 AND 7),
    note       TEXT NOT NULL DEFAULT '',
    source     TEXT NOT NULL DEFAULT 'ian' CHECK (source IN ('ian')),
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_poop_log_day ON poop_log(day) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS calendar_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL,
    start_time   TEXT,
    end_time     TEXT,
    summary      TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT '',
    duration_min INTEGER,
    hash         TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS focus_allocations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT NOT NULL UNIQUE,
    domains     TEXT NOT NULL,
    goal_ids    TEXT NOT NULL DEFAULT '[]',
    rationale   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS ingest_log (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    source               TEXT NOT NULL UNIQUE,
    last_import          TEXT,
    row_count            INTEGER NOT NULL DEFAULT 0,
    notes                TEXT NOT NULL DEFAULT '',
    last_attempt         TEXT,
    last_success         TEXT,
    last_error           TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    stale_alerted_at     TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account      TEXT NOT NULL DEFAULT 'fidelity',
    symbol       TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    quantity     REAL NOT NULL,
    cost_basis   REAL,
    market_value REAL NOT NULL,
    currency     TEXT NOT NULL DEFAULT 'USD',
    as_of_date   TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'snaptrade',
    hash         TEXT UNIQUE,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL DEFAULT '',
    kind        TEXT NOT NULL DEFAULT 'contract',
    status      TEXT NOT NULL DEFAULT 'pending',
    notes       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS proposals (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    role              TEXT NOT NULL,
    action            TEXT NOT NULL,
    reasoning         TEXT NOT NULL,
    kind              TEXT NOT NULL DEFAULT 'task'
                      CHECK (kind IN ('money', 'task', 'legal', 'health', 'personal')),
    -- EXPIRED is a timeout, NOT a verdict (SPEC-v32 law 4): a proposal Ian
    -- never got to is neither approved nor rejected, and role_stats /
    -- recent_decisions both keep it out of the agent's track record.
    status            TEXT NOT NULL DEFAULT 'PENDING'
                      CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    decided_at        TEXT,
    attachment_type   TEXT NOT NULL DEFAULT '',
    attachment_json   TEXT NOT NULL DEFAULT '',
    urgency           TEXT NOT NULL DEFAULT 'normal',
    due_at            TEXT,
    reversibility     TEXT NOT NULL DEFAULT 'reversible',
    evidence_json     TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_calendar_date ON calendar_events(date);
CREATE INDEX IF NOT EXISTS idx_holdings_as_of ON holdings(as_of_date);
CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);

CREATE TABLE IF NOT EXISTS partner_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    notes        TEXT NOT NULL DEFAULT '',
    done         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    completed_at TEXT,
    parent_id        INTEGER REFERENCES partner_tasks(id),
    deleted_at       TEXT,
    deleted_batch_id TEXT
);

-- SPEC-v41 §4.2: Life's daily to-do. Deliberately not partner_tasks (Ian's
-- decision, no shared table): no time slot (a plan block), no target (a
-- goal), no partner (partner_tasks stays its own thing).
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    due_date     TEXT NOT NULL,                       -- YYYY-MM-DD, local
    priority     INTEGER NOT NULL DEFAULT 0 CHECK (priority IN (0, 1)),
    goal_id      INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    source       TEXT NOT NULL DEFAULT 'ian'
                   CHECK (source IN ('ian', 'chat', 'agent', 'goal_draft')),
    source_role  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    done_at      TEXT,
    deleted_at   TEXT,
    position     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tasks_open ON tasks(due_date) WHERE done_at IS NULL AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS facts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    domain          TEXT NOT NULL,
    topic           TEXT NOT NULL,
    body            TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'fact'
                    CHECK (kind IN ('fact', 'preference', 'date', 'rule')),
    date            TEXT,
    recurs          TEXT NOT NULL DEFAULT '',
    source_role     TEXT NOT NULL DEFAULT '',
    source_memo_ids TEXT NOT NULL DEFAULT '',
    verified        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (domain, topic)
);

-- SPEC-v20 Phase B. facts.source_memo_ids remains a compatibility projection;
-- this relation is the canonical, foreign-key-protected evidence graph.
CREATE TABLE IF NOT EXISTS fact_sources (
    fact_id  INTEGER NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    memo_id  INTEGER NOT NULL REFERENCES memos(id) ON DELETE RESTRICT,
    added_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (fact_id, memo_id)
);

CREATE TABLE IF NOT EXISTS content_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    platform   TEXT NOT NULL,
    item       TEXT NOT NULL,
    url        TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS streak_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL UNIQUE,
    kind       TEXT NOT NULL CHECK (kind IN ('confirm', 'grace', 'reset')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS plan_blocks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,                 -- YYYY-MM-DD
    start_time  TEXT NOT NULL,                 -- "HH:MM", 15-min snapped
    end_time    TEXT NOT NULL,                 -- must be > start_time
    title       TEXT NOT NULL,
    goal_id     INTEGER REFERENCES goals(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'done')),
    caldav_uid  TEXT UNIQUE,                   -- null until first push to iCloud
    caldav_etag TEXT,
    synced_at   TEXT,                          -- null = never synced
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS plan_tombstones (
    caldav_uid TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,                 -- the day being closed (journal_day, SPEC-v8)
    body        TEXT NOT NULL,
    media_path  TEXT NOT NULL DEFAULT '',      -- ROOT-relative, e.g. data/journal/2026/07/12-a3f2.jpg
    media_kind  TEXT NOT NULL DEFAULT '' CHECK (media_kind IN ('', 'photo', 'video')),
    shared      INTEGER NOT NULL DEFAULT 0,    -- 1 once Ian sends the TEXT to the agents
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- SPEC-v31 "Notes, reimagined". Ian's own nested folder tree for notes,
-- self-referencing so it can go arbitrarily deep. NULL parent_id = top-level;
-- notes.folder_id (added below via _migrate_columns) reuses the same NULL =
-- "unfiled / All Notes" convention, so the ~existing notes need zero backfill.
-- No CHECK on parent_id: SQLite cannot declaratively forbid a self-reference
-- cycle, so that guard lives in code (move_note_folder's WITH RECURSIVE
-- ancestor walk), the same "guardrails live in code" discipline all_goals()'s
-- archived filter and _lead_filter() already use. deleted_batch_id mirrors
-- partner_tasks' cascade delete/restore precedent (archive_partner_task /
-- restore_partner_archive), generalized here to arbitrary depth.
CREATE TABLE IF NOT EXISTS note_folders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    parent_id        INTEGER REFERENCES note_folders(id),  -- NULL = top-level
    color            TEXT,                                  -- closed palette key
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at       TEXT,
    deleted_batch_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_note_folders_parent ON note_folders(parent_id, deleted_at);

-- SPEC-v10 "osUI". Ian's own notes, deliberately NOT journal_entries. The
-- journal's defining property is that no agent ever sees it (SPEC-v8 privacy
-- wall); notes are readable by chief + archivist. Sharing one table would put a
-- single boolean between his private reflections and a model, so they stay
-- apart. `title` is derived from the first line on save, but stored, so the
-- list never has to parse bodies. Deletes are soft, for a 30-day undo.
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    pinned      INTEGER NOT NULL DEFAULT 0,
    domain      TEXT,                          -- optional routing hint for agents
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at  TEXT                           -- soft delete: "Recently Deleted"
);
CREATE INDEX IF NOT EXISTS idx_notes_live ON notes (deleted_at, pinned, updated_at);

-- SPEC-v31. Inline images for a note body: one-to-many like lead_touches to
-- leads, not journal_entries' single media_path/media_kind columns (a note
-- routinely needs many images at different points in one body). Deliberately
-- no caption/alt_text column: caption lives in exactly one place, the note
-- body's own Markdown `![caption](note-image:TOKEN)` embed, per the data
-- skill's single-read-path law (D5) against two copies of one fact with no
-- sync rule. token's inline UNIQUE is this codebase's own house style for a
-- unique index (see leads.phone_norm, inbound_requests.request_id above),
-- not a separate CREATE UNIQUE INDEX statement.
CREATE TABLE IF NOT EXISTS note_attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE,   -- opaque id embedded in body text
    path        TEXT NOT NULL,          -- ROOT-relative, data/notes/YYYY/MM/<note_id>-<token>.<ext>
    kind        TEXT NOT NULL DEFAULT 'photo',
    width       INTEGER,
    height      INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_note_attachments_note ON note_attachments(note_id, deleted_at);

-- SPEC-v9 "The Line". Scored/scraped columns come from enrich_prospects.py and
-- are refreshed on re-import; the state block below is Ian's and the importer
-- must never overwrite it.
CREATE TABLE IF NOT EXISTS leads (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone_norm    TEXT UNIQUE,                  -- 10 digits; the import key
    phone         TEXT NOT NULL DEFAULT '',
    business_name TEXT NOT NULL,
    owner_name    TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    city          TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL DEFAULT '',
    market        TEXT NOT NULL DEFAULT '',     -- north | south
    segment       TEXT NOT NULL DEFAULT '',     -- trades | property | emergency
    service_type  TEXT NOT NULL DEFAULT '',
    tier          TEXT NOT NULL DEFAULT 'C' CHECK (tier IN ('A','B','C','D')),
    fit           INTEGER NOT NULL DEFAULT 0,
    pain          INTEGER NOT NULL DEFAULT 0,
    reach         INTEGER NOT NULL DEFAULT 0,
    total         INTEGER NOT NULL DEFAULT 0,
    why           TEXT NOT NULL DEFAULT '',
    miss_signal   TEXT NOT NULL DEFAULT '',     -- the review quote, the ammunition
    claims_247    INTEGER NOT NULL DEFAULT 0,
    rating        REAL,
    reviews       INTEGER,
    website       TEXT NOT NULL DEFAULT '',
    site_status   TEXT NOT NULL DEFAULT '',     -- ok | none | failed
    platform      TEXT NOT NULL DEFAULT '',
    address       TEXT NOT NULL DEFAULT '',
    maps_url      TEXT NOT NULL DEFAULT '',
    -- state Ian owns. NEVER written by the importer on an existing row.
    stage         TEXT NOT NULL DEFAULT 'new'
                  CHECK (stage IN ('new','attempted','reached','demo','won','lost','parked')),
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_touch    TEXT,
    next_touch    TEXT,
    notes         TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT 'enriched.csv',
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- A "run" is one bounded calling session, the unit of the game. Runs never
-- carry a penalty forward; they exist to be finite.
CREATE TABLE IF NOT EXISTS call_runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    date       TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    ended_at   TEXT,
    target     INTEGER NOT NULL DEFAULT 10,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Events, not tallies (the streak_events precedent). One row per touch, ever.
CREATE TABLE IF NOT EXISTS lead_touches (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    run_id     INTEGER REFERENCES call_runs(id) ON DELETE SET NULL,
    date       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('call','follow_up','demo','email','text')),
    outcome    TEXT NOT NULL DEFAULT '' CHECK (outcome IN
                 ('','no_answer','voicemail','gatekeeper','reached',
                  'booked','not_interested','bad_number')),
    duration_s INTEGER NOT NULL DEFAULT 0,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_facts_domain ON facts(domain);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
CREATE INDEX IF NOT EXISTS idx_content_date ON content_log(date);
CREATE INDEX IF NOT EXISTS idx_plan_date ON plan_blocks(date);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_tier ON leads(tier);
CREATE INDEX IF NOT EXISTS idx_leads_next ON leads(next_touch);
CREATE INDEX IF NOT EXISTS idx_touches_lead ON lead_touches(lead_id);
CREATE INDEX IF NOT EXISTS idx_touches_date ON lead_touches(date);
CREATE INDEX IF NOT EXISTS idx_runs_date ON call_runs(date);

-- SPEC-v17 BtC inbound: demo bookings + contact messages pulled from
-- beatyourclock.com. ingest/sync_btc.py is the ONLY writer for this seam.
-- The consent column is legally load-bearing A2P evidence and is WALLED
-- (journal precedent): never in /api/state, memos, facts, or any agent tool.
CREATE TABLE IF NOT EXISTS inbound_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  TEXT NOT NULL UNIQUE,          -- minted on the site; the dedupe key
    kind        TEXT NOT NULL CHECK (kind IN ('demo','contact')),
    lead_id     INTEGER REFERENCES leads(id) ON DELETE SET NULL,
    status      TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new','confirmed','dismissed')),
    name        TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL DEFAULT '',
    phone       TEXT NOT NULL DEFAULT '',
    topics      TEXT NOT NULL DEFAULT '[]',    -- JSON list of strings
    windows     TEXT NOT NULL DEFAULT '[]',    -- JSON list of {date,window,label}
    interest    TEXT NOT NULL DEFAULT '',
    message     TEXT NOT NULL DEFAULT '',
    consent     TEXT NOT NULL DEFAULT '{}',    -- WALLED, see above
    -- SPEC-v19. 'btc' is a Clockwork lead and gets a leads row; 'personal'
    -- is correspondence from ianmccallum.com and NEVER touches leads, because
    -- polluting the call queue would break the one ordering guarantee
    -- The Line exists to make.
    source      TEXT NOT NULL DEFAULT 'btc' CHECK (source IN ('btc','personal')),
    received_at TEXT NOT NULL,                  -- UTC ISO, as the site sent it
    -- SPEC-v18. promised_by is STORED, not derived: a deadline recomputed
    -- from "now" cannot be alerted on exactly once. It is naive LOCAL time,
    -- like every other timestamp here, converted from the UTC received_at
    -- (mixing the two silently shifts every deadline ~5h in Central).
    promised_by TEXT,
    alerted_at  TEXT,                           -- fire-once guard for the push
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_requests(status);

-- SPEC-v25. One-row daytime chat preference. Nightly code must not read this.
CREATE TABLE IF NOT EXISTS chat_prefs (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    default_model  TEXT NOT NULL DEFAULT 'claude-sonnet-5'
                     CHECK (default_model IN ('claude-haiku-4-5', 'claude-sonnet-5'))
);
INSERT OR IGNORE INTO chat_prefs (id, default_model) VALUES (1, 'claude-sonnet-5');

-- SPEC-v34. One-row gym tracking preference: how many days a week are
-- trackable and how many of those Ian may miss per week before the streak
-- resets. Mirrors chat_prefs' singleton shape exactly. Ian's own choice,
-- never agent-written.
CREATE TABLE IF NOT EXISTS gym_prefs (
    id                    INTEGER PRIMARY KEY CHECK (id = 1),
    track_days_per_week   INTEGER NOT NULL DEFAULT 5
                          CHECK (track_days_per_week IN (5, 7)),
    rest_days_per_week    INTEGER NOT NULL DEFAULT 2
                          CHECK (rest_days_per_week BETWEEN 0 AND 6),
    updated_at            TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
INSERT OR IGNORE INTO gym_prefs (id) VALUES (1);

-- SPEC-v30. One-row Money page display preference: hero metric choice,
-- widget order/visibility. Mirrors chat_prefs' singleton shape exactly.
-- Ian's own display config, never agent-facing.
CREATE TABLE IF NOT EXISTS money_prefs (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    hero_metric  TEXT NOT NULL DEFAULT 'net_worth'
                 CHECK (hero_metric IN ('net_worth','burn','cash','goal')),
    hero_goal_id INTEGER REFERENCES goals(id),
    widgets_json TEXT NOT NULL DEFAULT
      '[{"key":"accounts","visible":true},{"key":"goals","visible":true},
        {"key":"burn","visible":true},{"key":"transactions","visible":true}]',
    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
INSERT OR IGNORE INTO money_prefs (id) VALUES (1);

-- SPEC-v30 Phase 3. Replaces the hardcoded BUSINESS_CATEGORIES Python set
-- with a real, user-editable table: Ian can add/rename/re-cap a budget
-- category from the UI instead of editing code. `categories` is a JSON
-- array of transactions.category values this budget line groups; it is a
-- pure read-side aggregation over transactions.category, never written
-- back (import_csv.py stays the sole writer of that column, money is
-- sacred per CLAUDE.md). Soft-delete via `archived`, matching goals.archived
-- (partner_tasks' deleted_at/deleted_batch_id is a different mechanism).
CREATE TABLE IF NOT EXISTS budget_categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    cap        REAL NOT NULL,
    categories TEXT NOT NULL DEFAULT '[]',  -- JSON array of transactions.category values
    color      TEXT DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
-- budget_rules exists for personal spend, which today has almost nothing to
-- group (KEYWORD_CATEGORIES in ingest/categorize.py is 11 business-vendor
-- entries; personal transactions overwhelmingly land as category=''). A
-- rule matches ONLY category='' transactions, by the same lowercase-
-- substring semantics categorize() already uses, so a personal rule can
-- never poach an already-categorized business transaction.
CREATE TABLE IF NOT EXISTS budget_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    keyword     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
-- Seeds exactly one row reproducing today's hardcoded cap, so nothing
-- regresses on day one: this is BUSINESS_CATEGORIES (below) becoming row
-- one of a list Ian can add to, not a second parallel system living beside
-- the Python set.
INSERT OR IGNORE INTO budget_categories (name, cap, categories)
VALUES ('Business burn', 150,
        '["ai","telecom","hosting","saas","domain","marketing","fees","legal"]');

-- SPEC-v25. At most one OPEN thread (enforced in create_chat_thread).
CREATE TABLE IF NOT EXISTS chat_threads (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    -- SPEC-v26: the four plan models, and one agent per thread. Role is a
    -- foreign key into the role files, validated at the API boundary.
    model              TEXT NOT NULL DEFAULT 'claude-sonnet-5'
                         CHECK (model IN ('claude-haiku-4-5', 'claude-sonnet-5',
                                          'claude-opus-5', 'claude-fable-5')),
    role               TEXT NOT NULL DEFAULT 'chief',
    effort             TEXT NOT NULL DEFAULT 'high',
    granted_chips      TEXT NOT NULL DEFAULT '[]',
    specialist_sonnet  INTEGER NOT NULL DEFAULT 0 CHECK (specialist_sonnet IN (0, 1)),
    status             TEXT NOT NULL DEFAULT 'OPEN'
                         CHECK (status IN ('OPEN', 'CLOSED')),
    -- SPEC-v37 §7.4: native SDK session continuity, replacing the
    -- hand-rolled _prior_turn_prompt_rows/_chat_prior_block mechanism. Empty
    -- string (not NULL) until the thread's first turn completes.
    sdk_session_id     TEXT NOT NULL DEFAULT '',
    -- SPEC-v40 §3.2: durable threads. title is server-set from the first
    -- question (never model-written); summary is Compact's bounded output
    -- (empty = never compacted); summary_turn_count is how many turns it
    -- covers; compacted_at is when. Plain ALTERs in _migrate_columns.
    title              TEXT NOT NULL DEFAULT '',
    summary            TEXT NOT NULL DEFAULT '',
    summary_turn_count INTEGER NOT NULL DEFAULT 0,
    compacted_at       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- SPEC-v23. Interactive consultations are a short-lived conversation cache,
-- not agent memory. Nothing in the agent read surface exposes this table.
-- SPEC-v25 adds mode 'chat' and kinds chat_turn/chat_child; Ask/inspect rows
-- keep thread_id NULL.
CREATE TABLE IF NOT EXISTS agent_invocations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    role          TEXT NOT NULL,
    -- SPEC-v24: 'inspect' is a role-walled, entity-grounded consultation.
    -- Precomputed record context never lands in this table, only role/mode/
    -- question/answer do (see api/main.py's in-memory entity-context handoff).
    -- SPEC-v25: 'chat' is a daytime Fury turn on a chat_threads row.
    mode          TEXT NOT NULL CHECK (mode IN ('ask', 'inspect', 'chat')),
    question      TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (
                      status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')
                  ) DEFAULT 'QUEUED',
    answer        TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    error_code    TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    turns         INTEGER,
    cost_usd      REAL,
    started_at    TEXT,
    finished_at   TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    invocation_kind TEXT NOT NULL DEFAULT 'single'
                    CHECK (invocation_kind IN (
                        'single','room','room_child','chat_turn','chat_child'
                    )),
    parent_id       INTEGER REFERENCES agent_invocations(id) ON DELETE CASCADE,
    sequence_index  INTEGER NOT NULL DEFAULT 0,
    thread_id       INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_agent_invocations_status_created
    ON agent_invocations(status, created_at DESC);

-- SPEC-v37 §4.5. Ring 1 receipts: every reversible act an agent applies
-- without approval is recorded here in the same transaction as the act
-- itself (Law A5: no receipt row, no act). `inverse_json` carries whatever
-- `core.acts.undo_act` needs to restore the prior row exactly through the
-- same write path that made the change.
CREATE TABLE IF NOT EXISTS agent_acts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role         TEXT NOT NULL,
    act          TEXT NOT NULL,
    plane        TEXT NOT NULL CHECK (plane IN ('nightly','consult')),
    thread_id    INTEGER REFERENCES chat_threads(id) ON DELETE SET NULL,
    target_kind  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    summary      TEXT NOT NULL,
    inverse_json TEXT NOT NULL,
    undone_at    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_agent_acts_created ON agent_acts(created_at DESC);

-- SPEC-v37 §4.2 `attention.snooze`: live state a Ring 1 snooze needs to
-- actually suppress an item, separate from the `agent_acts` audit row (which
-- is retrospective and not meant to be queried on every attention compile).
-- One active snooze per item key; a fresh snooze on an already-snoozed key
-- simply replaces it rather than stacking.
CREATE TABLE IF NOT EXISTS attention_snoozes (
    item_key      TEXT PRIMARY KEY,
    snoozed_until TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- SPEC-v37 §5.4: Stage 1 of the memory index, lexical only, zero new
-- dependencies. Rebuilt wholesale by core.memory_index.sync_memory_index()
-- at the end of every nightly run -- not trigger-maintained, so a search
-- reflects last night's state, which is fine for a tool whose every result
-- is explicitly marked recall, never live fact (Law A6). The indexer takes
-- an explicit table allowlist (core/memory_index.py); a new table is
-- invisible to it until someone adds it deliberately (Law A7).
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    body, topic, kind UNINDEXED, source_table UNINDEXED,
    source_id UNINDEXED, occurred_at UNINDEXED,
    tokenize = 'porter unicode61'
);
"""

# SPEC-v30 Phase 3: superseded as the live source of truth by the
# budget_categories table (seeded with this exact set as its "Business burn"
# row, see SCHEMA above). burn_by_month/month_burn_detail no longer read
# this constant; it stays only as the historical/reference set and as the
# fallback _budget_burn_categories() uses if every budget_categories row
# is ever archived.
BUSINESS_CATEGORIES = {
    "ai", "telecom", "hosting", "saas", "domain", "marketing", "fees", "legal"
}

# SPEC-v30 Phase 2: closed sets for per-account color/icon customization.
# Colors are the hex-only subset of ROLE_COLORS (dashboard/src/lib/agents.js)
# -- the same literal hex strings, for visual consistency across the app --
# deliberately excluding its var(--good)/var(--warn)/var(--crit)/etc entries,
# which carry real status meaning elsewhere on the Money page (burnLevel/
# utilLevel) and must never be reused for plain account identity.
ACCOUNT_COLORS = {
    "#818cf8",  # counsel
    "#38bdf8",  # infra
    "#f472b6",  # lovebird
    "#c084fc",  # advisor
    "#facc15",  # wealth
    "#fb923c",  # publicist
    "#fca5a5",  # coach
    "#a3e635",  # family
    # Ian asked for a bigger account palette than the 8 reused from
    # ROLE_COLORS. These 8 are new, not agent colors: chosen to avoid the
    # semantic tokens (--good #4ade80, --warn #fbbf24, --crit #f87171,
    # --accent #6ea8ff) so an account color never reads as a status.
    "#2dd4bf",  # teal
    "#22d3ee",  # cyan
    "#a78bfa",  # violet
    "#e879f9",  # fuchsia
    "#fb7185",  # rose
    "#3b82f6",  # blue
    "#d97706",  # amber
    "#94a3b8",  # slate
}

# Short glyph strings, one per common account type. Distinct from
# ROLE_GLYPHS on purpose (same character meaning two different things in
# two different UI surfaces would be confusing). "-" (other/unset) matches
# the existing "UI empty values use ASCII `-`" convention.
ACCOUNT_ICONS = {
    "⌂",  # bank / checking
    "▭",  # card
    "◎",  # savings
    "▲",  # investment
    "₿",  # crypto
    "$",       # cash
    "⊘",  # loan / debt
    "◔",  # retirement
    "◫",  # credit
    "-",       # other
}


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(r[1] == column for r in conn.execute(f"PRAGMA table_info({table})"))


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _migrate_proposals_kind(conn: sqlite3.Connection) -> None:
    """Expand proposal kinds on legacy DBs."""
    if not _table_exists(conn, "proposals"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()
    if row and "'health'" in (row[0] or ""):
        return
    conn.executescript("""
        CREATE TABLE proposals_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            role              TEXT NOT NULL,
            action            TEXT NOT NULL,
            reasoning         TEXT NOT NULL,
            kind              TEXT NOT NULL DEFAULT 'task'
                              CHECK (kind IN ('money', 'task', 'legal', 'health', 'personal')),
            status            TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
            created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            decided_at        TEXT,
            attachment_type   TEXT NOT NULL DEFAULT '',
            attachment_json   TEXT NOT NULL DEFAULT '',
            urgency           TEXT NOT NULL DEFAULT 'normal',
            due_at            TEXT,
            reversibility     TEXT NOT NULL DEFAULT 'reversible',
            evidence_json     TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO proposals_new
            (id, role, action, reasoning, kind, status, created_at, decided_at,
             attachment_type, attachment_json, urgency, due_at, reversibility,
             evidence_json)
        SELECT id, role, action, reasoning, kind, status, created_at, decided_at,
               attachment_type, attachment_json, urgency, due_at, reversibility,
               evidence_json
        FROM proposals;
        DROP TABLE proposals;
        ALTER TABLE proposals_new RENAME TO proposals;
    """)


def _migrate_proposals_expired(conn: sqlite3.Connection) -> None:
    """Widen the status CHECK to admit EXPIRED (SPEC-v32).

    SQLite cannot ALTER a CHECK, so the table is rebuilt. This runs AFTER
    _migrate_columns, so every column that was only ever ALTERed in has to be
    named in both the DDL and the SELECT: a rebuild that forgets one drops the
    very state it was meant to preserve (the chat_threads.effort lesson).
    Statuses, ids, and timestamps are carried verbatim; nothing is reclassified
    by the migration itself.
    """
    if not _table_exists(conn, "proposals"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()
    sql = (row[0] or "") if row else ""
    if not sql or "'EXPIRED'" in sql:
        return
    conn.executescript("""
        CREATE TABLE proposals_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            role              TEXT NOT NULL,
            action            TEXT NOT NULL,
            reasoning         TEXT NOT NULL,
            kind              TEXT NOT NULL DEFAULT 'task'
                              CHECK (kind IN ('money', 'task', 'legal', 'health', 'personal')),
            status            TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
            created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            decided_at        TEXT,
            attachment_type   TEXT NOT NULL DEFAULT '',
            attachment_json   TEXT NOT NULL DEFAULT '',
            urgency           TEXT NOT NULL DEFAULT 'normal',
            due_at            TEXT,
            reversibility     TEXT NOT NULL DEFAULT 'reversible',
            evidence_json     TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO proposals_new
            (id, role, action, reasoning, kind, status, created_at, decided_at,
             attachment_type, attachment_json, urgency, due_at, reversibility,
             evidence_json)
        SELECT id, role, action, reasoning, kind, status, created_at, decided_at,
               attachment_type, attachment_json, urgency, due_at, reversibility,
               evidence_json
        FROM proposals;
        DROP TABLE proposals;
        ALTER TABLE proposals_new RENAME TO proposals;
    """)


def _migrate_proposals_ring2_kinds(conn: sqlite3.Connection) -> None:
    """Widen the kind CHECK to admit goal_change and quota_rebaseline
    (SPEC-v37 §4.3): the two new proposal kinds that give the dead APPROVE
    loop a verb for "this goal is obsolete" and "rebaseline a whole quota
    set", beyond the money/task/legal/health/personal set.

    Must run AFTER _migrate_proposals_expired, and must carry every column
    that migration already carries (including the EXPIRED status, not just
    the original three) or this rebuild silently reverts it.
    """
    if not _table_exists(conn, "proposals"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='proposals'"
    ).fetchone()
    sql = (row[0] or "") if row else ""
    if not sql or "'goal_change'" in sql:
        return
    conn.executescript("""
        CREATE TABLE proposals_new (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            role              TEXT NOT NULL,
            action            TEXT NOT NULL,
            reasoning         TEXT NOT NULL,
            kind              TEXT NOT NULL DEFAULT 'task'
                              CHECK (kind IN ('money', 'task', 'legal', 'health',
                                              'personal', 'goal_change', 'quota_rebaseline')),
            status            TEXT NOT NULL DEFAULT 'PENDING'
                              CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'EXPIRED')),
            created_at        TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            decided_at        TEXT,
            attachment_type   TEXT NOT NULL DEFAULT '',
            attachment_json   TEXT NOT NULL DEFAULT '',
            urgency           TEXT NOT NULL DEFAULT 'normal',
            due_at            TEXT,
            reversibility     TEXT NOT NULL DEFAULT 'reversible',
            evidence_json     TEXT NOT NULL DEFAULT '[]'
        );
        INSERT INTO proposals_new
            (id, role, action, reasoning, kind, status, created_at, decided_at,
             attachment_type, attachment_json, urgency, due_at, reversibility,
             evidence_json)
        SELECT id, role, action, reasoning, kind, status, created_at, decided_at,
               attachment_type, attachment_json, urgency, due_at, reversibility,
               evidence_json
        FROM proposals;
        DROP TABLE proposals;
        ALTER TABLE proposals_new RENAME TO proposals;
    """)


def _migrate_columns(conn: sqlite3.Connection) -> None:
    alters = [
        ("transactions", "source", "TEXT NOT NULL DEFAULT 'csv'"),
        ("briefs", "day_command", "TEXT NOT NULL DEFAULT ''"),
        ("goals", "domain", "TEXT NOT NULL DEFAULT 'business'"),
        ("goals", "metric_key", "TEXT NOT NULL DEFAULT ''"),
        ("goals", "depends_on_goal_id", "INTEGER"),
        ("goals", "hero", "INTEGER NOT NULL DEFAULT 0"),
        ("goals", "priority", "INTEGER NOT NULL DEFAULT 0"),
        # Retire a goal without destroying it, so Undo restores the same row : 
        # metrics resolve off goal ids, so a re-created goal is not a restore.
        ("goals", "archived", "INTEGER NOT NULL DEFAULT 0"),
        ("health_daily", "workout", "TEXT NOT NULL DEFAULT ''"),
        ("health_daily", "gym_confirmed", "INTEGER NOT NULL DEFAULT 0"),
        ("memos", "priority", "INTEGER NOT NULL DEFAULT 1"),
        ("memos", "archived", "INTEGER NOT NULL DEFAULT 0"),
        ("memos", "archived_at", "TEXT"),
        ("memos", "archived_into_id", "INTEGER REFERENCES memos(id) ON DELETE SET NULL"),
        # SPEC-v23: inert proposal drafts + verified decision metadata.
        ("proposals", "attachment_type", "TEXT NOT NULL DEFAULT ''"),
        ("proposals", "attachment_json", "TEXT NOT NULL DEFAULT ''"),
        ("proposals", "urgency", "TEXT NOT NULL DEFAULT 'normal'"),
        ("proposals", "due_at", "TEXT"),
        ("proposals", "reversibility", "TEXT NOT NULL DEFAULT 'reversible'"),
        ("proposals", "evidence_json", "TEXT NOT NULL DEFAULT '[]'"),
        # SPEC-v23 Phase 6: one room parent with ordered invocation children.
        ("agent_invocations", "invocation_kind", "TEXT NOT NULL DEFAULT 'single'"),
        ("agent_invocations", "parent_id",
         "INTEGER REFERENCES agent_invocations(id) ON DELETE CASCADE"),
        ("agent_invocations", "sequence_index", "INTEGER NOT NULL DEFAULT 0"),
        # SPEC-v22: one child level and reversible subtree archives.
        ("partner_tasks", "parent_id", "INTEGER REFERENCES partner_tasks(id)"),
        ("partner_tasks", "deleted_at", "TEXT"),
        ("partner_tasks", "deleted_batch_id", "TEXT"),
        # SPEC-v20 Phase D: distinguish a started sync from durable success.
        ("ingest_log", "last_attempt", "TEXT"),
        ("ingest_log", "last_success", "TEXT"),
        ("ingest_log", "last_error", "TEXT NOT NULL DEFAULT ''"),
        ("ingest_log", "consecutive_failures", "INTEGER NOT NULL DEFAULT 0"),
        ("ingest_log", "stale_alerted_at", "TEXT"),
        # SPEC-v18: the promise clock on an inbound request.
        ("inbound_requests", "promised_by", "TEXT"),
        ("inbound_requests", "alerted_at", "TEXT"),
        # SPEC-v19: which site this came from. Defaults to 'btc' so every
        # existing row keeps meaning exactly what it meant.
        ("inbound_requests", "source", "TEXT NOT NULL DEFAULT 'btc'"),
        # SPEC-v24: stable link into financial_accounts, '<source>:<external_id>'. '' = unlinked (CSV/legacy).
        # SPEC-v27: per-thread reasoning effort. Validated at the API
        # boundary against CHAT_EFFORTS, as role is.
        ("chat_threads", "effort", "TEXT NOT NULL DEFAULT 'high'"),
        ("transactions", "account_key", "TEXT NOT NULL DEFAULT ''"),
        ("holdings", "account_key", "TEXT NOT NULL DEFAULT ''"),
        # SPEC-v30 Phase 2: Ian's own per-account color/icon choice. Never
        # added to upsert_financial_accounts' ON CONFLICT column list, so a
        # Plaid/SimpleFIN/SnapTrade sync can never wipe it (LEAD_SCRAPED_COLS
        # precedent). Written only via set_account_appearance.
        ("financial_accounts", "color", "TEXT NOT NULL DEFAULT ''"),
        ("financial_accounts", "icon", "TEXT NOT NULL DEFAULT ''"),
        # SPEC-v31: nested folders for notes. NULL = unfiled ("All Notes"),
        # so the ~existing rows need zero backfill. deleted_batch_id is the
        # shared cascade token a folder delete stamps across itself, its
        # descendants, and every note inside them (partner_tasks precedent).
        ("notes", "folder_id", "INTEGER REFERENCES note_folders(id)"),
        ("notes", "deleted_batch_id", "TEXT"),
        # SPEC-v32 Part D: the Day Command can refresh live. anchor_key is
        # computed server-side (never trusted from the model); command_refreshes
        # caps how many times one brief's sentence may be rewritten per day.
        ("briefs", "anchor_key", "TEXT NOT NULL DEFAULT ''"),
        ("briefs", "command_refreshes", "INTEGER NOT NULL DEFAULT 0"),
        # SPEC-v37 §8.2: the day the Day Command is FOR, not the night the
        # run wrote it. A 21:30 run stamps `date` with tonight but
        # `governs_date` with tomorrow, so the stale chip compares the right
        # thing. Backfilled below for rows that predate the column.
        ("briefs", "governs_date", "TEXT NOT NULL DEFAULT ''"),
        # SPEC-v37 3.5: Alfred (steward) is the default agent, not Fury.
        ("chat_prefs", "default_role", "TEXT NOT NULL DEFAULT 'steward'"),
        # SPEC-v37 6.2: goals.season, derived from school_items term bounds
        # at read time (school.current_season), never hardcoded. 'always' is
        # the backward-compatible default: every existing goal is unaffected.
        ("goals", "season", "TEXT NOT NULL DEFAULT 'always'"),
        # SPEC-v37 §7.4: native SDK session continuity (see also
        # _migrate_chat_threads_v26, which carries this column forward on a
        # database old enough to still need that rebuild).
        ("chat_threads", "sdk_session_id", "TEXT NOT NULL DEFAULT ''"),
        # SPEC-v37 §8.6: "N of M woke; K off; J out of season" -- computed in
        # run_sequence, never the model's own account of the night. Kept off
        # `body` (the chief's own prose) on purpose: a mechanical status line
        # mixed into a persona's voice reads as slop the moment you notice
        # it, so it travels with the brief row instead, for the dashboard to
        # render as its own small line wherever it renders the brief.
        ("briefs", "dispatch_summary", "TEXT NOT NULL DEFAULT ''"),
        # SPEC-v40 §3.2: durable threads. No CHECK touched, so no rebuild.
        ("chat_threads", "title", "TEXT NOT NULL DEFAULT ''"),
        ("chat_threads", "summary", "TEXT NOT NULL DEFAULT ''"),
        ("chat_threads", "summary_turn_count", "INTEGER NOT NULL DEFAULT 0"),
        ("chat_threads", "compacted_at", "TEXT"),
    ]
    for table, col, typedef in alters:
        if _table_exists(conn, table) and not _column_exists(conn, table, col):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")


def _migrate_goals_school_domain(conn: sqlite3.Connection) -> None:
    """Allow school domain on goals (SQLite cannot ALTER CHECK)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='goals'"
    ).fetchone()
    if not row or "'school'" in (row[0] or ""):
        return
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS goals_new (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            name               TEXT NOT NULL UNIQUE,
            kind               TEXT NOT NULL DEFAULT 'goal'
                               CHECK (kind IN ('goal', 'quota', 'deadline')),
            target             TEXT NOT NULL,
            unit               TEXT NOT NULL DEFAULT '',
            deadline           TEXT,
            current_value      TEXT NOT NULL DEFAULT '',
            notes              TEXT NOT NULL DEFAULT '',
            domain             TEXT NOT NULL DEFAULT 'business'
                               CHECK (domain IN ('business', 'health', 'personal', 'finance', 'school')),
            metric_key         TEXT NOT NULL DEFAULT '',
            depends_on_goal_id INTEGER REFERENCES goals(id),
            hero               INTEGER NOT NULL DEFAULT 0,
            priority           INTEGER NOT NULL DEFAULT 0,
            archived           INTEGER NOT NULL DEFAULT 0,
            season             TEXT NOT NULL DEFAULT 'always'
        );
        INSERT INTO goals_new SELECT * FROM goals;
        DROP TABLE goals;
        ALTER TABLE goals_new RENAME TO goals;
    """)


def _migrate_agent_invocations_mode(conn: sqlite3.Connection) -> None:
    """Allow 'inspect' alongside 'ask' (SQLite cannot ALTER a CHECK clause)."""
    if not _table_exists(conn, "agent_invocations"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_invocations'"
    ).fetchone()
    if not row or "'inspect'" in (row[0] or ""):
        return
    conn.executescript("""
        CREATE TABLE agent_invocations_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            role          TEXT NOT NULL,
            mode          TEXT NOT NULL CHECK (mode IN ('ask', 'inspect')),
            question      TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (
                              status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')
                          ) DEFAULT 'QUEUED',
            answer        TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            error_code    TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            turns         INTEGER,
            cost_usd      REAL,
            started_at    TEXT,
            finished_at   TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            invocation_kind TEXT NOT NULL DEFAULT 'single'
                            CHECK (invocation_kind IN ('single','room','room_child')),
            parent_id       INTEGER REFERENCES agent_invocations(id) ON DELETE CASCADE,
            sequence_index  INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO agent_invocations_new
            (id, role, mode, question, status, answer, evidence_json, error_code,
             error_message, model, turns, cost_usd, started_at, finished_at,
             created_at, invocation_kind, parent_id, sequence_index)
        SELECT id, role, mode, question, status, answer, evidence_json, error_code,
               error_message, model, turns, cost_usd, started_at, finished_at,
               created_at, invocation_kind, parent_id, sequence_index
        FROM agent_invocations;
        DROP TABLE agent_invocations;
        ALTER TABLE agent_invocations_new RENAME TO agent_invocations;
    """)


def _migrate_chat_threads_v26(conn: sqlite3.Connection) -> None:
    """Widen the model CHECK to four models and add role (SPEC-v26).

    SQLite cannot ALTER a CHECK, so the table is rebuilt. Existing threads
    keep their id, model, chips, and status, and adopt role 'chief', which
    is what every v25 thread actually was.
    """
    if not _table_exists(conn, "chat_threads"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='chat_threads'"
    ).fetchone()
    sql = (row[0] or "") if row else ""
    if not sql or "claude-opus-5" in sql:
        return
    has_role = _column_exists(conn, "chat_threads", "role")
    role_select = "role" if has_role else "'chief'"
    # This rebuild runs after _migrate_columns, so a column that was just
    # ALTERed in has to be carried across or it is dropped again on the very
    # migration that was meant to preserve state.
    has_effort = _column_exists(conn, "chat_threads", "effort")
    effort_select = "effort" if has_effort else "'high'"
    # SPEC-v37 §7.4: _migrate_columns (run_migrations' first call) may have
    # already ALTERed sdk_session_id in before this rebuild runs. A rebuild
    # with an explicit column list drops any such column silently unless it
    # is carried forward here too (the documented trap: "a rebuild must carry
    # every ALTERed column or it drops the one it was meant to preserve").
    has_session = _column_exists(conn, "chat_threads", "sdk_session_id")
    session_select = "sdk_session_id" if has_session else "''"
    conn.executescript(f"""
        CREATE TABLE chat_threads_new (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            model              TEXT NOT NULL DEFAULT 'claude-sonnet-5'
                                 CHECK (model IN ('claude-haiku-4-5', 'claude-sonnet-5',
                                                  'claude-opus-5', 'claude-fable-5')),
            role               TEXT NOT NULL DEFAULT 'chief',
            effort             TEXT NOT NULL DEFAULT 'high',
            granted_chips      TEXT NOT NULL DEFAULT '[]',
            specialist_sonnet  INTEGER NOT NULL DEFAULT 0 CHECK (specialist_sonnet IN (0, 1)),
            status             TEXT NOT NULL DEFAULT 'OPEN'
                                 CHECK (status IN ('OPEN', 'CLOSED')),
            sdk_session_id     TEXT NOT NULL DEFAULT '',
            created_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            updated_at         TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        INSERT INTO chat_threads_new
            (id, model, role, effort, granted_chips, specialist_sonnet, status,
             sdk_session_id, created_at, updated_at)
        SELECT id, model, {role_select}, {effort_select}, granted_chips,
               specialist_sonnet, status, {session_select}, created_at, updated_at
        FROM chat_threads;
        DROP TABLE chat_threads;
        ALTER TABLE chat_threads_new RENAME TO chat_threads;
    """)


def _migrate_agent_invocations_chat(conn: sqlite3.Connection) -> None:
    """Widen mode/kind CHECKs for SPEC-v25 chat and add thread_id.

    SQLite cannot ALTER a CHECK. Existing Ask/inspect rows keep thread_id NULL.
    """
    if not _table_exists(conn, "agent_invocations"):
        return
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_invocations'"
    ).fetchone()
    sql = (row[0] or "") if row else ""
    has_chat = "'chat'" in sql and "'chat_turn'" in sql
    has_thread = _column_exists(conn, "agent_invocations", "thread_id")
    if has_chat and has_thread:
        return
    thread_select = "thread_id" if has_thread else "NULL"
    conn.executescript(f"""
        CREATE TABLE agent_invocations_new (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            role          TEXT NOT NULL,
            mode          TEXT NOT NULL CHECK (mode IN ('ask', 'inspect', 'chat')),
            question      TEXT NOT NULL,
            status        TEXT NOT NULL CHECK (
                              status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')
                          ) DEFAULT 'QUEUED',
            answer        TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            error_code    TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            model         TEXT NOT NULL DEFAULT '',
            turns         INTEGER,
            cost_usd      REAL,
            started_at    TEXT,
            finished_at   TEXT,
            created_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            invocation_kind TEXT NOT NULL DEFAULT 'single'
                            CHECK (invocation_kind IN (
                                'single','room','room_child','chat_turn','chat_child'
                            )),
            parent_id       INTEGER REFERENCES agent_invocations(id) ON DELETE CASCADE,
            sequence_index  INTEGER NOT NULL DEFAULT 0,
            thread_id       INTEGER REFERENCES chat_threads(id) ON DELETE CASCADE
        );
        INSERT INTO agent_invocations_new
            (id, role, mode, question, status, answer, evidence_json, error_code,
             error_message, model, turns, cost_usd, started_at, finished_at,
             created_at, invocation_kind, parent_id, sequence_index, thread_id)
        SELECT id, role, mode, question, status, answer, evidence_json, error_code,
               error_message, model, turns, cost_usd, started_at, finished_at,
               created_at, invocation_kind, parent_id, sequence_index, {thread_select}
        FROM agent_invocations;
        DROP TABLE agent_invocations;
        ALTER TABLE agent_invocations_new RENAME TO agent_invocations;
    """)


def _backfill_chat_thread_titles(conn: sqlite3.Connection) -> None:
    """SPEC-v40 §3.2: threads that predate the title column get one from
    their first question, the same rule create_chat_turn applies going
    forward. Idempotent: only empty titles with at least one turn."""
    if not _table_exists(conn, "chat_threads") or not _column_exists(conn, "chat_threads", "title"):
        return
    rows = conn.execute(
        """SELECT t.id AS id,
                  (SELECT question FROM agent_invocations i
                    WHERE i.thread_id=t.id AND i.invocation_kind='chat_turn'
                    ORDER BY i.id ASC LIMIT 1) AS first_question
             FROM chat_threads t
            WHERE t.title=''"""
    ).fetchall()
    for row in rows:
        title = chat_thread_title(row["first_question"] or "")
        if title:
            conn.execute("UPDATE chat_threads SET title=? WHERE id=?", (title, row["id"]))
    conn.commit()


def run_migrations(conn: sqlite3.Connection) -> None:
    _migrate_columns(conn)
    _backfill_brief_governs_date(conn)
    _backfill_ingest_freshness(conn)
    _migrate_proposals_kind(conn)
    _migrate_proposals_expired(conn)
    _migrate_proposals_ring2_kinds(conn)
    _migrate_goals_school_domain(conn)
    _migrate_agent_invocations_mode(conn)
    _migrate_agent_invocations_chat(conn)
    _migrate_chat_threads_v26(conn)
    # A CHECK rebuild above recreates a table with an explicit column list,
    # so any column _migrate_columns ALTERed in this same run is gone again
    # (the sdk_session_id trap, CLAUDE.md). Re-running the idempotent ALTER
    # pass closes that class of bug for every column, not just the ones the
    # rebuild remembered to carry.
    _migrate_columns(conn)
    _backfill_chat_thread_titles(conn)
    # These indexes reference Phase-B columns that an older table only gains
    # above, so they cannot live in the initial SCHEMA executescript.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_transactions_account_key ON transactions(account_key, date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memos_active_created ON memos(archived, created_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fact_sources_memo ON fact_sources(memo_id)"
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_agent_invocations_status_created
           ON agent_invocations(status, created_at DESC)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_agent_invocations_parent_sequence
           ON agent_invocations(parent_id, sequence_index, id)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_agent_invocations_thread
           ON agent_invocations(thread_id, invocation_kind, id)"""
    )
    conn.execute(
        """CREATE INDEX IF NOT EXISTS idx_partner_active_parent_done
           ON partner_tasks(parent_id, deleted_at, done, id)"""
    )
    conn.execute(
        """CREATE TRIGGER IF NOT EXISTS trg_partner_parent_immutable
           BEFORE UPDATE OF parent_id ON partner_tasks
           WHEN OLD.parent_id IS NOT NEW.parent_id
           BEGIN
               SELECT RAISE(ABORT, 'partner parent_id is immutable');
           END"""
    )
    _backfill_fact_sources(conn)
    _backfill_streak_events(conn)
    _migrate_facts_domain_all(conn)
    _backfill_seeded_placeholder_facts_unverified(conn)
    _delete_seed_holdings(conn)
    _seed_partner_defaults(conn)


def _backfill_brief_governs_date(conn: sqlite3.Connection) -> None:
    """Historic rows predate the column; best effort is the day they ran on
    (SPEC-v37 §8.2). Safe on every connection: rows that already have a
    value are untouched."""
    if not _table_exists(conn, "briefs"):
        return
    conn.execute("UPDATE briefs SET governs_date = date WHERE governs_date = ''")


def _backfill_ingest_freshness(conn: sqlite3.Connection) -> None:
    """Treat the historical compatibility timestamp as a successful attempt."""
    if not _table_exists(conn, "ingest_log"):
        return
    conn.execute(
        """UPDATE ingest_log
           SET last_attempt = COALESCE(last_attempt, last_import),
               last_success = COALESCE(last_success, last_import)
           WHERE last_import IS NOT NULL"""
    )


def _backfill_fact_sources(conn: sqlite3.Connection) -> None:
    """Normalize valid legacy comma-separated fact citations exactly once.

    The old column remains a compatibility projection, so this routine can run
    safely on every connection: relation rows are inserted idempotently, then
    every projection is rebuilt from the relation. Missing historic memo rows
    are deliberately not invented as evidence.
    """
    if not (_table_exists(conn, "facts") and _table_exists(conn, "memos")
            and _table_exists(conn, "fact_sources")):
        return
    for row in conn.execute("SELECT id, source_memo_ids FROM facts"):
        fact_id = row["id"]
        raw = row["source_memo_ids"] or ""
        legacy_ids: list[int] = []
        for token in str(raw).split(","):
            token = token.strip()
            if token and token.isdigit():
                memo_id = int(token)
                if memo_id not in legacy_ids:
                    legacy_ids.append(memo_id)
        if legacy_ids:
            placeholders = ",".join("?" for _ in legacy_ids)
            found = {
                r["id"] for r in conn.execute(
                    f"SELECT id FROM memos WHERE id IN ({placeholders})", legacy_ids
                )
            }
            missing = [memo_id for memo_id in legacy_ids if memo_id not in found]
            if missing:
                logger.warning(
                    "Fact %s has legacy source memo ids no longer retained: %s",
                    fact_id, ",".join(map(str, missing)),
                )
            conn.executemany(
                "INSERT OR IGNORE INTO fact_sources (fact_id, memo_id) VALUES (?, ?)",
                [(fact_id, memo_id) for memo_id in legacy_ids if memo_id in found],
            )
        _sync_fact_source_projection(conn, fact_id)


def _backfill_streak_events(conn: sqlite3.Connection) -> None:
    """Mirror existing gym confirms into the streak_events table (idempotent)."""
    if not _table_exists(conn, "streak_events") or not _table_exists(conn, "health_daily"):
        return
    conn.execute(
        "INSERT OR IGNORE INTO streak_events (date, kind) "
        "SELECT date, 'confirm' FROM health_daily WHERE gym_confirmed = 1"
    )


def _migrate_facts_domain_all(conn: sqlite3.Connection) -> None:
    """SPEC-v37 §5.2: no more domain='all' facts. The archivist was the only
    role ever exempted from the per-domain write check and it is retired, so
    any existing domain='all' row is historical drift, not a live pattern.
    Route each one to its namespace's real home via domain_for_topic(),
    falling back to 'business' the same way every other caller does when a
    topic has no namespace match. Idempotent: nothing is 'all' after the
    first run, so later runs touch zero rows."""
    if not _table_exists(conn, "facts"):
        return
    rows = conn.execute("SELECT id, topic FROM facts WHERE domain='all'").fetchall()
    for row in rows:
        new_domain = domain_for_topic(row["topic"], "business")
        conn.execute("UPDATE facts SET domain=? WHERE id=?", (new_domain, row["id"]))


def _backfill_seeded_placeholder_facts_unverified(conn: sqlite3.Connection) -> None:
    """SPEC-v37 §5.2 migration: a seeded placeholder fact is never trustworthy
    by construction (the seed script's own `SEEDED PLACEHOLDER`/`UNVERIFIED`
    markers say so in the body), so force verified=0 on any that somehow
    ended up verified=1 -- a fabricated verified date is worse than no date.
    Idempotent: a no-op once every matching row is already 0."""
    if not _table_exists(conn, "facts"):
        return
    conn.execute(
        "UPDATE facts SET verified=0 "
        "WHERE verified=1 AND (body LIKE 'SEEDED PLACEHOLDER%' OR body LIKE 'UNVERIFIED.%')"
    )


def _delete_seed_holdings(conn: sqlite3.Connection) -> None:
    """SPEC-v37 §8.4: delete the source='seed' demo holdings (four rows dated
    2026-07-21, $7,420 combined market value) that real SnapTrade data never
    replaced or removed. Left in place, they show as a real balance on
    2026-07-21 and then a cliff to $1,742 the next real snapshot, in any
    history view. Idempotent: a no-op once none remain."""
    if not _table_exists(conn, "holdings"):
        return
    conn.execute("DELETE FROM holdings WHERE source = 'seed'")


def _seed_partner_defaults(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "partner_tasks"):
        return
    n = conn.execute("SELECT COUNT(*) FROM partner_tasks").fetchone()[0]
    if n > 0:
        return
    defaults = [
        ("Buy her flowers", ""),
        ("Go to the water park with her", "Water park, plan a day together"),
    ]
    for title, notes in defaults:
        conn.execute(
            "INSERT INTO partner_tasks (title, notes) VALUES (?, ?)",
            (title, notes),
        )


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    run_migrations(conn)
    conn.commit()
    return conn


def today() -> str:
    return date.today().isoformat()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------- mutation receipts

# One service-worker release can still replay the old timestamp/random ids
# generated by dashboard/src/lib/offline.js. New writes are canonical UUIDs.
_UUID_MUTATION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_LEGACY_MUTATION_ID = re.compile(r"^\d{13}-[a-z0-9]{6}$")


class MutationReceiptConflict(Exception):
    """A mutation id was reused for a different operation or semantic body."""


def valid_mutation_id(mutation_id: str) -> bool:
    """Accept only v4/v5 UUIDs or the precise historical queue-id shape."""
    return bool(_UUID_MUTATION_ID.fullmatch(mutation_id) or _LEGACY_MUTATION_ID.fullmatch(mutation_id))


def mutation_request_hash(operation: str, semantic_body: object,
                          effective_date: str | None) -> str:
    """Stable, non-secret hash used to detect a dangerous id reuse."""
    canonical = json.dumps(
        {
            "operation": operation,
            "body": semantic_body,
            "effective_date": effective_date,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def store_mutation_receipt(conn, mutation_id: str, operation: str,
                           request_hash: str, effective_date: str | None,
                           captured_at: str | None, status_code: int,
                           response_json: str) -> None:
    """Insert a receipt inside the caller's already-open transaction."""
    conn.execute(
        """INSERT INTO mutation_receipts
           (mutation_id, operation, request_hash, effective_date, captured_at,
            status_code, response_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (mutation_id, operation, request_hash, effective_date, captured_at,
         status_code, response_json),
    )


def apply_with_mutation_receipt(conn, mutation_id: str, operation: str,
                                semantic_body: object, effective_date: str | None,
                                captured_at: str | None, apply,
                                status_code: int = 200) -> tuple[object, int, bool]:
    """Apply a browser mutation exactly once.

    `apply` must not commit. The business write, its optional memo, and this
    receipt are all committed together. The returned flag is true for a stored
    replay, so the API can mark the response without changing its JSON.
    """
    request_hash = mutation_request_hash(operation, semantic_body, effective_date)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            """SELECT operation, request_hash, status_code, response_json
               FROM mutation_receipts WHERE mutation_id = ?""",
            (mutation_id,),
        ).fetchone()
        if row is not None:
            if row["operation"] != operation or row["request_hash"] != request_hash:
                raise MutationReceiptConflict("mutation id was reused with a different request")
            response = json.loads(row["response_json"])
            conn.rollback()  # read-only replay: release the BEGIN IMMEDIATE lock
            return response, int(row["status_code"]), True

        response = apply()
        response_json = json.dumps(
            response, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        )
        store_mutation_receipt(
            conn, mutation_id, operation, request_hash, effective_date,
            captured_at, status_code, response_json,
        )
        conn.commit()
        return response, status_code, False
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


# ----------------------------------------------------- agent invocations

AGENT_INVOCATION_TERMINAL = ("SUCCEEDED", "FAILED")
_ROOM_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _bounded_invocation_text(value: object, limit: int) -> str:
    """Strip unsafe control bytes and cap transient invocation text."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    return text.strip()[:limit]


def _normalize_invocation_evidence(evidence: object) -> list[str]:
    """Keep only small, human-readable labels; raw tool data never belongs here."""
    if not isinstance(evidence, (list, tuple, set)):
        return []
    labels: list[str] = []
    for value in evidence:
        if not isinstance(value, str):
            continue
        label = _bounded_invocation_text(value, 120)
        if label in AGENT_INVOCATION_EVIDENCE_LABELS and label not in labels:
            labels.append(label)
        if len(labels) >= len(AGENT_INVOCATION_EVIDENCE_LABELS):
            break
    return labels


def _agent_invocation_dict(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    try:
        evidence = json.loads(item.pop("evidence_json", "[]"))
    except (TypeError, ValueError):
        evidence = []
    item["evidence"] = _normalize_invocation_evidence(evidence)
    return item


def create_agent_invocation(conn, role: str, mode: str, question: str) -> dict:
    """Create one durable, read-only consultation in QUEUED state.

    'ask' requires real question text. 'inspect' (SPEC-v24) is grounded by a
    precomputed entity-context block that never enters this table (see
    api/main.py), so its question may be blank.
    """
    role = _bounded_invocation_text(role, 64)
    mode = _bounded_invocation_text(mode, 16)
    question = _bounded_invocation_text(question, 1501)
    if not role:
        raise ValueError("agent invocation requires a role")
    if mode not in ("ask", "inspect"):
        raise ValueError("agent invocation mode must be 'ask' or 'inspect'")
    if mode == "ask" and not question:
        raise ValueError("agent invocation requires a question")
    if len(question) > 1500:
        raise ValueError("agent invocation question must be at most 1500 characters")
    cur = conn.execute(
        "INSERT INTO agent_invocations (role, mode, question) VALUES (?, ?, ?)",
        (role, mode, question),
    )
    conn.commit()
    return get_agent_invocation(conn, cur.lastrowid)


def create_agent_room(conn, roles: list[str] | tuple[str, ...], question: str) -> dict:
    """Atomically create one room parent and two or three ordered child jobs."""
    if not isinstance(roles, (list, tuple)) or not 2 <= len(roles) <= 3:
        raise ValueError("agent room requires 2-3 roles")
    clean_roles: list[str] = []
    for role in roles:
        if not isinstance(role, str) or not _ROOM_ROLE_RE.fullmatch(role):
            raise ValueError("agent room roles must be canonical role ids")
        if role == "chief":
            raise ValueError("chief is the room synthesizer, not a child role")
        if role in clean_roles:
            raise ValueError("agent room roles must be unique")
        clean_roles.append(role)
    safe_question = _bounded_invocation_text(question, 1501)
    if not safe_question:
        raise ValueError("agent room requires a question")
    if len(safe_question) > 1500:
        raise ValueError("agent room question must be at most 1500 characters")
    if conn.in_transaction:
        raise sqlite3.OperationalError("agent room creation requires a clean transaction")

    conn.execute("BEGIN IMMEDIATE")
    try:
        parent_cursor = conn.execute(
            """INSERT INTO agent_invocations
               (role, mode, question, invocation_kind, sequence_index)
               VALUES ('chief', 'ask', ?, 'room', 0)""",
            (safe_question,),
        )
        parent_id = int(parent_cursor.lastrowid)
        conn.executemany(
            """INSERT INTO agent_invocations
               (role, mode, question, invocation_kind, parent_id, sequence_index)
               VALUES (?, 'ask', ?, 'room_child', ?, ?)""",
            [
                (role, safe_question, parent_id, index)
                for index, role in enumerate(clean_roles, start=1)
            ],
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    return get_agent_invocation(conn, parent_id)


def get_agent_invocation(conn, invocation_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM agent_invocations WHERE id = ?", (int(invocation_id),)
    ).fetchone()
    return _agent_invocation_dict(row)


def get_agent_room_children(conn, parent_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM agent_invocations
           WHERE parent_id=? AND invocation_kind='room_child'
           ORDER BY sequence_index ASC, id ASC""",
        (int(parent_id),),
    ).fetchall()
    return [_agent_invocation_dict(row) for row in rows]


def claim_agent_invocation(conn, invocation_id: int) -> dict | None:
    """Atomically claim a QUEUED invocation; an existing claim wins."""
    cur = conn.execute(
        """UPDATE agent_invocations
           SET status='RUNNING', started_at=datetime('now', 'localtime')
           WHERE id=? AND status='QUEUED'""",
        (int(invocation_id),),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return get_agent_invocation(conn, invocation_id)


def finish_agent_invocation_success(conn, invocation_id: int, answer: str,
                                    evidence: object, model: str,
                                    turns: int | None,
                                    cost_usd: float | None) -> dict | None:
    """Finish a claimed invocation once; terminal rows are immutable."""
    safe_answer = _bounded_invocation_text(answer, 8000)
    safe_evidence = _normalize_invocation_evidence(evidence)
    safe_model = _bounded_invocation_text(model, 100)
    safe_turns = max(0, int(turns)) if turns is not None else None
    safe_cost = max(0.0, float(cost_usd)) if cost_usd is not None else None
    cur = conn.execute(
        """UPDATE agent_invocations
           SET status='SUCCEEDED', answer=?, evidence_json=?, model=?, turns=?,
               cost_usd=?, error_code='', error_message='',
               finished_at=datetime('now', 'localtime')
           WHERE id=? AND status='RUNNING'""",
        (safe_answer, json.dumps(safe_evidence, separators=(",", ":")), safe_model,
         safe_turns, safe_cost, int(invocation_id)),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return get_agent_invocation(conn, invocation_id)


def finish_agent_invocation_failure(conn, invocation_id: int, error_code: str,
                                    error_message: str) -> dict | None:
    """Fail a live invocation without persisting exception or SDK details."""
    code = _bounded_invocation_text(error_code, 64) or "runner_error"
    message = _bounded_invocation_text(error_message, 500) or "The consultation failed. Please try again."
    cur = conn.execute(
        """UPDATE agent_invocations
           SET status='FAILED', answer='', evidence_json='[]', error_code=?,
               error_message=?, finished_at=datetime('now', 'localtime')
           WHERE id=? AND status IN ('QUEUED','RUNNING')""",
        (code, message, int(invocation_id)),
    )
    conn.commit()
    if cur.rowcount != 1:
        return None
    return get_agent_invocation(conn, invocation_id)


def fail_stale_agent_invocations(conn, age_minutes: int = 10) -> int:
    """Truthfully terminate work that cannot survive a process restart."""
    age = max(0, int(age_minutes))
    cur = conn.execute(
        """UPDATE agent_invocations
           SET status='FAILED', answer='', evidence_json='[]',
               error_code='interrupted',
               error_message='The consultation was interrupted. Please try again.',
               finished_at=datetime('now', 'localtime')
           WHERE status IN ('QUEUED','RUNNING')
             AND COALESCE(started_at, created_at)
                 < datetime('now', 'localtime', ?)""",
        (f"-{age} minutes",),
    )
    conn.commit()
    return int(cur.rowcount)


def prune_agent_invocations(
    conn, older_than_days: int = 7, *, chat_days: int | None = None,
) -> int:
    """Delete old terminal singles/parents; room and chat children cascade.

    Then drop chat_threads with zero remaining turns whose updated_at is
    older than the same window. Never touches memos, facts, proposals, or
    journal.
    """
    age = max(0, int(older_than_days))
    # SPEC-v26: chat keeps a longer memory than a one-shot consult. Callers
    # still pass the Ask/inspect window; the chat window is applied here so
    # there is one place it lives.
    chat_age = max(age, int(chat_days if chat_days is not None else CHAT_RETENTION_DAYS))
    cur = conn.execute(
        """DELETE FROM agent_invocations
           WHERE status IN ('SUCCEEDED','FAILED')
             AND invocation_kind NOT IN ('room_child', 'chat_child')
             AND (
                 (invocation_kind = 'chat_turn'
                  AND COALESCE(finished_at, created_at)
                      < datetime('now', 'localtime', ?))
                 OR
                 (invocation_kind <> 'chat_turn'
                  AND COALESCE(finished_at, created_at)
                      < datetime('now', 'localtime', ?))
             )""",
        (f"-{chat_age} days", f"-{age} days"),
    )
    deleted = int(cur.rowcount)
    # SPEC-v40 §3.4: a compacted thread whose turns aged out keeps its
    # summary; that summary is the thread's memory and the whole point.
    conn.execute(
        """DELETE FROM chat_threads
           WHERE updated_at < datetime('now', 'localtime', ?)
             AND summary = ''
             AND NOT EXISTS (
                 SELECT 1 FROM agent_invocations
                 WHERE agent_invocations.thread_id = chat_threads.id
             )""",
        (f"-{chat_age} days",),
    )
    conn.commit()
    return deleted


def _parse_granted_chips(raw: object) -> list[str]:
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
    if not isinstance(values, list):
        return []
    seen: list[str] = []
    for value in values:
        if not isinstance(value, str) or value not in CHAT_CHIP_IDS:
            continue
        if value not in seen:
            seen.append(value)
        if len(seen) >= 8:
            break
    return [chip_id for chip_id in CHAT_CHIP_IDS if chip_id in seen]


def canonical_granted_chips(ids: object) -> str:
    """Sorted unique registry ids as canonical JSON. Unknown ids raise."""
    if ids is None:
        return "[]"
    if not isinstance(ids, (list, tuple)):
        raise ValueError("granted_chips must be a list")
    seen: list[str] = []
    for value in ids:
        if not isinstance(value, str):
            raise ValueError("granted_chips ids must be text")
        chip_id = value.strip()
        if not chip_id:
            raise ValueError("granted_chips ids must not be blank")
        if len(chip_id) > 16:
            raise ValueError("granted_chips id is too long")
        if chip_id not in CHAT_CHIP_IDS:
            raise ValueError(f"unknown chat chip: {chip_id}")
        if chip_id not in seen:
            seen.append(chip_id)
        if len(seen) > 8:
            raise ValueError("granted_chips accepts at most 8 ids")
    ordered = [chip_id for chip_id in CHAT_CHIP_IDS if chip_id in seen]
    return json.dumps(ordered, separators=(",", ":"))


def _chat_thread_dict(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item["granted_chips"] = _parse_granted_chips(item.get("granted_chips"))
    item["specialist_sonnet"] = 1 if item.get("specialist_sonnet") else 0
    return item


def get_chat_prefs(conn) -> dict:
    row = conn.execute("SELECT * FROM chat_prefs WHERE id=1").fetchone()
    if row is None:
        return {"id": 1, "default_model": CHAT_DEFAULT_MODEL, "default_role": CHAT_DEFAULT_ROLE}
    item = dict(row)
    model = item.get("default_model")
    if model not in CHAT_MODELS:
        item["default_model"] = CHAT_DEFAULT_MODEL
    if not (item.get("default_role") or "").strip():
        item["default_role"] = CHAT_DEFAULT_ROLE
    return item


def set_chat_prefs_model(conn, model: str) -> dict:
    if model not in CHAT_MODELS:
        raise ValueError("chat default_model must be a closed model id")
    conn.execute(
        """INSERT INTO chat_prefs (id, default_model) VALUES (1, ?)
           ON CONFLICT(id) DO UPDATE SET default_model=excluded.default_model""",
        (model,),
    )
    conn.commit()
    return get_chat_prefs(conn)


def gym_prefs(conn) -> dict:
    """Ian's own gym tracking settings (SPEC-v34): track_days_per_week (5 or
    7) and rest_days_per_week (0-6), the weekly-refill allowance that replaced
    the old 5-consecutive-confirms stool bank. Singleton row, id=1, seeded by
    the schema's own `INSERT OR IGNORE` so this reader needs no seed-on-read
    fallback (mirrors chat_prefs, which relies on the same schema-level seed)."""
    row = conn.execute("SELECT * FROM gym_prefs WHERE id=1").fetchone()
    return dict(row)


def set_gym_prefs(conn, *, track_days_per_week: int | None = None,
                   rest_days_per_week: int | None = None) -> dict:
    """Partial update, mirrors set_account_appearance's narrow-write shape:
    validate each provided value against gym_prefs' own CHECK constraints in
    Python before writing (so the API layer turns a ValueError into a 422
    instead of letting SQLite raise a bare IntegrityError), then UPDATE only
    the columns actually passed."""
    sets: list[str] = []
    params: list = []
    if track_days_per_week is not None:
        if track_days_per_week not in (5, 7):
            raise ValueError("track_days_per_week must be 5 or 7")
        sets.append("track_days_per_week=?")
        params.append(track_days_per_week)
    if rest_days_per_week is not None:
        if not (0 <= rest_days_per_week <= 6):
            raise ValueError("rest_days_per_week must be between 0 and 6")
        sets.append("rest_days_per_week=?")
        params.append(rest_days_per_week)
    if not sets:
        return gym_prefs(conn)
    sets.append("updated_at=datetime('now','localtime')")
    conn.execute(f"UPDATE gym_prefs SET {', '.join(sets)} WHERE id=1", params)
    conn.commit()
    return gym_prefs(conn)


def _parse_money_widgets(raw: object) -> list[dict]:
    """Defensive read-side parse, mirroring _parse_granted_chips: an unknown
    or malformed entry is dropped rather than trusted, never raised here."""
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return [dict(item) for item in MONEY_WIDGETS_DEFAULT]
    if not isinstance(values, list):
        return [dict(item) for item in MONEY_WIDGETS_DEFAULT]
    cleaned: list[dict] = []
    for entry in values:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if key not in MONEY_WIDGET_KEYS:
            continue
        cleaned.append({"key": key, "visible": bool(entry.get("visible", True))})
    return cleaned if cleaned else [dict(item) for item in MONEY_WIDGETS_DEFAULT]


def canonical_money_widgets(widgets: object) -> str:
    """Closed widget-key set as canonical JSON. Unknown keys raise."""
    if not isinstance(widgets, list):
        raise ValueError("money widgets_json must be a list")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for entry in widgets:
        if not isinstance(entry, dict):
            raise ValueError("money widgets_json entries must be objects")
        key = entry.get("key")
        if key not in MONEY_WIDGET_KEYS:
            raise ValueError(f"unknown money widget: {key}")
        if key in seen:
            raise ValueError(f"duplicate money widget: {key}")
        seen.add(key)
        cleaned.append({"key": key, "visible": bool(entry.get("visible", True))})
    return json.dumps(cleaned, separators=(",", ":"))


def get_money_prefs(conn) -> dict:
    row = conn.execute("SELECT * FROM money_prefs WHERE id=1").fetchone()
    if row is None:
        return {
            "id": 1,
            "hero_metric": MONEY_HERO_DEFAULT,
            "hero_goal_id": None,
            "widgets_json": [dict(item) for item in MONEY_WIDGETS_DEFAULT],
        }
    item = dict(row)
    if item.get("hero_metric") not in MONEY_HERO_METRICS:
        item["hero_metric"] = MONEY_HERO_DEFAULT
    item["widgets_json"] = _parse_money_widgets(item.get("widgets_json"))
    return item


def set_money_prefs(conn, **fields) -> dict:
    """Partial update of the money_prefs singleton row.

    Mirrors set_chat_prefs_model's INSERT .. ON CONFLICT DO UPDATE shape,
    widened to accept any subset of {hero_metric, hero_goal_id,
    widgets_json} since (unlike chat_prefs' single field) the Money
    customize sheet can patch these individually or together.
    """
    unknown = set(fields) - {"hero_metric", "hero_goal_id", "widgets_json"}
    if unknown:
        raise ValueError(f"unknown money_prefs field: {sorted(unknown)[0]}")
    sets: list[str] = []
    params: list = []
    if "hero_metric" in fields:
        hero_metric = fields["hero_metric"]
        if hero_metric not in MONEY_HERO_METRICS:
            raise ValueError(f"unknown hero_metric: {hero_metric}")
        sets.append("hero_metric=?")
        params.append(hero_metric)
    if "hero_goal_id" in fields:
        hero_goal_id = fields["hero_goal_id"]
        if hero_goal_id is not None and not isinstance(hero_goal_id, int):
            raise ValueError("money hero_goal_id must be an integer or null")
        sets.append("hero_goal_id=?")
        params.append(hero_goal_id)
    if "widgets_json" in fields:
        sets.append("widgets_json=?")
        params.append(canonical_money_widgets(fields["widgets_json"]))
    if not sets:
        return get_money_prefs(conn)
    sets.append("updated_at=datetime('now','localtime')")
    try:
        conn.execute(
            f"INSERT INTO money_prefs (id) VALUES (1) "
            f"ON CONFLICT(id) DO UPDATE SET {', '.join(sets)}",
            params,
        )
    except sqlite3.IntegrityError as exc:
        # hero_goal_id references goals(id); a stale or made-up id is a
        # 422-shaped caller error, not a 500.
        raise ValueError(f"invalid hero_goal_id: {fields.get('hero_goal_id')}") from exc
    conn.commit()
    return get_money_prefs(conn)


def create_chat_thread(conn, model: str, role: str = "chief",
                       effort: str = CHAT_DEFAULT_EFFORT) -> dict:
    """Open a thread with one agent.

    SPEC-v26: only the previous thread for THIS role is closed, so a money
    thread with the CFO and a sleep thread with the physician can both stay
    open. Role validity is checked at the API boundary against the canonical
    active roster; this layer only refuses an empty id.
    """
    if model not in CHAT_MODELS:
        raise ValueError("chat thread model must be a closed model id")
    if effort not in CHAT_EFFORTS:
        raise ValueError("chat thread effort must be a closed effort level")
    role = str(role or "chief").strip() or "chief"
    # SPEC-v40 §3.1: threads are durable. Creating one no longer closes the
    # role's other OPEN threads (SPEC-v26's one-open-thread-per-role law is
    # repealed); the "current" thread for a role is simply the most recently
    # updated OPEN one, and older ones stay listed and resumable.
    # SPEC-v37 §2.7: Files is the one capability chip granted by default; the
    # column's own DEFAULT clause is fixed at table-creation time and cannot
    # retroactively change for a database whose chat_threads already exists,
    # so every new row states it explicitly instead of relying on that.
    # A role whose whole beat lives behind one source chip gets that chip on
    # by default too: a Dumbledore thread that opens with School off is an
    # academic copilot that cannot see the syllabus, which is how "the school
    # helper can't read my notes" shipped. Ian can still turn it off.
    chips = ["files", *CHAT_DEFAULT_CHIPS_BY_ROLE.get(role, ())]
    cur = conn.execute(
        "INSERT INTO chat_threads (model, role, effort, granted_chips) VALUES (?,?,?,?)",
        (model, role, effort, canonical_granted_chips(chips)),
    )
    conn.commit()
    return get_chat_thread(conn, cur.lastrowid)


def chat_turns_since_summary(conn, thread_id: int) -> list[dict]:
    """Succeeded turns not yet covered by the thread's summary, oldest first.

    `summary_turn_count` is the thread's total turn count at compact time, so
    everything after that offset (in id order) is new. After a prune the
    offset can under-skip and a few covered turns get summarized twice;
    Compact is cumulative (it feeds the previous summary back in), so that is
    harmless, whereas over-skipping would silently drop conversation.
    """
    thread = get_chat_thread(conn, thread_id)
    if thread is None:
        return []
    offset = max(0, int(thread.get("summary_turn_count") or 0))
    rows = conn.execute(
        """SELECT id, question, answer, status FROM agent_invocations
           WHERE thread_id=? AND invocation_kind='chat_turn'
           ORDER BY id ASC LIMIT -1 OFFSET ?""",
        (int(thread_id), offset),
    ).fetchall()
    out = []
    for row in rows:
        if row["status"] != "SUCCEEDED":
            continue
        body = ""
        try:
            parsed = json.loads(row["answer"] or "")
            if isinstance(parsed, dict):
                body = str(parsed.get("body") or "").strip()
                verdict = str(parsed.get("verdict") or "").strip()
                if verdict and verdict != "-":
                    body = f"{body}\n[verdict] {verdict}".strip()
        except (TypeError, ValueError):
            body = ""
        out.append({"id": int(row["id"]), "question": row["question"] or "", "body": body})
    return out


def set_chat_thread_summary(conn, thread_id: int, summary: str) -> dict | None:
    """Store Compact's output and start the thread's memory over (§4.2).

    Bounded to CHAT_SUMMARY_CHARS. summary_turn_count becomes the current
    total so chat_turns_since_summary starts after this point, and
    sdk_session_id is cleared so the NEXT turn opens a fresh native session
    whose only history is this summary. Turn rows are never touched.
    """
    clean = " ".join(str(summary or "").split())[:CHAT_SUMMARY_CHARS].strip()
    if not clean:
        raise ValueError("a compact summary cannot be empty")
    conn.execute(
        """UPDATE chat_threads
           SET summary=?, summary_turn_count=?, compacted_at=datetime('now', 'localtime'),
               sdk_session_id='', updated_at=datetime('now', 'localtime')
           WHERE id=?""",
        (clean, chat_turn_count(conn, thread_id), int(thread_id)),
    )
    conn.commit()
    return get_chat_thread(conn, thread_id)


def chat_thread_summaries_for_role(conn, role: str, *, exclude_id: int | None = None,
                                   limit: int = CHAT_CROSS_THREAD_SUMMARIES) -> list[dict]:
    """Earlier compacted threads for ONE role, newest compact first (§4.4).

    Same role only, by construction of the WHERE clause: a Dumbledore thread
    never receives a Jordan Belfort summary. Title, date, summary; no ids
    the model could cite as evidence.
    """
    rows = conn.execute(
        """SELECT title, compacted_at, summary FROM chat_threads
           WHERE role=? AND summary <> '' AND id <> ?
           ORDER BY compacted_at DESC, id DESC LIMIT ?""",
        (str(role), int(exclude_id or 0), max(0, int(limit))),
    ).fetchall()
    return [
        {
            "title": row["title"] or "(untitled)",
            "date": (row["compacted_at"] or "")[:10],
            "summary": row["summary"],
        }
        for row in rows
    ]


def set_chat_thread_session(conn, thread_id: int, session_id: str) -> None:
    """Persist the SDK's session id after a turn completes (§7.4).

    The only writer of this column. Bounded and type-checked defensively:
    this value rides straight back into ClaudeAgentOptions(resume=...) on the
    next turn, so a malformed value must never reach the row.
    """
    clean = str(session_id or "").strip()[:200]
    if not clean:
        return
    conn.execute(
        "UPDATE chat_threads SET sdk_session_id=? WHERE id=?",
        (clean, int(thread_id)),
    )
    conn.commit()


def get_chat_thread(conn, thread_id: int, *, include_turns: bool = False) -> dict | None:
    row = conn.execute(
        "SELECT * FROM chat_threads WHERE id=?", (int(thread_id),)
    ).fetchone()
    item = _chat_thread_dict(row)
    if item is None:
        return None
    if include_turns:
        rows = conn.execute(
            """SELECT * FROM agent_invocations
               WHERE thread_id=? AND invocation_kind='chat_turn'
               ORDER BY id ASC""",
            (int(thread_id),),
        ).fetchall()
        item["turns"] = [_agent_invocation_dict(turn) for turn in rows]
    return item


def list_chat_threads(conn, limit: int = 50) -> list[dict]:
    """Summaries only: no bodies, no questions, no summary text.

    SPEC-v40 §3.3: newest activity first regardless of status, so the
    Threads sheet reads as a history; each row carries turn_count and
    has_summary so the UI can label a compacted thread without fetching it.
    """
    rows = conn.execute(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM agent_invocations i
                    WHERE i.thread_id=t.id AND i.invocation_kind='chat_turn') AS turn_count
             FROM chat_threads t
            ORDER BY t.updated_at DESC, t.id DESC
            LIMIT ?""",
        (max(1, min(int(limit), 50)),),
    ).fetchall()
    out = []
    for row in rows:
        item = _chat_thread_dict(row)
        item["turn_count"] = int(item.get("turn_count") or 0)
        item["has_summary"] = bool(item.get("summary"))
        last = conn.execute(
            """SELECT answer FROM agent_invocations
               WHERE thread_id=? AND invocation_kind='chat_turn'
                 AND status='SUCCEEDED'
               ORDER BY id DESC LIMIT 1""",
            (item["id"],),
        ).fetchone()
        verdict = "-"
        if last:
            try:
                parsed = json.loads(last["answer"] or "")
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                text = str(parsed.get("verdict") or "").strip()
                if text:
                    verdict = text[:160]
        item["last_verdict"] = verdict
        out.append(item)
    return out


def patch_chat_thread(conn, thread_id: int, *, model: str | None = None,
                      granted_chips: object | None = None,
                      specialist_sonnet: int | None = None,
                      status: str | None = None,
                      effort: str | None = None) -> dict | None:
    current = get_chat_thread(conn, thread_id)
    if current is None:
        return None
    # SPEC-v40 §3.1: a CLOSED thread accepts exactly one patch, reopening
    # (status=OPEN, alone). Its settings stay frozen until it is live again,
    # so an archive is never silently edited from a stale tab.
    if current["status"] == "CLOSED" and status != "CLOSED":
        only_reopen = status == "OPEN" and all(
            v is None for v in (model, granted_chips, specialist_sonnet, effort)
        )
        if not only_reopen:
            raise ValueError("closed chat thread cannot be patched; reopen it first")
    updates: list[str] = []
    params: list = []
    if effort is not None:
        if effort not in CHAT_EFFORTS:
            raise ValueError("chat effort must be a closed effort level")
        updates.append("effort=?")
        params.append(effort)
    if model is not None:
        if model not in CHAT_MODELS:
            raise ValueError("chat thread model must be a closed model id")
        updates.append("model=?")
        params.append(model)
    if granted_chips is not None:
        updates.append("granted_chips=?")
        params.append(canonical_granted_chips(granted_chips))
    if specialist_sonnet is not None:
        flag = int(specialist_sonnet)
        if flag not in (0, 1):
            raise ValueError("specialist_sonnet must be 0 or 1")
        updates.append("specialist_sonnet=?")
        params.append(flag)
    if status is not None:
        if status not in CHAT_THREAD_STATUSES:
            raise ValueError("chat thread status must be OPEN or CLOSED")
        updates.append("status=?")
        params.append(status)
    if not updates:
        return current
    updates.append("updated_at=datetime('now', 'localtime')")
    params.append(int(thread_id))
    conn.execute(
        f"UPDATE chat_threads SET {', '.join(updates)} WHERE id=?",
        params,
    )
    conn.commit()
    return get_chat_thread(conn, thread_id)


def chat_turn_in_flight(conn, thread_id: int) -> bool:
    """True while a turn on this thread is still QUEUED or RUNNING.

    SPEC-v26 replaced the chat cooldowns with this: the reason to refuse a
    send is that the thread is mid-answer, not that a timer has not expired.
    """
    row = conn.execute(
        """SELECT 1 FROM agent_invocations
           WHERE thread_id=? AND invocation_kind='chat_turn'
             AND status IN ('QUEUED','RUNNING') LIMIT 1""",
        (int(thread_id),),
    ).fetchone()
    return row is not None


def chat_turn_count(conn, thread_id: int) -> int:
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM agent_invocations
           WHERE thread_id=? AND invocation_kind='chat_turn'""",
        (int(thread_id),),
    ).fetchone()
    return int(row["n"] if row else 0)


def create_chat_turn(conn, thread_id: int, question: str, *, model: str) -> dict:
    thread = get_chat_thread(conn, thread_id)
    if thread is None:
        raise ValueError("chat thread not found")
    if thread["status"] != "OPEN":
        raise ValueError("chat thread is closed")
    if model not in CHAT_MODELS:
        raise ValueError("chat turn model must be a closed model id")
    if chat_turn_count(conn, thread_id) >= CHAT_TURNS_PER_THREAD:
        raise ValueError("chat thread turn limit reached")
    safe_question = _bounded_invocation_text(question, 1501)
    if not safe_question:
        raise ValueError("chat turn requires a question")
    if len(safe_question) > 1500:
        raise ValueError("chat turn question must be at most 1500 characters")
    cur = conn.execute(
        """INSERT INTO agent_invocations
           (role, mode, question, invocation_kind, thread_id, model)
           VALUES ('chief', 'chat', ?, 'chat_turn', ?, ?)""",
        (safe_question, int(thread_id), model),
    )
    # SPEC-v40 §3.2: the title is the first question, server-set once, never
    # model-written. It is what the Threads list shows.
    conn.execute(
        """UPDATE chat_threads
           SET updated_at=datetime('now', 'localtime'),
               title=CASE WHEN title='' THEN ? ELSE title END
           WHERE id=?""",
        (chat_thread_title(safe_question), int(thread_id)),
    )
    conn.commit()
    return get_agent_invocation(conn, cur.lastrowid)


CHAT_THREAD_TITLE_CHARS = 60


def chat_thread_title(question: str) -> str:
    """First line of the first question, whitespace-collapsed, 60 chars."""
    text = " ".join(str(question or "").split())
    if len(text) <= CHAT_THREAD_TITLE_CHARS:
        return text
    cut = text[:CHAT_THREAD_TITLE_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:")
    return (cut or text[:CHAT_THREAD_TITLE_CHARS]) + "…"


def create_chat_children(conn, parent_id: int, roles: list[str] | tuple[str, ...]) -> list[dict]:
    """Create 2-3 ordered specialist children on a chat_turn parent."""
    if not isinstance(roles, (list, tuple)) or not 2 <= len(roles) <= 3:
        raise ValueError("chat specialists require 2-3 roles")
    parent = get_agent_invocation(conn, parent_id)
    if parent is None or parent.get("invocation_kind") != "chat_turn":
        raise ValueError("chat children require a chat_turn parent")
    thread_id = parent.get("thread_id")
    if thread_id is None:
        raise ValueError("chat turn is missing a thread")
    clean_roles: list[str] = []
    for role in roles:
        if not isinstance(role, str) or not _ROOM_ROLE_RE.fullmatch(role):
            raise ValueError("chat specialist roles must be canonical role ids")
        if role == "chief":
            raise ValueError("chief synthesizes the chat turn, not a child role")
        if role in clean_roles:
            raise ValueError("chat specialist roles must be unique")
        clean_roles.append(role)
    question = parent.get("question") or ""
    conn.executemany(
        """INSERT INTO agent_invocations
           (role, mode, question, invocation_kind, parent_id, sequence_index, thread_id)
           VALUES (?, 'chat', ?, 'chat_child', ?, ?, ?)""",
        [
            (role, question, int(parent_id), index, int(thread_id))
            for index, role in enumerate(clean_roles, start=1)
        ],
    )
    conn.commit()
    return get_chat_children(conn, parent_id)


def get_chat_children(conn, parent_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM agent_invocations
           WHERE parent_id=? AND invocation_kind='chat_child'
           ORDER BY sequence_index ASC, id ASC""",
        (int(parent_id),),
    ).fetchall()
    return [_agent_invocation_dict(row) for row in rows]


def claim_chat_turn_model(conn, invocation_id: int, model: str) -> dict | None:
    """Stamp the thread model onto a claimed turn so a later PATCH cannot race."""
    if model not in CHAT_MODELS:
        return get_agent_invocation(conn, invocation_id)
    conn.execute(
        """UPDATE agent_invocations SET model=?
           WHERE id=? AND status='RUNNING' AND invocation_kind='chat_turn'""",
        (model, int(invocation_id)),
    )
    conn.commit()
    return get_agent_invocation(conn, invocation_id)


def recent_succeeded_chat_turns(conn, thread_id: int, limit: int | None = None) -> list[dict]:
    window = CHAT_PRIOR_TURN_WINDOW if limit is None else limit
    rows = conn.execute(
        """SELECT * FROM agent_invocations
           WHERE thread_id=? AND invocation_kind='chat_turn' AND status='SUCCEEDED'
           ORDER BY id DESC LIMIT ?""",
        (int(thread_id), max(0, int(window))),
    ).fetchall()
    return [_agent_invocation_dict(row) for row in reversed(rows)]


def chat_chip_connected(conn, chip_id: str) -> bool:
    """Whether a loader has something to read. Does not imply grant."""
    if chip_id == "money":
        plaid_row = conn.execute(
            "SELECT 1 FROM plaid_items WHERE item_key IN ('chase','capital_one') LIMIT 1"
        ).fetchone()
        if plaid_row:
            return True
        accounts = conn.execute("SELECT 1 FROM financial_accounts LIMIT 1").fetchone()
        if accounts:
            return True
        success = conn.execute(
            """SELECT 1 FROM ingest_log
               WHERE last_success IS NOT NULL AND last_success != ''
                 AND source IN (
                     'simplefin_chase','snaptrade_fidelity',
                     'plaid_chase','plaid_capital_one'
                 )
               LIMIT 1"""
        ).fetchone()
        return bool(success)
    if chip_id == "mail":
        status = ingest_status(conn, "gmail")
        if status and status.get("last_success"):
            return True
        note = conn.execute(
            """SELECT 1 FROM memos
               WHERE from_role='ian' AND topic LIKE 'email:%' LIMIT 1"""
        ).fetchone()
        return bool(note)
    if chip_id == "calendar":
        status = ingest_status(conn, "calendar")
        if status and status.get("last_success"):
            return True
        event = conn.execute("SELECT 1 FROM calendar_events LIMIT 1").fetchone()
        return bool(event)
    if chip_id == "school":
        # The School schema is lazily created by the local importer/API
        # projection. Chat may load first, so a missing table means exactly
        # "not connected", not a database error.
        if not _table_exists(conn, "school_items"):
            return False
        item = conn.execute(
            "SELECT 1 FROM school_items WHERE archived_at IS NULL LIMIT 1"
        ).fetchone()
        return bool(item)
    if chip_id == "documents":
        doc = conn.execute("SELECT 1 FROM documents LIMIT 1").fetchone()
        return bool(doc)
    if chip_id == "web":
        # An external tool, not a local sync: nothing to be "connected" to.
        return True
    if chip_id in ("files", "workspace", "shell"):
        # SPEC-v37 §2.7: local Claude Code capabilities, always available,
        # gated by agents/consult_gate.py rather than by a sync connection.
        return True
    return False


def synced_mail_notes(conn, limit: int = 40) -> list[dict]:
    """Connector-shaped mail notes only. Nightly blackboard rows never match."""
    rows = conn.execute(
        """SELECT id, from_role, topic, body, created_at FROM memos
           WHERE from_role='ian' AND topic LIKE 'email:%' AND archived=0
           ORDER BY created_at DESC, id DESC LIMIT ?""",
        (max(1, min(int(limit), 80)),),
    ).fetchall()
    return rows_to_dicts(rows)


def synced_mail_facts(conn, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        """SELECT id, domain, topic, body, kind, date, verified, source_role
           FROM facts WHERE source_role='connector-gmail'
           ORDER BY updated_at DESC, id DESC LIMIT ?""",
        (max(1, min(int(limit), 80)),),
    ).fetchall()
    return rows_to_dicts(rows)


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- memos

def add_memo(conn, from_role: str, topic: str, body: str, priority: int = 1,
             commit: bool = True) -> int:
    priority = max(0, min(3, int(priority)))
    cur = conn.execute(
        "INSERT INTO memos (from_role, topic, body, priority) VALUES (?, ?, ?, ?)",
        (from_role, topic, body, priority),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def recent_memos(conn, days: int = 7, limit: int = 60,
                 include_archived: bool = False) -> list[dict]:
    """Recent blackboard memos. Archived rows are evidence, not live context."""
    archive_clause = "" if include_archived else "AND archived = 0"
    rows = conn.execute(
        f"""SELECT * FROM memos
           WHERE created_at >= datetime('now', 'localtime', ?)
             {archive_clause}
           ORDER BY created_at DESC, id DESC LIMIT ?""",
        (f"-{int(days)} days", int(limit)),
    ).fetchall()
    return rows_to_dicts(rows)


def recent_shared_memos(conn, days: int = 7, limit: int = 60) -> list[dict]:
    """Active blackboard rows safe for broad state and remote agent context.

    ``recent_memos`` remains the low-level local maintenance reader. This
    projection deliberately omits historic health-agent output, which may
    contain health-derived values from before private health insights existed.
    """
    rows = recent_memos(conn, days=days, limit=limit)
    return [row for row in rows if row.get("from_role") not in PRIVATE_HEALTH_MEMO_ROLES]


def memo_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM memos WHERE archived = 0").fetchone()[0]


def latest_montage(conn) -> dict | None:
    """Rocky's most recent Sunday training-montage memo (topic 'montage: ...')."""
    row = conn.execute(
        "SELECT * FROM memos WHERE from_role='coach' AND topic LIKE 'montage:%' "
        "ORDER BY created_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["title"] = d["topic"].split("montage:", 1)[1].strip() or "This week"
    return d


def compact_memos(conn, before_days: int = 30) -> dict:
    """Archivist: atomically summarize and archive old active memos.

    Original rows are never deleted: facts can continue to cite their exact
    source body and `archived_into_id` leads back to the compacted summary.
    """
    outer_transaction = conn.in_transaction
    savepoint = "compact_memos"
    try:
        if outer_transaction:
            conn.execute(f"SAVEPOINT {savepoint}")
        else:
            conn.execute("BEGIN IMMEDIATE")
        rows = rows_to_dicts(conn.execute(
            """SELECT * FROM memos
               WHERE created_at < datetime('now', 'localtime', ?)
                 AND from_role != 'archivist'
                 AND archived = 0
               ORDER BY created_at, id""",
            (f"-{int(before_days)} days",),
        ).fetchall())
        if not rows:
            if outer_transaction:
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            else:
                conn.commit()
            return {"compacted": 0, "summaries_written": 0}

        groups: dict[str, list[dict]] = {}
        for memo in rows:
            prefix = memo["topic"].split(":")[0].strip() or "general"
            groups.setdefault(prefix, []).append(memo)

        summaries = 0
        for prefix, memos in groups.items():
            lines = [
                f"- [{memo['from_role']}] {memo['topic']}: {memo['body'][:120]}"
                for memo in memos[:8]
            ]
            body = f"Compacted {len(memos)} memos tagged '{prefix}':\n" + "\n".join(lines)
            summary_id = add_memo(conn, "archivist", f"compacted: {prefix}", body,
                                  commit=False)
            conn.executemany(
                """UPDATE memos
                   SET archived=1, archived_at=datetime('now', 'localtime'),
                       archived_into_id=?
                   WHERE id=? AND archived=0""",
                [(summary_id, memo["id"]) for memo in memos],
            )
            summaries += 1

        if outer_transaction:
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        else:
            conn.commit()
        return {"compacted": len(rows), "summaries_written": summaries}
    except Exception:
        if outer_transaction:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        elif conn.in_transaction:
            conn.rollback()
        raise


# ------------------------------------------------------------ proposals

DRAFT_ATTACHMENT_TYPES = frozenset({
    "email_draft", "message_draft", "document_outline",
})
PROPOSAL_URGENCIES = frozenset({"normal", "time_sensitive"})
PROPOSAL_REVERSIBILITIES = frozenset({"reversible", "hard_to_reverse"})
PROPOSAL_HARD_DEFAULT_KINDS = frozenset({"money", "legal", "health"})
_EVIDENCE_SOURCE_RE = re.compile(r"^(goal|fact|document|memo):([1-9][0-9]*)$")
_HTML_TAG_RE = re.compile(r"<[A-Za-z/!][^>]*>")
_ATTACHMENT_FIELDS = {
    "email_draft": {
        "to_label": (1, 120, True),
        "subject": (1, 200, True),
        "body": (1, 8000, False),
    },
    "message_draft": {
        "to_label": (1, 120, True),
        "body": (1, 4000, False),
    },
    "document_outline": {
        "title": (1, 200, True),
        "body": (1, 8000, False),
    },
}


def _proposal_text(value: object, field: str, minimum: int, maximum: int,
                   single_line: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be plain text")
    text = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if re.search(r"[\x00-\x08\x0b-\x1f\x7f]", text):
        raise ValueError(f"{field} contains control characters")
    if single_line and ("\n" in text or "\t" in text):
        raise ValueError(f"{field} must be one line")
    if len(text) < minimum or len(text) > maximum:
        raise ValueError(f"{field} must be {minimum}-{maximum} characters")
    return text


def validate_draft_attachment(attachment: object, kind: str) -> tuple[str, str, dict | None]:
    """Return type, canonical JSON, and parsed inert draft content."""
    if attachment is None:
        return "", "", None
    if kind == "money":
        raise ValueError("money proposals cannot include draft attachments")
    if not isinstance(attachment, dict):
        raise ValueError("attachment must be an object")
    attachment_type = attachment.get("type")
    if attachment_type not in DRAFT_ATTACHMENT_TYPES:
        raise ValueError("unknown draft attachment type")
    fields = _ATTACHMENT_FIELDS[attachment_type]
    expected = {"version", "type", *fields}
    if set(attachment) != expected:
        raise ValueError(f"{attachment_type} attachment has unknown or missing keys")
    version = attachment.get("version")
    if isinstance(version, bool) or version != 1:
        raise ValueError("draft attachment version must be 1")

    parsed = {"version": 1, "type": attachment_type}
    for field, (minimum, maximum, single_line) in fields.items():
        parsed[field] = _proposal_text(
            attachment[field], f"attachment.{field}", minimum, maximum, single_line,
        )
        if _HTML_TAG_RE.search(parsed[field]):
            raise ValueError(f"attachment.{field} must not contain HTML")
    to_label = parsed.get("to_label")
    if to_label and ("@" in to_label or "://" in to_label or to_label.lower().startswith("mailto:")):
        raise ValueError("attachment.to_label is display-only, not an address or URL")
    canonical = json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    )
    return attachment_type, canonical, parsed


def _canonical_local_due_at(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("metadata.due_at must be local date-time text")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise ValueError("metadata.due_at must be YYYY-MM-DDTHH:MM:SS local time") from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_proposal_label(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return " ".join(text.split())[:160]


def _resolve_evidence_source(
    conn,
    source: str,
    *,
    allowed_read_tools: set[str] | frozenset[str] | None = None,
    role_domains: list[str] | tuple[str, ...] | None = None,
) -> dict:
    match = _EVIDENCE_SOURCE_RE.fullmatch(source)
    if not match:
        raise ValueError("metadata evidence source is not allowed")
    source_type, raw_id = match.groups()
    record_id = int(raw_id)
    required_tool = {
        "goal": "read_goals", "fact": "read_facts", "document": "read_documents",
        # write_fact's own evidence requirement (SPEC-v37 §5.2): a fact
        # usually originates in something Ian said in a memo, which the goal/
        # fact/document set has no room for. read_memos is the read every
        # active role already has, so this never blocks a legitimate write.
        "memo": "read_memos",
    }[source_type]
    if allowed_read_tools is not None and required_tool not in allowed_read_tools:
        raise ValueError(f"role cannot cite {source_type} evidence")

    if source_type == "goal":
        row = conn.execute(
            "SELECT name FROM goals WHERE id=? AND COALESCE(archived, 0)=0", (record_id,)
        ).fetchone()
        label = row["name"] if row else None
    elif source_type == "fact":
        row = conn.execute(
            "SELECT topic, domain FROM facts WHERE id=? AND verified=1", (record_id,)
        ).fetchone()
        domains = set(role_domains or [])
        if row and allowed_read_tools is not None and domains and "all" not in domains:
            if row["domain"] not in domains:
                raise ValueError("role cannot cite facts outside its domains")
        label = row["topic"] if row else None
    elif source_type == "memo":
        row = conn.execute(
            "SELECT topic FROM memos WHERE id=? AND archived=0", (record_id,)
        ).fetchone()
        label = row["topic"] if row else None
    else:
        row = conn.execute("SELECT name FROM documents WHERE id=?", (record_id,)).fetchone()
        label = row["name"] if row else None
    if not row:
        raise ValueError(f"metadata evidence source does not exist: {source}")
    return {"source": source, "label": _safe_proposal_label(label)}


def _resolve_evidence_list(
    conn,
    evidence: object,
    *,
    allowed_read_tools: set[str] | frozenset[str] | None,
    role_domains: list[str] | tuple[str, ...] | None,
    label: str = "evidence",
) -> list[dict]:
    """Parse + server-side resolve a `[{"source": "fact:12"}, ...]` list
    against real rows (shared by proposal metadata.evidence and write_fact's
    own evidence requirement, SPEC-v37 §5.2). Deduped and sorted by source so
    the result is deterministic regardless of call order."""
    if not isinstance(evidence, list) or len(evidence) > 12:
        raise ValueError(f"{label} must be a list of at most 12 sources")
    resolved: dict[str, dict] = {}
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"source"}:
            raise ValueError(f"{label} accepts only a source; labels are server-owned")
        source = item.get("source")
        if not isinstance(source, str):
            raise ValueError(f"{label} source must be text")
        resolved[source] = _resolve_evidence_source(
            conn, source, allowed_read_tools=allowed_read_tools, role_domains=role_domains,
        )
    ordered_sources = sorted(resolved)
    return [resolved[source] for source in ordered_sources]


def _validate_proposal_metadata(
    conn,
    kind: str,
    metadata: object,
    *,
    allowed_read_tools: set[str] | frozenset[str] | None,
    role_domains: list[str] | tuple[str, ...] | None,
) -> tuple[str, str | None, str, str, list[dict]]:
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    allowed_keys = {"urgency", "due_at", "reversibility", "evidence"}
    if not set(metadata) <= allowed_keys:
        raise ValueError("metadata has unknown keys")
    urgency = metadata.get("urgency", "normal")
    if urgency not in PROPOSAL_URGENCIES:
        raise ValueError("metadata.urgency is invalid")
    due_at = _canonical_local_due_at(metadata.get("due_at"))
    default_reversibility = (
        "hard_to_reverse" if kind in PROPOSAL_HARD_DEFAULT_KINDS else "reversible"
    )
    reversibility = metadata.get("reversibility", default_reversibility)
    if reversibility not in PROPOSAL_REVERSIBILITIES:
        raise ValueError("metadata.reversibility is invalid")
    if kind in PROPOSAL_HARD_DEFAULT_KINDS and reversibility != "hard_to_reverse":
        raise ValueError(f"{kind} proposals must be hard_to_reverse")
    evidence = metadata.get("evidence", [])
    if evidence and allowed_read_tools is None:
        raise ValueError("metadata evidence requires the role permission context")
    resolved_evidence = _resolve_evidence_list(
        conn, evidence, allowed_read_tools=allowed_read_tools, role_domains=role_domains,
        label="metadata.evidence",
    )
    if urgency == "time_sensitive" and (due_at is None or not resolved_evidence):
        raise ValueError("time_sensitive proposals require due_at and verified evidence")
    evidence_json = json.dumps(
        [{"source": e["source"]} for e in resolved_evidence],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return urgency, due_at, reversibility, evidence_json, resolved_evidence


def validate_proposal(
    conn,
    role: str,
    action: str,
    reasoning: str,
    kind: str,
    *,
    attachment: object = None,
    metadata: object = None,
    allowed_read_tools: set[str] | frozenset[str] | None = None,
    role_domains: list[str] | tuple[str, ...] | None = None,
) -> dict:
    """Canonical validation shared by every proposal writer."""
    if kind not in PROPOSAL_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(PROPOSAL_KINDS)}")
    safe_role = _proposal_text(role, "role", 1, 64, True)
    safe_action = _proposal_text(action, "action", 1, 1000)
    safe_reasoning = _proposal_text(reasoning, "reasoning", 1, 4000)
    attachment_type, attachment_json, _ = validate_draft_attachment(attachment, kind)
    urgency, due_at, reversibility, evidence_json, _ = _validate_proposal_metadata(
        conn,
        kind,
        metadata,
        allowed_read_tools=allowed_read_tools,
        role_domains=role_domains,
    )
    return {
        "role": safe_role,
        "action": safe_action,
        "reasoning": safe_reasoning,
        "kind": kind,
        "attachment_type": attachment_type,
        "attachment_json": attachment_json,
        "urgency": urgency,
        "due_at": due_at,
        "reversibility": reversibility,
        "evidence_json": evidence_json,
    }


def _safe_attachment_from_row(row: dict) -> dict | None:
    raw = row.get("attachment_json") or ""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        attachment_type, _, parsed = validate_draft_attachment(payload, row.get("kind") or "task")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if attachment_type == row.get("attachment_type") else None


def _safe_evidence_from_row(conn, raw: object) -> list[dict]:
    try:
        payload = json.loads(raw or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list) or len(payload) > 12:
        return []
    resolved: list[dict] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"source"}:
            continue
        source = item.get("source")
        if not isinstance(source, str) or source in seen:
            continue
        try:
            evidence = _resolve_evidence_source(conn, source)
        except ValueError:
            continue
        seen.add(source)
        resolved.append(evidence)
    return resolved


def proposal_from_row(conn, row: sqlite3.Row | dict) -> dict:
    """Parse a proposal into a closed safe projection; never return raw JSON."""
    proposal = dict(row)
    attachment = _safe_attachment_from_row(proposal)
    evidence = _safe_evidence_from_row(conn, proposal.pop("evidence_json", "[]"))
    proposal.pop("attachment_json", None)
    proposal["attachment"] = attachment
    proposal["attachment_type"] = attachment["type"] if attachment else ""
    urgency = proposal.get("urgency")
    try:
        due_at = _canonical_local_due_at(proposal.get("due_at"))
    except ValueError:
        due_at = None
    if urgency not in PROPOSAL_URGENCIES:
        urgency = "normal"
    if urgency == "time_sensitive" and (due_at is None or not evidence):
        urgency = "normal"
    reversibility = proposal.get("reversibility")
    if reversibility not in PROPOSAL_REVERSIBILITIES:
        reversibility = (
            "hard_to_reverse"
            if proposal.get("kind") in PROPOSAL_HARD_DEFAULT_KINDS
            else "reversible"
        )
    proposal.update(
        urgency=urgency,
        due_at=due_at,
        reversibility=reversibility,
        evidence=evidence,
    )
    return proposal


# A model rephrases. "Confirm Illinois LLC filing status with Secretary of
# State: retrieve receipt number..." and "...by phone or online portal: (1) Is
# filing submitted..." are one action, and exact-match dedupe filed both.
#
# Scope note, measured against the real July backlog: this collapses
# REPHRASINGS, not REFORMULATIONS. "Complete Illinois LLC filing" and "Confirm
# Illinois LLC filing status" stay separate, and should -- one is do, one is
# check. Of the six real LLC rows only the true restatements merge. Bounding
# the pile is expire_stale_proposals' job; this just stops the same sentence
# arriving twice.
PROPOSAL_SIMILARITY = 0.6
PROPOSAL_HEAD_TOKENS = 12
_PROPOSAL_STOPWORDS = frozenset({
    "a", "an", "and", "the", "to", "of", "for", "with", "on", "in", "at", "by",
    "or", "if", "is", "it", "as", "from", "into", "within", "then", "that",
    "this", "your", "you", "his", "its", "any", "all", "now", "asap",
})
# The imperative lives in the opening clause; everything after the first colon,
# period, semicolon or parenthesis is elaboration that differs every night and
# would otherwise drown the shared intent (measured: 0.41 on two rows that are
# plainly the same ask, 0.70 once the tails are dropped).
_PROPOSAL_HEAD_SPLIT = re.compile(r"[:.;(\n]")


def _proposal_tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return frozenset(w for w in words if w not in _PROPOSAL_STOPWORDS)


def _proposal_head(text: str) -> str:
    clause = _PROPOSAL_HEAD_SPLIT.split(text or "", 1)[0]
    return " ".join(clause.split()[:PROPOSAL_HEAD_TOKENS])


def _proposal_verb(head: str) -> str:
    """The opening imperative, which is what the proposal actually asks for."""
    words = re.findall(r"[a-z0-9]+", (head or "").lower())
    return words[0] if words else ""


def proposal_similarity(left: str, right: str) -> float:
    """Jaccard overlap of two opening clauses. Pure, deterministic, no model.

    Two vetoes, both there because a false positive is the expensive error:
    it silently discards a proposal Ian never sees, while a false negative
    just leaves a duplicate that expire_stale_proposals will time out.

    - A differing LEADING VERB is a different action. "File IRS Form SS-4" and
      "Prepare IRS Form SS-4" overlap 0.67 on words alone; one is do, one is
      get ready. The cost of this veto is that synonyms ("Begin"/"Start" the
      same prep) no longer merge, which is the direction to err in.
    - A differing NUMBER is a different ask. "dispute $20" and "dispute $200"
      also overlap 0.67, and merging those loses real money.
    """
    head_a, head_b = _proposal_head(left), _proposal_head(right)
    a, b = _proposal_tokens(head_a), _proposal_tokens(head_b)
    if not a or not b:
        return 1.0 if a == b else 0.0
    if _proposal_verb(head_a) != _proposal_verb(head_b):
        return 0.0
    if {t for t in a if t.isdigit()} != {t for t in b if t.isdigit()}:
        return 0.0
    return len(a & b) / len(a | b)


def find_similar_pending_proposal(conn, role: str, kind: str, action: str) -> int | None:
    """The oldest PENDING near-duplicate of `action` from the same role+kind.

    Scoped to role AND kind deliberately: two agents independently reaching the
    same conclusion is signal Ian should see, and a `money` proposal never
    collapses into a `task` one. Oldest wins so the original keeps its place in
    the queue instead of the clock restarting on every rephrase.
    """
    best: tuple[float, int] | None = None
    for row in conn.execute(
        "SELECT id, action FROM proposals WHERE status='PENDING' AND role=? AND kind=? "
        "ORDER BY id ASC",
        (role, kind),
    ):
        score = proposal_similarity(action, row["action"])
        if score >= PROPOSAL_SIMILARITY and (best is None or score > best[0]):
            best = (score, int(row["id"]))
    return best[1] if best else None


def add_proposal(
    conn,
    role: str,
    action: str,
    reasoning: str,
    kind: str,
    *,
    attachment: object = None,
    metadata: object = None,
    allowed_read_tools: set[str] | frozenset[str] | None = None,
    role_domains: list[str] | tuple[str, ...] | None = None,
    return_created: bool = False,
) -> int | tuple[int, bool]:
    values = validate_proposal(
        conn,
        role,
        action,
        reasoning,
        kind,
        attachment=attachment,
        metadata=metadata,
        allowed_read_tools=allowed_read_tools,
        role_domains=role_domains,
    )
    duplicate = conn.execute(
        """SELECT id FROM proposals
           WHERE status='PENDING' AND role=? AND action=? AND reasoning=? AND kind=?
             AND attachment_type=? AND attachment_json=? AND urgency=?
             AND due_at IS ? AND reversibility=? AND evidence_json=?
           ORDER BY id ASC LIMIT 1""",
        tuple(values[key] for key in (
            "role", "action", "reasoning", "kind", "attachment_type",
            "attachment_json", "urgency", "due_at", "reversibility", "evidence_json",
        )),
    ).fetchone()
    if duplicate:
        result = (int(duplicate["id"]), False)
        return result if return_created else result[0]
    # Exact match missed, so try the near-duplicate wall. Only plain proposals
    # take this path: one carrying a draft attachment or an evidence set has
    # content beyond `action`, and collapsing it would silently discard the
    # part that differed.
    if not values["attachment_type"] and values["evidence_json"] == "[]":
        similar = find_similar_pending_proposal(
            conn, values["role"], values["kind"], values["action"],
        )
        if similar is not None:
            result = (similar, False)
            return result if return_created else result[0]
    cur = conn.execute(
        """INSERT INTO proposals
           (role, action, reasoning, kind, attachment_type, attachment_json,
            urgency, due_at, reversibility, evidence_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        tuple(values[key] for key in (
            "role", "action", "reasoning", "kind", "attachment_type",
            "attachment_json", "urgency", "due_at", "reversibility", "evidence_json",
        )),
    )
    conn.commit()
    result = (int(cur.lastrowid), True)
    return result if return_created else result[0]


def get_proposal(conn, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (int(proposal_id),)).fetchone()
    return proposal_from_row(conn, row) if row else None


def pending_proposals(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM proposals WHERE status='PENDING' ORDER BY created_at DESC, id DESC"
    ).fetchall()
    proposals = [proposal_from_row(conn, row) for row in rows]
    time_sensitive = sorted(
        (proposal for proposal in proposals if proposal["urgency"] == "time_sensitive"),
        # `proposals` already carries created_at DESC, id DESC, and Python's
        # stable sort preserves that newest-first tie-break for equal due_at.
        key=lambda proposal: proposal["due_at"],
    )
    hard = [
        proposal for proposal in proposals
        if proposal["urgency"] != "time_sensitive"
        and proposal["reversibility"] == "hard_to_reverse"
    ]
    normal = [
        proposal for proposal in proposals
        if proposal["urgency"] != "time_sensitive"
        and proposal["reversibility"] != "hard_to_reverse"
    ]
    return time_sensitive + hard + normal


def decide_proposal(conn, proposal_id: int, decision: str, note: str = "") -> dict | None:
    status = "APPROVED" if decision == "approve" else "REJECTED"
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None or row["status"] != "PENDING":
        return None
    conn.execute(
        "UPDATE proposals SET status = ?, decided_at = ? WHERE id = ?",
        (status, now(), proposal_id),
    )
    body = f"Proposal #{proposal_id} from {row['role']}: \"{row['action']}\" → {status}."
    if note:
        body += f" Ian's note: {note}"
    add_memo(conn, "ian", f"decision: proposal #{proposal_id}", body)
    conn.commit()
    return get_proposal(conn, proposal_id)


PROPOSAL_EXPIRY_DAYS = 7


def expire_stale_proposals(conn, *, days: int = PROPOSAL_EXPIRY_DAYS,
                           at: datetime | None = None) -> int:
    """Time out PENDING proposals older than `days`. THE write path for EXPIRED.

    Why this exists: proposal dedupe is exact-match, so a model that rephrases
    "confirm LLC status" files it again every night. By 2026-08-25 that had put
    29 July proposals in attention band 1, permanently ahead of anything real
    (SPEC-v32 fault 3). A pile that only grows is a pile Ian stops reading.

    Deliberately silent: no memo, no push. A timeout is not news, and a memo
    per expiry is exactly the nag this product bans. `decided_at` records WHEN
    it lapsed; the status records that nobody decided. The clock is injectable
    (named `at`, because `now` is this module's own clock function) so the
    window can be pinned at both edges in tests.
    """
    moment = at or datetime.now()
    stamp = moment.strftime("%Y-%m-%d %H:%M:%S")
    cutoff = (moment - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        """UPDATE proposals SET status = 'EXPIRED', decided_at = ?
           WHERE status = 'PENDING' AND created_at <= ?""",
        (stamp, cutoff),
    )
    conn.commit()
    return int(cur.rowcount or 0)


# --------------------------------------------------------------- briefs

def brief_governs_date(now: datetime) -> str:
    """The day a brief written at `now` is FOR (SPEC-v37 §8.2). The nightly
    run happens in the evening and produces tomorrow's Day Command, so a
    brief written before noon governs today (a manual daytime run catching
    up) and one written at/after noon governs tomorrow. Mirrors the
    morning/evening noon split `core/attention.py` already uses."""
    d = now.date()
    if now.hour >= 12:
        d += timedelta(days=1)
    return d.isoformat()


def upsert_brief(conn, brief_date: str, kind: str, body: str, day_command: str = "",
                  anchor_key: str = "", governs_date: str = "",
                  dispatch_summary: str = "") -> None:
    governs_date = governs_date or brief_date
    conn.execute(
        """INSERT INTO briefs (date, kind, body, day_command, anchor_key, governs_date,
                              dispatch_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (date, kind) DO UPDATE SET
             body = excluded.body,
             day_command = excluded.day_command,
             anchor_key = excluded.anchor_key,
             governs_date = excluded.governs_date,
             dispatch_summary = excluded.dispatch_summary,
             command_refreshes = 0,
             created_at = datetime('now', 'localtime')""",
        (brief_date, kind, body, day_command, anchor_key, governs_date, dispatch_summary),
    )
    conn.commit()


def update_day_command(conn, brief_date: str, kind: str, day_command: str, anchor_key: str) -> None:
    """The ONE write path for a live-refreshed Day Command sentence. Never a
    raw UPDATE from api/main.py: this is what keeps `body` (the nightly
    prose) untouched while the hero sentence and its anchor move."""
    conn.execute(
        """UPDATE briefs SET day_command=?, anchor_key=?,
             command_refreshes=command_refreshes+1
           WHERE date=? AND kind=?""",
        (day_command, anchor_key, brief_date, kind),
    )
    conn.commit()


def latest_brief(conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM briefs ORDER BY date DESC, CASE kind WHEN 'weekly' THEN 0 ELSE 1 END, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- goals

def all_goals(conn, include_archived: bool = False) -> list[dict]:
    """The single read path for goals: /api/state, metrics, pillars and the
    agents' read_goals all come through here, so filtering archived ones out
    once hides them everywhere, including from the nightly run."""
    where = "" if include_archived else "WHERE COALESCE(archived, 0) = 0"
    return rows_to_dicts(conn.execute(
        f"""SELECT * FROM goals
            {where}
            ORDER BY domain, priority,
                     CASE kind WHEN 'goal' THEN 0 WHEN 'quota' THEN 1 ELSE 2 END,
                     deadline"""
    ).fetchall())


def goal_lookup_all(conn) -> dict[int, dict]:
    """Every goal by id, INCLUDING archived, for parent-dependency lookups.
    all_goals() filters archived and is the single read path for the
    dashboard/metrics/pillars; this exists only so an archived parent's
    name and status are still resolvable from an active child (SPEC-v32
    law 2). Do not use this anywhere that should respect the archive
    filter -- it is a narrow exception, not a replacement for all_goals().
    """
    return {int(row['id']): dict(row) for row in conn.execute('SELECT * FROM goals')}


def clear_hero_in_domain(conn, domain: str, except_id: int | None = None) -> None:
    if except_id:
        conn.execute(
            "UPDATE goals SET hero = 0 WHERE domain = ? AND id != ?",
            (domain, except_id),
        )
    else:
        conn.execute("UPDATE goals SET hero = 0 WHERE domain = ?", (domain,))


def create_goal(conn, *, name: str, kind: str = "goal", domain: str = "business",
                 target: str = "", unit: str = "", deadline: str | None = None,
                 current_value: str = "", notes: str = "", metric_key: str = "",
                 hero: bool = False, priority: int = 0,
                 depends_on_goal_id: int | None = None, commit: bool = True) -> dict:
    """SPEC-v41 §5.4: the one INSERT INTO goals in this codebase. `metric_key`
    is deliberately not validated here -- core/db.py cannot import
    core/metrics.py (the reverse import already exists), so each caller
    (api/main.py, agents/runner.py) validates against
    metrics.METRIC_RESOLVERS before calling this."""
    name = name.strip()
    if not name:
        raise ValueError("goal needs a name")
    if kind not in ("goal", "quota", "deadline"):
        raise ValueError("kind must be goal, quota, or deadline")
    if domain not in DOMAINS:
        raise ValueError(f"domain must be one of: {', '.join(DOMAINS)}")
    if hero:
        clear_hero_in_domain(conn, domain)
    cur = conn.execute(
        """INSERT INTO goals
           (name, kind, domain, target, unit, deadline, current_value, notes,
            metric_key, hero, priority, depends_on_goal_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (name, kind, domain, target.strip(), unit.strip(), deadline or None,
         current_value.strip(), notes.strip(), metric_key, 1 if hero else 0,
         priority, depends_on_goal_id),
    )
    if commit:
        conn.commit()
    return get_goal(conn, cur.lastrowid)


# ------------------------------------------------------------- activity

def log_activity(conn, day: str, audit_calls=0, follow_ups=0, demos=0,
                 conversations=0, notes: str = "", replace: bool = False,
                 commit: bool = True) -> dict:
    conn.execute("INSERT OR IGNORE INTO activity (date) VALUES (?)", (day,))
    if replace:
        conn.execute(
            """UPDATE activity SET audit_calls=?, follow_ups=?, demos=?,
               conversations=?, notes=? WHERE date=?""",
            (audit_calls, follow_ups, demos, conversations, notes, day),
        )
    else:
        conn.execute(
            """UPDATE activity SET
                 audit_calls   = audit_calls + ?,
                 follow_ups    = follow_ups + ?,
                 demos         = demos + ?,
                 conversations = conversations + ?,
                 notes         = CASE WHEN ? = '' THEN notes
                                      WHEN notes = '' THEN ?
                                      ELSE notes || ' | ' || ? END
               WHERE date = ?""",
            (audit_calls, follow_ups, demos, conversations, notes, notes, notes, day),
        )
    if commit:
        conn.commit()
    return dict(conn.execute("SELECT * FROM activity WHERE date = ?", (day,)).fetchone())


def recent_activity(conn, days: int = 14) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM activity WHERE date >= date('now', 'localtime', ?) ORDER BY date DESC",
        (f"-{int(days)} days",),
    ).fetchall())


# ------------------------------------------------------------- health

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _weekday_walkback(d: date) -> date:
    while not _is_weekday(d):
        d -= timedelta(days=1)
    return d


def gym_confirmed_dates(conn, days: int = 90) -> set[str]:
    rows = conn.execute(
        "SELECT date FROM health_daily WHERE gym_confirmed = 1 "
        "AND date >= date('now', 'localtime', ?) ORDER BY date DESC",
        (f"-{int(days)} days",),
    ).fetchall()
    return {r[0] for r in rows}


def gym_streak_state(conn, commit: bool = True) -> dict:
    """Gym streak over Ian's configured tracked days (SPEC-v34). 5-day mode:
    Mon-Fri only, weekends don't break or count, exactly as before. 7-day
    mode: every day is trackable. Reads gym_prefs once and threads it through
    to core/streaks.py, which stays pure date/event math and never reads
    prefs itself."""
    today = date.today()
    prefs = gym_prefs(conn)
    track_days_per_week = prefs["track_days_per_week"]
    rest_days_per_week = prefs["rest_days_per_week"]
    confirmed = gym_confirmed_dates(conn)
    today_iso = today.isoformat()
    confirmed_today = today_iso in confirmed

    # 5-day mode keeps the exact Mon-Fri window (and order) it always has --
    # a pure refactor, no behavior change for the default. 7-day mode starts
    # from that week's Sunday (this app's week-start convention) so it covers
    # Sun-Sat. Both are "this calendar week", just different start days.
    if track_days_per_week == 7:
        week_start = date.fromisoformat(sunday_of(today))
    else:
        week_start = today - timedelta(days=today.weekday())
    week = []
    tracked_done = 0
    tracked_elapsed = 0
    for i in range(track_days_per_week):
        wd = week_start + timedelta(days=i)
        iso = wd.isoformat()
        done = iso in confirmed
        past_or_today = wd <= today
        week.append({"date": iso, "label": wd.strftime("%a"), "confirmed": done, "future": wd > today})
        if past_or_today:
            tracked_elapsed += 1
            if done:
                tracked_done += 1

    # Bending streak: rest days + grace come from the event log (core/streaks).
    streaks.sync_confirms(conn, commit=commit)
    bend = streaks.compute(
        conn, today,
        track_days_per_week=track_days_per_week,
        rest_days_per_week=rest_days_per_week,
    )
    graced = set(bend["graced_dates"])
    for d in week:
        d["graced"] = d["date"] in graced

    is_tracked_day = True if track_days_per_week == 7 else _is_weekday(today)
    return {
        "streak": bend["streak"],
        "stools": bend["stools"],
        "graced_dates": bend["graced_dates"],
        "confirmed_today": confirmed_today,
        "weekdays_this_week": tracked_done,
        "weekdays_elapsed": tracked_elapsed,
        "week": week,
        "is_tracked_day": is_tracked_day,
    }


def apply_gym_grace(conn) -> dict:
    """Nightly: spend a rest day for any missed tracked day (or reset if this
    week's allowance is used up). Reads gym_prefs once and threads it through;
    core/streaks.py stays pure and never reads prefs itself."""
    prefs = gym_prefs(conn)
    return streaks.apply_grace(
        conn,
        track_days_per_week=prefs["track_days_per_week"],
        rest_days_per_week=prefs["rest_days_per_week"],
    )


def recent_gym_grace(conn, within_days: int = 3) -> tuple[str, str] | None:
    return streaks.last_grace_or_reset(conn, within_days)


def confirm_gym(conn, day: str | None = None, commit: bool = True) -> dict:
    day = day or today()
    result = upsert_health(
        conn, day,
        gym_confirmed=1,
        commit=False,
    )
    # Mirror as a confirm event (a confirm supersedes any prior grace/reset).
    conn.execute(
        "INSERT INTO streak_events (date, kind) VALUES (?, 'confirm') "
        "ON CONFLICT(date) DO UPDATE SET kind='confirm'",
        (day,),
    )
    if commit:
        conn.commit()
    return result


def unconfirm_gym(conn, day: str | None = None, commit: bool = True) -> dict:
    """Reverse a `confirm_gym` for one date. Narrow on purpose:

    - Only touches `gym_confirmed` on health_daily (never automated workout
      values or labels, which are owned by the selected sensor source).
    - Deletes the mirrored streak_events row for that date ONLY when its kind
      is still 'confirm'. A 'grace'/'reset' event belongs to the nightly run
      (core/streaks.py) and must never be erased by this path.

    Deleting a genuine 'confirm' row is safe: streaks.sync_confirms() (called
    by both apply_grace and gym_streak_state) only re-inserts a 'confirm' event
    for a date where health_daily.gym_confirmed = 1, which this function just
    cleared, so it will not resurrect the row. The next nightly apply_grace
    then sees the date as having no event and re-derives the correct grace/
    reset for it from the stool bank as of the day before, exactly as if the
    confirm had never happened, per the module's own idempotency guarantee.
    """
    day = day or today()
    result = upsert_health(conn, day, gym_confirmed=0, commit=False)
    conn.execute(
        "DELETE FROM streak_events WHERE date = ? AND kind = 'confirm'",
        (day,),
    )
    if commit:
        conn.commit()
    return result


def upsert_health(conn, day: str, commit: bool = True, **fields) -> dict:
    conn.execute("INSERT OR IGNORE INTO health_daily (date) VALUES (?)", (day,))
    allowed = (
        "sleep_hours", "steps", "workouts", "workout_mins", "workout", "energy",
        "weight_lbs", "notes", "source", "gym_confirmed",
    )
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if updates:
        cols = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE health_daily SET {cols} WHERE date = ?", (*updates.values(), day))
    if commit:
        conn.commit()
    row = conn.execute("SELECT * FROM health_daily WHERE date = ?", (day,)).fetchone()
    return dict(row) if row else {}


def recent_health(conn, days: int = 14) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM health_daily WHERE date >= date('now', 'localtime', ?) ORDER BY date DESC",
        (f"-{int(days)} days",),
    ).fetchall())


def health_for_day(conn, day: str) -> dict | None:
    row = conn.execute("SELECT * FROM health_daily WHERE date = ?", (day,)).fetchone()
    return dict(row) if row else None


def health_today(conn) -> dict | None:
    return health_for_day(conn, today())


# ------------------------------------------------------------------ poop log
# Body's plainest logger. Every read below is COUNT(*)/SELECT over live rows;
# nothing here stores or decrements a tally, which is what makes the undo
# honest (D3, the streak_events / lead_touches precedent).
#
# One writer: the /api/poop routes, i.e. Ian's own taps. No agent tool writes
# this table and none ever should; physician and coach read the aggregates
# through read_health and never see `note`.

POOP_BRISTOL_MIN = 1
POOP_BRISTOL_MAX = 7


def _poop_bristol(value) -> int | None:
    """Validate the optional Bristol score. Absent stays absent."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("bristol must be a number between 1 and 7")
    if float(value) != int(value):
        raise ValueError("bristol must be a whole number between 1 and 7")
    score = int(value)
    if score < POOP_BRISTOL_MIN or score > POOP_BRISTOL_MAX:
        raise ValueError("bristol must be between 1 and 7")
    return score


def get_poop(conn, poop_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM poop_log WHERE id = ? AND deleted_at IS NULL", (poop_id,)
    ).fetchone()
    return dict(row) if row else None


def log_poop(conn, *, day: str | None = None, bristol=None, note: str = "",
             logged_at: str | None = None, commit: bool = True) -> dict:
    cur = conn.execute(
        """INSERT INTO poop_log (day, logged_at, bristol, note)
           VALUES (?, COALESCE(?, datetime('now', 'localtime')), ?, ?)""",
        (day or today(), logged_at, _poop_bristol(bristol), (note or "").strip()[:280]),
    )
    if commit:
        conn.commit()
    return get_poop(conn, cur.lastrowid)


def update_poop(conn, poop_id: int, commit: bool = True, **fields) -> dict | None:
    """The optional second beat: Bristol and a one-line note, both editable."""
    sets, values = [], []
    if "bristol" in fields:
        sets.append("bristol = ?")
        values.append(_poop_bristol(fields["bristol"]))
    if "note" in fields:
        sets.append("note = ?")
        values.append((fields["note"] or "").strip()[:280])
    if not sets:
        return get_poop(conn, poop_id)
    values.append(poop_id)
    conn.execute(
        f"UPDATE poop_log SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL",
        values,
    )
    if commit:
        conn.commit()
    return get_poop(conn, poop_id)


def delete_poop(conn, poop_id: int, commit: bool = True) -> dict | None:
    """Soft, so Undo restores the same row rather than logging a new one."""
    row = get_poop(conn, poop_id)
    if row is None:
        return None
    conn.execute("UPDATE poop_log SET deleted_at = ? WHERE id = ?", (now(), poop_id))
    if commit:
        conn.commit()
    return row


def restore_poop(conn, poop_id: int, commit: bool = True) -> dict | None:
    conn.execute("UPDATE poop_log SET deleted_at = NULL WHERE id = ?", (poop_id,))
    if commit:
        conn.commit()
    return get_poop(conn, poop_id)


def poop_entries(conn, day: str) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT * FROM poop_log
           WHERE day = ? AND deleted_at IS NULL
           ORDER BY logged_at ASC, id ASC""",
        (day,),
    ).fetchall())


def poop_daily_counts(conn, days: int = 7, today_iso: str | None = None) -> list[dict]:
    """The one read path behind the rail, the averages, and the agent view.

    Returns every day in the window oldest first, including the zero days,
    so a caller never has to guess which dates a sparse table skipped.
    """
    end = date.fromisoformat(today_iso or today())
    span = max(1, int(days))
    start = end - timedelta(days=span - 1)
    counted = {
        r["day"]: r["n"] for r in conn.execute(
            """SELECT day, COUNT(*) n FROM poop_log
               WHERE deleted_at IS NULL AND day >= ? AND day <= ?
               GROUP BY day""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    }
    return [
        {"day": (d := (start + timedelta(days=i)).isoformat()), "count": counted.get(d, 0)}
        for i in range(span)
    ]


def last_poop(conn) -> dict | None:
    row = conn.execute(
        """SELECT * FROM poop_log WHERE deleted_at IS NULL
           ORDER BY logged_at DESC, id DESC LIMIT 1"""
    ).fetchone()
    return dict(row) if row else None


def poop_state(conn, today_iso: str | None = None, days: int = 7) -> dict:
    """Everything both the Body panel and the agent aggregate are built from.

    Note text is deliberately absent from the derived numbers here: callers
    that may show it (the Body page) read `entries`, callers that may not
    (read_health) take the counts and leave the rows alone.
    """
    day = today_iso or today()
    rail = poop_daily_counts(conn, days, today_iso=day)
    entries = poop_entries(conn, day)
    window = [d["count"] for d in rail]
    scored = [e["bristol"] for e in entries if e["bristol"] is not None]
    bristol_7d: dict[str, int] = {}
    for row in conn.execute(
        """SELECT bristol, COUNT(*) n FROM poop_log
           WHERE deleted_at IS NULL AND bristol IS NOT NULL AND day >= ? AND day <= ?
           GROUP BY bristol ORDER BY bristol""",
        (rail[0]["day"], day),
    ).fetchall():
        bristol_7d[str(row["bristol"])] = row["n"]
    latest = last_poop(conn)
    return {
        "day": day,
        "today_count": len(entries),
        "entries": entries,
        "rail": rail,
        "per_day_avg": round(sum(window) / len(window), 1) if window else 0.0,
        "days_logged": sum(1 for n in window if n > 0),
        "window_days": len(rail),
        "bristol_mix": bristol_7d,
        "today_bristol": scored,
        "last_logged_at": latest["logged_at"] if latest else None,
    }


def add_health_insight(
    conn,
    *,
    kind: str,
    body: str,
    sample_size: int = 0,
    commit: bool = True,
) -> int:
    """Store a private, health-only AI observation outside global memos.

    Health analysis is intentionally not a ``memos`` producer: those rows are
    visible to unrelated roles and are included in the nightly compactor.  This
    narrow table is the only durable output path for the physician and coach.
    """
    kind = str(kind or "pattern").strip().lower()
    body = str(body or "").strip()
    if kind not in {"pattern", "nudge", "weekly"}:
        raise ValueError("health insight kind must be pattern, nudge, or weekly")
    if not body or len(body) > 1600:
        raise ValueError("health insight body must be 1 to 1600 characters")
    try:
        sample_size = int(sample_size or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("health insight sample_size must be an integer") from exc
    if sample_size < 0 or sample_size > 365:
        raise ValueError("health insight sample_size must be between 0 and 365")
    cur = conn.execute(
        "INSERT INTO health_insights (kind, body, sample_size) VALUES (?, ?, ?)",
        (kind, body, sample_size),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def recent_health_insights(conn, limit: int = 6) -> list[dict]:
    """Private health analysis for the dedicated no-store Body route only."""
    bounded = max(1, min(int(limit), 20))
    rows = conn.execute(
        """SELECT id, kind, body, sample_size, created_at
           FROM health_insights
           WHERE dismissed_at IS NULL
           ORDER BY created_at DESC, id DESC LIMIT ?""",
        (bounded,),
    ).fetchall()
    return rows_to_dicts(rows)


def health_ai_prefs(conn) -> dict:
    """Return the singleton, fail-closed health AI consent preference."""
    row = conn.execute("SELECT * FROM health_ai_prefs WHERE id = 1").fetchone()
    # This is on every remote-model permission boundary. It must stay a pure
    # read: an INSERT OR IGNORE here opens a SQLite write transaction merely
    # to learn the default and can lock concurrent Body/API reads. The explicit
    # setter below creates the singleton on first opt-in or revocation.
    return dict(row) if row else {
        "id": 1,
        "share_health_with_ai": 0,
        "consent_version": "",
        "consented_at": None,
        "updated_at": None,
    }


def health_ai_sharing_enabled(conn) -> bool:
    """A remote model may see health context only after explicit consent."""
    return bool(health_ai_prefs(conn).get("share_health_with_ai"))


def set_health_ai_sharing(conn, enabled: bool, consent_version: str = "") -> dict:
    """Persist an explicit, revocable AI-health consent decision."""
    conn.execute(
        """INSERT INTO health_ai_prefs
           (id, share_health_with_ai, consent_version, consented_at, updated_at)
           VALUES (1, ?, ?, CASE WHEN ? THEN datetime('now', 'localtime') ELSE NULL END,
                   datetime('now', 'localtime'))
           ON CONFLICT(id) DO UPDATE SET
             share_health_with_ai=excluded.share_health_with_ai,
             consent_version=excluded.consent_version,
             consented_at=CASE WHEN excluded.share_health_with_ai = 1
                               THEN datetime('now', 'localtime') ELSE NULL END,
             updated_at=datetime('now', 'localtime')""",
        (1 if enabled else 0, consent_version.strip()[:80], 1 if enabled else 0),
    )
    conn.commit()
    return health_ai_prefs(conn)


# ------------------------------------------------------------ calendar

def upsert_calendar_event(conn, **fields) -> None:
    conn.execute(
        """INSERT INTO calendar_events (date, start_time, end_time, summary, category, duration_min, hash)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(hash) DO UPDATE SET
             category=excluded.category, duration_min=excluded.duration_min""",
        (fields["date"], fields.get("start_time"), fields.get("end_time"),
         fields["summary"], fields.get("category", ""), fields.get("duration_min"), fields["hash"]),
    )


def recent_calendar(conn, days: int = 14) -> list[dict]:
    """Return the useful local calendar window, not an unbounded future feed.

    Calendar imports can hold an entire semester.  The agent-facing calendar
    read should stay a briefing-sized window; otherwise a fresh Canvas import
    turns a 14-day question into hundreds of future events.
    """
    return rows_to_dicts(conn.execute(
        """SELECT * FROM calendar_events
           WHERE date BETWEEN date('now', 'localtime', ?) AND date('now', 'localtime', ?)
           ORDER BY date, start_time, summary""",
        (f"-{int(days)} days", f"+{int(days)} days"),
    ).fetchall())


def calendar_hours_by_category(conn, days: int = 7) -> dict[str, float]:
    rows = conn.execute(
        """SELECT category, SUM(COALESCE(duration_min, 0)) AS mins
           FROM calendar_events
           WHERE date BETWEEN date('now', 'localtime', ?) AND date('now', 'localtime')
           GROUP BY category""",
        (f"-{int(days)} days",),
    ).fetchall()
    return {r["category"] or "other": round(r["mins"] / 60, 1) for r in rows}


def calendar_for_date(conn, d: str) -> list[dict]:
    """Commitments (read-only external events) on one day. All-day rows sort first."""
    rows = conn.execute(
        "SELECT * FROM calendar_events WHERE date = ? ORDER BY start_time",
        (d,),
    ).fetchall()
    return rows_to_dicts(rows)


def ingest_last(conn, source: str) -> str | None:
    """Last import timestamp for an ingest source, or None if never run."""
    row = conn.execute(
        "SELECT last_import FROM ingest_log WHERE source = ?", (source,)
    ).fetchone()
    return row["last_import"] if row else None


# ------------------------------------------------------------- plan blocks
# ianOS-authored day-plan blocks (SPEC-v7). Two statuses only: 'planned'|'done'.
# 'sailed'/'moved' are DERIVED (core/plan.py), never stored. Every write bumps
# updated_at so the iCloud sync (Phase C) can push rows where updated_at > synced_at.

def _plan_block(conn, block_id: int) -> dict | None:
    row = conn.execute(
        """SELECT b.*, g.name AS goal_name
           FROM plan_blocks b LEFT JOIN goals g ON g.id = b.goal_id
           WHERE b.id = ?""",
        (block_id,),
    ).fetchone()
    return dict(row) if row else None


def get_plan_block(conn, block_id: int) -> dict | None:
    return _plan_block(conn, block_id)


def plan_blocks_for_date(conn, d: str) -> list[dict]:
    rows = conn.execute(
        """SELECT b.*, g.name AS goal_name
           FROM plan_blocks b LEFT JOIN goals g ON g.id = b.goal_id
           WHERE b.date = ? ORDER BY b.start_time, b.id""",
        (d,),
    ).fetchall()
    return rows_to_dicts(rows)


def recent_plan_blocks(conn, days: int = 7) -> list[dict]:
    rows = conn.execute(
        """SELECT b.*, g.name AS goal_name
           FROM plan_blocks b LEFT JOIN goals g ON g.id = b.goal_id
           WHERE b.date >= date('now', 'localtime', ?)
           ORDER BY b.date DESC, b.start_time""",
        (f"-{int(days)} days",),
    ).fetchall()
    return rows_to_dicts(rows)


def create_plan_block(conn, date: str, start_time: str, end_time: str,
                      title: str, goal_id: int | None = None,
                      commit: bool = True) -> dict:
    cur = conn.execute(
        """INSERT INTO plan_blocks (date, start_time, end_time, title, goal_id)
           VALUES (?,?,?,?,?)""",
        (date, start_time, end_time, title, goal_id),
    )
    if commit:
        conn.commit()
    return _plan_block(conn, cur.lastrowid)


def update_plan_block(conn, block_id: int, commit: bool = True, **fields) -> dict | None:
    allowed = {"date", "start_time", "end_time", "title", "goal_id", "status"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return _plan_block(conn, block_id)
    fields["updated_at"] = now()   # explicit bump so sync knows the row is dirty
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE plan_blocks SET {cols} WHERE id=?", (*fields.values(), block_id))
    if commit:
        conn.commit()
    return _plan_block(conn, block_id)


def delete_plan_block(conn, block_id: int, commit: bool = True) -> bool:
    """Delete a block. If it was ever synced, leave a tombstone so the next
    iCloud pull removes it remotely instead of re-importing it (the resurrection trap)."""
    row = conn.execute(
        "SELECT caldav_uid FROM plan_blocks WHERE id = ?", (block_id,)
    ).fetchone()
    if row is None:
        return False
    if row["caldav_uid"]:
        conn.execute(
            "INSERT OR IGNORE INTO plan_tombstones (caldav_uid) VALUES (?)",
            (row["caldav_uid"],),
        )
    conn.execute("DELETE FROM plan_blocks WHERE id = ?", (block_id,))
    if commit:
        conn.commit()
    return True


_RESTORE_COLS = ("id", "date", "start_time", "end_time", "title", "goal_id",
                 "status", "caldav_uid", "caldav_etag", "synced_at")


def restore_plan_block(conn, row: dict, commit: bool = True) -> dict | None:
    """Undo a delete: put the SAME row back, and clear its tombstone.

    Clearing the tombstone is the load-bearing half. delete_plan_block leaves
    one so the next iCloud pull deletes the event remotely instead of
    re-importing it; restoring the row without clearing it means the block
    reappears locally and is then killed again by the very next sync. Restores
    the original id so anything referencing it still resolves (the goal-archive
    precedent: an undo is a restore, not a re-create)."""
    vals = [row.get(c) for c in _RESTORE_COLS]
    cols = ", ".join(_RESTORE_COLS)
    marks = ", ".join("?" for _ in _RESTORE_COLS)
    try:
        cur = conn.execute(
            f"INSERT INTO plan_blocks ({cols}) VALUES ({marks})", vals)
    except sqlite3.IntegrityError:
        return None                              # id or uid already back
    if row.get("caldav_uid"):
        conn.execute("DELETE FROM plan_tombstones WHERE caldav_uid = ?",
                     (row["caldav_uid"],))
    if commit:
        conn.commit()
    return _plan_block(conn, row.get("id") or cur.lastrowid)


def sweep_sailed_blocks(conn, from_date: str, to_date: str, now_hhmm: str) -> list[dict]:
    """Move every still-planned block whose end has passed to `to_date`.

    Returns the rows as they were BEFORE the move, so the caller can undo.
    Uses the same is_sailed rule the UI renders from, imported late to keep
    core.db free of a core.plan import at module load."""
    from core import plan as _plan
    moved = []
    for b in plan_blocks_for_date(conn, from_date):
        if _plan.is_sailed(b, from_date, now_hhmm):
            moved.append(dict(b))
            update_plan_block(conn, b["id"], date=to_date)
    return moved


# ------------------------------------------------------------- journal (v8)
def archive_goal(conn, goal_id: int, archived: bool = True, commit: bool = True) -> None:
    """Retire a goal without destroying it (SPEC-v10 §4.2).

    The only existing exit was a hard DELETE, which is the wrong end of a swipe
    gesture, one thumb-slip and the row and its history are gone. A finished
    deadline should *leave the list*, not be erased, and Undo has to restore the
    same row: metrics resolve off goal ids, so re-creating one is not a restore.
    """
    conn.execute(
        "UPDATE goals SET archived = ? WHERE id = ?",
        (1 if archived else 0, goal_id),
    )
    if commit:
        conn.commit()


def get_goal(conn, goal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    return dict(row) if row else None


_GOAL_DEADLINE_UNSET = object()


def rebaseline_goal(conn, goal_id: int, target: str | None = None,
                     deadline=_GOAL_DEADLINE_UNSET, commit: bool = True) -> dict | None:
    """Target or deadline only (SPEC-v37 §4.2 Ring 1 `goal.rebaseline`),
    never domain, never hero. Existing goal only; the caller passes whichever
    field(s) actually change.

    `deadline` is nullable on `goals`, so it needs the three-way sentinel
    (`_NOTES_FOLDER_UNSET`/`update_fact`'s `source_sentinel` precedent):
    omitted means don't touch, `deadline=None` means clear it. Undo needs the
    real clear, since a goal rebaselined from "no deadline" must be able to
    restore exactly that, not just leave whatever the act set."""
    row = get_goal(conn, goal_id)
    if row is None:
        return None
    updates = {}
    if target is not None:
        updates["target"] = target
    if deadline is not _GOAL_DEADLINE_UNSET:
        updates["deadline"] = deadline
    if updates:
        cols = ", ".join(f"{k}=?" for k in updates)
        conn.execute(f"UPDATE goals SET {cols} WHERE id=?", (*updates.values(), goal_id))
        if commit:
            conn.commit()
    return get_goal(conn, goal_id)


def goal_has_unarchived_dependent(conn, goal_id: int) -> bool:
    """SPEC-v37 §4.2 `goal.archive` bound: never archive a goal something
    else still depends on."""
    row = conn.execute(
        "SELECT 1 FROM goals WHERE depends_on_goal_id = ? AND COALESCE(archived, 0) = 0 LIMIT 1",
        (goal_id,),
    ).fetchone()
    return row is not None


def expired_undecided_goals(conn, today: date, days: int = 14) -> list[dict]:
    """SPEC-v37 §6.3 / Law A9: an unarchived goal whose deadline lapsed more
    than `days` ago and nobody has ruled on. Most-overdue first. The window
    is strictly more-than, not at-or-past: a guardrail that fires on its own
    boundary as readily as past it proves nothing (Law A12)."""
    rows = conn.execute(
        "SELECT * FROM goals WHERE COALESCE(archived, 0) = 0 "
        "AND deadline IS NOT NULL AND deadline != ''"
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        g = dict(row)
        try:
            deadline = date.fromisoformat(g["deadline"])
        except ValueError:
            continue
        days_past = (today - deadline).days
        if days_past > days:
            g["days_past"] = days_past
            out.append(g)
    out.sort(key=lambda g: -g["days_past"])
    return out


def role_stats(conn) -> dict[str, dict]:
    """Per-agent track record, computed from rows that already exist, no new
    writes, no new table (SPEC-v10 §6).

    This is the AGENT's record, never Ian's: how often he took its advice tells
    him which ones he actually trusts. Pending is excluded from the ratio,
    because an undecided proposal is not a rejection. EXPIRED is bucketed
    explicitly for the same reason (SPEC-v32 law 4): a proposal that timed out
    unread says nothing about the agent, and it must never leak into the
    `rejected` count the roster divides by.
    """
    blank = {"made": 0, "approved": 0, "rejected": 0, "pending": 0,
             "expired": 0, "last_seen": None}
    out: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT role, status, COUNT(*) n FROM proposals GROUP BY role, status"
    ):
        s = out.setdefault(r["role"], dict(blank))
        key = r["status"].lower()
        if key in s:
            s[key] = r["n"]
        # `made` is the ratio's denominator: approved + rejected + pending
        # only. EXPIRED is a timeout, never a verdict (SPEC-v32 law 4), and
        # must not leak into it (SPEC-v37 §8.8).
        if key != "expired":
            s["made"] += r["n"]
    for r in conn.execute(
        "SELECT from_role, MAX(created_at) last FROM memos WHERE archived=0 GROUP BY from_role"
    ):
        s = out.setdefault(r["from_role"], dict(blank))
        s["last_seen"] = r["last"]
    return out


# ---------------------------------------------------------------- notes (v10)
# Ian's own notes. Unlike the journal below, chief + archivist may READ these :
# there is no *nightly* writing counterpart, and the one instant-write
# exception (chat_write_note, SPEC-v29 Phase 6, agents/runner.py) is
# schema-frozen at exactly {body, domain} -- see runner.py NOTE_READERS /
# INSTANT_WRITE_TOOLS, and tests/test_notes.py for both walls asserted.

NOTE_TITLE_MAX = 80


def note_title_from(body: str) -> str:
    """iPhone Notes behaviour: the first non-empty line names the note. Derived
    on save but STORED, so rendering a list never parses a body."""
    for line in (body or "").splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:NOTE_TITLE_MAX]
    return ""


# ------------------------------------------------- note body grammar (v31)
# notes.body is TEXT, not JSON (see SPEC-v31 "Rich text"), but its CONTRACT
# is a small CLOSED Markdown dialect: **bold**, *italic*, "- "/"1. " lists,
# "- [ ]"/"- [x]" checklists, and inline image embeds
# "![caption](note-image:TOKEN)". Everything outside that closed grammar --
# raw HTML tags, Markdown tables, footnotes, plain (non-image) links, and any
# image embed pointing anywhere but the note-image: scheme -- is stripped on
# every write. Same "closed, versioned, validated shape" discipline
# create_proposal (agents/runner.py) already applies to proposal drafts, and
# it runs HERE, at the data layer, not only at the API edge, matching
# CLAUDE.md's "guardrails live in code, not prompts."
#
# Idempotent by construction: sanitizing already-sanitized text matches none
# of these patterns a second time, so re-saving an existing note is a no-op.

_NOTE_TABLE_SEPARATOR_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$\n?",
    re.MULTILINE,
)
_NOTE_FOOTNOTE_DEF_RE = re.compile(r"^[ \t]*\[\^[^\]\n]+\]:.*$\n?", re.MULTILINE)
_NOTE_FOOTNOTE_REF_RE = re.compile(r"\[\^[^\]\n]+\]")
_NOTE_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]*)\)")
_NOTE_IMAGE_TOKEN_RE = re.compile(r"^note-image:[A-Za-z0-9_-]+$")
_NOTE_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\n]*)\)")
_NOTE_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>")


def _strip_foreign_note_image(match: "re.Match") -> str:
    """Keep a match only if it is a well-formed note-image: embed; any other
    image target (http, data:, file:, a malformed token) is dropped whole so
    a note body can never carry an outbound fetch or a foreign token."""
    if _NOTE_IMAGE_TOKEN_RE.match(match.group(2).strip()):
        return match.group(0)
    return ""


def sanitize_note_body(body: str) -> str:
    """Enforce notes.body's closed Markdown dialect (SPEC-v31). Called from
    create_note and update_note so every write is sanitized, whoever the
    caller is (dashboard PATCH, chat_write_note, or a future caller) --
    never a check only the API layer remembers to run.

    Strips, never raises: a note body always saves, degraded rather than
    rejected outright, matching this surface's zero-friction autosave law.
    """
    text = body or ""
    text = _NOTE_TABLE_SEPARATOR_RE.sub("", text)
    text = _NOTE_FOOTNOTE_DEF_RE.sub("", text)
    text = _NOTE_FOOTNOTE_REF_RE.sub("", text)
    text = _NOTE_IMAGE_RE.sub(_strip_foreign_note_image, text)
    text = _NOTE_LINK_RE.sub(lambda m: m.group(1), text)
    text = _NOTE_HTML_TAG_RE.sub("", text)
    return text


def create_note(
    conn, body: str = "", domain: str | None = None, folder_id: int | None = None,
    commit: bool = True,
) -> dict:
    body = sanitize_note_body(body)
    cur = conn.execute(
        "INSERT INTO notes (title, body, domain, folder_id) VALUES (?, ?, ?, ?)",
        (note_title_from(body), body, domain, folder_id),
    )
    if commit:
        conn.commit()
    return note(conn, cur.lastrowid)


def note(conn, note_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


def update_note(conn, note_id: int, **fields) -> dict | None:
    allowed = {
        k: v for k, v in fields.items() if k in ("body", "pinned", "domain", "folder_id")
    }
    if "body" in allowed:
        allowed["body"] = sanitize_note_body(allowed["body"])
        allowed["title"] = note_title_from(allowed["body"])
    if not allowed:
        return note(conn, note_id)
    sets = ", ".join(f"{k} = ?" for k in allowed)
    conn.execute(
        f"UPDATE notes SET {sets}, updated_at = datetime('now', 'localtime') WHERE id = ?",
        (*allowed.values(), note_id),
    )
    conn.commit()
    # SPEC-v31: "deleting an attachment from the body soft-deletes the row
    # lazily on next autosave." The body is the one copy of which images a
    # note actually holds, so the reap runs HERE, in the single write path
    # for a note body, not at the API edge where a future caller could
    # forget it (the sanitize_note_body precedent directly above).
    if "body" in allowed:
        reap_note_attachments(conn, note_id, allowed["body"])
    return note(conn, note_id)


def delete_note(conn, note_id: int, commit: bool = True) -> None:
    """Soft, the list offers an undo, so nothing is destroyed on a single tap."""
    conn.execute(
        "UPDATE notes SET deleted_at = datetime('now', 'localtime') WHERE id = ?",
        (note_id,),
    )
    if commit:
        conn.commit()


def restore_note(conn, note_id: int) -> dict | None:
    conn.execute("UPDATE notes SET deleted_at = NULL WHERE id = ?", (note_id,))
    conn.commit()
    return note(conn, note_id)


# Sentinel distinguishing "folder_id not passed" from the real value None,
# the same pattern update_fact's source_sentinel already uses (core/db.py,
# update_fact). Must be a module-level constant: a default argument value is
# evaluated once at def-time, so a fresh object() inline as the default would
# still work for identity comparison, but naming it keeps the three-way
# meaning legible at every call site.
_NOTES_FOLDER_UNSET = object()


def list_notes(
    conn,
    q: str = "",
    include_deleted: bool = False,
    folder_id=_NOTES_FOLDER_UNSET,
) -> list[dict]:
    """Pinned first, then most recently touched, the order the list renders in.

    folder_id is three-way, not two-way: omitted (the default) returns every
    note regardless of folder -- today's one existing call site
    (api/main.py's GET /api/notes) and the spec's default "All Notes" view,
    both unscoped by folder and both left unchanged by this filter's
    addition. Passing None scopes to unfiled/root notes. Passing an int scopes
    to that folder's notes -- including when that folder id now points at a
    soft-deleted row (a note whose folder was independently deleted just
    keeps matching here; it reads as "unfiled" only once something clears its
    folder_id, never an error).
    """
    where = ["1=1" if include_deleted else "deleted_at IS NULL"]
    params: list = []
    if q:
        where.append("(title LIKE ? OR body LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if folder_id is not _NOTES_FOLDER_UNSET:
        if folder_id is None:
            where.append("folder_id IS NULL")
        else:
            where.append("folder_id = ?")
            params.append(folder_id)
    rows = conn.execute(
        f"SELECT * FROM notes WHERE {' AND '.join(where)} "
        f"ORDER BY pinned DESC, updated_at DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


# ------------------------------------------------------------ note folders
# SPEC-v31. Ian's own nested filing tree over `notes`. Cycle prevention lives
# in code (move_note_folder's WITH RECURSIVE ancestor walk), never a schema
# CHECK -- SQLite cannot declare "no self-reference cycle." Cascade
# delete/restore generalizes archive_partner_task/restore_partner_archive
# (core/db.py:4284-4370ish) to arbitrary depth, dropping partner's
# PartnerHierarchyConflict restore-order guard on purpose: a note whose folder
# is still independently deleted just shows unfiled, a harmless state with
# none of partner's progress-math dependency.

def note_folder(conn, folder_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM note_folders WHERE id = ?", (folder_id,)
    ).fetchone()
    return dict(row) if row else None


def create_note_folder(
    conn, name: str, parent_id: int | None = None, color: str | None = None
) -> dict:
    """Raises ValueError (writes nothing) when parent_id is given but does not
    reference a live folder -- mirrors move_note_folder's liveness check so a
    soft-deleted folder can't silently gain a new live child (D2: the write
    boundary validates itself rather than trusting a caller's pre-check)."""
    if parent_id is not None:
        parent_row = conn.execute(
            "SELECT deleted_at FROM note_folders WHERE id = ?", (parent_id,)
        ).fetchone()
        if parent_row is None or parent_row["deleted_at"] is not None:
            raise ValueError("parent folder not found")
    cur = conn.execute(
        "INSERT INTO note_folders (name, parent_id, color) VALUES (?, ?, ?)",
        (name, parent_id, color),
    )
    conn.commit()
    return note_folder(conn, cur.lastrowid)


def update_note_folder(conn, folder_id: int, **fields) -> dict | None:
    """Partial update: only name/color/position are settable here. Reparenting
    goes through move_note_folder instead, since that's the one write that
    needs the cycle guard -- keeping it out of this generic setter means a
    future field added here can never accidentally skip that check."""
    allowed = {k: v for k, v in fields.items() if k in ("name", "color", "position")}
    if not allowed:
        return note_folder(conn, folder_id)
    sets = ", ".join(f"{k} = ?" for k in allowed)
    conn.execute(
        f"UPDATE note_folders SET {sets}, updated_at = datetime('now', 'localtime') "
        f"WHERE id = ?",
        (*allowed.values(), folder_id),
    )
    conn.commit()
    return note_folder(conn, folder_id)


def list_note_folders(conn, parent_id: int | None = None) -> list[dict]:
    """Children of one parent, or top-level folders when parent_id is None.
    Excludes soft-deleted. Alphabetical, case-insensitive, among folders --
    folders-before-notes at each level is a UI concern, not this function's;
    `position` exists in the schema for a later drag-to-reorder pass and is
    not read here yet (named and deferred, not silently dropped, per spec)."""
    if parent_id is None:
        rows = conn.execute(
            "SELECT * FROM note_folders WHERE parent_id IS NULL AND deleted_at IS NULL "
            "ORDER BY name COLLATE NOCASE"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM note_folders WHERE parent_id = ? AND deleted_at IS NULL "
            "ORDER BY name COLLATE NOCASE",
            (parent_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def move_note_folder(conn, folder_id: int, new_parent_id: int | None) -> dict | None:
    """Reparents a folder. Refuses (raises ValueError, writes nothing) when
    new_parent_id equals folder_id, doesn't reference a live (non-soft-deleted)
    folder, or sits anywhere in folder_id's own subtree -- the last walked by
    climbing new_parent_id's ancestor chain with WITH RECURSIVE and checking
    whether folder_id appears in it. Moving to top-level (new_parent_id=None)
    is always safe, no checks needed.

    The liveness check must run before the ancestor walk: new_parent_id
    referencing a row that doesn't exist at all would otherwise sail through
    the (empty) ancestor walk and hit the UPDATE's FOREIGN KEY constraint as
    an uncaught IntegrityError, and a soft-deleted folder still exists as a
    row so it would pass a bare existence check and silently become a live
    folder's parent, orphaning it from the visible tree."""
    if new_parent_id is not None:
        new_parent_id = int(new_parent_id)
        if new_parent_id == int(folder_id):
            raise ValueError("a folder cannot become its own parent")
        parent_row = conn.execute(
            "SELECT deleted_at FROM note_folders WHERE id = ?", (new_parent_id,)
        ).fetchone()
        if parent_row is None or parent_row["deleted_at"] is not None:
            raise ValueError("new parent folder not found")
        ancestor_rows = conn.execute(
            """WITH RECURSIVE ancestors(id, parent_id) AS (
                   SELECT id, parent_id FROM note_folders WHERE id = ?
                   UNION ALL
                   SELECT nf.id, nf.parent_id
                   FROM note_folders nf
                   JOIN ancestors a ON nf.id = a.parent_id
               )
               SELECT id FROM ancestors""",
            (new_parent_id,),
        ).fetchall()
        if any(int(r["id"]) == int(folder_id) for r in ancestor_rows):
            raise ValueError("cannot move a folder into its own descendant")
    conn.execute(
        "UPDATE note_folders SET parent_id = ?, updated_at = datetime('now', 'localtime') "
        "WHERE id = ?",
        (new_parent_id, folder_id),
    )
    conn.commit()
    return note_folder(conn, folder_id)


# How many times a random token is re-minted before giving up. Shared by the
# note delete-batch id and the attachment token; both are 32 bits, so one
# retry already removes the collision from consideration and ten removes it
# from arithmetic.
_TOKEN_MINT_TRIES = 10


def _mint_note_batch_id(conn) -> str:
    """A deleted_batch_id no live-or-deleted row already carries, in either
    table. Undo is keyed on this string alone (restore_note_folder_cascade),
    so a reused id would restore someone else's rows."""
    for _ in range(_TOKEN_MINT_TRIES):
        candidate = secrets.token_hex(4)
        taken = conn.execute(
            "SELECT 1 FROM note_folders WHERE deleted_batch_id = ? "
            "UNION ALL SELECT 1 FROM notes WHERE deleted_batch_id = ? LIMIT 1",
            (candidate, candidate),
        ).fetchone()
        if taken is None:
            return candidate
    raise RuntimeError("could not mint a unique note delete-batch id")


def delete_note_folder_cascade(conn, folder_id: int) -> dict:
    """Soft-deletes a folder and its full descendant closure -- subfolders at
    any depth, and every note filed anywhere in that subtree -- under one
    shared deleted_batch_id, mirroring archive_partner_task generalized to
    arbitrary depth via WITH RECURSIVE over note_folders.parent_id, joined
    against notes.folder_id for the note half of the closure.

    deleted_at is computed once in Python and reused for every row so the
    whole batch shares one timestamp, not a per-row clock read. Only rows
    that are currently live (deleted_at IS NULL) get stamped, so a subfolder
    already deleted in an earlier batch keeps its own batch id instead of
    being silently absorbed into this one.
    """
    target = conn.execute(
        "SELECT id FROM note_folders WHERE id = ? AND deleted_at IS NULL",
        (folder_id,),
    ).fetchone()
    if target is None:
        raise ValueError("folder not found")

    folder_rows = conn.execute(
        """WITH RECURSIVE descendants(id) AS (
               SELECT id FROM note_folders WHERE id = ?
               UNION ALL
               SELECT nf.id FROM note_folders nf
               JOIN descendants d ON nf.parent_id = d.id
           )
           SELECT id FROM descendants""",
        (folder_id,),
    ).fetchall()
    folder_ids = [int(r["id"]) for r in folder_rows]
    folder_placeholders = ",".join("?" for _ in folder_ids)

    note_rows = conn.execute(
        f"SELECT id FROM notes WHERE folder_id IN ({folder_placeholders}) "
        f"AND deleted_at IS NULL",
        folder_ids,
    ).fetchall()
    note_ids = [int(r["id"]) for r in note_rows]

    # secrets.token_hex(4) matches this codebase's own existing convention
    # for a random (never timestamp-based) token -- see the journal media
    # filename suffix and sync_icloud's synthetic UID (api/main.py,
    # ingest/sync_icloud.py) -- so two deletes landing in the same second
    # never collide the way a timestamp-derived batch id would.
    #
    # deleted_batch_id has no UNIQUE constraint (it is the opposite: many
    # rows share one), so a repeat would not raise -- it would silently
    # MERGE two unrelated deletes, and one Undo would resurrect the other
    # batch's rows too. Mint against the ids already on disk instead.
    batch_id = _mint_note_batch_id(conn)
    stamp = now()

    conn.execute(
        f"UPDATE note_folders SET deleted_at = ?, deleted_batch_id = ? "
        f"WHERE deleted_at IS NULL AND id IN ({folder_placeholders})",
        (stamp, batch_id, *folder_ids),
    )
    if note_ids:
        note_placeholders = ",".join("?" for _ in note_ids)
        conn.execute(
            f"UPDATE notes SET deleted_at = ?, deleted_batch_id = ? "
            f"WHERE deleted_at IS NULL AND id IN ({note_placeholders})",
            (stamp, batch_id, *note_ids),
        )
    conn.commit()
    return {
        "deleted_batch_id": batch_id,
        "deleted_at": stamp,
        "folder_ids": folder_ids,
        "note_ids": note_ids,
    }


def restore_note_folder_cascade(conn, batch_id: str) -> dict:
    """Reverses delete_note_folder_cascade by matching deleted_batch_id
    exactly, across both tables, at whatever depth the original cascade
    spanned -- no ancestor walk needed here, unlike the delete side, because
    the batch id was already stamped flat onto every affected row. No
    restore-order guard (see the module comment above): a restored note whose
    folder is still independently deleted just shows unfiled."""
    folder_rows = conn.execute(
        "SELECT id FROM note_folders WHERE deleted_batch_id = ?", (batch_id,)
    ).fetchall()
    note_rows = conn.execute(
        "SELECT id FROM notes WHERE deleted_batch_id = ?", (batch_id,)
    ).fetchall()
    if not folder_rows and not note_rows:
        raise ValueError("delete batch not found")

    conn.execute(
        "UPDATE note_folders SET deleted_at = NULL, deleted_batch_id = NULL "
        "WHERE deleted_batch_id = ?",
        (batch_id,),
    )
    conn.execute(
        "UPDATE notes SET deleted_at = NULL, deleted_batch_id = NULL "
        "WHERE deleted_batch_id = ?",
        (batch_id,),
    )
    conn.commit()
    return {
        "deleted_batch_id": batch_id,
        "folder_ids": [int(r["id"]) for r in folder_rows],
        "note_ids": [int(r["id"]) for r in note_rows],
    }


# --------------------------------------------------------- note attachments
# SPEC-v31. One row per inline image embedded in a note body via the Markdown
# embed `![caption](note-image:TOKEN)` -- see note_attachments in SCHEMA above
# for why there's no caption column here (the body text is the one copy).
# The API route (POST /api/notes/{id}/attachments) writes the file to disk
# and resolves its ROOT-relative path *before* calling create_note_attachment;
# this function's own job is minting the opaque `token` that names the
# attachment everywhere downstream (the GET route, the Markdown embed) --
# secrets.token_hex(4) matches this file's own convention for a random,
# never-timestamp-based token (delete_note_folder_cascade's batch_id above,
# and api/main.py's journal media filename suffix).

def create_note_attachment(
    conn,
    note_id: int,
    *,
    path: str,
    kind: str = "photo",
    width: int | None = None,
    height: int | None = None,
) -> dict:
    # 32 bits of token in a UNIQUE column: a repeat is vanishingly unlikely
    # at Ian's volume, but "vanishingly unlikely" surfaces as an uncaught
    # IntegrityError and a 500 on an upload that had already written its
    # file to disk. Retrying costs two lines and makes it impossible.
    for _ in range(_TOKEN_MINT_TRIES):
        token = secrets.token_hex(4)
        try:
            cur = conn.execute(
                "INSERT INTO note_attachments (note_id, token, path, kind, width, height) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (note_id, token, path, kind, width, height),
            )
        except sqlite3.IntegrityError as exc:
            # Only a token collision is retryable. A foreign-key failure (a
            # note_id that does not exist) must still surface as itself
            # rather than as a bogus "could not mint a token" ten tries later.
            if "note_attachments.token" not in str(exc):
                raise
            continue
        conn.commit()
        return note_attachment(conn, cur.lastrowid)
    raise RuntimeError("could not mint a unique note attachment token")


# One token embed, capturing the token itself: the body is the only record of
# which attachments a note still holds (note_attachments has no caption
# column precisely because the body text is the one copy).
_NOTE_IMAGE_EMBED_TOKEN_RE = re.compile(
    r"!\[[^\]\n]*\]\(note-image:([A-Za-z0-9_-]+)\)"
)


def reap_note_attachments(conn, note_id: int, body: str) -> dict:
    """Reconcile this note's attachment rows against the embeds still in its
    body (SPEC-v31's "soft-deletes the row lazily on next autosave").

    Two directions, both required:
      - an embed the body no longer carries soft-deletes its row, so
        note_attachment_by_token stops resolving it and the bytes stop being
        servable the moment Ian removes the image;
      - an embed that came BACK un-deletes it, because the editor's own undo
        (and the sanitize round trip) can put a removed embed straight back,
        and a one-way reap would leave that image permanently broken.

    Soft only, and the file on disk is left alone, exactly like delete_note
    and delete_note_attachment: undo has to be able to restore the same row.
    """
    live = set(_NOTE_IMAGE_EMBED_TOKEN_RE.findall(body or ""))
    rows = conn.execute(
        "SELECT id, token, deleted_at FROM note_attachments WHERE note_id = ?",
        (note_id,),
    ).fetchall()

    reaped = [
        int(r["id"]) for r in rows if r["deleted_at"] is None and r["token"] not in live
    ]
    revived = [
        int(r["id"]) for r in rows if r["deleted_at"] is not None and r["token"] in live
    ]
    if reaped:
        conn.execute(
            "UPDATE note_attachments SET deleted_at = ? WHERE id IN "
            f"({','.join('?' for _ in reaped)})",
            (now(), *reaped),
        )
    if revived:
        conn.execute(
            "UPDATE note_attachments SET deleted_at = NULL WHERE id IN "
            f"({','.join('?' for _ in revived)})",
            revived,
        )
    if reaped or revived:
        conn.commit()
    return {"reaped": reaped, "revived": revived}


def note_attachment(conn, attachment_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM note_attachments WHERE id = ?", (attachment_id,)
    ).fetchone()
    return dict(row) if row else None


def note_attachment_by_token(conn, token: str) -> dict | None:
    """Only a live (non-deleted) attachment resolves -- this is the GET
    route's one source for the stored path, so no client input ever reaches
    filesystem resolution and a soft-deleted attachment's file stops being
    servable the instant it's deleted, no separate check needed downstream."""
    row = conn.execute(
        "SELECT * FROM note_attachments WHERE token = ? AND deleted_at IS NULL",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def delete_note_attachment(conn, attachment_id: int) -> None:
    """Soft delete, mirroring notes.deleted_at's own pattern exactly -- the
    file on disk is left alone here (the route layer's call, same split
    journal's media delete uses between the DB row and the unlink)."""
    conn.execute(
        "UPDATE note_attachments SET deleted_at = datetime('now', 'localtime') "
        "WHERE id = ?",
        (attachment_id,),
    )
    conn.commit()


# Private nightly reflection entries + one photo/video each. Bodies and media are
# Ian-only; nothing here is ever exposed to agents (see the api privacy wall and
# core/journal.py, which only ever reads dates for counts).

def _journal_row(conn, entry_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def journal_entry(conn, entry_id: int) -> dict | None:
    return _journal_row(conn, entry_id)


def create_journal_entry(conn, date: str, body: str) -> dict:
    cur = conn.execute("INSERT INTO journal_entries (date, body) VALUES (?, ?)", (date, body))
    conn.commit()
    return _journal_row(conn, cur.lastrowid)


def recent_journal(conn, limit: int = 30, before_id: int | None = None) -> list[dict]:
    """Reverse-chronological page. before_id is a simple cursor (append-only nightly
    entries make id order ≈ date order)."""
    if before_id:
        rows = conn.execute(
            "SELECT * FROM journal_entries WHERE id < ? ORDER BY date DESC, id DESC LIMIT ?",
            (int(before_id), int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM journal_entries ORDER BY date DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return rows_to_dicts(rows)


def journal_for_date(conn, d: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM journal_entries WHERE date = ? ORDER BY id", (d,)
    ).fetchall()
    return rows_to_dicts(rows)


def update_journal_entry(conn, entry_id: int, **fields) -> dict | None:
    allowed = {"body", "media_path", "media_kind", "shared"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return _journal_row(conn, entry_id)
    fields["updated_at"] = now()   # SQLite does not bump updated_at on its own
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE journal_entries SET {cols} WHERE id=?", (*fields.values(), entry_id))
    conn.commit()
    return _journal_row(conn, entry_id)


def delete_journal_entry(conn, entry_id: int) -> bool:
    row = conn.execute(
        "SELECT media_path FROM journal_entries WHERE id = ?", (entry_id,)
    ).fetchone()
    if row is None:
        return False
    if row["media_path"]:
        (ROOT / row["media_path"]).unlink(missing_ok=True)   # drop the media file too
    conn.execute("DELETE FROM journal_entries WHERE id = ?", (entry_id,))
    conn.commit()
    return True


# ------------------------------------------------------------- holdings

def replace_holdings_snapshot(conn, as_of_date: str, positions: list[dict], source: str,
                              *, commit: bool = True) -> int:
    conn.execute(
        "DELETE FROM holdings WHERE as_of_date = ? AND source = ?",
        (as_of_date, source),
    )
    for p in positions:
        conn.execute(
            """INSERT INTO holdings
               (account, symbol, description, quantity, cost_basis, market_value,
                currency, as_of_date, source, hash, account_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (p["account"], p["symbol"], p.get("description", ""), p["quantity"],
             p.get("cost_basis"), p["market_value"], p.get("currency", "USD"),
             as_of_date, source, p["hash"], p.get("account_key", "")),
        )
    if commit:
        conn.commit()
    return len(positions)


def latest_holdings(conn, source: str | None = None) -> list[dict]:
    q = "SELECT MAX(as_of_date) AS d FROM holdings"
    args: tuple = ()
    if source:
        q += " WHERE source = ?"
        args = (source,)
    row = conn.execute(q, args).fetchone()
    if not row or not row["d"]:
        return []
    q2 = "SELECT * FROM holdings WHERE as_of_date = ?"
    args2: list = [row["d"]]
    if source:
        q2 += " AND source = ?"
        args2.append(source)
    q2 += " ORDER BY market_value DESC"
    return rows_to_dicts(conn.execute(q2, args2).fetchall())


def get_holding(conn, holding_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM holdings WHERE id = ?", (int(holding_id),)
    ).fetchone()
    return dict(row) if row else None


def portfolio_snapshot(conn) -> dict | None:
    # A deliberately accepted empty SnapTrade refresh is current truth even
    # though holdings rows are retained as history. Without this marker the
    # previous nonempty day would incorrectly remain the current portfolio.
    source_status = ingest_status(conn, "snaptrade_fidelity")
    if source_status and source_status.get("last_success") and source_status.get("row_count") == 0:
        return None
    positions = latest_holdings(conn)
    if not positions:
        return None
    as_of = positions[0]["as_of_date"]
    total = round(sum(p["market_value"] for p in positions), 2)
    cost = sum(p["cost_basis"] for p in positions if p["cost_basis"] is not None)
    prior = conn.execute(
        """SELECT as_of_date, SUM(market_value) AS total
           FROM holdings WHERE as_of_date < ?
           GROUP BY as_of_date ORDER BY as_of_date DESC LIMIT 1""",
        (as_of,),
    ).fetchone()
    day_change = round(total - prior["total"], 2) if prior else None
    return {
        "total_value": total,
        "total_cost_basis": round(cost, 2) if cost else None,
        "day_change": day_change,
        "as_of_date": as_of,
        "positions": positions,
    }


# -------------------------------------------------------------- focus

def sunday_of(d: date | None = None) -> str:
    from datetime import timedelta
    d = d or date.today()
    days_since_sunday = (d.weekday() + 1) % 7
    return (d - timedelta(days=days_since_sunday)).isoformat()


def current_focus(conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM focus_allocations ORDER BY week_start DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"week_start": sunday_of(), "domains": ["business"], "goal_ids": [], "rationale": "default"}
    return {
        "week_start": row["week_start"],
        "domains": json.loads(row["domains"]),
        "goal_ids": json.loads(row["goal_ids"]),
        "rationale": row["rationale"],
    }


def upsert_focus(conn, week_start: str, domains: list[str], goal_ids: list[int], rationale: str) -> None:
    conn.execute(
        """INSERT INTO focus_allocations (week_start, domains, goal_ids, rationale)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(week_start) DO UPDATE SET
             domains=excluded.domains, goal_ids=excluded.goal_ids,
             rationale=excluded.rationale,
             created_at=datetime('now', 'localtime')""",
        (week_start, json.dumps(domains), json.dumps(goal_ids), rationale),
    )
    conn.commit()


# ----------------------------------------------------------- ingest log

_SAFE_INGEST_ERRORS = frozenset({"network", "auth", "provider_5xx", "protocol"})


def record_ingest_attempt(conn, source: str, *, commit: bool = True) -> None:
    """Persist that network work started without pretending it succeeded."""
    conn.execute(
        """INSERT INTO ingest_log (source, last_attempt)
           VALUES (?, datetime('now', 'localtime'))
           ON CONFLICT(source) DO UPDATE SET
             last_attempt=datetime('now', 'localtime')""",
        (source,),
    )
    if commit:
        conn.commit()


def record_ingest_success(conn, source: str, row_count: int, notes: str = "",
                          *, commit: bool = True) -> None:
    """Publish a durable success, including valid zero-row syncs.

    With ``commit=False`` a source writer can atomically commit its data and
    this freshness record in an outer transaction.
    """
    conn.execute(
        """INSERT INTO ingest_log
           (source, last_import, last_attempt, last_success, row_count, notes,
            last_error, consecutive_failures, stale_alerted_at)
           VALUES (?, datetime('now', 'localtime'), datetime('now', 'localtime'),
                   datetime('now', 'localtime'), ?, ?, '', 0, NULL)
           ON CONFLICT(source) DO UPDATE SET
             last_import=datetime('now', 'localtime'),
             last_attempt=datetime('now', 'localtime'),
             last_success=datetime('now', 'localtime'),
             row_count=excluded.row_count,
             notes=excluded.notes,
             last_error='',
             consecutive_failures=0,
             stale_alerted_at=NULL""",
        (source, row_count, notes),
    )
    if commit:
        conn.commit()


def record_ingest_failure(conn, source: str, error_code: str,
                          *, commit: bool = True) -> None:
    """Record only a classified failure; raw provider errors are forbidden.

    SPEC-v37 §8.4: the role-crash precedent, applied here too -- a failure
    that reaches this function must never be silent. Writes one `system`
    memo on the FIRST failure of a new streak only (consecutive_failures was
    0 or the row didn't exist yet), not on every retry of an already-known
    -broken source: that would be the exact "16 alerts an hour" trap D9's
    fire-once guard note already warns about, just for ingest instead of a
    push notification. The Aug 30 SnapTrade `failed (protocol)` drop-out (4
    of 9 accounts snapshotted) that motivated this was finance, but the
    function is shared with Canvas sync too, and a silent Canvas failure is
    exactly as real a bug.
    """
    if error_code not in _SAFE_INGEST_ERRORS:
        raise ValueError(f"unsafe ingest error code: {error_code!r}")
    prior = conn.execute(
        "SELECT consecutive_failures FROM ingest_log WHERE source = ?", (source,)
    ).fetchone()
    first_in_streak = prior is None or not prior["consecutive_failures"]
    conn.execute(
        """INSERT INTO ingest_log (source, last_error, consecutive_failures)
           VALUES (?, ?, 1)
           ON CONFLICT(source) DO UPDATE SET
             last_error=excluded.last_error,
             consecutive_failures=ingest_log.consecutive_failures + 1""",
        (source, error_code),
    )
    if first_in_streak:
        add_memo(
            conn, "system", f"sync failed: {source}",
            f"{source} failed ({error_code}) and has not recovered yet.",
            priority=2, commit=False,
        )
    if commit:
        conn.commit()


def update_ingest_log(conn, source: str, row_count: int, notes: str = "",
                      *, commit: bool = True) -> None:
    """Compatibility success path for existing non-finance importers."""
    record_ingest_success(conn, source, row_count, notes, commit=commit)


def claim_stale_ingest_alerts(conn, sources: list[str]) -> list[str]:
    """Atomically claim unalerted stale sources before any push is attempted.

    Freshness evaluation stays outside this short write transaction. The
    caller supplies only configured sources already evaluated as stale.
    """
    requested = list(dict.fromkeys(sources))
    if not requested:
        return []
    if conn.in_transaction:
        raise sqlite3.OperationalError("stale alert claim requires a clean transaction")
    marks = ",".join("?" for _ in requested)
    conn.execute("BEGIN IMMEDIATE")
    try:
        claimed = [
            row["source"] for row in conn.execute(
                f"""SELECT source FROM ingest_log
                    WHERE source IN ({marks}) AND stale_alerted_at IS NULL
                    ORDER BY source""",
                requested,
            )
        ]
        if claimed:
            claimed_marks = ",".join("?" for _ in claimed)
            conn.execute(
                f"""UPDATE ingest_log
                    SET stale_alerted_at=datetime('now', 'localtime')
                    WHERE source IN ({claimed_marks}) AND stale_alerted_at IS NULL""",
                claimed,
            )
        conn.commit()
        return claimed
    except Exception:
        conn.rollback()
        raise


def ingest_status(conn, source: str) -> dict | None:
    row = conn.execute("SELECT * FROM ingest_log WHERE source = ?", (source,)).fetchone()
    return dict(row) if row else None


def checking_balance(conn) -> dict | None:
    """SPEC-v37 §8.4: `source` travels with the balance so a caller can look
    up freshness against the account that actually produced this number
    (metrics.finance_state), instead of a hardcoded 'simplefin_chase' that
    stopped being true the day Plaid replaced it."""
    row = conn.execute(
        """SELECT current_balance AS balance, as_of, source
           FROM financial_accounts
           WHERE type = 'depository' AND subtype = 'checking'
           ORDER BY updated_at DESC LIMIT 1"""
    ).fetchone()
    if row and row["balance"] is not None:
        return {"balance": row["balance"], "as_of": row["as_of"], "source": row["source"]}
    row = ingest_status(conn, "simplefin_chase")
    if not row or not row["notes"]:
        return None
    try:
        data = json.loads(row["notes"])
        return {
            "balance": data.get("balance"),
            "as_of": data.get("as_of") or row["last_import"],
            "source": "simplefin_chase",
        }
    except json.JSONDecodeError:
        return None


def upsert_financial_accounts(conn, source: str, item_key: str,
                              institution: str, accounts: list[dict],
                              *, as_of: str | None = None) -> int:
    """Publish a provider's current account metadata/balances atomically."""
    if not isinstance(accounts, list):
        raise ValueError("accounts must be a list")

    def balance_value(balances: dict, key: str) -> float | None:
        value = balances.get(key)
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"account {key} balance is malformed") from exc
        if not math.isfinite(value):
            raise ValueError(f"account {key} balance is malformed")
        return value

    seen: list[str] = []
    for account in accounts:
        if not isinstance(account, dict):
            raise ValueError("account must be an object")
        external_id = str(account.get("account_id") or account.get("id") or "").strip()
        if not external_id:
            raise ValueError("account is missing an id")
        balances = account.get("balances") or {}
        if not isinstance(balances, dict):
            raise ValueError("account balances must be an object")
        seen.append(external_id)
        conn.execute(
            """INSERT INTO financial_accounts
               (source, external_id, item_key, institution, name, type, subtype,
                mask, current_balance, available_balance, credit_limit, currency, as_of)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, external_id) DO UPDATE SET
                 item_key=excluded.item_key, institution=excluded.institution,
                 name=excluded.name, type=excluded.type, subtype=excluded.subtype,
                 mask=excluded.mask, current_balance=excluded.current_balance,
                 available_balance=excluded.available_balance,
                 credit_limit=excluded.credit_limit, currency=excluded.currency,
                 as_of=excluded.as_of, updated_at=datetime('now', 'localtime')""",
            (
                source, external_id, item_key, institution,
                str(account.get("name") or ""), str(account.get("type") or ""),
                str(account.get("subtype") or ""), str(account.get("mask") or ""),
                balance_value(balances, "current"), balance_value(balances, "available"),
                balance_value(balances, "limit"),
                str(account.get("iso_currency_code") or "USD"), as_of,
            ),
        )
    if seen:
        marks = ",".join("?" for _ in seen)
        conn.execute(
            f"DELETE FROM financial_accounts WHERE source = ? AND item_key = ? "
            f"AND external_id NOT IN ({marks})",
            (source, item_key, *seen),
        )
    else:
        conn.execute(
            "DELETE FROM financial_accounts WHERE source = ? AND item_key = ?",
            (source, item_key),
        )
    return len(seen)


def upsert_plaid_item(conn, item_key: str, item_id: str, *,
                      institution_id: str = "", institution_name: str = "") -> None:
    conn.execute(
        """INSERT INTO plaid_items (item_key, item_id, institution_id, institution_name)
           VALUES (?,?,?,?)
           ON CONFLICT(item_key) DO UPDATE SET item_id=excluded.item_id,
             institution_id=excluded.institution_id,
             institution_name=excluded.institution_name,
             cursor='', updated_at=datetime('now', 'localtime')""",
        (item_key, item_id, institution_id, institution_name),
    )


def plaid_item(conn, item_key: str) -> dict | None:
    row = conn.execute("SELECT * FROM plaid_items WHERE item_key = ?", (item_key,)).fetchone()
    return dict(row) if row else None


def update_plaid_cursor(conn, item_key: str, cursor: str) -> None:
    conn.execute(
        "UPDATE plaid_items SET cursor = ?, updated_at=datetime('now', 'localtime') WHERE item_key = ?",
        (cursor, item_key),
    )


def upsert_plaid_transaction(conn, item_key: str, transaction_id: str,
                             values: dict) -> bool:
    """Insert or replace one transaction; returns True only for a new row."""
    row = conn.execute(
        "SELECT transaction_row_id FROM plaid_transaction_rows WHERE item_key = ? AND transaction_id = ?",
        (item_key, transaction_id),
    ).fetchone()
    params = (
        values["date"], values["description"], values["amount"], values["category"],
        values["account"], values["hash"], values["source"], values.get("account_key", ""),
    )
    if row:
        conn.execute(
            """UPDATE transactions SET date=?, description=?, amount=?, category=?, account=?, hash=?, source=?, account_key=?
               WHERE id=?""",
            (*params, row["transaction_row_id"]),
        )
        return False
    cur = conn.execute(
        """INSERT INTO transactions (date, description, amount, category, account, hash, source, account_key)
           VALUES (?,?,?,?,?,?,?,?)""",
        params,
    )
    conn.execute(
        "INSERT INTO plaid_transaction_rows (item_key, transaction_id, transaction_row_id) VALUES (?,?,?)",
        (item_key, transaction_id, cur.lastrowid),
    )
    return True


def remove_plaid_transaction(conn, item_key: str, transaction_id: str) -> None:
    row = conn.execute(
        "SELECT transaction_row_id FROM plaid_transaction_rows WHERE item_key = ? AND transaction_id = ?",
        (item_key, transaction_id),
    ).fetchone()
    if not row:
        return
    conn.execute("DELETE FROM transactions WHERE id = ?", (row["transaction_row_id"],))
    conn.execute(
        "DELETE FROM plaid_transaction_rows WHERE item_key = ? AND transaction_id = ?",
        (item_key, transaction_id),
    )


def financial_accounts(conn, *, source_prefix: str | None = None) -> list[dict]:
    q = ("SELECT source, institution, name, type, subtype, mask, current_balance, "
         "available_balance, credit_limit, currency, as_of, external_id, item_key, "
         "color, icon "
         "FROM financial_accounts")
    args: tuple = ()
    if source_prefix:
        q += " WHERE source LIKE ?"
        args = (f"{source_prefix}%",)
    q += " ORDER BY institution, type, name"
    return rows_to_dicts(conn.execute(q, args).fetchall())


# Plaid's own sign convention: a credit/loan current_balance is a positive
# amount OWED, never negative. Net worth therefore subtracts these types
# rather than summing every balance -- summing them would count debt as an
# asset.
_NET_WORTH_LIABILITY_TYPES = frozenset({"credit", "loan"})


def net_worth(conn) -> float | None:
    """SPEC-v37 §8.4: assets minus liabilities across every linked account,
    the one net worth computation every caller shares (D5) -- read_accounts
    (agents/runner.py) and Fury's live state (_live_state_finance_line) both
    call this rather than each summing balances their own, slightly
    different way. None only when there is no account data at all yet, so a
    genuinely $0 net worth is never confused with "nothing to show"."""
    accounts = financial_accounts(conn)
    if not accounts:
        return None
    total = 0.0
    for a in accounts:
        balance = a.get("current_balance")
        if balance is None:
            continue
        total += -balance if a.get("type") in _NET_WORTH_LIABILITY_TYPES else balance
    return round(total, 2)


def record_balance_snapshot(conn, source: str, external_id: str, date: str,
                            current: float | None, available: float | None) -> None:
    """Idempotent: calling this twice with the same (source, external_id, date)
    updates the same row in place rather than adding a second one."""
    conn.execute(
        """INSERT INTO balance_snapshots (source, external_id, date, current, available)
           VALUES (?,?,?,?,?)
           ON CONFLICT(source, external_id, date) DO UPDATE SET
             current=excluded.current, available=excluded.available""",
        (source, external_id, date, current, available),
    )


def account_snapshots(conn, source: str, external_id: str, days: int = 90) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT * FROM balance_snapshots
           WHERE source = ? AND external_id = ?
             AND date >= date('now', 'localtime', ?)
           ORDER BY date""",
        (source, external_id, f"-{int(days)} days"),
    ).fetchall())


def upsert_card_liabilities(conn, source: str, external_id: str, *,
                            statement_balance: float | None = None,
                            minimum_payment: float | None = None,
                            due_date: str | None = None,
                            apr: float | None = None,
                            is_overdue: bool = False) -> None:
    """Publish a provider's current card-liability snapshot. Never touches
    alerted_at: that fire-once guard belongs to mark_card_alerted alone."""
    conn.execute(
        """INSERT INTO card_liabilities
           (source, external_id, statement_balance, minimum_payment, due_date, apr, is_overdue)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(source, external_id) DO UPDATE SET
             statement_balance=excluded.statement_balance,
             minimum_payment=excluded.minimum_payment,
             due_date=excluded.due_date, apr=excluded.apr,
             is_overdue=excluded.is_overdue, updated_at=datetime('now', 'localtime')""",
        (source, external_id, statement_balance, minimum_payment, due_date, apr, int(bool(is_overdue))),
    )


def card_liability(conn, source: str, external_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM card_liabilities WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return dict(row) if row else None


def due_cards_for_alert(conn, *, within_days: int = 5) -> list[dict]:
    """Candidate card payments to alert on: never-alerted, a real statement
    balance, and a due date at or before the window. This does not push
    anything itself (core/db.py stays a pure data layer); a separate
    loader/orchestrator calls push and then mark_card_alerted.

    The due-date window is Python date math, not SQL date functions,
    mirroring core/promises.py's documented preference for pure Python over
    complex SQLite date comparisons.
    """
    rows = conn.execute(
        """SELECT cl.*, fa.institution, fa.name, fa.mask
           FROM card_liabilities cl
           JOIN financial_accounts fa
             ON fa.source = cl.source AND fa.external_id = cl.external_id
           WHERE cl.statement_balance > 0 AND cl.alerted_at IS NULL
             AND cl.due_date IS NOT NULL AND cl.due_date != ''"""
    ).fetchall()
    cutoff = date.today() + timedelta(days=int(within_days))
    due = []
    for row in rows:
        r = dict(row)
        try:
            due_date = date.fromisoformat(str(r["due_date"])[:10])
        except ValueError:
            continue
        if due_date <= cutoff:
            due.append(r)
    due.sort(key=lambda r: r["due_date"])
    return due


def mark_card_alerted(conn, source: str, external_id: str) -> None:
    """Fire-once guard: stamp on fire, never on a later 'success' concept
    (core/promises.py's documented law)."""
    conn.execute(
        "UPDATE card_liabilities SET alerted_at = datetime('now', 'localtime') "
        "WHERE source = ? AND external_id = ?",
        (source, external_id),
    )


# ----------------------------------------------------------- documents

def add_document(conn, name: str, path: str = "", kind: str = "contract",
                 notes: str = "") -> int:
    """Register a document for counsel review (status 'pending' trips the
    tripwire). Dedup on (name, path): an existing row's id is returned."""
    row = conn.execute(
        "SELECT id FROM documents WHERE name = ? AND path = ?",
        (name.strip(), path.strip()),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO documents (name, path, kind, notes) VALUES (?,?,?,?)",
        (name.strip(), path.strip(), kind.strip() or "contract", notes.strip()),
    )
    conn.commit()
    return cur.lastrowid


def all_documents(conn, limit: int = 20) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT id, name, path, kind, status, notes, created_at FROM documents ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall())


# ----------------------------------------------------------- money math

def recent_transactions(conn, days: int = 60) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM transactions WHERE date >= date('now', 'localtime', ?) ORDER BY date DESC, id DESC",
        (f"-{int(days)} days",),
    ).fetchall())


def _active_budget_category_rows(conn) -> list[dict]:
    """Non-archived budget_categories rows, each with `categories` parsed
    from its JSON column into a list. SPEC-v30 Phase 3: this is the one
    read path burn_by_month/month_burn_detail/active_budget_cap share, so
    the table (not BUSINESS_CATEGORIES) is the single source of truth.
    """
    rows = rows_to_dicts(conn.execute(
        "SELECT id, name, cap, categories, color FROM budget_categories "
        "WHERE archived = 0 ORDER BY id"
    ).fetchall())
    for row in rows:
        try:
            row["categories"] = json.loads(row["categories"]) or []
        except (TypeError, ValueError):
            row["categories"] = []
    return rows


def _budget_burn_categories(conn) -> set[str]:
    """The union of transactions.category values every active budget
    category groups. Falls back to the pre-SPEC-v30 hardcoded set only if
    every budget_categories row has been archived (a fresh DB always seeds
    one row, so this is defensive, not the normal path).
    """
    rows = _active_budget_category_rows(conn)
    if not rows:
        return set(BUSINESS_CATEGORIES)
    cats: set[str] = set()
    for row in rows:
        cats.update(row["categories"])
    return cats


def active_budget_cap(conn) -> float:
    """The cap the Money page's burn hero/meter renders against, read from
    budget_categories instead of a hardcoded literal (SPEC-v30 Phase 3: the
    third copy of `150`, alongside BUSINESS_CATEGORIES and MoneyPage.jsx's
    own defaults, all now trace to this one table). Sums every active row's
    cap, so adding a second budget line raises the combined cap the same
    way adding its categories raises the combined burn total below.
    """
    rows = _active_budget_category_rows(conn)
    if not rows:
        return 150.0
    return round(sum(float(row["cap"]) for row in rows), 2)


def _budget_rule_keyword_map(conn) -> list[tuple[str, str]]:
    """(lowercased keyword, owning budget_categories.name) pairs for every
    rule whose category is still active, ordered by category id then rule
    id so the first substring match wins deterministically -- the same
    first-match style ingest/categorize.py's categorize() uses for
    KEYWORD_CATEGORIES, mirrored here rather than imported: that function
    is the write-time categorizer for one flat dict, this is a read-time
    aggregation over Ian's own budget_rules and must never touch
    transactions.category.
    """
    rows = conn.execute(
        """SELECT r.keyword, c.name FROM budget_rules r
           JOIN budget_categories c ON c.id = r.category_id
           WHERE c.archived = 0
           ORDER BY c.id, r.id"""
    ).fetchall()
    return [(str(r["keyword"]).lower(), r["name"]) for r in rows if r["keyword"]]


def _budget_rule_matches(conn, month: str = "") -> list[dict]:
    """category='' transactions matched to a budget category by keyword,
    same lowercase-substring/first-match semantics as categorize(). Rules
    apply ONLY to category='' rows (the WHERE clause below), so a personal
    rule can never poach an already-categorized business transaction --
    and nothing here ever writes transactions.category back. Returns one
    {name, date, amount} dict per matched transaction.
    """
    keyword_map = _budget_rule_keyword_map(conn)
    if not keyword_map:
        return []
    where = "amount < 0 AND category = ''"
    params: list = []
    if month:
        where += " AND substr(date, 1, 7) = ?"
        params.append(month)
    rows = conn.execute(
        f"SELECT date, description, amount FROM transactions WHERE {where}", params,
    ).fetchall()
    matched = []
    for row in rows:
        low = (row["description"] or "").lower()
        name = next((n for kw, n in keyword_map if kw in low), None)
        if name:
            matched.append({"name": name, "date": row["date"], "amount": row["amount"]})
    return matched


def burn_by_month(conn, months: int = 3) -> list[dict]:
    categories = _budget_burn_categories(conn)
    by_month: dict[str, dict] = {}
    if categories:
        placeholders = ",".join("?" for _ in categories)
        rows = conn.execute(
            f"""SELECT substr(date, 1, 7) AS month,
                       ROUND(SUM(-amount), 2) AS burn,
                       COUNT(*) AS txn_count
                FROM transactions
                WHERE amount < 0 AND category IN ({placeholders})
                GROUP BY month""",
            (*categories,),
        ).fetchall()
        for r in rows:
            by_month[r["month"]] = {"month": r["month"], "burn": r["burn"], "txn_count": r["txn_count"]}
    # budget_rules matches (personal spend rules against category='' rows)
    # fold into the same monthly total, so a future personal budget line
    # genuinely raises "burn" instead of sitting decorative and unread.
    for m in _budget_rule_matches(conn):
        month = m["date"][:7]
        entry = by_month.setdefault(month, {"month": month, "burn": 0.0, "txn_count": 0})
        entry["burn"] = round(entry["burn"] + (-m["amount"]), 2)
        entry["txn_count"] += 1
    return sorted(by_month.values(), key=lambda d: d["month"], reverse=True)[:months]


def month_burn_detail(conn, month: str) -> list[dict]:
    categories = _budget_burn_categories(conn)
    rows: list[dict] = []
    if categories:
        placeholders = ",".join("?" for _ in categories)
        rows = rows_to_dicts(conn.execute(
            f"""SELECT category, ROUND(SUM(-amount), 2) AS spent, COUNT(*) AS n
                FROM transactions
                WHERE amount < 0 AND category IN ({placeholders}) AND substr(date,1,7) = ?
                GROUP BY category""",
            (*categories, month),
        ).fetchall())
    # Rule-matched category='' rows group under the owning budget category's
    # NAME (there is no real transactions.category to show for a blank row);
    # this can never collide with a real category row above since a real
    # category is never the empty string.
    rule_totals: dict[str, dict] = {}
    for m in _budget_rule_matches(conn, month):
        entry = rule_totals.setdefault(m["name"], {"category": m["name"], "spent": 0.0, "n": 0})
        entry["spent"] = round(entry["spent"] + (-m["amount"]), 2)
        entry["n"] += 1
    rows.extend(rule_totals.values())
    rows.sort(key=lambda r: r["spent"], reverse=True)
    return rows


# ------------------------------------------------- budget categories (manage UI)
# SPEC-v30 Phase 3.5: read/write surface behind BudgetCategorySheet.jsx. The
# burn-affecting read path above (_active_budget_category_rows/burn_by_month/
# month_burn_detail/active_budget_cap) is untouched; everything below is Ian's
# own CRUD over the same table, still never writing transactions.category.

def distinct_transaction_categories(conn) -> list[str]:
    """Every non-blank transactions.category value that actually exists.
    This is the closed set BudgetCategorySheet's checklist offers and
    create/update_budget_category validate `categories` against -- Ian picks
    from what's real, never free text that silently matches nothing.
    """
    rows = conn.execute(
        "SELECT DISTINCT category FROM transactions WHERE category != '' ORDER BY category"
    ).fetchall()
    return [r["category"] for r in rows]


def _clean_rule_keywords(rules: list[str] | None) -> list[str]:
    """Trim, drop blanks, and de-dupe case-insensitively while preserving the
    first-seen casing -- matching semantics stay lowercase-substring at match
    time (_budget_rule_keyword_map already lowercases on read).
    """
    if not rules:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for kw in rules:
        cleaned = str(kw or "").strip()
        low = cleaned.lower()
        if not cleaned or low in seen:
            continue
        seen.add(low)
        out.append(cleaned)
    return out


def _budget_category_row(conn, category_id: int) -> dict | None:
    """One budget_categories row (any archived state) plus its budget_rules
    keywords, parsed for API/UI consumption. The one shape POST/PATCH return."""
    row = conn.execute(
        "SELECT id, name, cap, categories, color, archived, created_at, updated_at "
        "FROM budget_categories WHERE id = ?", (category_id,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["categories"] = json.loads(item.get("categories") or "[]") or []
    except (TypeError, ValueError):
        item["categories"] = []
    item["archived"] = bool(item["archived"])
    item["rules"] = [r["keyword"] for r in conn.execute(
        "SELECT keyword FROM budget_rules WHERE category_id = ? ORDER BY id", (category_id,),
    ).fetchall()]
    return item


def list_budget_categories(conn) -> list[dict]:
    """Active (non-archived) budget_categories rows, each with its own
    this-month spend, for the manage-budgets list view. Spend is read off
    month_burn_detail's already-computed per-real-category and per-rule
    totals (single source of truth with burn_by_month), not a second
    aggregation query: a row's spend is the sum of every detail entry whose
    category is one of this row's `categories`, plus the entry (if any)
    keyed by this row's own name (that's where its budget_rules matches
    land, per month_burn_detail's rule_totals bucket).
    """
    rows = rows_to_dicts(conn.execute(
        "SELECT id, name, cap, categories, color, archived, created_at, updated_at "
        "FROM budget_categories WHERE archived = 0 ORDER BY id"
    ).fetchall())
    month = today()[:7]
    detail = month_burn_detail(conn, month)
    out = []
    for row in rows:
        try:
            row["categories"] = json.loads(row.get("categories") or "[]") or []
        except (TypeError, ValueError):
            row["categories"] = []
        row["archived"] = bool(row["archived"])
        row["rules"] = [r["keyword"] for r in conn.execute(
            "SELECT keyword FROM budget_rules WHERE category_id = ? ORDER BY id", (row["id"],),
        ).fetchall()]
        matched = [d for d in detail if d["category"] in row["categories"] or d["category"] == row["name"]]
        row["spent_this_month"] = round(sum(d["spent"] for d in matched), 2)
        row["txn_count_this_month"] = sum(d["n"] for d in matched)
        out.append(row)
    return out


def create_budget_category(conn, *, name: str, cap, categories: list[str] | None = None,
                           color: str = "", rules: list[str] | None = None) -> dict:
    """The one writer for a new budget_categories row. `categories` must be a
    subset of distinct_transaction_categories(conn); `rules` are optional
    budget_rules keyword rows created in the same transaction. Raises
    ValueError (a 422 at the API boundary) for any of: blank name, cap <= 0,
    a name collision among non-archived rows, or a category not in the live
    set.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    try:
        cap_val = float(cap)
    except (TypeError, ValueError):
        raise ValueError("cap must be a number") from None
    if cap_val <= 0:
        raise ValueError("cap must be greater than 0")
    dupe = conn.execute(
        "SELECT 1 FROM budget_categories WHERE name = ? AND archived = 0", (name,),
    ).fetchone()
    if dupe:
        raise ValueError(f'a budget category named "{name}" already exists')
    cats = list(categories or [])
    live = set(distinct_transaction_categories(conn))
    bad = sorted(c for c in cats if c not in live)
    if bad:
        raise ValueError(f"unknown transaction categories: {', '.join(bad)}")
    try:
        cur = conn.execute(
            "INSERT INTO budget_categories (name, cap, categories, color) VALUES (?,?,?,?)",
            (name, cap_val, json.dumps(cats, separators=(",", ":")), color or ""),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(f'a budget category named "{name}" already exists') from exc
    category_id = cur.lastrowid
    for keyword in _clean_rule_keywords(rules):
        conn.execute(
            "INSERT INTO budget_rules (category_id, keyword) VALUES (?,?)", (category_id, keyword),
        )
    conn.commit()
    return _budget_category_row(conn, category_id)


def update_budget_category(conn, category_id: int, **fields) -> dict | None:
    """Partial update of one budget_categories row, or a soft-delete via
    archived=True -- matching goals.archived, never a hard DELETE (partner_tasks'
    deleted_at/deleted_batch_id is a different mechanism and is not the
    precedent here). `rules`, when provided, fully replaces this category's
    budget_rules keyword set in the same transaction (delete-then-insert),
    the same "whole array, not a diff" shape `categories` already uses.
    Returns None (a 404 at the API boundary) if no such row exists.
    """
    existing = _budget_category_row(conn, category_id)
    if existing is None:
        return None
    unknown = set(fields) - {"name", "cap", "categories", "color", "archived", "rules"}
    if unknown:
        raise ValueError(f"unknown budget_categories field: {sorted(unknown)[0]}")
    sets: list[str] = []
    params: list = []
    if "name" in fields:
        name = (fields["name"] or "").strip()
        if not name:
            raise ValueError("name is required")
        dupe = conn.execute(
            "SELECT 1 FROM budget_categories WHERE name = ? AND archived = 0 AND id != ?",
            (name, category_id),
        ).fetchone()
        if dupe:
            raise ValueError(f'a budget category named "{name}" already exists')
        sets.append("name=?")
        params.append(name)
    if "cap" in fields:
        try:
            cap_val = float(fields["cap"])
        except (TypeError, ValueError):
            raise ValueError("cap must be a number") from None
        if cap_val <= 0:
            raise ValueError("cap must be greater than 0")
        sets.append("cap=?")
        params.append(cap_val)
    if "categories" in fields:
        cats = list(fields["categories"] or [])
        live = set(distinct_transaction_categories(conn))
        bad = sorted(c for c in cats if c not in live)
        if bad:
            raise ValueError(f"unknown transaction categories: {', '.join(bad)}")
        sets.append("categories=?")
        params.append(json.dumps(cats, separators=(",", ":")))
    if "color" in fields:
        sets.append("color=?")
        params.append(fields["color"] or "")
    if "archived" in fields:
        sets.append("archived=?")
        params.append(1 if fields["archived"] else 0)
    if sets:
        sets.append("updated_at=datetime('now','localtime')")
        params.append(category_id)
        try:
            conn.execute(
                f"UPDATE budget_categories SET {', '.join(sets)} WHERE id=?", params,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("a budget category with that name already exists") from exc
    if "rules" in fields:
        conn.execute("DELETE FROM budget_rules WHERE category_id = ?", (category_id,))
        for keyword in _clean_rule_keywords(fields["rules"]):
            conn.execute(
                "INSERT INTO budget_rules (category_id, keyword) VALUES (?,?)", (category_id, keyword),
            )
    conn.commit()
    return _budget_category_row(conn, category_id)


def cash_position(conn) -> dict:
    """SPEC-v37 §8.4: a rolling 30-day net flow over the real, linked account
    set. The old query summed every transaction since the first CSV import
    (May, seeded demo rows included) with no window at all, which is how
    two small balances turned into "~$81 months of runway" -- not a real number,
    just SUM(amount) since forever. account_key is only populated by a real
    sync (ingest/sync_plaid.py, sync_chase.py, sync_fidelity.py); the legacy
    CSV/seed rows never got one, so filtering on it excludes exactly the rows
    that made the old total meaningless."""
    since = (date.today() - timedelta(days=30)).isoformat()
    row = conn.execute(
        """SELECT ROUND(SUM(amount), 2) AS net FROM transactions
           WHERE date >= ? AND account_key != ''""",
        (since,),
    ).fetchone()
    return {"net_flow_30d": row["net"] or 0.0, "since": since}


def _txn_filter(account_key: str = "", category: str = "", q: str = "",
                month: str = "") -> tuple[str, list]:
    """One WHERE builder shared by list_transactions and count_transactions.

    They MUST stay in lockstep: if the count ignores a filter the list
    applies, the pager reports a total it can never reach and pages into an
    empty view (the _lead_filter precedent).
    """
    where, params = ["1=1"], []
    for col, val in (("account_key", account_key), ("category", category)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    if q:
        where.append("LOWER(description) LIKE ?")
        params.append(f"%{q.lower()}%")
    if month:
        where.append("date LIKE ?")
        params.append(f"{month}%")
    return " AND ".join(where), params


def list_transactions(conn, account_key: str = "", category: str = "", q: str = "",
                      month: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    where, params = _txn_filter(account_key, category, q, month)
    return rows_to_dicts(conn.execute(
        f"""SELECT * FROM transactions WHERE {where}
            ORDER BY date DESC, id DESC
            LIMIT ? OFFSET ?""",
        (*params, int(limit), int(offset)),
    ).fetchall())


def count_transactions(conn, account_key: str = "", category: str = "", q: str = "",
                       month: str = "") -> dict:
    where, params = _txn_filter(account_key, category, q, month)
    row = conn.execute(
        f"""SELECT COUNT(*) AS total,
                   ROUND(COALESCE(SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END), 0), 2) AS sum_in,
                   ROUND(COALESCE(SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END), 0), 2) AS sum_out
            FROM transactions WHERE {where}""",
        tuple(params),
    ).fetchone()
    return {"total": row["total"], "sum_in": row["sum_in"], "sum_out": row["sum_out"]}


def get_transaction(conn, transaction_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (int(transaction_id),)
    ).fetchone()
    return dict(row) if row else None


def recategorize_transaction(conn, transaction_id: int, category: str,
                              commit: bool = True) -> dict | None:
    """Touches `category` only, never amount/date/account/hash/source (SPEC-v37
    §4.2 Ring 1 `transaction.recategorize`). `transactions` otherwise has
    exactly one writer per row, the bank CSV / SimpleFIN / SnapTrade loaders
    (core data law D2): this is a narrow, spec-authorized exception for a
    label, the same shape as `financial_accounts.color`/`icon` being Ian's own
    judgment layered on top of the sacred, loader-owned fields."""
    row = get_transaction(conn, transaction_id)
    if row is None:
        return None
    conn.execute(
        "UPDATE transactions SET category = ? WHERE id = ?",
        (category, transaction_id),
    )
    if commit:
        conn.commit()
    return get_transaction(conn, transaction_id)


def financial_account_detail(conn, source: str, external_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM financial_accounts WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    if not row:
        return None
    account_key = f"{source}:{external_id}"
    return {
        **dict(row),
        "liabilities": card_liability(conn, source, external_id),
        "snapshots_90d": account_snapshots(conn, source, external_id, 90),
        "recent_transactions": list_transactions(conn, account_key=account_key, limit=20),
        "holdings": rows_to_dicts(conn.execute(
            "SELECT * FROM holdings WHERE account_key = ? ORDER BY market_value DESC",
            (account_key,),
        ).fetchall()),
    }


def set_account_appearance(conn, source: str, external_id: str, *,
                           color: str | None = None, icon: str | None = None) -> dict | None:
    """Ian's own per-account color/icon choice (SPEC-v30 Phase 2).

    The ONLY function that may write financial_accounts.color/icon.
    Mirrors set_chat_prefs_model's narrow-write shape: validates each
    provided value against its closed set (ACCOUNT_COLORS/ACCOUNT_ICONS)
    and does one targeted UPDATE. Deliberately never folded into
    upsert_financial_accounts' ON CONFLICT ... DO UPDATE SET column list,
    so the next Plaid/SimpleFIN/SnapTrade sync can never wipe it -- the
    same write-boundary partition CLAUDE.md documents for LEAD_SCRAPED_COLS.

    Returns the refreshed account detail, or None if no such
    (source, external_id) row exists (a 404 at the API boundary, not a
    422: the values themselves were valid).
    """
    sets: list[str] = []
    params: list = []
    if color is not None:
        if color not in ACCOUNT_COLORS:
            raise ValueError(f"unknown account color: {color}")
        sets.append("color=?")
        params.append(color)
    if icon is not None:
        if icon not in ACCOUNT_ICONS:
            raise ValueError(f"unknown account icon: {icon}")
        sets.append("icon=?")
        params.append(icon)
    if not sets:
        return financial_account_detail(conn, source, external_id)
    sets.append("updated_at=datetime('now','localtime')")
    params.extend([source, external_id])
    conn.execute(
        f"UPDATE financial_accounts SET {', '.join(sets)} "
        f"WHERE source = ? AND external_id = ?",
        params,
    )
    conn.commit()
    return financial_account_detail(conn, source, external_id)


# --------------------------------------------------------- partner tasks


class PartnerTaskNotFound(Exception):
    """The requested active task, archive batch, or parent does not exist."""


class PartnerHierarchyConflict(Exception):
    """A requested write would violate the deliberate one-level hierarchy."""


def _partner_dict(row) -> dict:
    task = dict(row)
    task["done"] = bool(task["done"])
    return task


def _next_partner_task_id(conn) -> int:
    row = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'partner_tasks'"
    ).fetchone()
    return int(row["seq"]) + 1 if row is not None else 1


def _begin_partner_write(conn) -> bool:
    """Acquire a writer lock unless a receipt transaction already owns one."""

    owned = not conn.in_transaction
    if owned:
        conn.execute("BEGIN IMMEDIATE")
    return owned


def _finish_partner_write(conn, *, commit: bool, owned: bool) -> None:
    if commit:
        conn.commit()


def _rollback_partner_write(conn, *, owned: bool) -> None:
    if owned and conn.in_transaction:
        conn.rollback()

def all_partner_tasks(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM partner_tasks
           WHERE deleted_at IS NULL
           ORDER BY COALESCE(parent_id, id),
                    CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END,
                    id"""
    ).fetchall()
    return [_partner_dict(row) for row in rows]


def get_partner_task(conn, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM partner_tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)
    ).fetchone()
    return _partner_dict(row) if row else None


def add_partner_task(conn, title: str, notes: str = "", parent_id: int | None = None,
                   commit: bool = True) -> dict:
    owned = _begin_partner_write(conn)
    try:
        clean_title = title.strip()
        if not clean_title:
            raise ValueError("task needs a title")
        if parent_id is not None:
            parent = conn.execute(
                "SELECT id, parent_id, deleted_at FROM partner_tasks WHERE id = ?",
                (parent_id,),
            ).fetchone()
            if parent is None:
                if int(parent_id) == _next_partner_task_id(conn):
                    raise PartnerHierarchyConflict("a task cannot parent itself")
                raise PartnerTaskNotFound("parent task not found")
            if parent["deleted_at"] is not None:
                raise PartnerTaskNotFound("parent task not found")
            if parent["parent_id"] is not None:
                raise PartnerHierarchyConflict("a step cannot have children")

        cur = conn.execute(
            "INSERT INTO partner_tasks (title, notes, parent_id) VALUES (?, ?, ?)",
            (clean_title, notes.strip(), parent_id),
        )
        row = conn.execute(
            "SELECT * FROM partner_tasks WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        _finish_partner_write(conn, commit=commit, owned=owned)
        return _partner_dict(row)
    except Exception:
        _rollback_partner_write(conn, owned=owned)
        raise


def update_partner_task(conn, task_id: int, commit: bool = True, **fields) -> dict | None:
    owned = _begin_partner_write(conn)
    try:
        row = conn.execute(
            "SELECT * FROM partner_tasks WHERE id = ? AND deleted_at IS NULL",
            (task_id,),
        ).fetchone()
        if row is None:
            _finish_partner_write(conn, commit=commit, owned=owned)
            return None
        allowed = {"title", "notes", "done"}
        updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "title" in updates and not str(updates["title"]).strip():
            updates.pop("title")
        if "done" in updates:
            updates["done"] = 1 if updates["done"] else 0
            updates["completed_at"] = now() if updates["done"] else None
        if not updates:
            _finish_partner_write(conn, commit=commit, owned=owned)
            return _partner_dict(row)
        if "title" in updates:
            updates["title"] = str(updates["title"]).strip()
        if "notes" in updates:
            updates["notes"] = str(updates["notes"]).strip()
        conn.execute(
            f"UPDATE partner_tasks SET {', '.join(f'{key}=?' for key in updates)} "
            "WHERE id=? AND deleted_at IS NULL",
            (*updates.values(), task_id),
        )
        out = conn.execute(
            "SELECT * FROM partner_tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)
        ).fetchone()
        _finish_partner_write(conn, commit=commit, owned=owned)
        return _partner_dict(out)
    except Exception:
        _rollback_partner_write(conn, owned=owned)
        raise


def archive_partner_task(conn, task_id: int, batch_id: str, commit: bool = True) -> dict:
    """Archive one active task, or an active parent and its active children."""

    if not str(batch_id).strip():
        raise ValueError("archive batch id is required")
    owned = _begin_partner_write(conn)
    try:
        target = conn.execute(
            "SELECT * FROM partner_tasks WHERE id = ? AND deleted_at IS NULL",
            (task_id,),
        ).fetchone()
        if target is None:
            raise PartnerTaskNotFound("task not found")

        if target["parent_id"] is None:
            rows = conn.execute(
                """SELECT * FROM partner_tasks
                   WHERE deleted_at IS NULL AND (id = ? OR parent_id = ?)
                   ORDER BY CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id""",
                (task_id, task_id),
            ).fetchall()
        else:
            rows = [target]
        archived_ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in archived_ids)
        conn.execute(
            f"""UPDATE partner_tasks
                SET deleted_at = ?, deleted_batch_id = ?
                WHERE deleted_at IS NULL AND id IN ({placeholders})""",
            (now(), batch_id, *archived_ids),
        )
        _finish_partner_write(conn, commit=commit, owned=owned)
        return {
            "archive_batch_id": batch_id,
            "archived_ids": archived_ids,
            "title": target["title"],
            "step_count": len(archived_ids) - 1 if target["parent_id"] is None else 0,
        }
    except Exception:
        _rollback_partner_write(conn, owned=owned)
        raise


def restore_partner_archive(conn, batch_id: str, commit: bool = True) -> list[dict]:
    """Restore exactly one archive batch without creating an active orphan."""

    owned = _begin_partner_write(conn)
    try:
        rows = conn.execute(
            """SELECT * FROM partner_tasks WHERE deleted_batch_id = ?
               ORDER BY COALESCE(parent_id, id),
                        CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id""",
            (batch_id,),
        ).fetchall()
        if not rows:
            raise PartnerTaskNotFound("archive batch not found")
        restoring_ids = {int(row["id"]) for row in rows}
        for row in rows:
            parent_id = row["parent_id"]
            if parent_id is None:
                continue
            parent = conn.execute(
                "SELECT id, parent_id, deleted_at FROM partner_tasks WHERE id = ?",
                (parent_id,),
            ).fetchone()
            if (parent is None or parent["parent_id"] is not None
                    or (parent["deleted_at"] is not None
                        and int(parent["id"]) not in restoring_ids)):
                raise PartnerHierarchyConflict(
                    "restore the parent outcome before restoring this step"
                )

        conn.execute(
            """UPDATE partner_tasks SET deleted_at = NULL, deleted_batch_id = NULL
               WHERE deleted_batch_id = ?""",
            (batch_id,),
        )
        placeholders = ",".join("?" for _ in restoring_ids)
        restored = conn.execute(
            f"""SELECT * FROM partner_tasks WHERE id IN ({placeholders})
                ORDER BY COALESCE(parent_id, id),
                         CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END, id""",
            tuple(sorted(restoring_ids)),
        ).fetchall()
        _finish_partner_write(conn, commit=commit, owned=owned)
        return [_partner_dict(row) for row in restored]
    except Exception:
        _rollback_partner_write(conn, owned=owned)
        raise


# ------------------------------------------------------------------ tasks
# Life's daily to-do (SPEC-v41 §4). Rolling is a READ, never a nightly write:
# tasks_today() is the single read path /api/state, read_tasks, and the
# attention candidate all share. Deletes are soft, the partner_tasks precedent.

def get_task(conn, task_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND deleted_at IS NULL", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def tasks_today(conn, today: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM tasks
           WHERE done_at IS NULL AND deleted_at IS NULL AND due_date <= ?
           ORDER BY due_date ASC, priority DESC, position ASC, id ASC""",
        (today,),
    ).fetchall()
    return [dict(r) for r in rows]


def tasks_done_today(conn, today: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM tasks
           WHERE deleted_at IS NULL AND done_at IS NOT NULL AND date(done_at) = ?
           ORDER BY done_at DESC""",
        (today,),
    ).fetchall()
    return [dict(r) for r in rows]


def create_task(conn, title: str, *, due_date: str | None = None, priority: int = 0,
                 goal_id: int | None = None, source: str = "ian",
                 source_role: str = "", commit: bool = True) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("task needs a title")
    if priority not in (0, 1):
        raise ValueError("priority must be 0 or 1")
    if source not in ("ian", "chat", "agent", "goal_draft"):
        raise ValueError("unknown task source")
    due_date = due_date or today()
    cur = conn.execute(
        """INSERT INTO tasks (title, due_date, priority, goal_id, source, source_role)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (title, due_date, priority, goal_id, source, source_role),
    )
    if commit:
        conn.commit()
    return get_task(conn, cur.lastrowid)


def update_task(conn, task_id: int, commit: bool = True, **fields) -> dict | None:
    allowed = {"title", "due_date", "priority", "goal_id", "position"}
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "title":
            value = str(value).strip()
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return get_task(conn, task_id)
    values.append(task_id)
    conn.execute(
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ? AND deleted_at IS NULL", values
    )
    if commit:
        conn.commit()
    return get_task(conn, task_id)


def set_task_done(conn, task_id: int, done: bool, commit: bool = True) -> dict | None:
    conn.execute(
        "UPDATE tasks SET done_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now() if done else None, task_id),
    )
    if commit:
        conn.commit()
    return get_task(conn, task_id)


def delete_task(conn, task_id: int, commit: bool = True) -> dict | None:
    row = get_task(conn, task_id)
    if row is None:
        return None
    conn.execute("UPDATE tasks SET deleted_at = ? WHERE id = ?", (now(), task_id))
    if commit:
        conn.commit()
    return row


def restore_task(conn, task_id: int, commit: bool = True) -> dict | None:
    conn.execute("UPDATE tasks SET deleted_at = NULL WHERE id = ?", (task_id,))
    if commit:
        conn.commit()
    return get_task(conn, task_id)


def tasks_done_this_week(conn, today_iso: str) -> int:
    d = date.fromisoformat(today_iso)
    monday = d - timedelta(days=d.weekday())
    row = conn.execute(
        """SELECT COUNT(*) n FROM tasks
           WHERE deleted_at IS NULL AND done_at IS NOT NULL AND date(done_at) >= ?""",
        (monday.isoformat(),),
    ).fetchone()
    return row["n"]


def tasks_done_for_goal(conn, goal_id: int) -> tuple[int, int]:
    row = conn.execute(
        """SELECT
             SUM(CASE WHEN done_at IS NOT NULL THEN 1 ELSE 0 END) done,
             COUNT(*) total
           FROM tasks WHERE deleted_at IS NULL AND goal_id = ?""",
        (goal_id,),
    ).fetchone()
    return (row["done"] or 0, row["total"] or 0)


# ---------------------------------------------------------------- facts
# Durable long-term memory (the RAG layer). Scoped by domain; dated facts drive
# the dispatcher's tripwires. Date math is pure Python so leap years stay correct.

def _next_occurrence(date_iso: str | None, recurs: str, ref: date) -> date | None:
    """Next occurrence of a dated fact on/after ref. Yearly recurs project the
    month-day; one-shot dates in the past return None (they don't recur)."""
    if not date_iso:
        return None
    try:
        d = date.fromisoformat(date_iso)
    except (ValueError, TypeError):
        return None
    if recurs != "yearly":
        return d if d >= ref else None

    def _mk(year: int) -> date:
        try:
            return date(year, d.month, d.day)
        except ValueError:            # Feb 29 in a non-leap year → Feb 28
            return date(year, d.month, 28)

    cand = _mk(ref.year)
    if cand < ref:
        cand = _mk(ref.year + 1)
    return cand


def _decorate_fact(f: dict, ref: date) -> dict:
    if f.get("kind") == "date":
        occ = _next_occurrence(f.get("date"), f.get("recurs") or "", ref)
        f["next_occurrence"] = occ.isoformat() if occ else None
        f["days_until"] = (occ - ref).days if occ else None
    else:
        f["next_occurrence"] = None
        f["days_until"] = None
    f["verified"] = bool(f["verified"])
    return f


def _validated_source_memo_ids(conn, source_memo_ids: list[int] | None) -> list[int] | None:
    """Validate a citation replacement before changing either side of a fact.

    `None` means preserve existing citations; an explicit empty list is the
    deliberate Ian/API operation that clears them.  Agents are prevented from
    taking that latter path in their tool handler.
    """
    if source_memo_ids is None:
        return None
    if not isinstance(source_memo_ids, list):
        raise ValueError("source_memo_ids must be a list of memo ids")
    memo_ids: list[int] = []
    for memo_id in source_memo_ids:
        if isinstance(memo_id, bool) or not isinstance(memo_id, int):
            raise ValueError("source_memo_ids must contain integer memo ids")
        if memo_id in memo_ids:
            raise ValueError("source_memo_ids must be unique")
        memo_ids.append(memo_id)
    if not memo_ids:
        return memo_ids
    placeholders = ",".join("?" for _ in memo_ids)
    found = {
        row["id"] for row in conn.execute(
            f"SELECT id FROM memos WHERE id IN ({placeholders})", memo_ids
        )
    }
    missing = [memo_id for memo_id in memo_ids if memo_id not in found]
    if missing:
        raise ValueError(f"source memo id {missing[0]} does not exist")
    return memo_ids


def _fact_source_ids(conn, fact_id: int) -> list[int]:
    return [
        row["memo_id"]
        for row in conn.execute(
            "SELECT memo_id FROM fact_sources WHERE fact_id=? ORDER BY memo_id", (fact_id,)
        )
    ]


def _fact_source_projections(conn, fact_ids: list[int]) -> dict[int, str]:
    """Return canonical compatibility strings without exposing source bodies."""
    projections = {int(fact_id): "" for fact_id in fact_ids}
    if not projections:
        return projections
    ids = list(projections)
    placeholders = ",".join("?" for _ in ids)
    grouped: dict[int, list[str]] = {fact_id: [] for fact_id in ids}
    for row in conn.execute(
        f"""SELECT fact_id, memo_id FROM fact_sources
            WHERE fact_id IN ({placeholders})
            ORDER BY fact_id, memo_id""",
        ids,
    ):
        grouped[row["fact_id"]].append(str(row["memo_id"]))
    return {fact_id: ",".join(source_ids) for fact_id, source_ids in grouped.items()}


def _sync_fact_source_projection(conn, fact_id: int) -> str:
    """Keep the retired serialized compatibility field exactly in sync."""
    projection = ",".join(str(memo_id) for memo_id in _fact_source_ids(conn, fact_id))
    conn.execute("UPDATE facts SET source_memo_ids=? WHERE id=?", (projection, fact_id))
    return projection


def _replace_fact_sources(conn, fact_id: int, memo_ids: list[int]) -> None:
    # `_validated_source_memo_ids` runs before this destructive replacement.
    conn.execute("DELETE FROM fact_sources WHERE fact_id=?", (fact_id,))
    conn.executemany(
        "INSERT INTO fact_sources (fact_id, memo_id) VALUES (?, ?)",
        [(fact_id, memo_id) for memo_id in memo_ids],
    )
    _sync_fact_source_projection(conn, fact_id)


def upsert_fact(conn, domain: str, topic: str, body: str, kind: str = "fact",
                date: str | None = None, recurs: str = "", source_role: str = "",
                source_memo_ids: list[int] | None = None, verified: int = 0,
                commit: bool = True, evidence: object = None,
                require_evidence: bool = False,
                allowed_read_tools: set[str] | frozenset[str] | None = None,
                role_domains: list[str] | tuple[str, ...] | None = None) -> int:
    """Create/update a durable fact without silently erasing its evidence.

    SPEC-v37 §5.2 Law A6: a model-written fact is born unverified. Six of the
    facts table's seventeen rows were fabricated and trusted as ground truth
    before this flip -- the two callers that legitimately know a fact is
    verified (a connector sync, Ian's own edit via the Memory page) already
    pass `verified=` explicitly and are unaffected.

    `require_evidence=True` (write_fact's tool path only) additionally
    demands at least one `evidence` reference server-side resolvable against
    a real goal/fact/document/memo row -- the same resolution
    `create_proposal` already does for proposal evidence, reused rather than
    reimplemented. Not persisted anywhere new: `source_memo_ids` (via
    `fact_sources`) already carries the citation trail this only gates.
    """
    if require_evidence:
        resolved = _resolve_evidence_list(
            conn, evidence or [], allowed_read_tools=allowed_read_tools,
            role_domains=role_domains, label="evidence",
        )
        if not resolved:
            raise ValueError("write_fact requires at least one resolvable evidence reference")
    memo_ids = _validated_source_memo_ids(conn, source_memo_ids)
    try:
        conn.execute(
            """INSERT INTO facts (domain, topic, body, kind, date, recurs,
                 source_role, source_memo_ids, verified)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(domain, topic) DO UPDATE SET
                 body=excluded.body, kind=excluded.kind, date=excluded.date,
                 recurs=excluded.recurs, source_role=excluded.source_role,
                 verified=excluded.verified,
                 updated_at=datetime('now', 'localtime')""",
            (domain, topic, body, kind, date, recurs, source_role,
             "", 1 if verified else 0),
        )
        fact_id = conn.execute(
            "SELECT id FROM facts WHERE domain=? AND topic=?", (domain, topic)
        ).fetchone()["id"]
        if memo_ids is None:
            _sync_fact_source_projection(conn, fact_id)
        else:
            _replace_fact_sources(conn, fact_id, memo_ids)
        if commit:
            conn.commit()
        return fact_id
    except Exception:
        if commit and conn.in_transaction:
            conn.rollback()
        raise


def _decorate_fact_row(conn, row: sqlite3.Row | dict, ref: date) -> dict:
    fact = dict(row)
    fact["source_memo_ids"] = _fact_source_projections(conn, [fact["id"]])[fact["id"]]
    return _decorate_fact(fact, ref)


def get_fact(conn, fact_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
    return _decorate_fact_row(conn, row, date.today()) if row else None


def set_fact_verified(conn, fact_id: int, verified: int, commit: bool = True) -> dict | None:
    """Narrow write path for `verified` only, used by Ring 1 `fact.flag_unverified`
    (SPEC-v37 §4.2) and its undo. Deliberately bypasses `update_fact`'s
    general-purpose field set: the act itself may only ever call this with
    verified=0 (a caller-side guard, not enforced here), and undo needs to be
    able to restore verified=1 even though the forward act never can."""
    row = get_fact(conn, fact_id)
    if row is None:
        return None
    conn.execute(
        "UPDATE facts SET verified=?, updated_at=datetime('now','localtime') WHERE id=?",
        (1 if verified else 0, fact_id),
    )
    if commit:
        conn.commit()
    return get_fact(conn, fact_id)


def fact_sources_for_fact(conn, fact_id: int, limit: int = 50) -> list[dict]:
    """Bounded evidence lookup for the authenticated fact-detail endpoint."""
    limit = max(1, min(int(limit), 100))
    rows = conn.execute(
        """SELECT m.id, m.from_role, m.topic, m.body, m.created_at, m.archived
           FROM fact_sources AS fs
           JOIN memos AS m ON m.id = fs.memo_id
           WHERE fs.fact_id=?
           ORDER BY m.created_at ASC, m.id ASC
           LIMIT ?""",
        (fact_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "from_role": row["from_role"],
            "topic": row["topic"],
            "body": row["body"],
            "created_at": row["created_at"],
            "archived": bool(row["archived"]),
        }
        for row in rows
    ]


def facts_for_domains(conn, domains: list[str], limit: int = 80) -> list[dict]:
    """Facts for the given domains, dated (nearest-first) then most-recently-updated.
    'all' in domains → every fact."""
    ref = date.today()
    if not domains or "all" in domains:
        rows = conn.execute("SELECT * FROM facts").fetchall()
    else:
        ph = ",".join("?" for _ in domains)
        rows = conn.execute(f"SELECT * FROM facts WHERE domain IN ({ph})", tuple(domains)).fetchall()
    projections = _fact_source_projections(conn, [row["id"] for row in rows])
    facts = []
    for row in rows:
        fact = dict(row)
        fact["source_memo_ids"] = projections[fact["id"]]
        facts.append(_decorate_fact(fact, ref))
    dated = sorted([f for f in facts if f["days_until"] is not None], key=lambda f: f["days_until"])
    undated = sorted([f for f in facts if f["days_until"] is None],
                     key=lambda f: f.get("updated_at") or "", reverse=True)
    return (dated + undated)[:limit]


def list_facts(conn, domain: str | None = None, limit: int = 500) -> list[dict]:
    return facts_for_domains(conn, [domain] if domain else ["all"], limit=limit)


def list_shared_facts(conn, limit: int = 500) -> list[dict]:
    """Fact projection permitted in broad dashboard state.

    The generic Facts surface predates private health insights. Keep any
    historic health-domain fact (or a fact written by an old health role) out
    of the broadly cached state; Body has its own authenticated no-store route.
    """
    rows = list_facts(conn, limit=limit)
    return [
        row for row in rows
        if row.get("domain") != "health"
        and row.get("source_role") not in PRIVATE_HEALTH_MEMO_ROLES
    ]


def upcoming_dated_facts(conn, within_days: int, domains: list[str] | None = None,
                         topic_prefix: str = "") -> list[dict]:
    """Every kind='date' fact whose next occurrence is within `within_days`."""
    ref = date.today()
    rows = conn.execute("SELECT * FROM facts WHERE kind='date'").fetchall()
    projections = _fact_source_projections(conn, [row["id"] for row in rows])
    out = []
    for r in rows:
        f = dict(r)
        f["source_memo_ids"] = projections[f["id"]]
        if domains and "all" not in domains and f["domain"] not in domains:
            continue
        if topic_prefix and not f["topic"].startswith(topic_prefix):
            continue
        occ = _next_occurrence(f.get("date"), f.get("recurs") or "", ref)
        if occ is None:
            continue
        du = (occ - ref).days
        if 0 <= du <= within_days:
            f["next_occurrence"] = occ.isoformat()
            f["days_until"] = du
            f["verified"] = bool(f["verified"])
            out.append(f)
    out.sort(key=lambda x: x["days_until"])
    return out


def update_fact(conn, fact_id: int, **fields) -> dict | None:
    row = conn.execute("SELECT * FROM facts WHERE id=?", (fact_id,)).fetchone()
    if row is None:
        return None
    source_sentinel = object()
    source_arg = fields.pop("source_memo_ids", source_sentinel)
    memo_ids = (
        _validated_source_memo_ids(conn, source_arg)
        if source_arg is not source_sentinel else None
    )
    allowed = {"body", "verified", "date", "kind"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "verified" in updates:
        updates["verified"] = 1 if updates["verified"] else 0
    if "body" in updates:
        updates["body"] = str(updates["body"]).strip()
    try:
        if updates:
            cols = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE facts SET {cols}, updated_at=datetime('now','localtime') WHERE id=?",
                (*updates.values(), fact_id),
            )
        if source_arg is not source_sentinel and memo_ids is not None:
            _replace_fact_sources(conn, fact_id, memo_ids)
        elif updates:
            _sync_fact_source_projection(conn, fact_id)
        if updates or (source_arg is not source_sentinel and memo_ids is not None):
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    return get_fact(conn, fact_id)


def delete_fact(conn, fact_id: int) -> bool:
    cur = conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
    conn.commit()
    return cur.rowcount > 0


# ------------------------------------------------------------- content log

def add_content(conn, day: str, platform: str, item: str, url: str = "", notes: str = "") -> dict:
    cur = conn.execute(
        "INSERT INTO content_log (date, platform, item, url, notes) VALUES (?,?,?,?,?)",
        (day, platform.strip(), item.strip(), url.strip(), notes.strip()),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM content_log WHERE id=?", (cur.lastrowid,)).fetchone())


def recent_content(conn, days: int = 30) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM content_log WHERE date >= date('now', 'localtime', ?) ORDER BY date DESC, id DESC",
        (f"-{int(days)} days",),
    ).fetchall())


def content_by_platform(conn, days: int = 30) -> dict[str, int]:
    rows = conn.execute(
        """SELECT platform, COUNT(*) AS n FROM content_log
           WHERE date >= date('now', 'localtime', ?) GROUP BY platform""",
        (f"-{int(days)} days",),
    ).fetchall()
    return {r["platform"]: r["n"] for r in rows}


# ------------------------------------------------------------------ leads
# SPEC-v9. ingest/import_leads.py is the only bulk writer; the API writes only
# through add_touch / update_lead / delete_touch.

# Columns the importer refreshes from a re-scrape. Everything NOT in this list
# (stage, attempts, last_touch, next_touch, notes) belongs to Ian and survives.
LEAD_SCRAPED_COLS = (
    "phone", "business_name", "owner_name", "email", "city", "state", "market",
    "segment", "service_type", "tier", "fit", "pain", "reach", "total", "why",
    "miss_signal", "claims_247", "rating", "reviews", "website", "site_status",
    "platform", "address", "maps_url",
)

LEAD_STAGES = ("new", "attempted", "reached", "demo", "won", "lost", "parked")
TOUCH_KINDS = ("call", "follow_up", "demo", "email", "text")
TOUCH_OUTCOMES = ("", "no_answer", "voicemail", "gatekeeper", "reached",
                  "booked", "not_interested", "bad_number")


def lead_by_id(conn, lead_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def lead_by_phone(conn, phone_norm: str) -> dict | None:
    row = conn.execute("SELECT * FROM leads WHERE phone_norm = ?", (phone_norm,)).fetchone()
    return dict(row) if row else None


def upsert_lead(conn, phone_norm: str, **fields) -> tuple[int, bool]:
    """Insert a new lead or refresh only the scraped columns of an existing one.

    Returns (lead_id, created). Ian's state columns are never touched on update : 
    this is what makes re-running the scraper safe.
    """
    existing = lead_by_phone(conn, phone_norm) if phone_norm else None
    if existing:
        updates = {k: v for k, v in fields.items() if k in LEAD_SCRAPED_COLS}
        if updates:
            cols = ", ".join(f"{k}=?" for k in updates)
            conn.execute(
                f"UPDATE leads SET {cols}, updated_at=datetime('now','localtime') WHERE id=?",
                (*updates.values(), existing["id"]),
            )
        return existing["id"], False
    allowed = {k: v for k, v in fields.items()
               if k in LEAD_SCRAPED_COLS or k in ("stage", "notes", "source")}
    allowed["phone_norm"] = phone_norm or None
    cols = ", ".join(allowed)
    marks = ", ".join("?" for _ in allowed)
    cur = conn.execute(f"INSERT INTO leads ({cols}) VALUES ({marks})", tuple(allowed.values()))
    return cur.lastrowid, True


def update_lead(conn, lead_id: int, **fields) -> dict | None:
    allowed = {k: v for k, v in fields.items() if k in
               ("stage", "notes", "next_touch", "last_touch", "attempts")}
    if allowed:
        cols = ", ".join(f"{k}=?" for k in allowed)
        conn.execute(
            f"UPDATE leads SET {cols}, updated_at=datetime('now','localtime') WHERE id=?",
            (*allowed.values(), lead_id),
        )
        conn.commit()
    return lead_by_id(conn, lead_id)


def _lead_filter(tier: str = "", stage: str = "", market: str = "",
                 q: str = "") -> tuple[str, list]:
    """One WHERE builder shared by list_leads and count_leads.

    They MUST stay in lockstep: if the count ignores a filter the list applies,
    the pager reports a total it can never reach and pages into an empty view.
    """
    where, params = ["1=1"], []
    for col, val in (("tier", tier), ("stage", stage), ("market", market)):
        if val:
            where.append(f"{col} = ?")
            params.append(val)
    if q:
        where.append("(business_name LIKE ? OR city LIKE ? OR phone LIKE ? "
                     "OR owner_name LIKE ?)")
        params += [f"%{q}%"] * 4
    return " AND ".join(where), params


def list_leads(conn, tier: str = "", stage: str = "", market: str = "",
               q: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    where, params = _lead_filter(tier, stage, market, q)
    return rows_to_dicts(conn.execute(
        f"""SELECT * FROM leads WHERE {where}
            ORDER BY CASE tier WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2 ELSE 3 END,
                     total DESC, id
            LIMIT ? OFFSET ?""",
        (*params, int(limit), int(offset)),
    ).fetchall())


def count_leads(conn, tier: str = "", stage: str = "", market: str = "",
                q: str = "") -> int:
    where, params = _lead_filter(tier, stage, market, q)
    return conn.execute(
        f"SELECT COUNT(*) AS n FROM leads WHERE {where}", tuple(params)
    ).fetchone()["n"]


def lead_counts_by(conn, column: str) -> dict[str, int]:
    if column not in ("tier", "stage", "market", "segment"):
        raise ValueError(f"refusing to group leads by {column!r}")
    rows = conn.execute(f"SELECT {column} AS k, COUNT(*) AS n FROM leads GROUP BY {column}").fetchall()
    return {r["k"]: r["n"] for r in rows}


def add_touch(conn, lead_id: int, day: str, kind: str, outcome: str = "",
              note: str = "", duration_s: int = 0, run_id: int | None = None) -> dict:
    cur = conn.execute(
        """INSERT INTO lead_touches (lead_id, run_id, date, kind, outcome, duration_s, note)
           VALUES (?,?,?,?,?,?,?)""",
        (lead_id, run_id, day, kind, outcome, int(duration_s), note.strip()),
    )
    return dict(conn.execute("SELECT * FROM lead_touches WHERE id=?", (cur.lastrowid,)).fetchone())


def touch_by_id(conn, touch_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM lead_touches WHERE id = ?", (touch_id,)).fetchone()
    return dict(row) if row else None


def delete_touch(conn, touch_id: int) -> bool:
    cur = conn.execute("DELETE FROM lead_touches WHERE id=?", (touch_id,))
    return cur.rowcount > 0


def touches_for_lead(conn, lead_id: int) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM lead_touches WHERE lead_id=? ORDER BY id DESC", (lead_id,)
    ).fetchall())


def touches_since(conn, days: int = 7) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM lead_touches WHERE date >= date('now','localtime',?) ORDER BY id DESC",
        (f"-{int(days)} days",),
    ).fetchall())


# ---------------------------------------------------------------- call runs

def start_run(conn, day: str, target: int = 10) -> dict:
    open_row = conn.execute(
        "SELECT * FROM call_runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if open_row:
        return dict(open_row)
    cur = conn.execute("INSERT INTO call_runs (date, target) VALUES (?,?)", (day, int(target)))
    conn.commit()
    return dict(conn.execute("SELECT * FROM call_runs WHERE id=?", (cur.lastrowid,)).fetchone())


def end_run(conn, run_id: int) -> dict | None:
    conn.execute(
        "UPDATE call_runs SET ended_at = datetime('now','localtime') WHERE id=? AND ended_at IS NULL",
        (run_id,),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM call_runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def current_run(conn) -> dict | None:
    row = conn.execute(
        "SELECT * FROM call_runs WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def touches_for_run(conn, run_id: int) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM lead_touches WHERE run_id=? ORDER BY id", (run_id,)
    ).fetchall())


# ------------------------------------------------------- inbound (SPEC-v17)
# ingest/sync_btc.py is the only writer of new rows; the API may only move
# status. The consent column is walled: no helper here strips it because the
# WALL lives at the read sites (api/main.py summary + agent tools), and a test
# asserts it. Keep it that way.

def insert_inbound(conn, rec: dict) -> bool:
    """INSERT OR IGNORE by request_id (the idempotency key). True = new row."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO inbound_requests
           (request_id, kind, lead_id, name, company, email, phone,
            topics, windows, interest, message, consent, received_at,
            promised_by, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (rec["request_id"], rec["kind"], rec.get("lead_id"),
         rec.get("name", ""), rec.get("company", ""), rec.get("email", ""),
         rec.get("phone", ""), rec.get("topics", "[]"), rec.get("windows", "[]"),
         rec.get("interest", ""), rec.get("message", ""),
         rec.get("consent", "{}"), rec["received_at"],
         rec.get("promised_by"), rec.get("source", "btc")),
    )
    return cur.rowcount > 0


def pending_promises(conn) -> list[dict]:
    """Unhandled inbound with a live promise clock (SPEC-v18)."""
    return rows_to_dicts(conn.execute(
        "SELECT * FROM inbound_requests "
        "WHERE status='new' AND alerted_at IS NULL AND promised_by IS NOT NULL "
        "ORDER BY promised_by"
    ).fetchall())


def active_promises(conn) -> list[dict]:
    """Unhandled BtC promise clocks, independent of push delivery state.

    ``alerted_at`` proves only that a notification was sent; it is not proof
    that Ian handled the request. This deliberately narrow projection also
    keeps consent, contact details, and message bodies out of generic derived
    views such as the attention compiler.
    """
    return rows_to_dicts(conn.execute(
        """SELECT id, request_id, kind, source, status, received_at,
                  promised_by, alerted_at
           FROM inbound_requests
           WHERE source='btc' AND status='new' AND promised_by IS NOT NULL
           ORDER BY promised_by, id"""
    ).fetchall())


def mark_alerted(conn, ids: list[int]) -> int:
    """Fire-once stamp. Without it a 15-minute job pushes 16 times an hour."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    cur = conn.execute(
        f"UPDATE inbound_requests SET alerted_at = datetime('now','localtime'), "
        f"updated_at = datetime('now','localtime') WHERE id IN ({marks})", ids)
    conn.commit()
    return cur.rowcount


def inbound_by_id(conn, inbound_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM inbound_requests WHERE id=?", (inbound_id,)).fetchone()
    return dict(row) if row else None


def list_inbound(conn, status: str = "new", limit: int = 20) -> list[dict]:
    return rows_to_dicts(conn.execute(
        "SELECT * FROM inbound_requests WHERE status=? "
        "ORDER BY received_at LIMIT ?", (status, limit)).fetchall())


def set_inbound_status(conn, inbound_id: int, status: str) -> dict | None:
    conn.execute(
        "UPDATE inbound_requests SET status=?, updated_at=datetime('now','localtime') "
        "WHERE id=?", (status, inbound_id))
    conn.commit()
    return inbound_by_id(conn, inbound_id)


# --------------------------------------------------------- agent acts (v37)
# Ring 1 receipts (SPEC-v37 §4.5). Raw table I/O only; validation, the
# per-act inverse shape, and the write-then-receipt transaction all live in
# core/acts.py, the same layering as core/streaks.py and core/plan.py doing
# pure logic while db.py does the actual reads/writes.

def insert_agent_act(conn, *, role: str, act: str, plane: str, thread_id: int | None,
                      target_kind: str, target_id: str, summary: str,
                      inverse: dict) -> int:
    cur = conn.execute(
        """INSERT INTO agent_acts
               (role, act, plane, thread_id, target_kind, target_id, summary, inverse_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (role, act, plane, thread_id, target_kind, target_id, summary, json.dumps(inverse)),
    )
    return cur.lastrowid


def get_agent_act(conn, act_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM agent_acts WHERE id = ?", (act_id,)).fetchone()
    return dict(row) if row else None


def recent_agent_acts(conn, hours: int = 24) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT * FROM agent_acts
           WHERE created_at >= datetime('now', 'localtime', ?)
           ORDER BY created_at DESC""",
        (f"-{int(hours)} hours",),
    ).fetchall())


def mark_act_undone(conn, act_id: int, commit: bool = True) -> None:
    conn.execute(
        "UPDATE agent_acts SET undone_at = datetime('now','localtime') "
        "WHERE id = ? AND undone_at IS NULL",
        (act_id,),
    )
    if commit:
        conn.commit()


# ---------------------------------------------------- attention snoozes (v37)

def set_attention_snooze(conn, item_key: str, until: str, commit: bool = True) -> None:
    conn.execute(
        """INSERT INTO attention_snoozes (item_key, snoozed_until) VALUES (?, ?)
           ON CONFLICT(item_key) DO UPDATE SET
             snoozed_until = excluded.snoozed_until,
             created_at = datetime('now','localtime')""",
        (item_key, until),
    )
    if commit:
        conn.commit()


def clear_attention_snooze(conn, item_key: str, commit: bool = True) -> None:
    conn.execute("DELETE FROM attention_snoozes WHERE item_key = ?", (item_key,))
    if commit:
        conn.commit()


def active_snooze_keys(conn, now: str | None = None) -> set[str]:
    """Item keys currently suppressed from the attention order. `now` is an
    injectable ISO timestamp so callers can pin the clock in tests."""
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT item_key FROM attention_snoozes WHERE snoozed_until > ?", (now,)
    ).fetchall()
    return {r[0] for r in rows}
