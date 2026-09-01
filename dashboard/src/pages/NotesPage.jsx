import React, { useCallback, useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import { relTime } from '../lib/time.js'
import NoteEditor from '../components/notes/NoteEditor.jsx'
import NoteFolderSheet from '../components/notes/NoteFolderSheet.jsx'
import NoteBreadcrumb from '../components/notes/NoteBreadcrumb.jsx'

/**
 * Notes (SPEC-v10 §5, reimagined by SPEC-v31). Deliberately shaped like iPhone
 * Notes:
 *   - one ✎ makes a note and puts the cursor in the body. No dialog, no title
 *     field, the first line becomes the title, server-side.
 *   - there is no save button, ever. Typing is saving.
 *   - delete is a soft delete with an undo, never a confirm dialog.
 *   - nested folders (a "+" beside ✎ New) and a rich-text body (NoteEditor.jsx)
 *     are layered on top of that exact same shape, never a second surface.
 */
const AUTOSAVE_MS = 600

// The one place folders are rendered as plain rows in the list itself (not
// inside a sheet): tap-to-open only, no edit/delete affordances here -- those
// live in NoteFolderSheet, reached via the "+" button or the desktop
// breadcrumb's "Folders" control. Reuses NoteFolderSheet's own `.folder-row`
// styling verbatim (same --folder color-wash technique) so a folder reads
// identically whether it's being browsed or being managed.
function FolderListRow({ folder, onOpen }) {
  const style = folder.color ? { '--folder': folder.color } : undefined
  return (
    <div className="folder-row" style={style}>
      <button type="button" className="folder-row-main" onClick={() => onOpen(folder)}>
        <span className="folder-row-name">{folder.name}</span>
      </button>
    </div>
  )
}

function NoteRow({ note, active, onOpen, onPin, onMove, onDelete }) {
  return (
    <div className={`note-row${active ? ' active' : ''}${note.pinned ? ' pinned' : ''}`}>
      <button type="button" className="note-row-main" onClick={() => onOpen(note)}>
        <span className="note-row-title">
          {/* !! matters: SQLite hands back 0/1, and JSX renders a literal 0
              (`0 && x` is 0, which is a valid child), the list read "0Dorm
              packing list". Booleans are the only falsy value React drops. */}
          {!!note.pinned && <span className="note-pin" aria-label="pinned">◆</span>}
          {titleText(note)}
        </span>
        <span className="note-row-meta">
          <span className="note-row-date">{relTime(note.updated_at)}</span>
          <span className="note-row-preview" title={preview(note)}>{preview(note)}</span>
        </span>
      </button>
      <div className="note-row-actions">
        <button type="button" onClick={() => onPin(note)}
                aria-label={note.pinned ? 'Unpin' : 'Pin'}>{note.pinned ? '◆' : '◇'}</button>
        <button type="button" onClick={(e) => onMove(note, e)}
                aria-label="Move to folder">Move</button>
        <button type="button" className="note-del" onClick={() => onDelete(note)}
                aria-label="Delete">✕</button>
      </div>
    </div>
  )
}

// A note's body is a closed Markdown dialect now (SPEC-v31), not plain text,
// so the list strips the six constructs down to their words rather than
// showing "**bold**" or a raw image embed literally. One line at a time, so
// the `^` list/checklist anchors still mean "start of this line". Purely
// cosmetic: notes.title and notes.body themselves are untouched.
function stripNoteMarkdown(line) {
  return line
    .replace(/!\[([^\]]*)\]\(note-image:[^)]+\)/g, (_, cap) => (cap ? cap : '[image]'))
    .replace(/^\s*[-*]\s*\[[ xX]\]\s*/, '')
    .replace(/^\s*[-*]\s+/, '')
    .replace(/^\s*\d+\.\s+/, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
}

// The stored title is the note's first line verbatim (core/db.py's
// note_title_from), and a first line can be any of the six constructs --
// including an image embed, which rendered here as the literal
// "![passport scan](note-image:84664c29)", token and all.
function titleText(note) {
  return stripNoteMarkdown(note.title || '').trim() || 'New note'
}

// Joining line-by-line (not before the strip) for the same anchor reason.
function preview(note) {
  const cleaned = (note.body || '')
    .split('\n')
    .slice(1)
    .map(stripNoteMarkdown)
    .join(' ')
    .trim()
  return cleaned ? cleaned.slice(0, 60) : 'No additional text'
}

// GET /api/notes/folders only ever answers "children of one parent, or the
// top level when parent_id is omitted" (api/main.py's own comment on that
// route). Resolving an arbitrary folder's full ancestor chain -- needed
// whenever NoteFolderSheet's browse mode picks a folder from somewhere other
// than the level currently on screen -- means walking that same endpoint
// down from the root until the target id turns up. Folder counts in a
// single-user app are small (dozens, not thousands, per NoteFolderSheet.jsx's
// own comment on the identical trade-off), so this is a handful of round
// trips, never a performance concern.
async function fetchFolderChildren(parentId) {
  const qs = parentId == null ? '' : `?parent_id=${parentId}`
  const d = await api(`/api/notes/folders${qs}`)
  return Array.isArray(d.folders) ? d.folders : []
}

async function resolveFolderPath(targetId) {
  if (targetId == null) return []
  async function search(parentId, trail) {
    const kids = await fetchFolderChildren(parentId)
    for (const kid of kids) {
      if (kid.id === targetId) return [...trail, kid]
      const found = await search(kid.id, [...trail, kid])
      if (found) return found
    }
    return null
  }
  return (await search(null, [])) || []
}

export default function NotesPage({ toast }) {
  const [notes, setNotes] = useState([])
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)      // the note being edited
  const [body, setBody] = useState('')
  const [freshNote, setFreshNote] = useState(false)  // autofocus only a just-created note
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)
  // folderId is the three-way switch GET /api/notes and GET /api/notes/folders
  // both share: null means "All Notes" (root, unscoped -- today's one existing
  // behaviour, left unchanged), an id means exactly that folder. `path` is the
  // ancestor chain rendered by the breadcrumb / used for the phone back label;
  // a plain stack built as Ian browses down, per SPEC-v31's own "keep a simple
  // stack in component state" allowance.
  const [folderId, setFolderId] = useState(null)
  const [path, setPath] = useState([])
  const [folders, setFolders] = useState([])
  const [manageOpen, setManageOpen] = useState(false)   // NoteFolderSheet, mode="browse"
  const [moveNote, setMoveNote] = useState(null)        // note being filed, NoteFolderSheet mode="move"
  const rm = useReducedMotion()
  const timer = useRef(null)
  // One shared popover anchor: whichever trigger (the "+" button, the desktop
  // breadcrumb's "Folders" control, or a note row's "Move" button) was just
  // clicked writes itself here right before opening a sheet, and only one of
  // the two sheets below is ever open at a time.
  const anchorRef = useRef(null)

  const searching = !!q.trim()

  // NoteEditor's own formatting toolbar is fixed to the exact same bottom
  // strip the mobile tab bar occupies (both ride `--kb`, the keyboard inset),
  // and z-index alone can't settle who wins since they sit in different
  // stacking contexts (styles.css has the full explanation next to
  // `body.note-editing .nav-mobile`). Mirrors Sheet.jsx's own `sheet-open`
  // body class exactly: something else owns this strip while a note is open
  // on phone, so the tab bar gets out of the way rather than fighting for it.
  useEffect(() => {
    document.body.classList.toggle('note-editing', !!open)
    return () => document.body.classList.remove('note-editing')
  }, [open])

  const load = useCallback(async (query = q, fid = folderId) => {
    try {
      const params = new URLSearchParams()
      const trimmed = query.trim()
      // Folder-scoped search is explicitly out of scope (SPEC-v31): a query
      // always searches every note, standing in for Apple's "All Notes",
      // regardless of which folder Ian happens to be browsing.
      if (trimmed) params.set('q', trimmed)
      else if (fid !== null) params.set('folder_id', fid)
      const qs = params.toString()
      const d = await api(`/api/notes${qs ? `?${qs}` : ''}`)
      setNotes(d.notes || [])
    } catch (e) { toast(e.message, 'crit') } finally { setLoaded(true) }
  }, [q, folderId, toast])

  const loadFolders = useCallback(async (fid = folderId) => {
    try {
      setFolders(await fetchFolderChildren(fid))
    } catch (e) { toast(e.message, 'crit') }
  }, [folderId, toast])

  useEffect(() => { load(); loadFolders() }, [])         // eslint-disable-line
  useEffect(() => {
    const t = setTimeout(() => load(q, folderId), 200)   // search as you type
    return () => clearTimeout(t)
  }, [q, folderId])                                      // eslint-disable-line
  useEffect(() => { loadFolders(folderId) }, [folderId])  // eslint-disable-line

  // Autosave. The debounce is why there is no save button: stop typing for a
  // moment and it is already written. NoteEditor.jsx serializes its document
  // to this same Markdown string on every keystroke, exactly the shape a
  // plain <textarea>'s onChange used to hand this effect -- the source
  // changed, the PATCH path did not.
  useEffect(() => {
    if (!open) return undefined
    if (body === open.body) return undefined
    setSaving(true)
    clearTimeout(timer.current)
    const sent = body
    timer.current = setTimeout(async () => {
      try {
        const saved = await api(`/api/notes/${open.id}`, 'PATCH', { body })
        setOpen(saved)
        setNotes((ns) => ns.map((n) => (n.id === saved.id ? saved : n)))
        // The server sanitizes on every write (core/db.py's
        // sanitize_note_body strips plain links, tables, raw HTML), so what
        // came back is not always what went up. Handing the sanitized string
        // back to `body` is what makes NoteEditor's own reset effect fire and
        // re-sync the editor; without it the screen kept showing text the DB
        // no longer held and still said "Saved".
        //
        // Guarded on `sent`: never clobber keystrokes typed while the PATCH
        // was in flight. Those are already queued for the next debounce, and
        // that save re-syncs instead.
        setBody((cur) => (cur === sent && saved.body !== cur ? saved.body : cur))
      } catch (e) { toast(e.message, 'crit') } finally { setSaving(false) }
    }, AUTOSAVE_MS)
    return () => clearTimeout(timer.current)
  }, [body])                                            // eslint-disable-line

  const newNote = async () => {
    try {
      // Created inside whatever folder Ian is currently browsing (null at
      // All Notes, same as every note today) -- zero interruption, matching
      // the existing one-tap flow exactly.
      const n = await api('/api/notes', 'POST', { body: '', folder_id: folderId })
      setNotes((ns) => [n, ...ns])
      setOpen(n); setBody(''); setFreshNote(true)
    } catch (e) { toast(e.message, 'crit') }
  }

  const openNote = (n) => { setOpen(n); setBody(n.body || ''); setFreshNote(false) }

  const pin = async (n) => {
    try {
      const s = await api(`/api/notes/${n.id}`, 'PATCH', { pinned: !n.pinned })
      setNotes((ns) => [...ns.map((x) => (x.id === s.id ? s : x))]
        .sort((a, b) => (b.pinned - a.pinned) || b.updated_at.localeCompare(a.updated_at)))
    } catch (e) { toast(e.message, 'crit') }
  }

  const remove = async (n) => {
    try {
      await api(`/api/notes/${n.id}`, 'DELETE')
      setNotes((ns) => ns.filter((x) => x.id !== n.id))
      if (open?.id === n.id) setOpen(null)
      // Soft delete, so Undo restores the same row rather than re-creating it.
      toast(`deleted "${n.title || 'note'}"`, 'good', async () => {
        await api(`/api/notes/${n.id}/restore`, 'POST')
        load()
      })
    } catch (e) { toast(e.message, 'crit') }
  }

  const openMove = (n, e) => { anchorRef.current = e.currentTarget; setMoveNote(n) }

  const moveNoteTo = async (folder) => {
    if (!moveNote) return
    try {
      const saved = await api(`/api/notes/${moveNote.id}`, 'PATCH', { folder_id: folder ? folder.id : null })
      if (open?.id === saved.id) setOpen(saved)
      setMoveNote(null)
      load()   // the note may have just entered or left the folder on screen
    } catch (e) { toast(e.message, 'crit') }
  }

  const openFolder = (folder) => {
    setPath((p) => [...p, folder])
    setFolderId(folder.id)
  }

  // Breadcrumb crumb tap: every crumb shown is already one of this page's own
  // ancestors, so this is a local slice, never a fetch.
  const goToCrumb = (id) => {
    if (id === null) { setPath([]); setFolderId(null); return }
    setPath((p) => {
      const idx = p.findIndex((f) => f.id === id)
      return idx === -1 ? p : p.slice(0, idx + 1)
    })
    setFolderId(id)
  }

  // Phone-only back chevron, reusing the exact `.note-back` pattern the
  // editor pane's "‹ Notes" button already uses (SPEC-v31 UI/UX): one level
  // up per tap, the same way the desktop breadcrumb's own parent crumb would.
  const goUp = () => {
    if (path.length <= 1) { setPath([]); setFolderId(null); return }
    const parent = path[path.length - 2]
    setPath((p) => p.slice(0, -1))
    setFolderId(parent.id)
  }

  const openManage = (e) => { anchorRef.current = e.currentTarget; setManageOpen(true) }

  // NoteFolderSheet's own tree can offer any folder in the whole tree, not
  // only children of the level on screen, so the ancestor chain has to be
  // resolved fresh rather than just appended to the current stack.
  const selectFromSheet = async (folder) => {
    setManageOpen(false)
    if (!folder) { setFolderId(null); setPath([]); return }
    setFolderId(folder.id)
    try {
      setPath(await resolveFolderPath(folder.id))
    } catch {
      setPath([folder])
    }
  }

  const onFolderMutated = () => {
    loadFolders()
    load()
    if (folderId !== null) resolveFolderPath(folderId).then(setPath).catch(() => {})
  }

  // A folder that was just deleted (possibly as part of a cascade) can't stay
  // "current" -- back out to All Notes rather than show a folder that no
  // longer exists.
  const onFolderDeleted = (deletedId) => {
    if (folderId === deletedId || path.some((f) => f.id === deletedId)) {
      setFolderId(null); setPath([])
    }
  }

  const backLabel = path.length <= 1 ? 'All Notes' : path[path.length - 2].name

  // One component at every width. On a phone the list and the editor take
  // turns (CSS hides the list once a note is open); from 901px up they sit
  // side by side. Desktop is the enhancement, which is exactly what L1 asks
  // for, an earlier pass deferred this on a misreading of that law.
  return (
    <div className={`notes-page${open ? ' has-open' : ''}`}>
      <div className="notes-list-pane">
        <NoteBreadcrumb path={path} onNavigate={goToCrumb} onOpenFolders={openManage} />

        {folderId !== null && (
          <button type="button" className="btn ghost note-back note-folder-back" onClick={goUp}>
            ‹ {backLabel}
          </button>
        )}

        <div className="note-toolbar">
          <input className="note-search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search notes" aria-label="Search notes"
                 autoCorrect="off" autoCapitalize="none" spellCheck={false} enterKeyHint="search" />
          <button type="button" className="btn ghost note-folders-btn" aria-label="New folder"
                  title="New folder" onClick={openManage}>+</button>
          <button type="button" className="btn approve primary note-new" onClick={newNote}>
            ✎ New
          </button>
        </div>

        {!loaded ? (
          <p className="dim">Loading…</p>
        ) : (folders.length === 0 && notes.length === 0) ? (
          <div className="empty glass-card glass-card-pad">
            <div className="empty-title">{q ? 'Nothing matches' : 'No notes yet'}</div>
            <p>{q ? 'Try a different word.' : 'Select ✎ New. The first line becomes the title.'}</p>
          </div>
        ) : (
          <>
            {!searching && folders.length > 0 && (
              <div className="folder-list note-folder-list" role="group" aria-label="Folders">
                {folders.map((f) => (
                  <FolderListRow key={f.id} folder={f} onOpen={openFolder} />
                ))}
              </div>
            )}
            {notes.length > 0 && (
              <motion.ul className="note-list"
                         initial={rm ? false : { opacity: 0 }} animate={{ opacity: 1 }}>
                {notes.map((n) => (
                  <li key={n.id}>
                    <NoteRow note={n} active={open?.id === n.id} onOpen={openNote}
                             onPin={pin} onMove={openMove} onDelete={remove} />
                  </li>
                ))}
              </motion.ul>
            )}
          </>
        )}
      </div>

      {open && (
        <div className="notes-editor-pane">
          <div className="note-editor-bar">
            {/* Back only exists on the phone; on desktop the list never left. */}
            <button type="button" className="btn ghost note-back"
                    onClick={() => { setOpen(null); load() }}>‹ Notes</button>
            <span className="note-save-state" aria-live="polite">{saving ? 'Saving…' : 'Saved'}</span>
          </div>
          <NoteEditor
            value={body}
            onChange={setBody}
            noteId={open.id}
            autoFocus={freshNote}
            toast={toast}
          />
        </div>
      )}

      <NoteFolderSheet
        open={manageOpen}
        onClose={() => setManageOpen(false)}
        mode="browse"
        anchor={anchorRef}
        activeFolderId={folderId}
        contextFolderId={folderId}
        onSelectFolder={selectFromSheet}
        onMutated={onFolderMutated}
        onFolderDeleted={onFolderDeleted}
        toast={toast}
      />

      <NoteFolderSheet
        open={!!moveNote}
        onClose={() => setMoveNote(null)}
        mode="move"
        anchor={anchorRef}
        activeFolderId={moveNote?.folder_id ?? null}
        contextFolderId={folderId}
        onSelectFolder={moveNoteTo}
        onMutated={onFolderMutated}
        onFolderDeleted={onFolderDeleted}
        toast={toast}
        emptyTitle="No folders yet"
        emptyBody='Select "+ New folder" below to file this note.'
      />
    </div>
  )
}
