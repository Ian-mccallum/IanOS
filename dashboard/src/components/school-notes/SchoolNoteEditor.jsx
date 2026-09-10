import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { EditorContent, useEditor } from '@tiptap/react'

// School documents intentionally have their own versioned JSON format. The
// general Notes editor speaks a six-feature Markdown dialect, which is ideal
// for quick personal notes but cannot preserve class headings, quotes, or
// code. The node/mark set lives in schema.js so a React-free test can build
// the real schema and diff it against core/school.py's server allowlist; read
// that file before changing what this editor can produce.
import { CharacterPickerTrigger, NOTE_PLACEHOLDER, SCHOOL_EXTENSIONS } from './schema.js'
import { characterSetFor, jumpIndex } from './characters.js'
import Sheet from '../Sheet.jsx'

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

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || '')
const MOD = IS_MAC ? '\u2318' : 'Ctrl+'
const SHIFT = IS_MAC ? '\u21e7' : 'Shift+'

/**
 * The course's special letters at the caret (Ian, 2026-09-10: "pop up as
 * selectable when i click some key combo that is very easy ONLY on viking
 * myth page"). Keyboard first, since he takes these notes on a laptop: arrow
 * keys move, up/down switches case, Enter picks, and typing the plain letter
 * jumps to it (t is þ, d is ð, pressing o again moves on to the next o).
 * Picking one inserts it and closes, the way the macOS accent popup does, so
 * typing carries on from the same spot.
 */
function CharacterPicker({ characterSet, open, anchor, onPick, onClose }) {
  const rows = [characterSet.lower, characterSet.upper]
  const size = characterSet.lower.length
  const [row, setRow] = useState(0)
  const [col, setCol] = useState(0)
  const keys = useRef([])

  useEffect(() => {
    if (!open) return
    setRow(0)
    setCol(0)
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    // After Sheet's focus trap has run, which focuses its first control (the
    // close button) on open. Focus belongs on the letters.
    const timer = setTimeout(() => keys.current[row * size + col]?.focus(), 0)
    return () => clearTimeout(timer)
  }, [open, row, col, size])

  const onKeyDown = (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return
    let nextRow = row
    let nextCol = col
    if (event.key === 'ArrowRight') nextCol = (col + 1) % size
    else if (event.key === 'ArrowLeft') nextCol = (col - 1 + size) % size
    else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') nextRow = row === 0 ? 1 : 0
    else if (event.key === 'Home') nextCol = 0
    else if (event.key === 'End') nextCol = size - 1
    else if (event.key.length === 1 && /[a-z]/i.test(event.key)) {
      const targetRow = event.shiftKey ? 1 : 0
      const found = jumpIndex(rows[targetRow], event.key, targetRow === row ? col : -1)
      if (found === -1) return
      nextRow = targetRow
      nextCol = found
    } else return
    event.preventDefault()
    setRow(nextRow)
    setCol(nextCol)
  }

  return (
    <Sheet open={open} onClose={onClose} title={characterSet.label} variant="popover"
           anchor={anchor} className="char-picker-sheet">
      <div className="char-picker-rows" onKeyDown={onKeyDown}>
        {rows.map((letters, r) => (
          <div key={r} className="char-picker-row" role="group" aria-label={r === 0 ? 'Lowercase' : 'Capitals'}>
            {letters.map((ch, c) => (
              <button
                key={ch}
                ref={(node) => { keys.current[r * size + c] = node }}
                type="button"
                className="char-picker-key"
                tabIndex={r === row && c === col ? 0 : -1}
                aria-label={ch}
                onClick={() => onPick(ch)}
              >
                {ch}
              </button>
            ))}
          </div>
        ))}
      </div>
      <p className="char-picker-hint">Type t for \u00fe, d for \u00f0. Shift for capitals.</p>
    </Sheet>
  )
}

export default function SchoolNoteEditor({
  document,
  onChange,
  autoFocus = false,
  placeholder = NOTE_PLACEHOLDER,
  courseCode = '',
}) {
  const characterSet = characterSetFor(courseCode)
  const [picker, setPicker] = useState(null)
  // The shortcut is built into the editor once, at creation, and the editor
  // outlives a switch between notebooks. So it asks a ref, which always holds
  // the current note's answer, instead of capturing a course at creation.
  const openPickerRef = useRef(() => false)
  const extensions = useMemo(() => [
    ...SCHOOL_EXTENSIONS,
    CharacterPickerTrigger.configure({ onTrigger: () => openPickerRef.current() }),
  ], [])
  const onChangeRef = useRef(onChange)
  const lastEmittedRef = useRef(stableDocument(document))
  useEffect(() => { onChangeRef.current = onChange }, [onChange])

  const editor = useEditor({
    extensions,
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

  const openPicker = useCallback(() => {
    if (!editor || !characterSet) return false
    const { from, to } = editor.state.selection
    // Bring the caret into view first: set it, scroll away, press Cmd+; and
    // an anchor measured off-screen put the picker at y=4465 in live testing,
    // invisible but holding focus, so the next keystrokes went nowhere. If
    // the caret still is not on screen after the scroll, drop the anchor and
    // let Sheet use its centred default.
    editor.commands.scrollIntoView()
    let rect = null
    try {
      const at = editor.view.coordsAtPos(from)
      const onScreen = at.bottom > 0 && at.top < window.innerHeight
        && at.right > 0 && at.left < window.innerWidth
      rect = onScreen ? { left: at.left, right: at.right, top: at.top, bottom: at.bottom } : null
    } catch { rect = null }
    setPicker({ range: { from, to }, rect })
    return true
  }, [editor, characterSet])
  useEffect(() => { openPickerRef.current = openPicker }, [openPicker])

  // Insert where the caret was when the picker opened, replacing a selection
  // if there was one. A plain string goes in as text, so it keeps the marks
  // of the surrounding text (a letter picked inside bold stays bold).
  const pickCharacter = useCallback((ch) => {
    const range = picker?.range
    setPicker(null)
    if (!editor) return
    const chain = editor.chain().focus()
    if (range) chain.insertContentAt(range, ch).run()
    else chain.insertContent(ch).run()
  }, [editor, picker])

  const closePicker = useCallback(() => {
    setPicker(null)
    editor?.commands.focus()
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
            <ToolButton label={`Bold (${MOD}B)`} toggle active={editor.isActive('bold')} onClick={() => editor.chain().focus().toggleBold().run()}><strong>B</strong></ToolButton>
            <ToolButton label="Italic" toggle active={editor.isActive('italic')} onClick={() => editor.chain().focus().toggleItalic().run()}><em>I</em></ToolButton>
            <ToolButton label="Strikethrough" toggle active={editor.isActive('strike')} onClick={() => editor.chain().focus().toggleStrike().run()}><span aria-hidden="true">S</span></ToolButton>
            <ToolButton label="Inline code" toggle active={editor.isActive('code')} onClick={() => editor.chain().focus().toggleCode().run()}><span className="school-note-inline-code" aria-hidden="true">&lt;/&gt;</span></ToolButton>
          </div>
          <ToolDivider />
          <div className="school-note-tool-group" aria-label="Lists">
            <ToolButton label={`Bullet list (${MOD}.)`} toggle active={editor.isActive('bulletList')} onClick={() => editor.chain().focus().toggleBulletList().run()}><span aria-hidden="true">•≡</span></ToolButton>
            <ToolButton label={`Numbered list (${MOD}${SHIFT}.)`} toggle active={editor.isActive('orderedList')} onClick={() => editor.chain().focus().toggleOrderedList().run()}><span aria-hidden="true">1≡</span></ToolButton>
            <ToolButton label="Checklist" toggle active={editor.isActive('taskList')} onClick={() => editor.chain().focus().toggleTaskList().run()}><span aria-hidden="true">☑</span></ToolButton>
            <ToolButton label="Outdent" onClick={() => outdent()}><span aria-hidden="true">⇤</span></ToolButton>
            <ToolButton label="Indent" onClick={() => indent()}><span aria-hidden="true">⇥</span></ToolButton>
          </div>
          <ToolDivider />
          <div className="school-note-tool-group" aria-label="Clear">
            <ToolButton label="Clear formatting" onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}><span aria-hidden="true">⌫T</span></ToolButton>
          </div>
          {characterSet && (
            <>
              <ToolDivider />
              <div className="school-note-tool-group" aria-label={characterSet.label}>
                <ToolButton label={`${characterSet.label} letters (${MOD};)`} onClick={openPicker}>
                  <span className="school-note-char-glyph" aria-hidden="true">{characterSet.upper[6]}</span>
                </ToolButton>
              </div>
            </>
          )}
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
      {characterSet && (
        <CharacterPicker
          characterSet={characterSet}
          open={Boolean(picker)}
          anchor={picker?.rect || null}
          onPick={pickCharacter}
          onClose={closePicker}
        />
      )}
    </div>
  )
}
