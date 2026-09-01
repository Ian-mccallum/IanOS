// Client-side plan helpers. Time math mirrors core/plan.py so one-tap creation
// lands in the same free slot the server would pick. Times are "HH:MM" strings.

export const DAY_START = 6 * 60    // 06:00, top of the ribbon
export const DAY_END = 23 * 60     // 23:00, bottom of the ribbon
export const LATEST_START = 22 * 60
const STEP = 15

export const toMin = (hhmm) => {
  if (!hhmm || typeof hhmm !== 'string') return null
  const [h, m] = hhmm.split(':')
  return Number(h) * 60 + Number(m)
}

export const toHHMM = (min) => {
  const v = Math.max(0, Math.min(min, 24 * 60 - 1))
  return `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`
}

const roundUp = (min, step = STEP) => Math.ceil(min / step) * step

// Earliest 15-min-aligned start ≥ max(now, 06:00) that fits duration without
// clashing a block or timed commitment; clamps to 22:00 when the day is packed.
export function nextFreeSlot(blocks, commitments, durationMin, nowHHMM) {
  const occ = []
  blocks.forEach((b) => occ.push([toMin(b.start_time), toMin(b.end_time)]))
  commitments.forEach((c) => {
    const s = toMin(c.start_time)
    const e = toMin(c.end_time)
    if (s != null && e != null) occ.push([s, e])
  })
  const clashes = (start) => {
    const end = start + durationMin
    return occ.some(([os, oe]) => start < oe && os < end)
  }
  let cand = roundUp(Math.max(toMin(nowHHMM), DAY_START))
  while (cand <= LATEST_START) {
    if (!clashes(cand)) return [toHHMM(cand), toHHMM(cand + durationMin)]
    cand += STEP
  }
  const lastEnd = occ.length ? Math.max(...occ.map(([, e]) => e)) : cand
  const start = Math.min(roundUp(lastEnd), LATEST_START)
  return [toHHMM(start), toHHMM(start + durationMin)]
}

// Overlapping blocks share width side-by-side. Returns id → {col, cols} where
// cols is the block's cluster width. Non-overlapping blocks get {col:0, cols:1}.
export function layoutColumns(blocks) {
  const items = blocks
    .map((b) => ({ id: b.id, s: toMin(b.start_time), e: toMin(b.end_time) }))
    .sort((a, z) => a.s - z.s || a.e - z.e)
  const out = new Map()
  let cluster = []
  let clusterEnd = -1
  const flush = () => {
    const colEnds = []
    cluster.forEach((it) => {
      let c = colEnds.findIndex((end) => end <= it.s)
      if (c === -1) { c = colEnds.length; colEnds.push(it.e) } else colEnds[c] = it.e
      it.col = c
    })
    cluster.forEach((it) => out.set(it.id, { col: it.col, cols: colEnds.length }))
    cluster = []
    clusterEnd = -1
  }
  items.forEach((it) => {
    if (cluster.length && it.s >= clusterEnd) flush()
    cluster.push(it)
    clusterEnd = Math.max(clusterEnd, it.e)
  })
  if (cluster.length) flush()
  return out
}

// The window the ribbon renders: 06:00-23:00 by default, widened to contain
// anything the day actually holds. Mirrors core/plan.py day_bounds(); the API
// also returns this as `bounds` and that value wins when present.
export function dayBounds(blocks = [], commitments = []) {
  let lo = DAY_START
  let hi = DAY_END
  blocks.forEach((b) => {
    lo = Math.min(lo, toMin(b.start_time) ?? lo)
    hi = Math.max(hi, toMin(b.end_time) ?? hi)
  })
  commitments.forEach((c) => {
    const s = toMin(c.start_time)
    const e = toMin(c.end_time)
    if (s != null) lo = Math.min(lo, s)
    if (e != null) hi = Math.max(hi, e)
  })
  return [Math.max(0, Math.floor(lo / 60) * 60), Math.min(1440, Math.ceil(hi / 60) * 60)]
}

// ---------------------------------------------------------------- quick add
// Deterministic mirror of core/plan.py parse_quick_add(). Never a model call:
// a model in this path would cost money per keystroke and add latency at the
// exact moment Ian needs none (The Line's call_card precedent).

const DUR_RE = /(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\.?$/i
const RANGE_RE = /(?:@|at|from)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to|until|till)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\.?$/i
const AT_RE = /(?:@|at)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\.?$/i
const TRAIL_JUNK = /[\s,;:@-]*(?:\b(?:at|from|on)\b)?[\s,;:@-]*$/i
const LONE_TIME = /^[\s@]*(?:at|from)?[\s@]*\d[\d:apm\s.-]*$/i

// A bare hour is ambiguous. Take the nearest FUTURE reading, falling back to
// the later one when both have passed: "gym 7" at 06:00 is this morning, the
// same words at 09:00 cannot be, so they mean tonight.
function resolveHour(h, minute, meridiem, nowMin) {
  if (!(h >= 0 && h <= 23 && minute >= 0 && minute <= 59)) return null
  if (meridiem) return ((h % 12) + (meridiem.toLowerCase() === 'pm' ? 12 : 0)) * 60 + minute
  if (h === 0 || h > 12) return h * 60 + minute
  const cands = h === 12 ? [720 + minute, minute] : [h * 60 + minute, (h + 12) * 60 + minute]
  const future = cands.filter((c) => c >= nowMin)
  return future.length ? Math.min(...future) : Math.max(...cands)
}

const strip = (text, m) => text.slice(0, m.index).replace(TRAIL_JUNK, '').trim()

export function parseQuickAdd(text, nowHHMM = '09:00', blocks = [], commitments = [], defaultMin = 60) {
  let raw = (text || '').trim()
  if (!raw) return null
  // A lone time fragment ("7", "9pm", "12-1") is not a plan; without this a
  // bare hour becomes a block literally titled "7".
  if (LONE_TIME.test(raw)) return null
  const nowMin = toMin(nowHHMM)
  let start = null
  let end = null

  const mr = RANGE_RE.exec(raw)
  if (mr) {
    const [, h1, m1, mer1, h2, m2, mer2] = mr
    const s = resolveHour(Number(h1), Number(m1 || 0), mer1, nowMin)
    if (s != null) {
      let e = mer2
        ? resolveHour(Number(h2), Number(m2 || 0), mer2, nowMin)
        : (Number(h2) % 12) * 60 + Number(m2 || 0) + Math.floor(s / 720) * 720
      while (e != null && e <= s) e += 720
      if (e != null && e < 1440) { start = s; end = e; raw = strip(raw, mr) }
    }
  }

  if (start == null) {
    let dur = null
    for (let i = 0; i < 2; i += 1) {
      const md = DUR_RE.exec(raw)
      if (md && dur == null) {
        const n = Number(md[1])
        dur = md[2].toLowerCase().startsWith('h') ? Math.round(n * 60) : Math.round(n)
        raw = strip(raw, md)
        continue
      }
      const ma = AT_RE.exec(raw)
      if (ma && start == null && strip(raw, ma)) {
        const s = resolveHour(Number(ma[1]), Number(ma[2] || 0), ma[3], nowMin)
        if (s != null) { start = s; raw = strip(raw, ma); continue }
      }
      break
    }
    dur = dur || defaultMin
    if (start == null) start = toMin(nextFreeSlot(blocks, commitments, dur, nowHHMM)[0])
    end = start + dur
  }

  const title = raw.trim()
  if (!title || start == null || end == null || end <= start) return null
  return { title, start_time: toHHMM(start), end_time: toHHMM(Math.min(end, 1439)) }
}

export const minutesLabel = (mins) => {
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

// ISO date helpers (local, no UTC drift).
export const isoDate = (d) =>
  new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10)

export const addDays = (isoStr, n) => {
  const d = new Date(`${isoStr}T00:00:00`)
  d.setDate(d.getDate() + n)
  return isoDate(d)
}

export const weekdayLabel = (isoStr) =>
  new Date(`${isoStr}T00:00:00`).toLocaleDateString('en-US', { weekday: 'short' })

export const dayNum = (isoStr) => new Date(`${isoStr}T00:00:00`).getDate()
