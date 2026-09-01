/* Offline write queue: tap now, sync when the Mac is awake.
 *
 * A queued write has one mutation identity from the first network attempt to
 * every replay. The server stores that identity with its business change, so a
 * lost response cannot turn a retry into a second gym confirmation or counter
 * increment.
 */

const KEY = 'ianos.queue.v1'
const DEAD_KEY = 'ianos.queue.dead.v1'
const SYNC_KEY = 'ianos.lastSync.v1'
const MAX = 100
const MAX_DEAD = 50
// SPEC-v20 names these exact terminal outcomes. Auth, timeout, rate-limit,
// network and 5xx results retain their id because they may recover.
const TERMINAL_STATUSES = new Set([400, 404, 409, 422])

const listeners = new Set()
let flushing = null
let issue = null

export class OfflineQueueError extends Error {
  constructor(message) {
    super(message)
    this.name = 'OfflineQueueError'
  }
}

function notify(count) {
  listeners.forEach((fn) => fn(count))
}

function readStored(key, fallback = [], errorMessage) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    const value = JSON.parse(raw)
    if (!Array.isArray(value)) throw new Error('not an array')
    return value
  } catch {
    issue = errorMessage
    throw new OfflineQueueError(errorMessage)
  }
}

function writeStored(key, items, failureMessage) {
  try {
    localStorage.setItem(key, JSON.stringify(items))
  } catch {
    issue = failureMessage
    throw new OfflineQueueError(failureMessage)
  }
}

function localDate(when) {
  const date = new Date(when)
  if (Number.isNaN(date.getTime())) return null
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function normalizeItem(item) {
  if (!item || typeof item !== 'object') return item
  if (item.mutation_id && item.captured_at && item.effective_date) return item

  // v1 used { id, at } only. Keep that historical id exactly: the API accepts
  // its narrow timestamp/random shape during the bridge release.
  const capturedAt = item.captured_at || item.at
  return {
    ...item,
    mutation_id: item.mutation_id || item.id,
    captured_at: capturedAt,
    effective_date: item.effective_date || localDate(capturedAt),
  }
}

function read() {
  const raw = readStored(KEY, [], 'Your offline queue could not be read. No saved action was removed.')
  const items = raw.map(normalizeItem)
  const migrated = JSON.stringify(raw) !== JSON.stringify(items)
  if (migrated) {
    try {
      // Persist before forgetting the legacy shape. If storage is full, the old
      // value remains untouched and this in-memory version can still be shown.
      writeStored(KEY, items, 'Your offline queue is full. Nothing was removed; reconnect before saving another action.')
    } catch { /* issue is visible to the caller; do not discard the raw queue */ }
  }
  return items
}

function write(items) {
  writeStored(KEY, items, 'Your offline queue is full. Nothing was removed; reconnect before saving another action.')
  issue = null
  notify(items.length)
}

function readDead() {
  return readStored(DEAD_KEY, [], 'Your offline review list could not be read. No saved action was removed.')
}

function writeDead(items) {
  writeStored(DEAD_KEY, items, 'A rejected offline action could not be saved for review. It remains in the sync queue.')
  issue = null
}

function secureUuid() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  if (globalThis.crypto?.getRandomValues) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  throw new OfflineQueueError('This browser cannot create a secure offline receipt. Please reconnect and try again.')
}

/** Create the full receipt envelope before the first network attempt. */
export function createMutation(now = new Date()) {
  const capturedAt = now.toISOString()
  return {
    mutation_id: secureUuid(),
    captured_at: capturedAt,
    effective_date: localDate(capturedAt),
  }
}

export function mutationHeaders(mutation, hasBody = false) {
  const headers = mutation
    ? {
        'X-ianOS-Mutation-Id': mutation.mutation_id,
        'X-ianOS-Captured-At': mutation.captured_at,
        'X-ianOS-Effective-Date': mutation.effective_date,
      }
    : {}
  if (hasBody) headers['Content-Type'] = 'application/json'
  return Object.keys(headers).length ? headers : undefined
}

export function pendingCount() {
  try {
    return read().length
  } catch {
    return 0
  }
}

export function deadLetters() {
  try {
    return readDead()
  } catch {
    return []
  }
}

export function queueIssue() {
  return issue
}

export function onQueueChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Queue a write that could not reach the Mac without minting a second id. */
export function enqueue(path, method, body, mutation = createMutation()) {
  const items = read()
  if (items.length >= MAX) {
    const message = 'Offline queue is full. Reconnect before saving another action.'
    issue = message
    notify(items.length)
    throw new OfflineQueueError(message)
  }
  if (!mutation?.mutation_id || !mutation?.captured_at || !mutation?.effective_date) {
    throw new OfflineQueueError('Offline action is missing its receipt identity. Please reconnect and try again.')
  }
  const item = {
    path,
    method,
    body,
    mutation_id: mutation.mutation_id,
    captured_at: mutation.captured_at,
    effective_date: mutation.effective_date,
  }
  write([...items, item])
  return item
}

export function lastSyncAt() {
  return localStorage.getItem(SYNC_KEY) || null
}

export function markSynced(iso) {
  try {
    localStorage.setItem(SYNC_KEY, iso || new Date().toISOString())
  } catch { /* a sync timestamp is informational, never a queue acknowledgement */ }
}

async function safeResponseDetail(res) {
  const body = await res.json().catch(() => null)
  const detail = body?.detail
  if (typeof detail === 'string' && detail.trim()) return detail.trim().slice(0, 240)
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg).slice(0, 240)
  return `Server rejected this action (${res.status}).`
}

async function moveToDeadLetter(item, res) {
  const detail = await safeResponseDetail(res)
  const dead = readDead()
  const record = {
    // The body can contain a Partner note. Terminal diagnostics need only the
    // safe server detail and enough receipt metadata to identify the event.
    mutation_id: item.mutation_id,
    path: item.path,
    method: item.method,
    captured_at: item.captured_at,
    effective_date: item.effective_date,
    status: res.status,
    detail,
    failed_at: new Date().toISOString(),
  }
  const existing = dead.findIndex((x) => x.mutation_id === item.mutation_id)
  if (existing < 0 && dead.length >= MAX_DEAD) {
    throw new OfflineQueueError('Offline review list is full. Dismiss a resolved entry before syncing another rejected action.')
  }
  const nextDead = existing >= 0
    ? dead.map((x, index) => (index === existing ? record : x))
    : [...dead, record]
  // Save the evidence first. If this fails, the live action stays queued.
  writeDead(nextDead)
  return record
}

function removeQueuedMutation(mutationId) {
  // Re-read after an awaited fetch. A tap can enqueue a second action while the
  // first is in flight; replacing the original snapshot would erase that tap.
  const current = read()
  const next = current.filter((entry) => entry?.mutation_id !== mutationId)
  if (next.length === current.length) return { items: current, removed: false }
  write(next)
  return { items: next, removed: true }
}

/** Remove a redacted terminal diagnostic only when Ian explicitly dismisses it. */
export function dismissDeadLetter(mutationId) {
  const dead = readDead()
  const next = dead.filter((entry) => entry.mutation_id !== mutationId)
  if (next.length === dead.length) return false
  writeDead(next)
  notify(pendingCount())
  return true
}

async function flushQueue() {
  let items = read()
  if (!items.length) return { sent: 0, dead: 0, remaining: 0, error: null }

  let sent = 0
  let dead = 0
  let error = null
  while (items.length) {
    const item = items[0]
    let res
    try {
      res = await fetch(item.path, {
        method: item.method,
        headers: mutationHeaders(item, item.body !== undefined),
        body: item.body === undefined ? undefined : JSON.stringify(item.body),
      })
    } catch {
      break // still offline: retain this and every later action in order
    }

    if (res.ok) {
      try {
        const acknowledged = removeQueuedMutation(item.mutation_id)
        items = acknowledged.items
      } catch (err) {
        error = err.message
        break // server has a receipt; retry is safe, but do not claim it was removed
      }
      sent += 1
      continue
    }

    if (TERMINAL_STATUSES.has(res.status)) {
      try {
        await moveToDeadLetter(item, res)
        const removed = removeQueuedMutation(item.mutation_id)
        dead += 1
        items = removed.items
      } catch (err) {
        error = err.message
        break
      }
      continue
    }

    break // 401/403/408/429/5xx may recover; retain the same mutation id
  }
  if (sent) markSynced()
  return { sent, dead, remaining: pendingCount(), error }
}

/** Oldest-first, serialized replay. Concurrent reconnect/visibility events
 * share one promise so they cannot send the first item twice in parallel. A
 * Web Lock extends that protection across browser tabs when the platform has
 * it; receipts remain the correctness backstop where Safari lacks Web Locks. */
export function flush() {
  if (!flushing) {
    const locks = globalThis.navigator?.locks
    const run = () => flushQueue()
    const work = locks?.request
      ? locks.request('ianos-offline-flush', { mode: 'exclusive' }, run)
      : run()
    flushing = work.finally(() => { flushing = null })
  }
  return flushing
}

/** Flush on reconnect or foregrounding. Returns { run, stop }. */
export function startAutoFlush(onFlushed) {
  const run = async () => {
    let result
    try {
      result = await flush()
    } catch (err) {
      result = { sent: 0, dead: 0, remaining: pendingCount(), error: err.message }
    }
    if (result.sent || result.dead || result.error) onFlushed?.(result)
    return result
  }
  const onVisible = () => {
    if (document.visibilityState === 'visible') run()
  }
  window.addEventListener('online', run)
  document.addEventListener('visibilitychange', onVisible)
  const stop = () => {
    window.removeEventListener('online', run)
    document.removeEventListener('visibilitychange', onVisible)
  }
  return { run, stop }
}
