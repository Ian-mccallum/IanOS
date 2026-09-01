/**
 * The Health routes are intentionally new and narrow.  This adapter lets the
 * Body surface stay honest during the migration: it accepts the source-aware
 * route shape when it exists, and the old wellness row only as a clearly
 * labelled manual fallback.  Do not turn missing fields into zero here.
 */

const SOURCE_LABELS = {
  apple_health_shortcuts: 'Apple Watch',
  apple_health: 'Apple Health',
  oura_via_apple_health: 'Apple Watch',
  oura_direct: 'Oura',
  manual: 'Manual entry',
  legacy_csv: 'Imported health record',
  legacy_import: 'Imported health record',
}

const STATE_ALIASES = {
  not_configured: 'not_configured',
  unconfigured: 'not_configured',
  setup_required: 'not_configured',
  awaiting_first_snapshot: 'awaiting_first_snapshot',
  awaiting: 'awaiting_first_snapshot',
  waiting: 'awaiting_first_snapshot',
  fresh: 'fresh',
  ready: 'fresh',
  current: 'fresh',
  late: 'late',
  stale: 'late',
  needs_review: 'needs_review',
  review: 'needs_review',
  partial: 'partial',
  app_cache_only: 'app_cache_only',
  cached: 'app_cache_only',
  queued_manual: 'queued_manual',
  queued: 'queued_manual',
}

function record(value) {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function scalar(value) {
  if (!record(value)) return value
  return value.value ?? value.value_num ?? value.current ?? value.amount ?? null
}

function candidates(root) {
  if (!record(root)) return []
  return [root, root.metrics, root.values, root.projection, root.data, root.today]
    .filter(record)
}

function firstScalar(root, keys) {
  for (const candidate of candidates(root)) {
    for (const key of keys) {
      if (candidate[key] !== undefined && candidate[key] !== null) {
        const value = scalar(candidate[key])
        if (value !== undefined && value !== null) return value
      }
    }
  }
  return null
}

function firstNumber(...sources) {
  for (const source of sources) {
    const value = numberOrNull(source)
    if (value !== null) return value
  }
  return null
}

function firstText(...sources) {
  for (const source of sources) {
    if (typeof source === 'string' && source.trim()) return source.trim()
  }
  return null
}

function statusRecord(payload) {
  if (!record(payload)) return {}
  return record(payload.status) ? payload.status : payload
}

function todayRecord(payload) {
  if (!record(payload)) return {}
  return record(payload.today) ? payload.today : payload
}

function sourceLabel(value) {
  if (record(value)) return sourceLabel(value.label || value.name || value.key || value.source_key)
  if (typeof value !== 'string' || !value.trim()) return null
  const normalized = value.trim().toLowerCase()
  return SOURCE_LABELS[normalized] || value.trim().replace(/_/g, ' ')
}

function statusKey(status, hasData) {
  const explicit = firstText(
    firstScalar(status, ['state', 'freshness', 'configuration_state', 'health_state']),
    typeof status.status === 'string' ? status.status : null,
  )
  const normalized = explicit?.trim().toLowerCase().replace(/[ -]+/g, '_')
  if (normalized && STATE_ALIASES[normalized]) return STATE_ALIASES[normalized]
  if (status.needs_review || status.review_required || status.quarantined_count > 0) return 'needs_review'
  if (status.partial || status.is_partial) return 'partial'
  if (status.cache_only || status.app_cache_only) return 'app_cache_only'
  if (status.queued_manual || status.manual_write_queued) return 'queued_manual'
  if (status.configured === false || status.is_configured === false) return 'not_configured'
  if (status.configured || status.is_configured) {
    const capture = firstText(firstScalar(status, [
      'last_accepted_capture', 'last_capture', 'captured_at', 'received_at', 'updated_at',
    ]))
    return capture || hasData ? 'fresh' : 'awaiting_first_snapshot'
  }
  return hasData ? 'legacy' : 'not_configured'
}

/** Convert a source-aware health payload into exactly the display facts Body needs. */
export function healthDisplayModel(statusPayload, todayPayload, legacyPayload = {}) {
  const status = statusRecord(statusPayload)
  const today = todayRecord(todayPayload)
  const legacy = todayRecord(legacyPayload)

  const field = (keys) => firstScalar(today, keys) ?? firstScalar(legacy, keys)
  const statusField = (keys) => firstScalar(status, keys)

  const sleepHours = firstNumber(field(['sleep_hours', 'sleep']))
  const steps = firstNumber(field(['steps']))
  const workoutMins = firstNumber(field(['workout_mins', 'workout_minutes', 'training_minutes']))
  const workouts = firstNumber(field(['workouts', 'workout_count']))
  const energy = firstNumber(field(['energy']))
  const hasData = [sleepHours, steps, workoutMins, workouts, energy].some((value) => value !== null)
  const key = statusKey(status, hasData)
  const source = sourceLabel(firstScalar(status, ['source_label', 'selected_source_label', 'source', 'source_key']))
    || sourceLabel(firstScalar(today, ['source_label', 'source', 'source_key']))
    || (key === 'legacy' ? 'Manual health log' : 'Apple Watch')

  const capturedAt = firstText(
    statusField(['last_accepted_capture', 'last_capture', 'captured_at', 'received_at', 'updated_at']),
    field(['captured_at', 'received_at', 'updated_at']),
  )
  const activityAsOf = firstText(field(['activity_as_of', 'as_of', 'activity_updated_at']))
  const finality = firstText(field(['activity_finality', 'finality']))
  const sleepStart = firstText(field(['sleep_window_start', 'sleep_start', 'sleep_started_at', 'sleep_begin']))
  const sleepEnd = firstText(field(['sleep_window_end', 'sleep_end', 'sleep_ended_at', 'sleep_finish']))

  return {
    state: key,
    source,
    capturedAt,
    sleepHours,
    sleepAverage: firstNumber(
      field(['sleep_avg_7d', 'sleep_7d_avg', 'average_sleep_7d']),
      statusField(['sleep_avg_7d', 'sleep_7d_avg', 'average_sleep_7d']),
    ),
    sleepCoverage: firstNumber(
      field(['sleep_coverage_7d', 'sleep_days_7d']),
      statusField(['sleep_coverage_7d', 'sleep_days_7d', 'sleep_coverage']),
    ),
    sleepStart,
    sleepEnd,
    steps,
    workoutMins,
    workouts,
    energy: energy != null && energy >= 1 && energy <= 5 ? energy : null,
    activityAsOf,
    activityDay: firstText(field(['activity_day', 'local_day', 'date'])),
    activityFinality: finality?.toLowerCase() || null,
    detectedWorkout: Boolean(
      firstScalar(today, ['detected_workout_awaiting_gym', 'workout_awaiting_confirmation', 'detected_workout']),
    ),
    reviewCount: firstNumber(statusField(['review_count', 'quarantined_count', 'needs_review_count'])),
    rawToday: today,
    rawStatus: status,
  }
}

export function healthHistory(payload) {
  const root = Array.isArray(payload) ? payload : (record(payload) ? payload : {})
  const rows = Array.isArray(root) ? root
    : (Array.isArray(root.days) ? root.days : (Array.isArray(root.history) ? root.history : []))
  return rows.map((row) => {
    const day = todayRecord(row)
    return {
      day: firstText(firstScalar(day, ['local_day', 'date', 'day'])),
      sleepHours: firstNumber(firstScalar(day, ['sleep_hours', 'sleep'])),
      energy: firstNumber(firstScalar(day, ['energy'])),
      source: sourceLabel(firstScalar(day, ['source_label', 'source', 'source_key'])),
    }
  }).filter((row) => row.day || row.sleepHours !== null || row.energy !== null)
}

export function formatHealthDuration(hours) {
  const value = numberOrNull(hours)
  if (value === null || value < 0) return 'No data yet'
  const minutes = Math.round(value * 60)
  const wholeHours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  if (!wholeHours) return `${remainder}m`
  return remainder ? `${wholeHours}h ${remainder}m` : `${wholeHours}h`
}

export function formatHealthCount(value) {
  const number = numberOrNull(value)
  return number === null ? null : Math.round(number).toLocaleString('en-US')
}

/** A user-facing capture label. Already-formatted server labels pass through. */
export function formatHealthTime(value) {
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(parsed)
}

export function healthStatusCopy(model) {
  const source = model.source || 'Health source'
  const capture = formatHealthTime(model.capturedAt)
  switch (model.state) {
    case 'not_configured': return 'Apple Watch capture is not set up.'
    case 'awaiting_first_snapshot': return 'Waiting for your first health snapshot.'
    case 'late': return 'No health snapshot received in 30h.'
    case 'needs_review': {
      const count = model.reviewCount || 1
      return `${count} health ${count === 1 ? 'snapshot needs' : 'snapshots need'} review. Your recorded data is unchanged.`
    }
    case 'partial': return model.activityAsOf
      ? `Today through ${formatHealthTime(model.activityAsOf) || model.activityAsOf}.`
      : 'Today has a partial health snapshot.'
    case 'app_cache_only': return 'Showing a cached ianOS view. Your Mac is asleep.'
    case 'queued_manual': return 'Energy is saved on this phone. Sends when your Mac wakes.'
    case 'legacy': return 'Manual health entry.'
    default: return capture ? `${source} snapshot received ${capture}.` : `${source} snapshot is current.`
  }
}

export function healthActivityCopy(model) {
  const facts = []
  const steps = formatHealthCount(model.steps)
  if (steps !== null) facts.push(`${steps} steps`)
  if (model.workoutMins !== null) facts.push(`${formatHealthDuration(model.workoutMins / 60)} training`)
  else if (model.workouts !== null) facts.push(`${model.workouts} ${model.workouts === 1 ? 'workout' : 'workouts'}`)
  if (!facts.length) return null
  const asOf = formatHealthTime(model.activityAsOf)
  const prefix = model.activityFinality === 'partial' || model.state === 'partial'
    ? (asOf ? `Today through ${asOf}` : 'Today so far')
    : (model.activityDay ? 'Yesterday' : 'Activity')
  return `${prefix}: ${facts.join(' · ')}`
}

export function healthNextAction(model, gymConfirmed = false) {
  if (model.state === 'not_configured') return { kind: 'setup', label: 'Set up capture' }
  if (model.state === 'awaiting_first_snapshot') return { kind: 'test', label: 'Run a test snapshot' }
  if (model.state === 'late' || model.state === 'needs_review') return { kind: 'repair', label: 'Check capture' }
  if (model.detectedWorkout && !gymConfirmed) return { kind: 'gym', label: 'Count toward gym streak' }
  if (model.energy === null) return { kind: 'energy', label: 'Log energy' }
  return { kind: 'details', label: 'Details' }
}

function hourOf(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return ((value % 24) + 24) % 24
  if (typeof value !== 'string' || !value.trim()) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.getHours() + (parsed.getMinutes() / 60)
}

/** SVG arc coordinates for a 6 PM through 6 PM 24-hour instrument arc. */
export function sleepArcPath(startValue, endValue) {
  const startHour = hourOf(startValue)
  const endHour = hourOf(endValue)
  if (startHour === null || endHour === null) return null
  const start = ((startHour - 18) + 24) % 24
  let end = ((endHour - 18) + 24) % 24
  if (end <= start) end += 24
  const duration = end - start
  if (duration <= 0 || duration > 18) return null
  const point = (hour) => {
    const theta = Math.PI - (Math.PI * (hour / 24))
    return [120 + (96 * Math.cos(theta)), 102 - (96 * Math.sin(theta))]
  }
  const [x1, y1] = point(start)
  const [x2, y2] = point(end)
  return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A 96 96 0 ${duration > 12 ? 1 : 0} 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`
}
