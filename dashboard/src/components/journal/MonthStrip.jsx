import React, { useEffect, useState } from 'react'
import { api } from '../../lib/api.js'

/** Soft month jumper, closed days only get a quiet dot (SPEC-v11 Phase D). */
export default function MonthStrip({ onPickDay, toast }) {
  const now = new Date()
  const [ym, setYm] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
  )
  const [days, setDays] = useState({})

  useEffect(() => {
    api(`/api/journal/month/${ym}`)
      .then((d) => setDays(d.days || {}))
      .catch((e) => toast?.(e.message, 'crit'))
  }, [ym, toast])

  const [y, m] = ym.split('-').map(Number)
  const first = new Date(y, m - 1, 1)
  const startPad = first.getDay() // 0 Sun
  const dim = new Date(y, m, 0).getDate()
  const label = first.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })

  const shift = (delta) => {
    const d = new Date(y, m - 1 + delta, 1)
    setYm(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`)
  }

  const cells = []
  for (let i = 0; i < startPad; i++) cells.push(null)
  for (let d = 1; d <= dim; d++) {
    const iso = `${ym}-${String(d).padStart(2, '0')}`
    cells.push({ d, iso, info: days[iso] })
  }

  return (
    <section className="journal-month-strip" aria-label="Jump to a month">
      <div className="journal-month-head">
        <button type="button" className="journal-act" onClick={() => shift(-1)} aria-label="Previous month">‹</button>
        <span>{label}</span>
        <button type="button" className="journal-act" onClick={() => shift(1)} aria-label="Next month">›</button>
      </div>
      <div className="journal-month-grid">
        {['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((w) => (
          <span key={w} className="journal-month-dow">{w}</span>
        ))}
        {cells.map((c, i) => (
          c == null
            ? <span key={`e${i}`} className="journal-month-cell empty" />
            : (
              <button
                key={c.iso}
                type="button"
                className={`journal-month-cell${c.info?.closed ? ' closed' : ''}${c.info?.has_media ? ' media' : ''}`}
                disabled={!c.info?.closed}
                onClick={() => c.info?.closed && onPickDay?.(c.iso)}
                aria-label={c.info?.closed ? `Open ${c.iso}` : c.iso}
              >
                {c.d}
              </button>
            )
        ))}
      </div>
    </section>
  )
}
