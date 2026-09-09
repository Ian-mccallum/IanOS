import React, { useCallback, useEffect, useRef } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'

// School documents intentionally have their own versioned JSON format. The
// general Notes editor speaks a six-feature Markdown dialect, which is ideal
// for quick personal notes but cannot preserve class headings, quotes, or
// code. The node/mark set lives in schema.js so a React-free test can build
// the real schema and diff it against core/school.py's server allowlist; read
// that file before changing what this editor can produce.
import { NOTE_PLACEHOLDER, SCHOOL_EXTENSIONS } from './schema.js'

const EMPTY_DOCUMENT = { type: 'doc', content: [{ type: 'paragraph' }] }

function stableDocument(value) {
  try { return JSON.stringify(value || EMPTY_DOCUMENT) } catch { return JSON.stringify(EMPTY_DOCUMENT) }
}

function ToolButton({ label, active = false, toggle = false, onClick, children }) {
  return (
    <button
      type="button"
      className={`school-note-tool${active ? ' is-active' : ''}`}
      aria-label={label}
      aria-pressed={toggle ? active : undefined}
      title={label}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {children}
    </button>
  )
}

function ToolDivider() {
  return <span className="school-note-tool-divider" aria-hidden="true" />
}

function styleValue(editor) {
  if (editor.isActive('heading', { level: 1 })) return 'heading-1'
  if (editor.isActive('heading', { level: 2 })) return 'heading-2'
  if (editor.isActive('heading', { level: 3 })) return 'heading-3'
  return 'paragraph'
}

export default function SchoolNoteEditor({
  document,
  onChange,
  autoFocus = false,
  placeholder = NOTE_PLACEHOLDER,
}) {
  const onChangeRef = useRef(onChange)
  const lastEmittedRef = useRef(stableDocument(document))
  useEffect(() => { onChangeRef.current = onChange }, [onChange])

  const editor = useEditor({
    extensions: SCHOOL_EXTENSIONS,
    content: document || EMPTY_DOCUMENT,
    autofocus: false,
    editorProps: {
      attributes: {
        class: 'school-note-prose',
        'aria-label': 'Class note',
        'data-note-placeholder': placeholder,
        autocorrect: 'on',
        autocapitalize: 'sentences',
        spellcheck: 'true',
      },
    },
    onUpdate: ({ editor: activeEditor }) => {
      const next = activeEditor.getJSON()
      lastEmittedRef.current = stableDocument(next)
      onChangeRef.current?.(next)
    },
  })

  // A route intent, a completed autosave, or a remote reload can replace the
  // document. Do not reset the editor for its own onUpdate echo, or typing
  // would jump the cursor backwards on every keystroke.
  useEffect(() => {
    if (!editor) return
    const next = stableDocument(document)
    if (next === lastEmittedRef.current) return
    lastEmittedRef.current = next
    editor.commands.setContent(document || EMPTY_DOCUMENT, { emitUpdate: false })
  }, [document, editor])

  useEffect(() => {
    if (autoFocus && editor) editor.commands.focus('end')
  }, [autoFocus, editor])

  const changeTextStyle = useCallback((value) => {
    const chain = editor?.chain().focus()
    if (!chain) return
    if (value === 'paragraph') chain.setParagraph().run()
    else chain.toggleHeading({ level: Number(value.slice(-1)) }).run()
  }, [editor])

  const indent = useCallback(() => {
    const chain = editor?.chain().focus()
    if (!chain) return
    if (editor.isActive('taskItem')) chain.sinkListItem('taskItem').run()
    else chain.sinkListItem('listItem').run()
  }, [editor])

  const outdent = useCallback(() => {
    const chain = editor?.chain().focus()
    if (!chain) return
    if (editor.isActive('taskItem')) chain.liftListItem('taskItem').run()
    else chain.liftListItem('listItem').run()
  }, [editor])

  const insert = useCallback((command) => {
    const chain = editor?.chain().focus()
    if (!chain) return
    if (command === 'quote') chain.toggleBlockquote().run()
    if (command === 'code') chain.toggleCodeBlock().run()
    if (command === 'divider') chain.setHorizontalRule().run()
  }, [editor])

  if (!editor) return null

  return (
    <div className="school-note-editor">
      <div className="school-note-toolbar" role="toolbar" aria-label="Class note formatting">
        <div className="school-note-toolbar-scroll">
          <div className="school-note-tool-group" aria-label="History">
            <ToolButton label="Undo" onClick={() => editor.chain().focus().undo().run()}><span aria-hidden="true">↶</span></ToolButton>
            <ToolButton label="Redo" onClick={() => editor.chain().focus().redo().run()}><span aria-hidden="true">↷</span></ToolButton>
          </div>
          <ToolDivider />
          <label className="school-note-style-select">
            <span className="sr-only">Text style</span>
            <select value={styleValue(editor)} onChange={(event) => changeTextStyle(event.target.value)} aria-label="Text style">
              <option value="paragraph">Normal text</option>
              <option value="heading-1">Title</option>
              <option value="heading-2">Heading</option>
              <option value="heading-3">Subheading</option>
            </select>
          </label>
          <ToolDivider />
          <div className="school-note-tool-group" aria-label="Text emphasis">
            <ToolButton label="Bold" toggle active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()}><strong>B</strong></ToolButton>
            <ToolButton label="Italic" toggle active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()}><em>I</em></ToolButton>
            <ToolButton label="Strikethrough" toggle active={editor.isActive('strike')} onClick={() => editor.chain().focus().toggleStrike().run()}><span aria-hidden="true">S</span></ToolButton>
            <ToolButton label="Inline code" toggle active={editor.isActive('code')} onClick={() => editor.chain().focus().toggleCode().run()}><span className="school-note-inline-code" aria-hidden="true">&lt;/&gt;</span></ToolButton>
          </div>
          <ToolDivider />
          <div className="school-note-tool-group" aria-label="Lists">
            <ToolButton label="Bullet list" toggle active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()}><span aria-hidden="true">•≡</span></ToolButton>
            <ToolButton label="Numbered list" toggle active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()}><span aria-hidden="true">1≡</span></ToolButton>
            <ToolButton label="Checklist" toggle active={editor.isActive('taskList')} onClick={() => editor.chain().focus().toggleTaskList().run()}><span aria-hidden="true">☑</span></ToolButton>
            <ToolButton label="Outdent" onClick={() => outdent()}><span aria-hidden="true">⇤</span></ToolButton>
            <ToolButton label="Indent" onClick={() => indent()}><span aria-hidden="true">⇥</span></ToolButton>
          </div>
          <ToolDivider />
          <div className="school-note-tool-group" aria-label="Clear">
            <ToolButton label="Clear formatting" onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}><span aria-hidden="true">⌫T</span></ToolButton>
          </div>
        </div>
        <ToolDivider />
        <details className="school-note-insert-menu">
          <summary>Insert <span aria-hidden="true">⌄</span></summary>
          <div>
            <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => insert('quote')}>Quote</button>
            <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => insert('code')}>Code block</button>
            <button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => insert('divider')}>Divider</button>
          </div>
        </details>
      </div>
      <div className="school-note-editor-surface">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}
