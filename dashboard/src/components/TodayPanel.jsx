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

function TaskRow({ task, today, onToggle, onPriority, onRename, onDelete, onFly }) {
  const [completing, setCompleting] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(task.title)
  const priorityRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const toggle = () => {
    if (task._done) { onToggle(task); return }
    // The ring fills and the tick draws before the row leaves, so the tap has
    // a visible result even on a list of one.
    setCompleting(true)
    setTimeout(() => onToggle(task), 320)
  }

  const togglePriority = () => {
    if (!task.priority && priorityRef.current) {
      onFly(priorityRef.current.getBoundingClientRect())
    }
    onPriority(task)
  }

  const commit = () => {
    const next = draft.trim()
    setEditing(false)
    if (!next || next === task.title) { setDraft(task.title); return }
    onRename(task, next)
  }

  return (
    <SwipeRow goal={task} onArchive={() => onDelete(task)} archiveLabel="Delete">
      <div className={`trow${completing ? ' completing' : ''}${task._done ? ' done' : ''}`}>
        <button
          type="button"
          className="trow-check"
          onClick={toggle}
          aria-label={`Mark "${task.title}" done`}
        >
          <CheckRing done={completing || Boolean(task._done)} />
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
              if (e.key === 'Escape') { setDraft(task.title); setEditing(false) }
            }}
            aria-label="Edit task"
          />
        ) : (
          <button type="button" className="trow-title" onClick={() => setEditing(true)}>
            {task.title}
          </button>
        )}

        {task.due_date < today && !task._done && !editing && <RolledAge dueDate={task.due_date} />}

        <button
          ref={priorityRef}
          type="button"
          className={`trow-star${task.priority ? ' on' : ''}`}
          onClick={togglePriority}
          aria-label={task.priority ? `Unstar "${task.title}"` : `Star "${task.title}" for Command`}
        >
          <StarMark on={Boolean(task.priority)} />
        </button>
      </div>
    </SwipeRow>
  )
}

export default function TodayPanel({ tasksToday = [], tasksDoneToday = [], today, refresh, toast, onFlyPriorityDot }) {
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const composerRef = useRef(null)
  const reduced = useReducedMotion()

  const openCount = tasksToday.filter((t) => !t._done).length

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

  const toggle = async (task) => {
    await api(`/api/tasks/${task.id}/done`, 'POST', { undo: Boolean(task._done) }, { queueable: true })
    refresh()
  }

  const setPriority = async (task) => {
    const starring = !task.priority
    await api(`/api/tasks/${task.id}`, 'PATCH', { priority: starring ? 1 : 0 }, { queueable: true })
    refresh()
    // Name the destination. The dot flying to the Command tab is invisible
    // under reduced motion and on the desktop rail, and a starred task lands
    // under "Also on deck" rather than as the headline, so without this the
    // tap has no legible outcome at all.
    toast?.(starring ? 'starred · now on Command' : 'unstarred · off Command', 'good')
  }

  const rename = async (task, title) => {
    await api(`/api/tasks/${task.id}`, 'PATCH', { title }, { queueable: true })
    refresh()
  }

  const remove = async (task) => {
    await api(`/api/tasks/${task.id}`, 'DELETE', undefined, { queueable: true })
    refresh()
    toast?.(`removed "${task.title}"`, 'good', async () => {
      await api(`/api/tasks/${task.id}/restore`, 'POST', {})
      refresh()
    })
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
            onToggle={toggle}
            onPriority={setPriority}
            onRename={rename}
            onDelete={remove}
            onFly={fly}
          />
        ))}

        <form className="trow trow-new" onSubmit={(e) => { e.preventDefault(); add() }}>
          <span className="trow-check trow-check-static"><PlusMark /></span>
          <input
            ref={composerRef}
            className="trow-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="New task"
            enterKeyHint="done"
            aria-label="New task"
          />
        </form>
      </div>

      {tasksDoneToday.length > 0 && (
        <details className="today-done-reveal">
          <summary>{tasksDoneToday.length} done today</summary>
          {tasksDoneToday.map((t) => (
            <div key={t.id} className="trow done">
              <span className="trow-check trow-check-static"><CheckRing done /></span>
              <span className="trow-title">{t.title}</span>
            </div>
          ))}
        </details>
      )}
    </section>
  )
}
