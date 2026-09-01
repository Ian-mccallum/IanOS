import assert from 'node:assert/strict'
import test from 'node:test'

class MemoryStorage {
  constructor(seed = {}) {
    this.values = new Map(Object.entries(seed))
    this.failNextWrite = false
  }

  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  removeItem(key) { this.values.delete(key) }
  clear() { this.values.clear() }
  setItem(key, value) {
    if (this.failNextWrite) {
      this.failNextWrite = false
      throw new Error('quota exceeded')
    }
    this.values.set(key, String(value))
  }
}

const storage = new MemoryStorage()
globalThis.localStorage = storage

const offline = await import('../src/lib/offline.js')
const api = await import('../src/lib/api.js')

const KEY = 'ianos.queue.v1'
const DEAD_KEY = 'ianos.queue.dead.v1'

function reset() {
  storage.clear()
  globalThis.fetch = undefined
}

function legacyExpectedDate(iso) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

test('migrates a v1 record without changing its replay identity', () => {
  reset()
  const at = '2025-01-01T01:30:00.000Z'
  storage.setItem(KEY, JSON.stringify([{
    id: '1735680000000-abc123',
    path: '/api/activity',
    method: 'POST',
    body: { audit_calls: 1 },
    at,
  }]))

  assert.equal(offline.pendingCount(), 1)
  const [migrated] = JSON.parse(storage.getItem(KEY))
  assert.equal(migrated.mutation_id, '1735680000000-abc123')
  assert.equal(migrated.captured_at, at)
  assert.equal(migrated.effective_date, legacyExpectedDate(at))
})

test('one mutation envelope is sent on the first request and retained when it queues', async () => {
  reset()
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    throw new TypeError('network down')
  }

  const result = await api.api('/api/activity', 'POST', { audit_calls: 1 }, { queueable: true })
  assert.equal(result.queued, true)
  assert.equal(calls.length, 1)
  const [queued] = JSON.parse(storage.getItem(KEY))
  assert.equal(result.mutation_id, queued.mutation_id)
  assert.match(calls[0].options.headers['X-ianOS-Mutation-Id'], /^[0-9a-f-]{36}$/)
  assert.equal(queued.mutation_id, calls[0].options.headers['X-ianOS-Mutation-Id'])
  assert.equal(queued.captured_at, calls[0].options.headers['X-ianOS-Captured-At'])
  assert.equal(queued.effective_date, calls[0].options.headers['X-ianOS-Effective-Date'])
})

test('terminal failures become visible dead letters while recoverable failures stay queued', async () => {
  reset()
  offline.enqueue('/api/activity', 'POST', { audit_calls: 1 }, offline.createMutation())
  const laterMutation = offline.createMutation()
  let release
  let attempts = 0
  const waiting = new Promise((resolve) => { release = resolve })
  globalThis.fetch = async () => {
    attempts += 1
    if (attempts === 1) await waiting
    if (attempts > 1) return { ok: false, status: 503, json: async () => ({}) }
    return {
      ok: false,
      status: 409,
      json: async () => ({ detail: 'mutation id was reused with a different request' }),
    }
  }

  const terminalFlush = offline.flush()
  offline.enqueue('/api/activity', 'POST', { audit_calls: 2 }, laterMutation)
  release()
  const terminal = await terminalFlush
  assert.equal(terminal.dead, 1)
  assert.equal(offline.pendingCount(), 1)
  assert.equal(JSON.parse(storage.getItem(KEY))[0].mutation_id, laterMutation.mutation_id)
  assert.equal(offline.deadLetters().length, 1)
  assert.match(offline.deadLetters()[0].detail, /reused/)
  assert.equal('body' in offline.deadLetters()[0], false)
  assert.equal(offline.dismissDeadLetter(offline.deadLetters()[0].mutation_id), true)
  assert.equal(offline.deadLetters().length, 0)

  reset()
  offline.enqueue('/api/activity', 'POST', { audit_calls: 1 }, offline.createMutation())
  globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({}) })
  const recoverable = await offline.flush()
  assert.equal(recoverable.dead, 0)
  assert.equal(offline.pendingCount(), 1)
  assert.equal(storage.getItem(DEAD_KEY), null)
})

test('flush serializes concurrent calls, preserves taps made during replay, and keeps an item when storage cannot acknowledge it', async () => {
  reset()
  const firstMutation = offline.createMutation()
  const laterMutation = offline.createMutation()
  offline.enqueue('/api/activity', 'POST', { audit_calls: 1 }, firstMutation)
  let calls = 0
  let release
  const pending = new Promise((resolve) => { release = resolve })
  globalThis.fetch = async () => {
    calls += 1
    if (calls === 1) await pending
    if (calls > 1) return { ok: false, status: 503, json: async () => ({}) }
    return { ok: true, status: 200, json: async () => ({ ok: true }) }
  }

  const first = offline.flush()
  const second = offline.flush()
  assert.equal(first, second)
  // A second tap can happen while the first replay is awaiting the Mac. Its
  // entry must survive acknowledgement of the first one.
  offline.enqueue('/api/activity', 'POST', { audit_calls: 2 }, laterMutation)
  release()
  await first
  assert.equal(calls, 2)
  assert.equal(offline.pendingCount(), 1)
  assert.equal(JSON.parse(storage.getItem(KEY))[0].mutation_id, laterMutation.mutation_id)

  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) })
  await offline.flush()
  assert.equal(offline.pendingCount(), 0)

  offline.enqueue('/api/activity', 'POST', { audit_calls: 1 }, offline.createMutation())
  const before = storage.getItem(KEY)
  storage.failNextWrite = true
  const failed = await offline.flush()
  assert.match(failed.error, /Nothing was removed/)
  assert.equal(storage.getItem(KEY), before)
  assert.equal(offline.pendingCount(), 1)
})

test('a malformed queue is never overwritten by a new offline action', () => {
  reset()
  storage.setItem(KEY, '{not valid json')
  assert.throws(
    () => offline.enqueue('/api/activity', 'POST', { audit_calls: 1 }, offline.createMutation()),
    /could not be read/,
  )
  assert.equal(storage.getItem(KEY), '{not valid json')
  assert.match(offline.queueIssue(), /No saved action was removed/)
})

test('a full queue rejects a new action without truncating an older one', () => {
  reset()
  for (let i = 0; i < 100; i += 1) {
    offline.enqueue('/api/activity', 'POST', { audit_calls: i }, offline.createMutation())
  }
  const first = JSON.parse(storage.getItem(KEY))[0]
  assert.throws(
    () => offline.enqueue('/api/activity', 'POST', { audit_calls: 101 }, offline.createMutation()),
    /Offline queue is full/,
  )
  const remaining = JSON.parse(storage.getItem(KEY))
  assert.equal(remaining.length, 100)
  assert.deepEqual(remaining[0], first)
})
