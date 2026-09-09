/**
 * The one poop in the product. Drawn, not the 💩 glyph, for the same reason
 * StarMark is drawn rather than ★: an emoji is a font, so it renders as
 * whatever face the OS ships, sits on the text baseline instead of the row's
 * optical center, and cannot take the app's own material (a flat Apple emoji
 * dropped on near-black glass reads as a sticker someone left behind).
 *
 * Three domes, each offset a little from the one below, plus a curl at the
 * tip. Eyes and mouth are optional so the same geometry serves the 96px tap
 * target, the 20px row marker, and the confetti coils that arc out of a tap.
 */
import { useId } from 'react'

export default function PoopMark({
  size = 48,
  face = true,
  blink = false,
  className = '',
  style,
}) {
  // One gradient id per instance: a tap paints several coils at once and
  // duplicate ids in one document are a url(#...) coin flip.
  const gradientId = `poopmark-body-${useId()}`
  return (
    <svg
      className={`poopmark${className ? ` ${className}` : ''}`}
      viewBox="0 0 48 48" width={size} height={size} style={style}
      aria-hidden="true" focusable="false"
    >
      <defs>
        {/* Lit from above, like every other surface in the app. */}
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--poop-lit)" />
          <stop offset="1" stopColor="var(--poop)" />
        </linearGradient>
      </defs>
      {/* Bottom tier first, so each tier's own outline draws over the fill of
          the one below it. That single line is what makes the stack read as
          three coils rather than one smooth pyramid, and it is why the tiers
          are drawn in this order rather than any other. */}
      <g fill={`url(#${gradientId})`} stroke="var(--poop-shade)" strokeWidth="0.9"
         strokeLinejoin="round">
        <path d="M2 44 C2 36.6 9.6 32.2 24 32.2 C38.4 32.2 46 36.6 46 44 Z" />
        <path d="M6.4 33.2 C6.4 27 12.8 23 24.6 23 C36.4 23 41.6 27 41.6 33.2 Z" />
        <path d="M12.8 23.8 C12.8 18.4 17.4 14.8 25.2 14.8 C33 14.8 36.8 18.4 36.8 23.8 Z" />
        <path d="M25.2 15.4 C23.6 11.6 26 8.2 30.4 7.8 C27.8 10 27.6 12.6 30 14.6 Z" />
      </g>
      {face && (
        <g className="poopmark-face">
          {blink ? (
            <>
              <path d="M18.4 28.6 h3.6" />
              <path d="M28 28.6 h3.6" />
            </>
          ) : (
            <>
              <circle cx="20.2" cy="28.4" r="1.9" />
              <circle cx="29.8" cy="28.4" r="1.9" />
            </>
          )}
          <path d="M19.4 37.2 C21.6 40.2 26.4 40.2 28.6 37.2" />
        </g>
      )}
    </svg>
  )
}
