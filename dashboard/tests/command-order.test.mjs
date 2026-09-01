import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isCommandStale,
  maybeTriggerOrderRefresh,
  orderRefreshGuardKey,
  shouldAttemptOrderRefresh,
} from '../src/lib/order.js'

class MemoryStorage {
  constructor() { this.values = new Map() }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  setItem(key, value) { this.values.set(key, String(value)) }
}

// --- isCommandStale (SPEC-v32 D3: the $0 dim-on-stale UI fallback) ---

test('command dims only when a today-anchored brief disagrees with the live order', () => {
  assert.equal(
    isCommandStale({ command: 'Call the plumber', primaryKey: 'school:9', anchorKey: 'proposal:3' }),
    true,
  )
})

test('command does not dim when the live order still matches the anchor', () => {
  assert.equal(
    isCommandStale({ command: 'Call the plumber', primaryKey: 'proposal:3', anchorKey: 'proposal:3' }),
    false,
  )
})

test('command does not dim with no sentence, no live pick, or no anchor', () => {
  assert.equal(isCommandStale({ command: '', primaryKey: 'school:9', anchorKey: 'proposal:3' }), false)
  assert.equal(isCommandStale({ command: 'x', primaryKey: undefined, anchorKey: 'proposal:3' }), false)
  assert.equal(isCommandStale({ command: 'x', primaryKey: 'school:9', anchorKey: undefined }), false)
})

// --- shouldAttemptOrderRefresh / orderRefreshGuardKey ---

test('refresh is only attempted for a today-anchored brief whose anchor disagrees with the order', () => {
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  assert.equal(shouldAttemptOrderRefresh({ nextKey: 'school:9', brief, today: '2026-08-25' }), true)
})

test('refresh is skipped when there is no live key, no brief, a stale brief date, no anchor, or a matching anchor', () => {
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  assert.equal(shouldAttemptOrderRefresh({ nextKey: null, brief, today: '2026-08-25' }), false)
  assert.equal(shouldAttemptOrderRefresh({ nextKey: 'school:9', brief: null, today: '2026-08-25' }), false)
  assert.equal(
    shouldAttemptOrderRefresh({ nextKey: 'school:9', brief: { ...brief, governs_date: '2026-08-24' }, today: '2026-08-25' }),
    false,
  )
  assert.equal(
    shouldAttemptOrderRefresh({ nextKey: 'school:9', brief: { ...brief, anchor_key: '' }, today: '2026-08-25' }),
    false,
  )
  assert.equal(shouldAttemptOrderRefresh({ nextKey: 'proposal:3', brief, today: '2026-08-25' }), false)
})

test('the guard key is unique per (brief date, anchor, next) triple', () => {
  const a = orderRefreshGuardKey({ briefDate: '2026-08-25', anchorKey: 'proposal:3', nextKey: 'school:9' })
  const b = orderRefreshGuardKey({ briefDate: '2026-08-25', anchorKey: 'proposal:3', nextKey: 'school:10' })
  assert.notEqual(a, b)
  assert.equal(a, 'order-refresh-attempted:2026-08-25:proposal:3:school:9')
})

// --- maybeTriggerOrderRefresh: the sessionStorage-backed chatty-tab guard ---

test('fires the refresh once for a fresh (date, anchor, next) triple', () => {
  const storage = new MemoryStorage()
  let calls = 0
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  const fired = maybeTriggerOrderRefresh({
    nextKey: 'school:9', brief, today: '2026-08-25', storage, requestRefresh: () => { calls += 1 },
  })
  assert.equal(fired, true)
  assert.equal(calls, 1)
})

test('a second call for the same triple never refires, even across simulated 15s polls', () => {
  const storage = new MemoryStorage()
  let calls = 0
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  const attempt = () => maybeTriggerOrderRefresh({
    nextKey: 'school:9', brief, today: '2026-08-25', storage, requestRefresh: () => { calls += 1 },
  })
  assert.equal(attempt(), true)
  assert.equal(attempt(), false)
  assert.equal(attempt(), false)
  assert.equal(calls, 1)
})

test('a new next.key (the order changed again) is allowed to fire independently', () => {
  const storage = new MemoryStorage()
  let calls = 0
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  const requestRefresh = () => { calls += 1 }
  maybeTriggerOrderRefresh({ nextKey: 'school:9', brief, today: '2026-08-25', storage, requestRefresh })
  maybeTriggerOrderRefresh({ nextKey: 'school:10', brief, today: '2026-08-25', storage, requestRefresh })
  assert.equal(calls, 2)
})

test('never fires and never throws when sessionStorage is unavailable (private browsing)', () => {
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  const throwingStorage = {
    getItem() { throw new Error('SecurityError') },
    setItem() { throw new Error('SecurityError') },
  }
  let calls = 0
  const fired = maybeTriggerOrderRefresh({
    nextKey: 'school:9', brief, today: '2026-08-25', storage: throwingStorage, requestRefresh: () => { calls += 1 },
  })
  assert.equal(fired, false)
  assert.equal(calls, 0)
})

test('does not fire once the anchor already matches the live order', () => {
  const storage = new MemoryStorage()
  let calls = 0
  const brief = { date: '2026-08-25', governs_date: '2026-08-25', anchor_key: 'proposal:3' }
  const fired = maybeTriggerOrderRefresh({
    nextKey: 'proposal:3', brief, today: '2026-08-25', storage, requestRefresh: () => { calls += 1 },
  })
  assert.equal(fired, false)
  assert.equal(calls, 0)
})
