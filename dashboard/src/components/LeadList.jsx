import React, { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'

// SPEC-v9 Phase D. The list is DELIBERATELY a detour: the queue is the surface,
// and a 1,958-row table is the activation-energy wall this product exists to
// avoid. So it starts collapsed, and nothing on Beat the Clock links to it more
// prominently than The Line.
//
// It exists for the times a queue can't help: "what was that shop in Oswego?",
// "who did I mark not-interested last week?", "how many tier-B are left in the
// south?". Look-up, not a work surface.

const TIERS = ['', 'A', 'B', 'C', 'D']
const STAGES = ['', 'new', 'attempted', 'reached', 'demo', 'won', 'lost', 'parked']
const MARKETS = ['', 'north', 'south']
const PAGE = 25

export default function LeadList() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [tier, setTier] = useState('')
  const [stage, setStage] = useState('')
  const [market, setMarket] = useState('')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState({ leads: [], total: 0 })
  // Starts true, not false: the debounced load fires up to 220ms after
  // opening, and a false start left "nothing matches" flashed over a
  // 1,958-row list for that whole window (SPEC-v14).
  const [busy, setBusy] = useState(true)
  const debounce = useRef(null)

  const load = useCallback(async (o = 0) => {
    setBusy(true)
    try {
      const params = new URLSearchParams({ limit: PAGE, offset: o })
      if (q.trim()) params.set('q', q.trim())
      if (tier) params.set('tier', tier)
      if (stage) params.set('stage', stage)
      if (market) params.set('market', market)
      setData(await api(`/api/leads?${params}`))
      setOffset(o)
    } catch {
      setData({ leads: [], total: 0 })
    } finally {
      setBusy(false)
    }
  }, [q, tier, stage, market])

  useEffect(() => {
    if (!open) return undefined
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => load(0), 220)
    return () => clearTimeout(debounce.current)
  }, [open, load])

  if (!open) {
    return (
      <button type="button" className="btn ghost lead-list-toggle"
              onClick={() => setOpen(true)}>
        Browse the whole list →
      </button>
    )
  }

  const shown = data.leads.length
  const canPrev = offset > 0
  const canNext = offset + shown < data.total

  return (
    <section className="lead-list">
      <div className="lead-list-head">
        <span className="section-label">The list</span>
        <button type="button" className="btn ghost" onClick={() => setOpen(false)}>close</button>
      </div>

      <div className="lead-list-filters">
        <input className="lead-search" type="search" placeholder="name, city, phone, owner"
               value={q} onChange={(e) => setQ(e.target.value)} aria-label="search leads" />
        <select value={tier} onChange={(e) => setTier(e.target.value)} aria-label="tier">
          {TIERS.map((t) => <option key={t} value={t}>{t ? `tier ${t}` : 'any tier'}</option>)}
        </select>
        <select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="stage">
          {STAGES.map((s) => <option key={s} value={s}>{s || 'any stage'}</option>)}
        </select>
        <select value={market} onChange={(e) => setMarket(e.target.value)} aria-label="market">
          {MARKETS.map((m) => <option key={m} value={m}>{m || 'both markets'}</option>)}
        </select>
      </div>

      <p className="lead-list-count dim">
        {busy ? 'searching…'
          : data.total
            ? `${offset + 1}-${offset + shown} of ${data.total.toLocaleString()}`
            : 'nothing matches'}
      </p>

      <div className="lead-rows">
        {/* Desktop only (SPEC-v14 W: mouse+keyboard has room a phone doesn't);
            shares .lead-row's own grid so the columns always line up. */}
        <div className="lead-row lead-row-head" aria-hidden="true">
          <span />
          <span>Business</span>
          <span>Phone</span>
          <span>Stage</span>
        </div>
        {data.leads.map((l) => (
          <div className="lead-row" key={l.id}>
            <span className={`lead-tier tier-${l.tier}`}>{l.tier}</span>
            <div className="lead-row-main">
              <span className="lead-row-name">{l.business_name}</span>
              <span className="lead-row-meta">
                {[l.city, l.service_type].filter(Boolean).join(' · ')}
              </span>
            </div>
            <a className="lead-row-phone" href={`tel:${l.phone}`}>{l.phone || '-'}</a>
            <span className={`lead-row-stage stage-${l.stage}`}>
              {l.stage}{l.attempts ? ` ·${l.attempts}` : ''}
            </span>
          </div>
        ))}
      </div>

      {(canPrev || canNext) && (
        <div className="lead-pager">
          <button type="button" className="btn ghost" disabled={!canPrev}
                  onClick={() => load(Math.max(0, offset - PAGE))}>← back</button>
          <button type="button" className="btn ghost" disabled={!canNext}
                  onClick={() => load(offset + PAGE)}>more →</button>
        </div>
      )}
    </section>
  )
}
