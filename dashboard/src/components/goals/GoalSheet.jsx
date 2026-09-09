import { useState } from 'react'
import Sheet from '../Sheet.jsx'
import { api } from '../../lib/api.js'
import { defaultDomainForPillar } from '../../lib/pillars.js'
import { METRIC_OPTIONS } from '../../lib/metricOptions.js'

const EMPTY = {
  text: '', name: '', shape: 'milestone', target: '', unit: '', per: '',
  deadline: '', metric_key: '', firstSteps: [], hero: false,
}

export default function GoalSheet({ open, onClose, pillar, toast, onSaved, notesDefault = '' }) {
  const [g, setG] = useState(EMPTY)
  const [drafting, setDrafting] = useState(false)
  const [busy, setBusy] = useState(false)
  const options = METRIC_OPTIONS[pillar] || [{ value: '', label: 'Manual' }]
  const showMetric = options.length > 1 || g.metric_key

  const reset = () => setG(EMPTY)

  const draft = async () => {
    if (!g.text.trim() || drafting) return
    setDrafting(true)
    try {
      const res = await api('/api/goals/draft', 'POST', { text: g.text, pillar })
      setG((cur) => ({
        ...cur,
        name: res.name || cur.text,
        shape: res.shape || 'milestone',
        target: res.target || '',
        unit: res.unit || '',
        per: res.per || '',
        deadline: res.deadline || '',
        metric_key: res.metric_key || '',
        firstSteps: (res.first_steps || []).map((title) => ({ title, checked: true })),
      }))
    } catch {
      toast?.("couldn't draft that, name and shape it yourself below", 'warn')
      setG((cur) => ({ ...cur, name: cur.text }))
    } finally {
      setDrafting(false)
    }
  }

  const save = async () => {
    const name = (g.name || g.text).trim()
    if (!name) { toast?.('goal needs a name', 'crit'); return }
    setBusy(true)
    try {
      const kind = g.shape === 'milestone' ? 'deadline' : g.shape === 'quota' ? 'quota' : 'goal'
      const domain = defaultDomainForPillar(pillar)
      const goal = await api('/api/goals', 'POST', {
        name,
        kind,
        domain,
        target: g.shape === 'milestone' ? '' : (g.shape === 'quota' && g.per ? `${g.target}-${g.per}` : g.target),
        unit: g.shape === 'milestone' ? '' : g.unit,
        deadline: g.deadline || null,
        metric_key: g.metric_key,
        notes: notesDefault,
        hero: Boolean(g.hero),
      })
      for (const step of g.firstSteps) {
        if (!step.checked || !step.title.trim()) continue
        await api('/api/tasks', 'POST', {
          title: step.title.trim(), goal_id: goal.id, source: 'goal_draft',
        })
      }
      toast?.('goal added', 'good')
      reset()
      onSaved?.()
    } catch (e) {
      toast?.(e.message || 'goal needs a name', 'crit')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet open={open} onClose={() => { reset(); onClose() }} title="New goal" variant="dialog">
      <div className="goal-sheet">
        <label className="gf-field gf-grow">
          Describe it
          <textarea
            rows={2}
            value={g.text}
            onChange={(e) => setG((cur) => ({ ...cur, text: e.target.value }))}
            placeholder="Join AKPSI by October"
          />
        </label>
        <button type="button" className="btn ghost" onClick={draft} disabled={drafting || !g.text.trim()}>
          {drafting ? 'Drafting…' : 'Draft'}
        </button>

        <label className="gf-field gf-grow">
          Name
          <input value={g.name} onChange={(e) => setG((cur) => ({ ...cur, name: e.target.value }))} />
        </label>

        <div className="segmented" role="radiogroup" aria-label="goal shape">
          {['milestone', 'number', 'quota'].map((s) => (
            <button
              key={s}
              type="button"
              role="radio"
              aria-checked={g.shape === s}
              className={g.shape === s ? 'seg-on' : ''}
              onClick={() => setG((cur) => ({ ...cur, shape: s }))}
            >{s}</button>
          ))}
        </div>

        {g.shape !== 'milestone' && (
          <div className="gf-row">
            <label className="gf-field">Target
              <input value={g.target} onChange={(e) => setG((cur) => ({ ...cur, target: e.target.value }))} />
            </label>
            <label className="gf-field">Unit
              <input value={g.unit} onChange={(e) => setG((cur) => ({ ...cur, unit: e.target.value }))} />
            </label>
            {g.shape === 'quota' && (
              <label className="gf-field">Per
                <select value={g.per} onChange={(e) => setG((cur) => ({ ...cur, per: e.target.value }))}>
                  <option value="day">day</option>
                  <option value="week">week</option>
                </select>
              </label>
            )}
          </div>
        )}

        <label className="gf-field">
          By when
          <input type="date" value={g.deadline} onChange={(e) => setG((cur) => ({ ...cur, deadline: e.target.value }))} />
        </label>

        {showMetric && (
          <label className="gf-field gf-grow">
            Track automatically
            <select value={g.metric_key} onChange={(e) => setG((cur) => ({ ...cur, metric_key: e.target.value }))}>
              {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
        )}

        {g.firstSteps.length > 0 && (
          <div className="goal-sheet-steps">
            <p className="section-label">First steps</p>
            {g.firstSteps.map((step, i) => (
              <label key={i} className="goal-sheet-step">
                <input
                  type="checkbox"
                  checked={step.checked}
                  onChange={(e) => setG((cur) => {
                    const firstSteps = [...cur.firstSteps]
                    firstSteps[i] = { ...firstSteps[i], checked: e.target.checked }
                    return { ...cur, firstSteps }
                  })}
                />
                <input
                  value={step.title}
                  onChange={(e) => setG((cur) => {
                    const firstSteps = [...cur.firstSteps]
                    firstSteps[i] = { ...firstSteps[i], title: e.target.value }
                    return { ...cur, firstSteps }
                  })}
                />
              </label>
            ))}
          </div>
        )}

        <label className="goal-sheet-hero">
          <input type="checkbox" checked={g.hero} onChange={(e) => setG((cur) => ({ ...cur, hero: e.target.checked }))} />
          Main focus for this pillar
        </label>

        <div className="gf-controls">
          <span className="gf-spacer" />
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn approve" onClick={save} disabled={busy}>
            {busy ? 'Saving…' : 'Save goal'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}
