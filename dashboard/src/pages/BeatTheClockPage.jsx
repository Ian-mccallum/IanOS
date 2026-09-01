import React, { useCallback, useState } from 'react'
import { api } from '../lib/api.js'
import { goalsForPillar } from '../lib/pillars.js'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'
import TheLine from '../components/TheLine.jsx'
import LeadList from '../components/LeadList.jsx'
import InboundStack from '../components/InboundStack.jsx'

export default function BeatTheClockPage({ state, refresh, toast, onCallMode, onBloom }) {
  const [busy, setBusy] = useState(null)
  const [inCall, setInCall] = useState(false)
  const goals = goalsForPillar(state.goals, 'btc')
  const activity = state.activity_today || {}
  const leads = state.leads || {}

  const handleCallMode = useCallback((on) => {
    setInCall(on)
    onCallMode?.(on)
  }, [onCallMode])

  const bump = async (key, label) => {
    setBusy(key)
    try {
      await api('/api/activity', 'POST', { [key]: 1 })
      toast(`${label} logged`, 'good')
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setBusy(null)
    }
  }

  // In call mode The Line is the only thing on screen, the lead is the content
  // and everything else is scaffolding (SPEC-v9).
  if (inCall) {
    return (
      <div className="btc-page btc-in-call">
        <TheLine refresh={refresh} toast={toast}
                 onCallMode={handleCallMode} onBloom={onBloom} />
      </div>
    )
  }

  return (
    <div className="btc-page">
      <InboundStack inbound={state.inbound} refresh={refresh} toast={toast} />
      <TheLine refresh={refresh} toast={toast}
               onCallMode={handleCallMode} onBloom={onBloom} />
      {(leads.callbacks_due > 0 || leads.tier_a_left > 0) && (
        <p className="line-standby dim">
          {leads.callbacks_due > 0 && `${leads.callbacks_due} callback${leads.callbacks_due === 1 ? '' : 's'} owed`}
          {leads.callbacks_due > 0 && leads.tier_a_left > 0 && ' · '}
          {leads.tier_a_left > 0 && `${leads.tier_a_left} tier-A left`}
          {leads.next_lead && ` · first up: ${leads.next_lead.business_name}, ${leads.next_lead.city}`}
        </p>
      )}
      <div className="quick-log-bar">
        <span className="section-label">Quick log</span>
        <div className="quick-log-btns">
          <button type="button" className="btn log" disabled={busy === 'audit_calls'}
                  onClick={() => bump('audit_calls', 'call')}>
            +1 call ({activity.audit_calls || 0})
          </button>
          <button type="button" className="btn log" disabled={busy === 'follow_ups'}
                  onClick={() => bump('follow_ups', 'follow-up')}>
            +1 follow-up ({activity.follow_ups || 0})
          </button>
          <button type="button" className="btn log" disabled={busy === 'demos'}
                  onClick={() => bump('demos', 'demo')}>
            +1 demo ({activity.demos || 0})
          </button>
        </div>
        <p className="dim btc-sub">For calls made off the line. Runs log themselves.</p>
      </div>
      <LeadList />
      <PillarGoalPanel
        pillar="btc"
        title="Beat the Clock goals"
        goals={goals}
        chainGoals={goals}
        burnMonths={state.burn_by_month}
        refresh={refresh}
        toast={toast}
        variant="business"
      />
    </div>
  )
}
