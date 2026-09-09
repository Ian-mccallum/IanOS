/**
 * The one star in the product (SPEC-v41 Life). Ian taps it on Life to put a
 * task on Command, and the same drawn mark identifies it when it lands there,
 * so the two surfaces read as one thing rather than two coincidences.
 *
 * Drawn, not a Unicode ★: a glyph inherits the text face's weight and sits on
 * the text baseline, which puts it off the row's optical center next to a
 * 22px ring.
 */
export default function StarMark({ on = false, size = 17, className = '' }) {
  return (
    <svg
      className={`starmark${className ? ` ${className}` : ''}`}
      viewBox="0 0 24 24" width={size} height={size} aria-hidden="true"
    >
      <path
        d="M12 3.6 L14.6 9.1 L20.5 9.9 L16.2 14.1 L17.3 20.1 L12 17.2 L6.7 20.1 L7.8 14.1 L3.5 9.9 L9.4 9.1 Z"
        fill={on ? 'currentColor' : 'none'}
        stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round"
      />
    </svg>
  )
}
