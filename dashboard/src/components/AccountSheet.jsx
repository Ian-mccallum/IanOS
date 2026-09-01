import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { fmt, PositionRow, TxnRow } from '../pages/MoneyPage.jsx'
import Sheet from './Sheet.jsx'

// SPEC-v30 Phase 2: mirrors core/db.py's ACCOUNT_COLORS exactly (the
// hex-only subset of ROLE_COLORS, dashboard/src/lib/agents.js) -- the
// server validates a PATCH against that same set, so an unlisted hex is
// rejected there, not just hidden here. Kept as a literal client-side copy
// rather than round-tripped through the API: ACCOUNT_COLORS is a Python
// `set` with no stable serialization order, and neither GET
// /api/accounts/{source}/{id} nor /api/state exposes the allowed set
// today. Names are display-only (aria-label / title), never sent to the
// server -- the PATCH body carries the hex.
const ACCOUNT_COLORS = [
  { hex: '#818cf8', name: 'Indigo' },
  { hex: '#38bdf8', name: 'Sky' },
  { hex: '#f472b6', name: 'Pink' },
  { hex: '#c084fc', name: 'Purple' },
  { hex: '#facc15', name: 'Yellow' },
  { hex: '#fb923c', name: 'Orange' },
  { hex: '#fca5a5', name: 'Red' },
  { hex: '#a3e635', name: 'Green' },
  { hex: '#2dd4bf', name: 'Teal' },
  { hex: '#22d3ee', name: 'Cyan' },
  { hex: '#a78bfa', name: 'Violet' },
  { hex: '#e879f9', name: 'Fuchsia' },
  { hex: '#fb7185', name: 'Rose' },
  { hex: '#3b82f6', name: 'Blue' },
  { hex: '#d97706', name: 'Amber' },
  { hex: '#94a3b8', name: 'Slate' },
]

// Mirrors core/db.py's ACCOUNT_ICONS exactly, same reasoning as above.
const ACCOUNT_ICONS = [
  { glyph: '⌂', name: 'Bank' },
  { glyph: '▭', name: 'Card' },
  { glyph: '◎', name: 'Savings' },
  { glyph: '▲', name: 'Investment' },
  { glyph: '₿', name: 'Crypto' },
  { glyph: '$', name: 'Cash' },
  { glyph: '⊘', name: 'Loan' },
  { glyph: '◔', name: 'Retirement' },
  { glyph: '◫', name: 'Credit' },
  { glyph: '-', name: 'Other' },
]

/**
 * A 90-day balance trend, inline SVG, no charting library. Deliberately
 * monochrome (var(--accent) only): this is a running balance, not a
 * purchase or a verdict, so it never earns --good/--crit coloring (osUI
 * inherited law). Omitted entirely below 2 points rather than drawn as a
 * flat, meaningless line (L3).
 */
function Sparkline({ points }) {
  const values = (Array.isArray(points) ? points : [])
    .map((p) => (p.current == null ? null : Number(p.current)))
    .filter((v) => v != null && !Number.isNaN(v))
  if (values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const w = 280
  const h = 48
  const stepX = w / (values.length - 1)
  const coords = values
    .map((v, i) => `${(i * stepX).toFixed(1)},${(h - ((v - min) / range) * h).toFixed(1)}`)
    .join(' ')
  return (
    <div className="account-sheet-spark">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="90-day balance trend">
        <polyline points={coords} fill="none" stroke="var(--accent)" strokeWidth="2"
                  strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <span className="account-sheet-spark-label">90-day trend</span>
    </div>
  )
}

/**
 * Bottom sheet for a single financial account. Chrome (portal, backdrop,
 * focus trap, Escape close, reduced-motion-aware slide-up) comes from the
 * shared <Sheet> primitive (SPEC-v29 Phase 3), same as AskAgentSheet.jsx;
 * only content genuinely new to this sheet (balance, sparkline, liabilities)
 * gets its own account-sheet- classes.
 *
 * Props:
 *   source       string   e.g. "plaid_chase" | "snaptrade"
 *   externalId   string   the provider's account id
 *   accountSummary object|undefined  the already-known row from
 *                  state.financial_accounts, used to paint the header and
 *                  balance instantly, before the detail fetch resolves.
 *   onClose      () => void
 *   navigate     (id: string) => void  |  undefined (SPEC-v24 BUILD 4). The
 *                  app's one hash-navigation function, passed down from
 *                  App.jsx through MoneyPage. "View all transactions" stashes
 *                  this account's key in sessionStorage (the journal-focus
 *                  deep-link precedent) then calls navigate('moneyhistory').
 *                  Omitted entirely, not disabled, when the caller has none.
 *   onInspect    (entity, label) => void  |  undefined. Opens AskAgentSheet
 *                  in read-only inspect mode for one record. Threaded through
 *                  to every row this sheet renders (recent transactions,
 *                  holdings) plus one entry point for the account itself.
 *   toast        (message, level) => void  |  undefined. Same toast the rest
 *                  of MoneyPage uses; surfaces a failed appearance PATCH.
 *   refresh      () => Promise  |  undefined. MoneyPage's /api/state refetch,
 *                  fired (not awaited) after a successful color/icon PATCH so
 *                  the account list behind this sheet updates without waiting
 *                  on the next 15s poll.
 */
export default function AccountSheet({ source, externalId, accountSummary, onClose, navigate, onInspect, toast, refresh }) {
  const [detail, setDetail] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setDetail(null)
    setLoading(true)
    setError('')
    api(`/api/accounts/${encodeURIComponent(source)}/${encodeURIComponent(externalId)}`)
      .then((data) => { if (!cancelled) setDetail(data) })
      .catch((err) => { if (!cancelled) setError(err?.message || 'Could not load this account.') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [source, externalId])

  const institution = detail?.institution ?? accountSummary?.institution
  const name = detail?.name ?? accountSummary?.name
  const mask = detail?.mask ?? accountSummary?.mask
  const type = detail?.type ?? accountSummary?.type
  const balance = detail ? detail.current_balance : accountSummary?.current_balance
  const isCard = type === 'credit'
  const isInvestment = type === 'investment'
  const liabilities = detail?.liabilities
  const overdue = Boolean(liabilities && liabilities.is_overdue)
  const transactions = detail?.recent_transactions || []
  const holdings = detail?.holdings || []

  // Same mechanism as App.jsx's own journal-focus deep link (sessionStorage +
  // a plain navigate(id) call), just written from the leaf that actually
  // knows the account key instead of from a wrapper above MoneyPage. Never
  // invents a second navigation channel.
  const goToHistory = () => {
    try { sessionStorage.setItem('money-history-account', `${source}:${externalId}`) } catch { /* private mode */ }
    navigate?.('moneyhistory')
  }

  const inspectAccount = onInspect
    ? () => onInspect({ kind: 'account', id: `${source}:${externalId}`, role: 'cfo' }, name || institution || 'Account')
    : null

  const inspectHolding = (h) => (onInspect
    ? () => onInspect({ kind: 'holding', id: String(h.id), role: 'wealth' }, h.symbol)
    : undefined)

  const inspectTxn = (t) => (onInspect
    ? () => onInspect({ kind: 'transaction', id: String(t.id), role: 'cfo' }, `${t.description}, ${fmt(t.amount, true)}`)
    : undefined)

  // SPEC-v30 Phase 2: instant-write, same optimistic-then-confirm shape as
  // AgentChat's patchThread (components/AgentChat.jsx:578-594) -- a picker
  // that waits on a round trip reads as broken. Only one field changes per
  // tap, so on failure the exact previous value is put back rather than
  // refetching the whole account.
  async function setAppearance(field, value) {
    const previous = detail ? detail[field] : undefined
    setDetail((current) => (current ? { ...current, [field]: value } : current))
    try {
      const updated = await api(
        `/api/accounts/${encodeURIComponent(source)}/${encodeURIComponent(externalId)}/appearance`,
        'PATCH',
        { [field]: value },
      )
      setDetail(updated)
      refresh?.()
    } catch (err) {
      setDetail((current) => (current ? { ...current, [field]: previous } : current))
      toast?.(err.message || 'Could not update this account.', 'warn')
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      title={`${name || 'Account detail'}${mask ? ` ••${mask}` : ''}`}
      variant="dialog"
    >
      <p className="section-label">{institution || 'Account'}</p>

      <div className="account-sheet-body">
          <div className="account-sheet-balance">
            <span className={`money-big ${isCard && balance > 0 ? 'crit-text' : ''}`}>{fmt(balance, true)}</span>
            {isCard && <span className="dim">owed</span>}
            {inspectAccount && (
              <button type="button" className="money-inspect account-sheet-inspect" onClick={inspectAccount}>
                Inspect
              </button>
            )}
          </div>

          {loading && (
            <div className="account-sheet-loading" role="status" aria-live="polite">
              <div className="ask-agent-reading" aria-hidden="true"><span /><span /><span /></div>
              <span className="dim">Loading account detail…</span>
            </div>
          )}

          {!loading && error && <p className="ask-agent-error" role="alert">{error}</p>}

          {!loading && !error && detail && (
            <>
              <div className="account-sheet-appearance">
                <div className="account-sheet-appearance-row">
                  <p className="section-label">Color</p>
                  <div className="account-sheet-swatches" role="group" aria-label="Account color">
                    {ACCOUNT_COLORS.map((c) => (
                      <button
                        key={c.hex}
                        type="button"
                        className={`account-sheet-swatch${detail.color === c.hex ? ' is-on' : ''}`}
                        style={{ '--swatch': c.hex }}
                        aria-pressed={detail.color === c.hex}
                        aria-label={c.name}
                        title={c.name}
                        onClick={() => setAppearance('color', c.hex)}
                      />
                    ))}
                  </div>
                </div>
                <div className="account-sheet-appearance-row">
                  <p className="section-label">Icon</p>
                  <div className="account-sheet-glyphs" role="group" aria-label="Account icon">
                    {ACCOUNT_ICONS.map((g) => (
                      <button
                        key={g.glyph}
                        type="button"
                        className={`account-sheet-glyph${detail.icon === g.glyph ? ' is-on' : ''}`}
                        aria-pressed={detail.icon === g.glyph}
                        aria-label={g.name}
                        title={g.name}
                        onClick={() => setAppearance('icon', g.glyph)}
                      >
                        {g.glyph}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <Sparkline points={detail.snapshots_90d} />

              {isCard && liabilities && (
                <div className="account-sheet-liabilities">
                  <div className="account-sheet-liab-row">
                    <span className="dim">Statement balance</span>
                    <span>{fmt(liabilities.statement_balance, true)}</span>
                  </div>
                  <div className="account-sheet-liab-row">
                    <span className="dim">Minimum payment</span>
                    <span>{fmt(liabilities.minimum_payment, true)}</span>
                  </div>
                  <div className="account-sheet-liab-row">
                    <span className="dim">Due date</span>
                    <span>
                      {liabilities.due_date || '-'}
                      {overdue && <span className="chip chip-crit">overdue</span>}
                    </span>
                  </div>
                  <div className="account-sheet-liab-row">
                    <span className="dim">APR</span>
                    <span>{liabilities.apr != null ? `${Number(liabilities.apr).toFixed(2)}%` : '-'}</span>
                  </div>
                </div>
              )}

              {isInvestment ? (
                holdings.length > 0 ? (
                  <div className="money-positions">
                    {holdings.map((h) => (
                      <PositionRow key={h.id} p={{ ...h, name: h.description }} onInspect={inspectHolding(h)} />
                    ))}
                  </div>
                ) : (
                  <p className="dim">No holdings on record for this account.</p>
                )
              ) : transactions.length > 0 ? (
                <>
                  <div className="money-txn-list">
                    {transactions.map((t) => <TxnRow key={t.id} t={t} onInspect={inspectTxn(t)} />)}
                  </div>
                  {/* Deep-links into the account history browser (Money history
                      page, SPEC-v24 BUILD 4), pre-filtered to this account via
                      the sessionStorage handoff in goToHistory(). A no-op when
                      the caller gave no navigate (defensive, should not happen
                      in the mounted app). */}
                  <button type="button" className="btn ghost account-sheet-viewall" onClick={goToHistory}>
                    View all transactions
                  </button>
                </>
              ) : (
                <p className="dim">No transactions on record for this account.</p>
              )}
            </>
          )}
      </div>
    </Sheet>
  )
}
