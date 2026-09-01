import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/api.js'

const STUDY_ACTIONS = [
  { kind: 'summary', label: 'Summary', note: 'Key ideas and review prompts' },
  { kind: 'flashcards', label: 'Flashcards', note: 'Recall practice from this note' },
  { kind: 'practice', label: 'Practice', note: 'Concept checks, not answers' },
  { kind: 'study_plan', label: 'Study plan', note: 'Suggested next steps' },
]

function policyState(course) {
  const policy = course?.policies?.ai_policy || {}
  if (policy.status === 'permitted_with_conditions') {
    return { known: true, label: 'Course policy: conditions apply', tone: 'good' }
  }
  if (policy.status === 'prohibited') return { known: true, label: 'Course policy: AI not permitted', tone: 'crit' }
  return { known: false, label: 'Course policy needs confirmation', tone: 'warn' }
}

function studyStatus(artifact) {
  const status = String(artifact?.status || '').toUpperCase()
  if (status === 'ACCEPTED') return 'Saved study aid'
  if (status === 'STALE') return 'Your note changed, regenerate this aid.'
  if (status === 'FAILED') return 'Study tool could not finish.'
  if (status === 'DISCARDED') return 'Discarded'
  if (status === 'RUNNING') return 'Making study aid…'
  if (status === 'QUEUED') return 'Study aid queued…'
  return 'Ready to review'
}

function stringList(value) {
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

function ArtifactOutput({ artifact }) {
  const output = artifact?.output || artifact?.output_json || {}
  if (!output || typeof output !== 'object') return null
  if (artifact.kind === 'summary') {
    const keyPoints = stringList(output.key_points)
    const reviewQuestions = stringList(output.review_questions)
    return (
      <div className="school-study-output">
        {output.title && <h4>{output.title}</h4>}
        {output.summary && <p>{output.summary}</p>}
        {keyPoints.length > 0 && <ul>{keyPoints.map((point, index) => <li key={`${index}-${point}`}>{point}</li>)}</ul>}
        {reviewQuestions.length > 0 && <div className="school-study-review"><strong>Review yourself:</strong><ul>{reviewQuestions.map((question, index) => <li key={`${index}-${question}`}>{question}</li>)}</ul></div>}
      </div>
    )
  }
  if (artifact.kind === 'flashcards') {
    const cards = Array.isArray(output.cards) ? output.cards : []
    return <div className="school-study-output school-study-cards">
      {cards.map((card, index) => card?.front && card?.back && <details key={`${index}-${card.front}`}>
        <summary>{card.front}</summary>
        <p>{card.back}</p>
      </details>)}
    </div>
  }
  if (artifact.kind === 'practice') {
    const questions = Array.isArray(output.questions) ? output.questions : []
    return <ol className="school-study-output school-study-questions">
      {questions.map((question, index) => question?.question && <li key={`${index}-${question.question}`}>
        <strong>{question.question}</strong>
        {question.hint && <span>Hint: {question.hint}</span>}
        {question.skill && <span>Skill: {question.skill}</span>}
      </li>)}
    </ol>
  }
  if (artifact.kind === 'study_plan') {
    const steps = Array.isArray(output.steps) ? output.steps : []
    return <div className="school-study-output">
      {output.goal && <p className="school-study-plan-goal">{output.goal}</p>}
      <ol className="school-study-plan">{steps.map((step, index) => step?.title && <li key={`${index}-${step.title}`}>
        <span><strong>{step.title}</strong>{step.instruction && <em>{step.instruction}</em>}</span>{Number.isFinite(step.minutes) && <small>{step.minutes} min</small>}
      </li>)}</ol>
    </div>
  }
  return null
}

function ArtifactCard({ artifact, onAccept, onDiscard, busy }) {
  const status = String(artifact.status || '').toUpperCase()
  const isDraft = status === 'DRAFT'
  const isReady = isDraft || status === 'ACCEPTED'
  const action = STUDY_ACTIONS.find((item) => item.kind === artifact.kind)
  return (
    <article className={`school-study-artifact is-${status.toLowerCase()}`}>
      <header>
        <div>
          <span>{action?.label || 'Study aid'}</span>
          <p>{studyStatus(artifact)}</p>
        </div>
        {artifact.source_note_revision && <small>Note v{artifact.source_note_revision}</small>}
      </header>
      {isReady && <ArtifactOutput artifact={artifact} />}
      {isDraft && <footer>
        <button type="button" className="school-study-accept" onClick={() => onAccept(artifact.id)} disabled={busy}>Keep aid</button>
        <button type="button" className="school-study-discard" onClick={() => onDiscard(artifact.id)} disabled={busy}>Discard</button>
      </footer>}
    </article>
  )
}

/**
 * Explicitly requested, revision-bound study aids. This component never
 * creates an aid on autosave, close, schedule entry, or file upload. Files
 * stay out of the request entirely; only the currently selected note may be
 * sent after consent.
 */
export default function SchoolStudyPanel({ course, session, toast }) {
  const [settings, setSettings] = useState(null)
  const [artifacts, setArtifacts] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const policy = policyState(course)
  const sessionId = session?.id
  const hasNoteText = Boolean(session?.plain_text?.trim())

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!sessionId) return
    if (!quiet) setLoading(true)
    setError('')
    try {
      const [prefs, listed] = await Promise.all([
        api('/api/school/ai/settings', 'GET', undefined, { cache: 'no-store' }),
        api(`/api/school/note-sessions/${sessionId}/study-artifacts`, 'GET', undefined, { cache: 'no-store' }),
      ])
      setSettings(prefs)
      setArtifacts(Array.isArray(listed.artifacts) ? listed.artifacts : [])
    } catch (loadError) {
      setError(loadError.message || 'Study tools could not load')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [sessionId])

  useEffect(() => { load() }, [load])

  const running = useMemo(
    () => artifacts.some((artifact) => ['QUEUED', 'RUNNING'].includes(String(artifact.status || '').toUpperCase())),
    [artifacts],
  )

  useEffect(() => {
    if (!running) return undefined
    const timer = window.setInterval(() => { load({ quiet: true }) }, 1500)
    return () => window.clearInterval(timer)
  }, [load, running])

  const setStudyEnabled = useCallback(async (enabled) => {
    setBusy(true)
    setError('')
    try {
      const result = await api('/api/school/ai/settings', 'PATCH', { enabled })
      setSettings(result)
      if (!enabled) await load({ quiet: true })
      toast?.(enabled ? 'Study mode enabled for requested aids' : 'Study mode turned off', 'good')
    } catch (enableError) {
      setError(enableError.message || 'Study mode setting could not update')
    } finally {
      setBusy(false)
    }
  }, [load, toast])

  const createArtifact = useCallback(async (kind) => {
    if (!sessionId || busy || !settings?.enabled || !hasNoteText) return
    setBusy(true)
    setError('')
    try {
      const result = await api(`/api/school/note-sessions/${sessionId}/study-artifacts`, 'POST', { kind })
      const artifact = result.artifact || result
      if (artifact?.id) setArtifacts((current) => [artifact, ...current.filter((item) => item.id !== artifact.id)])
      toast?.(result.created === false ? 'This study aid is already available' : 'Study aid requested', 'good')
    } catch (createError) {
      setError(createError.message || 'Study aid could not start')
    } finally {
      setBusy(false)
    }
  }, [busy, hasNoteText, sessionId, settings?.enabled, toast])

  const transition = useCallback(async (artifactId, action) => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api(`/api/school/study-artifacts/${artifactId}/${action}`, 'POST')
      const artifact = result.artifact || result
      if (artifact?.id) setArtifacts((current) => current.map((item) => item.id === artifact.id ? artifact : item))
      toast?.(action === 'accept'
        ? artifact?.status === 'ACCEPTED' ? 'Study aid saved' : 'This aid is stale; regenerate it from the saved note'
        : 'Study aid discarded', 'good')
    } catch (transitionError) {
      setError(transitionError.message || 'Study aid could not update')
    } finally {
      setBusy(false)
    }
  }, [busy, toast])

  if (!session) return null

  return (
    <section className="school-study" aria-label="Study tools">
      <header className="school-study-head">
        <div>
          <h3>Study tools</h3>
          <p>Requested aids from this note only. Course files are not included.</p>
        </div>
        <span className={`school-study-policy ${policy.tone}`}>{policy.label}</span>
      </header>

      {!settings?.enabled && !loading && <div className="school-study-consent">
        <p>Study mode sends this selected note to your configured Claude service to make a study aid. It never sends anything to Canvas or ianOS agents.</p>
        <button type="button" className="school-study-enable" onClick={() => setStudyEnabled(true)} disabled={busy}>Enable study mode</button>
      </div>}

      {settings?.enabled && <>
        <button type="button" className="school-study-disable" onClick={() => setStudyEnabled(false)} disabled={busy}>Turn off study mode</button>
        {!hasNoteText && <p className="school-study-empty">Add a few class notes first. Study tools only use the saved note text.</p>}
        {policy.tone === 'crit' && <p className="school-study-warning">This course says AI is not permitted. Study tools are blocked.</p>}
        {policy.tone === 'warn' && <p className="school-study-warning">Confirm this course’s AI policy before using a study aid.</p>}
        <div className="school-study-actions">
          {STUDY_ACTIONS.map((action) => <button
            key={action.kind}
            type="button"
            className="school-study-action"
            onClick={() => createArtifact(action.kind)}
            disabled={busy || running || !hasNoteText || policy.tone === 'crit'}
          >
            <strong>{action.label}</strong><span>{action.note}</span>
          </button>)}
        </div>
      </>}

      {error && <div className="school-study-error" role="alert"><span>{error}</span><button type="button" onClick={() => load()}>Retry</button></div>}
      {loading ? <p className="school-study-empty">Loading study tools…</p>
        : artifacts.length > 0 && <div className="school-study-artifacts">
          {artifacts.filter((artifact) => String(artifact.status || '').toUpperCase() !== 'DISCARDED').map((artifact) => (
            <ArtifactCard
              key={artifact.id}
              artifact={artifact}
              busy={busy}
              onAccept={(id) => transition(id, 'accept')}
              onDiscard={(id) => transition(id, 'discard')}
            />
          ))}
        </div>}
    </section>
  )
}
