import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import Sheet from '../components/Sheet.jsx'
import SchoolNoteEditor from '../components/school-notes/SchoolNoteEditor.jsx'
import SchoolFilesPanel from '../components/school-notes/SchoolFilesPanel.jsx'
import SchoolStudyPanel from '../components/school-notes/SchoolStudyPanel.jsx'
import {
  normalizeSchoolNoteTitle, SCHOOL_NOTE_TITLE_MAX, schoolWeekStart,
  takeSchoolNotebookIntent, truncateSchoolNoteTitle,
} from '../lib/school-notebook.js'

const AUTOSAVE_MS = 650

function readNotebookIntent() {
  return takeSchoolNotebookIntent()
}

function docKey(value) {
  try { return JSON.stringify(value || {}) } catch { return '' }
}

function localDate(value) {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function sessionDate(value) {
  const parsed = localDate(`${value}T12:00:00`)
  return parsed ? new Intl.DateTimeFormat('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
  }).format(parsed) : value || 'Today'
}

function clock(value) {
  const parsed = localDate(value)
  return parsed ? new Intl.DateTimeFormat('en-US', {
    hour: 'numeric', minute: '2-digit',
  }).format(parsed) : ''
}

function sessionTypeLabel(session) {
  if (session.session_type === 'meeting') return session.meeting?.kind || 'Class'
  return 'Week'
}

function isAsyncCourse(course) {
  return !(course?.meetings || []).some((meeting) => (meeting.days || []).length > 0)
}

function timelineEntry(session) {
  const { document, plain_text, ...entry } = session
  return entry
}

function mergeSession(items, session) {
  const entry = timelineEntry(session)
  const withoutCurrent = items.filter((item) => item.id !== entry.id)
  return [entry, ...withoutCurrent].sort((a, b) => (
    b.session_date.localeCompare(a.session_date) || b.id - a.id
  ))
}

const NOTE_TEMPLATES = [
  {
    id: 'lecture',
    label: 'Lecture',
    note: 'Key ideas, examples, questions',
    headings: ['Key ideas', 'Examples', 'Revisit'],
  },
  {
    id: 'problem',
    label: 'Problem set',
    note: 'Problem, method, question',
    headings: ['What I am solving', 'Method', 'Question to ask'],
  },
  {
    id: 'review',
    label: 'Review',
    note: 'Recall, gaps, next review',
    headings: ['What I remember', 'What is fuzzy', 'Next review'],
  },
]

function templateDocument(template) {
  const headings = template?.headings || []
  return {
    type: 'doc',
    content: headings.flatMap((heading) => ([
      { type: 'heading', attrs: { level: 2 }, content: [{ type: 'text', text: heading }] },
      { type: 'paragraph' },
    ])),
  }
}

function CoursePicker({ courses, activeCode, onSelect }) {
  return (
    <label className="school-course-picker">
      <span>Course notebook</span>
      <select value={activeCode || ''} onChange={(event) => { void onSelect(event.target.value) }}>
        {courses.map((course) => <option key={course.code} value={course.code}>{course.code} · {course.name}</option>)}
      </select>
    </label>
  )
}

/** One hit with the sentence around it, the matched word left as written. */
function MatchLine({ match }) {
  return (
    <span className="school-session-match">
      {match.head ? '…' : ''}{match.before}
      <mark>{match.match}</mark>
      {match.after}{match.tail ? '…' : ''}
    </span>
  )
}

function SessionRow({ session, active, onOpen, query }) {
  const kind = sessionTypeLabel(session)
  const matches = query ? (session.matches || []) : []
  const extra = (session.match_count || 0) - matches.length
  return (
    <button
      type="button"
      className={`school-session-row${active ? ' active' : ''}`}
      onClick={() => onOpen(session.id)}
      aria-current={active ? 'page' : undefined}
    >
      <span className="school-session-row-date"><time dateTime={session.session_date}>{sessionDate(session.session_date)}</time>{session.closed_at ? ' · Finished' : ''}</span>
      <span className="school-session-row-title">{session.title || kind}</span>
      {matches.length ? (
        <span className="school-session-row-matches">
          {matches.map((match, index) => <MatchLine key={index} match={match} />)}
          {extra > 0 && <span className="school-session-match-more">{extra} more in this note</span>}
        </span>
      ) : (
        <span className="school-session-row-preview">
          {/* A title-only hit still matched; saying so beats an unexplained row. */}
          {query && session.title_match ? 'matches the title' : session.preview || 'No notes yet'}
        </span>
      )}
    </button>
  )
}

function SessionTimeline({ sessions, active, onOpen, today, query = '' }) {
  const weekStart = schoolWeekStart(today || '')
  const groups = sessions.reduce((result, session) => {
    const key = weekStart && session.session_date >= weekStart ? 'This week' : 'Earlier'
    if (!result[key]) result[key] = []
    result[key].push(session)
    return result
  }, {})
  return Object.entries(groups).map(([label, rows]) => (
    <section className="school-session-group" key={label} aria-label={label}>
      <h3>{label}</h3>
      <div className="school-session-list">
        {rows.map((session) => <SessionRow key={session.id} session={session} active={active?.id === session.id} onOpen={onOpen} query={query} />)}
      </div>
    </section>
  ))
}

function ClassPulse({ session, course, onOpenFiles, onOpenStudy }) {
  const meeting = session?.meeting || course?.next_meeting || null
  const sessionName = session ? sessionTypeLabel(session) : meeting?.kind || 'Next session'
  const sessionValue = session
    ? `${sessionName} · ${sessionDate(session.session_date)}`
    : meeting?.start_at ? `${sessionName} · ${sessionDate(meeting.start_at.slice(0, 10))}` : 'No upcoming class loaded'
  return (
    <section className="school-class-pulse" aria-label="Class context">
      <header>
        <h3>Details</h3>
        <p>{course?.code || 'Course'} · {course?.name || 'Course notebook'}</p>
      </header>
      <dl>
        <div><dt>{session ? 'This note' : 'Up next'}</dt><dd>{sessionValue}</dd></div>
        {meeting?.start_at && <div><dt>Time</dt><dd>{clock(meeting.start_at)}{meeting.end_at ? ` to ${clock(meeting.end_at)}` : ''}</dd></div>}
        {meeting?.location && <div><dt>Place</dt><dd>{meeting.location}</dd></div>}
        {course?.next_due_at && <div><dt>Due next</dt><dd>{sessionDate(course.next_due_at.slice(0, 10))}</dd></div>}
      </dl>
      <div className="school-pulse-actions">
        <button type="button" onClick={onOpenFiles}>Class files</button>
        <button type="button" onClick={onOpenStudy} disabled={!session}>Study from this note</button>
      </div>
      {!session && <p className="school-class-pulse-note">Select a session to use its study tools.</p>}
    </section>
  )
}

function NotebookLoading() {
  return (
    <div className="school-notebook-page page-stack" aria-busy="true" aria-live="polite">
      <section className="school-notebook-loading">
        <div className="school-notebook-loading-line short" />
        <div className="school-notebook-loading-line" />
        <div className="school-notebook-loading-surface" />
        <span>Loading notes…</span>
      </section>
    </div>
  )
}

export default function SchoolNotebookPage({ state, toast, onBack }) {
  const school = state?.school || {}
  const coursesAreLoaded = Array.isArray(school.courses)
  const courses = coursesAreLoaded ? school.courses : []
  const intentRef = useRef(readNotebookIntent())
  const [activeCode, setActiveCode] = useState('')
  const [sessions, setSessions] = useState([])
  const [open, setOpen] = useState(null)
  // Keep this distinct from window.document. A previous local name collision
  // made document.body resolve to the empty note state and blank the route.
  const [noteDocument, setNoteDocument] = useState(null)
  const [noteTitle, setNoteTitle] = useState('')
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [loadingNote, setLoadingNote] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [saveConflict, setSaveConflict] = useState(false)
  const [freshSession, setFreshSession] = useState(false)
  const [fileShelfOpen, setFileShelfOpen] = useState(false)
  const [studyShelfOpen, setStudyShelfOpen] = useState(false)
  const [pulseOpen, setPulseOpen] = useState(false)
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const sessionQueryRef = useRef('')
  const sessionRequestRef = useRef(0)
  const [fullScreen, setFullScreen] = useState(false)
  const [sessionQuery, setSessionQuery] = useState('')
  const [saveCycle, setSaveCycle] = useState(0)
  const openRef = useRef(null)
  const documentRef = useRef(null)
  const titleRef = useRef('')
  const titleFieldRef = useRef(null)
  const saveTimer = useRef(null)
  const saveInFlight = useRef(false)
  const savePromise = useRef(null)
  const savePending = useRef(false)
  const flushCurrentNoteRef = useRef(() => Promise.resolve(true))
  const intentApplied = useRef(false)

  const activeCourse = useMemo(
    () => courses.find((course) => course.code === activeCode) || courses[0] || null,
    [courses, activeCode],
  )

  useEffect(() => { openRef.current = open }, [open])
  useEffect(() => { documentRef.current = noteDocument }, [noteDocument])
  useEffect(() => { titleRef.current = noteTitle }, [noteTitle])
  useLayoutEffect(() => {
    const field = titleFieldRef.current
    if (!field) return undefined
    const resize = () => {
      field.style.height = 'auto'
      if (field.scrollHeight) field.style.height = `${field.scrollHeight}px`
    }
    resize()
    if (typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(resize)
    observer.observe(field.parentElement || field)
    return () => observer.disconnect()
  }, [noteTitle, open?.id])

  // Refs let a just-fired typing event be saved by an immediate “Finish session”
  // click; React state alone updates on the next render, which is too late
  // for that very common laptop interaction.
  const changeDocument = useCallback((nextDocument) => {
    documentRef.current = nextDocument
    setNoteDocument(nextDocument)
  }, [])
  const changeTitle = useCallback((nextTitle) => {
    const value = truncateSchoolNoteTitle(nextTitle)
    titleRef.current = value
    setNoteTitle(value)
  }, [])
  useEffect(() => {
    if (!courses.length || courses.some((course) => course.code === activeCode)) return
    const intentCourse = intentRef.current?.courseCode
    const nextCourse = school.next_meetings?.[0]?.course_code
    setActiveCode(courses.some((course) => course.code === intentCourse)
      ? intentCourse
      : courses.some((course) => course.code === nextCourse) ? nextCourse : courses[0].code)
  }, [courses, activeCode, school.next_meetings])

  useEffect(() => {
    window.document.body.classList.toggle('school-note-editing', !!open)
    return () => window.document.body.classList.remove('school-note-editing')
  }, [open])
  useEffect(() => {
    const active = fullScreen && !!open
    window.document.body.classList.toggle('school-note-fullscreen', active)
    return () => window.document.body.classList.remove('school-note-fullscreen')
  }, [fullScreen, open])
  useEffect(() => {
    if (!open && fullScreen) setFullScreen(false)
  }, [open, fullScreen])
  useEffect(() => () => {
    clearTimeout(saveTimer.current)
    // Global navigation unmounts this route. Start a final save instead of
    // cancelling the debounce and losing the last thing Ian typed.
    void flushCurrentNoteRef.current()
  }, [])

  // Find-in-all-notes (Ian, 2026-09-09). The search is the SERVER's, because
  // only it has the full note text: a session card carries a 280-character
  // preview, so filtering those client-side missed every word past the third
  // line and the search read as broken. The server hands back each note's
  // match count and the sentence around each hit.
  const loadSessions = useCallback(async (courseCode, query = sessionQueryRef.current) => {
    if (!courseCode) return
    const requestId = ++sessionRequestRef.current
    setLoadingSessions(true)
    try {
      const search = query ? `?q=${encodeURIComponent(query)}` : ''
      const result = await api(`/api/school/courses/${encodeURIComponent(courseCode)}/note-sessions${search}`)
      // A slow response for an older query must not overwrite a newer one.
      if (requestId !== sessionRequestRef.current) return
      setSessions(result.sessions || [])
    } catch (error) {
      if (requestId === sessionRequestRef.current) toast(error.message, 'crit')
    } finally {
      if (requestId === sessionRequestRef.current) setLoadingSessions(false)
    }
  }, [toast])

  const selectSession = useCallback(async (sessionId, { autofocus = false } = {}) => {
    if (openRef.current?.id !== sessionId && !await flushCurrentNoteRef.current()) return
    if (openRef.current?.id !== sessionId) {
      setFileShelfOpen(false)
      setStudyShelfOpen(false)
    }
    setLoadingNote(true)
    setSaveError('')
    setSaveConflict(false)
    try {
      const result = await api(`/api/school/note-sessions/${sessionId}`)
      openRef.current = result
      documentRef.current = result.document
      titleRef.current = result.title || ''
      setOpen(result)
      setNoteDocument(result.document)
      setNoteTitle(result.title || '')
      setFreshSession(autofocus)
    } catch (error) {
      toast(error.message, 'crit')
    } finally {
      setLoadingNote(false)
    }
  }, [toast])

  const openMeeting = useCallback(async (schoolItemId, template = null) => {
    if (!await flushCurrentNoteRef.current()) return
    setFileShelfOpen(false)
    setStudyShelfOpen(false)
    setLoadingNote(true)
    setSaveError('')
    setSaveConflict(false)
    try {
      const result = await api('/api/school/note-sessions/open', 'POST', { school_item_id: schoolItemId })
      const session = result.session
      const nextDocument = result.created && template ? templateDocument(template) : session.document
      setActiveCode(session.course_code)
      openRef.current = session
      documentRef.current = nextDocument
      titleRef.current = session.title || ''
      setOpen(session)
      setNoteDocument(nextDocument)
      setNoteTitle(session.title || '')
      setFreshSession(result.created)
      setSessions((current) => mergeSession(current, session))
      await loadSessions(session.course_code)
    } catch (error) {
      toast(error.message, 'crit')
    } finally {
      setLoadingNote(false)
    }
  }, [loadSessions, toast])

  const openManualSession = useCallback(async (template = null) => {
    if (!activeCourse || !isAsyncCourse(activeCourse)) return
    if (!await flushCurrentNoteRef.current()) return
    setFileShelfOpen(false)
    setStudyShelfOpen(false)
    setLoadingNote(true)
    setSaveError('')
    setSaveConflict(false)
    try {
      const result = await api(
        `/api/school/courses/${encodeURIComponent(activeCourse.code)}/note-sessions`,
        'POST', { session_type: 'async', session_date: schoolWeekStart(school.today) },
      )
      const session = result.session
      const nextDocument = result.created && template ? templateDocument(template) : session.document
      openRef.current = session
      documentRef.current = nextDocument
      titleRef.current = session.title || ''
      setOpen(session)
      setNoteDocument(nextDocument)
      setNoteTitle(session.title || '')
      setFreshSession(result.created)
      setSessions((current) => mergeSession(current, session))
      await loadSessions(activeCourse.code)
    } catch (error) {
      toast(error.message, 'crit')
    } finally {
      setLoadingNote(false)
    }
  }, [activeCourse, loadSessions, school.today, toast])

  useEffect(() => { sessionQueryRef.current = sessionQuery }, [sessionQuery])
  useEffect(() => {
    if (!activeCode) return undefined
    // Typing a word is several keystrokes; only the pause is a search.
    const delay = sessionQuery ? 200 : 0
    const timer = setTimeout(() => { loadSessions(activeCode, sessionQuery) }, delay)
    return () => clearTimeout(timer)
  }, [activeCode, loadSessions, sessionQuery])

  useEffect(() => {
    const intent = intentRef.current
    if (!intent || intentApplied.current || !courses.length) return
    intentApplied.current = true
    if (intent.schoolItemId) openMeeting(intent.schoolItemId)
    else if (intent.sessionId) selectSession(intent.sessionId, { autofocus: false })
  }, [courses.length, openMeeting, selectSession])

  const reloadOpen = useCallback(async () => {
    if (!openRef.current) return
    await selectSession(openRef.current.id, { autofocus: false })
    setSaveError('')
    setSaveConflict(false)
  }, [selectSession])

  const saveDocument = useCallback(() => {
    const current = openRef.current
    const nextDocument = documentRef.current
    if (!current || !nextDocument) return Promise.resolve(true)
    const sentTitle = normalizeSchoolNoteTitle(titleRef.current) || current.title
    const documentChanged = docKey(current.document) !== docKey(nextDocument)
    const titleChanged = sentTitle !== current.title
    if (!documentChanged && !titleChanged) return Promise.resolve(true)
    if (saveInFlight.current) {
      savePending.current = true
      return savePromise.current || Promise.resolve(false)
    }

    saveInFlight.current = true
    setSaving(true)
    const sentDocument = nextDocument
    const request = (async () => {
      let succeeded = false
      try {
        const payload = {
          expected_revision: current.revision,
          ...(documentChanged ? { document: sentDocument } : {}),
          ...(titleChanged ? { title: sentTitle } : {}),
        }
        const saved = await api(`/api/school/note-sessions/${current.id}`, 'PATCH', payload)
        // A late response for a note that was closed or switched away from
        // must not hijack the current editor.
        if (openRef.current?.id !== current.id) return true
        succeeded = true
        setSaveError('')
        setSaveConflict(false)
        openRef.current = saved
        setOpen(saved)
        setSessions((items) => mergeSession(items, saved))
        if (docKey(documentRef.current) === docKey(sentDocument)) setNoteDocument(saved.document)
        if ((normalizeSchoolNoteTitle(titleRef.current) || current.title) === sentTitle) setNoteTitle(saved.title || '')
        return true
      } catch (error) {
        if (/changed elsewhere/i.test(error.message)) {
          setSaveConflict(true)
          setSaveError('This note changed on another device. Reload it before saving again.')
        } else {
          setSaveConflict(false)
          setSaveError(error.message || 'Could not save this note')
        }
        return false
      } finally {
        saveInFlight.current = false
        savePromise.current = null
        setSaving(false)
        const hasNewDocument = openRef.current && (
          docKey(openRef.current.document) !== docKey(documentRef.current)
          || (normalizeSchoolNoteTitle(titleRef.current) || openRef.current.title) !== openRef.current.title
        )
        // An edit that landed while a save was in flight gets one more
        // debounced pass. A failed request waits for an explicit retry or new
        // typing instead of hammering a broken network forever.
        if (succeeded && (savePending.current || hasNewDocument)) setSaveCycle((value) => value + 1)
        savePending.current = false
      }
    })()
    savePromise.current = request
    return request
  }, [])
  const flushCurrentNote = useCallback(async () => {
    clearTimeout(saveTimer.current)
    // A switch/back is a hard boundary: do not merely schedule a follow-up
    // save. Keep flushing until the latest editor ref equals the canonical
    // server document, including keystrokes made during a prior request.
    while (true) {
      const current = openRef.current
      const currentTitle = normalizeSchoolNoteTitle(titleRef.current) || current?.title
      if (!current || !documentRef.current || (
        docKey(current.document) === docKey(documentRef.current)
        && current.title === currentTitle
      )) {
        return true
      }
      if (!await saveDocument()) return false
    }
  }, [saveDocument])
  flushCurrentNoteRef.current = flushCurrentNote

  const saveNow = useCallback(async () => {
    if (!openRef.current) return
    const saved = await flushCurrentNote()
    toast(saved ? 'Class note saved' : 'Could not save this note', saved ? 'good' : 'crit')
  }, [flushCurrentNote, toast])

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && fullScreen && !pulseOpen && !fileShelfOpen && !studyShelfOpen && !sessionsOpen) {
        event.preventDefault()
        setFullScreen(false)
        return
      }
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return
      if (!openRef.current) return
      event.preventDefault()
      void saveNow()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [fileShelfOpen, fullScreen, pulseOpen, saveNow, sessionsOpen, studyShelfOpen])

  useEffect(() => {
    const titleChanged = String(noteTitle || '').trim() && String(noteTitle || '').trim() !== open?.title
    const documentChanged = open && noteDocument && docKey(open.document) !== docKey(noteDocument)
    if (!open || !noteDocument || (!documentChanged && !titleChanged) || saveConflict) return undefined
    clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(saveDocument, AUTOSAVE_MS)
    return () => clearTimeout(saveTimer.current)
  }, [noteDocument, noteTitle, open, saveCycle, saveConflict, saveDocument])

  const wrapClass = useCallback(async () => {
    if (!open) return
    const saved = await flushCurrentNote()
    // “Finished” is a promise that the note is safely there. If the local
    // autosave has a connectivity/conflict problem, leave the session open
    // and surface the recovery path instead of silently closing it first.
    if (!saved) return
    try {
      const current = openRef.current || open
      const result = await api(`/api/school/note-sessions/${current.id}/close`, 'POST')
      setOpen(result)
      openRef.current = result
      documentRef.current = result.document
      titleRef.current = result.title || ''
      setNoteDocument(result.document)
      setNoteTitle(result.title || '')
      setSessions((items) => mergeSession(items, result))
      toast('Session marked finished', 'good')
    } catch (error) {
      toast(error.message, 'crit')
    }
  }, [flushCurrentNote, open, toast])

  const retrySave = useCallback(async () => {
    if (saveConflict) return
    setSaveError('')
    await flushCurrentNote()
  }, [flushCurrentNote, saveConflict])

  const chooseCourse = async (code) => {
    if (code === activeCode) return
    if (!await flushCurrentNote()) return
    setFileShelfOpen(false)
    setStudyShelfOpen(false)
    setPulseOpen(false)
    setSessionQuery('')
    setActiveCode(code)
    openRef.current = null
    documentRef.current = null
    titleRef.current = ''
    setOpen(null)
    setNoteDocument(null)
    setNoteTitle('')
    setSaveError('')
    setSaveConflict(false)
  }

  const leaveNotebook = async () => {
    if (await flushCurrentNote()) onBack()
  }

  const settleTitle = useCallback(() => {
    const fallback = openRef.current?.title || ''
    const normalized = normalizeSchoolNoteTitle(titleRef.current)
    if (!normalized && fallback) {
      titleRef.current = fallback
      setNoteTitle(fallback)
      void flushCurrentNote()
      return
    }
    if (normalized !== titleRef.current) {
      titleRef.current = normalized
      setNoteTitle(normalized)
    }
    void flushCurrentNote()
  }, [flushCurrentNote])

  const openFileShelf = useCallback(() => {
    if (activeCourse?.code) setFileShelfOpen(true)
  }, [activeCourse?.code])

  const openStudyShelf = useCallback(() => {
    if (openRef.current?.id) setStudyShelfOpen(true)
  }, [])

  const nextMeeting = activeCourse?.next_meeting || null
  const visibleSessions = sessions
  const searchSummary = useMemo(() => {
    if (!sessionQuery.trim() || loadingSessions) return ''
    const notes = sessions.length
    const hits = sessions.reduce((total, session) => total + (session.match_count || 0), 0)
    if (!notes) return ''
    const noteWord = notes === 1 ? 'note' : 'notes'
    if (!hits) return `${notes} ${noteWord} matched`
    return `${hits} ${hits === 1 ? 'mention' : 'mentions'} in ${notes} ${noteWord}`
  }, [loadingSessions, sessionQuery, sessions])
  const primaryLabel = isAsyncCourse(activeCourse)
    ? 'Open week'
    : nextMeeting
      ? `${nextMeeting.existing_session_id ? 'Resume' : 'Start'} ${nextMeeting.kind || 'class'} note`
      : null

  if (!coursesAreLoaded) return <NotebookLoading />

  if (!courses.length) {
    return (
      <div className="school-notebook-page page-stack">
        <section className="school-notebook-empty-state panel">
          <div className="panel-body">
            <p className="school-notebook-recovery-label">Class notes</p>
            <h2>No courses loaded</h2>
            <p>Import the School schedule to create class notes.</p>
            <button type="button" className="btn primary" onClick={onBack}>Back to School</button>
          </div>
        </section>
      </div>
    )
  }

  // One navigator, two homes: the rail at normal size, and a sheet in full
  // screen, where the rail is hidden. Built here rather than duplicated so
  // the search field and the timeline can never drift between them.
  const navigator = (
    <>
      <div className="school-notebook-navigator-head">
        <CoursePicker courses={courses} activeCode={activeCourse?.code} onSelect={chooseCourse} />
        <div className="school-notebook-rail-head">
          <h3>{activeCourse?.code} sessions</h3>
          {isAsyncCourse(activeCourse) && <button type="button" className="school-notebook-new" onClick={openManualSession} disabled={loadingNote}>
            This week
          </button>}
        </div>
        <label className="school-session-search">
          <span>Search all notes</span>
          <input
            type="search"
            value={sessionQuery}
            onChange={(event) => setSessionQuery(event.target.value)}
            placeholder={`Find in ${activeCourse?.code || 'this notebook'}`}
          />
        </label>
        {searchSummary && <p className="school-session-search-summary">{searchSummary}</p>}
      </div>
      <div className="school-navigator-sessions">
        {loadingSessions ? <p className="school-notebook-empty">Loading sessions…</p>
          : visibleSessions.length ? <SessionTimeline sessions={visibleSessions} active={open} onOpen={selectSession} today={school.today} query={sessionQuery} />
            : sessionQuery ? <p className="school-notebook-empty">Nothing in {activeCourse?.code || 'this notebook'} mentions “{sessionQuery}”.</p>
              : <p className="school-notebook-empty">No sessions yet.</p>}
      </div>
    </>
  )

  return (
    <div className={`school-notebook-page page-stack${open ? ' has-open-note' : ''}${fullScreen ? ' is-full-screen' : ''}`}>
      <header className="school-notebook-head">
        <div className="school-notebook-identity">
          <div className="school-notebook-breadcrumb" aria-label="Notebook location">
            <button type="button" className="school-notebook-back" onClick={leaveNotebook}>School</button>
            <span aria-hidden="true">/</span>
            <strong>Notes</strong>
          </div>
        </div>
        <div className="school-notebook-head-actions">
          <span className={`school-note-save${saveError ? ' is-error' : ''}`} aria-live="polite">
            {saveError ? 'Needs attention' : saving ? 'Saving…' : open?.closed_at ? 'Finished' : open ? 'Saved' : ''}
          </span>
          <button type="button" className="school-notebook-utility school-pulse-launch" onClick={() => setPulseOpen(true)}>Details</button>
          <button type="button" className="school-notebook-utility school-fullscreen-toggle" onClick={() => setFullScreen((value) => !value)} disabled={!open} aria-pressed={fullScreen}>
            {fullScreen ? 'Exit full screen' : 'Full screen'}
          </button>
          {open && <button type="button" className="btn primary school-wrap-button" onClick={wrapClass} disabled={!!open.closed_at || saving}>{open.closed_at ? 'Finished' : 'Finish session'}</button>}
        </div>
      </header>

      <div className="school-notebook-layout">
        <aside className="school-notebook-rail" aria-label="Notebook sessions">{navigator}</aside>

        <section className="school-note-writing" aria-labelledby="school-note-heading">
          {open ? (
            <>
              <h1 className="sr-only" id="school-note-heading">{noteTitle || `${open.course_code} ${sessionTypeLabel(open)} note`}</h1>
              <div className="school-note-mobile-actions">
                <button type="button" className="school-note-mobile-back" onClick={async () => {
                  if (!await flushCurrentNote()) return
                  setFileShelfOpen(false)
                  setStudyShelfOpen(false)
                  openRef.current = null
                  documentRef.current = null
                  titleRef.current = ''
                  setOpen(null)
                  setNoteDocument(null)
                  setNoteTitle('')
                }}>Notes</button>
                <div className="school-note-context-actions">
                  <button type="button" className="school-notebook-utility school-note-details-button" onClick={() => setPulseOpen(true)}>Details</button>
                  <button type="button" className="school-notebook-utility school-note-fullscreen-button" onClick={() => setFullScreen((value) => !value)} aria-pressed={fullScreen}>
                    {fullScreen ? 'Exit full screen' : 'Full screen'}
                  </button>
                </div>
              </div>
              <div className="school-note-writing-head">
                <div className="school-note-document-heading">
                  <span>{open.course_code} · {sessionTypeLabel(open)}</span>
                  <textarea
                    ref={titleFieldRef}
                    className="school-note-title-input"
                    value={noteTitle}
                    rows={1}
                    wrap="soft"
                    enterKeyHint="done"
                    aria-label="Class note title"
                    aria-describedby="school-note-title-hint"
                    onChange={(event) => changeTitle(event.target.value)}
                    onBlur={settleTitle}
                    onKeyDown={(event) => {
                      if (event.key !== 'Enter') return
                      event.preventDefault()
                      event.currentTarget.blur()
                    }}
                  />
                  <span className="sr-only" id="school-note-title-hint">{SCHOOL_NOTE_TITLE_MAX} character maximum. Press Enter to finish editing.</span>
                  <p>{sessionDate(open.session_date)}{open.meeting?.start_at ? ` · ${clock(open.meeting.start_at)}` : ''}{open.meeting?.location ? ` · ${open.meeting.location}` : ''}</p>
                </div>
              </div>
              {saveError && <div className="school-note-save-error" role="alert"><span>{saveError}</span><button type="button" onClick={saveConflict ? reloadOpen : retrySave}>{saveConflict ? 'Reload note' : 'Retry save'}</button></div>}
              <SchoolNoteEditor
                document={noteDocument}
                onChange={changeDocument}
                autoFocus={freshSession}
              />
            </>
          ) : (
            <section className="school-note-preflight">
              <div className="school-note-preflight-copy">
                <h1>{activeCourse?.code} notes</h1>
                <p>{isAsyncCourse(activeCourse)
                  ? `Week of ${sessionDate(schoolWeekStart(school.today))}`
                  : nextMeeting ? `${nextMeeting.kind || 'Class'} · ${sessionDate(nextMeeting.start_at?.slice(0, 10))} · ${clock(nextMeeting.start_at)}${nextMeeting.location ? ` · ${nextMeeting.location}` : ''}`
                    : 'No upcoming session loaded.'}</p>
                {primaryLabel && <button
                  type="button"
                  className="btn primary school-note-start"
                  disabled={loadingNote}
                  onClick={() => (isAsyncCourse(activeCourse) ? openManualSession() : openMeeting(nextMeeting.school_item_id))}
                >
                  {loadingNote ? 'Opening…' : primaryLabel}
                </button>}
              </div>
              {primaryLabel && <div className="school-note-template-area">
                <h2>Templates</h2>
                <p>Optional</p>
                <div className="school-note-templates">
                  {NOTE_TEMPLATES.map((template) => <button
                    type="button"
                    key={template.id}
                    className="school-note-template"
                    disabled={loadingNote}
                    onClick={() => (isAsyncCourse(activeCourse)
                      ? openManualSession(template)
                      : openMeeting(nextMeeting.school_item_id, template))}
                  >
                    <strong>{template.label}</strong>
                    <span>{template.note}</span>
                  </button>)}
                </div>
              </div>}
            </section>
          )}
        </section>

        <aside className="school-note-context-rail">
          <ClassPulse session={open} course={activeCourse} onOpenFiles={openFileShelf} onOpenStudy={openStudyShelf} />
        </aside>
      </div>

      {fullScreen && (
        <div className="school-fs-bar" role="toolbar" aria-label="Full screen controls">
          <button type="button" className="school-fs-btn" onClick={() => setSessionsOpen(true)}>Notes</button>
          <button type="button" className="school-fs-btn" onClick={() => setPulseOpen(true)}>Details</button>
          <button type="button" className="school-fs-btn" onClick={openFileShelf} disabled={!activeCourse}>Files</button>
          <span className={`school-fs-save${saveError ? ' is-error' : ''}`} aria-live="polite">
            {saveError ? 'Needs attention' : saving ? 'Saving…' : open?.closed_at ? 'Finished' : open ? 'Saved' : ''}
          </span>
          {open && !open.closed_at && (
            <button type="button" className="school-fs-btn" onClick={wrapClass} disabled={saving}>Finish</button>
          )}
          <button type="button" className="school-fs-btn school-fs-exit" onClick={() => setFullScreen(false)}>
            Exit <kbd>esc</kbd>
          </button>
        </div>
      )}

      <Sheet
        open={sessionsOpen}
        onClose={() => setSessionsOpen(false)}
        title={`${activeCourse?.code || 'Course'} notes`}
        variant="dialog"
        className="school-sessions-sheet"
      >
        <div className="school-sessions-sheet-body">{navigator}</div>
      </Sheet>

      <Sheet
        open={pulseOpen}
        onClose={() => setPulseOpen(false)}
        title={`${activeCourse?.code || 'Course'} details`}
        variant="dialog"
        className="school-pulse-sheet"
      >
        <ClassPulse session={open} course={activeCourse} onOpenFiles={() => { setPulseOpen(false); openFileShelf() }} onOpenStudy={() => { setPulseOpen(false); openStudyShelf() }} />
      </Sheet>

      <Sheet
        open={fileShelfOpen}
        onClose={() => setFileShelfOpen(false)}
        title={`${activeCourse?.code || 'Course'} files`}
        variant="dialog"
        className="school-files-sheet"
      >
        <SchoolFilesPanel courseCode={activeCourse?.code} sessionId={open?.id} toast={toast} />
      </Sheet>
      <Sheet
        open={studyShelfOpen}
        onClose={() => setStudyShelfOpen(false)}
        title={`${open?.course_code || 'Class'} study`}
        variant="dialog"
        className="school-study-sheet"
      >
        <SchoolStudyPanel course={activeCourse} session={open} toast={toast} />
      </Sheet>
    </div>
  )
}
