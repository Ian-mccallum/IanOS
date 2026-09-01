import assert from 'node:assert/strict'
import test from 'node:test'

import { gymConfirmState } from '../src/lib/gym.js'

// SPEC-v34 §5: "BodyPage's confirm button renders on a Saturday when
// is_tracked_day is true and hides it when false" -- replacing any
// assertion that used the old `is_weekday` field name.

test('confirm button renders on a Saturday when is_tracked_day is true (7-day tracking)', () => {
  const gym = { confirmed_today: false, is_tracked_day: true }
  assert.equal(gymConfirmState(gym), 'confirm')
})

test('confirm button hides on a Saturday when is_tracked_day is false (5-day tracking)', () => {
  const gym = { confirmed_today: false, is_tracked_day: false }
  assert.equal(gymConfirmState(gym), 'rest')
})

test('confirmed-today message wins even on an untracked day', () => {
  assert.equal(gymConfirmState({ confirmed_today: true, is_tracked_day: false }), 'confirmed')
  assert.equal(gymConfirmState({ confirmed_today: true, is_tracked_day: true }), 'confirmed')
})

test('a tracked, unconfirmed weekday still shows the confirm button', () => {
  assert.equal(gymConfirmState({ confirmed_today: false, is_tracked_day: true }), 'confirm')
})

test('missing gym state defaults to the rest message, never a crash', () => {
  assert.equal(gymConfirmState({}), 'rest')
  assert.equal(gymConfirmState(undefined), 'rest')
})
