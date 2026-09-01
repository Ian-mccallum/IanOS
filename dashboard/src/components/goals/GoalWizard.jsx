import React, { useMemo, useState } from 'react'
import templates from '../../data/goalTemplates.json'
import { api } from '../../lib/api.js'
import { defaultDomainForPillar } from '../../lib/pillars.js'
import GoalForm from './GoalForm.jsx'

const METRIC_OPTIONS = {
  btc: [
    { value: 'clients_signed', label: 'Signed clients' },
    { value: 'audit_calls_today', label: 'Audit calls today' },
    { value: 'follow_ups_today', label: 'Follow-ups today' },
    { value: 'demos_last_7d', label: 'Demos last 7 days' },
    { value: 'burn_this_month', label: 'Monthly burn' },
    { value: '', label: 'Manual' },
  ],
  body: [
    { value: 'gym_weekdays_this_week', label: 'Gym weekdays this week' },
    { value: 'workouts_this_week', label: 'Workouts this week' },
    { value: 'sleep_avg_7d', label: 'Sleep avg (7d)' },
    { value: 'steps_today', label: 'Steps today' },
    { value: '', label: 'Manual' },
  ],
  money: [
    { value: 'portfolio_value', label: 'Portfolio value' },
    { value: 'checking_balance', label: 'Checking balance' },
    { value: '', label: 'Manual' },
  ],
}

function summaryLine(g) {
  const parts = [`Get **${g.target || '-'}${g.unit ? ` ${g.unit}` : ''}**`]
  if (g.name) parts.unshift(g.name)
  if (g.deadline) parts.push(`by **${g.deadline}**`)
  if (g.metric_key) parts.push('(tracked automatically)')
  return parts.join(' · ')
}

export default function GoalWizard({ pillar, toast, onSaved, onCancel, notesDefault = '' }) {
  const [step, setStep] = useState(1)
  const [template, setTemplate] = useState(null)
  const [busy, setBusy] = useState(false)
  const [g, setG] = useState({
    name: '', target: '', unit: '', deadline: '', metric_key: '', notes: notesDefault,
    kind: 'goal', domain: defaultDomainForPillar(pillar), current_value: '', hero: false,
  })

  const filtered = useMemo(
    () => templates.filter((t) => t.custom || t.pillar === pillar || t.pillar === null),
    [pillar],
  )

  const pickTemplate = (t) => {
    if (t.custom) {
      setTemplate(t)
      setStep(3)
      return
    }
    setTemplate(t)
    setG({
      name: t.namePlaceholder || '',
      target: t.target || '',
      unit: t.unit || '',
      deadline: '',
      metric_key: t.metric_key || '',
      notes: t.notes || notesDefault,
      kind: t.kind || 'goal',
      domain: t.domain || defaultDomainForPillar(pillar),
      current_value: t.current_value || '',
      hero: false,
    })
    setStep(2)
  }

  const save = async () => {
    if (!g.name.trim()) { toast('goal needs a name', 'crit'); return }
    setBusy(true)
    try {
      await api('/api/goals', 'POST', {
        ...g,
        deadline: g.deadline || null,
        hero: Boolean(g.hero),
      })
      toast('goal added', 'good')
      onSaved()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setBusy(false)
    }
  }

  if (template?.custom) {
    return (
      <GoalForm
        initial={{ domain: defaultDomainForPillar(pillar), notes: notesDefault }}
        defaultDomain={defaultDomainForPillar(pillar)}
        toast={toast}
        onSaved={onSaved}
        onDeleted={onCancel}
        onCancel={onCancel}
      />
    )
  }

  if (step === 1) {
    return (
      <div className="goal-wizard">
        <p className="section-label">Pick a template</p>
        <div className="wizard-templates">
          {filtered.map((t) => (
            <button key={t.id} type="button" className="wizard-card" onClick={() => pickTemplate(t)}>
              <span className="wizard-card-icon">{t.icon}</span>
              <span className="wizard-card-title">{t.title}</span>
              <span className="wizard-card-desc dim">{t.desc}</span>
            </button>
          ))}
        </div>
        <button type="button" className="btn ghost" onClick={onCancel}>Cancel</button>
      </div>
    )
  }

  if (step === 2) {
    const metrics = METRIC_OPTIONS[pillar] || [{ value: '', label: 'Manual' }]
    return (
      <div className="goal-wizard">
        <p className="section-label">{template?.title}</p>
        <label className="gf-field gf-grow">
          <span>What do you want to hit?</span>
          <input value={g.name} onChange={(e) => setG({ ...g, name: e.target.value })} autoFocus />
        </label>
        <div className="gf-row">
          <label className="gf-field">
            <span>How much?</span>
            <input value={g.target} onChange={(e) => setG({ ...g, target: e.target.value })} />
          </label>
          <label className="gf-field">
            <span>Unit</span>
            <input value={g.unit} onChange={(e) => setG({ ...g, unit: e.target.value })} />
          </label>
          {(g.kind === 'deadline' || g.kind === 'goal') && (
            <label className="gf-field">
              <span>By when?</span>
              <input type="date" value={g.deadline} onChange={(e) => setG({ ...g, deadline: e.target.value })} />
            </label>
          )}
        </div>
        <label className="gf-field gf-grow">
          <span>Track automatically?</span>
          <select value={g.metric_key} onChange={(e) => setG({ ...g, metric_key: e.target.value })}>
            {metrics.map((m) => <option key={m.value || 'manual'} value={m.value}>{m.label}</option>)}
          </select>
        </label>
        <label className="gf-field">
          <input type="checkbox" checked={g.hero} onChange={(e) => setG({ ...g, hero: e.target.checked })} />
          <span style={{ marginLeft: 8 }}>Main focus for this pillar</span>
        </label>
        <div className="gf-controls">
          <button type="button" className="btn ghost" onClick={() => setStep(1)}>Back</button>
          <button type="button" className="btn approve" onClick={() => setStep(3)}>Next</button>
        </div>
      </div>
    )
  }

  return (
    <div className="goal-wizard">
      <p className="section-label">Confirm</p>
      <div className="wizard-summary card-item">
        <strong>{g.name}</strong>
        <p className="dim">{summaryLine(g).replace(/\*\*/g, '')}</p>
      </div>
      <div className="gf-controls">
        <button type="button" className="btn ghost" onClick={() => setStep(2)} disabled={busy}>Back</button>
        <button type="button" className="btn approve" onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save goal'}
        </button>
      </div>
    </div>
  )
}
