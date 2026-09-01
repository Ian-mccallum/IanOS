import assert from 'node:assert/strict'
import test from 'node:test'

import {
  SCHOOL_NOTEBOOK_INTENT_KEY,
  normalizeSchoolNoteTitle,
  truncateSchoolNoteTitle,
  schoolNotebookIntent,
  schoolWeekStart,
  stashSchoolNotebookIntent,
  takeSchoolNotebookIntent,
} from '../src/lib/school-notebook.js'

class MemoryStorage {
  constructor(seed = {}) { this.values = new Map(Object.entries(seed)) }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  removeItem(key) { this.values.delete(key) }
  setItem(key, value) { this.values.set(key, String(value)) }
}

test('School notebook handoff keeps only route metadata, never a note document', () => {
  // Arrange: Plan has a verified occurrence plus fields that must never be
  // used as a route payload or survive in browser storage.
  const storage = new MemoryStorage()
  const unsafe = {
    courseCode: ' STAT 120 ', schoolItemId: 854, calendarEventId: 420,
    document: { type: 'doc', content: [{ type: 'text', text: 'private' }] },
    canvas_url: 'https://canvas.example/secret',
  }

  // Act.
  const stored = stashSchoolNotebookIntent(unsafe, storage)
  const raw = storage.getItem(SCHOOL_NOTEBOOK_INTENT_KEY)

  // Assert.
  assert.equal(stored, true)
  assert.deepEqual(JSON.parse(raw), { courseCode: 'STAT 120', schoolItemId: 854 })
  assert.equal(raw.includes('private'), false)
  assert.equal(raw.includes('canvas'), false)
})

test('School notebook intent is one-time and malformed route data is harmless', () => {
  // Arrange: an intent should not hijack a later ordinary notebook visit.
  const storage = new MemoryStorage()
  stashSchoolNotebookIntent({ courseCode: 'ANTH 210' }, storage)

  // Act / Assert: consumption clears before parsing, including a bad record.
  assert.deepEqual(takeSchoolNotebookIntent(storage), { courseCode: 'ANTH 210' })
  assert.equal(takeSchoolNotebookIntent(storage), null)
  storage.setItem(SCHOOL_NOTEBOOK_INTENT_KEY, '{not json')
  assert.equal(takeSchoolNotebookIntent(storage), null)
  assert.equal(storage.getItem(SCHOOL_NOTEBOOK_INTENT_KEY), null)
})

test('only a usable course or positive School session identifier can navigate', () => {
  assert.equal(schoolNotebookIntent({}), null)
  assert.equal(schoolNotebookIntent({ schoolItemId: 0 }), null)
  assert.equal(schoolNotebookIntent({ sessionId: -4 }), null)
  assert.deepEqual(schoolNotebookIntent({ sessionId: '12' }), { sessionId: 12 })
})

test('an async course always reopens the Monday-starting workspace for its week', () => {
  assert.equal(schoolWeekStart('2026-08-24'), '2026-08-24') // Monday
  assert.equal(schoolWeekStart('2026-08-25'), '2026-08-24') // Tuesday
  assert.equal(schoolWeekStart('2026-08-30'), '2026-08-24') // Sunday
  assert.equal(schoolWeekStart('not-a-date'), 'not-a-date')
})

// --------------------------------------------------- title normalization
// The client must normalize a note title EXACTLY the way core/school.py's
// `_clean_text(title, 180)` does, because it compares its typed title against
// the one the server echoes back. When the two disagreed, a title containing a
// double space never compared equal, so every autosave fired a second
// redundant PATCH that bumped `revision` again and re-marked study aids STALE.
// Expected values below are the real output of `_clean_text(value, 180)`.
test('note title normalization matches the server character for character', () => {
  const cases = [
    ['Lecture  3', 'Lecture 3'],
    ['  padded  ', 'padded'],
    ['a\tb\nc', 'a b c'],
    ['multi   space   here', 'multi space here'],
    ['Normal title', 'Normal title'],
    ['', ''],
    ['   ', ''],
    ['x'.repeat(200), 'x'.repeat(180)],
  ]
  for (const [input, expected] of cases) {
    assert.equal(normalizeSchoolNoteTitle(input), expected,
      `normalizeSchoolNoteTitle(${JSON.stringify(input)}) must match _clean_text`)
  }
})

test('normalizing a title is idempotent, so a save can settle', () => {
  // If normalize(normalize(x)) !== normalize(x) the client and server could
  // ping-pong forever instead of converging after one PATCH.
  for (const value of ['Lecture  3', '  x  ', 'x'.repeat(200), 'a\t\tb']) {
    const once = normalizeSchoolNoteTitle(value)
    assert.equal(normalizeSchoolNoteTitle(once), once)
  }
})

test('null and undefined titles normalize to empty, never "null"', () => {
  assert.equal(normalizeSchoolNoteTitle(null), '')
  assert.equal(normalizeSchoolNoteTitle(undefined), '')
})

test('title limits count visible Unicode characters, never UTF-16 halves', () => {
  const emoji = '😀'
  assert.equal(truncateSchoolNoteTitle(emoji.repeat(200)), emoji.repeat(180))
  assert.equal(normalizeSchoolNoteTitle(emoji.repeat(200)), emoji.repeat(180))
  assert.equal(
    truncateSchoolNoteTitle(`${'x'.repeat(179)}${emoji}${emoji}`),
    `${'x'.repeat(179)}${emoji}`,
  )
  assert.equal(truncateSchoolNoteTitle('A  title'), 'A  title')
})
