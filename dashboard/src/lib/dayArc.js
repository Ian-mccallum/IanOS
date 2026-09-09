const WINDOW_START_MIN = 6 * 60   // 06:00
const WINDOW_END_MIN = 24 * 60    // 24:00
const WINDOW_MIN = WINDOW_END_MIN - WINDOW_START_MIN // 1080

function toMinutes(hhmm) {
  const parts = String(hhmm || '').split(':').map(Number)
  const [h, m] = parts
  if (Number.isNaN(h) || Number.isNaN(m)) return null
  return h * 60 + m
}

function pct(min) {
  const clamped = Math.max(WINDOW_START_MIN, Math.min(WINDOW_END_MIN, min))
  return ((clamped - WINDOW_START_MIN) / WINDOW_MIN) * 100
}

export function dayArcLayout(blocks = [], commitments = [], now = new Date()) {
  const segments = []
  for (const b of blocks || []) {
    const start = toMinutes(b.start)
    const end = toMinutes(b.end)
    if (start == null || end == null) continue
    if (end <= WINDOW_START_MIN || start >= WINDOW_END_MIN) continue
    const left = pct(start)
    const width = Math.max(0.4, pct(end) - left)
    segments.push({ left, width, kind: b.status === 'done' ? 'block-done' : 'block-planned' })
  }
  for (const c of commitments || []) {
    const start = toMinutes(c.start)
    if (start == null || start < WINDOW_START_MIN || start >= WINDOW_END_MIN) continue
    segments.push({ left: pct(start), width: 0.3, kind: 'commitment' })
  }
  const nowMin = now.getHours() * 60 + now.getMinutes()
  return {
    segments,
    nowPct: pct(nowMin),
    inWindow: nowMin >= WINDOW_START_MIN && nowMin <= WINDOW_END_MIN,
  }
}

export function minutesUntil(atHHMM, now = new Date()) {
  const target = toMinutes(atHHMM)
  if (target == null) return null
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const diff = target - nowMin
  return diff >= 0 ? diff : null
}

export function pulseState(pulse, now = new Date()) {
  if (!pulse || !pulse.agents_at) {
    return { level: 'dim', breathing: false, ring: false }
  }
  const agentsAt = new Date(String(pulse.agents_at).replace(' ', 'T'))
  const ageHours = (now - agentsAt) / 3600000
  let level = 'dim'
  let breathing = false
  if (ageHours < 26) {
    level = 'accent'
    breathing = true
  } else if (ageHours < 72) {
    level = 'warn'
  }
  let ring = false
  if (pulse.backup_configured) {
    if (!pulse.backup_at) {
      ring = true
    } else {
      const backupAt = new Date(String(pulse.backup_at).replace(' ', 'T'))
      const backupAgeHours = (now - backupAt) / 3600000
      ring = backupAgeHours > 48
    }
  }
  return { level, breathing, ring }
}
