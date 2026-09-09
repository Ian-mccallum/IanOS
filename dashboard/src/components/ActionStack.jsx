import React, { memo, useState } from 'react'
import { api } from '../lib/api.js'
import StarMark from './StarMark.jsx'

const ACTIVITY_FIELDS = new Set(['audit_calls', 'follow_ups'])

function interactionFor(item) {
  return item?.interaction && typeof item.interaction === 'object'
    ? item.interaction
    : { type: item?.interaction }
}

function ActionStack({
  items = [],
  toast,
  refresh,
  onNavigate,
  onGymConfirm,
  gymBusy = false,
}) {
  const [busy, setBusy] = useState(null)

  const bump = async (item) => {
    const interaction = interactionFor(item)
    const field = interaction.field || interaction.ref_id
    if (!ACTIVITY_FIELDS.has(field)) return
    setBusy(item.key)
    try {
      const result = await api('/api/activity', 'POST', { [field]: 1 }, { queueable: true })
      const label = field === 'audit_calls' ? 'call' : 'follow-up'
      toast(result?.queued ? `${label} saved. Syncs when your Mac wakes` : `${label} logged`, 'good')
      refresh()
    } catch (error) {
      toast(error.message, 'crit')
    } finally {
      setBusy(null)
    }
  }

  const completeTask = async (item) => {
    const id = item.interaction?.ref_id ?? item.ref_id
    await api(`/api/tasks/${id}/done`, 'POST', {}, { queueable: true })
    refresh()
  }

  const run = async (item) => {
    const interaction = interactionFor(item)
    if (interaction.type === 'navigate') {
      onNavigate(item.route)
    } else if (interaction.type === 'gym_confirm') {
      await onGymConfirm()
    } else if (interaction.type === 'activity_increment') {
      await bump(item)
    } else if (interaction.type === 'task_complete') {
      await completeTask(item)
      return
    }
  }

  const visibleItems = (items || []).slice(0, 3)
  if (!visibleItems.length) {
    return (
      <div className="action-stack">
        <div className="section-label">Also on deck</div>
        <p className="action-clear dim">Nothing else needs your attention.</p>
      </div>
    )
  }

  return (
    <div className="action-stack">
      <div className="section-label">Also on deck</div>
      {visibleItems.map((item) => {
        const interaction = interactionFor(item)
        const itemBusy = busy === item.key

        return (
          <div key={item.key} className="action-stack-item card-item">
            {interaction.type === 'proposal_decision' ? (
              <div className="action-proposal">
                <p className="action-proposal-text">
                  {item.label}
                  {item.reason && <span className="action-sub">{item.reason}</span>}
                </p>
                <div className="action-proposal-btns">
                  <button type="button" className="btn ghost" onClick={() => onNavigate(item.route)}>
                    Review proposal
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                className={`action-btn${interaction.type === 'gym_confirm' ? ' action-gym' : ''}`}
                onClick={() => run(item)}
                disabled={itemBusy || (interaction.type === 'gym_confirm' && gymBusy)}
              >
                {/* A starred task is Ian's own pick, not a system suggestion:
                    it carries the same star he tapped on Life, so the two
                    surfaces read as one thing. */}
                {item.kind === 'task' && <StarMark on size={13} className="action-star" />}
                {item.label}
                {item.reason && <span className="action-sub">{item.reason}</span>}
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default memo(ActionStack)
