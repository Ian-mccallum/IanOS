// The detail route accepts only enough metadata to open a verified School
// session. Keeping this at the route boundary means note documents, Canvas
// identifiers/URLs, and arbitrary route payloads never land in sessionStorage.
export const SCHOOL_NOTEBOOK_INTENT_KEY = 'school-notebook-intent'

function positiveId(value) {
  const id = Number(value)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

export function schoolNotebookIntent(value) {
  if (!value || typeof value !== 'object') return null
  const courseCode = typeof value.courseCode === 'string'
    ? value.courseCode.trim().slice(0, 32)
    : ''
  const schoolItemId = positiveId(value.schoolItemId)
  const sessionId = positiveId(value.sessionId)
  if (!courseCode && !schoolItemId && !sessionId) return null
  return {
    ...(courseCode ? { courseCode } : {}),
    ...(schoolItemId ? { schoolItemId } : {}),
    ...(sessionId ? { sessionId } : {}),
  }
}

export function stashSchoolNotebookIntent(value, storage = sessionStorage) {
  const intent = schoolNotebookIntent(value)
  if (!intent) return false
  try {
    storage.setItem(SCHOOL_NOTEBOOK_INTENT_KEY, JSON.stringify(intent))
    return true
  } catch {
    return false
  }
}

export function takeSchoolNotebookIntent(storage = sessionStorage) {
  try {
    const raw = storage.getItem(SCHOOL_NOTEBOOK_INTENT_KEY)
    storage.removeItem(SCHOOL_NOTEBOOK_INTENT_KEY)
    return schoolNotebookIntent(raw ? JSON.parse(raw) : null)
  } catch {
    // Best effort routing should never strand the user on a blank notebook.
    try { storage.removeItem(SCHOOL_NOTEBOOK_INTENT_KEY) } catch { /* ignore */ }
    return null
  }
}

// Mirror of core/school.py's `_clean_text(title, 180)`, which every saved note
// title passes through server-side: collapse whitespace runs, then bound the
// length. The client has to normalize the SAME way before comparing its typed
// title against the one the server echoes back. It used to send a merely
// .trim()ed value, so a title with a double space never compared equal to the
// stored one, and each autosave fired a second redundant PATCH that bumped
// `revision` again (re-marking study aids STALE) until React caught up.
export const SCHOOL_NOTE_TITLE_MAX = 180

// JavaScript's String#slice counts UTF-16 code units, while the server's
// Python length limit counts Unicode code points. Array.from keeps the two
// sides in lockstep for emoji and other supplementary-plane characters.
export function truncateSchoolNoteTitle(value) {
  return Array.from(String(value ?? ''))
    .slice(0, SCHOOL_NOTE_TITLE_MAX)
    .join('')
}

export function normalizeSchoolNoteTitle(value) {
  return truncateSchoolNoteTitle(String(value ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' '))
}

// Async courses do not have lecture occurrences. Their smallest useful
// schedule unit is the local Monday-starting week, so all devices reopen the
// same workspace even when they begin work on different days.
export function schoolWeekStart(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return value
  const [year, month, day] = value.split('-').map(Number)
  const local = new Date(year, month - 1, day, 12)
  if (Number.isNaN(local.getTime())) return value
  local.setDate(local.getDate() - ((local.getDay() + 6) % 7))
  const startYear = local.getFullYear()
  const startMonth = String(local.getMonth() + 1).padStart(2, '0')
  const startDay = String(local.getDate()).padStart(2, '0')
  return `${startYear}-${startMonth}-${startDay}`
}
