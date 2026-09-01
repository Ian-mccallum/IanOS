/**
 * SPEC-v31's one binding wire-format contract: the Markdown <-> ProseMirror
 * translation in src/components/notes/markdown.js, plus the schema in
 * schema.js that keeps unrepresentable documents out of it.
 *
 * This file exists because it did not. A single Tab keystroke inside a
 * bullet list nested the item, and the serializer -- which read only the
 * FIRST paragraph child of a list item -- dropped the nested text on the
 * floor. The note saved without it and the editor still said "Saved".
 * Nothing here imports React, so `node --test` runs it directly.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { getSchema } from '@tiptap/core'
import { sinkListItem } from '@tiptap/pm/schema-list'
import { EditorState, TextSelection } from '@tiptap/pm/state'

import { parseNoteMarkdown, serializeNoteDoc, parseInline } from '../src/components/notes/markdown.js'
import { EXTENSIONS, FlatListItem } from '../src/components/notes/schema.js'
import { isUploadableImage } from '../src/components/notes/attachments.js'

const roundTrip = (md) => serializeNoteDoc(parseNoteMarkdown(md))

// ------------------------------------------------------------ round trips

test('the six constructs round-trip exactly', () => {
  const md = [
    'Heading line',
    '- bullet one',
    '- bullet two',
    '1. num one',
    '2. num two',
    '- [ ] task one',
    '- [x] task two',
    'plain **bold** and *italic* words',
    '![passport scan](note-image:84664c29)',
  ].join('\n')
  assert.equal(roundTrip(md), md)
})

test('a plain-text note is byte-identical, blank lines included', () => {
  const md = 'Things to buy:\n\nWhite t\n\n\ntrailing'
  assert.equal(roundTrip(md), md)
})

test('the round trip is idempotent', () => {
  const md = '- a\n- b\n1. one\n- [x] done\n![](note-image:deadbeef)'
  assert.equal(roundTrip(roundTrip(md)), roundTrip(md))
})

test('an empty body stays empty', () => {
  assert.equal(roundTrip(''), '')
  assert.equal(serializeNoteDoc(null), '')
})

test('numbered lists renumber from 1 by position, digits are not stored', () => {
  assert.equal(roundTrip('7. seven\n9. nine'), '1. seven\n2. nine')
})

test('an unpaired asterisk is literal text, never an open italic', () => {
  assert.equal(roundTrip('3 * 4 = 12'), '3 * 4 = 12')
  assert.deepEqual(parseInline('3 * 4 = 12'), [{ type: 'text', text: '3 * 4 = 12' }])
})

test('an image embed keeps its caption and its token', () => {
  const nodes = parseInline('![a cat](note-image:ab12cd34)')
  assert.equal(nodes.length, 1)
  assert.equal(nodes[0].type, 'noteImage')
  assert.equal(nodes[0].attrs.token, 'ab12cd34')
  assert.equal(nodes[0].attrs.caption, 'a cat')
})

// -------------------------------------------- the serializer loses nothing

test('a nested sublist is flattened, never dropped', () => {
  const doc = {
    type: 'doc',
    content: [{
      type: 'bulletList',
      content: [{
        type: 'listItem',
        content: [
          { type: 'paragraph', content: [{ type: 'text', text: 'a' }] },
          {
            type: 'bulletList',
            content: [{
              type: 'listItem',
              content: [{ type: 'paragraph', content: [{ type: 'text', text: 'b' }] }],
            }],
          },
        ],
      }],
    }],
  }
  assert.equal(serializeNoteDoc(doc), '- a\n- b')
})

test('a second paragraph in one list item is flattened, never dropped', () => {
  const doc = {
    type: 'doc',
    content: [{
      type: 'orderedList',
      content: [{
        type: 'listItem',
        content: [
          { type: 'paragraph', content: [{ type: 'text', text: 'first' }] },
          { type: 'paragraph', content: [{ type: 'text', text: 'second' }] },
        ],
      }],
    }],
  }
  assert.equal(serializeNoteDoc(doc), '1. first\n2. second')
})

test('extra lines in a task item inherit that item\'s checkbox', () => {
  const doc = {
    type: 'doc',
    content: [{
      type: 'taskList',
      content: [{
        type: 'taskItem',
        attrs: { checked: true },
        content: [
          { type: 'paragraph', content: [{ type: 'text', text: 'one' }] },
          { type: 'paragraph', content: [{ type: 'text', text: 'two' }] },
        ],
      }],
    }],
  }
  assert.equal(serializeNoteDoc(doc), '- [x] one\n- [x] two')
})

// ----------------------------------------------------- the schema is a wall

test('a list item holds exactly one paragraph, so nesting cannot exist', () => {
  const schema = getSchema(EXTENSIONS)
  assert.equal(schema.nodes.listItem.spec.content, 'paragraph')
})

test('sinkListItem cannot produce a valid document, so nesting is unreachable', () => {
  const schema = getSchema(EXTENSIONS)
  const doc = schema.nodeFromJSON(parseNoteMarkdown('- a\n- b'))

  // The caret inside the second bullet -- exactly where Tab was pressed in
  // the live app when "bullet two" disappeared.
  let caret = null
  doc.descendants((node, pos) => {
    if (node.type.name === 'text' && node.text === 'b') caret = pos
    return caret === null
  })
  assert.notEqual(caret, null, 'the fixture should contain the text "b"')

  let state = EditorState.create({ schema, doc })
  state = state.apply(state.tr.setSelection(TextSelection.create(doc, caret)))

  // ProseMirror builds the step before consulting the schema, so this is a
  // throw rather than a `false`. Either way the transform is rejected and
  // the document is untouched, which is the property that matters.
  assert.throws(
    () => sinkListItem(schema.nodes.listItem)(state, (tr) => { state = state.apply(tr) }),
    /Invalid content for node listItem/,
  )
  assert.equal(serializeNoteDoc(state.doc.toJSON()), '- a\n- b')
})

// ---------------------------------------------------- the upload whitelist

test('an image whose MIME the OS reports as empty is still uploadable', () => {
  // The picker is accept="image/*", so a file arriving here with a blank
  // type was dropped and the button looked like it simply did nothing.
  assert.equal(isUploadableImage({ name: 'IMG_0042.HEIC', type: '' }), true)
  assert.equal(isUploadableImage({ name: 'shot.png', type: '' }), true)
  assert.equal(isUploadableImage({ name: 'anything', type: 'image/png' }), true)
})

test('a non-image is still rejected before the round trip', () => {
  assert.equal(isUploadableImage({ name: 'lease.pdf', type: 'application/pdf' }), false)
  assert.equal(isUploadableImage({ name: 'notes', type: '' }), false)
  assert.equal(isUploadableImage(null), false)
})

test('Tab is unbound from sinkListItem, so the keystroke cannot throw', () => {
  const shortcuts = FlatListItem.config.addKeyboardShortcuts.call({
    name: 'listItem',
    parent: () => ({
      Enter: () => true,
      Tab: () => { throw new Error('sinkListItem must not be reachable from Tab') },
      'Shift-Tab': () => true,
    }),
  })
  assert.equal(shortcuts.Tab(), false)
  // Shift-Tab (lift out of the list) and Enter (split the item) still work.
  assert.equal(shortcuts['Shift-Tab'](), true)
  assert.equal(shortcuts.Enter(), true)
})
