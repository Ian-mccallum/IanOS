import React, { memo } from 'react'
import { PILLAR_ORDER, PILLAR_ROUTES } from '../lib/pillars.js'

function statusClass(status) {
  if (status === 'OFF TRACK') return 'crit'
  if (status === 'AT RISK') return 'warn'
  if (status === 'ON TRACK') return 'good'
  return 'idle'
}

function PillarStrip({ pillars, onNavigate }) {
  if (!pillars) return null
  return (
    <div className="pillar-strip" aria-label="Life pillars">
      <div className="section-label">Your pillars</div>
      {PILLAR_ORDER.map((id) => {
        const p = pillars[id]
        if (!p) return null
        const att = p.attention_count > 0 && id !== 'partner'
        return (
          <button
            key={id}
            type="button"
            className={`pillar-row${p.off_focus ? ' off-focus' : ''}${att ? ' needs-you' : ''}`}
            onClick={() => onNavigate(PILLAR_ROUTES[id] || id)}
          >
            <span className={`pillar-icon pillar-${id}`} aria-hidden="true">{p.icon}</span>
            <span className="pillar-row-main">
              <span className="pillar-name">{p.label}</span>
              <span className="pillar-detail dim">{p.detail}</span>
            </span>
            {att && <span className={`chip chip-${statusClass(p.status)}`}>{p.attention_count}</span>}
            <span className="pillar-chevron" aria-hidden="true">→</span>
          </button>
        )
      })}
    </div>
  )
}

export default memo(PillarStrip)
