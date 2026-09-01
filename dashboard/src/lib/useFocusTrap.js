import { useEffect, useRef } from 'react'

// :not([tabindex="-1"]) has to be combined onto EVERY branch, not left as its
// own catch-all clause: `button:not([disabled])` alone still matches a
// button that has tabIndex={-1}, since tabindex isn't disqualifying for that
// selector on its own. CommandPalette's result buttons (tabIndex={-1}, so
// only the input is a real Tab stop) were slipping through this exact gap.
const FOCUSABLE = 'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), '
  + 'input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), '
  + 'textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])'

/**
 * Traps Tab/Shift+Tab inside containerRef while a dialog is open, and
 * restores focus to whatever was focused before it opened once it closes
 * (SPEC-v14 W5). Desktop-native gap: the command palette and the Plan sheet
 * are role="dialog" surfaces a keyboard user could previously Tab straight
 * through, into the nav-rail or page content behind the still-visible
 * overlay, with no way back to where they started.
 */
export function useFocusTrap(active, containerRef) {
  const restoreRef = useRef(null)

  useEffect(() => {
    if (!active) return undefined
    restoreRef.current = document.activeElement

    const onKeyDown = (e) => {
      if (e.key !== 'Tab' || !containerRef.current) return
      const focusable = [...containerRef.current.querySelectorAll(FOCUSABLE)]
        .filter((el) => el.offsetParent !== null)
      if (!focusable.length) { e.preventDefault(); return }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      restoreRef.current?.focus?.()
    }
  }, [active, containerRef])
}
