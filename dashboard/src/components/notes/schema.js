import StarterKit from '@tiptap/starter-kit'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import { ListItem } from '@tiptap/extension-list'
import { NoteImage } from './NoteImage.js'

/**
 * The Tiptap node set behind SPEC-v31's note editor, kept in its own module
 * (rather than inline in NoteEditor.jsx) so it can be built and asserted in
 * a plain node test: `getSchema(EXTENSIONS)` needs no React and no DOM. The
 * schema IS the wall that keeps unrepresentable documents out of the wire
 * format, so it is worth a test, and a .jsx file cannot have one here.
 *
 * The toolbar offers exactly six things because the grammar has exactly six
 * node kinds (core/db.py's sanitize_note_body): Bold, Italic, Bulleted
 * list, Numbered list, Checklist, Insert image. Nothing else is reachable,
 * even though StarterKit ships headings/blockquotes/strike/etc by default --
 * seeing a toolbar option whose result silently disappears on the next save
 * would be a broken UX, so those extensions are explicitly turned off, not
 * merely hidden.
 */

/**
 * One list item = one source line, so a list item holds exactly one
 * paragraph. Stock ListItem is `content: "paragraph block*"` and binds
 * Tab to sinkListItem, which made a nested sublist reachable by a single
 * keystroke -- a shape this wire format has no line for, and which the
 * serializer used to drop on the floor (the text vanished, silently, and
 * the editor still said "Saved").
 *
 * Narrowing the schema is the wall: a nested sublist is not a document this
 * editor can hold, so a paste is renormalized by ProseMirror's own parser
 * instead of being accepted and then silently dropped on save.
 *
 * Unbinding Tab is the second half, and it is not redundant. ProseMirror's
 * sinkListItem does not check the schema before building its step: it
 * returns true and throws "Invalid content for node listItem" out of the
 * keymap handler. The transaction is rejected (the wall holds, no text is
 * lost) but the user gets an uncaught error on an ordinary keystroke.
 * Returning false instead lets Tab do what Tab does everywhere else and
 * move focus. Shift-Tab is left alone: lifting a top-level item out of the
 * list is exactly what it already did before this narrowing.
 */
export const FlatListItem = ListItem.extend({
  content: 'paragraph',
  addKeyboardShortcuts() {
    return {
      ...this.parent?.(),
      Tab: () => false,
    }
  },
})

export const EXTENSIONS = [
  StarterKit.configure({
    // Turned OFF: not part of the six-construct grammar, and StarterKit
    // would otherwise make each of these reachable by a markdown input
    // rule (typing "# " autoconverts to a heading, etc) even with no
    // toolbar button for it, which is exactly the "vanishes on reload"
    // trap this spec calls out by name.
    heading: false,
    blockquote: false,
    codeBlock: false,
    code: false,
    horizontalRule: false,
    strike: false,
    underline: false,
    link: false,
    // One source line = one paragraph node (see markdown.js). A soft break
    // inside a single paragraph has no representation in this grammar, so
    // Enter always starts a new line rather than a <br> mid-paragraph.
    hardBreak: false,
    // Tiptap's TrailingNode plugin silently appends an empty paragraph
    // after certain trailing block types (e.g. a note ending in a list)
    // the moment ANY edit happens, which would inject a blank line into
    // the saved markdown the user never typed. Off, to keep the round
    // trip exact.
    trailingNode: false,
    // Replaced by FlatListItem below, under the same `listItem` node name,
    // so StarterKit's own BulletList/OrderedList (content: "listItem+")
    // still resolve against it.
    listItem: false,
  }),
  FlatListItem,
  TaskList.configure({ HTMLAttributes: { class: 'note-rte-task-list' } }),
  TaskItem.configure({ nested: false }),
  NoteImage,
]

export default EXTENSIONS
