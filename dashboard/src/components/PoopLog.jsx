import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import {
  BRISTOL_LABELS,
  QUICK_TIMES,
  bristolLabel,
  clockLabel,
  composeLoggedAt,
  dayInitial,
  dayLine,
  defaultMissedMoment,
  entryDetail,
  missedDayOptions,
  missedTimeProblem,
  nowLocalStamp,
  railLevels,
  sinceLabel,
  weekLine,
} from '../lib/poop.js'
import PoopMark from './PoopMark.jsx'
import Sheet from './Sheet.jsx'

const BRISTOL_SCORES = [1, 2, 3, 4, 5, 6, 7]

/* One tap is the whole interaction, so the tap is where the craft goes.
 *
 * Three things fire at once and they are deliberately different lengths, the
 * way a real plop is: the mark falls and squashes (220ms), five coils arc out
 * on fixed ballistic paths (620ms), two stink lines rise and fade (700ms).
 * Nothing here is random per frame: the coil vectors are a constant, so the
 * burst is the same joke every time rather than a slot machine, and the whole
 * thing is one `key` bump away from replaying. */
const COILS = [
  { x: -58, y: -46, r: -140, s: 0.42, d: 0 },
  { x: -30, y: -68, r: 95, s: 0.34, d: 0.04 },
  { x: 4, y: -78, r: -60, s: 0.46, d: 0.02 },
  { x: 36, y: -64, r: 130, s: 0.32, d: 0.06 },
  { x: 62, y: -40, r: -110, s: 0.4, d: 0.01 },
]

function Burst({ id, reduced }) {
  if (!id) return null
  if (reduced) {
    // Reduced motion still gets the confirmation, just held instead of
    // thrown: one mark fading in and out over the button.
    return (
      <motion.span key={id} className="poop-burst-quiet" aria-hidden="true"
        initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 0] }}
        transition={{ duration: 0.7, times: [0, 0.25, 1] }}>
        <PoopMark size={44} />
      </motion.span>
    )
  }
  return (
    <span className="poop-burst" aria-hidden="true">
      {COILS.map((c, i) => (
        <motion.span key={`${id}-${i}`} className="poop-coil"
          initial={{ x: 0, y: 0, scale: 0.2, rotate: 0, opacity: 0 }}
          animate={{
            x: [0, c.x * 0.72, c.x],
            y: [0, c.y, c.y + 34],
            scale: [0.2, c.s, c.s * 0.86],
            rotate: [0, c.r * 0.6, c.r],
            opacity: [0, 1, 0],
          }}
          transition={{ duration: 0.62, delay: c.d, ease: [0.22, 1, 0.36, 1], times: [0, 0.45, 1] }}>
          <PoopMark size={40} face={false} />
        </motion.span>
      ))}
      {[0, 1].map((i) => (
        <motion.svg key={`${id}-stink-${i}`} className={`poop-stink poop-stink--${i}`}
          viewBox="0 0 12 30" width="12" height="30"
          initial={{ opacity: 0, y: 0 }}
          animate={{ opacity: [0, 0.7, 0], y: -34 }}
          transition={{ duration: 0.7, delay: 0.1 + i * 0.09, ease: 'easeOut' }}>
          <path d="M6 29 C2 24 10 19 6 14 C2 9 10 5 6 1" />
        </motion.svg>
      ))}
      <motion.span className="poop-splat"
        initial={{ scale: 0.3, opacity: 0.55 }}
        animate={{ scale: 1.7, opacity: 0 }}
        transition={{ duration: 0.44, ease: 'easeOut' }} />
    </span>
  )
}

/** The log button. It squashes on press and rebounds, so the plop has weight. */
function LogButton({ onLog, busy, burstId, reduced }) {
  return (
    <div className="poop-log-btn-wrap">
      <Burst id={burstId} reduced={reduced} />
      <motion.button
        type="button" className="poop-log-btn" onClick={onLog} disabled={busy}
        aria-label="Log a poop"
        whileTap={reduced ? undefined : { scale: 0.9 }}
        animate={burstId && !reduced
          ? { scale: [1, 0.86, 1.06, 1], y: [0, 4, -3, 0] }
          : { scale: 1, y: 0 }}
        transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      >
        <PoopMark size={64} blink={busy} />
      </motion.button>
      <span className="poop-log-btn-hint">Tap to log</span>
    </div>
  )
}

function Rail({ rail }) {
  const days = railLevels(rail)
  if (!days.length) return null
  return (
    <ol className="poop-rail" aria-label="Logs over the last 7 days">
      {days.map((d) => (
        <li key={d.day} className={d.count ? 'poop-rail-day' : 'poop-rail-day is-empty'}>
          <span className="poop-rail-bar"
                role="img"
                aria-label={`${d.day}: ${d.count} ${d.count === 1 ? 'log' : 'logs'}`}
                style={{ '--poop-rail-level': `${d.level}%` }}>
            <span />
          </span>
          <span aria-hidden="true">{dayInitial(d.day)}</span>
        </li>
      ))}
    </ol>
  )
}

/* Bristol and the note are the same two optional fields whether you are
   annotating a tap or adding one you forgot, so they are written once. */
function BristolField({ value, onChange }) {
  return (
    <section className="poop-detail-section">
      <h3 className="poop-detail-label">Bristol scale</h3>
      <div className="poop-bristol-row" role="radiogroup" aria-label="Bristol scale, 1 is hard and 7 is liquid">
        {BRISTOL_SCORES.map((n) => (
          <button key={n} type="button" role="radio" aria-checked={value === n}
                  aria-label={`${n}, ${BRISTOL_LABELS[n]}`}
                  className={`poop-bristol${value === n ? ' is-on' : ''}`}
                  onClick={() => onChange(value === n ? null : n)}>
            {n}
          </button>
        ))}
      </div>
      <p className="poop-bristol-caption">
        {value ? bristolLabel(value) : 'Optional. Tap again to clear.'}
      </p>
    </section>
  )
}

function NoteField({ value, onChange }) {
  return (
    <section className="poop-detail-section">
      <h3 className="poop-detail-label">Note</h3>
      <textarea className="poop-note-input" rows={2} value={value} maxLength={280}
                placeholder="Anything worth remembering"
                onChange={(e) => onChange(e.target.value)} />
    </section>
  )
}

/** The optional second beat: Bristol and one line of note, both skippable. */
function DetailSheet({ entry, open, onClose, onSave, saving }) {
  const [bristol, setBristol] = useState(null)
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!open) return
    setBristol(entry?.bristol ?? null)
    setNote(entry?.note || '')
  }, [open, entry])

  return (
    <Sheet open={open} onClose={onClose}
           title={entry ? `Logged ${clockLabel(entry.logged_at)}` : 'Detail'}
           variant="dialog">
      <div className="poop-detail">
        <BristolField value={bristol} onChange={setBristol} />
        <NoteField value={note} onChange={setNote} />
        <div className="poop-detail-actions">
          <button type="button" className="btn" disabled={saving}
                  onClick={() => onSave({ bristol, note })}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}

/**
 * Adding one you forgot. Remembering at 6pm that it happened at 10am is the
 * normal case, so the four presets are the interaction and the time field is
 * the escape hatch, not the other way round: one chip plus Save is two taps.
 */
function MissedSheet({ open, onClose, onSave, saving }) {
  const [day, setDay] = useState(() => defaultMissedMoment().day)
  const [time, setTime] = useState(() => defaultMissedMoment().time)
  const [bristol, setBristol] = useState(null)
  const [note, setNote] = useState('')
  const dayOptions = useMemo(() => missedDayOptions(), [open])

  useEffect(() => {
    if (!open) return
    const seed = defaultMissedMoment()
    setDay(seed.day)
    setTime(seed.time)
    setBristol(null)
    setNote('')
  }, [open])

  const problem = missedTimeProblem(day, time)

  return (
    <Sheet open={open} onClose={onClose} title="Add one you missed" variant="dialog">
      <div className="poop-detail">
        <section className="poop-detail-section">
          <h3 className="poop-detail-label">When</h3>
          <div className="segmented" role="radiogroup" aria-label="Which day">
            {dayOptions.map((option) => (
              <button key={option.day} type="button" role="radio" aria-checked={day === option.day}
                      className={day === option.day ? 'seg-on' : ''}
                      onClick={() => setDay(option.day)}>
                {option.label}
              </button>
            ))}
          </div>
          {/* A preset that has not happened yet is dimmed rather than left
              tappable: reaching the disabled Save through a chip is a dead
              end you only discover after the tap. */}
          <div className="poop-quick-row">
            {QUICK_TIMES.map((quick) => {
              const unreachable = Boolean(missedTimeProblem(day, quick.time))
              return (
                <button key={quick.time} type="button" disabled={unreachable}
                        className={`poop-quick${time === quick.time ? ' is-on' : ''}`}
                        onClick={() => setTime(quick.time)}>
                  {quick.label}
                </button>
              )
            })}
          </div>
          <label className="poop-time-label">
            <span>Exact time</span>
            <input className="poop-time-input" type="time" value={time}
                   onChange={(e) => setTime(e.target.value)} />
          </label>
          {problem && <p className="poop-time-problem">{problem}</p>}
        </section>
        <BristolField value={bristol} onChange={setBristol} />
        <NoteField value={note} onChange={setNote} />
        <div className="poop-detail-actions">
          <button type="button" className="btn" disabled={saving || Boolean(problem)}
                  onClick={() => onSave({ logged_at: composeLoggedAt(day, time), bristol, note })}>
            {saving ? 'Saving…' : 'Add it'}
          </button>
        </div>
      </div>
    </Sheet>
  )
}

/**
 * Body's log (Ian, 2026-09-09). Count, rail, tap.
 *
 * It lives on its own no-store routes rather than /api/state for the same
 * reason the sleep and step values do: state is polled every 15s and cached
 * by the phone's service worker.
 */
export default function PoopLog({ toast }) {
  const [state, setState] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [burstId, setBurstId] = useState(0)
  const [detailFor, setDetailFor] = useState(null)
  const [savingDetail, setSavingDetail] = useState(false)
  const [missedOpen, setMissedOpen] = useState(false)
  const [savingMissed, setSavingMissed] = useState(false)
  const [freshId, setFreshId] = useState(null)
  const reduced = useReducedMotion()
  const requestRef = useRef(0)
  const freshTimer = useRef(null)

  const load = useCallback(async () => {
    const id = ++requestRef.current
    try {
      const next = await api('/api/poop/today?range=7', 'GET', undefined, { cache: 'no-store' })
      if (id === requestRef.current) setState(next)
    } catch {
      /* Mac asleep: the panel keeps whatever it last had and the tap queues. */
    } finally {
      if (id === requestRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    return () => { requestRef.current += 1; clearTimeout(freshTimer.current) }
  }, [load])

  // Optimistic count so the number moves on the same frame as the animation.
  // A queued (offline) tap has no server row yet, so it gets a local id that
  // the next successful load replaces.
  const applyResult = useCallback((result, fallbackId, loggedAt = null) => {
    if (result?.state) {
      setState(result.state)
      return result.entry?.id ?? null
    }
    const localId = `queued-${fallbackId}`
    const at = loggedAt || nowLocalStamp()
    setState((prev) => {
      // A backfill of an earlier day queued offline is real, but it does not
      // belong in today's list: the panel shows one day, and the server's
      // next read is what will move that day's rail.
      if (prev?.day && at.slice(0, 10) !== prev.day) return prev
      const entry = {
        id: localId, day: at.slice(0, 10), logged_at: at,
        bristol: null, note: '', queued: true,
      }
      const entries = [...(prev?.entries || []), entry]
        .sort((a, b) => String(a.logged_at).localeCompare(String(b.logged_at)))
      return prev
        ? { ...prev, entries, today_count: entries.length }
        : { entries, today_count: entries.length, rail: [], per_day_avg: 0, window_days: 7 }
    })
    return localId
  }, [])

  const markFresh = useCallback((id) => {
    setFreshId(id)
    clearTimeout(freshTimer.current)
    freshTimer.current = setTimeout(() => setFreshId(null), 6000)
  }, [])

  const undoLog = useCallback(async (entryId) => {
    if (typeof entryId !== 'number') return
    try {
      const result = await api(`/api/poop/${entryId}`, 'DELETE')
      if (result?.state) setState(result.state)
      toast('Removed.', 'good')
    } catch (e) {
      toast(e.message || 'Could not undo', 'warn')
    }
  }, [toast])

  const logPoop = async () => {
    setBusy(true)
    const localSeq = burstId + 1
    setBurstId(localSeq)
    try {
      const result = await api('/api/poop', 'POST', { note: '' }, { queueable: true })
      const id = applyResult(result, localSeq)
      markFresh(id)
      const count = result?.state?.today_count
      toast(
        result?.queued
          ? 'Logged. Syncs when your Mac wakes.'
          : `${dayLine(count)} ${clockLabel(result?.entry?.logged_at)}`,
        'good',
        typeof id === 'number' ? () => undoLog(id) : null,
      )
    } catch (e) {
      toast(e.message || 'Could not log', 'warn')
    } finally {
      setBusy(false)
    }
  }

  const saveDetail = async ({ bristol, note }) => {
    if (!detailFor || typeof detailFor.id !== 'number') return
    setSavingDetail(true)
    try {
      const result = await api(`/api/poop/${detailFor.id}`, 'PATCH', { bristol, note })
      if (result?.state) setState(result.state)
      setDetailFor(null)
      toast('Detail saved.', 'good')
    } catch (e) {
      toast(e.message || 'Could not save detail', 'warn')
    } finally {
      setSavingDetail(false)
    }
  }

  // The backfill shares the log route: a poop is a poop, and the only thing a
  // missed one carries extra is the moment it actually happened.
  const saveMissed = async ({ logged_at: loggedAt, bristol, note }) => {
    setSavingMissed(true)
    try {
      const result = await api('/api/poop', 'POST', { logged_at: loggedAt, bristol, note },
                               { queueable: true })
      const id = applyResult(result, Date.now(), loggedAt)
      markFresh(id)
      setMissedOpen(false)
      toast(
        result?.queued
          ? 'Added. Syncs when your Mac wakes.'
          : `Added at ${clockLabel(result?.entry?.logged_at)}.`,
        'good',
        typeof id === 'number' ? () => undoLog(id) : null,
      )
    } catch (e) {
      toast(e.message || 'Could not add it', 'warn')
    } finally {
      setSavingMissed(false)
    }
  }

  const removeEntry = async (entry) => {
    if (typeof entry.id !== 'number') return
    try {
      const result = await api(`/api/poop/${entry.id}`, 'DELETE')
      if (result?.state) setState(result.state)
      toast('Removed.', 'good', async () => {
        try {
          const restored = await api(`/api/poop/${entry.id}/restore`, 'POST', {})
          if (restored?.state) setState(restored.state)
        } catch (e) {
          toast(e.message || 'Could not restore', 'warn')
        }
      })
    } catch (e) {
      toast(e.message || 'Could not remove', 'warn')
    }
  }

  const entries = useMemo(() => state?.entries || [], [state])
  const count = state?.today_count ?? 0

  return (
    <section className="poop-panel" aria-labelledby="poop-panel-title">
      <div className="poop-head">
        <h2 id="poop-panel-title" className="section-label">The log</h2>
        {state?.last_logged_at && (
          <span className="poop-since">last · {sinceLabel(state.last_logged_at)}</span>
        )}
      </div>

      <div className="poop-hero">
        <div className="poop-tally">
          <motion.span key={count} className="poop-count"
            initial={reduced ? false : { scale: 0.7, opacity: 0.4 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ type: 'spring', stiffness: 460, damping: 22 }}>
            {loading && !state ? '-' : count}
          </motion.span>
          <span className="poop-tally-label">today</span>
          <p className="poop-day-line">{dayLine(count)}</p>
        </div>
        <LogButton onLog={logPoop} busy={busy} burstId={burstId} reduced={reduced} />
        <button type="button" className="poop-missed-btn" onClick={() => setMissedOpen(true)}>
          Add one you missed
        </button>
      </div>

      <Rail rail={state?.rail} />
      <p className="poop-week-line">{weekLine(state)}</p>

      {entries.length > 0 && (
        <ul className="poop-entries">
          <AnimatePresence initial={false}>
            {entries.map((entry) => (
              <motion.li key={entry.id}
                className={`poop-entry${entry.id === freshId ? ' is-fresh' : ''}`}
                initial={reduced ? false : { opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
                transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
                <PoopMark size={20} className="poop-entry-mark" />
                <button type="button" className="poop-entry-main"
                        disabled={typeof entry.id !== 'number'}
                        onClick={() => setDetailFor(entry)}>
                  <span className="poop-entry-time">{clockLabel(entry.logged_at)}</span>
                  <span className="poop-entry-detail">{entryDetail(entry)}</span>
                </button>
                {typeof entry.id === 'number' && (
                  <button type="button" className="poop-entry-remove"
                          aria-label={`Remove the ${clockLabel(entry.logged_at)} log`}
                          onClick={() => removeEntry(entry)}>×</button>
                )}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}

      <DetailSheet entry={detailFor} open={Boolean(detailFor)} saving={savingDetail}
                   onClose={() => setDetailFor(null)} onSave={saveDetail} />
      <MissedSheet open={missedOpen} saving={savingMissed}
                   onClose={() => setMissedOpen(false)} onSave={saveMissed} />
    </section>
  )
}
