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

import { CharacterPickerTrigger, SCHOOL_EXTENSIONS } from '../src/components/school-notes/schema.js'

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

/** Read `_NOTE_ALLOWED_ATTRS = {"node": frozenset({...}), ...}` out of core/school.py. */
function pythonAttrAllowlist() {
  const source = readFileSync(SCHOOL_PY, 'utf8')
  const match = source.match(/_NOTE_ALLOWED_ATTRS\s*=\s*\{([\s\S]*?)\n\}/)
  assert.ok(match, 'could not find _NOTE_ALLOWED_ATTRS in core/school.py')
  const allowed = new Map()
  for (const [, node, keys] of match[1].matchAll(/"([^"]+)":\s*frozenset\(\{([^}]*)\}\)/g)) {
    allowed.set(node, new Set([...keys.matchAll(/"([^"]+)"/g)].map((m) => m[1])))
  }
  return allowed
}

// Node and mark NAMES matching was not enough. Tiptap writes every attribute's
// default into every save, and orderedList's {start, type} were on no server
// list, so every numbered list 422'd from the day its button shipped until a
// real Cmd+Shift+. caught it (2026-09-10).
test('every attribute the editor gives a node is accepted by the server', () => {
  const allowed = pythonAttrAllowlist()
  const extra = []
  for (const [name, type] of Object.entries(schema.nodes)) {
    for (const key of Object.keys(type.spec.attrs || {})) {
      if (!allowed.get(name)?.has(key)) extra.push(`${name}.${key}`)
    }
  }
  assert.deepEqual(
    extra, [],
    `editor saves attribute(s) core/school.py rejects with 422: ${extra.join(', ')}`,
  )
})

test('a numbered list saves the attributes the server now accepts', () => {
  const list = schema.nodes.orderedList.createAndFill()
  assert.deepEqual(Object.keys(list.toJSON().attrs).sort(), ['start', 'type'])
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

// Ian, 2026-09-09: two shortcuts and a placeholder joined the extension list.
// None of them may widen what the editor can put in a document.
test('the placeholder and the shortcuts add no node and no mark', () => {
  const bare = getSchema([
    ...SCHOOL_EXTENSIONS.filter((e) => !['placeholder', 'schoolShortcuts'].includes(e.name)),
  ])
  assert.deepEqual(Object.keys(schema.nodes).sort(), Object.keys(bare.nodes).sort())
  assert.deepEqual(Object.keys(schema.marks).sort(), Object.keys(bare.marks).sort())
})

test('bullets are Cmd+. and Cmd+P is left to the browser', () => {
  const shortcuts = SCHOOL_EXTENSIONS.find((e) => e.name === 'schoolShortcuts')
  assert.ok(shortcuts, 'the shortcut extension is gone')
  // It has to outrank StarterKit: UndoRedo owns Mod-y and Bold owns Mod-b.
  assert.ok(shortcuts.config.priority > 100,
    'schoolShortcuts must outrank StarterKit or its keys never fire')
  const keys = Object.keys(shortcuts.config.addKeyboardShortcuts.call({ editor: null }))
  assert.deepEqual(keys.sort(), ['Mod-Shift-.', 'Mod-b', 'Mod-.'].sort())
  assert.ok(!keys.includes('Mod-p'), 'Cmd+P opened Print in real use; never bind it again')
})

// Ian, 2026-09-10: the Old Norse picker's key. It is added per editor, not in
// SCHOOL_EXTENSIONS, and it must widen nothing the editor can produce.
test('the character-picker shortcut adds no node and no mark', () => {
  const withTrigger = getSchema([...SCHOOL_EXTENSIONS, CharacterPickerTrigger])
  assert.deepEqual(Object.keys(withTrigger.nodes).sort(), Object.keys(schema.nodes).sort())
  assert.deepEqual(Object.keys(withTrigger.marks).sort(), Object.keys(schema.marks).sort())
})

test('Cmd+; falls through untouched unless the note has a character set', () => {
  const bind = (onTrigger) => CharacterPickerTrigger.config.addKeyboardShortcuts.call({ options: { onTrigger } })
  assert.deepEqual(Object.keys(bind(() => false)), ['Mod-;'])
  assert.equal(bind(() => false)['Mod-;'](), false, 'a course with no set must not swallow the key')
  assert.equal(bind(() => true)['Mod-;'](), true)
  assert.equal(CharacterPickerTrigger.config.addOptions().onTrigger(), false)
})
