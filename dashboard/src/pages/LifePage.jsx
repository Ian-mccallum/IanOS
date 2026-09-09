import React from 'react'
import { goalsForPillar } from '../lib/pillars.js'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'
import TodayPanel from '../components/TodayPanel.jsx'

export default function LifePage({ state, refresh, toast, onFlyPriorityDot }) {
  const goals = goalsForPillar(state.goals, 'life')
  return (
    <div className="life-page page-layout page-layout--overview">
      <TodayPanel
        tasksToday={state.tasks_today || []}
        tasksDoneToday={state.tasks_done_today || []}
        today={state.today}
        refresh={refresh}
        toast={toast}
        onFlyPriorityDot={onFlyPriorityDot}
      />
      <PillarGoalPanel
        pillar="life"
        title="Life admin"
        goals={goals}
        refresh={refresh}
        toast={toast}
        variant="simple"
        doneStates={new Set((state.meta?.done_states || []).map((s) => s.toLowerCase()))}
      />
    </div>
  )
}
