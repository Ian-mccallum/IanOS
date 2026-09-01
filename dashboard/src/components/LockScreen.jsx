import React, { useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import {
  biometricLabel,
  enrollBiometric,
  hasBiometricCredential,
  unlockWithBiometric,
  unlockWithPassword,
  webauthnAvailable,
} from '../lib/lock.js'

/** Ian lives on Central; lock clock is always America/Chicago, 12-hour. */
const LOCK_TZ = 'America/Chicago'

const timeFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: LOCK_TZ,
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true,
})

const dateFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: LOCK_TZ,
  weekday: 'long',
  month: 'long',
  day: 'numeric',
})

function useClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

function centralStamp(now) {
  const parts = Object.fromEntries(
    timeFmt.formatToParts(now).filter((p) => p.type !== 'literal').map((p) => [p.type, p.value]),
  )
  return {
    hm: `${parts.hour}:${parts.minute}`,
    sec: parts.second,
    dayPeriod: (parts.dayPeriod || '').toUpperCase(),
    date: dateFmt.format(now),
  }
}

/**
 * Full-bleed unlock gate (SPEC-v12). One job: unlock.
 */
export default function LockScreen({ onUnlocked }) {
  const rm = useReducedMotion()
  const now = useClock()
  const stamp = useMemo(() => centralStamp(now), [now])
  const bio = biometricLabel()
  const canBio = webauthnAvailable()
  const enrolled = hasBiometricCredential()

  const [mode, setMode] = useState(() => (canBio && enrolled ? 'bio' : 'password'))
  // bio | password | offer-enroll
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    if (mode === 'password') {
      const id = requestAnimationFrame(() => inputRef.current?.focus())
      return () => cancelAnimationFrame(id)
    }
  }, [mode])

  const finish = () => {
    setError('')
    onUnlocked()
  }

  const afterPasswordOk = async () => {
    if (canBio && !hasBiometricCredential()) {
      setMode('offer-enroll')
      setBusy(false)
      return
    }
    finish()
  }

  const onBio = async () => {
    setBusy(true)
    setError('')
    const r = await unlockWithBiometric()
    setBusy(false)
    if (r.ok) finish()
    else setError(r.error || 'Try again')
  }

  const onPassword = async (e) => {
    e?.preventDefault?.()
    setBusy(true)
    setError('')
    const r = await unlockWithPassword(password)
    if (!r.ok) {
      setBusy(false)
      setError(r.error || 'Wrong password')
      setPassword('')
      inputRef.current?.focus()
      return
    }
    setPassword('')
    await afterPasswordOk()
  }

  const onEnroll = async () => {
    setBusy(true)
    setError('')
    const r = await enrollBiometric()
    setBusy(false)
    if (r.ok) finish()
    else setError(r.error || 'Could not enable')
  }

  const skipEnroll = () => finish()

  return (
    <div className="lock-screen" role="dialog" aria-modal="true" aria-label="Unlock ianOS">
      <motion.div
        className="lock-inner"
        initial={rm ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      >
        <img
          className="lock-logo"
          src="/logo-lockup.png"
          alt=""
          width="640"
          height="306"
          decoding="async"
        />

        <div className="lock-timeblock" aria-hidden="true">
          <div className="lock-clock">
            <span className="lock-clock-hm">{stamp.hm}</span>
            <span className="lock-clock-s">{stamp.sec}</span>
            <span className="lock-clock-ampm">{stamp.dayPeriod}</span>
          </div>
          <p className="lock-date">{stamp.date}</p>
        </div>

        {mode === 'offer-enroll' ? (
          <div className="lock-actions">
            <p className="lock-prompt">Enable {bio} for next time?</p>
            {error && <p className="lock-error" role="alert">{error}</p>}
            <button
              type="button"
              className="lock-primary"
              disabled={busy}
              onClick={onEnroll}
            >
              {busy ? 'Waiting…' : `Enable ${bio}`}
            </button>
            <button type="button" className="lock-secondary" disabled={busy} onClick={skipEnroll}>
              Not now
            </button>
          </div>
        ) : mode === 'password' ? (
          <form className="lock-actions" onSubmit={onPassword}>
            <label className="lock-label" htmlFor="lock-pass">Password</label>
            <input
              ref={inputRef}
              id="lock-pass"
              className="lock-input"
              type="password"
              name="password"
              autoComplete="current-password"
              enterKeyHint="done"
              value={password}
              disabled={busy}
              onChange={(e) => { setPassword(e.target.value); setError('') }}
            />
            {error && <p className="lock-error" role="alert">{error}</p>}
            <button type="submit" className="lock-primary" disabled={busy || !password}>
              {busy ? '…' : 'Unlock'}
            </button>
            {canBio && enrolled && (
              <button
                type="button"
                className="lock-secondary"
                disabled={busy}
                onClick={() => { setMode('bio'); setError(''); setPassword('') }}
              >
                Use {bio}
              </button>
            )}
          </form>
        ) : (
          <div className="lock-actions">
            {error && <p className="lock-error" role="alert">{error}</p>}
            <button
              type="button"
              className="lock-primary"
              disabled={busy}
              onClick={onBio}
            >
              {busy ? 'Waiting…' : bio}
            </button>
            <button
              type="button"
              className="lock-secondary"
              disabled={busy}
              onClick={() => { setMode('password'); setError('') }}
            >
              Use password
            </button>
          </div>
        )}
      </motion.div>
    </div>
  )
}
