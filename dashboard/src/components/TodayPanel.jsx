import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import { SwipeRow } from './goals/PillarGoalPanel.jsx'
import StarMark from './StarMark.jsx'

/* Drawn icons, one 1.6 stroke across the set. The row's controls have to read
   as instruments at 22px, which a Unicode ★ or ✓ never does: it inherits the
   text face's weight and sits on the text baseline instead of the row's
   optical center. */

function CheckRing({ done }) {
  return (
    <svg className="trow-ring" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path
        className="trow-tick"
        d="M7.5 12.4 L10.6 15.4 L16.6 8.9"
        fill="none" stroke="currentColor" strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round"
        pathLength="1"
        style={{ strokeDasharray: 1, strokeDashoffset: done ? 0 : 1 }}
      />
    </svg>
  )
}

function PlusMark() {
  return (
    <svg className="trow-plus" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <path d="M12 6.5 V17.5 M6.5 12 H17.5" fill="none" stroke="currentColor"
            strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

/* SPEC-v41 §4.6: a rolled task's age arrives a second after the row does, so
   opening Life never greets Ian with a wall of "since". It fades rather than
   pops, because it arrives into a row that is already sitting still. */
function RolledAge({ dueDate }) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setShow(true), 1000)
    return () => clearTimeout(t)
  }, [])
  if (!show) return null
  const label = new Date(`${dueDate}T00:00:00`).toLocaleDateString('en-US', { weekday: 'short' })
  return <span className="trow-age">since {label}</span>
}

function TaskRow({ task, today, onComplete, onPriority, onRename, onDelete, onFly }) {
  const [completing, setCompleting] = useState(false)
  const [editing, setEditing] = useState(false)
  // `title` is what the row shows, `draft` is the editor's buffer. They are
  // separate so a committed rename paints immediately instead of flashing the
  // old text back for the length of one /api/state round trip.
  const [title, setTitle] = useState(task.title)
  const [draft, setDraft] = useState(task.title)
  const priorityRef = useRef(null)
  const inputRef = useRef(null)
  const timer = useRef(null)

  useEffect(() => { setTitle(task.title) }, [task.title])
  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])
  useEffect(() => () => clearTimeout(timer.current), [])

  const complete = () => {
    if (completing) return
    // The ring fills and the tick draws before the row leaves, so the tap has
    // a visible result even on a list of one.
    setCompleting(true)
    timer.current = setTimeout(async () => {
      const ok = await onComplete(task)
      // A rejected write must not leave the row struck through and greyed for
      // the rest of the session: `completing` is local state, so the 15s poll
      // re-renders a row that goes on claiming it is done.
      if (!ok) setCompleting(false)
    }, 320)
  }

  const togglePriority = () => {
    if (!task.priority && priorityRef.current) {
      onFly(priorityRef.current.getBoundingClientRect())
    }
    onPriority(task)
  }

  const commit = async () => {
    const next = draft.trim()
    setEditing(false)
    if (!next || next === title) { setDraft(title); return }
    setTitle(next)
    const ok = await onRename(task, next)
    if (!ok) { setTitle(task.title); setDraft(task.title) }
  }

  return (
    <SwipeRow goal={task} onArchive={() => onDelete(task, title)} archiveLabel="Delete">
      <div className={`trow${completing ? ' completing' : ''}`}>
        <button
          type="button"
          className="trow-check"
          onClick={complete}
          aria-label={`Mark "${title}" done`}
        >
          <CheckRing done={completing} />
        </button>

        {editing ? (
          <input
            ref={inputRef}
            className="trow-edit"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); commit() }
              if (e.key === 'Escape') { setDraft(title); setEditing(false) }
            }}
            aria-label="Edit task"
          />
        ) : (
          <button
            type="button"
            className="trow-title"
            onClick={() => { setDraft(title); setEditing(true) }}
          >
            {title}
          </button>
        )}

        {task.due_date < today && !editing && <RolledAge dueDate={task.due_date} />}

        <button
          ref={priorityRef}
          type="button"
          className={`trow-star${task.priority ? ' on' : ''}`}
          onClick={togglePriority}
          aria-label={task.priority ? `Unstar "${title}"` : `Star "${title}" for Command`}
        >
          <StarMark on={Boolean(task.priority)} />
        </button>
      </div>
    </SwipeRow>
  )
}

/* A finished task is reversible from the surface that finished it. The ring in
   the Done disclosure used to be an inert <span>, so a mis-tap on a 52px row
   was the one write in this product with no way back, even though the endpoint
   has taken `{undo: true}` since SPEC-v41 shipped. */
function DoneRow({ task, onUncomplete }) {
  return (
    <div className="trow done">
      <button
        type="button"
        className="trow-check"
        onClick={() => onUncomplete(task)}
        aria-label={`Move "${task.title}" back to Today`}
      >
        <CheckRing done />
      </button>
      <span className="trow-title">{task.title}</span>
    </div>
  )
}

export default function TodayPanel({ tasksToday = [], tasksDoneToday = [], today, refresh, toast, onFlyPriorityDot }) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [clearedAll, setClearedAll] = useState(false)
  const composerRef = useRef(null)
  const clearedTimer = useRef(null)
  const reduced = useReducedMotion()

  const openCount = tasksToday.length
  const doneCount = tasksDoneToday.length

  useEffect(() => () => clearTimeout(clearedTimer.current), [])

  const fail = (e) => { toast?.(e?.message || "couldn't save that", 'crit'); return false }

  const add = async () => {
    const title = draft.trim()
    if (!title || busy) return
    setBusy(true)
    setDraft('')
    try {
      await api('/api/tasks', 'POST', { title }, { queueable: true })
      refresh()
      // Capture is the job: the caret stays put so a second line costs nothing.
      composerRef.current?.focus()
    } catch (e) {
      toast?.(e.message || "couldn't add that", 'crit')
    } finally {
      setBusy(false)
    }
  }

  const complete = async (task) => {
    const last = tasksToday.length === 1
    try {
      await api(`/api/tasks/${task.id}/done`, 'POST', { undo: false }, { queueable: true })
      refresh()
      // SPEC-v41 §4.6: clearing the list says so once, in the composer, and
      // then stops. Nothing persistent, no badge, no score.
      if (last) {
        setClearedAll(true)
        clearTimeout(clearedTimer.current)
        clearedTimer.current = setTimeout(() => setClearedAll(false), 3000)
      }
      return true
    } catch (e) { return fail(e) }
  }

  const uncomplete = async (task) => {
    try {
      await api(`/api/tasks/${task.id}/done`, 'POST', { undo: true }, { queueable: true })
      setClearedAll(false)
      refresh()
      return true
    } catch (e) { return fail(e) }
  }

  const setPriority = async (task) => {
    const starring = !task.priority
    try {
      await api(`/api/tasks/${task.id}`, 'PATCH', { priority: starring ? 1 : 0 }, { queueable: true })
    } catch (e) { return fail(e) }
    refresh()
    // Name the destination. The dot flying to the Command tab is invisible
    // under reduced motion and on the desktop rail, and a starred task lands
    // under "Also on deck" rather than as the headline, so without this the
    // tap has no legible outcome at all.
    toast?.(starring ? 'starred · now on Command' : 'unstarred · off Command', 'good')
    return true
  }

  const rename = async (task, title) => {
    try {
      await api(`/api/tasks/${task.id}`, 'PATCH', { title }, { queueable: true })
    } catch (e) { return fail(e) }
    refresh()
    return true
  }

  const remove = async (task, shownTitle) => {
    try {
      await api(`/api/tasks/${task.id}`, 'DELETE', undefined, { queueable: true })
    } catch (e) { return fail(e) }
    refresh()
    toast?.(`removed "${shownTitle || task.title}"`, 'good', async () => {
      await api(`/api/tasks/${task.id}/restore`, 'POST', {})
      refresh()
    })
    return true
  }

  const fly = (rect) => { if (!reduced) onFlyPriorityDot?.(rect) }

  return (
    <section className="panel today-panel">
      <header className="today-head">
        <h2>Today</h2>
        {openCount > 0 && <span className="today-count">{openCount}</span>}
      </header>

      <div className="today-rows">
        {/* Plain rows. The one authored moment on this surface is the
            completion (ring fills, tick draws, title strikes), and it is pure
            CSS, so it renders whether or not rAF is running. A JS entrance or
            layout animation here bought nothing and could strand a row at
            opacity 0 in a backgrounded tab. */}
        {tasksToday.map((t) => (
          <TaskRow
            key={t.id}
            task={t}
            today={today}
            onComplete={complete}
            onPriority={setPriority}
            onRename={rename}
            onDelete={remove}
            onFly={fly}
          />
        ))}

        {/* The plus looks like a control and sits in the 34px column every
            other row's ring is tappable in, so the whole row hands focus to
            the field rather than leaving a dead target there. */}
        <form
          className="trow trow-new"
          onSubmit={(e) => { e.preventDefault(); add() }}
          onClick={() => composerRef.current?.focus()}
        >
          <span className="trow-check trow-check-static"><PlusMark /></span>
          <input
            ref={composerRef}
            className="trow-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={clearedAll ? 'Done for today' : 'New task'}
            enterKeyHint="done"
            aria-label="New task"
          />
        </form>
      </div>

      {doneCount > 0 && (
        /* Open when nothing is left: finishing the list used to leave the panel
           looking empty while the day's actual work sat collapsed behind a
           disclosure. */
        <details className="today-done-reveal" open={openCount === 0}>
          <summary>{doneCount} done today</summary>
          {tasksDoneToday.map((t) => (
            <DoneRow key={t.id} task={t} onUncomplete={uncomplete} />
          ))}
        </details>
      )}
    </section>
  )
}
