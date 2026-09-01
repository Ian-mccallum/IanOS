/** Subtle journal sounds (SPEC-v11). Web Audio only, no asset files. */

let ctx = null

function audio() {
  if (typeof window === 'undefined') return null
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return null
  if (localStorage.getItem('journal-sound') === '0') return null
  try {
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)()
    if (ctx.state === 'suspended') ctx.resume()
    return ctx
  } catch {
    return null
  }
}

function tone({ freq = 180, freqEnd = 120, dur = 0.4, gain = 0.06, type = 'sine' }) {
  const c = audio()
  if (!c) return
  const t0 = c.currentTime
  const o = c.createOscillator()
  const g = c.createGain()
  o.type = type
  o.frequency.setValueAtTime(freq, t0)
  o.frequency.exponentialRampToValueAtTime(Math.max(freqEnd, 40), t0 + dur)
  g.gain.setValueAtTime(0.0001, t0)
  g.gain.exponentialRampToValueAtTime(gain, t0 + 0.03)
  g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur)
  o.connect(g)
  g.connect(c.destination)
  o.start(t0)
  o.stop(t0 + dur + 0.02)
}

export function playClose() {
  tone({ freq: 220, freqEnd: 110, dur: 0.45, gain: 0.07 })
}

export function playAttach() {
  tone({ freq: 880, freqEnd: 660, dur: 0.06, gain: 0.04, type: 'triangle' })
}

export function playUndo() {
  tone({ freq: 330, freqEnd: 440, dur: 0.12, gain: 0.05 })
}

export function soundEnabled() {
  return localStorage.getItem('journal-sound') !== '0'
}

export function setSoundEnabled(on) {
  localStorage.setItem('journal-sound', on ? '1' : '0')
}
