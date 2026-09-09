/**
 * The School note editor's node/mark set, kept in its own module so a plain
 * `node --test` can build the real ProseMirror schema from it without pulling
 * in React (the same split `notes/schema.js` already uses).
 *
 * This list is one half of a contract. The other half is
 * `_NOTE_ALLOWED_NODES` / `_NOTE_ALLOWED_MARKS` in core/school.py, which the
 * server enforces on every write: a document containing anything outside that
 * allowlist is rejected with 422, and because the offending mark stays in the
 * editor, EVERY later autosave fails too. A note becomes permanently
 * unsaveable mid-lecture.
 *
 * `link: false` and `underline: false` are therefore load-bearing, not
 * tidiness. StarterKit 3.x bundles both; neither has a toolbar button here,
 * and both fire on their own -- Underline binds Mod-u, and Link's `autolink`
 * converts a typed URL on the next space. Deleting either flag reintroduces a
 * one-keystroke data-loss bug.
 *
 * Placeholder and SchoolShortcuts below are safe to add to this list because
 * neither declares a node or a mark: one draws a decoration, the other only
 * binds keys. Anything that DOES add a node or mark needs the Python
 * allowlist extended in the same commit.
 *
 * dashboard/tests/school-note-schema.test.mjs reads the Python allowlist and
 * fails if these two ever drift apart again.
 */
import { Extension } from '@tiptap/core'
import { Placeholder } from '@tiptap/extensions'
import StarterKit from '@tiptap/starter-kit'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'

export const NOTE_PLACEHOLDER = 'Start typing.'

/**
 * Cmd+B with nothing selected bolds the WHOLE LINE (Ian, 2026-09-09).
 *
 * The editor default only flips the stored mark at the caret, so pressing it
 * mid-sentence changed nothing visible and looked broken. With a selection
 * this is the ordinary toggle; with none it selects the text block, toggles,
 * and puts the caret back exactly where it was. On a genuinely empty line
 * there is nothing to bold, so it falls through to the stored-mark toggle and
 * the next thing typed comes out bold.
 */
function boldLineOrSelection(editor) {
  const { selection } = editor.state
  if (!selection.empty) return editor.chain().focus().toggleBold().run()
  const { $from } = selection
  const start = $from.start()
  const end = $from.end()
  if (start >= end) return editor.chain().focus().toggleBold().run()
  return editor.chain().focus()
    .setTextSelection({ from: start, to: end })
    .toggleBold()
    .setTextSelection($from.pos)
    .run()
}

/**
 * Keys that have to beat StarterKit's own bindings, hence the priority.
 *
 * Mod-p is the browser's Print. Returning true from a ProseMirror keymap
 * handler calls preventDefault, so the print dialog does not open while the
 * caret is in a note. Every plain Cmd+letter is claimed by the browser or the
 * OS; this app already takes Cmd+K for the palette, and printing a lecture
 * note is not something that happens here.
 */
const SchoolShortcuts = Extension.create({
  name: 'schoolShortcuts',
  priority: 1000,
  addKeyboardShortcuts() {
    return {
      'Mod-b': () => boldLineOrSelection(this.editor),
      'Mod-p': () => this.editor.chain().focus().toggleBulletList().run(),
      'Mod-Shift-p': () => this.editor.chain().focus().toggleOrderedList().run(),
    }
  },
})

export const SCHOOL_EXTENSIONS = [
  StarterKit.configure({ trailingNode: false, link: false, underline: false }),
  TaskList.configure({ HTMLAttributes: { class: 'school-note-task-list' } }),
  TaskItem.configure({ nested: true }),
  // A decoration, not a sibling element. The old placeholder was an
  // absolutely positioned <p> over the prose, so it only disappeared when
  // React happened to re-render and otherwise sat underneath what was being
  // typed. This one is part of the document's own render pass.
  Placeholder.configure({
    placeholder: NOTE_PLACEHOLDER,
    showOnlyWhenEditable: true,
    showOnlyCurrent: false,
  }),
  SchoolShortcuts,
]

export default SCHOOL_EXTENSIONS
