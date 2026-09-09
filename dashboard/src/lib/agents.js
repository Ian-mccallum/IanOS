/**
 * Agent identity, in one place (SPEC-v10 §6).
 *
 * A signature colour and a glyph per role, so the same agent looks the same
 * wherever it appears, a memo, a proposal, its card. Personality is seasoning,
 * not content (the runner's SHARED_RULES): this decorates who is speaking, and
 * never what they said.
 */

export const ROLE_COLORS = {
  scout: 'var(--good)', cfo: 'var(--warn)', physician: 'var(--health)',
  steward: 'var(--personal)', watchdog: 'var(--crit)', counsel: '#818cf8',
  infra: '#38bdf8', archivist: 'var(--muted)', chief: 'var(--accent)',
  lovebird: '#f472b6', advisor: '#c084fc', wealth: '#facc15',
  publicist: '#fb923c', coach: '#fca5a5', family: '#a3e635',
  tutor: '#2dd4bf',
  ian: 'var(--ink)', system: 'var(--muted)',
}

export const ROLE_GLYPHS = {
  scout: '◆', cfo: '$', physician: '✚', steward: '▤', watchdog: '⚠',
  counsel: '§', infra: '⌬', archivist: '❋', chief: '⬡',
  lovebird: '♥', advisor: '△', wealth: '◈', publicist: '✦',
  coach: '◉', family: '○', tutor: '✎', ian: '●', system: '·',
}

export const roleColor = (role) => ROLE_COLORS[role] || 'var(--muted)'
export const roleGlyph = (role) => ROLE_GLYPHS[role] || '·'

// Role frontmatter stores a short day ("mon"). Pluralising that gives "mons".
const DAY_NAMES = {
  mon: 'Mondays', tue: 'Tuesdays', wed: 'Wednesdays', thu: 'Thursdays',
  fri: 'Fridays', sat: 'Saturdays', sun: 'Sundays',
}

/** What the dispatcher will do with this role tonight, in Ian's words. */
export function cadenceLabel(r) {
  if (r.active === false) return 'off'
  if (r.tier === 'daily') return 'every night'
  if (r.tier === 'weekly') {
    const day = DAY_NAMES[String(r.day || '').slice(0, 3).toLowerCase()]
    return day ? `${day}, or when something fires` : 'weekly'
  }
  if (r.tier === 'tripwire') return 'only when something fires'
  return r.tier || '-'
}

/**
 * How often Ian took this agent's advice. Pending is excluded, an undecided
 * proposal is not a rejection. Returns null when there is nothing decided yet,
 * so the card can say "no calls yet" instead of printing a hollow 0%.
 */
export function trustRate(stats) {
  if (!stats) return null
  const decided = (stats.approved || 0) + (stats.rejected || 0)
  if (!decided) return null
  return Math.round((stats.approved / decided) * 100)
}
