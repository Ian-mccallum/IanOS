import React, { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { resumePlaidLink, startPlaidLink } from '../lib/plaid.js'
import { api } from '../lib/api.js'
import { relTime } from '../lib/time.js'
import AccountSheet from '../components/AccountSheet.jsx'
import BudgetCategorySheet from '../components/BudgetCategorySheet.jsx'
import Sheet from '../components/Sheet.jsx'

// SPEC-v37 §8.4 point 4: the Money hero's own refresh control. Loosely
// mirrors the server's 120s cooldown (api/main.py `_MONEY_REFRESH_COOLDOWN_SEC`)
// so a second tap during the window reads as "already refreshing" locally
// instead of round-tripping to learn the same thing.
const MONEY_REFRESH_COOLDOWN_MS = 120000

// financial_accounts.as_of is a full 'YYYY-MM-DD HH:MM:SS' local timestamp
// for Plaid sources but a bare 'YYYY-MM-DD' date for SnapTrade (sync_fidelity.py
// stamps db.today(), never db.now()). Comparing/parsing the two formats
// interchangeably is the actual trap: relTime's `new Date('2026-09-01')`
// parses a bare date as UTC midnight, which in Central time lands ~5-6h
// *before* local midnight -- immediately after a fresh SnapTrade sync this
// read as "as of 22h ago" instead of "just now". Appending a local midnight
// time only for comparison (never for what's shown) keeps the ordering
// correct without inheriting that UTC-parse bug.
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
function comparableAsOf(v) {
  return DATE_ONLY.test(v) ? `${v} 00:00:00` : v
}
function localToday() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
// Oldest (not newest) as_of among a set of balance timestamps: an aggregate
// figure (net worth, cash) is only as fresh as its stalest contributing
// account, so showing the newest would overstate how current the number is.
// Returns the original (un-normalized) string so a date-only value stays
// date-only for formatAsOf to recognize.
function oldestAsOf(values) {
  const present = values.filter(Boolean)
  if (!present.length) return null
  return present.reduce((oldest, v) => (comparableAsOf(v) < comparableAsOf(oldest) ? v : oldest))
}
// A same-day SnapTrade sync only ever tells us "today", never a time, so
// relTime (built for full local timestamps) would either misparse it or
// claim a false hour-level precision. "today" is the honest, checkable
// claim; a genuinely stale SnapTrade date still degrades to a normal
// relTime day count.
function formatAsOf(v) {
  if (!v) return null
  if (DATE_ONLY.test(v)) return v === localToday() ? 'today' : relTime(comparableAsOf(v))
  return relTime(v)
}

export function fmt(n, precise = false) {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: precise ? 2 : 0,
    maximumFractionDigits: precise ? 2 : 0,
  })
}

function burnLevel(amount, cap) {
  if (amount > cap) return 'crit'
  if (amount > cap * 0.8) return 'warn'
  return 'good'
}

// SPEC-v24 BUILD 3: one grouping rule shared by the unified account list.
// depository -> Cash, credit -> Cards, investment/crypto -> Crypto, any
// other investment subtype -> Investments. Anything else (a future provider
// type this mapping doesn't know yet) is deliberately left ungrouped so it
// never silently vanishes into the wrong bucket.
export function groupForAccount(account) {
  if (account.type === 'depository') return 'cash'
  if (account.type === 'credit') return 'cards'
  if (account.type === 'investment') return account.subtype === 'crypto' ? 'crypto' : 'investments'
  return null
}

const ACCOUNT_GROUPS = [
  { key: 'cash', label: 'Cash' },
  { key: 'cards', label: 'Cards' },
  { key: 'crypto', label: 'Crypto' },
  { key: 'investments', label: 'Investments' },
]

function utilLevel(u) {
  if (u > 0.7) return 'crit'
  if (u > 0.3) return 'warn'
  return 'good'
}

function StatusChip({ level, children }) {
  return <span className={`chip chip-${level}`}>{children}</span>
}

const FINANCE_SOURCE_META = [
  ['simplefin_chase', 'SimpleFIN'],
  ['snaptrade_fidelity', 'SnapTrade'],
  ['plaid_chase', 'Chase'],
  ['plaid_capital_one', 'Capital One'],
]

function freshnessLabel(state) {
  return {
    healthy: 'current',
    degraded: 'retrying',
    stale: 'stale',
    never: 'not synced yet',
  }[state] || state
}

function Meter({ value, max, level, label, className = '' }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className={`meter ${className}`} role="img" aria-label={label}>
      <div className={`meter-fill fill-${level}`} style={{ transform: `scaleX(${pct / 100})` }} />
    </div>
  )
}

function Card({ title, tag, children, className = '' }) {
  return (
    <section className={`money-card glass-card glass-card-pad ${className}`}>
      {(title || tag) && (
        <header className="money-card-head">
          {title && <h3 className="money-card-title">{title}</h3>}
          {tag && <span className="money-card-tag">{tag}</span>}
        </header>
      )}
      {children}
    </section>
  )
}

// onInspect, when passed, is a zero-arg callback the caller already bound to
// this specific row's entity (SPEC-v24 BUILD 4): the row itself never builds
// the {kind, id, role} payload, so the entity-id convention (holding.id as a
// string) lives in exactly one place, the render site, not duplicated here.
export function PositionRow({ p, onInspect }) {
  const gain = p.cost_basis != null ? p.market_value - p.cost_basis : null
  const gainCls = gain == null ? '' : gain >= 0 ? 'good-text' : 'crit-text'
  return (
    <div className="money-position">
      <div className="money-position-main">
        <span className="money-symbol">{p.symbol}</span>
        <span className="money-position-name dim" title={p.name}>{p.name}</span>
      </div>
      <div className="money-position-meta">
        <span className="money-position-val">{fmt(p.market_value, true)}</span>
        {gain != null && (
          <span className={`money-position-gain ${gainCls}`}>
            {gain >= 0 ? '+' : ''}{fmt(gain, true)}
          </span>
        )}
        {onInspect && (
          <button type="button" className="money-inspect" onClick={onInspect}>Inspect</button>
        )}
      </div>
    </div>
  )
}

export function TxnRow({ t, onInspect }) {
  const out = t.amount < 0
  return (
    <div className="money-txn">
      <div className="money-txn-main">
        <span className="money-txn-date dim">{t.date}</span>
        <span className="money-txn-desc" title={t.description}>{t.description}</span>
      </div>
      <div className="money-txn-meta">
        {t.category && <span className="money-cat">{t.category}</span>}
        <span className={`money-txn-amt ${out ? 'crit-text' : 'good-text'}`}>
          {out ? '' : '+'}{fmt(t.amount, true)}
        </span>
        {onInspect && (
          <button type="button" className="money-inspect" onClick={onInspect}>Inspect</button>
        )}
      </div>
    </div>
  )
}

function AccountRow({ account, onOpen }) {
  const balance = Number(account.current_balance) || 0
  const card = account.type === 'credit'
  const detail = [account.subtype, account.mask ? `••${account.mask}` : ''].filter(Boolean).join(' · ')
  // utilization is only ever a number when the backend had both a balance
  // and a nonzero credit_limit to divide (see _augment_financial_accounts);
  // anything else means "don't know", so the meter is omitted rather than
  // drawn at a misleading 0% (L3).
  const hasUtil = card && typeof account.utilization === 'number'
  // `liabilities` is present as a key only when a card_liabilities row
  // exists (checked by presence, not truthiness, per the API contract).
  const dueDate = card && account.liabilities ? account.liabilities.due_date : null
  const overdue = Boolean(account.liabilities && account.liabilities.is_overdue)
  // SPEC-v30 Phase 2: identity color, set the same way RosterPage.jsx sets
  // --agent on .agent-card. Omitted (not set to '') when Ian hasn't chosen
  // one yet, so var(--account, transparent)'s fallback in styles.css keeps
  // an un-customized row visually identical to today.
  const rowStyle = account.color ? { '--account': account.color } : undefined
  return (
    <button type="button" className="money-position money-position-row" style={rowStyle} onClick={onOpen}>
      <div className="money-position-main">
        <span className="money-symbol">
          {account.icon && <span className="money-account-icon">{account.icon}</span>}
          {account.institution || 'Bank'}
        </span>
        <span className="money-position-name dim">{account.name}{detail ? ` · ${detail}` : ''}</span>
        {hasUtil && (
          <Meter value={account.utilization} max={1} level={utilLevel(account.utilization)}
                 className="money-util-meter"
                 label={`Utilization ${Math.round(account.utilization * 100)}%`} />
        )}
        {dueDate && (
          <span className={`chip ${overdue ? 'chip-crit' : 'chip-warn'}`}>
            {overdue ? 'overdue' : `due ${dueDate}`}
          </span>
        )}
      </div>
      <div className="money-position-meta">
        <span className={card && balance > 0 ? 'crit-text' : 'money-position-val'}>{fmt(balance, true)}</span>
        {card && <span className="money-position-gain dim">owed</span>}
      </div>
    </button>
  )
}

function GoalRow({ g }) {
  const act = Number(g.actual) || 0
  const tgt = Number(g.target) || 1
  const level = act >= tgt ? 'good' : act >= tgt * 0.5 ? 'warn' : 'crit'
  return (
    <div className="money-goal">
      <div className="money-goal-head">
        <span className="money-goal-name">{g.name}</span>
        <span className="money-goal-val">{g.actual_label}</span>
      </div>
      <Meter value={act} max={tgt} level={level} className="money-burn-meter"
             label={`${g.name}: ${g.actual_label}`} />
      <span className="dim money-goal-target">Target: {fmt(tgt)} {g.unit}</span>
    </div>
  )
}

// SPEC-v30 Phase 1: money_prefs.hero_metric picks ONE of these four shapes
// for the top-of-page hero card. Pure selector, no JSX: maps the chosen
// metric (plus the page's already-computed numbers) into the plain data
// shape { label, value, sub, meter, ... } that <MoneyHero> renders. Falls
// through to the net_worth shape for an unrecognized string too, so a
// pre-migration or malformed money_prefs row never renders a blank hero.
function heroFor(metric, ctx) {
  const {
    hasBalances, netWorth, portfolio, portfolioVal, cashVal, cardVal, cashAccounts, checking,
    burnNow, burnCap, burnLvl, heroGoal, cashIsHero, sourceHealth, cashAsOf, netWorthAsOf,
  } = ctx

  if (metric === 'burn') {
    return {
      label: 'Business burn',
      tag: `${burnCap}/mo cap`,
      value: fmt(burnNow, true),
      valueCrit: burnLvl === 'crit',
      sub: `of ${fmt(burnCap)} cap`,
      meter: { value: burnNow, max: burnCap, level: burnLvl, label: `Business burn ${burnNow} of ${burnCap}` },
    }
  }

  if (metric === 'cash') {
    const cashKnown = cashAccounts.length > 0 || checking?.balance != null
    const belowFloor = cashVal < 1000
    return {
      label: cashAccounts.length > 0 ? 'Cash' : 'Checking',
      value: cashKnown ? fmt(cashVal, true) : '-',
      sub: belowFloor ? 'Below $1,000 floor' : null,
      subCrit: belowFloor,
      meter: null,
      asOf: cashKnown ? cashAsOf : null,
    }
  }

  if (metric === 'goal' && heroGoal) {
    const act = Number(heroGoal.actual) || 0
    const tgt = Number(heroGoal.target) || 1
    const level = act >= tgt ? 'good' : act >= tgt * 0.5 ? 'warn' : 'crit'
    return {
      label: heroGoal.name,
      value: heroGoal.actual_label,
      sub: `Target: ${fmt(tgt)} ${heroGoal.unit}`,
      meter: { value: act, max: tgt, level, label: `${heroGoal.name}: ${heroGoal.actual_label}` },
    }
  }

  // net_worth: today's default, and the safe fallback when hero_metric is
  // 'goal' but hero_goal_id no longer names a live finance goal. Cash (and
  // its below-$1,000 floor warning) folds into this one plain sub-line
  // whenever cash itself isn't the chosen hero; no meter, net worth has no cap.
  if (!hasBalances) {
    return {
      label: 'Net worth',
      value: '-',
      sub: sourceHealth.length ? 'No current balances to show' : 'Connect SnapTrade or SimpleFIN to see balances',
      meter: null,
    }
  }
  const parts = []
  if (portfolio) parts.push(`Portfolio ${fmt(portfolioVal, true)}`)
  const cashKnown = cashAccounts.length > 0 || checking?.balance != null
  if (cashKnown && !cashIsHero) parts.push(`${cashAccounts.length > 0 ? 'Cash' : 'Checking'} ${fmt(cashVal, true)}`)
  if (cardVal > 0) parts.push(`Cards owed ${fmt(cardVal, true)}`)
  const floorNote = !cashIsHero && cashVal < 1000
  if (floorNote) parts.push('Below $1,000')
  return {
    label: 'Net worth',
    value: fmt(netWorth, true),
    sub: parts.length ? parts.join(' · ') : null,
    subCrit: floorNote,
    meter: null,
    asOf: netWorthAsOf,
  }
}

// SPEC-v30: the closed widget-key enum, mirrored from core/db.py's
// MONEY_WIDGET_KEYS / MONEY_WIDGETS_DEFAULT so the fallback shape used before
// money_prefs has loaded (or on a pre-migration DB) is identical to what the
// server would hand back anyway.
const WIDGET_LABELS = {
  accounts: 'Linked accounts',
  goals: 'Finance goals',
  burn: 'Business burn',
  transactions: 'Recent transactions',
}
const DEFAULT_WIDGETS = [
  { key: 'accounts', visible: true },
  { key: 'goals', visible: true },
  { key: 'burn', visible: true },
  { key: 'transactions', visible: true },
]
const HERO_METRIC_OPTIONS = [
  { id: 'net_worth', label: 'Net worth' },
  { id: 'burn', label: 'Burn' },
  { id: 'cash', label: 'Cash' },
]

// One <MoneyHero>, four data shapes (SPEC-v30): the amber hero-wash class
// (`.money-hero`, byte-identical to the old `.money-burn-hero`) applies to
// whichever single metric money_prefs names; every other render of this
// same component falls back to the plain `.money-card` treatment already
// used by Linked accounts / Finance goals below, never a second amber.
// `metric === 'burn'` keeps its existing verbatim layout (cap tag, the
// meter, category rows, month history); the other three metrics share one
// simpler label/value/sub/meter template. `labelExtra` (net_worth only) is
// the "Customize Money" gear, rendered beside the eyebrow label rather than
// inside the generic badges slot (which sits beside the big number instead).
function MoneyHero({ metric, isHero, ctx, rm, badges, labelExtra, onManageBudgets, children }) {
  const hero = heroFor(metric, ctx)
  const containerClass = `glass-card ${isHero ? 'money-hero' : 'money-card glass-card-pad'}`
  const labelClass = `money-hero-label${isHero ? ' is-hero' : ''}`

  if (metric === 'burn') {
    return (
      <section className={containerClass}>
        <div className="money-burn-hero-head">
          <span className={labelClass}>{hero.label}</span>
          <span className="money-burn-hero-actions">
            <span className="money-card-tag">{hero.tag}</span>
            {/* SPEC-v30 Phase 3.5: opens BudgetCategorySheet, the one entry
                point into managing budget_categories/budget_rules -- a small
                text affordance beside the cap tag, not a second gear icon. */}
            {onManageBudgets && (
              <button type="button" className="money-inspect budget-edit-btn" onClick={onManageBudgets}>
                Manage budgets
              </button>
            )}
          </span>
        </div>
        <div className="money-burn-head">
          <span className={`hero-num money-burn-amt ${hero.valueCrit ? 'crit-text' : ''}`}>{hero.value}</span>
          <span className="dim">{hero.sub}</span>
        </div>
        {hero.meter && (
          <Meter value={hero.meter.value} max={hero.meter.max} level={hero.meter.level}
                 label={hero.meter.label} className="money-burn-meter" />
        )}
        {children}
      </section>
    )
  }

  const body = (
    <>
      <div className="money-hero-label-row">
        <p className={labelClass}>{hero.label}</p>
        {labelExtra}
      </div>
      <div className="money-hero-row">
        <h2 className="money-net">{hero.value}</h2>
        {badges}
      </div>
      {hero.asOf && <p className="money-hero-asof dim">as of {formatAsOf(hero.asOf)}</p>}
      {hero.meter && (
        <Meter value={hero.meter.value} max={hero.meter.max} level={hero.meter.level}
               label={hero.meter.label} className="money-burn-meter" />
      )}
      {hero.sub && <p className={`money-hero-sub ${hero.subCrit ? 'crit-text' : ''}`}>{hero.sub}</p>}
      {children}
    </>
  )

  // Only the net-worth card keeps the original mount fade-in (it was the one
  // hero that ever had it); burn/cash/goal render as a plain section, same
  // as burn's own pre-SPEC-v30 markup did.
  if (metric === 'net_worth') {
    return (
      <motion.div className={containerClass}
                  initial={rm ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}>
        {body}
      </motion.div>
    )
  }
  return <section className={containerClass}>{body}</section>
}

// "Customize Money" (SPEC-v30): one preference object, one sheet. Hero metric
// and widget order/visibility live together here rather than as two separate
// controls, matching money_prefs' own "one array, not two" shape. Reordering
// is up/down buttons, not drag-and-drop: this codebase has no drag library
// (verified zero draggable/onDragStart usage in dashboard/src, and exactly
// four runtime deps in package.json), so a drag implementation would be new
// infrastructure, not a reuse of something proven.
function MoneyPrefsSheet({ open, onClose, prefs, financeGoals, toast, onSaved }) {
  const [heroMetric, setHeroMetric] = useState('net_worth')
  const [heroGoalId, setHeroGoalId] = useState(null)
  const [widgets, setWidgets] = useState(DEFAULT_WIDGETS)
  const [saving, setSaving] = useState(false)

  // Re-seed local editable state from the server-shaped prefs every time the
  // sheet opens, so a Cancel (or a stale fetch that resolved while it was
  // open) never leaves last session's edits lying around.
  useEffect(() => {
    if (!open) return
    setHeroMetric(prefs?.hero_metric || 'net_worth')
    setHeroGoalId(prefs?.hero_goal_id ?? null)
    const seed = Array.isArray(prefs?.widgets_json) && prefs.widgets_json.length
      ? prefs.widgets_json
      : DEFAULT_WIDGETS
    setWidgets(seed.map((item) => ({ key: item.key, visible: item.visible !== false })))
  }, [open, prefs])

  function toggleWidget(key) {
    setWidgets((list) => list.map((w) => (w.key === key ? { ...w, visible: !w.visible } : w)))
  }

  function moveWidget(key, dir) {
    setWidgets((list) => {
      const idx = list.findIndex((w) => w.key === key)
      const next = idx + dir
      if (idx < 0 || next < 0 || next >= list.length) return list
      const copy = list.slice()
      ;[copy[idx], copy[next]] = [copy[next], copy[idx]]
      return copy
    })
  }

  async function save() {
    setSaving(true)
    try {
      const saved = await api('/api/money/prefs', 'PATCH', {
        hero_metric: heroMetric,
        // Clearing hero_goal_id whenever a non-goal metric is saved keeps a
        // stale goal id from lingering after Ian switches away from it.
        hero_goal_id: heroMetric === 'goal' ? heroGoalId : null,
        widgets_json: widgets,
      })
      onSaved?.(saved)
      onClose?.()
    } catch (err) {
      toast?.(err.message || 'Could not save Money preferences', 'warn')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Customize Money" variant="dialog">
      <section className="money-prefs-section">
        <h3 className="money-prefs-label">Hero metric</h3>
        <div className="money-hero-picker" role="group" aria-label="Hero metric">
          {HERO_METRIC_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`money-hero-opt${heroMetric === opt.id ? ' is-on' : ''}`}
              aria-pressed={heroMetric === opt.id}
              onClick={() => setHeroMetric(opt.id)}
            >
              {opt.label}
            </button>
          ))}
          {/* The goal picker only appears meaningfully once a finance goal
              exists to hoist; with none, selecting it would just fall back
              to net worth (heroFor's own safe-default rule). */}
          {financeGoals.length > 0 && (
            <button
              type="button"
              className={`money-hero-opt${heroMetric === 'goal' ? ' is-on' : ''}`}
              aria-pressed={heroMetric === 'goal'}
              onClick={() => setHeroMetric('goal')}
            >
              Goal
            </button>
          )}
        </div>
        {heroMetric === 'goal' && financeGoals.length > 0 && (
          <div className="money-goal-picker" role="group" aria-label="Choose finance goal">
            {financeGoals.map((g) => (
              <button
                key={g.id}
                type="button"
                className={`money-goal-opt${heroGoalId === g.id ? ' is-on' : ''}`}
                aria-pressed={heroGoalId === g.id}
                onClick={() => setHeroGoalId(g.id)}
              >
                {g.name}
              </button>
            ))}
          </div>
        )}
      </section>

      <section className="money-prefs-section">
        <h3 className="money-prefs-label">Widgets</h3>
        <div className="money-widget-rows">
          {widgets.map((w, idx) => (
            <div className="money-widget-row" key={w.key}>
              <label className="money-widget-row-toggle">
                <input type="checkbox" checked={w.visible !== false} onChange={() => toggleWidget(w.key)} />
                <span>{WIDGET_LABELS[w.key] || w.key}</span>
              </label>
              <div className="money-widget-move">
                <button
                  type="button"
                  className="money-move-btn"
                  disabled={idx === 0}
                  aria-label={`Move ${WIDGET_LABELS[w.key] || w.key} up`}
                  onClick={() => moveWidget(w.key, -1)}
                >
                  {'↑'}
                </button>
                <button
                  type="button"
                  className="money-move-btn"
                  disabled={idx === widgets.length - 1}
                  aria-label={`Move ${WIDGET_LABELS[w.key] || w.key} down`}
                  onClick={() => moveWidget(w.key, 1)}
                >
                  {'↓'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      <div className="money-prefs-actions">
        <button type="button" className="btn ghost" onClick={onClose} disabled={saving}>Cancel</button>
        <button type="button" className="btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </Sheet>
  )
}

export default function MoneyPage({ state, refresh, toast, navigate, onInspect, onOpenChat }) {
  const rm = useReducedMotion()
  // SPEC-v30: showDetails is gone (it hid three unrelated things behind one
  // boolean). Each widget below is its own native <details>, independently
  // toggle-able; this is only the shared *initial* open/closed value they're
  // each born with (collapsed-by-default is a phone concession; a laptop has
  // the room to show the numbers without an extra tap every session,
  // matchMedia read once at mount, mobile behavior unchanged). Passed as a
  // plain literal `open` prop, same as `.money-group` one level down: never
  // written to again, so a click natively toggles that one element's own
  // DOM state without React fighting it.
  const [detailsDefaultOpen] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(min-width: 901px)').matches,
  )
  const [connecting, setConnecting] = useState('')
  // SPEC-v37 §8.4 point 4: 'idle' | 'busy' (request in flight) | 'cooldown'
  // (response landed, waiting out the loose 120s client mirror of the
  // server's own cooldown so a second tap reads as a no-op, not a fresh
  // round trip).
  const [moneyRefreshState, setMoneyRefreshState] = useState('idle')
  const moneyRefreshTimer = useRef(null)
  useEffect(() => () => clearTimeout(moneyRefreshTimer.current), [])
  // "Customize Money" sheet: hero metric + widget order/visibility.
  const [prefsOpen, setPrefsOpen] = useState(false)
  // "Manage budgets" sheet (SPEC-v30 Phase 3.5): budget_categories/budget_rules.
  const [budgetSheetOpen, setBudgetSheetOpen] = useState(false)
  // { source, externalId } of the account whose detail sheet is open, or
  // null. Lives here (not in AccountSheet) because the row that opens it
  // and the sheet that closes it are siblings on this page.
  const [openAccount, setOpenAccount] = useState(null)
  // SPEC-v30: which metric gets the hero card. Defaults to net_worth so a
  // pre-migration DB (money_prefs doesn't exist yet) or an offline Mac
  // never crashes this page or renders a blank hero.
  const [moneyPrefs, setMoneyPrefs] = useState({ hero_metric: 'net_worth', hero_goal_id: null, widgets_json: null })
  useEffect(() => {
    let cancelled = false
    api('/api/money/prefs', 'GET', undefined, { cache: 'no-store' })
      .then((prefs) => { if (!cancelled) setMoneyPrefs(prefs) })
      .catch(() => { /* pre-migration DB or unreachable Mac: net_worth default stands */ })
    return () => { cancelled = true }
  }, [])
  const { portfolio, checking, financial_accounts, burn_by_month, burn_detail, budget_cap, recent_transactions, goals_by_domain, domain_status, stale_domains, finance_health } = state

  const financeGoals = goals_by_domain?.finance || []
  const portfolioVal = portfolio?.total_value ?? 0
  const linkedAccounts = Array.isArray(financial_accounts) ? financial_accounts : []
  const cashAccounts = linkedAccounts.filter((account) => account.type === 'depository')
  const cardAccounts = linkedAccounts.filter((account) => account.type === 'credit')
  const total = (accounts) => accounts.reduce((sum, account) => sum + (Number(account.current_balance) || 0), 0)
  const cashVal = cashAccounts.length ? total(cashAccounts) : (checking?.balance ?? 0)
  const cardVal = total(cardAccounts)
  const netWorth = (portfolio ? portfolioVal : 0) + cashVal - cardVal
  const hasBalances = portfolio || checking || linkedAccounts.length > 0

  const accountGroups = useMemo(() => {
    const buckets = { cash: [], cards: [], crypto: [], investments: [] }
    linkedAccounts.forEach((account) => {
      const key = groupForAccount(account)
      if (key && buckets[key]) buckets[key].push(account)
    })
    return buckets
  }, [linkedAccounts])

  const openAccountSummary = openAccount
    ? linkedAccounts.find(
        (a) => a.source === openAccount.source && a.external_id === openAccount.externalId,
      )
    : null

  // Binds a single transaction's Inspect entry point to the shared AskAgentSheet
  // (SPEC-v24 BUILD 4). Returns undefined (not a bound no-op) when the caller
  // gave no onInspect, which is exactly the "omit the affordance" signal
  // TxnRow's own `{onInspect && ...}` check reads.
  const inspectTransaction = (t) => (onInspect
    ? () => onInspect({ kind: 'transaction', id: String(t.id), role: 'cfo' }, `${t.description}, ${fmt(t.amount, true)}`)
    : undefined)

  const thisMonth = burn_by_month?.[0]
  const burnNow = thisMonth?.burn ?? 0
  // SPEC-v30 Phase 3: cap comes from the active budget_categories row via
  // /api/state (db.active_budget_cap), not a hardcoded literal -- editing
  // the cap in the Customize UI must actually move this meter. 150 here is
  // only the pre-fetch/pre-migration fallback, the same default the table
  // itself seeds, never a second source of truth.
  const burnCap = budget_cap ?? 150
  const burnLvl = burnLevel(burnNow, burnCap)

  const staleFinance = stale_domains?.includes('finance')
  const sourceHealth = FINANCE_SOURCE_META
    .map(([source, label]) => ({ source, label, state: finance_health?.[source]?.state }))
    .filter((source) => source.state && source.state !== 'disabled')

  const pendingMoney = useMemo(
    () => (state.pending_proposals || []).filter((p) => p.kind === 'money').length,
    [state.pending_proposals],
  )

  // SPEC-v30: resolve the hero_metric preference against data this render
  // actually has. A 'goal' preference whose hero_goal_id no longer names a
  // live finance goal (deleted/archived goal, or the pref just hasn't
  // loaded yet) falls back to net_worth rather than rendering a blank hero.
  const heroGoal = moneyPrefs.hero_metric === 'goal' && moneyPrefs.hero_goal_id != null
    ? financeGoals.find((g) => g.id === moneyPrefs.hero_goal_id) || null
    : null
  const heroMetric = moneyPrefs.hero_metric === 'goal' && !heroGoal
    ? 'net_worth'
    : (moneyPrefs.hero_metric || 'net_worth')
  const cashIsHero = heroMetric === 'cash'
  // SPEC-v37 §8.4 point 4: as_of beside the hero number, sourced from
  // state.checking.as_of and state.financial_accounts[].as_of (already on
  // /api/state, no backend change needed here). Oldest timestamp among the
  // accounts that actually feed each figure, see oldestAsOf's own note.
  const cashAsOf = oldestAsOf(
    cashAccounts.length ? cashAccounts.map((a) => a.as_of) : [checking?.as_of],
  )
  const netWorthAsOf = oldestAsOf([
    checking?.as_of,
    portfolio?.as_of_date,
    ...linkedAccounts.map((a) => a.as_of),
  ])
  const heroCtx = {
    hasBalances, netWorth, portfolio, portfolioVal, cashVal, cardVal, cashAccounts, checking,
    burnNow, burnCap, burnLvl, heroGoal, cashIsHero, sourceHealth, cashAsOf, netWorthAsOf,
  }
  // The hoisted hero goal renders once, up top; everyone else still lives
  // in the Finance goals card below (SPEC-v30: "the goal inside Finance
  // goals if not chosen").
  const remainingFinanceGoals = heroGoal ? financeGoals.filter((g) => g.id !== heroGoal.id) : financeGoals

  // SPEC-v30: each collapsible widget shows a persistent one-line status even
  // while collapsed, computed from data already on this page (no new fetch).
  // Linked accounts nets cards as owed (negative) rather than summing raw
  // balances, so the line reads as a real contribution to net worth.
  const linkedAccountsTotal = linkedAccounts.reduce((sum, a) => {
    const bal = Number(a.current_balance) || 0
    return sum + (a.type === 'credit' ? -bal : bal)
  }, 0)
  const financeGoalsOnTrack = remainingFinanceGoals.filter((g) => g.status === 'ON TRACK').length

  const burnChildren = (
    <>
      {burn_detail?.length > 0 && (
        <div className="money-burn-cats">
          <p className="section-label">This month by category</p>
          {burn_detail.map((c) => (
            <div key={c.category} className="money-burn-cat">
              <span className="money-cat">{c.category}</span>
              <span>{fmt(c.spent, true)}</span>
              <span className="dim">{c.n} txn{c.n === 1 ? '' : 's'}</span>
            </div>
          ))}
        </div>
      )}
      {burn_by_month?.length > 0 && (
        <div className="money-burn-history">
          <p className="section-label">Recent months</p>
          <div className="burn-months">
            {burn_by_month.map((m) => {
              const over = m.burn > burnCap
              return (
                <div key={m.month} className="burn-month">
                  <span className="dim">{m.month}</span>
                  <div className="mini-track">
                    <div className={`mini-fill ${over ? 'fill-crit' : 'fill-accent'}`}
                         style={{ width: `${Math.min(100, (m.burn / 220) * 100)}%` }} />
                    <span className="cap-tick" style={{ left: `${(burnCap / 220) * 100}%` }} />
                  </div>
                  <span className={over ? 'crit-text' : ''}>
                    {fmt(m.burn, true)}{over ? ' over' : ''}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </>
  )

  // SPEC-v30: MoneyPage.jsx's hardcoded JSX order becomes a small
  // [{key, render}] array filtered/sorted by money_prefs.widgets_json. Burn
  // only ever appears here when it is NOT the chosen hero (its render
  // function returns null otherwise), so it never renders twice: once fixed
  // at the top as the amber hero, once again down here.
  const widgetRenderers = {
    accounts: () => linkedAccounts.length > 0 && (
      <details className="money-card glass-card glass-card-pad money-widget" open={detailsDefaultOpen} key="accounts">
        <summary className="money-widget-head">
          <span className="money-card-title">Linked accounts</span>
          <span className="money-widget-subtotal">
            {linkedAccounts.length} account{linkedAccounts.length === 1 ? '' : 's'} · {fmt(linkedAccountsTotal, true)}
          </span>
        </summary>
        <div className="money-widget-body">
          <div className="money-groups">
            {ACCOUNT_GROUPS.map(({ key, label }) => {
              const accounts = accountGroups[key]
              if (!accounts || !accounts.length) return null
              const subtotal = accounts.reduce((sum, a) => sum + (Number(a.current_balance) || 0), 0)
              const isCards = key === 'cards'
              return (
                <details className="money-group" open key={key}>
                  <summary className="money-group-head">
                    <span className="money-group-name">{label}</span>
                    <span className={`money-group-subtotal ${isCards && subtotal > 0 ? 'crit-text' : ''}`}>
                      {fmt(subtotal, true)}{isCards ? ' owed' : ''}
                    </span>
                  </summary>
                  <div className="money-positions money-group-list">
                    {accounts.map((account) => (
                      <AccountRow
                        key={`${account.source}-${account.external_id}`}
                        account={account}
                        onOpen={() => setOpenAccount({ source: account.source, externalId: account.external_id })}
                      />
                    ))}
                  </div>
                </details>
              )
            })}
          </div>
        </div>
      </details>
    ),
    goals: () => remainingFinanceGoals.length > 0 && (
      <details className="money-card glass-card glass-card-pad money-widget" open={detailsDefaultOpen} key="goals">
        <summary className="money-widget-head">
          <span className="money-card-title">Finance goals</span>
          <span className="money-widget-subtotal">
            {remainingFinanceGoals.length} goal{remainingFinanceGoals.length === 1 ? '' : 's'} · {financeGoalsOnTrack} on track
          </span>
        </summary>
        <div className="money-widget-body">
          {remainingFinanceGoals.map((g) => <GoalRow key={g.id} g={g} />)}
        </div>
      </details>
    ),
    burn: () => heroMetric !== 'burn' && (
      <MoneyHero key="burn" metric="burn" isHero={false} ctx={heroCtx} rm={rm}
                 onManageBudgets={() => setBudgetSheetOpen(true)}>
        {burnChildren}
      </MoneyHero>
    ),
    transactions: () => recent_transactions?.length > 0 && (
      <details className="money-card glass-card glass-card-pad money-widget" open={detailsDefaultOpen} key="transactions">
        <summary className="money-widget-head">
          <span className="money-card-title">Recent transactions</span>
          <span className="money-widget-subtotal">
            {recent_transactions.length} transaction{recent_transactions.length === 1 ? '' : 's'} · last 45 days
          </span>
        </summary>
        <div className="money-widget-body">
          <div className="money-txn-list">
            {recent_transactions.map((t) => (
              <TxnRow key={t.id} t={t} onInspect={inspectTransaction(t)} />
            ))}
          </div>
        </div>
      </details>
    ),
  }

  const widgetOrder = Array.isArray(moneyPrefs.widgets_json) && moneyPrefs.widgets_json.length
    ? moneyPrefs.widgets_json
    : DEFAULT_WIDGETS
  const orderedWidgets = widgetOrder
    .filter((w) => w && w.visible !== false && widgetRenderers[w.key])
    .map((w) => widgetRenderers[w.key]())
    .filter(Boolean)

  const connectionCallbacks = useMemo(() => ({
    onConnected: async (itemKey, result) => {
      setConnecting('')
      await refresh?.()
      const label = itemKey === 'chase' ? 'Chase' : 'Capital One'
      toast?.(`${label} connected · ${result.inserted} new transactions`, 'good')
      try {
        if (sessionStorage.getItem('ianos:chat-return') === '1') {
          sessionStorage.removeItem('ianos:chat-return')
          // SPEC-v26 folded #chat into #home and moved chat into shell-level
          // overlay state (App.jsx `chatOpen`), so returning here means
          // landing on Command home and reopening that overlay, not a hash
          // navigate to a page that no longer exists.
          navigate?.('home')
          onOpenChat?.()
        }
      } catch { /* ignore */ }
    },
    onError: (error) => {
      setConnecting('')
      toast?.(error.message || 'Bank connection was not completed', 'warn')
    },
  }), [refresh, toast, navigate, onOpenChat])

  useEffect(() => {
    resumePlaidLink(connectionCallbacks)
  }, [connectionCallbacks])

  // SPEC-v37 §8.4 point 4. `sourceHealth` (finance_health with 'disabled'
  // filtered out) is the page's existing signal for "is at least one finance
  // source configured" -- the same FINANCE_SOURCES set the server checks for
  // its own 501, so the button simply doesn't render rather than sitting
  // there disabled when nothing is configured.
  async function refreshMoneyBalances() {
    if (moneyRefreshState !== 'idle') return
    setMoneyRefreshState('busy')
    try {
      const result = await api('/api/money/refresh', 'POST')
      if (result?.throttled) {
        // 200, not an error: a refresh already ran in the last 120s
        // (plan-sync/btc-sync precedent). Never surface this as a warning.
        toast('Already refreshing. Try again in a moment.', 'good')
      } else {
        const report = Array.isArray(result?.report) ? result.report : []
        toast(report.length ? report.join('; ') : 'Refreshed', 'good')
        await refresh?.()
      }
    } catch (err) {
      toast(err.message || 'Refresh failed', 'warn')
    } finally {
      setMoneyRefreshState('cooldown')
      clearTimeout(moneyRefreshTimer.current)
      moneyRefreshTimer.current = setTimeout(() => setMoneyRefreshState('idle'), MONEY_REFRESH_COOLDOWN_MS)
    }
  }

  async function connectPlaid(itemKey) {
    setConnecting(itemKey)
    try {
      await startPlaidLink(itemKey, connectionCallbacks)
    } catch (error) {
      setConnecting('')
      toast?.(error.message || 'Bank connection could not be started', 'warn')
    }
  }

  return (
    <div className="page-stack money-page">
      {/* SPEC-v30: one hero, not two. Net worth always renders (it's the
          page masthead: badges, data health, connect accordion, and the
          Customize Money gear live here regardless of which metric is
          chosen), amber only when it IS the chosen hero_metric. */}
      <MoneyHero
        metric="net_worth"
        isHero={heroMetric === 'net_worth'}
        ctx={heroCtx}
        rm={rm}
        labelExtra={(
          <>
            {sourceHealth.length > 0 && (
              <button type="button" className={`money-refresh-btn${moneyRefreshState === 'busy' ? ' is-busy' : ''}`}
                      aria-label={moneyRefreshState === 'busy' ? 'Refreshing balances' : 'Refresh balances'}
                      disabled={moneyRefreshState !== 'idle'}
                      onClick={refreshMoneyBalances}>
                <span aria-hidden="true">{'⟳'}</span>
              </button>
            )}
            <button type="button" className="money-settings-btn" aria-label="Customize Money"
                    onClick={() => setPrefsOpen(true)}>
              <span aria-hidden="true">{'⚙︎'}</span>
            </button>
          </>
        )}
        badges={(
          <div className="money-hero-badges">
            {staleFinance && <StatusChip level="warn">Stale data</StatusChip>}
            <StatusChip level={statusLevel(domain_status?.finance)}>
              {statusLabel(domain_status?.finance)}
            </StatusChip>
            {pendingMoney > 0 && (
              <StatusChip level="warn">{pendingMoney} money proposal{pendingMoney === 1 ? '' : 's'}</StatusChip>
            )}
          </div>
        )}
      >
        {sourceHealth.length > 0 && (
          <div className="money-data-health" aria-label="Finance data health">
            <span className="money-data-health-label">Data health</span>
            <div className="money-data-health-sources">
              {sourceHealth.map((source) => (
                <span className="money-data-source" data-state={source.state} key={source.source}>
                  <span>{source.label}</span>
                  <span className="money-data-state">{freshnessLabel(source.state)}</span>
                </span>
              ))}
            </div>
          </div>
        )}
        <details className="money-connect">
          <summary>Connect bank accounts</summary>
          <p>Link Chase checking and Capital One banking or cards. ianOS stores no Plaid access tokens in its database.</p>
          <div className="money-connect-actions">
            <button type="button" className="btn btn-quiet" disabled={Boolean(connecting)}
                    onClick={() => connectPlaid('chase')}>
              {connecting === 'chase' ? 'Opening Chase…' : 'Connect Chase'}
            </button>
            <button type="button" className="btn btn-quiet" disabled={Boolean(connecting)}
                    onClick={() => connectPlaid('capital_one')}>
              {connecting === 'capital_one' ? 'Opening Capital One…' : 'Connect Capital One'}
            </button>
          </div>
        </details>
      </MoneyHero>

      {/* Burn, cash and the chosen goal have no independent "normal module":
          each mounts fixed here, right under net worth, ONLY when it is the
          chosen hero_metric (amber wash). When burn is not the hero it still
          renders, just as an ordinary ordered widget below (widgetRenderers.
          burn); cash and an unchosen goal have no such lower-page form at
          all (cash folds into net worth's sub-line, an unchosen goal lives
          inside the Finance goals widget). */}
      {heroMetric === 'burn' && (
        <MoneyHero metric="burn" isHero ctx={heroCtx} rm={rm} onManageBudgets={() => setBudgetSheetOpen(true)}>
          {burnChildren}
        </MoneyHero>
      )}
      {heroMetric === 'cash' && (
        <MoneyHero metric="cash" isHero ctx={heroCtx} rm={rm} />
      )}
      {heroMetric === 'goal' && heroGoal && (
        <MoneyHero metric="goal" isHero ctx={heroCtx} rm={rm} />
      )}

      {/* SPEC-v30: showDetails is gone. Linked accounts / Finance goals /
          Recent transactions are independent native <details>, each with a
          persistent summary; Business burn (when not hero) joins them as an
          ordinary always-expanded module. Order and visibility come from
          money_prefs.widgets_json via the "Customize Money" sheet, never a
          hardcoded sequence. */}
      {orderedWidgets.length > 0 && (
        <div className="money-grid">{orderedWidgets}</div>
      )}

      {!portfolio && !checking && !recent_transactions?.length && (
        <Card>
          <div className="empty">
            <div className="empty-title">No financial data yet</div>
            <p>Import Chase CSV or connect SimpleFIN / SnapTrade. Run <code>make seed</code> for demo data.</p>
          </div>
        </Card>
      )}

      {openAccount && (
        <AccountSheet
          source={openAccount.source}
          externalId={openAccount.externalId}
          accountSummary={openAccountSummary}
          onClose={() => setOpenAccount(null)}
          navigate={navigate}
          onInspect={onInspect}
          toast={toast}
          refresh={refresh}
        />
      )}

      <MoneyPrefsSheet
        open={prefsOpen}
        onClose={() => setPrefsOpen(false)}
        prefs={moneyPrefs}
        financeGoals={financeGoals}
        toast={toast}
        onSaved={setMoneyPrefs}
      />

      <BudgetCategorySheet
        open={budgetSheetOpen}
        onClose={() => setBudgetSheetOpen(false)}
        toast={toast}
        onSaved={() => refresh?.()}
      />
    </div>
  )
}

function statusLabel(s) {
  const labels = {
    'ON TRACK': 'On track',
    'AT RISK': 'At risk',
    'OFF TRACK': 'Off track',
    'NO DATA': 'No data',
  }
  return labels[s] || s || 'No data'
}

function statusLevel(s) {
  if (s === 'ON TRACK') return 'good'
  if (s === 'AT RISK') return 'warn'
  if (s === 'OFF TRACK') return 'crit'
  return 'idle'
}
