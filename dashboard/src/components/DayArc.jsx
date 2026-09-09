import { useEffect, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { dayArcLayout, minutesUntil, pulseState } from '../lib/dayArc.js'

export default function DayArc({ header, onOpenPlan, onOpenRoster }) {
  const [now, setNow] = useState(() => new Date())
  const reduced = useReducedMotion()

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(id)
  }, [])

  const arc = header?.arc || {}
  const pulse = header?.pulse || {}
  const { segments, nowPct } = dayArcLayout(arc.blocks, arc.commitments, now)
  const pulseSt = pulseState(pulse, now)
  const mins = arc.next ? minutesUntil(arc.next.at, now) : null
  const nextLabel = arc.next && mins != null ? `${arc.next.label} in ${mins}m` : ''
  const ariaLabel = nextLabel ? `Today's plan, next: ${nextLabel}` : "Today's plan"

  const pulseLabel = !pulse.agents_at
    ? 'Agents have not run yet'
    : `Agents ran · backup ${pulse.backup_configured ? (pulseSt.ring ? 'missed' : 'ok') : 'not configured'}`

  return (
    <div className="day-arc-wrap">
      <button type="button" className="day-arc" onClick={onOpenPlan} aria-label={ariaLabel}>
        <div className="day-arc-track" aria-hidden="true">
          {segments.map((s, i) => (
            <span
              key={i}
              className={`day-arc-seg day-arc-${s.kind}`}
              style={{ left: `${s.left}%`, width: `${s.width}%` }}
            />
          ))}
          {[6, 12, 18, 24].map((h) => (
            <span key={h} className="day-arc-tick" style={{ left: `${((h * 60 - 360) / 1080) * 100}%` }}>
              {h}
            </span>
          ))}
          <span
            className={`day-arc-now${!reduced ? ' day-arc-now-breathe' : ''}`}
            style={{ left: `${nowPct}%` }}
          />
        </div>
        {nextLabel && <span className="day-arc-next">{nextLabel}</span>}
      </button>
      <button
        type="button"
        className={`pulse-dot pulse-${pulseSt.level}${pulseSt.breathing && !reduced ? ' pulse-breathe' : ''}${pulseSt.ring ? ' pulse-ring' : ''}`}
        onClick={onOpenRoster}
        aria-label={pulseLabel}
        title={pulseLabel}
      />
    </div>
  )
}
