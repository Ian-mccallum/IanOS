const DONE = new Set([
  'filed', 'obtained', 'approved', 'renewed', 'done', 'complete', 'signed', '1', 'auto-renew on',
])

export function isGoalDone(goal) {
  const cv = (goal?.current_value || '').toLowerCase().trim()
  return DONE.has(cv) || Number(goal?.actual) >= Number(goal?.target || 1)
}

export function deadlineGoals(goals, domain) {
  return (goals || []).filter((g) => g.kind === 'deadline' && (!domain || g.domain === domain))
}
