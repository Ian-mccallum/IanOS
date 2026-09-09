import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import AuroraBackground from './components/AuroraBackground.jsx'
import Nav from './components/Nav.jsx'
import PartnerPage from './pages/PartnerPage.jsx'
import MoneyPage from './pages/MoneyPage.jsx'
import MoneyHistoryPage from './pages/MoneyHistoryPage.jsx'
import MemoryPage from './pages/MemoryPage.jsx'
import CommandPage from './pages/CommandPage.jsx'
import PlanPage from './pages/PlanPage.jsx'
import JournalPage from './pages/JournalPage.jsx'
import BeatTheClockPage from './pages/BeatTheClockPage.jsx'
import BodyPage from './pages/BodyPage.jsx'
import SchoolPage from './pages/SchoolPage.jsx'
import SchoolNotebookPage from './pages/SchoolNotebookPage.jsx'
import SchoolNotebookBoundary from './components/school-notes/SchoolNotebookBoundary.jsx'
import { stashSchoolNotebookIntent } from './lib/school-notebook.js'
import LifePage from './pages/LifePage.jsx'
import LearningPage from './pages/LearningPage.jsx'
import CommandPalette, { useCommandPalette } from './components/CommandPalette.jsx'
import { api, fetchState } from './lib/api.js'
import { deadLetters, dismissDeadLetter, pendingCount, onQueueChange, queueIssue, startAutoFlush } from './lib/offline.js'
import { pillarSwipeHandlers } from './lib/swipe.js'
import { bold } from './components/Md.jsx'
import { relTime } from './lib/time.js'
import NotesPage from './pages/NotesPage.jsx'
import RosterPage from './pages/RosterPage.jsx'
import LockScreen from './components/LockScreen.jsx'
import { roleColor, roleGlyph } from './lib/agents.js'
import { attachRelockListeners, isUnlocked, lockNow } from './lib/lock.js'
import AgentChat from './components/AgentChat.jsx'
import { draftLabel, draftPlainText, formatProposalDue } from './lib/proposals.js'
import DayArc from './components/DayArc.jsx'

// 'moneyhistory' is deliberately absent from Nav.jsx's ALL_LINKS/ALL_MOBILE_MORE
// (SPEC-v24 BUILD 4): it's a detail page reached only by disclosure from
// AccountSheet's "View all transactions", the same "not in the tab bar keeps
// its own title" rule this file already applies to every page below.
const PAGES = ['home', 'plan', 'btc', 'body', 'partner', 'school', 'schoolnotebook', 'life', 'learning', 'money', 'moneyhistory', 'memory', 'inbox', 'log', 'notes', 'goals', 'journal', 'roster', 'shutdown']
// The four pages with a permanent slot in the mobile tab bar (SPEC-v10 §2.1).
// Keep in step with MOBILE_PRIMARY in components/Nav.jsx.
const TAB_PAGES = ['home', 'plan', 'btc', 'partner']

// Roster (role → codename) fetched once from /api/state, shared via context.
const RosterContext = React.createContext({})

/** Colour and glyph come from lib/agents.js, the single source of agent
 *  identity, so Dumbledore is the same red ⚠ on a memo, a proposal and his card.
 *  (This used to keep its own private copy of the colour table.) */
function RoleTag({ role, className = 'role-tag' }) {
  const roster = React.useContext(RosterContext)
  const codename = roster[role]?.codename
  return (
    <span className={className} style={{ color: roleColor(role) }}>
      <span className="role-glyph" aria-hidden="true">{roleGlyph(role)}</span>
      {codename || cap(role)}
      {codename && <span className="role-sub"> · {role}</span>}
    </span>
  )
}
const KIND_LABEL = {
  money: 'Money', task: 'Task', legal: 'Legal',
  health: 'Health', personal: 'Personal',
}

function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

// ---------------------------------------------------------------- utils

function statusLabel(s) {
  const labels = {
    'ON TRACK': 'On track',
    'AT RISK': 'At risk',
    'OFF TRACK': 'Off track',
    'NO DATA': 'No data',
  }
  return labels[s] || s
}

function statusLevel(s) {
  if (s === 'ON TRACK') return 'good'
  if (s === 'AT RISK') return 'warn'
  if (s === 'OFF TRACK') return 'crit'
  return 'idle'
}

// api/fetchState live in lib/api.js, one implementation, so the offline write
// queue applies everywhere instead of only in the pages that import it.

// ------------------------------------------------------------ primitives

function Panel({ title, tag, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <h2>{title}</h2>
        <div className="panel-head-right">
          {tag && <span className="panel-tag">{tag}</span>}
          {actions}
        </div>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  )
}

function StatusChip({ level, children }) {
  return <span className={`chip chip-${level}`}>{children}</span>
}

function Meter({ value, max, level, label }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  return (
    <div className="meter" role="img" aria-label={label}>
      <div className={`meter-fill fill-${level}`} style={{ transform: `scaleX(${pct / 100})` }} />
    </div>
  )
}

// ------------------------------------------------------------ proposals

function ProposalMetadata({ proposal }) {
  const evidence = Array.isArray(proposal.evidence)
    ? proposal.evidence.map((item) => (
      typeof item === 'string' ? item.trim() : typeof item?.label === 'string' ? item.label.trim() : ''
    )).filter(Boolean)
    : []
  const due = formatProposalDue(proposal.due_at)
  const timeSensitive = proposal.urgency === 'time_sensitive'
  const hardToReverse = proposal.reversibility === 'hard_to_reverse'
  if (!timeSensitive && !due && !proposal.reversibility && evidence.length === 0) return null
  return (
    <div className="prop-metadata" aria-label="Proposal decision context">
      {timeSensitive && <span className="prop-meta-item time">Time-sensitive</span>}
      {due && <span className="prop-meta-item">Due {due}</span>}
      {proposal.reversibility && (
        <span className={`prop-meta-item${hardToReverse ? ' hard' : ''}`}>
          {hardToReverse ? 'Hard to reverse' : 'Reversible'}
        </span>
      )}
      {evidence.length > 0 && (
        <span className="prop-meta-evidence">Evidence: {evidence.join(', ')}</span>
      )}
    </div>
  )
}

function ProposalDraft({ proposal, toast }) {
  const [expanded, setExpanded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')
  const regionId = `proposal-draft-${proposal.id}`

  const toggle = async () => {
    if (expanded) {
      setExpanded(false)
      return
    }
    setExpanded(true)
    if (detail || loading) return
    setLoading(true)
    setError('')
    try {
      const result = await api(`/api/proposals/${proposal.id}`, 'GET', undefined, { cache: 'no-store' })
      setDetail(result)
    } catch (fetchError) {
      setError(fetchError?.message || 'Draft detail could not load.')
    } finally {
      setLoading(false)
    }
  }

  const attachment = detail?.attachment
  const plainText = draftPlainText(attachment)
  const copyDraft = async () => {
    if (!plainText || !navigator.clipboard?.writeText) {
      toast('Copy is not available in this browser', 'warn')
      return
    }
    try {
      await navigator.clipboard.writeText(plainText)
      toast('Draft copied', 'good')
    } catch {
      toast('Draft could not be copied', 'warn')
    }
  }

  return (
    <div className="prop-draft">
      <div className="prop-draft-head">
        <span className="prop-draft-chip">Draft attached</span>
        <button
          type="button"
          className="prop-draft-toggle"
          onClick={toggle}
          aria-expanded={expanded}
          aria-controls={regionId}
        >
          {expanded ? 'Hide draft' : 'View draft'}
        </button>
      </div>
      {expanded && (
        <div id={regionId} className="prop-draft-detail">
          {loading ? (
            <p className="dim" role="status">Loading draft…</p>
          ) : error ? (
            <p className="prop-draft-error" role="alert">{error}</p>
          ) : attachment && plainText ? (
            <>
              <span className="prop-draft-type">{draftLabel(attachment.type || proposal.attachment_type)}</span>
              {!!attachment.to_label && <p><strong>To:</strong> {attachment.to_label}</p>}
              {!!attachment.subject && <p><strong>Subject:</strong> {attachment.subject}</p>}
              {!!attachment.title && <p className="prop-draft-title">{attachment.title}</p>}
              {!!attachment.body && <pre className="prop-draft-body">{attachment.body}</pre>}
              <button type="button" className="btn ghost prop-copy-draft" onClick={copyDraft}>Copy draft</button>
            </>
          ) : (
            <p className="dim">Draft detail is unavailable.</p>
          )}
        </div>
      )}
      <p className="prop-draft-approval">Records approval. Does not send this draft.</p>
    </div>
  )
}

function Proposals({ pending, decided, onDecide, toast }) {
  const [notes, setNotes] = useState({})
  const [noteOpen, setNoteOpen] = useState({})
  const [focusedIdx, setFocusedIdx] = useState(0)
  const [confirmingId, setConfirmingId] = useState(null)
  const confirmRef = useRef(null)
  const rm = useReducedMotion()

  useEffect(() => {
    setFocusedIdx((i) => Math.min(i, Math.max(0, pending.length - 1)))
  }, [pending.length])

  useEffect(() => {
    if (confirmingId != null) confirmRef.current?.focus()
  }, [confirmingId])

  useEffect(() => {
    if (confirmingId != null && !pending.some((proposal) => proposal.id === confirmingId)) {
      setConfirmingId(null)
    }
  }, [confirmingId, pending])

  const requestApproval = (proposal) => {
    if (proposal.reversibility === 'hard_to_reverse') {
      setConfirmingId(proposal.id)
      return
    }
    onDecide(proposal.id, 'approve', notes[proposal.id] || '')
  }

  const confirmApproval = (proposal) => {
    setConfirmingId(null)
    onDecide(proposal.id, 'approve', notes[proposal.id] || '', { confirmed_hard_to_reverse: true })
  }

  // Desktop keyboard triage (SPEC-v14 W13): j/k walk the list, a/r decide the
  // focused proposal, mirroring the pattern The Line already uses for an
  // identical "decide on one item, move to the next" flow. Never fires while
  // typing (the note field, or the command palette's own input).
  useEffect(() => {
    if (!pending.length) return undefined
    const onKey = (e) => {
      const tag = e.target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return
      if (e.key === 'j' || e.key === 'ArrowDown') {
        e.preventDefault(); setFocusedIdx((i) => Math.min(i + 1, pending.length - 1))
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        e.preventDefault(); setFocusedIdx((i) => Math.max(i - 1, 0))
      } else if (e.key === 'a') {
        const p = pending[focusedIdx]
        if (p) requestApproval(p)
      } else if (e.key === 'r') {
        const p = pending[focusedIdx]
        if (p) onDecide(p.id, 'reject', notes[p.id] || '')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pending, focusedIdx, notes, onDecide, confirmingId])

  return (
    <div className="proposals">
      {pending.length === 0 && (
        <div className="empty">
          <div className="empty-title">No pending proposals</div>
          <p>Agents file proposals here when they want something to change, money moves from cfo, schedule blocks from scout, filings from watchdog. Run <code>make run</code> to trigger tonight's pass.</p>
        </div>
      )}
      {pending.length > 1 && (
        <p className="proposals-hint dim">j/k to move &middot; a approve &middot; r reject</p>
      )}
      <AnimatePresence initial={false}>
        {pending.map((p, i) => (
          <motion.article key={p.id} className={`proposal${i === focusedIdx ? ' focused' : ''}`} layout={!rm}
            initial={rm ? false : { opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={rm ? { opacity: 0 } : { opacity: 0, x: 40, transition: { duration: 0.2 } }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
            <header>
              <span className="prop-id">#{p.id}</span>
              <RoleTag role={p.role} />
              <span className={`kind kind-${p.kind}`}>{KIND_LABEL[p.kind] || p.kind}</span>
              <span className="dim right">{relTime(p.created_at)}</span>
            </header>
            <div className="prop-action">{p.action}</div>
            <ClampedText className="prop-reasoning" text={p.reasoning} />
            <ProposalMetadata proposal={p} />
            {!!p.has_attachment && <ProposalDraft proposal={p} toast={toast} />}
            {noteOpen[p.id] && (
              <div className="prop-note-row">
                <input
                  autoFocus
                  placeholder="note to the agents…"
                  aria-label={`note for proposal ${p.id}`}
                  value={notes[p.id] || ''}
                  onChange={(e) => setNotes({ ...notes, [p.id]: e.target.value })}
                />
              </div>
            )}
            <div className="prop-controls">
              <button className="btn approve primary" onClick={() => requestApproval(p)}>
                {p.reversibility === 'hard_to_reverse' ? 'Review approval' : 'Approve'}
              </button>
              <button className="btn reject" onClick={() => {
                setConfirmingId(null)
                onDecide(p.id, 'reject', notes[p.id] || '')
              }}>Reject</button>
              <button type="button" className={`note-toggle${noteOpen[p.id] ? ' on' : ''}`}
                      aria-expanded={Boolean(noteOpen[p.id])}
                      onClick={() => setNoteOpen({ ...noteOpen, [p.id]: !noteOpen[p.id] })}>
                {noteOpen[p.id] ? '− note' : '+ note'}
              </button>
            </div>
            {confirmingId === p.id && (
              <div className="prop-hard-confirm" role="group" aria-label={`Confirm approval for proposal ${p.id}`}>
                <p>This decision is hard to reverse.</p>
                <div>
                  <button ref={confirmRef} type="button" className="btn approve" onClick={() => confirmApproval(p)}>
                    Confirm approval
                  </button>
                  <button type="button" className="btn ghost" onClick={() => setConfirmingId(null)}>Cancel</button>
                </div>
              </div>
            )}
          </motion.article>
        ))}
      </AnimatePresence>
      {decided.length > 0 && (
        <div className="decided">
          <div className="section-label">Decided recently</div>
          {decided.map((p) => (
            <div key={p.id} className="decided-row">
              <span className={`decided-verdict ${p.status === 'APPROVED' ? 'approved' : 'rejected'}`}>
                {p.status === 'APPROVED' ? 'Approved' : 'Rejected'}
              </span>
              <span className="dim">#{p.id} {p.action}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Clamps long text to 3 lines with a "Show more" toggle when it overflows.
function ClampedText({ text, className = '', renderBody }) {
  const [expanded, setExpanded] = useState(false)
  const [overflows, setOverflows] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (el) setOverflows(el.scrollHeight > el.clientHeight + 1)
  }, [text])
  return (
    <>
      {renderBody
        ? renderBody(ref, expanded ? className : `${className} clamped`)
        : <div ref={ref} className={expanded ? className : `${className} clamped`}>{text}</div>}
      {(overflows || expanded) && (
        <button type="button" className="memo-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </>
  )
}

// ------------------------------------------------------------ memo feed

const PRIORITY_LABEL = { 0: 'FYI', 1: 'normal', 2: 'important', 3: 'urgent' }

function dayLabel(ts) {
  if (!ts) return 'Earlier'
  const d = ts.slice(0, 10)
  const today = new Date()
  const iso = (dt) => dt.toISOString().slice(0, 10)
  const local = (dt) => new Date(dt.getTime() - dt.getTimezoneOffset() * 60000)
  const todayIso = iso(local(today))
  const yest = new Date(today.getTime() - 86400000)
  if (d === todayIso) return 'Today'
  if (d === iso(local(yest))) return 'Yesterday'
  return d
}

function MemoFeed({ memos, filter = 'all' }) {
  const rm = useReducedMotion()
  const shown = memos.filter((m) => {
    const p = m.priority ?? 1
    if (filter === 'p2') return p >= 2
    if (filter === 'p3') return p >= 3
    return true
  })
  let lastDay = null
  return (
    <div className="feed">
      {memos.length === 0 && (
        <div className="empty">
          <div className="empty-title">No agent notes yet</div>
          <p>This is the agents' blackboard, every memo they write to each other (and every decision you make) lands here. It fills up after <code>make run</code>.</p>
        </div>
      )}
      {memos.length > 0 && shown.length === 0 && (
        <div className="empty"><p>No memos at this priority.</p></div>
      )}
      <AnimatePresence initial={false}>
        {shown.map((m) => {
          const p = m.priority ?? 1
          const day = dayLabel(m.created_at)
          const divider = day !== lastDay
          lastDay = day
          return (
            <React.Fragment key={m.id}>
              {divider && <div className="feed-day">{day}</div>}
              <motion.article className={`memo memo-p${p}`}
                initial={rm ? false : { opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, ease: 'easeOut' }}>
                <header>
                  <span className={`prio-dot prio-${p}`} aria-hidden="true" />
                  {p >= 2 && <span className={`prio-word p${p}`}>{PRIORITY_LABEL[p]}</span>}
                  <RoleTag role={m.from_role} />
                  <span className="memo-topic" title={m.topic}>{m.topic}</span>
                  <span className="dim right">{relTime(m.created_at)}</span>
                </header>
                <ClampedText text={m.body}
                             renderBody={(ref, cls) => <p ref={ref} className={cls}>{bold(m.body)}</p>} />
              </motion.article>
            </React.Fragment>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

// ------------------------------------------------------------- log page

function LogPage({ onLogged, toast, wellnessToday, activityToday }) {
  const act = activityToday || {}
  const [note, setNote] = useState('')
  const [healthToday, setHealthToday] = useState(null)
  const currentWellness = healthToday || wellnessToday || {}
  const [sleep, setSleep] = useState(currentWellness.sleep_hours ?? '')
  const [energy, setEnergy] = useState(currentWellness.energy ?? null)
  const [workout, setWorkout] = useState(currentWellness.manual_workout || currentWellness.workout || '')

  useEffect(() => {
    let cancelled = false
    api('/api/health/today', 'GET', undefined, { cache: 'no-store' })
      .then((payload) => { if (!cancelled) setHealthToday(payload) })
      .catch(() => { /* Older server or sleeping Mac: preserve the state fallback. */ })
    return () => { cancelled = true }
  }, [])

  // Depend on the primitive fields, not the wellnessToday object: refresh()
  // hands back a freshly parsed object every 15s even when nothing changed,
  // which would otherwise reset a half-typed field out from under the user.
  useEffect(() => {
    setSleep(currentWellness.sleep_hours ?? '')
    setEnergy(currentWellness.energy ?? null)
    setWorkout(currentWellness.manual_workout || currentWellness.workout || '')
  }, [currentWellness.sleep_hours, currentWellness.energy, currentWellness.manual_workout, currentWellness.workout])

  const bump = async (field) => {
    try {
      const r = await api('/api/activity', 'POST', { [field]: 1 }, { queueable: true })
      toast(r?.queued ? '+1 saved. Syncs when your Mac wakes' : '+1 logged', 'good')
      onLogged()
    } catch (e) { toast(e.message, 'crit') }
  }

  const saveNote = async () => {
    if (!note.trim()) return
    try {
      const r = await api('/api/activity', 'POST', { notes: note }, { queueable: true })
      setNote('')
      toast(r?.queued ? 'note saved. Syncs when your Mac wakes' : 'note saved', 'good')
      onLogged()
    } catch (e) { toast(e.message, 'crit') }
  }

  const saveWellness = async (patch = {}) => {
    const body = { ...patch }
    if (sleep !== '' && sleep != null) body.sleep_hours = Number(sleep)
    if (energy != null) body.energy = Number(energy)
    if (workout && workout !== 'rest') body.workout = workout
    if (!Object.keys(body).length) { toast('pick something to log', 'warn'); return }
    try {
      const r = await api('/api/wellness', 'POST', body, { queueable: true })
      toast(r?.queued ? 'wellness saved. Syncs when your Mac wakes' : 'wellness saved', 'good')
      onLogged()
    } catch (e) { toast(e.message, 'crit') }
  }

  return (
    <div className="log-page">
      <section className="log-section">
        <h3>Sales activity</h3>
        <div className="log-grid">
          <button type="button" className="log-tap" onClick={() => bump('audit_calls')}>
            Calls
            <span className="log-tap-count">{act.audit_calls || 0}</span>
          </button>
          <button type="button" className="log-tap" onClick={() => bump('follow_ups')}>
            Follow-ups
            <span className="log-tap-count">{act.follow_ups || 0}</span>
          </button>
          <button type="button" className="log-tap" onClick={() => bump('demos')}>
            Demos
            <span className="log-tap-count">{act.demos || 0}</span>
          </button>
        </div>
        <input className="ql-note" placeholder="Note about a lead or call…" value={note}
               aria-label="Note about a lead or call" enterKeyHint="done"
               onKeyDown={(e) => e.key === 'Enter' && saveNote()}
               onChange={(e) => setNote(e.target.value)} />
        <button className="btn log" onClick={saveNote} disabled={!note.trim()}>Save note</button>
      </section>

      <section className="log-section">
        <h3>Wellness</h3>
        <div className="log-field-group">
          <label className="ql-field">
            <span>Sleep (hours)</span>
            <input className="log-sleep-input" type="number" min="0" max="24" step="0.5" value={sleep}
                   inputMode="decimal" enterKeyHint="done"
                   onChange={(e) => setSleep(e.target.value)} />
          </label>
        </div>
        <div className="log-field-group">
          <div className="ql-field"><span>Energy</span></div>
          <div className="energy-row">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button"
                      className={`energy-btn${energy === n ? ' on' : ''}`}
                      onClick={() => setEnergy(n)}>{n}</button>
            ))}
          </div>
        </div>
        <div className="log-field-group">
          <div className="ql-field"><span>Workout</span></div>
          <div className="segmented" role="radiogroup" aria-label="workout type">
            {['mma', 'lift', 'soccer', 'run', 'rest'].map((t) => (
              <button key={t} type="button" role="radio" aria-checked={workout === t}
                      className={workout === t ? 'seg-on' : ''}
                      onClick={() => setWorkout(workout === t ? '' : t)}>
                {t === 'mma' ? 'MMA' : cap(t)}
              </button>
            ))}
          </div>
        </div>
        <button className="btn log" onClick={() => saveWellness()}>Save wellness</button>
      </section>
    </div>
  )
}

function InboxPage({ state, onDecide, refresh, toast }) {
  // SPEC-v19: correspondence from ianmccallum.com. Deliberately NOT the BtC
  // tab and deliberately not a lead: these are people writing to Ian, not
  // rows in Clockwork's call queue.
  const personal = (state.inbound?.pending || []).filter((r) => r.source === 'personal')
  return (
    <>
      {personal.length > 0 && (
        <PersonalInbound requests={personal} refresh={refresh} toast={toast} />
      )}
      <Panel title="Pending proposals"
             tag={state.pending_proposals.length ? `${state.pending_proposals.length} waiting` : 'All clear'}>
        <Proposals pending={state.pending_proposals}
                   decided={state.recent_decisions}
                   onDecide={onDecide}
                   toast={toast} />
      </Panel>
    </>
  )
}

/** Messages from ianmccallum.com. No stage, no pipeline, no score: the only
 *  two things you can do with a note from a person are answer it or let it
 *  go. Same wilt-not-redden law as everywhere else. */
function PersonalInbound({ requests, refresh, toast }) {
  const [busy, setBusy] = useState(null)
  const dismiss = async (id) => {
    setBusy(id)
    try {
      await api(`/api/inbound/${id}/dismiss`, 'POST')
      toast('Dismissed', 'good')
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setBusy(null)
    }
  }
  return (
    <Panel title="Messages" tag={`${requests.length} waiting`}>
      <div className="inbound-stack">
        {requests.map((r) => {
          const wilted = Date.now() - Date.parse(r.received_at) > 7 * 86400000
          return (
            <div key={r.id} className={`inbound-card${wilted ? ' wilted' : ''}`}>
              <div className="inbound-head">
                <strong>{r.name || r.email}</strong>
                <span className="inbound-kind contact">ianmccallum.com</span>
              </div>
              {!!r.message && <p className="inbound-line">{r.message}</p>}
              {!!r.email && (
                <a className="btn log inbound-reply" href={`mailto:${r.email}`}>Reply</a>
              )}
              <button type="button" className="inbound-dismiss dim"
                      disabled={busy === r.id} onClick={() => dismiss(r.id)}>
                dismiss
              </button>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

/** The agent memo feed. It used to be called "Notes", which it never was, it
 *  is read-only agent chatter, not something Ian writes. It now lives under
 *  Inbox, alongside the decisions it belongs with, and the Notes tab is a real
 *  notes app (pages/NotesPage.jsx, SPEC-v10 §5). */
function AgentMemoFeed({ memos }) {
  const [filter, setFilter] = useState('all')
  const FILTERS = [['all', 'All'], ['p2', 'P2+'], ['p3', 'P3']]
  return (
    <Panel title="Agent notes" tag={`${memos.length} total`}
           actions={
             <div className="memo-filter" role="group" aria-label="Filter memos by priority">
               {FILTERS.map(([id, label]) => (
                 <button key={id} type="button"
                         className={`memo-filter-btn${filter === id ? ' active' : ''}`}
                         onClick={() => setFilter(id)}>{label}</button>
               ))}
             </div>
           }>
      <MemoFeed memos={memos} filter={filter} />
    </Panel>
  )
}

// --------------------------------------------------------------- header

const PAGE_TITLES = {
  home: 'Command',
  plan: 'Plan',
  shutdown: 'Journal',
  journal: 'Journal',
  btc: 'Beat the Clock',
  body: 'Body',
  partner: 'Partner',
  school: 'School',
  schoolnotebook: 'Class notes',
  life: 'Life',
  learning: 'Learning',
  money: 'Money',
  moneyhistory: 'Transaction history',
  memory: 'Memory',
  inbox: 'Inbox',
  log: 'Log',
  notes: 'Notes',
  roster: 'Roster',
  goals: 'Beat the Clock',
}

// SPEC-v41 §4.5: the Command tab's icon exists twice in the DOM at once (the
// desktop rail and the mobile bar, each hidden by CSS on the other's
// breakpoint, never unmounted), so a bare querySelector can land on the
// hidden copy and return a zero-size rect. Take the first copy that's
// actually laid out.
function navCommandIconRect() {
  const nodes = document.querySelectorAll('[data-nav-id="home"]')
  for (const node of nodes) {
    const rect = node.getBoundingClientRect()
    if (rect.width > 0 && rect.height > 0) return rect
  }
  return nodes[0]?.getBoundingClientRect() || { left: 0, top: 0, width: 0, height: 0 }
}

function FlyingDot({ from, to, onDone }) {
  const start = { left: from.left + from.width / 2, top: from.top + from.height / 2 }
  const end = { left: to.left + to.width / 2, top: to.top + to.height / 2 }
  return (
    <motion.span
      className="priority-fly-dot"
      initial={start}
      animate={end}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      onAnimationComplete={onDone}
    />
  )
}

function usePage() {
  const [page, setPage] = useState(() => {
    const h = window.location.hash.replace('#', '')
    if (h === 'goals') return 'btc'
    if (h === 'shutdown') return 'journal'
    // SPEC-v26: chat became the Command surface, so its old route folds home.
    if (h === 'chat') return 'home'
    return PAGES.includes(h) ? h : 'home'
  })
  useEffect(() => {
    const sync = () => {
      let h = window.location.hash.replace('#', '')
      if (h === 'goals') {
        window.location.hash = 'btc'
        h = 'btc'
      }
      // SPEC-v11: Shutdown merged into Journal, keep the hash for old links.
      if (h === 'shutdown') {
        window.location.hash = 'journal'
        h = 'journal'
      }
      setPage(h === 'chat' ? 'home' : (PAGES.includes(h) ? h : 'home'))
    }
    if (!window.location.hash || window.location.hash === '#') window.location.hash = 'home'
    if (window.location.hash === '#goals') window.location.hash = 'btc'
    if (window.location.hash === '#shutdown') window.location.hash = 'journal'
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  const navigate = (id) => {
    window.location.hash = id === 'goals' ? 'btc' : id === 'shutdown' ? 'journal' : id
  }
  return [page, navigate]
}

// ------------------------------------------------------------------ app

let toastSeq = 0

export default function App() {
  const [unlocked, setUnlocked] = useState(() => isUnlocked())
  const [state, setState] = useState(null)
  const [offline, setOffline] = useState(false)
  const [stale, setStale] = useState(null)     // serving a cached snapshot
  const [pending, setPending] = useState(0)    // writes waiting for the Mac
  const [deadEntries, setDeadEntries] = useState([]) // terminal queue failures, never hidden
  const [queueProblem, setQueueProblem] = useState(null)
  const [toasts, setToasts] = useState([])
  const [page, rawNavigate] = usePage()
  // Which way a swipe sent us, so the incoming page finishes the motion the
  // thumb started (0 = arrived by tap, which keeps the plain fade).
  //
  // A ref, NOT state, and that is the whole point: this is read once while
  // rendering the new page. Held as state, clearing it re-rendered mid-flight
  // and stranded the page at its initial values, opacity 0, permanently blank.
  const swipeDir = useRef(0)
  const navigate = useCallback((id) => { swipeDir.current = 0; rawNavigate(id) }, [rawNavigate])
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette()
  const [apiReady, setApiReady] = useState(true)
  // The Line (SPEC-v9): call mode dims the shell exactly like shutdown mode;
  // bloom is a counter the aurora swells on when a milestone lands.
  const [callMode, setCallMode] = useState(false)
  const [bloom, setBloom] = useState(0)
  const [journalComposing, setJournalComposing] = useState(false)
  const [journalFocus, setJournalFocus] = useState(0)
  // Deep-link for the Money history page's account filter, same
  // sessionStorage + read-on-page-change convention as journalFocus above,
  // written by AccountSheet's "View all transactions" (SPEC-v24 BUILD 4).
  const [historyAccountKey, setHistoryAccountKey] = useState(null)
  // SPEC-v41 §4.5: Life's priority toggle sends a dot flying to the Command
  // tab icon. Lifted here because the choreography spans Life's TodayPanel
  // and the fixed Nav bar, two components with no shared parent closer than this.
  const [flyingDot, setFlyingDot] = useState(null)
  const onFlyPriorityDot = useCallback((fromRect) => setFlyingDot(fromRect), [])
  // SPEC-v37 §7.1-7.3: the unified replacement for the old Ask sheet, inspect
  // mode, and rooms (all deleted). AgentChat keeps its one mount in App.jsx
  // (Law A10 -- position is a portal, lifecycle is a mount) and owns its own
  // dock/expanded/fullscreen view state internally; this is the one piece of
  // App-level state that hands it a request to open (or create) a thread,
  // optionally seed the composer, and switch view. AgentChat clears it via
  // onConsultRequestHandled once it has acted on it.
  const [consultRequest, setConsultRequest] = useState(null)
  const requestConsult = useCallback((req) => setConsultRequest(req), [])
  const handleConsultRequestHandled = useCallback(() => setConsultRequest(null), [])
  const onBloom = useCallback(() => setBloom((b) => b + 1), [])
  // "Open chat" with no particular agent or seed text: reopen whatever
  // thread is already active (or the default agent), in the expanded view.
  const openChat = useCallback(
    () => requestConsult({ seedText: '', view: 'expanded' }),
    [requestConsult],
  )
  // Roster's "Ask <Codename>" button: always passes a concrete role.
  const openAskAgent = useCallback(
    (role = '') => requestConsult(role ? { role, seedText: '', view: 'expanded' } : { seedText: '', view: 'expanded' }),
    [requestConsult],
  )
  // Record "Inspect" triggers (Money/MoneyHistory/AccountSheet). entity is
  // {kind, id, role}; label is the short display string those callers already
  // built. Opens that agent's thread with a plain seeded question, never sent
  // automatically -- Ian reviews and sends it himself.
  const openInspect = useCallback((entity, label) => {
    if (!entity || !entity.kind || !entity.id || !entity.role) return
    const what = label || entity.kind
    requestConsult({ role: entity.role, seedText: `About ${what}: what should I know?`, view: 'expanded' })
  }, [requestConsult])
  // A detail route is deliberately not in global navigation. The School page
  // and a verified Plan commitment can both hand it one schedule-derived
  // intent, which survives the route change without pushing note documents
  // into /api/state or re-deriving class recurrence in the browser.
  const openSchoolNote = useCallback((intent = {}) => {
    stashSchoolNotebookIntent(intent)
    navigate('schoolnotebook')
  }, [navigate])
  const timer = useRef(null)
  const rm = useReducedMotion()

  // The mobile tab bar is intentionally portaled to document.body (Nav.jsx),
  // outside .app-shell, so the `.call-mode`/`.journal-mode` selectors above
  // can't reach it. Mirror both flags onto body so the one dimming scale the
  // product calls for actually covers the brightest chrome on screen too.
  useEffect(() => {
    document.body.classList.toggle('call-mode', callMode)
    document.body.classList.toggle('journal-mode', journalComposing)
    return () => {
      document.body.classList.remove('call-mode', 'journal-mode')
    }
  }, [callMode, journalComposing])

  const onRelock = useCallback(() => {
    lockNow()
    setUnlocked(false)
    setState(null)
    setCallMode(false)
    setJournalComposing(false)
    // The lock screen is a full early-return (see below): nothing in the
    // authenticated tree, AgentChat included, renders while locked, so it
    // naturally unmounts and remounts fresh on next unlock. Only a pending
    // consult request needs an explicit reset, so it doesn't fire stale
    // against whatever thread AgentChat resumes after the next unlock.
    setConsultRequest(null)
  }, [])

  useEffect(() => attachRelockListeners(onRelock), [onRelock])

  // Deep-link / nudge: focus the composer when arriving via Close the day.
  useEffect(() => {
    if (page === 'journal' && sessionStorage.getItem('journal-focus') === '1') {
      sessionStorage.removeItem('journal-focus')
      setJournalFocus((n) => n + 1)
    }
    if (page !== 'journal') setJournalComposing(false)
    // A stray tap away from The Line mid-call must not leave the shell dimmed
    // (TheLine's own unmount cleanup covers the common case; this covers
    // navigating to the SAME mounted BeatTheClockPage's other content without
    // TheLine unmounting, and any future reachability from elsewhere).
    if (page !== 'btc' && page !== 'goals') setCallMode(false)
    // Deep-link: AccountSheet's "View all transactions" stashes an account
    // key before navigating here (same mechanism as journal-focus above).
    // Consumed once, then cleared, so a plain revisit (back button, a typed
    // #moneyhistory) starts at "All accounts" instead of a stale filter.
    if (page === 'moneyhistory') {
      const key = sessionStorage.getItem('money-history-account')
      if (key) {
        sessionStorage.removeItem('money-history-account')
        setHistoryAccountKey(key)
      }
    } else {
      setHistoryAccountKey(null)
    }
  }, [page])

  // `undo` turns the toast into the confirmation step. A soft delete plus an
  // undo beats an "are you sure?", it never interrupts the 99% of taps that
  // meant it, and still rescues the 1% that didn't.
  const toast = useCallback((msg, level = 'good', undo = null) => {
    const id = ++toastSeq
    setToasts((t) => [...t, { id, msg, level, undo }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), undo ? 8000 : 3200)
  }, [])

  const dismissDead = useCallback((mutationId) => {
    try {
      dismissDeadLetter(mutationId)
      setDeadEntries(deadLetters())
      setQueueProblem(queueIssue())
    } catch (e) { toast(e.message, 'warn') }
  }, [toast])

  const refresh = useCallback(async () => {
    try {
      // fetchState reports whether the service worker served a cached snapshot
      // (i.e. the Mac is asleep) so the UI can be honest about freshness.
      const { state: next, cached, fetchedAt } = await fetchState()
      setState(next)
      setStale(cached ? { at: fetchedAt } : null)
      setOffline(false)
    } catch { setOffline(true) }
  }, [])

  // SPEC-v12: no state poll until unlocked (privacy curtain).
  useEffect(() => {
    if (!unlocked) {
      if (timer.current) clearInterval(timer.current)
      timer.current = null
      return undefined
    }
    refresh()
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => setApiReady(Boolean(h?.features?.partner_tasks)))
      .catch(() => setApiReady(false))
    timer.current = setInterval(refresh, 15000)
    return () => clearInterval(timer.current)
  }, [refresh, unlocked])

  // Replay anything captured while the Mac was unreachable.
  useEffect(() => {
    if (!unlocked) return undefined
    const refreshQueueState = () => {
      setPending(pendingCount())
      setDeadEntries(deadLetters())
      setQueueProblem(queueIssue())
    }
    refreshQueueState()
    const unsub = onQueueChange(refreshQueueState)
    const { run, stop } = startAutoFlush(({ sent, dead, error }) => {
      if (sent) toast(`synced ${sent} offline ${sent === 1 ? 'entry' : 'entries'}`, 'good')
      if (dead) toast(`${dead} offline ${dead === 1 ? 'entry needs' : 'entries need'} attention`, 'warn')
      if (error) toast(error, 'warn')
      refreshQueueState()
      if (sent) refresh()
    })
    run()
    return () => { stop(); unsub() }
  }, [refresh, toast, unlocked])

  const decide = useCallback(async (id, decision, note, options = {}) => {
    try {
      const confirmation = options.confirmed_hard_to_reverse === true
        ? { confirmed_hard_to_reverse: true }
        : {}
      await api(`/api/proposals/${id}/decide`, 'POST', { decision, note, ...confirmation })
      toast(`proposal #${id} ${decision === 'approve' ? 'approved' : 'rejected'}. Memo sent to agents`, 'good')
      refresh()
    } catch (e) { toast(e.message, 'crit') }
  }, [refresh, toast])

  // CommandPage's own memo guard checks `prev.roster === next.roster` by
  // reference, so this needs a stable identity across polls, not just a
  // useMemo keyed on state.roster: fetchState() hands back a freshly
  // JSON-parsed array every 15s even when the roster itself hasn't changed.
  // Keying on the content, not the array reference, is what actually skips
  // the re-render (and the redundant /api/day fetch CommandPage does on
  // mount) when nothing changed.
  const rosterSignature = JSON.stringify(state?.roster || [])
  const rosterMap = useMemo(
    () => Object.fromEntries((state?.roster || []).map((r) => [r.role, r])),
    [rosterSignature],
  )

  if (!unlocked) {
    return (
      <>
        <AuroraBackground />
        <div className="app-grain" aria-hidden="true" />
        <LockScreen onUnlocked={() => setUnlocked(true)} />
      </>
    )
  }

  if (!state) {
    return (
      <>
        <AuroraBackground />
        <div className="app-grain" aria-hidden="true" />
        <div className="boot" role="status" aria-live="polite">
          <img className="boot-logo" src="/logo-lockup.png" alt="ianOS" width="640" height="306" decoding="async" />
          <span className="boot-copy">
            {offline ? <>API offline. Run <code>make dev</code></> : 'Loading'}
          </span>
        </div>
      </>
    )
  }

  const briefIsToday = state.brief && state.brief.governs_date === state.today
  const title = PAGE_TITLES[page] || PAGE_TITLES.home
  const partnerOpen = Number.isInteger(state.partner_summary?.open_count)
    ? state.partner_summary.open_count
    : 0
  // Red badge is earned, not default: a P3 memo today or a live deadline <7d.
  const urgent = (state.memos || []).some((m) => (m.priority ?? 1) >= 3 && dayLabel(m.created_at) === 'Today')
    || (state.goals || []).some((g) => g.kind === 'deadline' && g.days_remaining != null
        && g.days_remaining < 7 && g.status !== 'ON TRACK')

  return (
    <RosterContext.Provider value={rosterMap}>
    {/* First focusable element in the DOM (SPEC-v14 W6): without this, a
        keyboard visit tabs through all 14+ nav-rail links before reaching
        any page content, on a product whose whole premise is a sub-two-
        minute check-in. */}
    <a href="#main-content" className="skip-link">Skip to content</a>
    <AuroraBackground bloom={bloom} />
    <div className="app-grain" aria-hidden="true" />
    <div className={`app-shell${journalComposing ? ' journal-mode' : ''}${callMode ? ' call-mode' : ''}`}>
      <div className="nav-wrap">
        <Nav page={page === 'schoolnotebook' ? 'school' : page} onNavigate={navigate}
             pending={(state.pending_proposals || []).length}
             urgent={urgent}
             partnerOpen={partnerOpen}
             onOpenPalette={() => setPaletteOpen(true)} />
      </div>

      <main id="main-content" className="app-main">
        {/* A page named by a pinned tab does not repeat its own name on mobile
            (SPEC-v10 L3), the lit tab already says where you are. Pages that
            live behind "More" keep their title, because nothing else names them. */}
        {page !== 'schoolnotebook' && <header className={`page-header${TAB_PAGES.includes(page) ? ' page-header-quiet' : ''}`}>
          <div className="page-title-row">
            <h1 className="page-title">{title}</h1>
            {page === 'partner' && partnerOpen > 0 && <span className="partner-open-chip">{partnerOpen} open</span>}
          </div>
          <DayArc header={state.header} onOpenPlan={() => navigate('plan')} onOpenRoster={() => navigate('roster')} />
        </header>}

        {/* Mac asleep: say so plainly rather than showing stale data as live. */}
        {(stale || pending > 0 || deadEntries.length > 0 || queueProblem) && (
          <div className="offline-bar" role="status">
            {stale && (
              <span>
                Showing your last synced view{stale.at ? ` (${relTime(stale.at)})` : ''}.
                Your Mac is asleep.
              </span>
            )}
            {pending > 0 && (
              <span className="offline-pending">
                {pending} {pending === 1 ? 'entry' : 'entries'} waiting to sync
              </span>
            )}
            {queueProblem && <span className="offline-problem">{queueProblem}</span>}
            {deadEntries.length > 0 && (
              <details className="offline-dead">
                <summary>
                  {deadEntries.length} offline {deadEntries.length === 1 ? 'entry needs' : 'entries need'} attention
                </summary>
                <ul>
                  {deadEntries.map((entry) => (
                    <li key={`${entry.mutation_id}-${entry.failed_at}`}>
                      <span>{entry.detail || 'Server rejected this action.'}</span>
                      <button type="button" onClick={() => dismissDead(entry.mutation_id)}>
                        Dismiss
                      </button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {/* enter-only: exit choreography raced hash navigation and could
            strand the old page half-faded (mode="wait" swap never firing).
            Swipe handlers ride on this element; they are disabled inside
            committed modes, which must never be exitable by a stray thumb. */}
          <motion.div
            key={page}
            className="page-content"
            initial={
              rm ? false
                : swipeDir.current ? { opacity: 0, x: swipeDir.current * 32 }
                : page === 'home' ? false
                : { opacity: 0, y: 10 }
            }
            animate={{ opacity: 1, x: 0, y: 0 }}
            transition={{ duration: swipeDir.current ? 0.26 : 0.22, ease: [0.22, 1, 0.36, 1] }}
            {...pillarSwipeHandlers(
              page,
              (id, dir) => { swipeDir.current = dir; rawNavigate(id) },
              !journalComposing && !callMode,
            )}
          >
            {page === 'home' && (
              <CommandPage
                state={state}
                briefIsToday={briefIsToday}
                navigate={(id) => {
                  if (id === 'shutdown' || id === 'journal') {
                    sessionStorage.setItem('journal-focus', '1')
                    navigate('journal')
                  } else navigate(id)
                }}
                toast={toast}
                refresh={refresh}
                attentionFresh={!stale}
                onOpenChat={openChat}
              />
            )}
            {page === 'plan' && (
              <PlanPage state={state} refresh={refresh} toast={toast} onOpenSchoolNote={openSchoolNote} />
            )}
            {page === 'journal' && (
              <JournalPage
                toast={toast}
                refresh={refresh}
                onComposingChange={setJournalComposing}
                focusCompose={journalFocus}
              />
            )}
            {page === 'btc' && (
              <BeatTheClockPage state={state} refresh={refresh} toast={toast}
                                onCallMode={setCallMode} onBloom={onBloom} />
            )}
            {page === 'body' && (
              <BodyPage state={state} refresh={refresh} toast={toast} />
            )}
            {page === 'school' && (
              <SchoolPage state={state} refresh={refresh} toast={toast} onOpenSchoolNote={openSchoolNote} />
            )}
            {page === 'schoolnotebook' && (
              <SchoolNotebookBoundary onBack={() => navigate('school')}>
                <SchoolNotebookPage state={state} toast={toast} onBack={() => navigate('school')} />
              </SchoolNotebookBoundary>
            )}
            {page === 'life' && (
              <LifePage state={state} refresh={refresh} toast={toast} onFlyPriorityDot={onFlyPriorityDot} />
            )}
            {page === 'learning' && (
              <LearningPage state={state} refresh={refresh} toast={toast} requestConsult={requestConsult} />
            )}
            {page === 'goals' && (
              <BeatTheClockPage state={state} refresh={refresh} toast={toast}
                                onCallMode={setCallMode} onBloom={onBloom} />
            )}
            {page === 'money' && (
              <MoneyPage state={state} refresh={refresh} toast={toast}
                         navigate={navigate} onInspect={openInspect} onOpenChat={openChat} />
            )}
            {page === 'moneyhistory' && (
              <MoneyHistoryPage state={state} initialAccountKey={historyAccountKey} onInspect={openInspect} />
            )}
            {page === 'partner' && (
              <PartnerPage
                tasks={state.partner_tasks || []}
                summary={state.partner_summary}
                onTasksChange={(tasks) => setState((s) => (s ? { ...s, partner_tasks: tasks } : s))}
                toast={toast}
                apiReady={apiReady}
                state={state}
                refresh={refresh}
              />
            )}
            {page === 'inbox' && (
              <div className="inbox-page">
                <InboxPage state={state} onDecide={decide} refresh={refresh} toast={toast} />
                <AgentMemoFeed memos={state.memos} />
              </div>
            )}
            {page === 'log' && (
              <LogPage onLogged={refresh} toast={toast}
                       wellnessToday={state.wellness_today}
                       activityToday={state.activity_today} />
            )}
            {page === 'memory' && (
              <MemoryPage facts={state.facts || []} toast={toast} onChange={refresh} />
            )}
            {page === 'notes' && (
              <NotesPage toast={toast} />
            )}
            {page === 'roster' && (
              <RosterPage toast={toast} onAskAgent={openAskAgent} />
            )}
          </motion.div>
      </main>
    </div>

    {flyingDot && (
      <FlyingDot from={flyingDot} to={navCommandIconRect()} onDone={() => setFlyingDot(null)} />
    )}

    <CommandPalette
      open={paletteOpen}
      onClose={() => setPaletteOpen(false)}
      onNavigate={navigate}
      // SPEC-v37 §7.3 deleted /api/agent-commands (the server-side role
      // resolver this used to hand off to) along with the Ask sheet it
      // opened. CommandPalette now resolves "ask <agent> <question>"
      // against state.roster itself (lib/agentCommands.js) and hands back
      // the resolved role + question directly; a "resume #N" command no
      // longer exists (threads are per-role, not per-invocation).
      onAskAgent={(role, question) => requestConsult({ role, seedText: question, view: 'expanded' })}
      state={state}
    />

    {/* SPEC-v37 §7.1: AgentChat is always mounted, sibling to <Nav> and the
        toast stack below, never inside a page component, so it never shares
        a page's unmount schedule (Law A10). It owns its own dock/expanded/
        fullscreen view state and portals into CommandPage's dock slot when
        Command is active; consultRequest is the one hand-off point App.jsx
        uses to open a thread from elsewhere (Roster, an Inspect trigger, the
        Order's "Ask an agent" link). */}
    <AgentChat
      page={page}
      consultRequest={consultRequest}
      onConsultRequestHandled={handleConsultRequestHandled}
      toast={toast}
      navigate={navigate}
      roster={state.roster || []}
    />

    <div className="toasts" role="status" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} className={`toast toast-${t.level}`}
            initial={rm ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
            transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
            {t.msg}
            {t.undo && (
              <button type="button" className="toast-undo"
                      onClick={() => {
                        setToasts((ts) => ts.filter((x) => x.id !== t.id))
                        t.undo()
                      }}>Undo</button>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
    </RosterContext.Provider>
  )
}
