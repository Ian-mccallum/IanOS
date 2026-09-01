import React from 'react'

export default function BlockedBadge({ goal }) {
  if (!goal?.blocked_by) return null
  return (
    <span className="goal-blocked chip chip-warn" title={'Complete "' + goal.blocked_by + '" first'}>
      Blocked by {goal.blocked_by}
    </span>
  )
}
