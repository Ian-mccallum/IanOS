import React, { useMemo } from 'react'

const CHAIN_HINTS = [
  { match: /llc/i, short: 'LLC', key: 'llc' },
  { match: /ein/i, short: 'EIN', key: 'ein' },
  { match: /a2p|10dlc|twilio/i, short: 'A2P', key: 'a2p' },
]

const DONE = new Set(['filed', 'obtained', 'approved', 'renewed', 'done', 'complete', 'signed', '1'])

function stepState(goal) {
  const cv = (goal?.current_value || '').toLowerCase().trim()
  if (DONE.has(cv) || cv.includes('auto-renew')) return 'done'
  if (cv === 'in progress' || cv === 'in_progress') return 'active'
  if (cv && cv !== 'not started') return 'active'
  return 'pending'
}

function findStep(goals, hint) {
  return goals.find((g) => hint.match.test(g.name || ''))
}

export default function LegalChain({ goals }) {
  const steps = useMemo(() => {
    const deadlines = (goals || []).filter((g) => g.kind === 'deadline')
    const chain = CHAIN_HINTS.map((hint) => {
      const goal = findStep(deadlines, hint)
      return { ...hint, goal, state: goal ? stepState(goal) : 'missing' }
    }).filter((s) => s.goal || s.key === 'llc')

    if (!chain.some((s) => s.goal)) return null
    return chain
  }, [goals])

  if (!steps?.length) return null

  return (
    <div className="legal-chain">
      <div className="section-label">Legal chain</div>
      <div className="legal-chain-track" role="list">
        {steps.map((s, i) => (
          <React.Fragment key={s.key}>
            {i > 0 && <span className={`legal-chain-arrow${s.state === 'pending' ? ' dim' : ''}`} aria-hidden="true">→</span>}
            <div className={`legal-chain-step state-${s.state}`} role="listitem">
              <span className="legal-chain-dot" aria-hidden="true">
                {s.state === 'done' ? '●' : s.state === 'active' ? '◐' : '○'}
              </span>
              <span className="legal-chain-label">{s.short}</span>
              {s.goal && (
                <span className="legal-chain-meta dim">
                  {s.goal.days_remaining != null ? `${s.goal.days_remaining}d` : s.goal.current_value || '-'}
                </span>
              )}
            </div>
          </React.Fragment>
        ))}
      </div>
      <p className="dim legal-chain-hint">LLC → EIN → A2P. Clockwork SMS needs all three.</p>
    </div>
  )
}
