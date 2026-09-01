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
 * dashboard/tests/school-note-schema.test.mjs reads the Python allowlist and
 * fails if these two ever drift apart again.
 */
import StarterKit from '@tiptap/starter-kit'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'

export const SCHOOL_EXTENSIONS = [
  StarterKit.configure({ trailingNode: false, link: false, underline: false }),
  TaskList.configure({ HTMLAttributes: { class: 'school-note-task-list' } }),
  TaskItem.configure({ nested: true }),
]

export default SCHOOL_EXTENSIONS
