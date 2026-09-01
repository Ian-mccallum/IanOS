import React from 'react'
import { goalsForPillar } from '../lib/pillars.js'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'

export default function LifePage({ state, refresh, toast }) {
  const goals = goalsForPillar(state.goals, 'life')
  return (
    <div className="life-page page-layout page-layout--overview">
      <PillarGoalPanel
        pillar="life"
        title="Life admin"
        goals={goals}
        refresh={refresh}
        toast={toast}
        variant="simple"
      />
    </div>
  )
}
