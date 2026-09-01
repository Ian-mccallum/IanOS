import assert from 'node:assert/strict'
import test from 'node:test'

import {
  formatHealthDuration,
  healthDisplayModel,
  healthHistory,
  healthNextAction,
  healthStatusCopy,
  sleepArcPath,
} from '../src/pages/bodyHealth.js'

test('source-aware health payload keeps source, finality, and unknown values honest', () => {
  const model = healthDisplayModel(
    {
      state: 'fresh',
      source_key: 'apple_health_shortcuts',
      source_label: 'Apple Watch',
      last_accepted_capture: '2026-08-26T12:00:00-05:00',
      sleep_coverage_7d: 5,
    },
    {
      sleep_hours: 7.5,
      sleep_avg_7d: 7.1,
      sleep_window_start: '2026-08-25T23:20:00-05:00',
      sleep_window_end: '2026-08-26T06:50:00-05:00',
      steps: 8044,
      workout_mins: 42,
      activity_day: '2026-08-26',
      activity_finality: 'partial',
      energy: null,
    },
  )

  assert.equal(model.state, 'fresh')
  assert.equal(model.source, 'Apple Watch')
  assert.equal(model.sleepHours, 7.5)
  assert.equal(model.sleepAverage, 7.1)
  assert.equal(model.steps, 8044)
  assert.equal(model.energy, null)
  assert.equal(healthNextAction(model).kind, 'energy')
})

test('health history accepts both the route envelope and a direct array', () => {
  const rows = [
    { day: '2026-08-25', sleep_hours: 7.25, energy: 4, source_key: 'apple_health_shortcuts' },
  ]
  assert.deepEqual(healthHistory({ days: rows }), healthHistory(rows))
  assert.equal(healthHistory(rows)[0].source, 'Apple Watch')
})

test('health states select one honest next action', () => {
  assert.deepEqual(healthNextAction({ state: 'not_configured' }), { kind: 'setup', label: 'Set up capture' })
  assert.deepEqual(healthNextAction({ state: 'late' }), { kind: 'repair', label: 'Check capture' })
  assert.deepEqual(healthNextAction({ state: 'fresh', detectedWorkout: true, energy: 4 }), {
    kind: 'gym', label: 'Count toward gym streak',
  })
  assert.deepEqual(healthNextAction({ state: 'fresh', detectedWorkout: true, energy: 4 }, true), {
    kind: 'details', label: 'Details',
  })
})

test('formatting and the sleep arc never fabricate an unavailable measurement', () => {
  assert.equal(formatHealthDuration(null), 'No data yet')
  assert.equal(formatHealthDuration(7.5), '7h 30m')
  assert.equal(sleepArcPath(null, '2026-08-26T07:00:00-05:00'), null)
  assert.match(sleepArcPath('2026-08-25T23:00:00-05:00', '2026-08-26T07:00:00-05:00'), /^M /)
  assert.match(healthStatusCopy({ state: 'late', source: 'Apple Watch' }), /30h/)
})
