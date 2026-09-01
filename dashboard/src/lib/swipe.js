/**
 * Horizontal swipe between pillars (SPEC-v10 §2.2).
 *
 * Three rules keep this from being annoying, and all three matter more than the
 * gesture itself:
 *
 *  1. **The edges belong to iOS.** A swipe starting within EDGE px of either
 *     side is ignored, so the system back/forward gesture still works inside an
 *     installed PWA. We take the middle, iOS keeps the rails.
 *  2. **Vertical intent wins.** The direction is judged once, on the first
 *     DECIDE px of travel. If the finger is moving more vertically than
 *     horizontally it is a scroll, forever, no mid-gesture switching.
 *  3. **Horizontal scrollers win.** If the touch started inside something that
 *     scrolls sideways (the Plan ribbon, a lead row), that element gets it.
 */

export const PILLAR_RING = [
  'home', 'plan', 'btc', 'body', 'partner', 'school', 'life', 'money',
]

const EDGE = 24      // px reserved for the iOS system gesture on each side
const DECIDE = 12    // px of travel before we commit to an axis
const DISTANCE = 60  // px required to count as a swipe…
const VELOCITY = 0.4 // …or px/ms, so a short flick still works

/**
 * True when the touch began somewhere that owns horizontal gestures itself : 
 * a sideways scroller (the Plan ribbon), or anything marked `data-swipe-own`
 * (a goal row with its own reveal). Without this, one drag would both reveal a
 * row's actions and navigate to another pillar.
 */
function startsInHorizontalScroller(target) {
  for (let el = target; el && el !== document.body; el = el.parentElement) {
    if (el.dataset && el.dataset.swipeOwn !== undefined) return true
    if (el.scrollWidth > el.clientWidth + 4) {
      const ox = getComputedStyle(el).overflowX
      if (ox === 'auto' || ox === 'scroll') return true
    }
  }
  return false
}

/**
 * @param {string} page current page id
 * @param {(id: string) => void} navigate
 * @param {boolean} enabled false inside committed modes (call, shutdown)
 * @returns touch handlers to spread onto the scrolling container
 */
export function pillarSwipeHandlers(page, navigate, enabled = true) {
  if (!enabled) return {}

  let x0 = 0, y0 = 0, t0 = 0
  let axis = null   // null = undecided, 'x' = ours, 'y' = the scroller's

  return {
    onTouchStart(e) {
      if (e.touches.length !== 1) { axis = 'y'; return }
      const t = e.touches[0]
      if (t.clientX < EDGE || t.clientX > window.innerWidth - EDGE) { axis = 'y'; return }
      if (startsInHorizontalScroller(e.target)) { axis = 'y'; return }
      x0 = t.clientX; y0 = t.clientY; t0 = e.timeStamp; axis = null
    },
    onTouchMove(e) {
      if (axis === 'y' || e.touches.length !== 1) return
      const dx = e.touches[0].clientX - x0
      const dy = e.touches[0].clientY - y0
      if (axis === null && Math.hypot(dx, dy) > DECIDE) {
        axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
      }
    },
    onTouchEnd(e) {
      if (axis !== 'x') { axis = null; return }
      axis = null
      const t = e.changedTouches[0]
      const dx = t.clientX - x0
      const dt = Math.max(1, e.timeStamp - t0)
      if (Math.abs(dx) < DISTANCE && Math.abs(dx) / dt < VELOCITY) return

      const i = PILLAR_RING.indexOf(page)
      if (i === -1) return                       // not a pillar; leave it alone
      // drag left (dx < 0) = move forward through the ring
      const forward = dx < 0
      const next = (i + (forward ? 1 : -1) + PILLAR_RING.length) % PILLAR_RING.length
      // Second arg is the direction the content should arrive FROM: drag left
      // and the next page comes in from the right. The animation finishes the
      // motion the thumb started, instead of contradicting it.
      navigate(PILLAR_RING[next], forward ? 1 : -1)
    },
    onTouchCancel() { axis = null },
  }
}
