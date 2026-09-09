import React, { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../../lib/api.js'
import { defaultDomainForPillar } from '../../lib/pillars.js'
import GoalForm from './GoalForm.jsx'
import GoalSheet from './GoalSheet.jsx'
import LegalChain from './LegalChain.jsx'
import BlockedBadge from './BlockedBadge.jsx'

function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

function statusLabel(s) {
  const labels = { 'ON TRACK': 'On track', 'AT RISK': 'At risk', 'OFF TRACK': 'Off track', 'NO DATA': 'No data' }
  return labels[s] || s
}

function statusLevel(s) {
  if (s === 'ON TRACK') return 'good'
  if (s === 'AT RISK') return 'warn'
  if (s === 'OFF TRACK') return 'crit'
  return 'idle'
}

function goalOpacity(goal) {
  if (!goal.off_focus) return 1
  if (goal.kind === 'deadline' && goal.days_remaining != null && goal.days_remaining < 7) return 1
  return 0.55
}

function fmtMoneyPrecise(n) {
  if (n == null) return '-'
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 })
}

function StatusChip({ level, children }) {
  return <span className={`chip chip-${level}`}>{children}</span>
}

function Meter({ value, max, level, label }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className="meter" role="img" aria-label={label}>
      <div className={`meter-fill fill-${level}`} style={{ transform: `scaleX(${pct / 100})` }} />
    </div>
  )
}

function Editable({ goal, editingId, setEditingId, refresh, toast, defaultDomain, allGoals, pillar, children }) {
  const rm = useReducedMotion()
  if (editingId === goal.id) {
    return (
      <motion.div initial={rm ? false : { opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}>
        <GoalForm initial={goal} toast={toast} defaultDomain={defaultDomain} allGoals={allGoals} pillar={pillar}
                  onSaved={() => { setEditingId(null); refresh() }}
                  onDeleted={() => { setEditingId(null); refresh() }}
                  onCancel={() => setEditingId(null)} />
      </motion.div>
    )
  }

  const archive = async () => {
    try {
      await api(`/api/goals/${goal.id}/archive`, 'POST')
      refresh()
      toast(`archived "${goal.name}"`, 'good', async () => {
        await api(`/api/goals/${goal.id}/archive?restore=true`, 'POST')
        refresh()
      })
    } catch (e) { toast(e.message, 'crit') }
  }

  return (
    <SwipeRow goal={goal} onEdit={() => setEditingId(goal.id)} onArchive={archive}>
      <div className="editable" style={{ opacity: goalOpacity(goal) }}>
        {children}
        <div className="editable-glyphs">
          <button className="edit-glyph" aria-label={`Edit ${goal.name}`} onClick={() => setEditingId(goal.id)}>✎</button>
          {/* Always-available, not just the touch swipe-reveal: "goals are
              archived, never deleted, from the UI" (CLAUDE.md) has to hold on
              every input device, and the swipe reveal is display:none at
              desktop widths (SPEC-v14 W4). Same visibility as Edit's pencil. */}
          <button type="button" className="archive-glyph" aria-label={`Archive ${goal.name}`} onClick={archive}>⤓</button>
        </div>
      </div>
    </SwipeRow>
  )
}

/**
 * Swipe left on a goal to reveal Edit / Archive (SPEC-v10 §4.2).
 *
 * `data-swipe-own` tells the pillar-swipe ring to keep its hands off any touch
 * that starts here, otherwise one drag would both open this row and navigate
 * to another pillar. Archive is a soft retire with an Undo, never a delete:
 * metrics resolve off goal ids, so a re-created goal would not be a restore.
 */
export function SwipeRow({ goal, onEdit, onArchive, archiveLabel = 'Archive', children }) {
  const [dx, setDx] = useState(0)
  const start = useRef(null)
  // 66px per revealed button. A row with nothing to edit (a task, whose text
  // is its whole content) reveals one button, not a dead "Edit" beside it.
  const REVEAL = onEdit ? 132 : 66
  // Same axis-judgment as lib/swipe.js's pillar ring: decide once, on the
  // first 12px of travel, whichever direction dominates. Without this an
  // ordinary vertical scroll of the goal list reads as a horizontal drag on
  // its very first move event and yanks the row sideways.
  const DECIDE = 12

  const onStart = (e) => {
    const t = e.touches[0]
    start.current = { x: t.clientX, y: t.clientY, base: dx, axis: null }
  }
  const onMove = (e) => {
    const s = start.current
    if (!s) return
    const t = e.touches[0]
    const rawDx = t.clientX - s.x
    if (s.axis === null) {
      const rawDy = t.clientY - s.y
      if (Math.hypot(rawDx, rawDy) < DECIDE) return
      s.axis = Math.abs(rawDx) > Math.abs(rawDy) ? 'x' : 'y'
    }
    if (s.axis === 'y') return   // a scroll, not ours: leave it to the page
    setDx(Math.max(-REVEAL, Math.min(0, s.base + rawDx)))     // left only, and only this far
  }
  const onEnd = () => {
    const s = start.current
    start.current = null
    if (s?.axis !== 'x') return   // never engaged: don't snap a resting row
    setDx((d) => (d < -REVEAL / 2 ? -REVEAL : 0))   // snap open or shut
  }

  return (
    <div className="swipe-row" data-swipe-own="">
      <div className="swipe-actions" aria-hidden={dx === 0}>
        {onEdit && <button type="button" onClick={() => { setDx(0); onEdit() }}>Edit</button>}
        <button type="button" className="swipe-archive" onClick={() => { setDx(0); onArchive() }}>{archiveLabel}</button>
      </div>
      {/* .swipe-face is opaque at every dx, including rest: the Edit/Archive
          buttons are anchored behind the row's own right edge and bleed
          through the row's text otherwise (styles.css). `.shifted` only
          flags the dragged state for anything else that keys off it. */}
      <div className={`swipe-face${dx ? ' shifted' : ''}`}
           style={{ transform: `translateX(${dx}px)` }}
           onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd}
           onTouchCancel={onEnd}>
        {children}
      </div>
    </div>
  )
}

/**
 * The target, editable where it is written. Changing a number was a five-step
 * trip through the whole goal form; it is now tap, type, done (SPEC-v10 §4.2).
 * The form still exists for everything else, this only owns the common case.
 */
function InlineTarget({ goal, refresh, toast }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(String(goal.target ?? ''))
  const unit = goal.unit ? ` ${goal.unit}` : ''

  // goal is a fresh object every 15s poll; without this, an external update
  // to the same target (an approved proposal, another tab) never reaches the
  // local buffer, and the next unrelated tap-to-edit-and-blur silently PATCHes
  // the stale mount-time value back over it.
  useEffect(() => {
    if (!editing) setVal(String(goal.target ?? ''))
  }, [goal.target, editing])

  const commit = async () => {
    setEditing(false)
    const next = val.trim()
    if (!next || next === String(goal.target ?? '')) return
    try {
      // PATCH is partial server-side, so only the target travels.
      await api(`/api/goals/${goal.id}`, 'PATCH', { target: next })
      toast(`${goal.name}: target ${next}`, 'good')
      refresh()
    } catch (e) {
      setVal(String(goal.target ?? ''))
      toast(e.message, 'crit')
    }
  }

  if (editing) {
    return (
      <span className="goal-target-edit">
        target
        <input
          autoFocus
          className="goal-target-input"
          inputMode="decimal"
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); e.currentTarget.blur() }
            if (e.key === 'Escape') { setVal(String(goal.target ?? '')); setEditing(false) }
          }}
          aria-label={`Target for ${goal.name}`}
        />
        {goal.unit}
      </span>
    )
  }
  return (
    <button type="button" className="goal-target-btn" onClick={() => setEditing(true)}>
      target <span className="goal-target-val">{goal.target ?? '-'}</span>{unit}
    </button>
  )
}

function splitActual(label) {
  const parts = String(label || '-').split(' · ')
  return [parts[0], parts.slice(1).join(' · ') || null]
}

function GoalRow({ goal, ed, meter, value, valueSub, sub, defaultDomain }) {
  return (
    <Editable goal={goal} {...ed} defaultDomain={defaultDomain}>
      <div className="goal-row">
        <div className="goal-row-main">
          <span className="goal-name">{goal.name}</span>
          {sub && <div className="goal-row-sub">{sub}</div>}
        </div>
        <div>{meter}</div>
        <div className="goal-row-value">
          <span className="goal-val">{value}</span>
          {valueSub && <span className="goal-row-value-sub">{valueSub}</span>}
        </div>
      </div>
    </Editable>
  )
}

function QuotaRow({ goal, ed, defaultDomain }) {
  const target = Number(String(goal.target).split('-')[0]) || 1
  const today = Number(goal.actual) || 0
  const level = today >= target ? 'good' : today >= target / 2 ? 'warn' : 'crit'
  const [val, valSub] = splitActual(goal.actual_label)
  return (
    <GoalRow goal={goal} ed={ed} defaultDomain={defaultDomain}
             sub={<InlineTarget goal={goal} refresh={ed.refresh} toast={ed.toast} />}
             meter={<Meter value={today} max={target} level={level} label={goal.name} />}
             value={val} valueSub={valSub} />
  )
}

function DeadlineRow({ goal, ed, defaultDomain }) {
  const level = goal.days_remaining == null ? 'idle'
    : goal.days_remaining < 7 ? 'crit'
    : goal.days_remaining < 14 ? 'warn' : 'good'
  const done = ed.doneStates.has(String(goal.current_value || '').toLowerCase())
  const toggle = async () => {
    await api(`/api/goals/${goal.id}`, 'PATCH', { current_value: done ? '' : 'done' })
    ed.refresh()
  }
  return (
    <Editable goal={goal} {...ed} defaultDomain={defaultDomain}>
      <div className="deadline-row">
        <button
          type="button"
          className={`deadline-check${done ? ' checked' : ''}`}
          onClick={toggle}
          aria-label={`Mark "${goal.name}" ${done ? 'not done' : 'done'}`}
        >
          <span className="deadline-check-mark">✓</span>
        </button>
        {goal.deadline && (
          <StatusChip level={level}>
            {goal.days_remaining == null ? 'No date'
              : goal.days_remaining < 0 ? `${-goal.days_remaining}d late`
              : `${goal.days_remaining}d left`}
          </StatusChip>
        )}
        <span className="deadline-name">{goal.name}</span>
        <BlockedBadge goal={goal} />
        {!done && <span className="dim">{goal.current_value || goal.actual_label || '-'}</span>}
      </div>
    </Editable>
  )
}

function GenericGoalRow({ goal, ed, defaultDomain }) {
  const tgt = Number(goal.target) || 1
  const act = Number(goal.actual) || 0
  const level = act >= tgt ? 'good' : act >= tgt * 0.5 ? 'warn' : 'crit'
  const [val, valSub] = splitActual(goal.actual_label)
  return (
    <GoalRow goal={goal} ed={ed} defaultDomain={defaultDomain}
             sub={<InlineTarget goal={goal} refresh={ed.refresh} toast={ed.toast} />}
             meter={<StatusChip level={statusLevel(goal.status)}>{statusLabel(goal.status)}</StatusChip>}
             value={val} valueSub={valSub} />
  )
}

export function BusinessGoals({ goals, burnMonths, ed, chainGoals, allGoals }) {
  const client = goals.find((g) => g.hero) || goals.find((g) => /client/i.test(g.name))
  const burn = goals.find((g) => (g.name || '').toLowerCase().includes('burn'))
  const quotas = goals.filter((g) => g.kind === 'quota')
  const deadlines = goals.filter((g) => g.kind === 'deadline')
  const others = goals.filter((g) => g.kind === 'goal' && g !== client && g !== burn)
  const burnNow = burn ? Number(burn.actual) || 0 : 0
  const burnLevel = burnNow > 150 ? 'crit' : burnNow > 120 ? 'warn' : 'good'
  const allBtc = chainGoals || goals

  return (
    <>
      <LegalChain goals={allBtc} doneStates={ed.doneStates} />
      {client && (
        <Editable goal={client} {...ed} defaultDomain="business">
          <div className="goal-hero">
            <div className="hero-num">{client.actual}<span className="hero-denom">/{client.target}</span></div>
            <div className="hero-meta">
              <div className="hero-name">Beat the Clock: first client</div>
              <StatusChip level={Number(client.actual) >= 1 ? 'good' : client.days_remaining < 14 ? 'crit' : 'warn'}>
                {Number(client.actual) >= 1 ? 'Signed' : `${client.days_remaining}d left`}
              </StatusChip>
            </div>
          </div>
        </Editable>
      )}
      {burn && (
        <Editable goal={burn} {...ed} defaultDomain="business">
          <div className="goal-block">
            <div className="goal-row" style={{ borderTop: 'none', paddingTop: 0 }}>
              <div className="goal-row-main">
                <span className="goal-name">Burn this month</span>
                <div className="goal-row-sub">Clockwork ops · $150 cap</div>
              </div>
              <Meter value={burnNow} max={150} level={burnLevel} label="burn" />
              <div className="goal-row-value"><span className="goal-val">${burnNow.toFixed(2)}</span></div>
            </div>
            <div className="burn-months">
              {(burnMonths || []).map((m) => (
                <div key={m.month} className="burn-month">
                  <span className="dim">{m.month}</span>
                  <div className="mini-track">
                    <div className={`mini-fill ${m.burn > 150 ? 'fill-crit' : 'fill-accent'}`}
                         style={{ width: `${Math.min(100, (m.burn / 220) * 100)}%` }} />
                  </div>
                  <span className={m.burn > 150 ? 'crit-text' : ''}>${m.burn.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        </Editable>
      )}
      {quotas.length > 0 && (
        <div className="goal-block">
          <div className="section-label">Daily quotas</div>
          {quotas.map((q) => <QuotaRow key={q.id} goal={q} ed={ed} defaultDomain="business" />)}
        </div>
      )}
      {deadlines.length > 0 && (
        <div className="goal-block">
          <div className="section-label">Deadlines</div>
          {deadlines.map((g) => <DeadlineRow key={g.id} goal={g} ed={ed} defaultDomain="business" />)}
        </div>
      )}
      {others.map((g) => <GenericGoalRow key={g.id} goal={g} ed={ed} defaultDomain="business" />)}
    </>
  )
}

export function SimpleGoals({ goals, ed, defaultDomain, allGoals }) {
  const quotas = goals.filter((g) => g.kind === 'quota')
  const deadlines = goals.filter((g) => g.kind === 'deadline')
  const rest = goals.filter((g) => g.kind === 'goal')
  return (
    <>
      {quotas.map((q) => <QuotaRow key={q.id} goal={q} ed={ed} defaultDomain={defaultDomain} />)}
      {deadlines.map((g) => <DeadlineRow key={g.id} goal={g} ed={ed} defaultDomain={defaultDomain} />)}
      {rest.map((g) => <GenericGoalRow key={g.id} goal={g} ed={ed} defaultDomain={defaultDomain} />)}
    </>
  )
}

function needsAttention(g) {
  return g.hero || (g.name || '').toLowerCase().includes('burn') || g.status !== 'ON TRACK'
}

export default function PillarGoalPanel({
  pillar,
  title,
  goals,
  chainGoals,
  burnMonths,
  refresh,
  toast,
  variant = 'simple',
  notesDefault = '',
  doneStates = new Set(),
}) {
  const [editingId, setEditingId] = useState(null)
  const [adding, setAdding] = useState(false)
  const [hideOnTrack, setHideOnTrack] = useState(true)
  const defaultDomain = defaultDomainForPillar(pillar)
  const ed = { editingId, setEditingId, refresh, toast, allGoals: goals, pillar, doneStates }
  const shown = hideOnTrack ? (goals || []).filter(needsAttention) : (goals || [])
  const hidden = (goals || []).filter(needsAttention).length < (goals || []).length
    ? (goals || []).filter((g) => !needsAttention(g)).length : 0

  return (
    <div className="pillar-goal-panel">
      <section className="panel pillar-goal-panel__surface">
        <header className="panel-head">
          <h2>{title}</h2>
          <button type="button" className="btn add-goal" onClick={() => setAdding(!adding)}>
            {adding ? 'Cancel' : 'Add goal'}
          </button>
        </header>
        <div className="panel-body goals">
          <GoalSheet
            open={adding}
            onClose={() => setAdding(false)}
            pillar={pillar}
            toast={toast}
            notesDefault={notesDefault}
            onSaved={() => { setAdding(false); refresh() }}
          />
          {variant === 'business' ? (
            <BusinessGoals goals={shown} chainGoals={chainGoals || goals} burnMonths={burnMonths} ed={ed} allGoals={goals} />
          ) : (
            <SimpleGoals goals={shown} ed={ed} defaultDomain={defaultDomain} allGoals={goals} />
          )}
          {hidden > 0 && (
            <button type="button" className="goals-reveal" onClick={() => setHideOnTrack(!hideOnTrack)}>
              {hideOnTrack ? `Show ${hidden} on track ✓` : 'Show only what needs attention'}
            </button>
          )}
        </div>
      </section>
    </div>
  )
}
