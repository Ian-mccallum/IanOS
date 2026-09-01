export const PILLAR_ORDER = ['btc', 'body', 'partner', 'school', 'life', 'money']

export const PILLAR_ROUTES = {
  btc: 'btc',
  body: 'body',
  partner: 'partner',
  school: 'school',
  life: 'life',
  money: 'money',
}

export function isPartnerGoal(goal) {
  const notes = (goal?.notes || '').toLowerCase()
  const name = (goal?.name || '').toLowerCase()
  return notes.includes('#partner') || name.includes('partner')
}

export function goalsForPillar(goals, pillar) {
  const list = goals || []
  if (pillar === 'btc') return list.filter((g) => g.domain === 'business')
  if (pillar === 'body') return list.filter((g) => g.domain === 'health')
  if (pillar === 'money') return list.filter((g) => g.domain === 'finance')
  if (pillar === 'school') return list.filter((g) => g.domain === 'school')
  if (pillar === 'partner') return list.filter((g) => g.domain === 'personal' && isPartnerGoal(g))
  if (pillar === 'life') return list.filter((g) => g.domain === 'personal' && !isPartnerGoal(g))
  return []
}

export function defaultDomainForPillar(pillar) {
  const map = {
    btc: 'business',
    body: 'health',
    partner: 'personal',
    school: 'school',
    life: 'personal',
    money: 'finance',
  }
  return map[pillar] || 'business'
}
