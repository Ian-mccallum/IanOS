/**
 * Client-side lock gate (SPEC-v12).
 * WebAuthn platform authenticator (Face ID / Touch ID) + password fallback.
 * Not network auth. LAN token still gates the API.
 */

const CRED_KEY = 'ianos.lock.cred.v1'
const SESSION_KEY = 'ianos.lock.session.v1'
const HIDDEN_AT_KEY = 'ianos.lock.hiddenAt.v1'
/** Re-lock after this long in the background (ms). Brief switches stay open. */
export const BG_RELOCK_MS = 90_000

const PASS_PREFIX = 'ianos.lock.v1|'
/** SHA-256 hex of PASS_PREFIX + the manual unlock secret (see SPEC-v12). */
const PASS_HASH =
  '54f90600aff32dfe600f53c9cb98ccbe7b41fc35a918578c0e8ee89700e5cca1'

function b64url(buf) {
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : buf
  let s = ''
  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i])
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function fromB64url(s) {
  const pad = '='.repeat((4 - (s.length % 4)) % 4)
  const b64 = (s + pad).replace(/-/g, '+').replace(/_/g, '/')
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}

function randomChallenge(len = 32) {
  const buf = new Uint8Array(len)
  crypto.getRandomValues(buf)
  return buf.buffer
}

async function sha256Hex(text) {
  const data = new TextEncoder().encode(text)
  const dig = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(dig)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

export function isSecureLockContext() {
  return typeof window !== 'undefined' && window.isSecureContext === true
}

export function webauthnAvailable() {
  return (
    isSecureLockContext()
    && typeof window !== 'undefined'
    && !!window.PublicKeyCredential
    && typeof navigator.credentials?.create === 'function'
    && typeof navigator.credentials?.get === 'function'
  )
}

/** Best-effort label for the platform authenticator. */
export function biometricLabel() {
  if (typeof navigator === 'undefined') return 'Biometrics'
  const ua = navigator.userAgent || ''
  // iPhone / iPad → Face ID. Mac with Touch ID still says Touch ID.
  if (/iPhone|iPad|iPod/.test(ua)) return 'Face ID'
  if (/Macintosh|Mac OS X/.test(ua)) return 'Touch ID'
  return 'Biometrics'
}

export function hasBiometricCredential() {
  try {
    return Boolean(localStorage.getItem(CRED_KEY))
  } catch {
    return false
  }
}

export function getCredentialId() {
  try {
    return localStorage.getItem(CRED_KEY)
  } catch {
    return null
  }
}

function storeCredentialId(idB64) {
  localStorage.setItem(CRED_KEY, idB64)
}

export function clearBiometricCredential() {
  try {
    localStorage.removeItem(CRED_KEY)
  } catch { /* ignore */ }
}

export function isUnlocked() {
  try {
    return sessionStorage.getItem(SESSION_KEY) === '1'
  } catch {
    return false
  }
}

export function markUnlocked() {
  try {
    sessionStorage.setItem(SESSION_KEY, '1')
    sessionStorage.removeItem(HIDDEN_AT_KEY)
  } catch { /* ignore */ }
}

export function lockNow() {
  try {
    sessionStorage.removeItem(SESSION_KEY)
    sessionStorage.removeItem(HIDDEN_AT_KEY)
  } catch { /* ignore */ }
}

export async function unlockWithPassword(password) {
  const hex = await sha256Hex(PASS_PREFIX + String(password ?? ''))
  if (hex !== PASS_HASH) return { ok: false, error: 'Wrong password' }
  markUnlocked()
  return { ok: true }
}

export async function enrollBiometric() {
  if (!webauthnAvailable()) {
    return { ok: false, error: 'Biometrics need HTTPS (Tailscale) or localhost' }
  }
  const userId = new TextEncoder().encode('ian-ianos-lock-v1')
  const publicKey = {
    challenge: randomChallenge(),
    rp: {
      name: 'ianOS',
      id: window.location.hostname,
    },
    user: {
      id: userId,
      name: 'ian',
      displayName: 'Ian',
    },
    pubKeyCredParams: [
      { type: 'public-key', alg: -7 },   // ES256
      { type: 'public-key', alg: -257 }, // RS256
    ],
    authenticatorSelection: {
      authenticatorAttachment: 'platform',
      residentKey: 'preferred',
      requireResidentKey: false,
      userVerification: 'required',
    },
    timeout: 60_000,
    attestation: 'none',
  }
  try {
    const cred = await navigator.credentials.create({ publicKey })
    if (!cred || !('rawId' in cred)) {
      return { ok: false, error: 'Enrollment cancelled' }
    }
    storeCredentialId(b64url(cred.rawId))
    return { ok: true }
  } catch (e) {
    const name = e?.name || ''
    if (name === 'NotAllowedError') return { ok: false, error: 'Cancelled' }
    if (name === 'InvalidStateError') {
      // Already enrolled at OS level for this rp; try to recover id if we lost it.
      return { ok: false, error: 'Already set up on this device. Try Face ID unlock.' }
    }
    return { ok: false, error: e?.message || 'Could not enable biometrics' }
  }
}

export async function unlockWithBiometric() {
  if (!webauthnAvailable()) {
    return { ok: false, error: 'Biometrics need HTTPS (Tailscale) or localhost' }
  }
  const id = getCredentialId()
  if (!id) return { ok: false, error: 'Face ID not set up yet' }

  const publicKey = {
    challenge: randomChallenge(),
    rpId: window.location.hostname,
    allowCredentials: [
      { type: 'public-key', id: fromB64url(id), transports: ['internal'] },
    ],
    userVerification: 'required',
    timeout: 60_000,
  }
  try {
    const assertion = await navigator.credentials.get({ publicKey })
    if (!assertion) return { ok: false, error: 'Cancelled' }
    markUnlocked()
    return { ok: true }
  } catch (e) {
    const name = e?.name || ''
    if (name === 'NotAllowedError') return { ok: false, error: 'Cancelled or failed' }
    return { ok: false, error: e?.message || 'Biometrics failed' }
  }
}

/**
 * Watch visibility. After BG_RELOCK_MS hidden, call onRelock().
 * Returns a cleanup function.
 */
export function attachRelockListeners(onRelock) {
  const onVis = () => {
    try {
      if (document.visibilityState === 'hidden') {
        sessionStorage.setItem(HIDDEN_AT_KEY, String(Date.now()))
        return
      }
      const raw = sessionStorage.getItem(HIDDEN_AT_KEY)
      sessionStorage.removeItem(HIDDEN_AT_KEY)
      if (!raw) return
      const hiddenFor = Date.now() - Number(raw)
      if (hiddenFor >= BG_RELOCK_MS && isUnlocked()) {
        lockNow()
        onRelock()
      }
    } catch { /* ignore */ }
  }
  document.addEventListener('visibilitychange', onVis)
  return () => document.removeEventListener('visibilitychange', onVis)
}
