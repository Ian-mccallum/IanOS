import React, { useEffect, useRef } from 'react'

const BLOBS = [
  { color: [45, 120, 255], x: 0.22, y: 0.35, r: 0.42, speed: 0.00018, phase: 0 },
  { color: [120, 60, 255], x: 0.78, y: 0.28, r: 0.38, speed: 0.00014, phase: 1.8 },
  { color: [20, 200, 180], x: 0.55, y: 0.72, r: 0.34, speed: 0.00016, phase: 3.2 },
  { color: [255, 90, 160], x: 0.12, y: 0.78, r: 0.28, speed: 0.00012, phase: 5.1 },
]

function drawGrid(ctx, w, h, t) {
  const spacing = 48
  const offset = (t * 0.012) % spacing
  ctx.strokeStyle = 'rgba(120, 160, 255, 0.06)'
  ctx.lineWidth = 1
  for (let x = -spacing; x < w + spacing; x += spacing) {
    ctx.beginPath()
    ctx.moveTo(x + offset, 0)
    ctx.lineTo(x + offset - h * 0.35, h)
    ctx.stroke()
  }
  for (let y = -spacing; y < h + spacing; y += spacing) {
    ctx.beginPath()
    ctx.moveTo(0, y + offset * 0.5)
    ctx.lineTo(w, y + offset * 0.5)
    ctx.stroke()
  }
}

function drawParticles(ctx, w, h, t, particles) {
  for (const p of particles) {
    p.x += p.vx
    p.y += p.vy
    if (p.x < 0) p.x = w
    if (p.x > w) p.x = 0
    if (p.y < 0) p.y = h
    if (p.y > h) p.y = 0
    const pulse = 0.35 + 0.25 * Math.sin(t * 0.001 + p.phase)
    ctx.beginPath()
    ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
    ctx.fillStyle = `rgba(180, 210, 255, ${pulse * p.alpha})`
    ctx.fill()
  }
}

// SPEC-v9: `bloom` is a counter. Increment it and the aurora swells once : 
// the milestone reward for The Line, in ianOS's own visual language rather than
// a confetti library. Quiet enough to fire at 11pm without feeling like a slot
// machine. Under prefers-reduced-motion the RAF loop never runs, so no bloom.
const BLOOM_MS = 1200

export default function AuroraBackground({ bloom = 0 }) {
  const canvasRef = useRef(null)
  const particlesRef = useRef(null)
  const bloomRef = useRef({ at: -Infinity, seen: 0 })

  useEffect(() => {
    if (bloom > bloomRef.current.seen) {
      bloomRef.current = { at: performance.now(), seen: bloom }
    }
  }, [bloom])

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let frame = 0
    let raf = 0

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = window.innerWidth * dpr
      canvas.height = window.innerHeight * dpr
      canvas.style.width = `${window.innerWidth}px`
      canvas.style.height = `${window.innerHeight}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    if (!particlesRef.current) {
      particlesRef.current = Array.from({ length: 42 }, (_, i) => ({
        x: Math.random() * window.innerWidth,
        y: Math.random() * window.innerHeight,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.12,
        size: Math.random() * 1.2 + 0.4,
        alpha: Math.random() * 0.5 + 0.15,
        phase: i * 0.7,
      }))
    }

    resize()
    window.addEventListener('resize', resize)

    const paint = (time) => {
      const w = window.innerWidth
      const h = window.innerHeight
      ctx.fillStyle = '#04050a'
      ctx.fillRect(0, 0, w, h)

      drawGrid(ctx, w, h, reduced ? 0 : time)

      for (const blob of BLOBS) {
        const bx = (blob.x + Math.sin(time * blob.speed + blob.phase) * 0.08) * w
        const by = (blob.y + Math.cos(time * blob.speed * 1.3 + blob.phase) * 0.06) * h
        const radius = blob.r * Math.max(w, h)
        const grad = ctx.createRadialGradient(bx, by, 0, bx, by, radius)
        const [r, g, b] = blob.color
        grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.22)`)
        grad.addColorStop(0.45, `rgba(${r}, ${g}, ${b}, 0.08)`)
        grad.addColorStop(1, 'rgba(0, 0, 0, 0)')
        ctx.fillStyle = grad
        ctx.fillRect(0, 0, w, h)
      }

      if (!reduced) drawParticles(ctx, w, h, time, particlesRef.current)

      const sinceBloom = time - bloomRef.current.at
      if (!reduced && sinceBloom >= 0 && sinceBloom < BLOOM_MS) {
        // one slow swell, eased out: never a flash
        const k = Math.sin((1 - sinceBloom / BLOOM_MS) * Math.PI * 0.5)
        const bg = ctx.createRadialGradient(w / 2, h * 0.55, 0, w / 2, h * 0.55, Math.max(w, h) * 0.9)
        bg.addColorStop(0, `rgba(110, 168, 255, ${0.3 * k})`)
        bg.addColorStop(0.5, `rgba(110, 168, 255, ${0.12 * k})`)
        bg.addColorStop(1, 'rgba(0, 0, 0, 0)')
        ctx.fillStyle = bg
        ctx.fillRect(0, 0, w, h)
      }

      const vignette = ctx.createRadialGradient(w / 2, h / 2, h * 0.2, w / 2, h / 2, h * 0.85)
      vignette.addColorStop(0, 'rgba(0,0,0,0)')
      vignette.addColorStop(1, 'rgba(0,0,0,0.55)')
      ctx.fillStyle = vignette
      ctx.fillRect(0, 0, w, h)

      // Backgrounded (locked, tab-switched) or reduced motion: paint this
      // frame and stop, rather than spending GPU/battery on an invisible
      // canvas for the ~20 opens/day this PWA gets.
      if (!reduced && !document.hidden) {
        frame++
        raf = requestAnimationFrame(paint)
      }
    }

    const onVisibility = () => {
      if (!document.hidden && !reduced) {
        cancelAnimationFrame(raf)
        raf = requestAnimationFrame(paint)
      }
    }

    paint(0)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', onVisibility)
      cancelAnimationFrame(raf)
    }
  }, [])

  return <canvas className="aurora-canvas" ref={canvasRef} aria-hidden="true" />
}
