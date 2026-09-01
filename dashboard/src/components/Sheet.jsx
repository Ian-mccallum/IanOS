import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, useReducedMotion } from 'motion/react'
import { useFocusTrap } from '../lib/useFocusTrap.js'

const POPOVER_MARGIN = 8
// Below this width every variant renders as the phone bottom sheet (CSS
// handles the layout itself); only the popover branch needs to know the
// breakpoint in JS, to decide whether its anchor-relative math applies at
// all or whether to defer entirely to the mobile bottom-sheet CSS below.
const POPOVER_DESKTOP_MIN = 901

// How many mounted Sheet instances currently have open=true. Module-scoped
// (not component state) because every Sheet consumer across the app shares
// one document.body, and two sheets can briefly overlap (e.g. a sheet opened
// from inside another sheet's content). A plain classList.toggle keyed to a
// single instance's `open` would let sheet B's close wipe the class while
// sheet A is still open; the counter only clears it at zero.
let openSheetCount = 0

// `anchor` is either a React ref ({ current: HTMLElement | null }) or an
// already-resolved DOMRect-like object. A ref has a `current` key, a plain
// rect does not, so that's what tells the two apart.
function resolveAnchorRect(anchor) {
  if (!anchor) return null
  if (typeof anchor === 'object' && 'current' in anchor) {
    return anchor.current ? anchor.current.getBoundingClientRect() : null
  }
  return anchor
}

/**
 * One Sheet primitive for popover / drawer / dialog content weights
 * (SPEC-v29 Phase 3). Structural template borrowed from AskAgentSheet.jsx:
 * portal to document.body, useFocusTrap, a real Escape listener, backdrop-tap
 * closes, internal scroll on content only. Wired into AskAgentSheet.jsx,
 * AccountSheet.jsx, PlanPage.jsx's block editor, Nav.jsx's More sheet, and
 * AgentChat.jsx's Context/Reasoning/FileDraft sheets.
 */
export default function Sheet({
  open,
  onClose,
  title = '',
  variant = 'dialog',
  tone = 'neutral',
  anchor = null,
  // Optional override for the destructive control's text label. Defaults to
  // the safe reading ("Cancel") rather than the spec's other example
  // ("Delete"): onClose is the one callback backdrop-tap, Escape, and this
  // control all share, so the default must never look like it confirms an
  // irreversible action. A caller whose destructive sheet really is a
  // single-control delete (no separate confirm step) can pass
  // dismissLabel="Delete" deliberately.
  dismissLabel = '',
  className = '',
  children,
}) {
  const containerRef = useRef(null)
  const panelRef = useRef(null)
  const titleId = useId()
  const reduced = useReducedMotion()
  const [popoverPos, setPopoverPos] = useState(null)

  useFocusTrap(open, containerRef)

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  // The panel below fades in by animating element-level opacity (motion's
  // `initial={{opacity:0}} animate={{opacity:1}}`), which multiplies through
  // everything painted in the panel's own stacking context, including its
  // own near-opaque background. For the ~200ms of that transition the panel
  // is genuinely translucent as a whole, so .nav-mobile's lower z-index (it
  // sits correctly behind sheet-wrap the entire time) still shows through
  // underneath, because "behind" doesn't help when the thing in front is
  // partly see-through. Rather than trust z-index + opacity stacking to
  // never let that peek through, make the tab bar's hidden state explicit
  // and independent of it: every Sheet marks the body for as long as it is
  // open, and the CSS hides .nav-mobile unconditionally while that's set,
  // mirroring how call-mode/journal-mode already mirror their flag onto
  // document.body for this same portaled-outside-.app-shell element (see
  // the useEffect in App.jsx that toggles call-mode/journal-mode).
  useEffect(() => {
    if (!open) return undefined
    openSheetCount += 1
    document.body.classList.add('sheet-open')
    return () => {
      openSheetCount = Math.max(0, openSheetCount - 1)
      if (openSheetCount === 0) document.body.classList.remove('sheet-open')
    }
  }, [open])

  // Popover positioning: anchored under/above the trigger on desktop, left
  // alone entirely on phone where CSS alone turns it into the same bottom
  // sheet every other variant uses (`Sheet.jsx` never branches variant
  // structure in JS by breakpoint, only the popover's anchor math needs to
  // know when it does not apply).
  useLayoutEffect(() => {
    if (!open || variant !== 'popover') { setPopoverPos(null); return undefined }
    const panel = panelRef.current
    if (!panel) return undefined

    const reposition = () => {
      if (window.innerWidth < POPOVER_DESKTOP_MIN) { setPopoverPos(null); return }
      const rect = resolveAnchorRect(anchor)
      const panelRect = panel.getBoundingClientRect()
      const vw = window.innerWidth
      const vh = window.innerHeight
      let top
      let left
      if (rect) {
        top = rect.bottom + POPOVER_MARGIN
        left = rect.left
        // Flip above the anchor when there is not enough room below.
        if (top + panelRect.height > vh - POPOVER_MARGIN
          && rect.top - panelRect.height - POPOVER_MARGIN > POPOVER_MARGIN) {
          top = rect.top - panelRect.height - POPOVER_MARGIN
        }
        // Clamp horizontally so the panel never runs off either edge.
        if (left + panelRect.width > vw - POPOVER_MARGIN) left = vw - panelRect.width - POPOVER_MARGIN
        if (left < POPOVER_MARGIN) left = POPOVER_MARGIN
      } else {
        // No anchor given: a reasonable default, centered near the top of
        // the viewport rather than dead center of the screen.
        top = POPOVER_MARGIN + 64
        left = Math.max(POPOVER_MARGIN, (vw - panelRect.width) / 2)
      }
      setPopoverPos({ top, left })
    }

    reposition()
    window.addEventListener('resize', reposition)
    // A popover's own content can change shape after it opens without any of
    // this effect's own deps changing -- NoteFolderSheet.jsx swapping its
    // internal 'list' view for a wider 'form' view is exactly this case. The
    // first reposition() clamps correctly against the content measured at
    // that moment; without also watching the panel's own box, a later resize
    // of the SAME panel (not the window) never re-triggers the clamp, and a
    // form that grew wider than the initial popover can render partly off
    // the right edge of the viewport, its own Save control unreachable.
    const ro = new ResizeObserver(reposition)
    ro.observe(panel)
    return () => { window.removeEventListener('resize', reposition); ro.disconnect() }
  }, [open, anchor, variant])

  if (!open) return null

  const destructive = tone === 'destructive'
  const closeText = destructive ? (dismissLabel || 'Cancel') : ''
  const closeAriaLabel = destructive
    ? closeText
    : (title ? `Close ${title}` : 'Close')
  const panelStyle = variant === 'popover' && popoverPos
    ? { top: popoverPos.top, left: popoverPos.left }
    : undefined

  return createPortal(
    <div
      ref={containerRef}
      className={`sheet-wrap sheet-wrap--${variant}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? titleId : undefined}
      aria-label={title ? undefined : 'Sheet'}
      data-swipe-own=""
    >
      <button
        type="button"
        className="sheet-backdrop"
        onClick={onClose}
        aria-label={title ? `Close ${title}` : 'Close'}
      />
      <motion.section
        ref={panelRef}
        className={className ? `sheet-panel ${className}` : 'sheet-panel'}
        style={panelStyle}
        initial={reduced ? false : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduced ? 0 : 0.2, ease: [0.22, 1, 0.36, 1] }}
      >
        <header className="sheet-head">
          <div>{title ? <h2 id={titleId}>{title}</h2> : null}</div>
          <button
            type="button"
            className={destructive ? 'sheet-close sheet-close--destructive' : 'sheet-close'}
            onClick={onClose}
            aria-label={closeAriaLabel}
          >
            {destructive ? closeText : <span aria-hidden="true">×</span>}
          </button>
        </header>
        <div className="sheet-body">{children}</div>
      </motion.section>
    </div>,
    document.body,
  )
}
