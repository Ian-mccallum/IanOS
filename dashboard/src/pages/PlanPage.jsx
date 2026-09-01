import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import {
  DAY_START, DAY_END, toMin, toHHMM, nextFreeSlot, layoutColumns, dayBounds,
  parseQuickAdd, minutesLabel, isoDate, addDays, weekdayLabel, dayNum,
} from '../lib/plan.js'
import Sheet from '../components/Sheet.jsx'
import { courseTone } from '../lib/courseColors.js'

const PX = 1                       // pixels per minute → 60px per hour
const DURATIONS = [30, 60, 90, 120, 180, 240]
const durLabel = (m) => (m < 60 ? `${m}m` : `${m / 60}h`)   // 30m · 1h · 1.5h · 2h · 3h · 4h
const DONE_LINES = ['Done.', 'Landed it.', 'One down.', 'That\'s the one.']
const DESKTOP = '(min-width: 901px)'

// ingest_log stamps "YYYY-MM-DD HH:MM:SS"; show the clock, fall back to the
// whole string rather than slicing a shape we did not get.
const syncClock = (s) => (typeof s === 'string' && s.length >= 16 ? s.slice(11, 16) : s)

// Monday-anchored week containing `iso`. The old strip was [date-3 … date+3],
// so tapping any chip re-centred all seven and nothing held a stable position
// (SPEC-v15 C4). A week that stays put is what makes the strip learnable.
function weekOf(iso) {
  const d = new Date(`${iso}T00:00:00`)
  const monday = addDays(iso, -((d.getDay() + 6) % 7))
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i))
}

export default function PlanPage({ state, refresh, toast, onOpenSchoolNote }) {
  const rm = useReducedMotion()
  const todayIso = state.today || isoDate(new Date())
  const [date, setDate] = useState(todayIso)
  const [day, setDay] = useState(null)
  const [week, setWeek] = useState(null)
  const [view, setView] = useState('day')
  const [wide, setWide] = useState(() => window.matchMedia?.(DESKTOP).matches ?? false)
  const [now, setNow] = useState(() => new Date())
  const [sheet, setSheet] = useState(null)   // {mode:'create'|'block', ...}
  const [burst, setBurst] = useState(0)
  const [quick, setQuick] = useState('')
  const [atNow, setAtNow] = useState(true)
  const ribbonRef = useRef(null)
  const quickRef = useRef(null)

  const isToday = date === todayIso
  const nowMin = now.getHours() * 60 + now.getMinutes()
  const nowHHMM = toHHMM(nowMin)
  // Week view is a desktop enhancement (osUI L1): the phone keeps one screen,
  // one job. Falling back to 'day' on narrow means a resize can never strand
  // the phone in a seven-column layout.
  const isWeek = view === 'week' && wide

  useEffect(() => {
    const mq = window.matchMedia?.(DESKTOP)
    if (!mq) return undefined
    const on = (e) => setWide(e.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])

  const load = useCallback(async () => {
    try {
      if (view === 'week' && wide) setWeek(await api(`/api/week?date=${date}`))
      setDay(await api(`/api/day?date=${date}`))
    } catch (e) { toast(e.message, 'warn') }
  }, [date, view, wide, toast])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60000)
    return () => clearInterval(t)
  }, [])

  const blocks = day?.blocks || []
  const commitments = day?.commitments || []
  const timed = useMemo(() => commitments.filter((c) => !c.all_day), [commitments])
  const allDay = useMemo(() => commitments.filter((c) => c.all_day), [commitments])

  // The API is the source of truth for the window; dayBounds() is the mirror
  // used before the first response lands (SPEC-v15 C2/L21).
  const [lo, hi] = useMemo(() => {
    const src = isWeek ? week?.bounds : day?.bounds
    if (src) return [src.start_min, src.end_min]
    return isWeek ? [DAY_START, DAY_END] : dayBounds(blocks, timed)
  }, [isWeek, week, day, blocks, timed])
  const hours = useMemo(
    () => Array.from({ length: Math.max(1, hi / 60 - Math.floor(lo / 60)) },
                     (_, i) => Math.floor(lo / 60) + i),
    [lo, hi],
  )
  const gridH = (hi - lo) * PX

  const scrollToNow = useCallback((smooth = true) => {
    const el = ribbonRef.current
    if (!el) return
    el.scrollTo({ top: Math.max(0, (nowMin - lo) * PX - el.clientHeight / 3),
                  behavior: smooth && !rm ? 'smooth' : 'auto' })
  }, [nowMin, lo, rm])

  // Centre once when the day lands; after that the user owns the scroll and
  // the pill is the way back (SPEC-v15 C7).
  const centred = useRef(null)
  useEffect(() => {
    if (!day || !ribbonRef.current) return
    const key = `${date}-${isWeek}`
    if (centred.current === key) return
    centred.current = key
    if (isToday || isWeek) scrollToNow(false)
    else ribbonRef.current.scrollTop = 0
  }, [day, date, isWeek, isToday, scrollToNow])

  // Show "jump to now" only when the now-line is actually off-screen.
  useEffect(() => {
    const el = ribbonRef.current
    if (!el || !(isToday || isWeek)) { setAtNow(true); return undefined }
    const check = () => {
      const y = (nowMin - lo) * PX
      setAtNow(y >= el.scrollTop && y <= el.scrollTop + el.clientHeight)
    }
    check()
    el.addEventListener('scroll', check, { passive: true })
    return () => el.removeEventListener('scroll', check)
  }, [isToday, isWeek, nowMin, lo, day])

  const nextItem = useMemo(() => {
    if (!isToday) return null
    const items = [
      ...blocks.filter((b) => b.status !== 'done').map((b) => ({ start: toMin(b.start_time), title: b.title })),
      ...timed.map((c) => ({ start: toMin(c.start_time), title: c.summary })),
    ].filter((x) => x.start != null && x.start > nowMin).sort((a, b) => a.start - b.start)
    return items[0] || null
  }, [blocks, timed, isToday, nowMin])

  const weekDates = useMemo(() => weekOf(date), [date])

  // ---- mutations
  const openCreate = (startHHMM, suggestion, endHHMM) => {
    const dur = suggestion?.duration_min || 60
    const start = startHHMM || nextFreeSlot(blocks, commitments, dur, nowHHMM)[0]
    setSheet({
      mode: 'create', title: suggestion?.title || '',
      start, end: endHHMM || toHHMM(toMin(start) + dur), goal_id: suggestion?.goal_id ?? null,
    })
  }

  const create = async (body, note = 'planned') => {
    try {
      await api('/api/plan/blocks', 'POST', { date, ...body })
      setSheet(null); toast(note, 'good'); load(); refresh()
      return true
    } catch (e) { toast(e.message, 'warn'); return false }
  }

  const saveCreate = () => {
    if (!sheet.title.trim()) { toast('name the block', 'warn'); return }
    if (toMin(sheet.end) <= toMin(sheet.start)) { toast('end must be after start', 'warn'); return }
    create({ title: sheet.title.trim(), start_time: sheet.start,
             end_time: sheet.end, goal_id: sheet.goal_id })
  }

  // One line of typing instead of tap-modal-form-form-chip-submit. Parsing is
  // deterministic (lib/plan.js mirrors core/plan.py): no model in this path.
  const quickParsed = useMemo(
    () => parseQuickAdd(quick, nowHHMM, blocks, commitments),
    [quick, nowHHMM, blocks, commitments],
  )
  const submitQuick = async () => {
    if (!quickParsed) { toast('try "gym 7" or "deep work 2h at 9"', 'warn'); return }
    if (await create(quickParsed, 'planned')) setQuick('')
  }

  const patchBlock = async (b, body, note) => {
    try {
      await api(`/api/plan/blocks/${b.id}`, 'PATCH', body)
      setSheet(null); if (note) toast(note, 'good'); load(); refresh()
    } catch (e) { toast(e.message, 'warn') }
  }

  const markDone = (b) => {
    setBurst((n) => n + 1)
    patchBlock(b, { status: 'done' }, DONE_LINES[burst % DONE_LINES.length])
  }

  // Delete carries the same undo every other surface got in v13/v14 (L23).
  // Restore also clears the iCloud tombstone server-side, or the next pull
  // would delete the restored block remotely.
  const del = async (b) => {
    try {
      const res = await api(`/api/plan/blocks/${b.id}`, 'DELETE')
      setSheet(null); load(); refresh()
      toast('removed', 'good', async () => {
        try { await api('/api/plan/blocks/restore', 'POST', res.block || b); load(); refresh() }
        catch (e) { toast(e.message, 'warn') }
      })
    } catch (e) { toast(e.message, 'warn') }
  }

  const sweep = async () => {
    try {
      const res = await api('/api/plan/sweep', 'POST', { date })
      const n = res.moved?.length || 0
      if (!n) { toast('nothing to move', 'warn'); return }
      load(); refresh()
      toast(`moved ${n} to tomorrow`, 'good', async () => {
        try {
          await Promise.all(res.moved.map((b) =>
            api(`/api/plan/blocks/${b.id}`, 'PATCH', { date: b.date })))
          load(); refresh()
        } catch (e) { toast(e.message, 'warn') }
      })
    } catch (e) { toast(e.message, 'warn') }
  }

  // ---- drag to move, drag the bottom edge to resize, drag empty space to create
  //
  // A vertical calendar and a vertical scroller want the same gesture, so a
  // block is *picked up* by a long press (300ms), exactly how the OS calendar
  // resolves it. Move more than 8px before that and it was a scroll all along.
  // The touchmove listener has to be non-passive: only a non-passive listener
  // may preventDefault, and without that the ribbon scrolls out from under the
  // block you are dragging.
  const [drag, setDrag] = useState(null)      // {id, mode, delta}: preview only
  const [draw, setDraw] = useState(null)      // {date, from, to}: create preview
  const press = useRef(null)
  const suppressClick = useRef(false)
  const blocksRef = useRef(blocks)
  blocksRef.current = blocks
  const LONG_PRESS_MS = 300
  const GRAB_EDGE = 16                        // bottom strip that resizes

  const beginPress = (clientY, b, target, isMouse = false) => {
    const rect = target.getBoundingClientRect()
    // On a short block (a 15-30m preset), a flat 16px grip can eat more than
    // half the block: cap it so at least two-thirds stays move-only.
    const edge = Math.min(GRAB_EDGE, rect.height / 3)
    press.current = {
      kind: 'block', id: b.id, y0: clientY, delta: 0, dragging: false, isMouse,
      mode: clientY > rect.bottom - edge ? 'resize' : 'move',
      s: toMin(b.start_time), e: toMin(b.end_time),
    }
    // The 300ms arm delay exists to disambiguate a drag from a vertical
    // scroll on TOUCH. A mouse has no competing scroll gesture on this
    // element, so it arms on the same 8px movement threshold instead
    // (see onMove below), with no dead time before the block picks up.
    if (!isMouse) {
      press.current.timer = setTimeout(() => {
        if (!press.current) return
        press.current.dragging = true
        setDrag({ id: b.id, mode: press.current.mode, delta: 0 })
      }, LONG_PRESS_MS)
    }
  }

  // Drag on empty grid draws the block directly, the way every calendar app
  // does it (SPEC-v15 C9). A plain tap still falls through to the cell's own
  // click handler, so one-tap create is unchanged.
  const beginDraw = (clientY, colDate, target, isMouse = false) => {
    const top = target.getBoundingClientRect().top
    const at = lo + Math.round((clientY - top) / PX / 15) * 15
    press.current = {
      kind: 'draw', date: colDate, y0: clientY, anchor: at, cur: at,
      dragging: false, isMouse,
    }
    if (!isMouse) {
      press.current.timer = setTimeout(() => {
        if (!press.current) return
        press.current.dragging = true
        setDraw({ date: colDate, from: at, to: at + 15 })
      }, LONG_PRESS_MS)
    }
  }

  const endPress = useCallback(async () => {
    const p = press.current
    press.current = null
    if (!p) return
    clearTimeout(p.timer)
    if (!p.dragging) return                   // a plain tap: onClick handles it
    suppressClick.current = true              // ...but a drag must not also open it
    if (p.kind === 'draw') {
      setDraw(null)
      const s = Math.min(p.anchor, p.cur)
      const e = Math.max(p.anchor, p.cur)
      if (e - s < 15) return
      setDate(p.date)
      openCreate(toHHMM(s), null, toHHMM(e))
      return
    }
    setDrag(null)
    if (!p.delta) return
    const b = blocksRef.current.find((x) => x.id === p.id)
    if (!b) return
    let s = p.s
    let e = p.e
    if (p.mode === 'move') { s += p.delta; e += p.delta } else { e += p.delta }
    if (s < 0 || e > 24 * 60 || e - s < 15) { toast('out of range', 'warn'); return }
    await patchBlock(b, { start_time: toHHMM(s), end_time: toHHMM(e) },
                     p.mode === 'move' ? 'moved' : 'resized')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast])

  useEffect(() => {
    const el = ribbonRef.current
    if (!el) return undefined
    const onMove = (ev) => {
      const p = press.current
      if (!p) return
      const y = ev.touches ? ev.touches[0].clientY : ev.clientY
      const dy = y - p.y0
      if (!p.dragging) {
        if (Math.abs(dy) <= 8) return
        if (p.isMouse) {
          p.dragging = true
          if (p.kind === 'draw') setDraw({ date: p.date, from: p.anchor, to: p.anchor + 15 })
          else setDrag({ id: p.id, mode: p.mode, delta: 0 })
        } else { clearTimeout(p.timer); press.current = null }
        return
      }
      ev.preventDefault()                      // needs the non-passive listener
      if (p.kind === 'draw') {
        const cur = p.anchor + Math.round(dy / PX / 15) * 15
        if (cur !== p.cur) {
          p.cur = cur
          setDraw({ date: p.date, from: Math.min(p.anchor, cur), to: Math.max(p.anchor, cur) })
        }
        return
      }
      const delta = Math.round(dy / PX / 15) * 15
      if (delta !== p.delta) {
        p.delta = delta
        setDrag({ id: p.id, mode: p.mode, delta })
      }
    }
    const onUp = () => { endPress() }
    el.addEventListener('touchmove', onMove, { passive: false })
    el.addEventListener('mousemove', onMove)
    window.addEventListener('touchend', onUp)
    window.addEventListener('mouseup', onUp)
    return () => {
      el.removeEventListener('touchmove', onMove)
      el.removeEventListener('mousemove', onMove)
      window.removeEventListener('touchend', onUp)
      window.removeEventListener('mouseup', onUp)
    }
  }, [endPress])

  // ---- keyboard (desktop). A calendar a keyboard cannot drive is a calendar
  // that makes you reach for the mouse for every single edit (SPEC-v15 C14).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') { setSheet(null); return }
      const t = e.target
      const typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)
      if (typing || sheet || e.metaKey || e.ctrlKey || e.altKey) return
      const step = isWeek ? 7 : 1
      if (e.key === 'ArrowLeft') { e.preventDefault(); setDate((d) => addDays(d, -step)) }
      else if (e.key === 'ArrowRight') { e.preventDefault(); setDate((d) => addDays(d, step)) }
      else if (e.key === 't' || e.key === 'T') { setDate(todayIso); scrollToNow() }
      else if (e.key === 'n' || e.key === 'N') { e.preventDefault(); openCreate() }
      else if (e.key === '/') { e.preventDefault(); quickRef.current?.focus() }
      else if (wide && (e.key === 'w' || e.key === 'W')) setView('week')
      else if (wide && (e.key === 'd' || e.key === 'D')) setView('day')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheet, isWeek, wide, todayIso, scrollToNow])

  const columns = isWeek
    ? (week?.days || []).map((d) => ({ ...d, timed: d.commitments.filter((c) => !c.all_day) }))
    : [{ date, is_today: isToday, blocks, commitments, timed }]

  const suggestions = day?.suggestions || []
  const icloud = day?.icloud

  return (
    <div className={`plan-page${isWeek ? ' is-week' : ''}`}>
      {/* ---- day strip */}
      <div className="plan-daybar">
        <button type="button" className="plan-arrow" onClick={() => setDate(addDays(date, isWeek ? -7 : -1))}
                aria-label={isWeek ? 'Previous week' : 'Previous day'}>‹</button>
        <div className="plan-days" role="tablist" aria-label="Pick a day">
          {weekDates.map((d) => (
            <button key={d} type="button" role="tab" aria-selected={d === date}
                    className={`plan-day-chip${d === date ? ' on' : ''}${d === todayIso ? ' is-today' : ''}`}
                    onClick={() => setDate(d)}>
              <span className="plan-day-wd">{weekdayLabel(d)}</span>
              <span className="plan-day-num">{dayNum(d)}</span>
            </button>
          ))}
        </div>
        <button type="button" className="plan-arrow" onClick={() => setDate(addDays(date, isWeek ? 7 : 1))}
                aria-label={isWeek ? 'Next week' : 'Next day'}>›</button>
        {!isToday && (
          <button type="button" className="plan-today-btn" onClick={() => setDate(todayIso)}>Today</button>
        )}
        {wide && (
          <div className="plan-viewtoggle" role="group" aria-label="View">
            <button type="button" className={view === 'day' ? 'on' : ''}
                    onClick={() => setView('day')} aria-pressed={view === 'day'}>Day</button>
            <button type="button" className={view === 'week' ? 'on' : ''}
                    onClick={() => setView('week')} aria-pressed={view === 'week'}>Week</button>
          </div>
        )}
      </div>

      {/* ---- quick add */}
      <div className="plan-quick">
        <input ref={quickRef} className="plan-quick-input" value={quick}
               onChange={(e) => setQuick(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); submitQuick() } }}
               placeholder="gym 7 · deep work 2h at 9" aria-label="Quick add a block"
               enterKeyHint="go" />
        {quick.trim() && (
          <span className={`plan-quick-echo${quickParsed ? '' : ' none'}`} aria-live="polite">
            {quickParsed
              ? `${quickParsed.title} · ${quickParsed.start_time}-${quickParsed.end_time}`
              : 'add a time, like "at 9"'}
          </span>
        )}
      </div>

      {/* ---- one-tap suggestions, on the page instead of buried in the sheet */}
      {suggestions.length > 0 && !isWeek && (
        <div className="plan-suggest-row" data-swipe-own="">
          {suggestions.map((s) => (
            <button key={s.key} type="button" className="plan-suggest-chip"
                    onClick={() => openCreate(null, s)}>{s.title}</button>
          ))}
        </div>
      )}

      {/* ---- signals */}
      {(allDay.length > 0 || nextItem || day?.overpack || day?.sailed > 0) && (
        <div className="plan-signals">
          {allDay.map((c) => (
            <span key={c.id} className="plan-allday" title="all-day commitment">{c.summary}</span>
          ))}
          {nextItem && (
            <span className="plan-next">Next: <strong>{nextItem.title}</strong> · in {minutesLabel(nextItem.start - nowMin)}</span>
          )}
          {day?.overpack && <span className="plan-overpack">{day.overpack}</span>}
          {day?.sailed > 0 && (
            <button type="button" className="plan-sweep" onClick={sweep}>
              Move {day.sailed} to tomorrow
            </button>
          )}
        </div>
      )}

      {/* Week headers live ABOVE the scroller, not inside it. Placed in the
          grid they sat at the top of a 1000px scrolling canvas, so the day
          each column belonged to scrolled out of sight immediately. Padding
          and gap mirror .plan-cols exactly so the labels stay over their
          columns. */}
      {isWeek && (
        <div className="plan-weekhead" aria-hidden="true">
          {columns.map((c) => (
            <span key={c.date} className={`plan-weekhead-day${c.date === todayIso ? ' is-today' : ''}${c.date === date ? ' on' : ''}`}>
              <span className="plan-day-wd">{weekdayLabel(c.date)}</span>
              <span className="plan-day-num">{dayNum(c.date)}</span>
            </span>
          ))}
        </div>
      )}

      {/* ---- the ribbon */}
      <div className="plan-ribbon" ref={ribbonRef}>
        <div className="plan-grid" style={{ height: gridH }}>
          {hours.map((h) => (
            <div key={h} className="plan-hour" style={{ top: (h * 60 - lo) * PX }}>
              <span className="plan-hour-label">{String(h).padStart(2, '0')}:00</span>
              <span className="plan-hour-rule" />
            </div>
          ))}

          <div className="plan-cols">
            {columns.map((c) => (
              <Column
                key={c.date} col={c} lo={lo} hi={hi} isWeek={isWeek}
                drag={drag} draw={draw} nowMin={nowMin} todayIso={todayIso}
                courses={state.school?.courses}
                onCellDown={beginDraw} onBlockDown={beginPress}
                onCellClick={(hhmm, colDate) => {
                  if (suppressClick.current) { suppressClick.current = false; return }
                  if (colDate !== date) setDate(colDate)
                  openCreate(hhmm)
                }}
                onBlockClick={(b) => {
                  if (suppressClick.current) { suppressClick.current = false; return }
                  setSheet({ mode: 'block', block: b })
                }}
                onCommitmentClick={onOpenSchoolNote}
              />
            ))}
          </div>

          {(isToday || isWeek) && nowMin >= lo && nowMin <= hi && (
            <div className="plan-now" style={{ top: (nowMin - lo) * PX }}>
              <time className="plan-now-label" dateTime={nowHHMM}>{nowHHMM}</time>
            </div>
          )}
        </div>
      </div>

      {!atNow && (
        <button type="button" className="plan-nowpill" onClick={() => scrollToNow()}>
          Now · {nowHHMM}
        </button>
      )}

      {blocks.length === 0 && !isWeek && (
        <p className="plan-empty-hint dim">
          Type above, or tap any hour to drop a block in.
        </p>
      )}

      {icloud && (
        <p className="plan-icloud dim">
          {!icloud.configured ? 'Calendar sync not configured'
            : icloud.last_sync ? `Calendar synced ${syncClock(icloud.last_sync)}`
              : 'Calendar not synced yet'}
        </p>
      )}

      {/* ---- sheet */}
      {sheet && (
        <PlanSheet
          sheet={sheet} setSheet={setSheet}
          suggestions={suggestions}
          onCreate={saveCreate} onOpenCreate={openCreate}
          onDone={markDone} onDelete={del} onPatch={patchBlock}
          date={date} nextDate={addDays(date, 1)}
        />
      )}

      {/* completion burst */}
      <AnimatePresence>
        {burst > 0 && !rm && (
          <motion.span key={burst} className="plan-burst" aria-hidden="true"
            initial={{ opacity: 0, scale: 0.5, y: 0 }}
            animate={{ opacity: [0, 1, 0], scale: [0.5, 1.2, 1], y: -28 }}
            transition={{ duration: 0.9 }}>✦</motion.span>
        )}
      </AnimatePresence>
    </div>
  )
}

// ------------------------------------------------------------------ a column
//
// One day. Two lanes, always (SPEC-v15 L20): commitments are constraints Ian
// does not control, blocks are intentions he does. They used to share a lane
// at different z-indexes, so a block rendered exactly on top of a synced class
// and hid it completely, untappable. Separate lanes make that collision
// impossible by construction rather than by careful ordering.

function Column({ col, lo, hi, isWeek, drag, draw, nowMin, todayIso, courses,
                  onCellDown, onBlockDown, onCellClick, onBlockClick,
                  onCommitmentClick }) {
  const cols = useMemo(() => layoutColumns(col.blocks), [col.blocks])
  const hours = Array.from({ length: Math.max(1, hi / 60 - Math.floor(lo / 60)) },
                           (_, i) => Math.floor(lo / 60) + i)
  const hasCommits = col.timed.length > 0
  const drawing = draw && draw.date === col.date

  return (
    <div className={`plan-col${hasCommits ? ' has-commits' : ''}${col.date === todayIso ? ' is-today' : ''}`}>
      {/* commitments: read-only, their own lane, never overlapped by a block */}
      <div className="plan-rail" aria-hidden={!hasCommits}>
        {col.timed.map((c) => {
          const s = toMin(c.start_time)
          const e = toMin(c.end_time) ?? s + 60
          const launch = c.school_note_launch
          const height = Math.max(18, (e - s) * PX)
          // Course color is the at-a-glance identifier a world-class calendar
          // gives every class; a personal/iCloud event (no launch, no course
          // code) keeps the neutral grey treatment untouched.
          const tone = launch ? courseTone(launch.course_code, courses) : null
          const style = { top: (s - lo) * PX, height, ...(tone ? { '--course-tone': tone } : {}) }
          const label = `${launch ? 'Open class note for' : ''} ${c.summary} (${c.start_time})`.trim()
          // A short block has no room for a second line without crowding the
          // title; only show the room once there's clearly space for both.
          const showLocation = launch?.location && height >= 36
          const content = (
            <>
              <span className="plan-commit-title">{c.summary}</span>
              {showLocation && <span className="plan-commit-loc">{launch.location}</span>}
            </>
          )
          const className = `plan-commit${tone ? ' plan-commit-course' : ''}`

          // The API adds school_note_launch only for a verified school schedule
          // occurrence. Calendar events merely look alike; they cannot open a
          // class session based on a brittle title/date match in the client.
          if (launch && onCommitmentClick) {
            return (
              <button key={`c-${c.id}`} type="button" className={`${className} plan-commit-school-note`}
                      style={style} title={label} aria-label={label}
                      onClick={() => onCommitmentClick({
                        courseCode: launch.course_code,
                        schoolItemId: launch.school_item_id,
                        calendarEventId: c.id,
                      })}>
                {content}
              </button>
            )
          }

          return (
            <div key={`c-${c.id}`} className={className} style={style} title={label}>
              {content}
            </div>
          )
        })}
      </div>

      {/* intentions: editable, and the only thing that can be dragged */}
      <div className="plan-lane">
        {hours.map((h) => (
          <button key={`cell-${h}`} type="button" className="plan-cell"
                  style={{ top: (h * 60 - lo) * PX, height: 60 * PX }}
                  onMouseDown={(e) => onCellDown(e.clientY, col.date, e.currentTarget.parentNode, true)}
                  onTouchStart={(e) => onCellDown(e.touches[0].clientY, col.date, e.currentTarget.parentNode)}
                  onClick={(e) => {
                    // Start where you tapped, snapped to 15 minutes, not at the
                    // top of the hour: tapping 9:40 and getting 09:00 means
                    // every block needs correcting right after it is made.
                    const y = e.clientY - e.currentTarget.getBoundingClientRect().top
                    const within = Math.min(45, Math.max(0, Math.round(y / PX / 15) * 15))
                    onCellClick(toHHMM(h * 60 + within), col.date)
                  }}
                  aria-label={`Add a block between ${String(h).padStart(2, '0')}:00 and ${String(h + 1).padStart(2, '0')}:00`} />
        ))}

        {drawing && (
          <div className="plan-draw" aria-hidden="true"
               style={{ top: (draw.from - lo) * PX, height: Math.max(4, (draw.to - draw.from) * PX) }}>
            <span>{toHHMM(draw.from)}-{toHHMM(draw.to)}</span>
          </div>
        )}

        {col.blocks.map((b) => {
          const d = drag && drag.id === b.id ? drag : null
          // Preview only: nothing is written until the finger lifts.
          const s = toMin(b.start_time) + (d?.mode === 'move' ? d.delta : 0)
          const e = toMin(b.end_time) + (d ? d.delta : 0)
          const { col: ci = 0, cols: n = 1 } = cols.get(b.id) || {}
          // Past two abreast, stop dividing and cascade. Three-way splitting on
          // a phone left ~100px per block, which after the ellipsis showed two
          // characters of the title (SPEC-v15 C10).
          const cascade = n > 2
          const geom = cascade
            ? { left: `${ci * 12}px`, right: 0, zIndex: 3 + ci }
            : { left: `${(100 / n) * ci}%`, width: `calc(${100 / n}% - 3px)` }
          return (
            <button key={b.id} type="button"
                    className={`plan-block${b.status === 'done' ? ' done' : ''}${b.sailed ? ' sailed' : ''}${b.goal_id ? ' linked' : ''}${cascade ? ' cascade' : ''}${d ? ' dragging' : ''}`}
                    style={{ top: (s - lo) * PX, height: Math.max(22, (e - s) * PX), ...geom }}
                    onTouchStart={(ev) => onBlockDown(ev.touches[0].clientY, b, ev.currentTarget)}
                    onMouseDown={(ev) => onBlockDown(ev.clientY, b, ev.currentTarget, true)}
                    onClick={() => onBlockClick(b)}
                    aria-label={`${b.title}, ${b.start_time} to ${b.end_time}, ${b.status}`}>
              {/* During a resize the START does not move, so showing it meant
                  the number never changed while you dragged the edge. Show the
                  edge actually being mutated (SPEC-v15 C3/L22). */}
              <span className="plan-block-time">
                {d ? (d.mode === 'resize' ? toHHMM(e) : toHHMM(s)) : b.start_time}
              </span>
              <span className="plan-block-title" title={b.title}>
                {b.status === 'done' ? '✓ ' : ''}{b.title}
              </span>
              <span className="plan-block-grip" aria-hidden="true" />
            </button>
          )
        })}

        {isWeek && col.date === todayIso && nowMin >= lo && nowMin <= hi && (
          <div className="plan-col-now" style={{ top: (nowMin - lo) * PX }} aria-hidden="true" />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- the sheet
//
// Real form content (title, start/end pickers, duration presets, goal link)
// is dialog weight, per SPEC-v29 Phase 3's content-weight rule. Migrated onto
// the shared <Sheet>: it supplies the portal, focus trap, Escape listener,
// backdrop-tap, and its own --kb-aware max-height, so the ~20-line bespoke
// visualViewport listener this used to carry is gone, not replaced.

function PlanSheet({ sheet, setSheet, suggestions, onCreate, onOpenCreate, onDone, onDelete, onPatch, date, nextDate }) {
  const isCreate = sheet.mode === 'create'
  const b = sheet.block
  const [editing, setEditing] = useState(false)

  const close = () => setSheet(null)
  const upd = (patch) => setSheet((s) => ({ ...s, ...patch }))

  return (
    <Sheet open onClose={close} title={isCreate ? 'New block' : b.title} variant="dialog">
      {isCreate ? (
        <>
          {suggestions.length > 0 && (
            <div className="plan-suggest">
              {suggestions.map((s) => (
                <button key={s.key} type="button" className="plan-suggest-chip"
                        onClick={() => onOpenCreate(null, s)}>{s.title}</button>
              ))}
            </div>
          )}
          <input className="plan-input" autoFocus placeholder="What's the block?"
                 aria-label="Block title" enterKeyHint="go"
                 value={sheet.title} onChange={(e) => upd({ title: e.target.value })}
                 onKeyDown={(e) => e.key === 'Enter' && onCreate()} />
          <div className="plan-time-row">
            <label className="plan-time-field">
              <span>Start</span>
              <input type="time" step="900" value={sheet.start}
                     onChange={(e) => upd({ start: e.target.value, end: toHHMM(toMin(e.target.value) + (toMin(sheet.end) - toMin(sheet.start))) })} />
            </label>
            <label className="plan-time-field">
              <span>End</span>
              <input type="time" step="900" value={sheet.end}
                     onChange={(e) => upd({ end: e.target.value })} />
            </label>
          </div>
          <div className="plan-dur">
            {DURATIONS.map((d) => (
              <button key={d} type="button"
                      className={`plan-dur-btn${toMin(sheet.end) - toMin(sheet.start) === d ? ' on' : ''}`}
                      onClick={() => upd({ end: toHHMM(toMin(sheet.start) + d) })}>{durLabel(d)}</button>
            ))}
          </div>
          <div className="plan-sheet-actions">
            <button type="button" className="btn approve primary" onClick={onCreate}>Add to plan</button>
            <button type="button" className="btn ghost" onClick={close}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <div className="plan-sheet-head">
            <span className="plan-sheet-time">{b.start_time}-{b.end_time}</span>
            {b.sailed && <span className="plan-sheet-sailed">sailed</span>}
          </div>
          {editing ? (
            <>
              <input className="plan-input" autoFocus value={sheet.editTitle ?? b.title}
                     onChange={(e) => upd({ editTitle: e.target.value })} />
              <div className="plan-time-row">
                <label className="plan-time-field">
                  <span>Start</span>
                  <input type="time" step="900" value={sheet.editStart ?? b.start_time}
                         onChange={(e) => upd({ editStart: e.target.value })} />
                </label>
                <label className="plan-time-field">
                  <span>End</span>
                  <input type="time" step="900" value={sheet.editEnd ?? b.end_time}
                         onChange={(e) => upd({ editEnd: e.target.value })} />
                </label>
              </div>
              <div className="plan-sheet-actions">
                <button type="button" className="btn approve primary" onClick={() => {
                  const start = sheet.editStart ?? b.start_time
                  const end = sheet.editEnd ?? b.end_time
                  onPatch(b, { title: (sheet.editTitle ?? b.title).trim() || b.title, start_time: start, end_time: end }, 'updated')
                }}>Save</button>
                <button type="button" className="btn ghost" onClick={() => setEditing(false)}>Back</button>
              </div>
            </>
          ) : (
            <>
              {/* The title itself is now the Sheet's own header; the green
                  edge said "linked" and nothing said to what. */}
              {b.goal_name && <div className="plan-sheet-goal dim">Linked: {b.goal_name}</div>}
              <div className="plan-sheet-actions">
                {b.status !== 'done' && (
                  <button type="button" className="btn approve primary" onClick={() => onDone(b)}>Done</button>
                )}
                <button type="button" className="btn" onClick={() => setEditing(true)}>Edit</button>
                <button type="button" className="btn"
                        onClick={() => onPatch(b, { date: nextDate }, 'moved to tomorrow')}>Tomorrow</button>
                <button type="button" className="btn ghost" onClick={() => onDelete(b)}>Delete</button>
              </div>
            </>
          )}
        </>
      )}
    </Sheet>
  )
}
