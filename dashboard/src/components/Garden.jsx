import React from 'react'
import { motion, useReducedMotion } from 'motion/react'

// The Garden, a living plant grown purely from Ian's last 14 days.
// Never a guilt object: it wilts (droops + desaturates) but NEVER dies, shows
// no number and no label, and uses zero red. stage 1..5, mood thriving|steady|thirsty.

const LEAF = 'var(--health)'   // teal, the body pillar color
const STEM = '#3f8f7f'
const SOIL = 'rgba(140, 180, 255, 0.10)'

// Which leaves/branches exist at each stage (progressive reveal).
const STAGE_PARTS = {
  1: ['sprout'],
  2: ['sprout', 'l1'],
  3: ['sprout', 'l1', 'r1'],
  4: ['sprout', 'l1', 'r1', 'l2'],
  5: ['sprout', 'l1', 'r1', 'l2', 'r2', 'bud'],
}

export default function Garden({ stage = 1, mood = 'steady', spark = false }) {
  const rm = useReducedMotion()
  const parts = new Set(STAGE_PARTS[Math.max(1, Math.min(5, stage))])
  const thirsty = mood === 'thirsty'
  const thriving = mood === 'thriving'

  // Wilt = slight droop + desaturation (a CSS filter), never a color change.
  const wrapStyle = thirsty ? { filter: 'saturate(0.55) brightness(0.9)' } : undefined
  const droop = thirsty ? 6 : 0

  const sway = thriving && !rm
    ? { rotate: [-1.5, 1.5, -1.5] }
    : {}
  const swayT = { duration: 4.5, repeat: Infinity, ease: 'easeInOut' }

  const leaf = (id, d, cx, cy, extraDroop = 0) =>
    parts.has(id) && (
      <motion.path
        key={id}
        d={d}
        fill={LEAF}
        initial={rm ? false : { scale: 0, opacity: 0 }}
        animate={{ scale: 1, opacity: 1, y: droop + extraDroop }}
        transition={{ type: 'spring', stiffness: 200, damping: 18 }}
        style={{ originX: `${cx}px`, originY: `${cy}px` }}
      />
    )

  return (
    <div className="garden" aria-hidden="true" style={wrapStyle}>
      <svg viewBox="0 0 120 120" width="150" height="150" role="img">
        {/* soil line */}
        <ellipse cx="60" cy="108" rx="34" ry="6" fill={SOIL} />
        <motion.g animate={sway} transition={swayT} style={{ originX: '60px', originY: '108px' }}>
          {/* stem: height grows with stage */}
          <motion.path
            d={`M60 108 C 58 ${100 - stage * 8}, 62 ${96 - stage * 9}, 60 ${92 - stage * 10}`}
            stroke={STEM} strokeWidth="3" fill="none" strokeLinecap="round"
            initial={rm ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
          />
          {/* sprout tip */}
          {parts.has('sprout') && (
            <motion.circle cx="60" cy={90 - stage * 10} r="4" fill={LEAF}
              initial={rm ? false : { scale: 0 }} animate={{ scale: 1 }}
              transition={{ type: 'spring', stiffness: 220, damping: 16 }} />
          )}
          {/* leaves fan out as stages increase */}
          {leaf('l1', 'M60 84 C 44 80, 40 66, 54 68 C 58 72, 60 80, 60 84 Z', 60, 80)}
          {leaf('r1', 'M60 82 C 76 78, 80 64, 66 66 C 62 70, 60 78, 60 82 Z', 60, 78)}
          {leaf('l2', 'M60 70 C 42 64, 38 50, 53 53 C 58 58, 60 66, 60 70 Z', 60, 66, 2)}
          {leaf('r2', 'M60 66 C 78 60, 82 46, 67 49 C 62 54, 60 62, 60 66 Z', 60, 62, 2)}
          {/* the bud (stage 5), a small flower */}
          {parts.has('bud') && (
            <motion.g initial={rm ? false : { scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ delay: 0.3, type: 'spring', stiffness: 200, damping: 15 }}>
              <circle cx="60" cy={40} r="6" fill="var(--personal)" opacity="0.85" />
              <circle cx="60" cy={40} r="2.5" fill="#fce7f3" />
            </motion.g>
          )}
        </motion.g>
        {/* spark: one firefly on a 14-day best, fires once */}
        {spark && !rm && (
          <motion.circle r="2" fill="#fce7f3"
            initial={{ opacity: 0, cx: 60, cy: 90 }}
            animate={{ opacity: [0, 1, 0], cx: [60, 78, 88], cy: [90, 60, 44] }}
            transition={{ duration: 2.2, ease: 'easeOut' }} />
        )}
      </svg>
    </div>
  )
}
