/**
 * The School note editor and core/school.py's document validator are two
 * halves of one contract, and nothing checked they agreed.
 *
 * They did not. Tiptap 3's StarterKit silently bundles Underline (bound to
 * Mod-u) and Link (`autolink: true`), neither of which is in the server's
 * `_NOTE_ALLOWED_MARKS`. Pressing Cmd+U, or typing a URL and hitting space,
 * put a mark in the document that the server rejected with 422 -- and since
 * the mark stayed in the editor, every autosave after it failed too. The note
 * became permanently unsaveable mid-lecture, with no toolbar button to remove
 * the formatting that caused it.
 *
 * This test builds the REAL ProseMirror schema from the editor's own
 * extension list and diffs it against the allowlist parsed out of
 * core/school.py, so the failure is a red test instead of lost class notes.
 * Nothing here imports React, so `node --test` runs it directly.
 */
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { getSchema } from '@tiptap/core'

import { SCHOOL_EXTENSIONS } from '../src/components/school-notes/schema.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const SCHOOL_PY = resolve(HERE, '../../core/school.py')

/** Read one `frozenset({...})` literal out of core/school.py. */
function pythonAllowlist(name) {
  const source = readFileSync(SCHOOL_PY, 'utf8')
  const match = source.match(new RegExp(`${name}\\s*=\\s*frozenset\\(\\{([\\s\\S]*?)\\}\\)`))
  assert.ok(match, `could not find ${name} in core/school.py`)
  return new Set([...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]))
}

const schema = getSchema(SCHOOL_EXTENSIONS)
const editorNodes = new Set(Object.keys(schema.nodes))
const editorMarks = new Set(Object.keys(schema.marks))

test('every node the editor can emit is accepted by the server', () => {
  const allowed = pythonAllowlist('_NOTE_ALLOWED_NODES')
  const extra = [...editorNodes].filter((name) => !allowed.has(name))
  assert.deepEqual(
    extra, [],
    `editor can produce node(s) core/school.py rejects with 422: ${extra.join(', ')}`,
  )
})

test('every mark the editor can emit is accepted by the server', () => {
  const allowed = pythonAllowlist('_NOTE_ALLOWED_MARKS')
  const extra = [...editorMarks].filter((name) => !allowed.has(name))
  assert.deepEqual(
    extra, [],
    `editor can produce mark(s) core/school.py rejects with 422: ${extra.join(', ')}`,
  )
})

// The two that actually shipped broken. Named individually so a regression
// says what it broke rather than only that a set diff is non-empty.
test('underline stays disabled: Mod-u must not be able to break a note', () => {
  assert.ok(!editorMarks.has('underline'),
    'StarterKit re-enabled Underline; Cmd+U will 422 every save for that note')
})

test('link stays disabled: autolink must not be able to break a note', () => {
  assert.ok(!editorMarks.has('link'),
    'StarterKit re-enabled Link; typing a URL will 422 every save for that note')
})

// The toolbar advertises these, so losing one silently is its own bug.
test('the editor still supports everything its toolbar offers', () => {
  for (const node of ['heading', 'bulletList', 'orderedList', 'taskList',
                      'taskItem', 'blockquote', 'codeBlock', 'horizontalRule']) {
    assert.ok(editorNodes.has(node), `toolbar offers ${node} but the schema lost it`)
  }
  for (const mark of ['bold', 'italic', 'strike', 'code']) {
    assert.ok(editorMarks.has(mark), `toolbar offers ${mark} but the schema lost it`)
  }
})
