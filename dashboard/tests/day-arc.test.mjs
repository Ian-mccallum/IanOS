import assert from 'node:assert/strict'
import test from 'node:test'
import { dayArcLayout, minutesUntil, pulseState } from '../src/lib/dayArc.js'

test('dayArcLayout clamps a block starting before the window to 0', () => {
  const { segments } = dayArcLayout(
    [{ start: '05:30', end: '07:00', status: 'planned' }], [],
    new Date('2026-09-02T10:00:00'),
  )
  assert.equal(segments[0].left, 0)
})

test('dayArcLayout draws an empty-day state with no blocks or commitments', () => {
  const { segments, nowPct } = dayArcLayout([], [], new Date('2026-09-02T13:00:00'))
  assert.equal(segments.length, 0)
  assert.ok(nowPct > 0 && nowPct < 100)
})

test('minutesUntil returns null for a time already passed today', () => {
  assert.equal(minutesUntil('09:00', new Date('2026-09-02T14:00:00')), null)
})

test('minutesUntil returns the minute gap for a future time today', () => {
  assert.equal(minutesUntil('13:00', new Date('2026-09-02T12:12:00')), 48)
})

test('pulseState breathes accent under 26 hours', () => {
  const now = new Date('2026-09-02T12:00:00')
  const pulse = { agents_at: '2026-09-02 00:00:00', backup_configured: false, backup_at: null }
  const state = pulseState(pulse, now)
  assert.equal(state.level, 'accent')
  assert.equal(state.breathing, true)
})

test('pulseState is static warn between 26 and 72 hours', () => {
  const now = new Date('2026-09-03T12:00:00')
  const pulse = { agents_at: '2026-09-02 00:00:00', backup_configured: false, backup_at: null }
  const state = pulseState(pulse, now)
  assert.equal(state.level, 'warn')
  assert.equal(state.breathing, false)
})

test('pulseState is dim and hollow past 72 hours or with no memo at all', () => {
  const now = new Date('2026-09-06T12:00:00')
  const pulse = { agents_at: '2026-09-02 00:00:00', backup_configured: false, backup_at: null }
  assert.equal(pulseState(pulse, now).level, 'dim')
  assert.equal(pulseState(null, now).level, 'dim')
})

test('pulseState rings when backup is configured and stale past 48 hours', () => {
  const now = new Date('2026-09-05T12:00:00')
  const pulse = { agents_at: '2026-09-05 00:00:00', backup_configured: true, backup_at: '2026-09-02 21:45:10' }
  assert.equal(pulseState(pulse, now).ring, true)
})

test('pulseState never returns a level containing crit for any input', () => {
  const cases = [
    null, {},
    { agents_at: '2020-01-01 00:00:00' },
    { agents_at: new Date().toISOString(), backup_configured: true, backup_at: null },
  ]
  for (const c of cases) {
    assert.ok(!String(pulseState(c, new Date()).level).includes('crit'))
  }
})
