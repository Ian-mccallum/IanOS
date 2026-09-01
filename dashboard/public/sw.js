/* ianOS service worker: makes the app open instantly with the Mac asleep.
 *
 * Strategy:
 *   navigation      → network-first, fall back to the cached shell (offline launch)
 *   GET /api/state  → network-first, fall back to the last good snapshot (~96 KB),
 *                     tagged with X-ianOS-Cached so the UI can say "as of ...".
 *   other GETs      → cache-first (hashed Vite assets, icons, fonts)
 *   writes (POST/…) → never touched; the app's offline queue owns them.
 */

const VERSION = 'ianos-v4'
const SHELL = `${VERSION}-shell`
const DATA = `${VERSION}-data`
const STATE_PATH = '/api/state'

// Injected at build time by scripts/inject-sw.mjs with the hashed Vite assets.
// This MUST be precached: on a first visit the JS/CSS load before the worker
// takes control, so they'd otherwise never be cached and an offline launch
// would render a blank page.
const BUILD_ASSETS = /*__PRECACHE__*/[]

// A reverse proxy in front of the Mac (Tailscale `serve`) stays up when the Mac
// itself is asleep. The request then SUCCEEDS with a gateway error rather than
// rejecting, so a plain .catch() never fires and the app is handed a 502 where
// it wanted its last-known snapshot. On the LAN this never showed up, a
// sleeping Mac just refused the connection.
const GATEWAY_DOWN = new Set([502, 503, 504])

/** Network-first with a cache fallback, counting a dead backend as offline. */
async function freshOr(request, onFresh, fallback) {
  try {
    const res = await fetch(request)
    if (GATEWAY_DOWN.has(res.status)) throw new Error('backend down')
    onFresh(res)
    return res
  } catch {
    return fallback()
  }
}

self.addEventListener('install', (e) => {
  const urls = ['/', '/manifest.webmanifest', '/icons/icon-192.png', ...BUILD_ASSETS]
  e.waitUntil(
    caches.open(SHELL)
      // addAll is all-or-nothing; cache individually so one bad URL can't
      // leave the app with no shell at all.
      .then((c) => Promise.all(urls.map((u) => c.add(u).catch(() => {}))))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)),
      ))
      .then(() => self.clients.claim()),
  )
})

/** Re-serve a cached response with headers telling the UI how stale it is. */
async function taggedFromCache(cached) {
  const body = await cached.blob()
  const headers = new Headers(cached.headers)
  headers.set('X-ianOS-Cached', '1')
  headers.set('X-ianOS-Cached-At', cached.headers.get('X-ianOS-Fetched-At') || '')
  return new Response(body, { status: 200, statusText: 'OK (cached)', headers })
}

/** Store a copy stamped with the time we actually fetched it. */
async function cacheStamped(cacheName, request, response) {
  const body = await response.clone().blob()
  const headers = new Headers(response.headers)
  headers.set('X-ianOS-Fetched-At', new Date().toISOString())
  const cache = await caches.open(cacheName)
  await cache.put(request, new Response(body, {
    status: response.status, statusText: response.statusText, headers,
  }))
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return          // writes: straight to the network

  const url = new URL(request.url)

  // The app shell, offline launch.
  if (request.mode === 'navigate') {
    event.respondWith(freshOr(
      request,
      (res) => cacheStamped(SHELL, '/', res),
      async () => (await caches.match('/')) || Response.error(),
    ))
    return
  }

  // The dashboard payload: fresh when we can, last-known when we can't.
  if (url.origin === self.location.origin && url.pathname === STATE_PATH) {
    event.respondWith(freshOr(
      request,
      (res) => { if (res.ok) cacheStamped(DATA, STATE_PATH, res) },
      async () => {
        const cached = await caches.match(STATE_PATH)
        return cached ? taggedFromCache(cached) : Response.error()
      },
    ))
    return
  }

  // Everything else that's cacheable: assets, icons, fonts.
  if (url.pathname.startsWith('/api/')) return
  event.respondWith(
    caches.match(request).then((hit) => hit || fetch(request).then((res) => {
      if (res.ok || res.type === 'opaque') {
        const copy = res.clone()
        caches.open(SHELL).then((c) => c.put(request, copy)).catch(() => {})
      }
      return res
    }).catch(() => Response.error())),
  )
})
