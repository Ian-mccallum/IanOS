import React, { useCallback, useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import { goalsForPillar } from '../lib/pillars.js'
import { gymConfirmState } from '../lib/gym.js'
import {
  formatHealthDuration,
  healthActivityCopy,
  healthDisplayModel,
  healthHistory,
  healthNextAction,
  healthStatusCopy,
  sleepArcPath,
} from './bodyHealth.js'
import PillarGoalPanel from '../components/goals/PillarGoalPanel.jsx'
import Garden from '../components/Garden.jsx'
import PoopLog from '../components/PoopLog.jsx'
import Sheet from '../components/Sheet.jsx'

const DELIGHT = ['Let\'s go.', 'Another one.', 'Building the streak.', 'You showed up.']
const TRACK_DAYS_OPTIONS = [5, 7]
const REST_DAYS_MIN = 0
const REST_DAYS_MAX = 6

// SPEC-v37 §8.6 point 1: health_ai_prefs has been empty since Aug 26, which
// means physician and coach have run every night without anyone actually
// being asked. `consented_at` only ever means "opted in" (db.set_health_ai_
// sharing clears it back to NULL on a decline), so a plain "Not now" would
// leave the card popping back on every visit; this local flag is the only
// record that the ask itself already happened. Version string is a durable
// marker of which copy Ian agreed to, not a feature flag.
const HEALTH_CONSENT_VERSION = 'v1'
const HEALTH_CONSENT_SEEN_KEY = 'ianos:health-ai-consent-seen'

function healthDayLabel(value) {
  if (typeof value !== 'string' || !value) return '-'
  const parsed = new Date(`${value}T12:00:00`)
  if (Number.isNaN(parsed.getTime())) return value.slice(-2)
  return new Intl.DateTimeFormat(undefined, { weekday: 'narrow' }).format(parsed)
}

function healthStateLabel(state) {
  const labels = {
    fresh: 'Current',
    partial: 'Today so far',
    late: 'Needs capture',
    needs_review: 'Needs review',
    awaiting_first_snapshot: 'Waiting',
    not_configured: 'Setup',
    app_cache_only: 'Cached',
    queued_manual: 'Saved on phone',
    legacy: 'Manual',
  }
  return labels[state] || 'Health'
}

function HealthSleepArc({ model, reduced }) {
  const arc = sleepArcPath(model.sleepStart, model.sleepEnd)
  const windowLabel = arc ? 'Sleep window' : 'Sleep timing appears with your first timed snapshot'

  return (
    <div className="health-sleep-arc" aria-label={windowLabel}>
      <svg viewBox="0 0 240 124" aria-hidden="true" focusable="false">
        <path className="health-arc-track" d="M 24 102 A 96 96 0 0 1 216 102" />
        {arc && (
          <motion.path
            key={`${model.sleepStart}-${model.sleepEnd}`}
            className="health-arc-value"
            d={arc}
            initial={reduced ? false : { pathLength: 0, opacity: 0.45 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: reduced ? 0 : 0.45, ease: [0.22, 1, 0.36, 1] }}
          />
        )}
      </svg>
      <span className="health-arc-caption">{arc ? 'sleep window' : 'timing pending'}</span>
    </div>
  )
}

function HealthMicroRail({ history }) {
  const days = history.slice(-7)
  if (!days.length) {
    return <p className="health-rail-empty">Your sleep rhythm appears here after the first snapshot.</p>
  }
  return (
    <div className="health-rail-wrap">
      <p className="health-rail-title">Last 7 nights</p>
      <ol className="health-rail" aria-label="Sleep over the last 7 nights">
        {days.map((entry, index) => {
          const hasSleep = entry.sleepHours !== null && entry.sleepHours !== undefined
          const level = hasSleep ? Math.max(12, Math.min(100, (Number(entry.sleepHours) / 10) * 100)) : 8
          const label = hasSleep
            ? `${entry.day || 'Day'}: ${formatHealthDuration(entry.sleepHours)} sleep`
            : `${entry.day || 'Day'}: no sleep snapshot`
          return (
            <li key={`${entry.day || 'day'}-${index}`} className={hasSleep ? 'health-rail-day' : 'health-rail-day is-empty'}>
              <span className="health-rail-bar" style={{ '--health-rail-level': `${level}%` }} aria-label={label}>
                <span />
              </span>
              <span aria-hidden="true">{healthDayLabel(entry.day)}</span>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function EnergyCheckIn({ onChoose, busy }) {
  return (
    <div className="health-energy-checkin">
      <span>Energy today</span>
      <div className="health-energy-options" role="radiogroup" aria-label="Energy today: 1 is low and 5 is high">
        {[1, 2, 3, 4, 5].map((value) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked="false"
            disabled={busy}
            aria-label={`Log energy ${value} of 5, ${value === 1 ? 'low' : value === 5 ? 'high' : 'medium'}`}
            onClick={() => onChoose(value)}
          >
            {value}
          </button>
        ))}
      </div>
    </div>
  )
}

function HealthSignalSkeleton() {
  return (
    <section className="health-signal health-signal--loading" aria-busy="true" aria-label="Loading health signal">
      <span className="health-skeleton health-skeleton--source" />
      <div className="health-signal-main">
        <div className="health-signal-sleep">
          <span className="health-skeleton health-skeleton--label" />
          <span className="health-skeleton health-skeleton--metric" />
          <span className="health-skeleton health-skeleton--detail" />
        </div>
        <span className="health-skeleton health-skeleton--arc" />
      </div>
      <span className="health-skeleton health-skeleton--rail" />
    </section>
  )
}

function HealthSignalPanel({ model, history, gymConfirmed, reduced, onAction, onEnergy, energyBusy }) {
  const action = healthNextAction(model, gymConfirmed)
  const sleepValue = model.sleepHours === null ? 'No sleep yet' : formatHealthDuration(model.sleepHours)
  const sleepDetail = model.sleepAverage !== null
    ? `${formatHealthDuration(model.sleepAverage)} average across ${model.sleepCoverage || 'recent'} nights`
    : 'A calm view of your sleep, activity, and recovery rhythm.'
  const activity = healthActivityCopy(model)

  return (
    <section className={`health-signal health-signal--${model.state}`} aria-labelledby="health-signal-title">
      <div className="health-signal-head">
        <span className="health-source-beacon">
          <span className="health-source-dot" aria-hidden="true" />
          {model.source}
        </span>
        <span className="health-state-label">{healthStateLabel(model.state)}</span>
      </div>

      <div className="health-signal-main">
        <div className="health-signal-sleep">
          <h2 id="health-signal-title">Sleep</h2>
          <p className={model.sleepHours === null ? 'health-sleep-value is-empty' : 'health-sleep-value'}>{sleepValue}</p>
          <p className="health-sleep-detail">{sleepDetail}</p>
        </div>
        <HealthSleepArc model={model} reduced={reduced} />
      </div>

      <HealthMicroRail history={history} />
      <p className="health-capture-copy">{healthStatusCopy(model)}</p>
      {activity && <p className="health-activity-copy">{activity}</p>}

      {action.kind === 'energy' ? (
        <EnergyCheckIn onChoose={onEnergy} busy={energyBusy} />
      ) : (
        <button type="button" className="health-signal-action" onClick={() => onAction(action)}>
          {action.label}
        </button>
      )}
    </section>
  )
}

function SetupValue({ label, value, secret = false, onCopy }) {
  if (!value) return null
  const display = secret && value.length > 14
    ? `${value.slice(0, 7)}••••${value.slice(-5)}`
    : value
  return (
    <div className="health-setup-value">
      <span>{label}</span>
      <code>{display}</code>
      <button type="button" onClick={() => onCopy(value, label)}>Copy</button>
    </div>
  )
}

function HealthLensSheet({
  open, onClose, model, history, setupConfig, setupLoading, setupError, onCopySetupValue,
  healthAiConsent, consentSaving, onToggleHealthAiConsent,
}) {
  const setup = model.state === 'not_configured' || model.state === 'awaiting_first_snapshot'
  const testEndpoint = setupConfig && typeof window !== 'undefined'
    ? `${window.location.origin}${setupConfig.test_path}`
    : ''
  const progressEndpoint = setupConfig?.progress_path && typeof window !== 'undefined'
    ? `${window.location.origin}${setupConfig.progress_path}`
    : ''
  return (
    <Sheet open={open} onClose={onClose} title={setup ? 'Apple Watch capture' : 'Health details'} variant="drawer">
      <div className="health-lens-sheet">
        <p className="health-lens-source"><span aria-hidden="true" />{model.source}</p>
        {setup ? (
          <>
            <h3>Ready when your iPhone is.</h3>
            <p>
              ianOS will ask for one small daily snapshot: sleep, steps, workout count, and workout minutes.
              It will not pull a raw HealthKit export.
            </p>
            <ol className="health-lens-steps">
              <li>Confirm Apple Health is recording sleep and activity from your Apple Watch.</li>
              <li>Open this Sheet from the installed ianOS app on your iPhone, then create the connection test below.</li>
              <li>After the connection test says ready, add the Health-summary actions to the same Shortcut.</li>
            </ol>
            <section className="health-shortcut-pairing" aria-labelledby="health-shortcut-pairing-title">
              <h4 id="health-shortcut-pairing-title">Shortcut connection test</h4>
              <p>This verifies the private route only. It does not save health data.</p>
              {setupLoading ? (
                <p className="dim">Preparing your paired Shortcut…</p>
              ) : setupError ? (
                <p className="dim">{setupError}</p>
              ) : setupConfig ? (
                <>
                  <div className="health-setup-values">
                    <SetupValue label="Test endpoint" value={testEndpoint} onCopy={onCopySetupValue} />
                    <SetupValue label="Live activity endpoint" value={progressEndpoint} onCopy={onCopySetupValue} />
                    <SetupValue label="Health capture token" value={setupConfig.capture_token} secret onCopy={onCopySetupValue} />
                    <SetupValue label="Installation ID" value={setupConfig.installation_id} onCopy={onCopySetupValue} />
                  </div>
                  <ol className="health-lens-steps health-lens-steps--compact">
                    <li>In Shortcuts, create <strong>ianOS Health test</strong> and add <strong>Get Contents of URL</strong>.</li>
                    <li>Paste the test endpoint, set Method to <strong>POST</strong>, and add header <code>Authorization</code> with value <code>Bearer [Health capture token]</code>.</li>
                    <li>Add <strong>Show Result</strong>, run it once, and look for <strong>ready</strong>.</li>
                  </ol>
                  <p className="dim">When your Steps lookup returns one daily number, use the live activity endpoint with the Current Date variable and that number. ianOS adds the secure date and provenance fields for you.</p>
                </>
              ) : null}
            </section>
          </>
        ) : (
          <>
            <h3>{healthStatusCopy(model)}</h3>
            <dl className="health-lens-facts">
              <div><dt>Last sleep</dt><dd>{model.sleepHours === null ? '-' : formatHealthDuration(model.sleepHours)}</dd></div>
              <div><dt>Sleep average</dt><dd>{model.sleepAverage === null ? '-' : formatHealthDuration(model.sleepAverage)}</dd></div>
              <div><dt>Sleep coverage</dt><dd>{model.sleepCoverage === null ? '-' : `${model.sleepCoverage} of 7 nights`}</dd></div>
            </dl>
            <HealthMicroRail history={history} />
          </>
        )}
        {/* SPEC-v37 §8.6 point 1: the one-time card on the page only asks
            once, this is the permanent way back to the same decision --
            "on"/"off" here always matches health_ai_prefs.share_health_with_
            ai, not the local one-time-seen flag that only suppresses the
            card. */}
        <div className="health-ai-consent-row">
          <p className="health-lens-privacy">
            {healthAiConsent?.enabled
              ? 'Health sharing is on. Physician and coach can include your health log in their nightly prompt.'
              : 'Health sharing is off. Physician and coach run without your health log.'}
          </p>
          {onToggleHealthAiConsent && (
            <button type="button" className="btn btn-quiet health-ai-toggle-btn"
                    disabled={consentSaving} onClick={onToggleHealthAiConsent}>
              {consentSaving ? 'Saving…' : healthAiConsent?.enabled ? 'Turn off' : 'Turn on'}
            </button>
          )}
        </div>
      </div>
    </Sheet>
  )
}

// SPEC-v34: track_days_per_week (5 = weekdays only, 7 = every day) and
// rest_days_per_week (0-6, the weekly-refill allowance). Ian's own choice,
// never agent-written, kept out of the main hero per the spec (a small gear
// near the streak, not a prominent control -- this is a once-in-a-while
// setting). Popover on desktop / bottom sheet on phone, the Sheet primitive
// deciding which by breakpoint, same as AgentChat's Context sheet.
function GymPrefsSheet({ open, onClose, anchor, prefs, toast, onSaved }) {
  const [trackDays, setTrackDays] = useState(5)
  const [restDays, setRestDays] = useState(2)
  const [saving, setSaving] = useState(false)

  // Re-seed from the server-shaped prefs every time the sheet opens, so a
  // dismiss-without-saving never leaves a half-edited value lying around
  // (mirrors MoneyPrefsSheet's own open-triggered re-seed).
  useEffect(() => {
    if (!open) return
    setTrackDays(prefs?.track_days_per_week === 7 ? 7 : 5)
    const rest = Number(prefs?.rest_days_per_week)
    setRestDays(Number.isFinite(rest) ? Math.min(REST_DAYS_MAX, Math.max(REST_DAYS_MIN, rest)) : 2)
  }, [open, prefs])

  async function save() {
    setSaving(true)
    try {
      const saved = await api('/api/gym/prefs', 'PATCH', {
        track_days_per_week: trackDays,
        rest_days_per_week: restDays,
      })
      onSaved?.(saved)
      onClose?.()
    } catch (err) {
      toast?.(err.message || 'Could not save gym tracking settings', 'warn')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onClose={onClose} title="Gym tracking" variant="popover" anchor={anchor}>
      <section className="money-prefs-section">
        <h3 className="money-prefs-label">Track</h3>
        <div className="segmented" role="radiogroup" aria-label="days tracked per week">
          {TRACK_DAYS_OPTIONS.map((n) => (
            <button key={n} type="button" role="radio" aria-checked={trackDays === n}
                    className={trackDays === n ? 'seg-on' : ''}
                    onClick={() => setTrackDays(n)}>
              {n === 5 ? 'Weekdays' : 'Every day'}
            </button>
          ))}
        </div>
      </section>
      <section className="money-prefs-section">
        <h3 className="money-prefs-label">Rest days per week</h3>
        <div className="gym-rest-stepper">
          <button type="button" className="gym-rest-btn" aria-label="Fewer rest days"
                  disabled={restDays <= REST_DAYS_MIN}
                  onClick={() => setRestDays((n) => Math.max(REST_DAYS_MIN, n - 1))}>−</button>
          <span className="gym-rest-value">{restDays}</span>
          <button type="button" className="gym-rest-btn" aria-label="More rest days"
                  disabled={restDays >= REST_DAYS_MAX}
                  onClick={() => setRestDays((n) => Math.min(REST_DAYS_MAX, n + 1))}>+</button>
        </div>
        <p className="dim gym-rest-hint">
          Miss a tracked day and it holds the streak until this many are spent for the week. Refills every week.
        </p>
      </section>
      <div className="money-prefs-actions">
        <button type="button" className="btn" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </Sheet>
  )
}

// SPEC-v37 §8.6 point 1: shown once, only while consent is genuinely
// undecided (consented_at is null -- nobody has ever answered either way).
// Calm, informational styling: this is a consent surface, not a warning, so
// no --crit, no urgency framing, matching the gym/Plan/Journal/lock-screen/
// Fury-chat precedent of never shaming or alarming Ian on this app.
function HealthAiConsentCard({ saving, onDecide }) {
  return (
    <section className="panel health-consent-card" aria-labelledby="health-consent-title">
      <h3 id="health-consent-title">Let physician and coach read your health log?</h3>
      <p>
        Turning this on lets <strong>physician</strong> and <strong>coach</strong>, the two health-focused
        nightly agents, include your health log (sleep hours, steps, workout count/minutes/type, energy
        rating, weight, and any notes you write for the day) plus 7-day rollups (average sleep, workout
        count, days since your last workout) in the prompt they send to Anthropic&apos;s API each night
        they run.
      </p>
      <p>
        Every other agent stays exactly as walled off as it is today: this only changes what physician
        and coach can see, only in their own nightly prompt, and only while this stays on. Turn it off
        again any time from this page, no explanation needed.
      </p>
      <div className="health-consent-actions">
        <button type="button" className="btn ghost" disabled={saving} onClick={() => onDecide(false)}>
          Not now
        </button>
        <button type="button" className="btn" disabled={saving} onClick={() => onDecide(true)}>
          {saving ? 'Saving…' : 'Turn on'}
        </button>
      </div>
    </section>
  )
}

export default function BodyPage({ state, refresh, toast }) {
  const [busy, setBusy] = useState(false)
  const [burst, setBurst] = useState(0)
  const [montageOpen, setMontageOpen] = useState(false)
  const [prefsOpen, setPrefsOpen] = useState(false)
  const [healthLensOpen, setHealthLensOpen] = useState(false)
  const [healthBusy, setHealthBusy] = useState(false)
  const [healthLoading, setHealthLoading] = useState(!state.health_status)
  const [healthSetup, setHealthSetup] = useState(null)
  const [healthSetupLoading, setHealthSetupLoading] = useState(false)
  const [healthSetupError, setHealthSetupError] = useState('')
  const [healthPayload, setHealthPayload] = useState({
    status: state.health_status || null,
    today: null,
    history: null,
    insights: null,
  })
  const [gymPrefs, setGymPrefs] = useState({ track_days_per_week: 5, rest_days_per_week: 2 })
  // SPEC-v37 §8.6 point 1. `consented_at` is server truth for "has anyone
  // ever answered" (Turn on sets it, Not now leaves it NULL); consentSeen is
  // this browser's own record that the ask already happened, so a "Not now"
  // doesn't leave the card reappearing on every visit (db.set_health_ai_
  // sharing only ever stamps consented_at on an opt-in, never on a decline).
  const [healthAiConsent, setHealthAiConsent] = useState({ enabled: false, consent_version: '', consented_at: null })
  const [healthAiConsentLoaded, setHealthAiConsentLoaded] = useState(false)
  const [consentSeen, setConsentSeen] = useState(() => {
    try { return localStorage.getItem(HEALTH_CONSENT_SEEN_KEY) === '1' } catch { return true }
  })
  const [consentSaving, setConsentSaving] = useState(false)
  const gearRef = useRef(null)
  const healthRequestRef = useRef(0)
  const healthStatusRef = useRef(state.health_status || null)
  const rm = useReducedMotion()
  const gym = state.gym || {}
  const garden = state.garden || { stage: 1, mood: 'steady' }
  const weeklyInsight = Array.isArray(healthPayload.insights?.insights)
    ? healthPayload.insights.insights.find((insight) => insight?.kind === 'weekly')
    : null
  const montage = weeklyInsight
    ? { title: 'Weekly reflection', body: weeklyInsight.body }
    : healthPayload.insights?.legacy_montage || null
  const stools = gym.stools ?? 0
  const goals = goalsForPillar(state.goals, 'body')
  const trackDaysPerWeek = gymPrefs.track_days_per_week === 7 ? 7 : 5
  const healthModel = healthDisplayModel(
    healthPayload.status || state.health_status,
    healthPayload.today,
    state.wellness_today || {},
  )
  const healthHistoryRows = healthHistory(healthPayload.history)

  useEffect(() => {
    healthStatusRef.current = state.health_status || null
  }, [state.health_status])

  const refreshHealth = useCallback(async () => {
    const requestId = ++healthRequestRef.current
    const requests = await Promise.allSettled([
      api('/api/health/status', 'GET', undefined, { cache: 'no-store' }),
      api('/api/health/today', 'GET', undefined, { cache: 'no-store' }),
      api('/api/health/history?range=7', 'GET', undefined, { cache: 'no-store' }),
      api('/api/health/insights', 'GET', undefined, { cache: 'no-store' }),
    ])
    if (requestId !== healthRequestRef.current) return
    setHealthPayload((previous) => ({
      status: requests[0].status === 'fulfilled' ? requests[0].value : (previous.status || healthStatusRef.current),
      today: requests[1].status === 'fulfilled' ? requests[1].value : previous.today,
      history: requests[2].status === 'fulfilled' ? requests[2].value : previous.history,
      insights: requests[3].status === 'fulfilled' ? requests[3].value : previous.insights,
    }))
    setHealthLoading(false)
  }, [])

  useEffect(() => {
    let cancelled = false
    api('/api/gym/prefs', 'GET', undefined, { cache: 'no-store' })
      .then((prefs) => { if (!cancelled) setGymPrefs(prefs) })
      .catch(() => { /* pre-migration DB or unreachable Mac: 5-day/2-rest default stands */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    let cancelled = false
    api('/api/health/ai-consent', 'GET', undefined, { cache: 'no-store' })
      .then((prefs) => { if (!cancelled) { setHealthAiConsent(prefs); setHealthAiConsentLoaded(true) } })
      .catch(() => { /* unreachable Mac: card stays hidden until this resolves */ })
    return () => { cancelled = true }
  }, [])

  const decideHealthAiConsent = async (enabled) => {
    setConsentSaving(true)
    try {
      const saved = await api('/api/health/ai-consent', 'PATCH', {
        enabled,
        consent_version: enabled ? HEALTH_CONSENT_VERSION : '',
      })
      setHealthAiConsent(saved)
      if (!enabled) {
        try { localStorage.setItem(HEALTH_CONSENT_SEEN_KEY, '1') } catch { /* not load-bearing */ }
        setConsentSeen(true)
      }
      toast(enabled
        ? 'Health sharing on. Physician and coach can use it starting tonight.'
        : 'Health sharing stays off.', 'good')
    } catch (err) {
      toast(err.message || 'Could not save health sharing preference', 'warn')
    } finally {
      setConsentSaving(false)
    }
  }

  useEffect(() => {
    let active = true
    refreshHealth().catch(() => {
      if (active) setHealthLoading(false)
    })
    return () => {
      active = false
      healthRequestRef.current += 1
    }
  }, [refreshHealth])

  useEffect(() => {
    const needsSetup = healthModel.state === 'not_configured' || healthModel.state === 'awaiting_first_snapshot'
    if (!healthLensOpen || !needsSetup) return undefined
    let active = true
    setHealthSetupLoading(true)
    setHealthSetupError('')
    api('/api/health/setup', 'GET', undefined, { cache: 'no-store' })
      .then((config) => {
        if (active) setHealthSetup(config)
      })
      .catch(() => {
        if (active) setHealthSetupError('Run make phone once on your Mac to prepare Health capture, then reopen this Sheet.')
      })
      .finally(() => {
        if (active) setHealthSetupLoading(false)
      })
    return () => { active = false }
  }, [healthLensOpen, healthModel.state])

  const confirmGym = async () => {
    setBusy(true)
    try {
      const res = await api('/api/gym/confirm', 'POST', {}, { queueable: true })
      setBurst((n) => n + 1)
      toast(res?.queued
        ? `${DELIGHT[burst % DELIGHT.length]} Saved. Syncs when your Mac wakes.`
        : `${DELIGHT[burst % DELIGHT.length]} ${res.gym?.streak || 0} day streak`, 'good')
      refresh()
    } catch (e) {
      toast(e.message || 'Could not confirm gym', 'warn')
    } finally {
      setBusy(false)
    }
  }

  const logEnergy = async (value) => {
    setHealthBusy(true)
    try {
      const result = await api('/api/wellness', 'POST', { energy: value }, { queueable: true })
      setHealthPayload((previous) => ({
        ...previous,
        status: result?.queued
          ? { ...(previous.status || state.health_status || {}), state: 'queued_manual' }
          : previous.status,
        today: { ...(previous.today || {}), energy: value },
      }))
      toast(result?.queued ? 'Energy saved on this phone. Syncs when your Mac wakes.' : 'Energy saved.', 'good')
      if (!result?.queued) await refreshHealth()
      refresh()
    } catch (error) {
      toast(error.message || 'Could not save energy', 'warn')
    } finally {
      setHealthBusy(false)
    }
  }

  const handleHealthAction = async (action) => {
    if (action.kind === 'gym') {
      await confirmGym()
      return
    }
    setHealthLensOpen(true)
  }

  const copyHealthSetupValue = async (value, label) => {
    try {
      await navigator.clipboard.writeText(value)
      toast(`${label} copied.`, 'good')
    } catch {
      toast(`Could not copy ${label.toLowerCase()}.`, 'warn')
    }
  }

  const showHealthConsentCard = healthAiConsentLoaded && !consentSeen && !healthAiConsent.consented_at

  return (
    <div className="body-page page-layout page-layout--overview">
      {showHealthConsentCard && (
        <HealthAiConsentCard saving={consentSaving} onDecide={decideHealthAiConsent} />
      )}

      {healthLoading && !healthPayload.status && !state.health_status ? (
        <HealthSignalSkeleton />
      ) : (
        <HealthSignalPanel
          model={healthModel}
          history={healthHistoryRows}
          gymConfirmed={Boolean(gym.confirmed_today)}
          reduced={rm}
          onAction={handleHealthAction}
          onEnergy={logEnergy}
          energyBusy={healthBusy}
        />
      )}

      <div className="body-training-column">
        <section className="panel gym-hero-panel">
          <div className="gym-hero">
            <Garden stage={garden.stage} mood={garden.mood} spark={garden.spark} />
            <div className="gym-streak-wrap">
              <motion.div
                key={gym.streak}
                className="gym-streak-num"
                initial={rm ? false : { scale: 0.92 }}
                animate={{ scale: 1 }}
                transition={{ type: 'spring', stiffness: 400, damping: 24 }}
              >
                {gym.streak ?? 0}
              </motion.div>
              <div className="gym-streak-head">
                <span className="gym-streak-label">{trackDaysPerWeek === 7 ? 'day streak' : 'weekday streak'}</span>
                <button ref={gearRef} type="button" className="gym-settings-btn"
                        aria-label="Gym tracking settings" onClick={() => setPrefsOpen(true)}>
                  <span aria-hidden="true">⚙︎</span>
                </button>
              </div>
              {stools > 0 && (
                <div className="gym-stools" title="rest days left this week">
                  {Array.from({ length: stools }).map((_, i) => (
                    <span key={i} className="gym-stool" aria-hidden="true">▰</span>
                  ))}
                  <span className="gym-stools-label">rest {stools === 1 ? 'day' : 'days'} left this week</span>
                </div>
              )}
            </div>
            <div className={`gym-week${trackDaysPerWeek === 7 ? ' gym-week--seven' : ''}`}>
              {(gym.week || []).map((d) => {
                const status = d.confirmed ? 'gym confirmed' : d.graced ? 'planned rest day' : d.future ? 'upcoming' : 'not confirmed'
                return (
                  <div key={d.date}
                       role="img"
                       aria-label={`${d.label}: ${status}`}
                       className={`gym-day${d.confirmed ? ' done' : ''}${d.graced ? ' graced' : ''}${d.future ? ' future' : ''}`}>
                    <span className="gym-day-label">{d.label}</span>
                    <span className="gym-day-dot" aria-hidden="true">
                      {d.confirmed ? '✓' : d.graced ? '◐' : '·'}
                    </span>
                  </div>
                )
              })}
            </div>
            <div className="gym-confirm-wrap">
              {gymConfirmState(gym) === 'confirmed' ? (
                <p className="gym-done-msg good-text">Gym confirmed today ✓</p>
              ) : gymConfirmState(gym) === 'confirm' ? (
                <button type="button" className="btn gym-confirm-btn" onClick={confirmGym} disabled={busy}>
                  {busy ? 'Saving…' : 'Confirm gym'}
                </button>
              ) : (
                <p className="dim">Weekend, streak safe</p>
              )}
              <AnimatePresence>
                {burst > 0 && !rm && (
                  <motion.span
                    key={burst}
                    className="gym-burst"
                    initial={{ opacity: 0, scale: 0.5, y: 0 }}
                  animate={{ opacity: [0, 1, 0], scale: [0.5, 1.2, 1], y: -24 }}
                  transition={{ duration: 0.9 }}
                  aria-hidden="true"
                >
                    ✦
                  </motion.span>
                )}
              </AnimatePresence>
            </div>
            <span className="chip chip-idle gym-hint">{trackDaysPerWeek === 7 ? 'every day' : 'weekdays'}</span>
          </div>
        </section>

        <PoopLog toast={toast} />

        {montage && (
          <section className="panel montage-panel">
            <button type="button" className="montage-head" onClick={() => setMontageOpen(!montageOpen)}
                    aria-expanded={montageOpen} aria-controls="body-weekly-montage">
              <span className="section-label">This week&apos;s montage</span>
              <span className="montage-title">{montage.title}</span>
              <span className="montage-toggle">{montageOpen ? '−' : 'Read →'}</span>
            </button>
            <AnimatePresence initial={false}>
              {montageOpen && (
                <motion.div id="body-weekly-montage" className="montage-body"
                  initial={rm ? false : { opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}>
                  {montage.body.split(/\n+/).filter(Boolean).map((para, i) => {
                    const m = para.match(/^\*\*(.+?):\*\*\s*(.*)$/)
                    return m
                      ? <p key={i}><strong>{m[1]}</strong> {m[2]}</p>
                      : <p key={i}>{para.replace(/\*\*/g, '')}</p>
                  })}
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        )}

        <PillarGoalPanel
          pillar="body"
          title="Health goals"
          goals={goals}
          refresh={refresh}
          toast={toast}
          variant="simple"
          doneStates={new Set((state.meta?.done_states || []).map((s) => s.toLowerCase()))}
        />
      </div>

      <GymPrefsSheet
        open={prefsOpen}
        onClose={() => setPrefsOpen(false)}
        anchor={gearRef}
        prefs={gymPrefs}
        toast={toast}
        onSaved={(saved) => { setGymPrefs(saved); refresh() }}
      />

      <HealthLensSheet
        open={healthLensOpen}
        onClose={() => {
          setHealthLensOpen(false)
          setHealthSetup(null)
          setHealthSetupError('')
        }}
        model={healthModel}
        history={healthHistoryRows}
        setupConfig={healthSetup}
        setupLoading={healthSetupLoading}
        setupError={healthSetupError}
        onCopySetupValue={copyHealthSetupValue}
        healthAiConsent={healthAiConsent}
        consentSaving={consentSaving}
        onToggleHealthAiConsent={() => decideHealthAiConsent(!healthAiConsent.enabled)}
      />
    </div>
  )
}
