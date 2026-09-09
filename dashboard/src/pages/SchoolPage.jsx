import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { goalsForPillar } from '../lib/pillars.js'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'
import { api } from '../lib/api.js'
import { courseTone } from '../lib/courseColors.js'

const DAY_NAMES = { MO: 'Mon', TU: 'Tue', WE: 'Wed', TH: 'Thu', FR: 'Fri', SA: 'Sat', SU: 'Sun' }

function useMediaQuery(query) {
  const getMatches = () => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return Boolean(window.matchMedia(query)?.matches)
  }
  const [matches, setMatches] = useState(getMatches)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia(query)
    if (!media) return undefined
    const update = () => setMatches(media.matches)
    update()
    if (media.addEventListener) {
      media.addEventListener('change', update)
      return () => media.removeEventListener('change', update)
    }
    media.addListener?.(update)
    return () => media.removeListener?.(update)
  }, [query])

  return matches
}

function localDate(value) {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function shortDate(value) {
  const d = localDate(value)
  if (!d) return 'TBD'
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(d)
}

function time(value) {
  const d = localDate(value)
  if (!d || !String(value).includes('T')) return ''
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(d)
}

function dueLabel(value, today) {
  const d = localDate(value)
  if (!d) return 'TBD'
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const base = new Date(`${today || target.toISOString().slice(0, 10)}T00:00:00`)
  const days = Math.round((target - base) / 86400000)
  const day = days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : shortDate(value)
  const at = time(value)
  return at ? `${day} · ${at}` : day
}

function meetingLabel(meeting) {
  const days = (meeting?.days || []).map((day) => DAY_NAMES[day] || day).join('/')
  const start = meeting?.start_local ? time(`2026-01-01T${meeting.start_local}`) : ''
  const end = meeting?.end_local ? time(`2026-01-01T${meeting.end_local}`) : ''
  const schedule = [days, start && end ? `${start} - ${end}` : start].filter(Boolean).join(' ')
  return [schedule, meeting?.location].filter(Boolean).join(' · ') || 'Asynchronous'
}

function aiState(course) {
  const policy = course?.policies?.ai_policy || {}
  if (policy.status === 'permitted_with_conditions') return { label: 'AI permitted with conditions', tone: 'good' }
  return { label: 'AI rules need confirmation', tone: 'warn' }
}

function isAsyncCourse(course) {
  return !(course?.meetings || []).some((meeting) => (meeting.days || []).length > 0)
}

function statusFor(item, today) {
  const d = localDate(item?.due_at)
  if (!d) return 'idle'
  const base = new Date(`${today}T00:00:00`)
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - base) / 86400000)
  return days <= 1 ? 'crit' : days <= 4 ? 'warn' : 'good'
}

function CourseRail({ courses, activeCode, onSelect, today }) {
  return (
    <nav className="school-course-rail" aria-label="Courses">
      {courses.map((course) => {
        const active = activeCode === course.code
        const tone = courseTone(course.code, courses)
        return (
          <button
            key={course.code}
            type="button"
            className={`school-course-tab ${active ? 'active' : ''}`}
            aria-pressed={active}
            onClick={() => onSelect(course.code)}
            style={{ '--course-tone': tone }}
          >
            <span className="school-course-code">{course.code}</span>
            <span className="school-course-name">{course.name}</span>
            <span className="school-course-next">
              {course.next_due_at ? dueLabel(course.next_due_at, today) : 'No dated work'}
              {course.upcoming_count ? ` · ${course.upcoming_count}` : ''}
            </span>
          </button>
        )
      })}
    </nav>
  )
}

function DeadlineLine({ item, today, dense = false, onToggleDone }) {
  const done = !!item.done
  // The urgency dot doubles as the checkbox rather than sitting beside one.
  // It already occupies the row's leading column and already carries the
  // status colour, so crossing work off happens exactly where the eye lands,
  // in one tap, with no dialog (the repo's law for reversible actions).
  return (
    <div className={`school-deadline ${dense ? 'dense' : ''}${done ? ' is-done' : ''}`}>
      <button
        type="button"
        className={`school-deadline-check ${statusFor(item, today)}`}
        role="checkbox"
        aria-checked={done}
        aria-label={done ? `Mark "${item.title}" as not done` : `Mark "${item.title}" done`}
        onClick={() => onToggleDone?.(item, !done)}
      >
        <span aria-hidden="true">{done ? '✓' : ''}</span>
      </button>
      <div className="school-deadline-copy">
        <span className="school-deadline-title">{item.title}</span>
        <span className="school-deadline-meta">{item.course_code} · {item.kind}</span>
      </div>
      <time className="school-deadline-when" dateTime={item.due_at || undefined}>
        {done ? 'done' : dueLabel(item.due_at, today)}
      </time>
    </div>
  )
}

export default function SchoolPage({ state, refresh, toast, onOpenSchoolNote }) {
  const school = state.school || {}
  const courses = school.courses || []
  const upcoming = school.upcoming || []
  const goals = goalsForPillar(state.goals || [], 'school')
  const [activeCode, setActiveCode] = useState(courses[0]?.code || '')
  const [nextMovesExpanded, setNextMovesExpanded] = useState(false)
  const hasRoomForSixMoves = useMediaQuery('(min-width: 901px) and (min-height: 850px)')
  const hasRoomForThreeMoves = useMediaQuery('(min-width: 341px)')

  useEffect(() => {
    if (!courses.some((course) => course.code === activeCode)) setActiveCode(courses[0]?.code || '')
  }, [courses, activeCode])

  const activeCourse = useMemo(
    () => courses.find((course) => course.code === activeCode) || courses[0] || null,
    [courses, activeCode],
  )
  const justDone = school.just_done || []
  const courseUpcoming = useMemo(
    () => upcoming.filter((item) => item.course_code === activeCourse?.code),
    [upcoming, activeCourse],
  )
  const courseJustDone = useMemo(
    () => justDone.filter((item) => item.course_code === activeCourse?.code),
    [justDone, activeCourse],
  )
  // 320px is a real minimum, not a shrunken 375px: three long titles can push
  // the course rail under the fixed tab bar. Preserve the two urgent moves,
  // keep the rail fully reachable, and disclose the rest. Larger phones and
  // shorter desktops get three; a roomy desktop gets six.
  const initialMoveCount = hasRoomForSixMoves ? 6 : hasRoomForThreeMoves ? 3 : 2
  const priorityMoves = upcoming.slice(0, initialMoveCount)
  const remainingMoves = upcoming.slice(initialMoveCount)
  const sync = school.sync || {}
  const ai = aiState(activeCourse)

  // Crossing homework off is a reversible, one-tap action, so it follows the
  // repo's soft-delete idiom: no confirm dialog, an Undo that calls the exact
  // inverse, and a refresh so every count on the page settles from the server
  // rather than from optimistic local arithmetic.
  const toggleDone = useCallback(async (item, done) => {
    try {
      await api(`/api/school/items/${item.id}/done`, 'POST', { done })
      refresh()
      toast(
        done ? `crossed off "${item.title}"` : `back on the list: "${item.title}"`,
        'good',
        async () => {
          await api(`/api/school/items/${item.id}/done`, 'POST', { done: !done })
          refresh()
        },
      )
    } catch (error) {
      toast(error.message, 'crit')
    }
  }, [refresh, toast])

  if (!courses.length) {
    return (
      <div className="school-page page-layout page-layout--workspace school-page--empty">
        <section className="panel school-empty">
          <div className="panel-body">
            <h2>School is waiting on a local import.</h2>
            <p className="dim">Import a Canvas .ics to see deadlines here</p>
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="school-page page-layout page-layout--workspace">
      <section className="school-command" aria-label="School command center">
        <header className="school-command-head school-command-utility" aria-label="School tools">
          <div className="school-command-actions">
            <button
              type="button"
              className="btn primary school-notebook-entry"
              onClick={() => onOpenSchoolNote?.({ courseCode: activeCourse?.code })}
            >
              Class notes
            </button>
            <div className={`school-sync ${sync.connected ? 'ready' : ''}`} title={sync.last_success || 'Not imported'}>
              <span aria-hidden="true" />
              {sync.connected ? `Canvas snapshot · ${sync.item_count || 0} items` : 'Canvas snapshot needed'}
            </div>
          </div>
        </header>

        <div className="school-command-body">
          <section className="school-next" aria-labelledby="school-next-heading">
            <div className="school-section-heading">
              <h2 id="school-next-heading">Next moves</h2>
              <span>
                {school.summary?.upcoming_count || 0} in 14 days
                {/* Finished work is stated as a plain count, never a streak or
                    a percentage: it can only ever go up, so it cannot break
                    and cannot be used to keep score against him. */}
                {school.summary?.done_count ? ` · ${school.summary.done_count} done` : ''}
              </span>
            </div>
            {priorityMoves.length ? (
              <div className="school-next-list">
                {priorityMoves.map((item) => (
                  <DeadlineLine key={item.id} item={item} today={school.today} onToggleDone={toggleDone} />
                ))}
              </div>
            ) : upcoming.length === 0 && justDone.length ? (
              <p className="school-quiet">Everything in the next 14 days is crossed off.</p>
            ) : <p className="school-quiet">No dated work is loaded yet.</p>}
            {remainingMoves.length > 0 && (
              <div className="school-next-disclosure">
                <button
                  type="button"
                  className="school-next-toggle"
                  aria-expanded={nextMovesExpanded}
                  aria-controls="school-next-remaining"
                  onClick={() => setNextMovesExpanded((expanded) => !expanded)}
                >
                  {nextMovesExpanded ? 'Show fewer' : `Show ${remainingMoves.length} more`}
                </button>
                <div id="school-next-remaining" className="school-next-list school-next-remaining">
                  {nextMovesExpanded && remainingMoves.map((item) => (
                    <DeadlineLine key={item.id} item={item} today={school.today} onToggleDone={toggleDone} />
                  ))}
                </div>
              </div>
            )}
            {justDone.length > 0 && (
              <details className="school-done-reveal">
                <summary>{justDone.length} crossed off</summary>
                <div className="school-next-list">
                  {justDone.map((item) => (
                    <DeadlineLine key={item.id} item={item} today={school.today} onToggleDone={toggleDone} />
                  ))}
                </div>
              </details>
            )}
          </section>

          <CourseRail courses={courses} activeCode={activeCourse?.code} onSelect={setActiveCode} today={school.today} />

          {activeCourse && (
            <section className="school-workbench">
              <p className="sr-only" role="status" aria-atomic="true">
                Showing {activeCourse.code} {activeCourse.name}
              </p>
              <div className="school-workbench-head">
                <div>
                  <span className="school-course-code workbench-code">{activeCourse.code}</span>
                  <h2>{activeCourse.name}</h2>
                  <p>{activeCourse.instructor || 'Instructor pending'} · {activeCourse.credits || '-'} credits · {activeCourse.section || 'section pending'}</p>
                </div>
                <div className="school-workbench-actions">
                  <span className={`chip chip-${ai.tone}`}>{ai.label}</span>
                  <button
                    type="button"
                    className="school-notebook-link"
                    onClick={() => onOpenSchoolNote?.({ courseCode: activeCourse.code })}
                  >
                    All sessions
                  </button>
                  <button
                    type="button"
                    className="btn primary school-start-note"
                    onClick={() => onOpenSchoolNote?.({
                      courseCode: activeCourse.code,
                      schoolItemId: activeCourse.next_meeting?.school_item_id,
                    })}
                  >
                    {activeCourse.next_meeting?.existing_session_id ? 'Resume next note'
                      : activeCourse.next_meeting ? `Start ${activeCourse.next_meeting.kind} note`
                        : isAsyncCourse(activeCourse) ? 'Open week'
                          : 'View notebook'}
                  </button>
                </div>
              </div>

              <div className="school-detail-grid">
                <section className="school-detail-section">
                  <h3>Rhythm</h3>
                  <div className="school-meetings">
                    {(activeCourse.meetings || []).map((meeting, index) => (
                      <div key={`${meeting.kind}-${index}`} className="school-meeting">
                        <span>{meeting.kind || 'Course'}</span>
                        <strong>{meetingLabel(meeting)}</strong>
                      </div>
                    ))}
                  </div>
                </section>

                <section className="school-detail-section school-grade-section">
                  <h3>Grade map</h3>
                  {(activeCourse.grade_categories || []).length ? (
                    <div className="school-grade-list">
                      {activeCourse.grade_categories.map((category) => (
                        <div key={category.name} className="school-grade-row">
                          <span>{category.name}</span>
                          <strong>{category.weight_percent != null ? `${category.weight_percent}%` : category.points ? `${category.points} pts` : '-'}</strong>
                        </div>
                      ))}
                    </div>
                  ) : <p className="school-quiet">Grade categories have not been entered.</p>}
                </section>
              </div>

              <section className="school-detail-section school-course-work">
                <div className="school-section-heading">
                  <h3>Course queue</h3>
                  <span>
                    {courseUpcoming.length} loaded
                    {courseJustDone.length ? ` · ${courseJustDone.length} done` : ''}
                  </span>
                </div>
                {courseUpcoming.length ? (
                  <div className="school-course-queue">
                    {courseUpcoming.slice(0, 10).map((item) => (
                      <DeadlineLine key={item.id} item={item} today={school.today} dense onToggleDone={toggleDone} />
                    ))}
                  </div>
                ) : courseJustDone.length ? (
                  <p className="school-quiet">This course is clear for the current window.</p>
                ) : <p className="school-quiet">Nothing dated in the current window.</p>}
                {courseJustDone.length > 0 && (
                  <details className="school-done-reveal">
                    <summary>{courseJustDone.length} crossed off</summary>
                    <div className="school-course-queue">
                      {courseJustDone.map((item) => (
                        <DeadlineLine key={item.id} item={item} today={school.today} dense onToggleDone={toggleDone} />
                      ))}
                    </div>
                  </details>
                )}
              </section>

              <details className="school-policy">
                <summary>Course policies and AI boundary</summary>
                <div>
                  {Object.entries(activeCourse.policies || {}).map(([key, value]) => {
                    if (key === 'target_cutoffs' || key === 'total_points' || typeof value === 'object') return null
                    return <p key={key}><strong>{key.replace(/_/g, ' ')}:</strong> {value}</p>
                  })}
                  {activeCourse.policies?.ai_policy?.requirements && (
                    <p><strong>AI requirements:</strong> {activeCourse.policies.ai_policy.requirements.join(' · ')}</p>
                  )}
                </div>
              </details>
            </section>
          )}
        </div>
      </section>
      {goals.length > 0 && <PillarGoalPanel pillar="school" title="School goals" goals={goals} refresh={refresh} toast={toast} doneStates={new Set((state.meta?.done_states || []).map((s) => s.toLowerCase()))} />}
    </div>
  )
}
