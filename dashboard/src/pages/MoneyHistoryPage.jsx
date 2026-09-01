import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { fmt, TxnRow } from './MoneyPage.jsx'

// SPEC-v24 BUILD 4: the account history browser. One job (osUI L2): browse
// every transaction, filtered. No charting/virtualization library is
// available, so "load more" beats an infinite scroll here rather than
// reaching for one just for this page.

const PAGE_SIZE = 50

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

// String-only, deliberately never Date-parsed: a bare "YYYY-MM" run through
// `new Date()` and formatted back out shifts across a timezone boundary the
// same way core/promises.py warns naive-local/UTC mixing does. A month
// label has no time component to get wrong in the first place.
function monthLabel(key) {
  const [y, m] = String(key || '').split('-')
  const name = MONTH_NAMES[Number(m) - 1]
  return name ? `${name} ${y}` : key || 'Unknown'
}

function accountLabel(a) {
  return [a.institution, a.name].filter(Boolean).join(' · ') || a.name || a.institution || 'Account'
}

// Rows arrive sorted date DESC, id DESC (core/db.py list_transactions), so a
// single left-to-right pass groups them correctly, and a "load more" append
// can only ever extend the last group or start a new one after it. Never
// re-sorts, never reshuffles an earlier group.
function groupByMonth(rows) {
  const groups = []
  let current = null
  for (const t of rows) {
    const key = String(t.date || '').slice(0, 7)
    if (!current || current.key !== key) {
      current = { key, rows: [] }
      groups.push(current)
    }
    current.rows.push(t)
  }
  return groups
}

function monthStats(rows) {
  let inflow = 0
  let outflow = 0
  for (const t of rows) {
    const amt = Number(t.amount) || 0
    if (amt >= 0) inflow += amt
    else outflow += -amt
  }
  return { inflow, outflow, net: inflow - outflow }
}

/**
 * Props:
 *   state              object   dashboard state (for financial_accounts, the
 *                       account filter's options)
 *   initialAccountKey   string|null  pre-fills the account filter, e.g. from
 *                       AccountSheet's "View all transactions" deep link
 *                       (App.jsx reads this from sessionStorage, the
 *                       journal-focus precedent, and hands it down here).
 *   onInspect          (entity, label) => void | undefined. Threaded through
 *                       to every TxnRow exactly like MoneyPage and
 *                       AccountSheet, so a record inspected from history is
 *                       the same read AskAgentSheet already knows how to run.
 */
export default function MoneyHistoryPage({ state, initialAccountKey = null, onInspect }) {
  const accounts = Array.isArray(state?.financial_accounts) ? state.financial_accounts : []
  const [accountKey, setAccountKey] = useState(initialAccountKey || '')
  const [qInput, setQInput] = useState('')
  const [q, setQ] = useState('')
  const [month, setMonth] = useState('')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const debounce = useRef(null)

  // A fresh deep-link can arrive on a page that's already mounted (App.jsx
  // sets this prop from sessionStorage the same render it switches pages),
  // so the filter has to track it, not just read it once at mount.
  useEffect(() => {
    setAccountKey(initialAccountKey || '')
  }, [initialAccountKey])

  // Debounced ~300ms (SPEC-v24 BUILD 4 task law): `q` (the applied filter)
  // only follows `qInput` (what's on screen) after the user pauses, so a
  // fetch never fires per keystroke.
  useEffect(() => {
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => setQ(qInput.trim()), 300)
    return () => clearTimeout(debounce.current)
  }, [qInput])

  const load = useCallback(async (offset) => {
    setBusy(true)
    setError('')
    try {
      const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
      if (accountKey) params.set('account_key', accountKey)
      if (q) params.set('q', q)
      if (month) params.set('month', month)
      const result = await api(`/api/transactions?${params.toString()}`)
      const nextRows = Array.isArray(result.rows) ? result.rows : []
      setRows((current) => (offset === 0 ? nextRows : [...current, ...nextRows]))
      setTotal(Number(result.total) || 0)
    } catch (err) {
      setError(err?.message || 'Transactions could not load.')
      if (offset === 0) { setRows([]); setTotal(0) }
    } finally {
      setBusy(false)
    }
  }, [accountKey, q, month])

  // Any filter change starts over at offset 0; `load`'s identity changes
  // with its own deps, so this fires exactly when a filter does.
  useEffect(() => { load(0) }, [load])

  const groups = useMemo(() => groupByMonth(rows), [rows])
  const hasMore = rows.length < total

  const inspectTxn = (t) => (onInspect
    ? () => onInspect({ kind: 'transaction', id: String(t.id), role: 'cfo' }, `${t.description}, ${fmt(t.amount, true)}`)
    : undefined)

  return (
    <div className="money-history-page page-stack">
      {/* Reached only via AccountSheet's "View all transactions" deep link
          (SPEC-v24 BUILD 4); this page holds no tab of its own, so without
          this the OS back gesture was the only way out (SPEC-v29 Phase 7
          audit). Sticky so the way back stays reachable through every group
          of scrolled transactions, not just at the very top of the list. A
          plain hash href, not a navigate() call: MoneyHistoryPage is never
          handed a navigate prop (compare MoneyPage.jsx, which is), and
          usePage()'s hashchange listener in App.jsx already treats any
          '#money' href exactly like a real navigate('money'). */}
      <div className="money-history-topbar">
        <a className="btn ghost money-history-back" href="#money">← Back to Money</a>
      </div>
      <div className="money-history-filters">
        <select className="money-history-account" value={accountKey}
                onChange={(e) => setAccountKey(e.target.value)} aria-label="Filter by account">
          <option value="">All accounts</option>
          {accounts.map((a) => (
            <option key={`${a.source}-${a.external_id}`} value={`${a.source}:${a.external_id}`}>
              {accountLabel(a)}
            </option>
          ))}
        </select>
        <input className="money-history-search" type="search" inputMode="search" placeholder="Search description"
               value={qInput} onChange={(e) => setQInput(e.target.value)} aria-label="Search transaction descriptions" />
        <input className="money-history-month-input" type="month" value={month}
               onChange={(e) => setMonth(e.target.value)} aria-label="Filter by month" />
      </div>

      {error ? (
        <p className="ask-agent-error" role="alert">{error}</p>
      ) : busy && rows.length === 0 ? (
        <p className="dim">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="dim">No transactions match these filters.</p>
      ) : (
        <div className="money-history-groups">
          {groups.map((group) => {
            const stats = monthStats(group.rows)
            return (
              <section className="money-history-group" key={group.key}>
                <header className="money-history-group-head">
                  <span className="money-history-group-label">{monthLabel(group.key)}</span>
                  <span className="money-history-group-stats">
                    <span className="money-txn-amt good-text">+{fmt(stats.inflow, true)}</span>
                    <span className="money-txn-amt crit-text">-{fmt(stats.outflow, true)}</span>
                    <span className={`money-txn-amt ${stats.net >= 0 ? 'good-text' : 'crit-text'}`}>
                      {stats.net >= 0 ? '+' : ''}{fmt(stats.net, true)} net
                    </span>
                  </span>
                </header>
                <div className="money-txn-list">
                  {group.rows.map((t) => <TxnRow key={t.id} t={t} onInspect={inspectTxn(t)} />)}
                </div>
              </section>
            )
          })}
        </div>
      )}

      {hasMore && (
        <button type="button" className="btn ghost money-history-more" disabled={busy}
                onClick={() => load(rows.length)}>
          {busy ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  )
}
