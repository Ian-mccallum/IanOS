import React, { forwardRef, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'
import { api } from '../lib/api.js'
import { groupTasks } from '../lib/partner.js'
import { goalsForPillar } from '../lib/pillars.js'

function apiError(err, fallback = 'something went wrong') {
  const msg = err?.message || String(err)
  if (msg === 'Not Found' || msg.includes('404')) {
    return 'API is out of date. Stop and run make dev again'
  }
  return msg || fallback
}

function orderedRows(rows) {
  return groupTasks(rows).flatMap(({ parent, children }) => [parent, ...children])
}

const PARTNER_WHISPERS = [
  'Start with something sweet below.',
  'Small things add up.',
  'She notices the effort.',
  'The list is love, written down.',
]

function SparkleName({ reduced }) {
  const [burst, setBurst] = useState(0)

  useEffect(() => {
    if (reduced) return undefined
    const id = setInterval(() => setBurst((n) => n + 1), 4200)
    return () => clearInterval(id)
  }, [reduced])

  const dots = useMemo(() => {
    if (!burst) return []
    return Array.from({ length: 7 }, (_, i) => ({
      id: i,
      x: 8 + ((i * 17 + burst * 3) % 78),
      y: 15 + ((i * 23 + burst) % 55),
      delay: i * 0.06,
      char: i % 2 === 0 ? '✦' : '·',
    }))
  }, [burst])

  return (
    <h2 className={`partner-name${reduced ? '' : ' partner-name-alive'}`}>
      <span className="partner-name-text" aria-label="Partner Ziegler">Partner Ziegler</span>
      {!reduced && (
        <span className="partner-name-sparkles" aria-hidden="true">
          <AnimatePresence>
            {dots.map((dot) => (
              <motion.span
                key={`${burst}-${dot.id}`}
                className="partner-sparkle"
                style={{ left: `${dot.x}%`, top: `${dot.y}%` }}
                initial={{ opacity: 0, scale: 0, rotate: -20 }}
                animate={{ opacity: [0, 1, 0], scale: [0, 1.1, 0.4], y: [0, -10, -18], rotate: [0, 12, 24] }}
                transition={{ duration: 0.9, delay: dot.delay, ease: [0.22, 1, 0.36, 1] }}
              >
                {dot.char}
              </motion.span>
            ))}
          </AnimatePresence>
        </span>
      )}
    </h2>
  )
}

function PartnerEmpty({ reduced }) {
  return (
    <motion.div
      className="partner-empty"
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
    >
      <span className="partner-empty-heart" aria-hidden="true">♥</span>
      <p>Your list is empty. Add the first thing above.</p>
    </motion.div>
  )
}

const TaskRow = React.forwardRef(function TaskRow({
  task,
  kind,
  onToggle,
  onArchive,
  onSave,
  busy,
  children,
}, ref) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(task.title)
  const [notes, setNotes] = useState(task.notes || '')
  const [confirmArchive, setConfirmArchive] = useState(false)
  const titleRef = useRef(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    setTitle(task.title)
    setNotes(task.notes || '')
  }, [task.title, task.notes])

  useEffect(() => {
    if (editing) titleRef.current?.focus()
  }, [editing])

  const save = async () => {
    if (!title.trim()) return
    await onSave(task.id, { title: title.trim(), notes: notes.trim() })
    setEditing(false)
  }

  if (editing) {
    return (
      <div ref={ref} className={`partner-task partner-${kind} editing`}>
        <label className="sr-only" htmlFor={`partner-title-${task.id}`}>{`Edit ${kind} title`}</label>
        <input
          ref={titleRef}
          id={`partner-title-${task.id}`}
          className="partner-edit-title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') save()
            if (event.key === 'Escape') setEditing(false)
          }}
        />
        <label className="sr-only" htmlFor={`partner-notes-${task.id}`}>{`Edit ${kind} notes`}</label>
        <input
          id={`partner-notes-${task.id}`}
          className="partner-edit-notes"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Notes (optional)"
        />
        <div className="partner-edit-actions">
          <button type="button" className="btn ghost" onClick={() => setEditing(false)}>Cancel</button>
          <button type="button" className="btn partner-btn" onClick={save} disabled={busy || !title.trim()}>Save changes</button>
        </div>
      </div>
    )
  }

  const kindLabel = kind === 'outcome' ? 'outcome' : 'step'
  return (
    <motion.div
      ref={ref}
      layout={!reduced}
      className={`partner-task partner-${kind}${task.done ? ' done' : ''}${task._pending ? ' pending' : ''}`}
      initial={reduced ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduced ? { opacity: 0 } : { opacity: 0, y: -4, transition: { duration: 0.15 } }}
    >
      <button
        type="button"
        className={`partner-check${task.done ? ' checked' : ''}`}
        onClick={() => onToggle(task)}
        disabled={busy || task._pending}
        aria-label={task.done ? `Reopen ${kindLabel}: ${task.title}` : `Mark ${kindLabel} done: ${task.title}`}
      >
        {task.done && <span className="partner-check-mark" aria-hidden="true">✓</span>}
      </button>
      <button
        type="button"
        className="partner-task-body"
        onClick={() => setEditing(true)}
        disabled={busy || task._pending}
        aria-label={`Edit ${kindLabel}: ${task.title}`}
      >
        <span className="partner-task-title">{task.title}</span>
        {task.notes && <span className="partner-task-notes">{task.notes}</span>}
        {task._pending && <span className="partner-task-sync">Waiting to sync</span>}
      </button>
      {children}
      <button
        type="button"
        className={`partner-delete${confirmArchive ? ' confirm' : ''}`}
        onClick={() => {
          if (!confirmArchive) {
            setConfirmArchive(true)
            return
          }
          onArchive(task)
        }}
        onBlur={() => setConfirmArchive(false)}
        disabled={busy || task._pending}
        aria-label={confirmArchive ? `Confirm remove ${kindLabel}: ${task.title}` : `Remove ${kindLabel}: ${task.title}`}
      >
        {confirmArchive ? 'Remove?' : '×'}
      </button>
    </motion.div>
  )
})

const TaskGroup = forwardRef(function TaskGroup({ group, busyIds, onToggle, onArchive, onSave, onAddStep }, ref) {
  const { parent, children, complete } = group
  const [expanded, setExpanded] = useState(!complete)
  const [showDone, setShowDone] = useState(false)
  const [adding, setAdding] = useState(false)
  const [stepTitle, setStepTitle] = useState('')
  const stepRef = useRef(null)
  const reduced = useReducedMotion()
  const panelId = `partner-steps-${parent.id}`
  const donePanelId = `partner-done-steps-${parent.id}`
  const openSteps = children.filter((child) => !child.done)
  const doneSteps = children.filter((child) => child.done)
  const summary = openSteps.length
    ? `${openSteps.length} step${openSteps.length === 1 ? '' : 's'} left`
    : doneSteps.length
      ? `${doneSteps.length} step${doneSteps.length === 1 ? '' : 's'} done`
      : 'No steps'

  useEffect(() => {
    if (adding) stepRef.current?.focus()
  }, [adding])

  const addStep = async () => {
    const title = stepTitle.trim()
    if (!title) {
      stepRef.current?.focus()
      return
    }
    const saved = await onAddStep(parent, title)
    if (saved) {
      setStepTitle('')
      setAdding(false)
    }
  }

  return (
    <motion.section
      ref={ref}
      layout={!reduced}
      className={`partner-group${complete ? ' complete' : ''}`}
      aria-label={`Outcome: ${parent.title}`}
    >
      <TaskRow
        task={parent}
        kind="outcome"
        onToggle={onToggle}
        onArchive={onArchive}
        onSave={onSave}
        busy={busyIds.has(parent.id)}
      >
        <button
          type="button"
          className="partner-disclosure"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={panelId}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} steps for ${parent.title}. ${summary}`}
        >
          <span>{summary}</span>
          <span className="partner-disclosure-icon" aria-hidden="true">{expanded ? '⌃' : '⌄'}</span>
        </button>
      </TaskRow>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            id={panelId}
            className="partner-step-panel"
            initial={reduced ? false : { opacity: 0, y: -5 }}
            animate={{ opacity: 1, y: 0 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: -3 }}
            transition={{ duration: reduced ? 0 : 0.18, ease: [0.22, 1, 0.36, 1] }}
          >
            {openSteps.map((step) => (
              <TaskRow
                key={step.id}
                task={step}
                kind="step"
                onToggle={onToggle}
                onArchive={onArchive}
                onSave={onSave}
                busy={busyIds.has(step.id)}
              />
            ))}

            {doneSteps.length > 0 && (
              <div className="partner-finished-steps">
                <button
                  type="button"
                  className="partner-done-toggle"
                  onClick={() => setShowDone((value) => !value)}
                  aria-expanded={showDone}
                  aria-controls={donePanelId}
                >
                  {showDone ? 'Hide' : 'Show'} {doneSteps.length} done
                </button>
                {showDone && (
                  <div id={donePanelId}>
                    {doneSteps.map((step) => (
                      <TaskRow
                        key={step.id}
                        task={step}
                        kind="step"
                        onToggle={onToggle}
                        onArchive={onArchive}
                        onSave={onSave}
                        busy={busyIds.has(step.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}

            {parent._pending ? (
              <p className="partner-sync-hint">Sync to add steps</p>
            ) : adding ? (
              <div className="partner-step-add-form">
                <label className="sr-only" htmlFor={`partner-new-step-${parent.id}`}>Step title</label>
                <input
                  ref={stepRef}
                  id={`partner-new-step-${parent.id}`}
                  value={stepTitle}
                  onChange={(event) => setStepTitle(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') addStep()
                    if (event.key === 'Escape') setAdding(false)
                  }}
                  placeholder="Add the next step"
                />
                <button type="button" className="btn ghost" onClick={() => setAdding(false)}>Cancel</button>
                <button type="button" className="btn partner-btn" onClick={addStep} disabled={!stepTitle.trim()}>Add step</button>
              </div>
            ) : (
              <button type="button" className="partner-add-step" onClick={() => setAdding(true)}>+ Add step</button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  )
})

TaskGroup.displayName = 'TaskGroup'

export default function PartnerPage({ tasks, summary, onTasksChange, toast, apiReady = true, state, refresh }) {
  const [list, setList] = useState(() => orderedRows(tasks))
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [addingOutcome, setAddingOutcome] = useState(false)
  const [busyIds, setBusyIds] = useState(() => new Set())
  const addRef = useRef(null)
  const reduced = useReducedMotion()

  useEffect(() => {
    setList(orderedRows(tasks))
  }, [tasks])

  const sync = (updater) => {
    setList((previous) => {
      const next = typeof updater === 'function' ? updater(previous) : updater
      const ordered = orderedRows(next)
      onTasksChange?.(ordered)
      return ordered
    })
  }

  const setBusy = (id, value) => {
    setBusyIds((previous) => {
      const next = new Set(previous)
      if (value) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const groups = useMemo(() => groupTasks(list), [list])
  const openGroups = groups.filter((group) => !group.complete)
  const doneGroups = groups.filter((group) => group.complete)
  const serverOpen = Number.isInteger(summary?.open_count) ? summary.open_count : null
  const whisper = useMemo(() => {
    if (groups.length) return null
    const day = Math.floor(Date.now() / 86400000)
    return PARTNER_WHISPERS[day % PARTNER_WHISPERS.length]
  }, [groups.length])
  const subLine = serverOpen == null
    ? 'Waiting for the shared task count'
    : serverOpen > 0
      ? `${serverOpen} open ${serverOpen === 1 ? 'thing' : 'things'}`
      : groups.length
        ? 'All caught up'
        : whisper

  const addOutcome = async () => {
    const taskTitle = title.trim()
    const taskNotes = notes.trim()
    if (!taskTitle) {
      toast('add a title first', 'warn')
      addRef.current?.focus()
      return
    }
    if (!apiReady) {
      toast('API is out of date. Run make dev again', 'crit')
      return
    }

    const tempId = `tmp-${Date.now()}`
    const optimistic = { id: tempId, parent_id: null, title: taskTitle, notes: taskNotes, done: false, _pending: true }
    sync((previous) => [...previous, optimistic])
    setTitle('')
    setNotes('')
    setAddingOutcome(true)

    try {
      const result = await api('/api/partner-tasks', 'POST', { title: taskTitle, notes: taskNotes, parent_id: null }, { queueable: true })
      if (result?.queued) {
        toast('Added for Partner. Syncs when your Mac wakes', 'good')
      } else {
        sync((previous) => previous.filter((task) => task.id !== tempId).concat([result]))
        toast('Added for Partner', 'good')
      }
      addRef.current?.focus()
    } catch (error) {
      sync((previous) => previous.filter((task) => task.id !== tempId))
      setTitle(taskTitle)
      setNotes(taskNotes)
      toast(apiError(error), 'crit')
    } finally {
      setAddingOutcome(false)
    }
  }

  const addStep = async (parent, stepTitle) => {
    if (parent._pending || String(parent.id).startsWith('tmp-')) return false
    const tempId = `tmp-step-${Date.now()}`
    const optimistic = { id: tempId, parent_id: parent.id, title: stepTitle, notes: '', done: false, _pending: true }
    sync((previous) => [...previous, optimistic])
    setBusy(parent.id, true)
    try {
      const result = await api('/api/partner-tasks', 'POST', { title: stepTitle, notes: '', parent_id: parent.id }, { queueable: true })
      if (result?.queued) {
        toast('Step saved. Syncs when your Mac wakes', 'good')
      } else {
        sync((previous) => previous.filter((task) => task.id !== tempId).concat([result]))
        toast('Step added', 'good')
      }
      return true
    } catch (error) {
      sync((previous) => previous.filter((task) => task.id !== tempId))
      toast(apiError(error), 'crit')
      return false
    } finally {
      setBusy(parent.id, false)
    }
  }

  const toggle = async (task) => {
    if (task._pending || String(task.id).startsWith('tmp-')) return
    const nextDone = !task.done
    sync((previous) => previous.map((row) => (row.id === task.id ? { ...row, done: nextDone, _pending: true } : row)))
    setBusy(task.id, true)
    try {
      const result = await api(`/api/partner-tasks/${task.id}`, 'PATCH', { done: nextDone }, { queueable: true })
      if (result?.queued) {
        sync((previous) => previous.map((row) => (row.id === task.id ? { ...row, _pending: false } : row)))
        toast(`${nextDone ? 'Marked done' : 'Reopened'}. Syncs when your Mac wakes`, 'good')
      } else {
        sync((previous) => previous.map((row) => (row.id === task.id ? result : row)))
        toast(nextDone ? 'Marked done' : 'Reopened', 'good')
      }
    } catch (error) {
      sync((previous) => previous.map((row) => (row.id === task.id ? { ...row, done: !nextDone, _pending: false } : row)))
      toast(apiError(error), 'crit')
    } finally {
      setBusy(task.id, false)
    }
  }

  const save = async (id, fields) => {
    if (String(id).startsWith('tmp-')) return
    setBusy(id, true)
    try {
      const result = await api(`/api/partner-tasks/${id}`, 'PATCH', fields, { queueable: true })
      if (result?.queued) {
        sync((previous) => previous.map((row) => (row.id === id ? { ...row, ...fields } : row)))
        toast('Updated. Syncs when your Mac wakes', 'good')
      } else {
        sync((previous) => previous.map((row) => (row.id === id ? result : row)))
        toast('Updated', 'good')
      }
    } catch (error) {
      toast(apiError(error), 'crit')
      throw error
    } finally {
      setBusy(id, false)
    }
  }

  const restoreArchive = async (batchId, archivedRows) => {
    const ids = new Set(archivedRows.map((row) => row.id))
    sync((previous) => previous.concat(archivedRows.map((row) => ({ ...row, _pending: true }))))
    try {
      const result = await api(`/api/partner-tasks/archive/${batchId}/restore`, 'POST', undefined, { queueable: true })
      if (result?.queued) {
        toast('Restore saved. Syncs when your Mac wakes', 'good')
        return
      }
      const restored = Array.isArray(result) ? result : result?.restored || result?.tasks || []
      sync((previous) => previous.filter((row) => !ids.has(row.id)).concat(restored))
      toast('Restored', 'good')
    } catch (error) {
      sync((previous) => previous.filter((row) => !ids.has(row.id)))
      toast(apiError(error), 'crit')
    }
  }

  const archive = async (task) => {
    if (task._pending || String(task.id).startsWith('tmp-')) return
    const archivedRows = task.parent_id == null
      ? list.filter((row) => row.id === task.id || row.parent_id === task.id)
      : list.filter((row) => row.id === task.id)
    const ids = new Set(archivedRows.map((row) => row.id))
    sync((previous) => previous.filter((row) => !ids.has(row.id)))
    setBusy(task.id, true)
    try {
      const result = await api(`/api/partner-tasks/${task.id}`, 'DELETE', undefined, { queueable: true })
      const batchId = result?.archive_batch_id || result?.mutation_id
      const stepCount = task.parent_id == null ? archivedRows.length - 1 : 0
      const copy = task.parent_id == null && stepCount > 0
        ? `Removed outcome and ${stepCount} ${stepCount === 1 ? 'step' : 'steps'}`
        : `Removed ${task.parent_id == null ? 'outcome' : 'step'}`
      toast(result?.queued ? `${copy}. Syncs when your Mac wakes` : copy, 'good', batchId
        ? () => restoreArchive(batchId, archivedRows)
        : null)
    } catch (error) {
      sync((previous) => previous.concat(archivedRows))
      toast(apiError(error), 'crit')
    } finally {
      setBusy(task.id, false)
    }
  }

  return (
    <div className="partner-page page-layout page-layout--overview">
      {!apiReady && (
        <div className="partner-api-warn" role="alert">
          Partner tasks need a fresh API. Stop the terminal and run <code>make dev</code> again.
        </div>
      )}

      <div className="partner-sidebar">
        <motion.div
          className="partner-hero glass-card"
          initial={reduced ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: reduced ? 0 : 0.2 }}
        >
          <p className="partner-eyebrow">For my girlfriend <span className="partner-eyebrow-heart" aria-hidden="true">♥</span></p>
          <SparkleName reduced={reduced} />
          <p className="partner-sub">{subLine}</p>
        </motion.div>

        <div className="partner-add glass-card glass-card-pad">
          <h3 className="partner-add-title">Add something for Partner</h3>
          <div className="partner-add-form">
            <input
              ref={addRef}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); addOutcome() } }}
              placeholder="Buy her flowers, plan the water park…"
              enterKeyHint="next"
              aria-label="Outcome title"
            />
            <input
              className="partner-notes-input"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              onKeyDown={(event) => { if (event.key === 'Enter') addOutcome() }}
              placeholder="Notes (optional)"
              enterKeyHint="done"
              aria-label="Outcome notes"
            />
            <motion.button
              type="button"
              className="btn partner-btn"
              onClick={addOutcome}
              disabled={addingOutcome || !title.trim()}
              whileTap={reduced ? {} : { scale: 0.97 }}
            >
              {addingOutcome ? 'Saving…' : 'Add to list'}
            </motion.button>
          </div>
        </div>
      </div>

      <div className="partner-workstream">
        <div className="partner-list" aria-label="Open Partner outcomes">
          <AnimatePresence initial={false} mode="popLayout">
            {openGroups.map((group) => (
              <TaskGroup
                key={group.parent.id}
                group={group}
                busyIds={busyIds}
                onToggle={toggle}
                onArchive={archive}
                onSave={save}
                onAddStep={addStep}
              />
            ))}
          </AnimatePresence>
          {groups.length === 0 && <PartnerEmpty reduced={reduced} />}
        </div>

        {doneGroups.length > 0 && (
          <section className="partner-done-section" aria-label="Done Partner outcomes">
            <p className="section-label">Done</p>
            <div className="partner-list">
              {doneGroups.map((group) => (
                <TaskGroup
                  key={group.parent.id}
                  group={group}
                  busyIds={busyIds}
                  onToggle={toggle}
                  onArchive={archive}
                  onSave={save}
                  onAddStep={addStep}
                />
              ))}
            </div>
          </section>
        )}

        {state && refresh && (
          <div className="partner-goals-section">
            <PillarGoalPanel
              pillar="partner"
              title="Goals for us"
              goals={goalsForPillar(state.goals, 'partner')}
              refresh={refresh}
              toast={toast}
              variant="simple"
              notesDefault="#partner"
            />
          </div>
        )}
      </div>
    </div>
  )
}
