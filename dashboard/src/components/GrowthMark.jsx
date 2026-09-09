import { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'

export const GROWTH_STAGE_THRESHOLDS = [0, 1, 3, 6, 9, 12]

export function growthStage(count) {
  let stage = 1
  for (let i = 1; i < GROWTH_STAGE_THRESHOLDS.length; i++) {
    if (count >= GROWTH_STAGE_THRESHOLDS[i]) stage = i + 1
  }
  return Math.min(stage, 5)
}

const STAGE_PATHS = {
  1: 'M12 20 L12 16',
  2: 'M12 20 L12 13 M12 13 L9 10',
  3: 'M12 20 L12 10 M12 13 L9 10 M12 13 L15 10',
  4: 'M12 20 L12 7 M12 12 L8 9 M12 12 L16 9 M12 8 L9 5',
  5: 'M12 20 L12 4 M12 11 L7 8 M12 11 L17 8 M12 7 L8 4 M12 7 L16 4',
}

export default function GrowthMark({ count = 0 }) {
  const stage = growthStage(count)
  const reduced = useReducedMotion()
  const prevStage = useRef(stage)
  const [pop, setPop] = useState(false)

  useEffect(() => {
    if (stage > prevStage.current) {
      setPop(true)
      const t = setTimeout(() => setPop(false), 320)
      prevStage.current = stage
      return () => clearTimeout(t)
    }
    prevStage.current = stage
  }, [stage])

  return (
    <motion.svg
      className="growth-mark"
      viewBox="0 0 24 24" width="20" height="20"
      animate={pop && !reduced ? { scale: [1, 1.22, 1] } : { scale: 1 }}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      aria-hidden="true"
    >
      <path d={STAGE_PATHS[stage]} stroke="var(--health)" strokeWidth="1.6"
            strokeLinecap="round" fill="none" />
    </motion.svg>
  )
}
