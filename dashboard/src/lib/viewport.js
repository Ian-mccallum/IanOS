/** iOS standalone PWA viewport fix (WebKit #254868).
 *
 * In an installed Home Screen app, 100dvh / innerHeight / -webkit-fill-available
 * are SHORT by ~safe-area-inset-top (~59px on Dynamic Island phones). That
 * shortfall shows up as a black band under the tab bar. 100vh / screen.height
 * are correct from cold start.
 *
 * Browser Safari still needs 100dvh (URL bar). Split: CSS defaults to 100dvh;
 * this module + an index.html bootstrap set --app-height: 100vh when standalone.
 *
 * Do NOT use @media (display-mode: standalone) alone - it is unreliable on iOS.
 * Prefer navigator.standalone.
 */

function isStandalone() {
  return window.navigator.standalone === true
    || window.matchMedia('(display-mode: standalone)').matches
    || window.matchMedia('(display-mode: fullscreen)').matches
}

function applyAppHeight() {
  const root = document.documentElement
  if (isStandalone()) {
    // Full physical screen. Never sync from visualViewport/innerHeight here -
    // those lie on cold start and would reintroduce the gap.
    root.style.setProperty('--app-height', '100vh')
    root.dataset.ianosStandalone = '1'
  } else {
    root.style.setProperty('--app-height', '100dvh')
    delete root.dataset.ianosStandalone
  }
}

/* Keyboard inset (SPEC-v26). The tab bar is position:fixed, which anchors to
 * the LAYOUT viewport. An on-screen keyboard shrinks only the VISUAL viewport
 * on iOS, so without this the bar sits behind the keyboard and reads as
 * "not truly fixed" the moment you type. index.html asks for
 * interactive-widget=resizes-content, which fixes it natively where supported;
 * this measures the same inset everywhere else.
 *
 * This deliberately does NOT touch --app-height: that value is load-bearing
 * for the standalone cold-start gap and must never be synced from
 * visualViewport (see applyAppHeight above). The inset is a separate variable
 * the shell subtracts, and it stays 0px unless a keyboard is really up.
 */
const KEYBOARD_MIN_PX = 80

function applyKeyboardInset() {
  const vv = window.visualViewport
  const root = document.documentElement
  if (!vv) return
  const hidden = Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
  // Below the threshold this is browser chrome (collapsing URL bar), not a
  // keyboard. Treating that as a keyboard would jitter the whole shell.
  const inset = hidden > KEYBOARD_MIN_PX ? Math.round(hidden) : 0
  root.style.setProperty('--kb', `${inset}px`)
  root.dataset.ianosKeyboard = inset > 0 ? '1' : '0'
}

/** Install. Safe to call once from main.jsx (bootstrap in index.html runs first). */
export function installNavFlush() {
  if (typeof window === 'undefined') return () => {}
  const run = () => {
    try { applyAppHeight() } catch { /* non-fatal */ }
    try { applyKeyboardInset() } catch { /* non-fatal */ }
  }
  run()
  window.addEventListener('resize', run)
  window.addEventListener('orientationchange', run)
  document.addEventListener('visibilitychange', run)
  const vv = window.visualViewport
  if (vv) {
    vv.addEventListener('resize', run)
    vv.addEventListener('scroll', run)
  }
  // Cold-start sometimes settles after a tick.
  const timers = [50, 200, 600].map((ms) => window.setTimeout(run, ms))
  return () => {
    timers.forEach((t) => window.clearTimeout(t))
    window.removeEventListener('resize', run)
    window.removeEventListener('orientationchange', run)
    document.removeEventListener('visibilitychange', run)
    if (vv) {
      vv.removeEventListener('resize', run)
      vv.removeEventListener('scroll', run)
    }
  }
}
