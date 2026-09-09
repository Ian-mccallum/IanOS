import test from 'node:test'
import assert from 'node:assert/strict'

import {
  bristolLabel,
  clockLabel,
  composeLoggedAt,
  dayLine,
  defaultMissedMoment,
  entryDetail,
  missedDayOptions,
  missedTimeProblem,
  nowLocalStamp,
  railLevels,
  sinceLabel,
  weekLine,
} from '../src/lib/poop.js'

test('the rail scales against the busiest day in view', () => {
  const levels = railLevels([
    { day: '2026-09-03', count: 0 },
    { day: '2026-09-04', count: 1 },
    { day: '2026-09-05', count: 4 },
  ])
  assert.equal(levels[0].level, 0)
  assert.equal(levels[2].level, 100)
  // A logged day is never invisible: one poop must not read as none.
  assert.ok(levels[1].level >= 14)
})

test('a rail of only zeroes draws nothing rather than dividing by zero', () => {
  const levels = railLevels([{ day: '2026-09-03', count: 0 }, { day: '2026-09-04', count: 0 }])
  assert.deepEqual(levels.map((d) => d.level), [0, 0])
})

test('the day line reacts to volume and never to a target', () => {
  assert.equal(dayLine(0), 'Nothing logged yet.')
  assert.equal(dayLine(1), 'One down.')
  assert.equal(dayLine(3), 'Three. Hat trick.')
  assert.equal(dayLine(9), '9. Tell nobody.')
  assert.equal(dayLine(undefined), 'Nothing logged yet.')
})

test('no day line can read as a failure', () => {
  for (let n = 0; n <= 12; n++) {
    const line = dayLine(n).toLowerCase()
    for (const banned of ['should', 'behind', 'missed', 'fail', 'low', 'too few']) {
      assert.ok(!line.includes(banned), `dayLine(${n}) scolds: ${line}`)
    }
  }
})

test('since reads in the largest unit that still says something', () => {
  const now = new Date('2026-09-09T18:00:00')
  assert.equal(sinceLabel('2026-09-09 17:58:00', now), '2m ago')
  assert.equal(sinceLabel('2026-09-09 12:00:00', now), '6h ago')
  assert.equal(sinceLabel('2026-09-06 12:00:00', now), '3d ago')
  assert.equal(sinceLabel(null, now), '')
})

test('the DB naive-local timestamp parses without a timezone shift', () => {
  const at = clockLabel('2026-09-09 14:32:00')
  assert.match(at, /2:32/)
})

test('the week line carries data or says there is none', () => {
  assert.equal(weekLine({ per_day_avg: 1.8, window_days: 7 }), '1.8/day over 7 days')
  assert.equal(weekLine({ per_day_avg: 0, window_days: 7 }), 'no logs in 7 days')
  assert.equal(weekLine(null), 'no logs in 7 days')
})

test('an entry shows both bristol and note when both exist', () => {
  assert.equal(entryDetail({}), 'Add detail')
  assert.equal(entryDetail({ bristol: 4 }), `type 4 · ${bristolLabel(4)}`)
  assert.equal(entryDetail({ note: 'coffee' }), 'coffee')
  assert.equal(entryDetail({ bristol: 4, note: 'coffee' }), `type 4 · ${bristolLabel(4)} · coffee`)
  assert.equal(entryDetail({ queued: true }), 'saved on this phone')
})

test('the missed-time default is an hour ago, rounded to five minutes', () => {
  assert.deepEqual(defaultMissedMoment(new Date('2026-09-09T18:07:00')),
                   { day: '2026-09-09', time: '17:05' })
})

test('an hour before midnight seeds yesterday, not a future time today', () => {
  // Seeding today 23:20 at 00:20 would open the sheet already refused.
  assert.deepEqual(defaultMissedMoment(new Date('2026-09-09T00:20:00')),
                   { day: '2026-09-08', time: '23:20' })
})

test('a missed time is refused before the tap, on both bounds', () => {
  const now = new Date('2026-09-09T18:00:00')
  assert.equal(missedTimeProblem('2026-09-09', '10:00', now), '')
  assert.equal(missedTimeProblem('2026-09-08', '23:30', now), '')
  assert.match(missedTimeProblem('2026-09-09', '21:00', now), /ahead of you/)
  assert.match(missedTimeProblem('2026-08-01', '10:00', now), /last 14 days/)
  assert.equal(missedTimeProblem('2026-09-09', '', now), 'Pick a time.')
})

test('the composed stamp is the naive-local shape the table stores', () => {
  assert.equal(composeLoggedAt('2026-09-09', '08:00'), '2026-09-09 08:00:00')
  assert.equal(composeLoggedAt('2026-09-09', '8:00'), null)
  assert.equal(composeLoggedAt('', '08:00'), null)
  // No 'T', no 'Z', no offset: one aware value among naive rows shifts them all.
  assert.ok(!/[TZ+]/.test(composeLoggedAt('2026-09-09', '08:00')))
  assert.ok(!/[TZ]/.test(nowLocalStamp(new Date('2026-09-09T08:07:03'))))
})

test('the day choices are today and yesterday', () => {
  const opts = missedDayOptions(new Date('2026-09-09T18:00:00'))
  assert.deepEqual(opts.map((o) => o.day), ['2026-09-09', '2026-09-08'])
  assert.deepEqual(opts.map((o) => o.label), ['Today', 'Yesterday'])
})
