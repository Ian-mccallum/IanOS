import { createMutation, enqueue, markSynced, mutationHeaders } from './offline.js'

/** Gateway errors a reverse proxy returns when the machine behind it is down.
 *  Indistinguishable from "offline" as far as the phone is concerned. */
export const GATEWAY_DOWN = new Set([502, 503, 504])

/**
 * @param {object} [opts]
 * @param {boolean} [opts.queueable] Daily-capture writes (gym, activity, wellness)
 *   that are stamped to the DAY, not the second. If the Mac is unreachable these
 *   are stored locally and replayed on reconnect, and the call resolves with
 *   `{ queued: true, mutation_id }` instead of throwing. The receipt id lets
 *   reversible offline writes address the same archive batch. Interactive writes (goals, facts,
 *   proposals, leads) must NOT set this, they need a real server response.
 */
export async function api(path, method = 'GET', body, opts = {}) {
  // The identity is born before the FIRST attempt, not only after it fails.
  // A server commit followed by a dropped response therefore queues the same
  // mutation for safe receipt replay instead of a fresh counter increment.
  const mutation = opts.queueable && method !== 'GET' ? createMutation() : null
  let r
  const unreachable = () => {
    if (opts.queueable && method !== 'GET') {
      enqueue(path, method, body, mutation)
      return { queued: true, mutation_id: mutation.mutation_id }
    }
    throw new Error('offline. Your Mac is not reachable')
  }
  try {
    r = await fetch(path, {
      method,
      headers: mutationHeaders(mutation, body !== undefined),
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: opts.cache,
    })
  } catch {
    return unreachable()
  }
  // A tunnel in front of the Mac (Tailscale `serve`) stays up when the Mac does
  // not, so the fetch SUCCEEDS with a gateway error instead of rejecting. To
  // the phone that is simply offline, and without this, a gym tap made on a
  // sleeping Mac would throw a red error instead of queueing, and be lost.
  if (GATEWAY_DOWN.has(r.status)) return unreachable()
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail
    const msg = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : `${r.status}`
    throw new Error(msg || `${r.status}`)
  }
  if (method !== 'GET') markSynced()
  return r.json()
}

/**
 * Fetch dashboard state, reporting whether it came from the service-worker
 * cache (i.e. the Mac is asleep) and how old that snapshot is.
 * @returns {Promise<{state: object, cached: boolean, fetchedAt: string|null}>}
 */
export async function fetchState() {
  const r = await fetch('/api/state')
  if (!r.ok) throw new Error(`${r.status}`)
  const cached = r.headers.get('X-ianOS-Cached') === '1'
  const fetchedAt = r.headers.get('X-ianOS-Cached-At') || null
  const state = await r.json()
  if (!cached) markSynced()
  return { state, cached, fetchedAt }
}
