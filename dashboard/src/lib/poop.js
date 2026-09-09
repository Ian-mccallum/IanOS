/* Pure derivations for Body's log. No React, no fetch, no clock of its own:
 * every function that needs "now" takes it, so the tests can pin it.
 *
 * The server owns the counts (db.poop_state is the single read path); this
 * file only turns them into the things a screen needs: a bar height, a
 * readable clock, and the day's line. */

export const BRISTOL_LABELS = {
  1: 'Separate hard lumps',
  2: 'Lumpy sausage',
  3: 'Cracked sausage',
  4: 'Smooth sausage',
  5: 'Soft blobs',
  6: 'Mushy, ragged edges',
  7: 'Entirely liquid',
}

/** Bristol 4 is the middle of the scale, so it anchors the row's center. */
export function bristolLabel(score) {
  return BRISTOL_LABELS[score] || ''
}

/**
 * Bar heights for the 7-day rail, scaled against the busiest day in view so
 * a quiet week still draws a readable shape instead of seven stubs. A logged
 * day never falls below 14%: zero and one must look different.
 */
export function railLevels(rail) {
  const days = Array.isArray(rail) ? rail : []
  const peak = days.reduce((max, d) => Math.max(max, Number(d?.count) || 0), 0)
  return days.map((d) => {
    const count = Number(d?.count) || 0
    if (!count) return { ...d, count: 0, level: 0 }
    const share = peak > 0 ? count / peak : 0
    return { ...d, count, level: Math.round(14 + share * 86) }
  })
}

/** 'YYYY-MM-DD HH:MM:SS' (the DB's naive local shape) or an ISO string. */
export function parseLocal(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = new Date(value.includes('T') ? value : value.replace(' ', 'T'))
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export function clockLabel(value) {
  const at = parseLocal(value)
  if (!at) return '-'
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(at)
}

export function dayInitial(value) {
  const parsed = typeof value === 'string' ? new Date(`${value}T12:00:00`) : null
  if (!parsed || Number.isNaN(parsed.getTime())) return '-'
  return new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(parsed)
}

/** "last · 6h ago". Days once it passes 48h; nothing alarming ever. */
export function sinceLabel(lastLoggedAt, now = new Date()) {
  const at = parseLocal(lastLoggedAt)
  if (!at) return ''
  const mins = Math.floor((now.getTime() - at.getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 48) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

/* The day's line. It reacts to volume and nothing else: there is no target
 * here, no streak, and no state this can enter that reads as a verdict on
 * Ian (osui: no shame, --crit banned on this surface). The joke is the
 * reward, so the tally is the only input. */
const DAY_LINES = [
  'Nothing logged yet.',
  'One down.',
  'Two. Productive.',
  'Three. Hat trick.',
  'Four. Fully committed.',
  'Five. That is a lot of poops.',
  'Six. Historic.',
]

export function dayLine(count) {
  const n = Math.max(0, Number(count) || 0)
  if (n >= DAY_LINES.length) return `${n}. Tell nobody.`
  return DAY_LINES[n]
}

/** The line under the rail. Carries data or it does not exist. */
export function weekLine(state) {
  const avg = Number(state?.per_day_avg)
  const days = Number(state?.window_days) || 7
  if (!Number.isFinite(avg) || avg <= 0) return `no logs in ${days} days`
  return `${avg.toFixed(1)}/day over ${days} days`
}

/**
 * The second line of an entry row. Bristol and note are independent, so both
 * show when both exist; an entry with neither says what to do about it.
 */
export function entryDetail(entry) {
  if (entry?.queued) return 'saved on this phone'
  const parts = []
  if (entry?.bristol) parts.push(`type ${entry.bristol} · ${bristolLabel(entry.bristol)}`)
  if (entry?.note) parts.push(entry.note)
  return parts.length ? parts.join(' · ') : 'Add detail'
}

/* ------------------------------------------------------- the backfill door
 * Forgetting is the normal case, not the exception, so remembering at 6pm
 * that it happened at 10am has to cost about as much as the tap would have.
 * The presets are what make that one tap: the time field is there for the
 * times the presets are wrong, not for every entry. */

export const QUICK_TIMES = [
  { label: 'Morning', time: '08:00' },
  { label: 'Midday', time: '12:00' },
  { label: 'Afternoon', time: '15:00' },
  { label: 'Evening', time: '19:00' },
]

/** How far back the server will accept a backdated log. Kept in step by hand
 *  with POOP_BACKFILL_MAX_DAYS in api/main.py. */
export const BACKFILL_MAX_DAYS = 14

function pad(n) {
  return String(n).padStart(2, '0')
}

export function isoDay(when) {
  return `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`
}

/**
 * An hour ago, rounded down to five minutes: the likeliest thing to forget.
 * It returns the day as well as the clock because an hour before 00:20 is
 * yesterday, and seeding the sheet with today plus 23:20 would open it on a
 * time that is refused for being in the future.
 */
export function defaultMissedMoment(now = new Date()) {
  const at = new Date(now.getTime() - 60 * 60 * 1000)
  at.setMinutes(Math.floor(at.getMinutes() / 5) * 5, 0, 0)
  return { day: isoDay(at), time: `${pad(at.getHours())}:${pad(at.getMinutes())}` }
}

/** 'YYYY-MM-DD' + 'HH:MM' into the naive-local shape the table stores. */
export function composeLoggedAt(day, time) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day || '') || !/^\d{2}:\d{2}$/.test(time || '')) return null
  return `${day} ${time}:00`
}

/**
 * Why a chosen moment cannot be saved, or '' when it can. The same two bounds
 * the server enforces, checked here so the refusal arrives before the tap
 * rather than as a 422 after it.
 */
export function missedTimeProblem(day, time, now = new Date()) {
  const composed = composeLoggedAt(day, time)
  if (!composed) return 'Pick a time.'
  const at = new Date(composed.replace(' ', 'T'))
  if (Number.isNaN(at.getTime())) return 'Pick a time.'
  if (at.getTime() > now.getTime() + 2 * 60 * 1000) return 'That is still ahead of you.'
  if (at.getTime() < now.getTime() - BACKFILL_MAX_DAYS * 86400000) {
    return `Only the last ${BACKFILL_MAX_DAYS} days.`
  }
  return ''
}

/** Today and yesterday, labelled. Anything older is typed into the date field. */
export function missedDayOptions(now = new Date()) {
  const yesterday = new Date(now.getTime() - 86400000)
  return [
    { label: 'Today', day: isoDay(now) },
    { label: 'Yesterday', day: isoDay(yesterday) },
  ]
}

/** Now, in the naive-local shape the table stores. */
export function nowLocalStamp(now = new Date()) {
  return `${isoDay(now)} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}
