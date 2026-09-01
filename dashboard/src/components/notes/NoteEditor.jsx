import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import Sheet from '../Sheet.jsx'
import { EXTENSIONS } from './schema.js'
import { parseNoteMarkdown, serializeNoteDoc } from './markdown.js'
import { uploadNoteAttachment, isUploadableImage } from './attachments.js'

/**
 * Touch-first WYSIWYG editor for SPEC-v31's closed note-body grammar. Public
 * contract, exactly as the spec requires: `value` (a Markdown string in
 * that grammar) in, `onChange(newMarkdown)` out. This component owns ALL
 * translation between Tiptap's document state and the wire format --
 * NotesPage.jsx (a later stage) PATCHes the string this hands it straight
 * to /api/notes/{id}, exactly as it does today with the plain textarea.
 *
 * The toolbar offers exactly six things because the grammar has exactly six
 * node kinds (core/db.py's sanitize_note_body). The node set that enforces
 * that lives in schema.js, so a plain node test can build and assert it.
 */

function ToolbarButton({ label, glyph, active, disabled, onClick }) {
  return (
    <button
      type="button"
      className={`note-rte-btn${active ? ' is-active' : ''}`}
      aria-label={label}
      aria-pressed={active || undefined}
      title={label}
      disabled={disabled}
      // Toolbar taps must not steal focus/selection from the editor before
      // the command runs (a plain button click otherwise blurs the
      // contentEditable first, so toggling bold would apply to nothing).
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
    >
      {glyph}
    </button>
  )
}

export default function NoteEditor({
  value,
  onChange,
  noteId = null,
  autoFocus = false,
  toast = null,
  placeholder = 'Start writing…',
}) {
  const [viewer, setViewer] = useState(null) // { token, caption } | null
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)
  const noteIdRef = useRef(noteId)
  const toastRef = useRef(toast)
  const lastEmittedRef = useRef(value)

  useEffect(() => { noteIdRef.current = noteId }, [noteId])
  useEffect(() => { toastRef.current = toast }, [toast])

  const notifyError = useCallback((msg) => {
    const t = toastRef.current
    if (t) t(msg, 'crit')
    else console.error('[NoteEditor]', msg) // eslint-disable-line no-console
  }, [])

  const editor = useEditor({
    extensions: EXTENSIONS,
    content: parseNoteMarkdown(value),
    autofocus: false,
    editorProps: {
      attributes: {
        class: 'note-rte-prose',
        'aria-label': 'Note body',
        autocorrect: 'on',
        autocapitalize: 'sentences',
        spellcheck: 'true',
      },
      // Desktop-only enhancement layer (osui: "desktop is the
      // enhancement," never the only path) -- the picker button above is
      // the phone-first primary path for every platform, iOS included.
      handleDrop(view, event, _slice, moved) {
        if (moved) return false // internal drag-reorder, not a file drop
        const files = Array.from(event.dataTransfer?.files || []).filter(isUploadableImage)
        if (!files.length) return false
        event.preventDefault()
        const id = noteIdRef.current
        if (!id) { notifyError('save the note before adding an image'); return true }
        const coords = view.posAtCoords({ left: event.clientX, top: event.clientY })
        let cursor = coords?.pos ?? view.state.selection.to;
        (async () => {
          for (const file of files) {
            try {
              setUploading(true)
              const att = await uploadNoteAttachment(id, file)
              const node = view.state.schema.nodes.noteImage.create({
                token: att.token, caption: '', width: att.width, height: att.height,
              })
              view.dispatch(view.state.tr.insert(cursor, node))
              cursor += node.nodeSize
            } catch (e) {
              notifyError(e?.message || 'image upload failed')
            } finally {
              setUploading(false)
            }
          }
        })()
        return true
      },
      handlePaste(view, event) {
        const files = Array.from(event.clipboardData?.files || []).filter(isUploadableImage)
        if (!files.length) return false
        event.preventDefault()
        const id = noteIdRef.current
        if (!id) { notifyError('save the note before adding an image'); return true }
        let cursor = view.state.selection.from;
        (async () => {
          for (const file of files) {
            try {
              setUploading(true)
              const att = await uploadNoteAttachment(id, file)
              const node = view.state.schema.nodes.noteImage.create({
                token: att.token, caption: '', width: att.width, height: att.height,
              })
              view.dispatch(view.state.tr.insert(cursor, node))
              cursor += node.nodeSize
            } catch (e) {
              notifyError(e?.message || 'image upload failed')
            } finally {
              setUploading(false)
            }
          }
        })()
        return true
      },
    },
    onUpdate: ({ editor: ed }) => {
      const md = serializeNoteDoc(ed.getJSON())
      lastEmittedRef.current = md
      onChange?.(md)
    },
  })

  // Reset editor content when the caller hands us a `value` that did not
  // come from our own last onChange -- a note switch, or an external write
  // (e.g. the server's own sanitize pass) overwriting the parent's `body`
  // state. Comparing against our own last-emitted string (rather than
  // re-serializing the live doc on every render) means a keystroke never
  // fights itself: the effect only ever fires for a genuinely external
  // change, never as an echo of the change it just caused.
  //
  // The second argument MUST be the options object. Tiptap 2 took a bare
  // `emitUpdate` boolean here; Tiptap 3 (the installed 3.30.2) destructures
  // it -- `const { emitUpdate = true } = false` yields `true`, so passing
  // `false` did the exact opposite of what it read as. onUpdate fired,
  // re-serialized, and PATCHed: merely CLICKING a note whose stored body
  // was not already a fixed point of parse-then-serialize rewrote it on
  // disk, with zero keystrokes.
  useEffect(() => {
    if (!editor) return
    if (value === lastEmittedRef.current) return
    lastEmittedRef.current = value
    editor.commands.setContent(parseNoteMarkdown(value), { emitUpdate: false })
  }, [value, editor, noteId])

  useEffect(() => {
    if (autoFocus && editor) editor.commands.focus('end')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor])

  // Delegated click on the editable surface: a tap/click landing on one of
  // our own note-image <img> tags opens the full-size viewer. Everything
  // else falls through to Tiptap's normal editing behaviour.
  const onSurfaceClick = useCallback((e) => {
    const img = e.target?.closest?.('img[data-note-image-token]')
    if (!img) return
    const token = img.getAttribute('data-note-image-token')
    if (!token) return
    setViewer({ token, caption: img.getAttribute('alt') || '' })
  }, [])

  const pickFiles = useCallback(async (fileList) => {
    const id = noteIdRef.current
    if (!id) { notifyError('save the note before adding an image'); return }
    const picked = Array.from(fileList || [])
    const files = picked.filter(isUploadableImage)
    // Never fail silently: a picker that appears to do nothing at all reads
    // as a broken button, not as a rejection.
    if (files.length < picked.length) {
      notifyError(files.length
        ? 'some files were not images and were skipped'
        : 'that is not an image (jpg, png, heic, webp, gif)')
    }
    for (const file of files) {
      try {
        setUploading(true)
        const att = await uploadNoteAttachment(id, file)
        editor?.chain().focus().insertContent({
          type: 'noteImage',
          attrs: { token: att.token, caption: '', width: att.width, height: att.height },
        }).run()
      } catch (e) {
        notifyError(e?.message || 'image upload failed')
      } finally {
        setUploading(false)
      }
    }
  }, [editor, notifyError])

  const onFileInputChange = useCallback((e) => {
    const files = e.target.files
    if (files && files.length) pickFiles(files)
    e.target.value = '' // allow re-picking the same file back to back
  }, [pickFiles])

  const removeViewerImage = useCallback(() => {
    if (!editor || !viewer) { setViewer(null); return }
    let foundPos = null
    let foundSize = 0
    editor.state.doc.descendants((node, pos) => {
      if (foundPos !== null) return false
      if (node.type.name === 'noteImage' && node.attrs.token === viewer.token) {
        foundPos = pos
        foundSize = node.nodeSize
        return false
      }
      return true
    })
    if (foundPos !== null) {
      editor.chain().focus().deleteRange({ from: foundPos, to: foundPos + foundSize }).run()
    }
    setViewer(null)
  }, [editor, viewer])

  if (!editor) return null

  const noImageTarget = !noteId

  return (
    <div className="note-rte">
      <div className="note-rte-content" onClick={onSurfaceClick}>
        <EditorContent editor={editor} />
        {editor.isEmpty && (
          <div className="note-rte-placeholder" aria-hidden="true">{placeholder}</div>
        )}
      </div>

      <div className="note-rte-toolbar" role="toolbar" aria-label="Formatting">
        <ToolbarButton
          label="Bold" glyph={<strong>B</strong>}
          active={editor.isActive('bold')}
          onClick={() => editor.chain().focus().toggleBold().run()}
        />
        <ToolbarButton
          label="Italic" glyph={<em>I</em>}
          active={editor.isActive('italic')}
          onClick={() => editor.chain().focus().toggleItalic().run()}
        />
        <ToolbarButton
          label="Bulleted list" glyph="•"
          active={editor.isActive('bulletList')}
          onClick={() => editor.chain().focus().toggleBulletList().run()}
        />
        <ToolbarButton
          label="Numbered list" glyph="1."
          active={editor.isActive('orderedList')}
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
        />
        <ToolbarButton
          label="Checklist" glyph="☑"
          active={editor.isActive('taskList')}
          onClick={() => editor.chain().focus().toggleTaskList().run()}
        />
        <ToolbarButton
          label="Insert image" glyph="▣"
          active={false}
          disabled={noImageTarget || uploading}
          onClick={() => fileInputRef.current?.click()}
        />
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="note-rte-file-input"
        aria-hidden="true"
        tabIndex={-1}
        onChange={onFileInputChange}
      />

      <Sheet
        open={!!viewer}
        onClose={() => setViewer(null)}
        variant="dialog"
        title={viewer?.caption || 'Image'}
      >
        {viewer && (
          <div className="note-rte-viewer">
            <img
              className="note-rte-viewer-img"
              src={`/api/notes/attachments/${viewer.token}`}
              alt={viewer.caption || ''}
            />
            <div className="note-rte-viewer-actions">
              <button type="button" className="btn reject" onClick={removeViewerImage}>
                Remove image
              </button>
            </div>
          </div>
        )}
      </Sheet>
    </div>
  )
}
