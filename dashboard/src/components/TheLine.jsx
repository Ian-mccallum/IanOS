import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'

// SPEC-v9 "The Line". Three beats: brief -> live -> card, then the next lead.
//
// Design laws enforced here (do not soften):
//   * --crit is never used on this surface. A lead is never late, never red.
//   * No percentage, no streak, no lifetime counter. A run is the unit, and a
//     run resets by design so it cannot be broken.
//   * The run tally ticks once for ANY outcome, a no-answer counts exactly as
//     much as a booked demo, because Ian controls the dial and not the pickup.
//   * Every outcome is one tap, instantly undoable, and never confirmed.

const OUTCOMES = [
  { id: 'no_answer', label: 'No answer', key: '1' },
  { id: 'voicemail', label: 'Voicemail', key: '2' },
  { id: 'gatekeeper', label: 'Gatekeeper', key: '3' },
  { id: 'reached', label: 'Reached', key: '4' },
  { id: 'booked', label: 'Booked demo', key: '5', win: true },
  { id: 'not_interested', label: 'Not interested', key: '6' },
]

const RECEIPT = {
  no_answer: 'No answer · logged',
  voicemail: 'Voicemail · logged',
  gatekeeper: 'Gatekeeper · logged',
  reached: 'You got through.',
  booked: 'Demo booked.',
  not_interested: 'Passed · logged',
  bad_number: 'Bad number · parked',
}

// The pause is the reward (SPEC-v9 §8). A win holds; a non-event does not
// linger, and is never commented on, encouragement after a no-answer implies
// something needed forgiving.
const MA_MS = { reached: 1400, booked: 1800 }
const QUICK_MS = 420
const UNDO_MS = 8000
const RUN_TARGETS = [5, 10, 20]

// A real phone call routinely runs past the 90s background-relock window
// (SPEC-v12): without this, the whole shell unmounts mid-call, the run's
// queue/index/note vanish with it, and the server-side run is never closed.
// sessionStorage survives the relock (only the two lock keys are cleared),
// so a snapshot here is what "Resume run N of M" is built from after unlock.
const SNAPSHOT_KEY = 'ianos.line.snapshot.v1'

function saveSnapshot(snap) {
  try {
    if (snap) sessionStorage.setItem(SNAPSHOT_KEY, JSON.stringify(snap))
    else sessionStorage.removeItem(SNAPSHOT_KEY)
  } catch { /* ignore */ }
}

function loadSnapshot() {
  try {
    const raw = sessionStorage.getItem(SNAPSHOT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function fmtClock(s) {
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function bizDaysFromNow(n) {
  const d = new Date()
  let added = 0
  while (added < n) {
    d.setDate(d.getDate() + 1)
    if (d.getDay() !== 0 && d.getDay() !== 6) added += 1
  }
  return d.toISOString().slice(0, 10)
}

export default function TheLine({ refresh, toast, onCallMode, onBloom }) {
  const rm = useReducedMotion()
  const [run, setRun] = useState(null)
  const [queue, setQueue] = useState([])
  const [idx, setIdx] = useState(0)
  const [phase, setPhase] = useState('idle')      // idle | brief | live | card | summary
  const [elapsed, setElapsed] = useState(0)
  const [note, setNote] = useState('')
  const [receipt, setReceipt] = useState(null)    // { outcome, win }
  const [undo, setUndo] = useState(null)          // { touchId, label }
  const [summary, setSummary] = useState(null)
  const [busy, setBusy] = useState(false)
  const [resumable, setResumable] = useState(() => loadSnapshot())
  const noteRef = useRef(null)
  const telRef = useRef(null)

  const lead = queue[idx] || null
  const card = lead?.call_card || null
  const inCall = phase !== 'idle' && phase !== 'summary'

  useEffect(() => {
    onCallMode?.(inCall || phase === 'summary')
    // A stray tap away from BtC mid-call must not leave the whole app dimmed
    // and re-laid-out forever: this component is self-sealing on unmount.
    return () => onCallMode?.(false)
  }, [inCall, phase, onCallMode])

  // Snapshot whenever there's a live run worth surviving a relock; clear it
  // once the run is genuinely over (idle/summary) so a stale snapshot never
  // outlives its run.
  useEffect(() => {
    if (phase === 'brief' || phase === 'live' || phase === 'card') {
      saveSnapshot({ runId: run?.id, target: run?.target, dialed: run?.dialed, leadId: lead?.id, idx, note })
    } else {
      saveSnapshot(null)
    }
  }, [run?.id, run?.target, run?.dialed, idx, phase, note, lead?.id])

  // elapsed timer: counts UP, never toward a target, never colored
  useEffect(() => {
    if (phase !== 'live') return undefined
    const t = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [phase])

  useEffect(() => {
    if (!undo) return undefined
    const t = setTimeout(() => setUndo(null), UNDO_MS)
    return () => clearTimeout(t)
  }, [undo])

  const loadQueue = useCallback(async (limit) => {
    const d = await api(`/api/leads/queue${limit ? `?limit=${limit}` : ''}`)
    setQueue(d.queue || [])
    return d.queue || []
  }, [])

  const startRun = async (target) => {
    setBusy(true)
    try {
      const d = await api('/api/runs', 'POST', { target })
      const q = await loadQueue(target)
      if (!q.length) {
        toast('Nothing in the line right now.', 'good')
        setPhase('idle')
        return
      }
      setRun(d.run)
      setIdx(0)
      setPhase('brief')
    } catch (e) {
      toast(e.message, 'warn')
    } finally {
      setBusy(false)
    }
  }

  // After a relock mid-call, land him ready to log what happened rather than
  // re-briefing the same lead: he was almost certainly on the actual call
  // (via the OS Phone app) when the PWA backgrounded and unmounted.
  const resumeRun = async () => {
    const snap = resumable
    if (!snap) return
    setBusy(true)
    try {
      const q = await loadQueue(snap.target)
      if (!q.length) {
        saveSnapshot(null)
        setResumable(null)
        toast('That run already finished.', 'good')
        return
      }
      let nextIdx = q.findIndex((l) => l.id === snap.leadId)
      if (nextIdx === -1) nextIdx = Math.min(snap.idx ?? 0, q.length - 1)
      setRun({ id: snap.runId, target: snap.target, dialed: snap.dialed })
      setIdx(nextIdx)
      setNote(snap.note || '')
      setResumable(null)
      setPhase('card')
    } catch (e) {
      toast(e.message, 'warn')
    } finally {
      setBusy(false)
    }
  }

  const discardResume = () => {
    saveSnapshot(null)
    setResumable(null)
  }

  const startCall = () => {
    if (!lead) return
    // The impossible moment: the number is already dialing before the surface
    // finishes transitioning. Intention -> action with nothing in between.
    telRef.current?.click()
    setElapsed(0)
    setNote('')
    setPhase('live')
  }

  const advance = useCallback(async () => {
    setReceipt(null)
    const next = idx + 1
    if (run && next >= (run.target || 0)) {
      try {
        const d = await api(`/api/runs/${run.id}/end`, 'POST')
        setSummary(d.summary)
      } catch { /* a failed close should never trap him in the run */ }
      setPhase('summary')
      refresh?.()
      return
    }
    if (next >= queue.length) {
      const q = await loadQueue(run?.target)
      if (!q.length) {
        // The queue is empty before the target was hit: still end the run and
        // show what actually happened, not a blank "no calls." after real
        // dials, and not a run left open for "Run again" to double up on.
        if (run) {
          try {
            const d = await api(`/api/runs/${run.id}/end`, 'POST')
            setSummary(d.summary)
          } catch { /* a failed close should never trap him in the run */ }
        }
        setPhase('summary')
        refresh?.()
        return
      }
      setIdx(0)
    } else {
      setIdx(next)
    }
    setPhase('brief')
  }, [idx, run, queue.length, loadQueue, refresh])

  const logOutcome = async (outcome, extra = {}) => {
    if (!lead || busy) return
    setBusy(true)
    try {
      const res = await api(`/api/leads/${lead.id}/touch`, 'POST', {
        kind: 'call',
        outcome,
        note: note.trim(),
        duration_s: elapsed,
        run_id: run?.id,
        ...extra,
      })
      setRun(res.run || run)
      setUndo({ touchId: res.touch.id, label: RECEIPT[outcome] || 'Logged' })
      setReceipt({ outcome, win: outcome === 'booked' || outcome === 'reached' })
      if (res.milestones?.length && !rm) onBloom?.(res.milestones)
      refresh?.()

      const hold = MA_MS[outcome] || QUICK_MS
      setTimeout(advance, hold)
    } catch (e) {
      toast(e.message, 'warn')
    } finally {
      setBusy(false)
    }
  }

  const doUndo = async () => {
    if (!undo) return
    try {
      await api(`/api/leads/touches/${undo.touchId}`, 'DELETE')
      setUndo(null)
      toast('Undone.', 'good')
      refresh?.()
      const q = await loadQueue(run?.target)
      setQueue(q)
    } catch (e) {
      toast(e.message, 'warn')
    }
  }

  const skip = () => { setReceipt(null); advance() }

  const exit = useCallback(async () => {
    if (run) { try { await api(`/api/runs/${run.id}/end`, 'POST') } catch { /* ignore */ } }
    setPhase('idle'); setRun(null); setQueue([]); setIdx(0); setSummary(null)
    refresh?.()
  }, [run, refresh])

  // keyboard: the fastest path on desktop
  useEffect(() => {
    if (!inCall) return undefined
    const onKey = (e) => {
      if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') {
        if (e.key === 'Escape') e.target.blur()
        return
      }
      if (e.key === 'Escape') { exit(); return }
      if (e.key.toLowerCase() === 'u' && undo) { doUndo(); return }
      if (phase === 'brief') {
        if (e.code === 'Space') { e.preventDefault(); startCall() }
        if (e.key.toLowerCase() === 's') skip()
        return
      }
      if (phase === 'live') {
        if (e.key.toLowerCase() === 'n') { e.preventDefault(); noteRef.current?.focus() }
        if (e.code === 'Space') { e.preventDefault(); setPhase('card') }
        return
      }
      if (phase === 'card') {
        const hit = OUTCOMES.find((o) => o.key === e.key)
        if (hit) logOutcome(hit.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const heatClass = useMemo(() => `line-heat-${Math.min(run?.heat ?? 0, 5)}`, [run])

  // ------------------------------------------------------------- idle
  if (phase === 'idle') {
    return (
      <LineResting onStart={startRun} busy={busy}
                   resumable={resumable} onResume={resumeRun} onDiscardResume={discardResume} />
    )
  }

  // ---------------------------------------------------------- summary
  if (phase === 'summary') {
    return (
      <LineSummary summary={summary} rm={rm}
                   onAgain={() => { setSummary(null); startRun(run?.target || 10) }}
                   onDone={exit} />
    )
  }

  return (
    <div className={`line-stage ${heatClass}`}>
      <a ref={telRef} href={`tel:${lead?.phone || ''}`} className="line-tel" aria-hidden="true" tabIndex={-1}>dial</a>

      <div className="line-topbar">
        <span className="line-reason">{lead?.tier} · {lead?.queue_reason}</span>
        <span className="line-progress">
          {phase === 'live' ? <><span className="line-live-dot" />live {fmtClock(elapsed)}</>
            : `run ${(run?.dialed ?? 0) + 1} of ${run?.target ?? 0}`}
        </span>
      </div>

      <AnimatePresence mode="wait">
        {receipt ? (
          <motion.div key="receipt" className={`line-receipt${receipt.win ? ' win' : ''}`}
            layoutId={rm ? undefined : `outcome-${receipt.outcome}`}
            initial={rm ? false : { opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={rm ? { opacity: 0 } : { opacity: 0, x: -40 }}
            transition={{ type: 'spring', stiffness: 380, damping: 30 }}>
            <p className="line-receipt-text">{RECEIPT[receipt.outcome]}</p>
          </motion.div>
        ) : (
          /* Keyed by LEAD, never by phase: brief -> live must recompose the
             same card (the script stays put), not swap a new one in. Keying by
             phase also deadlocks AnimatePresence mode="wait". */
          <motion.div key={`lead-${lead?.id}`} className="line-card"
            initial={rm ? false : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={rm ? { opacity: 0 } : { opacity: 0, x: -24 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}>

            <h2 className="line-biz">{lead?.business_name}</h2>
            <p className="line-meta">
              {[lead?.city, lead?.service_type,
                lead?.rating ? `${lead.rating}★ ${lead.reviews || 0} reviews` : null]
                .filter(Boolean).join(' · ')}
            </p>

            {phase === 'brief' && (
              <div className="line-dial">
                <a className="line-number" href={`tel:${lead?.phone || ''}`}>{lead?.phone}</a>
                <p className="line-askfor">ask for {card?.ask_for}</p>
              </div>
            )}

            {card?.evidence && (
              <blockquote className="line-quote">
                <p>“{card.evidence}”</p>
                <cite>from their own reviews</cite>
              </blockquote>
            )}

            <div className="line-script">
              <ScriptLine label="OPEN" text={card?.open} dim={phase === 'live' && elapsed > 20} />
              <ScriptLine label="HOOK" text={card?.hook} />
              <ScriptLine label="ASK" text={card?.ask} />
            </div>

            {phase === 'live' && (
              <>
                <div className="line-objections">
                  <p className="line-obj-head">IF THEY SAY</p>
                  {card?.objections?.map((o) => (
                    <div className="line-obj" key={o.trigger}>
                      <span className="line-obj-trigger">{o.trigger}</span>
                      <span className="line-obj-reply">{o.reply}</span>
                    </div>
                  ))}
                </div>
                <textarea ref={noteRef} className="line-note" placeholder="notes"
                          value={note} onChange={(e) => setNote(e.target.value)}
                          aria-label="call notes" />
              </>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {!receipt && phase === 'brief' && (
        <div className="line-actions">
          <button type="button" className="btn line-start" onClick={startCall}>
            ▸ Start call
          </button>
          <button type="button" className="btn ghost line-skip" onClick={skip}>Skip</button>
        </div>
      )}

      {!receipt && phase === 'live' && (
        <div className="line-actions">
          <button type="button" className="btn line-end" onClick={() => setPhase('card')}>
            End call → log outcome
          </button>
        </div>
      )}

      {!receipt && phase === 'card' && (
        <div className="line-outcomes">
          <p className="line-ask">How&apos;d it go?</p>
          <div className="line-outcome-grid">
            {OUTCOMES.map((o) => (
              <motion.button key={o.id} type="button"
                layoutId={rm ? undefined : `outcome-${o.id}`}
                className={`btn line-outcome${o.win ? ' win' : ''}`}
                disabled={busy}
                onClick={() => logOutcome(o.id)}>
                {o.label}
              </motion.button>
            ))}
          </div>
          <div className="line-outcome-extra">
            <button type="button" className="btn ghost"
                    onClick={() => logOutcome('gatekeeper', { next_touch: bizDaysFromNow(2) })}>
              ⟲ Call back in 2 days
            </button>
            <button type="button" className="btn ghost"
                    onClick={() => logOutcome('bad_number')}>Bad number</button>
          </div>
        </div>
      )}

      <div className="line-footer">
        <button type="button" className="btn ghost line-exit" onClick={exit}>Leave the line (Esc)</button>
      </div>

      <AnimatePresence>
        {undo && (
          <motion.div className="line-undo" key="undo"
            initial={rm ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <span>{undo.label}</span>
            <button type="button" className="btn ghost" onClick={doUndo}>Undo</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function ScriptLine({ label, text, dim }) {
  if (!text) return null
  return (
    <div className={`line-script-row${dim ? ' spent' : ''}`}>
      <span className="line-script-label">{label}</span>
      <span className="line-script-text">{dim ? 'past it' : text}</span>
    </div>
  )
}

function LineResting({ onStart, busy, resumable, onResume, onDiscardResume }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="line-resting">
      <div className="line-resting-head">
        <span className="section-label">The Line</span>
      </div>
      {resumable && (
        <div className="line-resume">
          <button type="button" className="btn line-begin" disabled={busy} onClick={onResume}>
            ▸ Resume run ({resumable.dialed ?? 0} of {resumable.target})
          </button>
          <button type="button" className="btn ghost" disabled={busy} onClick={onDiscardResume}>Discard</button>
        </div>
      )}
      {open ? (
        <div className="line-target-row">
          <span className="dim">how many?</span>
          {RUN_TARGETS.map((t) => (
            <button key={t} type="button" className="btn line-target"
                    disabled={busy} onClick={() => onStart(t)}>{t}</button>
          ))}
          <button type="button" className="btn ghost" onClick={() => setOpen(false)}>cancel</button>
        </div>
      ) : (
        <button type="button" className="btn line-begin" disabled={busy}
                onClick={() => setOpen(true)}>▸ Start a run</button>
      )}
    </div>
  )
}

function LineSummary({ summary, onAgain, onDone, rm }) {
  const [ready, setReady] = useState(rm)
  useEffect(() => {
    if (rm) return undefined
    const t = setTimeout(() => setReady(true), 1900)   // ma: let it land first
    return () => clearTimeout(t)
  }, [rm])

  const n = summary?.dialed ?? 0
  const words = ['no calls', 'one call', 'two calls', 'three calls', 'four calls', 'five calls']
  return (
    <div className="line-summary">
      <motion.p className="line-summary-count"
        initial={rm ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}>
        {words[n] || `${n} calls`}.
      </motion.p>
      <motion.p className="line-summary-line"
        initial={rm ? false : { opacity: 0 }} animate={{ opacity: 1 }}
        transition={{ delay: rm ? 0 : 0.5, duration: 0.5 }}>
        {summary?.conversations || 0} conversation{summary?.conversations === 1 ? '' : 's'}
        {' · '}{summary?.booked || 0} demo{summary?.booked === 1 ? '' : 's'} booked
      </motion.p>
      {!!summary?.booked_names?.length && (
        <p className="line-summary-names">{summary.booked_names.join(' · ')}</p>
      )}
      {!!summary?.callbacks?.length && (
        <p className="line-summary-names">
          next: {summary.callbacks[0].business_name} on {summary.callbacks[0].next_touch}
        </p>
      )}
      <AnimatePresence>
        {ready && (
          <motion.div className="line-summary-actions"
            initial={rm ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}>
            <button type="button" className="btn line-begin" onClick={onAgain}>Run again</button>
            <button type="button" className="btn ghost" onClick={onDone}>That&apos;s the day</button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
