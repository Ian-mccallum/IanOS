import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { fmt } from '../pages/MoneyPage.jsx'
import Sheet from './Sheet.jsx'

// Same three-tier language as MoneyPage.jsx's burnLevel (duplicated, not
// imported: that function is scoped to the page's own burn-hero meter and
// this sheet's rows are a different, per-category read, same precedent as
// burnLevel/utilLevel already living as two separate near-identical
// functions in MoneyPage.jsx for two different metrics).
function levelFor(spent, cap) {
  if (!cap || cap <= 0) return 'good'
  if (spent > cap) return 'crit'
  if (spent > cap * 0.8) return 'warn'
  return 'good'
}

const EMPTY_DRAFT = { id: null, name: '', cap: '', categories: [], color: '', rules: [] }

/**
 * "Manage budgets" (SPEC-v30 Phase 3.5). One Sheet, two local views: a list
 * of Ian's budget_categories rows (each with this-month spend against its
 * own cap) and an edit-one-row view (name, cap, a checklist of the live
 * distinct transactions.category values, and an add/remove keyword-rule
 * list for uncategorized personal spend). No second Sheet, no drag
 * (this codebase has none, the money_prefs sheet precedent).
 *
 * Props:
 *   open     boolean
 *   onClose  () => void
 *   toast    (message, level) => void | undefined
 *   onSaved  () => void | undefined  -- called after a create/update/archive
 *            that actually changed the table, so MoneyPage can refresh
 *            /api/state (the active cap this sheet edits also drives the
 *            burn hero's meter color there).
 */
export default function BudgetCategorySheet({ open, onClose, toast, onSaved }) {
  const [view, setView] = useState('list') // 'list' | 'edit'
  const [rows, setRows] = useState([])
  const [available, setAvailable] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [newKeyword, setNewKeyword] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)

  function load() {
    setLoading(true)
    setError('')
    return api('/api/budget-categories', 'GET', undefined, { cache: 'no-store' })
      .then((data) => {
        setRows(Array.isArray(data.rows) ? data.rows : [])
        setAvailable(Array.isArray(data.available_categories) ? data.available_categories : [])
      })
      .catch((err) => setError(err.message || 'Could not load budget categories'))
      .finally(() => setLoading(false))
  }

  // Re-seed on every open, same reasoning as MoneyPrefsSheet: a stale fetch
  // resolving after a previous close/reopen must never show last session's
  // data, and the sheet always starts on the list view.
  useEffect(() => {
    if (!open) return
    setView('list')
    setConfirmArchive(false)
    load()
  }, [open])

  function openNew() {
    setDraft({ ...EMPTY_DRAFT })
    setNewKeyword('')
    setConfirmArchive(false)
    setView('edit')
  }

  function openEdit(row) {
    setDraft({
      id: row.id,
      name: row.name,
      cap: String(row.cap ?? ''),
      categories: Array.isArray(row.categories) ? [...row.categories] : [],
      color: row.color || '',
      rules: Array.isArray(row.rules) ? [...row.rules] : [],
    })
    setNewKeyword('')
    setConfirmArchive(false)
    setView('edit')
  }

  function toggleCategory(cat) {
    setDraft((d) => ({
      ...d,
      categories: d.categories.includes(cat)
        ? d.categories.filter((c) => c !== cat)
        : [...d.categories, cat],
    }))
  }

  function addKeyword() {
    const kw = newKeyword.trim()
    if (!kw) return
    setDraft((d) => (d.rules.some((r) => r.toLowerCase() === kw.toLowerCase())
      ? d
      : { ...d, rules: [...d.rules, kw] }))
    setNewKeyword('')
  }

  function removeKeyword(kw) {
    setDraft((d) => ({ ...d, rules: d.rules.filter((r) => r !== kw) }))
  }

  async function save() {
    const name = draft.name.trim()
    if (!name) { toast?.('a budget category needs a name', 'warn'); return }
    const capNum = Number(draft.cap)
    if (!Number.isFinite(capNum) || capNum <= 0) { toast?.('cap must be greater than 0', 'warn'); return }
    setSaving(true)
    try {
      const body = { name, cap: capNum, categories: draft.categories, color: draft.color, rules: draft.rules }
      if (draft.id) await api(`/api/budget-categories/${draft.id}`, 'PATCH', body)
      else await api('/api/budget-categories', 'POST', body)
      await load()
      setView('list')
      onSaved?.()
    } catch (err) {
      toast?.(err.message || 'Could not save this budget category', 'warn')
    } finally {
      setSaving(false)
    }
  }

  // Soft delete only (goals.archived precedent) -- there is no DELETE route
  // for this table. Two-tap confirm in place, the GoalForm.jsx precedent,
  // rather than a native confirm() popup (unused anywhere in this codebase).
  async function archive() {
    if (!draft.id) return
    if (!confirmArchive) { setConfirmArchive(true); return }
    setSaving(true)
    try {
      await api(`/api/budget-categories/${draft.id}`, 'PATCH', { archived: true })
      await load()
      setView('list')
      onSaved?.()
    } catch (err) {
      toast?.(err.message || 'Could not archive this budget category', 'warn')
    } finally {
      setSaving(false)
      setConfirmArchive(false)
    }
  }

  const title = view === 'edit' ? (draft.id ? 'Edit budget' : 'New budget category') : 'Manage budgets'

  return (
    <Sheet open={open} onClose={onClose} title={title} variant="dialog">
      {view === 'list' && (
        <>
          {loading && <p className="dim">Loading budgets…</p>}
          {!loading && error && <p className="ask-agent-error" role="alert">{error}</p>}
          {!loading && !error && rows.length === 0 && (
            <p className="dim">No budget categories yet.</p>
          )}
          {!loading && !error && rows.map((row) => {
            const level = levelFor(row.spent_this_month, row.cap)
            const pct = row.cap ? Math.max(0, Math.min(1, row.spent_this_month / row.cap)) : 0
            return (
              <div className="money-goal" key={row.id}>
                <div className="money-goal-head">
                  <span>
                    <span className="money-goal-name">{row.name}</span>
                    <span className="dim"> · {fmt(row.cap)}/mo cap</span>
                  </span>
                  <button type="button" className="money-inspect budget-edit-btn"
                          aria-label={`Edit ${row.name}`} onClick={() => openEdit(row)}>
                    Edit
                  </button>
                </div>
                <div className="meter" role="img"
                     aria-label={`${row.name}: ${fmt(row.spent_this_month, true)} of ${fmt(row.cap)} cap`}>
                  <div className={`meter-fill fill-${level}`} style={{ transform: `scaleX(${pct})` }} />
                </div>
                <span className="dim money-goal-target">
                  {fmt(row.spent_this_month, true)} this month · {row.txn_count_this_month}{' '}
                  txn{row.txn_count_this_month === 1 ? '' : 's'}
                </span>
              </div>
            )
          })}
          <div className="money-prefs-actions">
            <button type="button" className="btn add-goal" onClick={openNew} disabled={loading}>
              + New budget category
            </button>
          </div>
        </>
      )}

      {view === 'edit' && (
        <>
          <div className="gf-row">
            <label className="gf-field gf-grow">
              <span>Name</span>
              <input value={draft.name} autoFocus placeholder="e.g. Business burn"
                     onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
            </label>
            <label className="gf-field">
              <span>Cap ($/mo)</span>
              <input type="number" min="0.01" step="0.01" value={draft.cap} placeholder="150"
                     onChange={(e) => setDraft((d) => ({ ...d, cap: e.target.value }))} />
            </label>
          </div>

          <section className="money-prefs-section">
            <h3 className="money-prefs-label">Transaction categories</h3>
            {available.length === 0 ? (
              <p className="dim">No categorized transactions yet.</p>
            ) : (
              <div className="budget-checklist" role="group" aria-label="Transaction categories">
                {available.map((cat) => (
                  <label className="money-widget-row-toggle" key={cat}>
                    <input type="checkbox" checked={draft.categories.includes(cat)}
                           onChange={() => toggleCategory(cat)} />
                    <span>{cat}</span>
                  </label>
                ))}
              </div>
            )}
          </section>

          <section className="money-prefs-section">
            <h3 className="money-prefs-label">Uncategorized spend keywords</h3>
            <p className="dim">
              Matches personal transactions with no category by description
              (e.g. "whole foods"), never an already-categorized transaction.
            </p>
            {draft.rules.length > 0 && (
              <div className="budget-rules-list">
                {draft.rules.map((kw) => (
                  <span className="chip chip-idle budget-rule-chip" key={kw}>
                    {kw}
                    <button type="button" className="budget-rule-remove"
                            aria-label={`Remove keyword ${kw}`} onClick={() => removeKeyword(kw)}>
                      {'×'}
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="budget-rule-add">
              <input value={newKeyword} placeholder="e.g. whole foods"
                     onChange={(e) => setNewKeyword(e.target.value)}
                     onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addKeyword() } }} />
              <button type="button" className="btn ghost" onClick={addKeyword} disabled={!newKeyword.trim()}>
                Add
              </button>
            </div>
          </section>

          <div className="money-prefs-actions">
            {draft.id && (
              <button type="button" className="btn reject" onClick={archive} disabled={saving}>
                {confirmArchive ? 'Confirm archive?' : 'Archive'}
              </button>
            )}
            <button type="button" className="btn ghost" onClick={() => setView('list')} disabled={saving}>
              Back
            </button>
            <button type="button" className="btn" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </>
      )}
    </Sheet>
  )
}
