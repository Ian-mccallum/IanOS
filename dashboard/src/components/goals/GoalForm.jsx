import React, { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api.js'

const EMPTY_GOAL = {
  name: '', kind: 'goal', domain: 'business', target: '', unit: '',
  deadline: '', current_value: '', notes: '', metric_key: '', hero: false,
  depends_on_goal_id: null,
}

function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

export default function GoalForm({ initial, onSaved, onCancel, onDeleted, toast, defaultDomain, allGoals = [] }) {
  const editing = Boolean(initial?.id)
  const [g, setG] = useState({
    ...EMPTY_GOAL, ...initial,
    deadline: initial?.deadline || '',
    hero: Boolean(initial?.hero),
    domain: initial?.domain || defaultDomain || 'business',
    depends_on_goal_id: initial?.depends_on_goal_id ?? null,
  })
  const chainOptions = (allGoals || []).filter(
    (og) => og.kind === 'deadline' && og.id !== initial?.id && og.domain === g.domain,
  )
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const nameRef = useRef(null)
  useEffect(() => { nameRef.current?.focus() }, [])

  const set = (k) => (e) => setG({ ...g, [k]: e.target.value })

  const save = async () => {
    if (!g.name.trim()) { toast('goal needs a name', 'crit'); return }
    setBusy(true)
    try {
      const body = {
        ...g,
        deadline: g.deadline || null,
        hero: Boolean(g.hero),
        depends_on_goal_id: g.depends_on_goal_id ? Number(g.depends_on_goal_id) : null,
      }
      if (editing) await api(`/api/goals/${initial.id}`, 'PATCH', body)
      else await api('/api/goals', 'POST', body)
      toast(editing ? 'goal updated' : 'goal added', 'good')
      onSaved()
    } catch (e) { toast(e.message, 'crit') } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!confirmDelete) { setConfirmDelete(true); return }
    setBusy(true)
    try {
      await api(`/api/goals/${initial.id}`, 'DELETE')
      toast('goal removed', 'good')
      onDeleted()
    } catch (e) { toast(e.message, 'crit'); setBusy(false) }
  }

  return (
    <div className="goal-form">
      <div className="gf-row">
        <label className="gf-field gf-grow">
          <span>What do you want to hit?</span>
          <input ref={nameRef} value={g.name} onChange={set('name')} placeholder="e.g. Land client #1" />
        </label>
      </div>
      <div className="gf-row">
        <label className="gf-field"><span>Target</span>
          <input value={g.target} onChange={set('target')} placeholder="1 · 5 · filed" /></label>
        <label className="gf-field"><span>Unit</span>
          <input value={g.unit} onChange={set('unit')} placeholder="clients · weekdays" /></label>
        <label className="gf-field"><span>By when</span>
          <input type="date" value={g.deadline || ''} onChange={set('deadline')} /></label>
      </div>
      <details className="gf-advanced">
        <summary>More options</summary>
        <div className="gf-row">
          <div className="gf-field">
            <span>Kind</span>
            <div className="segmented" role="radiogroup" aria-label="goal kind">
              {['goal', 'quota', 'deadline'].map((k) => (
                <button key={k} type="button" role="radio" aria-checked={g.kind === k}
                        className={g.kind === k ? 'seg-on' : ''}
                        onClick={() => setG({ ...g, kind: k })}>{cap(k)}</button>
              ))}
            </div>
          </div>
          <label className="gf-field gf-grow">
            <span>Track automatically</span>
            <input value={g.metric_key} onChange={set('metric_key')} placeholder="clients_signed" />
          </label>
        </div>
        <label className="gf-field gf-grow"><span>Notes</span>
          <input value={g.notes} onChange={set('notes')} placeholder="agents read this" /></label>
        {chainOptions.length > 0 && (
          <label className="gf-field gf-grow">
            <span>Blocked until (optional)</span>
            <select
              value={g.depends_on_goal_id || ''}
              onChange={(e) => setG({ ...g, depends_on_goal_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">None (not blocked)</option>
              {chainOptions.map((og) => (
                <option key={og.id} value={og.id}>{og.name}</option>
              ))}
            </select>
          </label>
        )}
        <label className="gf-field">
          <span>Main focus</span>
          <input type="checkbox" checked={g.hero} onChange={(e) => setG({ ...g, hero: e.target.checked })} />
        </label>
      </details>
      <div className="gf-controls">
        {editing && (
          <button className="btn reject" onClick={remove} disabled={busy}>
            {confirmDelete ? 'Confirm delete' : 'Delete'}
          </button>
        )}
        <span className="gf-spacer" />
        <button className="btn ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn approve" onClick={save} disabled={busy}>{editing ? 'Save' : 'Add goal'}</button>
      </div>
    </div>
  )
}
