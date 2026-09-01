import { api } from './api.js'

export const PLAID_ITEM_KEYS = Object.freeze(['chase', 'capital_one'])
export const PLAID_OAUTH_SESSION_KEY = 'ianos:plaid-link'
const PLAID_SCRIPT_URL = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js'

let loadPromise = null

function isItemKey(itemKey) {
  return PLAID_ITEM_KEYS.includes(itemKey)
}

function savedLink() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(PLAID_OAUTH_SESSION_KEY) || 'null')
    return parsed && isItemKey(parsed.itemKey) && typeof parsed.linkToken === 'string'
      ? parsed : null
  } catch {
    return null
  }
}

function clearSavedLink() {
  sessionStorage.removeItem(PLAID_OAUTH_SESSION_KEY)
}

function loadPlaid() {
  if (window.Plaid?.create) return Promise.resolve(window.Plaid)
  if (loadPromise) return loadPromise
  loadPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = PLAID_SCRIPT_URL
    script.async = true
    script.onload = () => window.Plaid?.create
      ? resolve(window.Plaid)
      : reject(new Error('Bank connection could not be loaded'))
    script.onerror = () => reject(new Error('Bank connection could not be loaded'))
    document.head.appendChild(script)
  })
  return loadPromise
}

function withoutOAuthState() {
  const url = new URL(window.location.href)
  url.searchParams.delete('oauth_state_id')
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
}

async function openLink({ itemKey, linkToken, receivedRedirectUri, onConnected, onError }) {
  const Plaid = await loadPlaid()
  const handler = Plaid.create({
    token: linkToken,
    ...(receivedRedirectUri ? { receivedRedirectUri } : {}),
    onSuccess: async (publicToken) => {
      try {
        await api(`/api/plaid/items/${itemKey}`, 'POST', { public_token: publicToken })
        const result = await api(`/api/plaid/items/${itemKey}/sync`, 'POST', {})
        clearSavedLink()
        if (receivedRedirectUri) withoutOAuthState()
        onConnected?.(itemKey, result)
      } catch {
        onError?.(new Error('Account connected, but ianOS could not sync it yet'))
      }
    },
    onExit: (error) => {
      // Plaid errors can name institutions or contain provider diagnostics;
      // keep client feedback useful without exposing that data in the UI.
      if (error) onError?.(new Error('Bank connection was not completed'))
    },
  })
  handler.open()
}

export async function startPlaidLink(itemKey, callbacks = {}) {
  if (!isItemKey(itemKey)) throw new Error('Unknown bank connection')
  const { link_token: linkToken } = await api(`/api/plaid/link-token/${itemKey}`, 'POST', {})
  if (typeof linkToken !== 'string' || !linkToken) throw new Error('Bank connection could not be started')
  sessionStorage.setItem(PLAID_OAUTH_SESSION_KEY, JSON.stringify({ itemKey, linkToken }))
  await openLink({ itemKey, linkToken, ...callbacks })
}

export async function resumePlaidLink(callbacks = {}) {
  if (!new URLSearchParams(window.location.search).get('oauth_state_id')) return false
  const saved = savedLink()
  if (!saved) return false
  try {
    await openLink({ ...saved, receivedRedirectUri: window.location.href, ...callbacks })
  } catch (error) {
    callbacks.onError?.(error)
  }
  return true
}
