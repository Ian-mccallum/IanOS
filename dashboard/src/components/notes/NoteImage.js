import { Node, mergeAttributes } from '@tiptap/core'

/**
 * Inline atomic image node for SPEC-v31's closed note grammar: the only
 * markdown an image can ever be is `![caption](note-image:TOKEN)` (see
 * core/db.py's _NOTE_IMAGE_RE / _strip_foreign_note_image -- any other image
 * target is stripped server-side on save, so this node never needs to
 * render, parse, or accept anything else).
 *
 * The rendered <img> always points at GET /api/notes/attachments/{token},
 * never at a client-supplied URL: `token` is the only thing this node's
 * markdown embed carries, resolved server-side. width/height are NOT part
 * of the markdown wire format (see markdown.js) -- they live only in this
 * node's in-memory attrs, set once at insert time from the upload
 * response, purely so a freshly-inserted image can reserve its layout box
 * immediately. Re-opening a note from saved markdown starts those attrs at
 * null (the server has no per-note "list attachments" endpoint to refetch
 * them from in this pass), so the browser sizes those images naturally
 * once loaded -- a real but narrow gap, not a bug in this component.
 */
export const NoteImage = Node.create({
  name: 'noteImage',
  group: 'inline',
  inline: true,
  atom: true,
  selectable: true,
  draggable: false,

  addAttributes() {
    return {
      token: { default: null },
      caption: { default: '' },
      width: { default: null },
      height: { default: null },
    }
  },

  parseHTML() {
    return [{ tag: 'img[data-note-image-token]' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    const { token, caption, width, height } = node.attrs
    const attrs = {
      'data-note-image-token': token || '',
      src: token ? `/api/notes/attachments/${token}` : '',
      alt: caption || '',
      loading: 'lazy',
      class: 'note-rte-image',
    }
    if (width && height) {
      attrs.width = width
      attrs.height = height
      attrs.style = `aspect-ratio: ${width} / ${height};`
    }
    return ['img', mergeAttributes(HTMLAttributes, attrs)]
  },
})

export default NoteImage
