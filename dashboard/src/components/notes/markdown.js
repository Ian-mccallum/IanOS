/**
 * Bidirectional Markdown <-> Tiptap/ProseMirror JSON for SPEC-v31's CLOSED
 * note-body grammar: **bold**, *italic*, "- " bullet lists, "1. " numbered
 * lists, "- [ ]"/"- [x]" checklists, and inline `![caption](note-image:TOKEN)`
 * embeds. Nothing else exists in this dialect (see core/db.py's
 * sanitize_note_body -- raw HTML, tables, footnotes, and plain links are
 * stripped server-side on every write, so this module never needs to round-
 * trip them).
 *
 * Hand-rolled rather than a Markdown-editor library extension on purpose:
 * Tiptap 3's node packages (bold/italic/bulletList/taskItem/...) already ship
 * internal `parseMarkdown`/`renderMarkdown` hooks (see
 * node_modules/@tiptap/extension-list), but the glue that walks a document
 * and calls them is NOT part of any published `@tiptap/*` package today (no
 * `@tiptap/extension-markdown` exists on the registry) -- it is unexported
 * internal groundwork, not a stable public API. Depending on it would mean
 * betting this feature's one wire-format contract on undocumented internals
 * that owe us nothing. A closed, 6-construct grammar is also small enough
 * that a dedicated ~150-line parser can guarantee an EXACT round trip
 * (including the note-image: scheme, which no generic Markdown library
 * knows about anyway), where a general-purpose serializer would need
 * fighting-the-grain configuration to promise the same thing.
 *
 * Model: one line of source text = one block-level node (a paragraph, or one
 * item in a list). Blank lines are preserved as empty paragraphs. This is
 * why an existing plain-text note (SPEC-v31's required degenerate case)
 * round-trips byte-for-byte: split on "\n", one paragraph per line, joined
 * back with "\n" reproduces the original exactly, blank lines included.
 */

const TASK_RE = /^-\s\[([ xX])\]\s?(.*)$/
const BULLET_RE = /^-\s(.*)$/
const ORDERED_RE = /^\d+\.\s(.*)$/
const IMAGE_RE = /^!\[([^\]\n]*)\]\(([^)\n]*)\)/
const NOTE_IMAGE_TOKEN_RE = /^note-image:([A-Za-z0-9_-]+)$/

function lineKind(line) {
  let m = TASK_RE.exec(line)
  if (m) return { kind: 'task', checked: m[1].toLowerCase() === 'x', text: m[2] }
  m = BULLET_RE.exec(line)
  if (m) return { kind: 'bullet', text: m[1] }
  m = ORDERED_RE.exec(line)
  if (m) return { kind: 'ordered', text: m[1] }
  return { kind: 'para', text: line }
}

/**
 * Inline tokenizer: text runs (with bold/italic marks) plus noteImage atoms.
 * Uses a lightweight CommonMark-ish flanking rule (a `*`/`**` may only OPEN
 * when the next character is non-whitespace, and may only CLOSE when the
 * preceding character is non-whitespace) so a stray, unpaired asterisk ("3 *
 * 4 = 12") never accidentally toggles italic to the end of the line. Any
 * editor-produced markdown always satisfies this (see serializeInlineNode's
 * own lead/trail whitespace handling below), so real content always round-
 * trips; the heuristic only changes behaviour for text nobody's editor wrote.
 */
export function parseInline(text) {
  const nodes = []
  const s = text || ''
  let buf = ''
  let lastChar = ''
  let bold = false
  let italic = false

  const flush = () => {
    if (!buf) return
    const marks = []
    if (bold) marks.push({ type: 'bold' })
    if (italic) marks.push({ type: 'italic' })
    nodes.push(marks.length ? { type: 'text', text: buf, marks } : { type: 'text', text: buf })
    buf = ''
  }
  const appendChar = (ch) => { buf += ch; lastChar = ch }
  const isSpace = (ch) => !ch || /\s/.test(ch)

  let i = 0
  while (i < s.length) {
    if (s[i] === '!' && s[i + 1] === '[') {
      const m = IMAGE_RE.exec(s.slice(i))
      if (m) {
        flush()
        const caption = m[1]
        const target = m[2].trim()
        const tm = NOTE_IMAGE_TOKEN_RE.exec(target)
        nodes.push({
          type: 'noteImage',
          attrs: { token: tm ? tm[1] : null, caption, width: null, height: null },
        })
        i += m[0].length
        lastChar = ')'
        continue
      }
    }
    if (s[i] === '*' && s[i + 1] === '*') {
      const nextCh = s[i + 2] || ''
      const canToggle = bold ? !isSpace(lastChar) : !isSpace(nextCh)
      if (canToggle) { flush(); bold = !bold; i += 2; continue }
      appendChar('*'); i += 1; continue
    }
    if (s[i] === '*') {
      const nextCh = s[i + 1] || ''
      const canToggle = italic ? !isSpace(lastChar) : !isSpace(nextCh)
      if (canToggle) { flush(); italic = !italic; i += 1; continue }
      appendChar('*'); i += 1; continue
    }
    appendChar(s[i]); i += 1
  }
  flush()
  return nodes
}

function paragraphOf(text) {
  return { type: 'paragraph', content: parseInline(text) }
}

/** Markdown string -> Tiptap/ProseMirror JSON doc. Never throws: an odd or
 * malformed line just falls through to a plain paragraph. */
export function parseNoteMarkdown(markdown) {
  const lines = (markdown ?? '').split('\n')
  const blocks = []
  let i = 0
  while (i < lines.length) {
    const k = lineKind(lines[i])
    if (k.kind === 'para') {
      blocks.push(paragraphOf(k.text))
      i += 1
      continue
    }
    const items = []
    while (i < lines.length) {
      const kk = lineKind(lines[i])
      if (kk.kind !== k.kind) break
      if (k.kind === 'task') {
        items.push({ type: 'taskItem', attrs: { checked: kk.checked }, content: [paragraphOf(kk.text)] })
      } else {
        items.push({ type: 'listItem', content: [paragraphOf(kk.text)] })
      }
      i += 1
    }
    if (k.kind === 'task') blocks.push({ type: 'taskList', content: items })
    else if (k.kind === 'bullet') blocks.push({ type: 'bulletList', content: items })
    else blocks.push({ type: 'orderedList', attrs: { start: 1 }, content: items })
  }
  if (blocks.length === 0) blocks.push({ type: 'paragraph', content: [] })
  return { type: 'doc', content: blocks }
}

function serializeInlineNode(node) {
  if (node.type === 'noteImage') {
    const caption = node.attrs?.caption || ''
    const token = node.attrs?.token || ''
    return `![${caption}](note-image:${token})`
  }
  if (node.type === 'text') {
    const marks = (node.marks || []).map((m) => m.type)
    const bold = marks.includes('bold')
    const italic = marks.includes('italic')
    const raw = node.text || ''
    if (!bold && !italic) return raw
    // Delimiters must hug non-space content (the same flanking rule the
    // parser enforces on the way in) or a leading/trailing space inside
    // "** bold **" would fail to reparse as emphasis at all.
    const lead = raw.match(/^\s*/)[0]
    const trail = raw.match(/\s*$/)[0]
    const core = raw.slice(lead.length, raw.length - trail.length)
    if (!core) return raw
    const wrapped = bold && italic ? `***${core}***` : bold ? `**${core}**` : `*${core}*`
    return lead + wrapped + trail
  }
  return ''
}

function serializeInline(content) {
  return (content || []).map(serializeInlineNode).join('')
}

const LIST_TYPES = new Set(['bulletList', 'orderedList', 'taskList'])

/**
 * Every line of text one list item contributes, in document order.
 *
 * This grammar has exactly one source line per list item, so the editor's
 * schema pins a list item to exactly one paragraph (see schema.js's
 * FlatListItem). A document that violates that is unreachable through the
 * editor, but this function is the wire-format contract and must never be
 * the thing that loses words: a second paragraph, or a nested sublist,
 * flattens into further lines at the SAME level rather than being dropped.
 *
 * This used to take only the FIRST paragraph child. Stock Tiptap binds Tab
 * to sinkListItem and ships `content: "paragraph block*"`, so one keystroke
 * on the second bullet of a list moved it into a sublist -- and this
 * function then serialized it to nothing. The note saved without it, said
 * "Saved", and the text was gone on reload.
 *
 * Flattening is stable: reparsing the flattened lines yields the same flat
 * list, so the round trip stays idempotent.
 */
function listItemLines(item) {
  const lines = []
  for (const child of item.content || []) {
    if (child.type === 'paragraph') lines.push(serializeInline(child.content))
    else if (LIST_TYPES.has(child.type)) {
      for (const sub of child.content || []) lines.push(...listItemLines(sub))
    }
  }
  if (lines.length === 0) lines.push('')
  return lines
}

function serializeBlock(node) {
  switch (node.type) {
    case 'paragraph':
      return serializeInline(node.content)
    case 'bulletList':
      return (node.content || [])
        .flatMap((li) => listItemLines(li))
        .map((text) => `- ${text}`)
        .join('\n')
    case 'orderedList':
      return (node.content || [])
        .flatMap((li) => listItemLines(li))
        .map((text, idx) => `${idx + 1}. ${text}`)
        .join('\n')
    case 'taskList':
      return (node.content || [])
        .flatMap((ti) => {
          // Extra lines from one task item inherit that item's own checkbox:
          // there is no other item to read a state from.
          const box = ti.attrs?.checked ? 'x' : ' '
          return listItemLines(ti).map((text) => `- [${box}] ${text}`)
        })
        .join('\n')
    default:
      return ''
  }
}

/** Tiptap/ProseMirror JSON doc -> Markdown string (the wire format PATCHed
 * to /api/notes/{id}). Numbered lists always renumber from 1 by position --
 * the editor, not stored digits, owns list order, matching how every
 * WYSIWYG numbered list actually behaves. */
export function serializeNoteDoc(doc) {
  if (!doc || !Array.isArray(doc.content)) return ''
  return doc.content.map(serializeBlock).join('\n')
}
