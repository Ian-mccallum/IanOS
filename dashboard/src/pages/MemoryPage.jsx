import React, { useMemo, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'

const DOMAIN_ORDER = ['personal', 'college', 'health', 'business', 'finance', 'legal']
const DOMAIN_LABELS = {
  personal: 'Personal', college: 'College', health: 'Health',
  business: 'Business', finance: 'Finance', legal: 'Legal',
}
const KIND_LABELS = { fact: 'fact', preference: 'pref', date: 'date', rule: 'rule' }

function countdownLevel(days) {
  if (days == null) return null
  if (days < 7) return 'crit'
  if (days < 21) return 'warn'
  return 'good'
}

function FactChips({ fact }) {
  const level = countdownLevel(fact.days_until)
  return (
    <>
      <span className={`fact-kind fact-kind-${fact.kind}`}>{KIND_LABELS[fact.kind] || fact.kind}</span>
      {level && (
        <span className={`chip chip-${level}`}>
          {fact.days_until === 0 ? 'today' : `in ${fact.days_until}d`}
        </span>
      )}
      {!fact.verified && <span className="chip chip-warn">unconfirmed</span>}
    </>
  )
}

/* Single tap, then Undo: the app's own convention everywhere else a row is
   removed (Notes, goal Archive). This used to be the one delete in the
   product that armed on a first click and had no way back (SPEC-v14). */
function FactActions({ fact, onConfirm, onDelete, onEdit, busy }) {
  return (
    <span className="fact-actions">
      {onEdit && (
        <button type="button" className="btn ghost fact-btn" onClick={() => onEdit(fact)} disabled={busy}>
          Edit
        </button>
      )}
      {!fact.verified && (
        <button type="button" className="btn ghost fact-btn"
                onClick={() => onConfirm(fact)} disabled={busy}>Confirm</button>
      )}
      <button type="button" className="fact-delete"
              onClick={() => onDelete(fact)}
              disabled={busy} aria-label={`Delete fact ${fact.topic}`}>
        ×
      </button>
    </span>
  )
}

function FactCard({ fact, onConfirm, onDelete, onEdit, onSave, onCancel, busy, editing }) {
  const rm = useReducedMotion()
  return (
    <motion.div
      layout={!rm}
      className={`fact-card glass-card glass-card-pad${fact.verified ? '' : ' unverified'}`}
      initial={rm ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={rm ? { opacity: 0 } : { opacity: 0, x: -12, transition: { duration: 0.15 } }}
    >
      <div className="fact-head">
        <span className="fact-topic">{fact.topic}</span>
        <FactChips fact={fact} />
      </div>
      {editing?.id === fact.id ? (
        <FactEditForm fact={editing} onSave={onSave} onCancel={onCancel} busy={busy} />
      ) : (
        <p className="fact-body">{fact.body}</p>
      )}
      <div className="fact-meta">
        {fact.next_occurrence && <span>{fact.next_occurrence}{fact.recurs === 'yearly' ? ' · yearly' : ''}</span>}
        {fact.source_role && <span>via {fact.source_role}</span>}
        <FactActions fact={fact} onConfirm={onConfirm} onDelete={onDelete}
                     onEdit={editing?.id === fact.id ? null : onEdit} busy={busy} />
      </div>
    </motion.div>
  )
}

function FactEditForm({ fact, onSave, onCancel, busy }) {
  const [body, setBody] = useState(fact.body || '')
  const [date, setDate] = useState(fact.date || '')
  return (
    <div className="fact-edit-form">
      <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={3} aria-label="Memory text" />
      {fact.kind === 'date' && (
        <label className="gf-field">
          <span>Date</span>
          <input type="date" value={date || ''} onChange={(e) => setDate(e.target.value)} />
        </label>
      )}
      <div className="gf-controls">
        <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className="btn approve" onClick={() => onSave({ ...fact, body, date: date || null })} disabled={busy}>
          Save
        </button>
      </div>
    </div>
  )
}

const FactRow = React.forwardRef(function FactRow({ fact, onConfirm, onDelete, onEdit, onSave, onCancel, busy, editing }, ref) {
  const rm = useReducedMotion()
  const [open, setOpen] = useState(false)
  const editingCurrent = editing?.id === fact.id
  const expanded = open || editingCurrent
  const detailId = `fact-detail-${fact.id}`

  const toggleOpen = () => {
    if (editingCurrent) onCancel?.()
    setOpen((current) => !current)
  }

  return (
    <motion.div
      ref={ref}
      layout={!rm}
      className="card-item"
      initial={rm ? false : { opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={rm ? { opacity: 0 } : { opacity: 0, x: -12, transition: { duration: 0.15 } }}
    >
      <button type="button" className="fact-row" onClick={toggleOpen}
              aria-expanded={expanded} aria-controls={detailId} title={fact.body}>
        <span className="fact-topic">{fact.topic}</span>
        <FactChips fact={fact} />
        {!expanded && <span className="fact-row-body">{fact.body}</span>}
      </button>
      {expanded && (
        <div id={detailId} className="fact-row-expanded">
          {editingCurrent ? (
            <FactEditForm fact={editing} onSave={onSave} onCancel={onCancel} busy={busy} />
          ) : (
            <p className="fact-body">{fact.body}</p>
          )}
          <div className="fact-meta">
            {fact.next_occurrence && <span>{fact.next_occurrence}{fact.recurs === 'yearly' ? ' · yearly' : ''}</span>}
            {fact.source_role && <span>via {fact.source_role}</span>}
            <span className="fact-actions">
              <FactActions fact={fact} onConfirm={onConfirm} onDelete={onDelete}
                           onEdit={editingCurrent ? null : onEdit} busy={busy} />
            </span>
          </div>
        </div>
      )}
    </motion.div>
  )
})

function AddFactForm({ onAdded, toast, busy, setBusy }) {
  const [open, setOpen] = useState(false)
  const [domain, setDomain] = useState('personal')
  const [topic, setTopic] = useState('')
  const [body, setBody] = useState('')
  const [kind, setKind] = useState('fact')
  const [date, setDate] = useState('')

  const save = async () => {
    if (!topic.trim() || !body.trim()) { toast('topic and body required', 'crit'); return }
    setBusy(true)
    try {
      await api('/api/facts', 'POST', {
        domain, topic: topic.trim(), body: body.trim(), kind,
        date: date || null, verified: true,
      })
      toast('memory saved', 'good')
      setTopic(''); setBody(''); setDate(''); setOpen(false)
      onAdded?.()
    } catch (e) { toast(e.message, 'crit') } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button type="button" className="btn add-goal" onClick={() => setOpen(true)}>+ Add memory</button>
    )
  }

  return (
    <div className="fact-add-form card-item">
      <p className="section-label">New memory</p>
      <div className="gf-row">
        <label className="gf-field">
          <span>Domain</span>
          <select value={domain} onChange={(e) => setDomain(e.target.value)}>
            {DOMAIN_ORDER.map((d) => <option key={d} value={d}>{DOMAIN_LABELS[d]}</option>)}
          </select>
        </label>
        <label className="gf-field gf-grow">
          <span>Topic</span>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="partner:favorite-food"
                 autoCapitalize="none" autoCorrect="off" spellCheck={false} />
        </label>
      </div>
      <label className="gf-field gf-grow">
        <span>What to remember</span>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={2} />
      </label>
      <div className="gf-row">
        <label className="gf-field">
          <span>Kind</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.keys(KIND_LABELS).map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </label>
        {kind === 'date' && (
          <label className="gf-field">
            <span>Date</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
        )}
      </div>
      <div className="gf-controls">
        <button type="button" className="btn ghost" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
        <button type="button" className="btn approve" onClick={save} disabled={busy}>Save</button>
      </div>
    </div>
  )
}

export default function MemoryPage({ facts = [], toast, onChange }) {
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(null)
  const [q, setQ] = useState('')
  const query = q.trim().toLowerCase()

  const unconfirmed = useMemo(
    () => facts.filter((f) => !f.verified)
      .filter((f) => !query || `${f.topic} ${f.body} ${f.kind}`.toLowerCase().includes(query))
      .sort((a, b) => (a.days_until ?? 9e9) - (b.days_until ?? 9e9)),
    [facts, query],
  )
  const confirmed = useMemo(() => {
    const verified = facts.filter((f) => f.verified)
    if (!query) return verified
    return verified.filter((f) => `${f.topic} ${f.body} ${f.kind}`.toLowerCase().includes(query))
  }, [facts, query])

  const grouped = useMemo(() => {
    const g = {}
    for (const f of confirmed) (g[f.domain] = g[f.domain] || []).push(f)
    return g
  }, [confirmed])

  const domains = useMemo(
    () => DOMAIN_ORDER.filter((d) => grouped[d]?.length)
      .concat(Object.keys(grouped).filter((d) => !DOMAIN_ORDER.includes(d))),
    [grouped],
  )

  const confirm = async (fact) => {
    setBusy(true)
    try {
      await api(`/api/facts/${fact.id}`, 'PATCH', { verified: true })
      toast('confirmed. Agents will trust it now', 'good')
      onChange?.()
    } catch (e) { toast(e.message, 'crit') } finally { setBusy(false) }
  }

  const remove = async (fact) => {
    setBusy(true)
    try {
      await api(`/api/facts/${fact.id}`, 'DELETE')
      onChange?.()
      toast(`removed "${fact.topic}"`, 'good', async () => {
        try {
          await api('/api/facts', 'POST', {
            domain: fact.domain, topic: fact.topic, body: fact.body, kind: fact.kind,
            date: fact.date || null, verified: fact.verified,
          })
          onChange?.()
        } catch (e) { toast(e.message, 'crit') }
      })
    } catch (e) { toast(e.message, 'crit') } finally { setBusy(false) }
  }

  const startEdit = (fact) => setEditing({ ...fact })

  const saveEdit = async (payload) => {
    if (!payload?.id) return
    setBusy(true)
    try {
      await api(`/api/facts/${payload.id}`, 'PATCH', {
        body: payload.body,
        date: payload.date,
      })
      toast('memory updated', 'good')
      setEditing(null)
      onChange?.()
    } catch (e) { toast(e.message, 'crit') } finally { setBusy(false) }
  }

  const cancelEdit = () => setEditing(null)

  const handlers = { onConfirm: confirm, onDelete: remove, onEdit: startEdit, onSave: saveEdit, onCancel: cancelEdit, busy, editing }

  return (
    <div className="memory-page page-layout page-layout--overview">
      <div className="memory-tools">
        <div className="memory-intro glass-card glass-card-pad">
          <p>Agents read this before they memo or brief. Confirm placeholders, add your own, edit when life changes.</p>
          <AddFactForm onAdded={onChange} toast={toast} busy={busy} setBusy={setBusy} />
        </div>
      </div>
      <div className="memory-records">
        {!facts.length && (
          <div className="empty glass-card glass-card-pad">
            <div className="empty-title">No memory yet</div>
            <p>Samwell Tarly (archivist) fills this weekly. You can add facts anytime above.</p>
          </div>
        )}
        {unconfirmed.length > 0 && (
          <section className="memory-domain memory-attn" aria-labelledby="memory-confirm-heading">
            <h2 id="memory-confirm-heading" className="section-label">Needs your confirmation · {unconfirmed.length}</h2>
            <div className="fact-list">
              <AnimatePresence initial={false}>
                {unconfirmed.map((f) => <FactCard key={f.id} fact={f} {...handlers} />)}
              </AnimatePresence>
            </div>
          </section>
        )}
        {facts.length > 0 && (
          <input type="search" className="memory-search" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search memory" aria-label="Search memory"
                 autoCorrect="off" autoCapitalize="none" spellCheck={false} enterKeyHint="search" />
        )}
        {query && unconfirmed.length + confirmed.length === 0 && (
          <p className="dim">Nothing matches "{q.trim()}".</p>
        )}
        <div className="memory-domains">
          {domains.map((domain) => (
            <section key={domain} className="memory-domain" aria-labelledby={`memory-domain-${domain}`}>
              <h2 id={`memory-domain-${domain}`} className="section-label">{DOMAIN_LABELS[domain] || domain}</h2>
              <div className="fact-list">
                <AnimatePresence initial={false}>
                  {grouped[domain].map((f) => <FactRow key={f.id} fact={f} {...handlers} />)}
                </AnimatePresence>
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
