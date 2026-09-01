import React, { useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import { relTime } from '../lib/time.js'
import { roleColor, roleGlyph, cadenceLabel, trustRate } from '../lib/agents.js'

/**
 * The roster (SPEC-v10 §6). Fifteen agents as cards, each with its glyph,
 * codename, what it covers, when it wakes, and its track record.
 *
 * The record is the agent's, never Ian's: "you approved 12 of its 14 calls"
 * tells him which agents he actually trusts. There is no number here that can
 * be read as a verdict on him, which is the same law the streak and The Line
 * are built on.
 */
function AgentCard({ r, onAskAgent }) {
  const color = roleColor(r.role)
  const trust = trustRate(r.stats)
  const s = r.stats || {}
  const domains = String(r.domains || '').split(',').map((d) => d.trim()).filter(Boolean)

  return (
    <div className={`agent-card${r.active === false ? ' inactive' : ''}`} style={{ '--agent': color }}>
      <div className="agent-card-head">
        <span className="agent-glyph" style={{ color, borderColor: color }}>
          {roleGlyph(r.role)}
        </span>
        <div className="agent-id">
          <span className="agent-codename" style={{ color }}>{r.codename}</span>
          <span className="agent-role">{r.role}</span>
        </div>
      </div>

      {r.persona && <p className="agent-persona">{r.persona}</p>}

      <div className="agent-meta">
        {domains.map((d) => <span key={d} className="agent-domain">{d}</span>)}
        <span className="agent-cadence">{cadenceLabel(r)}</span>
      </div>

      <div className="agent-record">
        <span className="agent-last">
          {/* SPEC-v37 §8.6 point 2: a health-gated agent's last_seen just
              gets older forever, which reads as "asleep" rather than
              "permanently off pending a decision Ian hasn't made". */}
          {r.health_sharing_off
            ? 'off, health sharing'
            : s.last_seen ? `spoke ${relTime(s.last_seen)}` : 'not heard from yet'}
        </span>
        {s.made > 0 && (
          <span className="agent-trust">
            {trust == null
              ? `${s.made} proposed · none decided`
              : `you took ${s.approved} of ${s.approved + s.rejected}`}
          </span>
        )}
      </div>
      {r.active !== false && onAskAgent && (
        <button type="button" className="agent-ask" onClick={() => onAskAgent(r.role)}>
          Ask {r.codename || r.role}
        </button>
      )}
    </div>
  )
}

const SORTS = [
  ['default', 'Default'],
  ['trust', 'Trust'],
  ['recent', 'Recent'],
  ['name', 'A-Z'],
]

function sortRoster(roster, sort) {
  if (sort === 'default') return roster
  const list = [...roster]
  if (sort === 'trust') {
    // Nulls (nothing decided yet) sort last, never read as a zero.
    list.sort((a, b) => (trustRate(b.stats) ?? -1) - (trustRate(a.stats) ?? -1))
  } else if (sort === 'recent') {
    list.sort((a, b) => new Date(b.stats?.last_seen || 0) - new Date(a.stats?.last_seen || 0))
  } else if (sort === 'name') {
    list.sort((a, b) => (a.codename || '').localeCompare(b.codename || ''))
  }
  return list
}

export default function RosterPage({ toast, onAskAgent }) {
  const [roster, setRoster] = useState([])
  const [loaded, setLoaded] = useState(false)
  const [sort, setSort] = useState('default')
  const rm = useReducedMotion()

  useEffect(() => {
    api('/api/roster')
      .then((r) => setRoster(Array.isArray(r) ? r : []))
      .catch((e) => toast?.(e.message, 'crit'))
      .finally(() => setLoaded(true))
  }, [])                                                  // eslint-disable-line

  const spokeToday = roster.filter((r) => {
    const t = r.stats?.last_seen
    return t && (Date.now() - new Date(String(t).replace(' ', 'T')).getTime()) < 864e5
  })
  const sorted = sortRoster(roster, sort)

  return (
    <div className="page-stack roster-page">
      {spokeToday.length > 0 && (
        <p className="roster-slate">
          Last 24h: {spokeToday.map((r) => r.codename).join(', ')}
        </p>
      )}
      {roster.length > 1 && (
        <div className="roster-sort" role="group" aria-label="Sort roster">
          {SORTS.map(([id, label]) => (
            <button key={id} type="button"
                    className={`roster-sort-btn${sort === id ? ' active' : ''}`}
                    onClick={() => setSort(id)}>{label}</button>
          ))}
        </div>
      )}
      {!loaded ? (
        <p className="dim">Loading…</p>
      ) : roster.length === 0 ? (
        <div className="empty">
          <div className="empty-title">No agents configured</div>
          <p>See <code>agents/roles/</code> to add one.</p>
        </div>
      ) : (
        <motion.div className="agent-grid"
                    initial={rm ? false : { opacity: 0 }} animate={{ opacity: 1 }}>
          {sorted.map((r) => <AgentCard key={r.role} r={r} onAskAgent={onAskAgent} />)}
        </motion.div>
      )}
    </div>
  )
}
