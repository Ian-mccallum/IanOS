/* Bake the hashed Vite asset names into the service worker's precache list.
 *
 * Without this the first offline launch is a blank screen: on a first visit the
 * JS/CSS are requested before the service worker takes control, so they never
 * pass through its fetch handler and never land in the cache.
 *
 * Runs automatically after `vite build` (see package.json).
 */
import { readdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const dist = join(root, 'dist')
const swPath = join(dist, 'sw.js')

if (!existsSync(swPath)) {
  console.error('inject-sw: dist/sw.js not found, did vite build run?')
  process.exit(1)
}

const assets = existsSync(join(dist, 'assets'))
  ? readdirSync(join(dist, 'assets')).map((f) => `/assets/${f}`)
  : []
const icons = existsSync(join(dist, 'icons'))
  ? readdirSync(join(dist, 'icons')).map((f) => `/icons/${f}`)
  : []
const brand = ['/logo-lockup.png', '/logo.png', '/ianOS.jpg'].filter((p) =>
  existsSync(join(dist, p.slice(1))),
)
const urls = [...assets, ...icons, ...brand]

const sw = readFileSync(swPath, 'utf8')
if (!sw.includes('/*__PRECACHE__*/')) {
  console.error('inject-sw: placeholder /*__PRECACHE__*/ missing from sw.js')
  process.exit(1)
}
writeFileSync(swPath, sw.replace('/*__PRECACHE__*/[]', JSON.stringify(urls)))
console.log(`inject-sw: precaching ${urls.length} files for offline launch`)
