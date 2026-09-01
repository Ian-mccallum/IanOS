import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/api.js'
import Sheet from '../Sheet.jsx'

// Mirrors dashboard/src/components/AccountSheet.jsx's ACCOUNT_COLORS almost
// verbatim (SPEC-v31 "closely mirror the account-color closed-palette
// pattern" instruction): a closed, client-side-only set of hex/name pairs,
// not a free color field. Unlike accounts, core/db.py's note_folders.color
// column has no server-side CHECK against a fixed set (it is TEXT, "closed
// palette key" is a naming convention, not an enforced constraint) -- the
// closure lives entirely in this UI, same discipline, lighter enforcement,
// because a wrong folder color is cosmetic where a wrong account color
// collides with real financial UI. Kept as its own literal copy rather than
// imported: ACCOUNT_COLORS is a local const inside AccountSheet.jsx, not
// exported, and duplicating a 16-row array here is cheaper than reshaping
// that file just to share it.
export const FOLDER_COLORS = [
  { hex: '#818cf8', name: 'Indigo' },
  { hex: '#38bdf8', name: 'Sky' },
  { hex: '#f472b6', name: 'Pink' },
  { hex: '#c084fc', name: 'Purple' },
  { hex: '#facc15', name: 'Yellow' },
  { hex: '#fb923c', name: 'Orange' },
  { hex: '#fca5a5', name: 'Red' },
  { hex: '#a3e635', name: 'Green' },
  { hex: '#2dd4bf', name: 'Teal' },
  { hex: '#22d3ee', name: 'Cyan' },
  { hex: '#a78bfa', name: 'Violet' },
  { hex: '#e879f9', name: 'Fuchsia' },
  { hex: '#fb7185', name: 'Rose' },
  { hex: '#3b82f6', name: 'Blue' },
  { hex: '#d97706', name: 'Amber' },
  { hex: '#94a3b8', name: 'Slate' },
]

const EMPTY_DRAFT = { id: null, name: '', color: '', parentId: null }

/** GET /api/notes/folders only ever answers "children of one parent" (see
 * api/main.py's own comment on that route: "no everything flat mode"), so a
 * flat depth-indented tree has to be assembled client-side, one recursive
 * fan-out of that same endpoint. Folder counts in a single-user app are
 * small (dozens, not thousands), so this is a handful of round trips, not a
 * performance concern. `cancelled` is a plain mutable ref, not state, so a
 * fast close-then-reopen can't let a stale recursive fetch win a race against
 * the fetch the reopen just started. */
async function fetchFolderTree(cancelledRef) {
  async function children(parentId) {
    if (cancelledRef.current) return []
    const data = await api(
      `/api/notes/folders${parentId == null ? '' : `?parent_id=${parentId}`}`,
      'GET',
      undefined,
      { cache: 'no-store' },
    )
    const rows = Array.isArray(data.folders) ? data.folders : []
    const withKids = []
    for (const row of rows) {
      if (cancelledRef.current) return []
      withKids.push({ ...row, children: await children(row.id) })
    }
    return withKids
  }
  return children(null)
}

/** Folders-before-notes, alphabetical: list_note_folders already returns
 * each level in that order, so a DFS preserves it. Strips the `children`
 * key off each folder before handing it to a row (a row never needs to know
 * its own subtree), depth starts at 0 for a top-level folder. */
function flattenTree(nodes, depth = 0, out = []) {
  for (const node of nodes) {
    const { children, ...folder } = node
    out.push({ folder, depth })
    if (children && children.length) flattenTree(children, depth + 1, out)
  }
  return out
}

function findNode(nodes, id) {
  for (const node of nodes) {
    if (node.id === id) return node
    if (node.children && node.children.length) {
      const found = findNode(node.children, id)
      if (found) return found
    }
  }
  return null
}

/** A folder's own id plus every descendant's, so a rename/recolor/move form
 * can refuse to offer "move into itself" or "move into its own child" as a
 * location option. The server (move_note_folder) enforces the same rule
 * with a WITH RECURSIVE ancestor walk regardless, this is just the UI not
 * showing an option it knows will bounce. */
function descendantIds(node) {
  const ids = new Set([node.id])
  for (const child of node.children || []) {
    for (const id of descendantIds(child)) ids.add(id)
  }
  return ids
}

/**
 * One row, reused for both the top-level folder picker and the location
 * picker inside the create/rename form. `folder` of `null` renders the
 * synthetic "All Notes" row (top-level / unfiled). Composition mirrors
 * NotesPage.jsx's NoteRow exactly: one main button that "opens" the row, an
 * optional row of small mutation actions next to it, each an independent
 * callback prop, no folder id encoded into the DOM to be re-parsed later.
 *
 * The color wash is the same --agent-style technique RosterPage.jsx's
 * .agent-card and MoneyPage.jsx's AccountRow (.money-position-row) already
 * use, at the identical 14%/34% color-mix ratios: --folder is set inline
 * here, ONLY when the row actually has a color, exactly like
 * MoneyPage.jsx:159's `account.color ? { '--account': account.color } :
 * undefined` -- var(--folder, transparent)'s fallback (styles.css) means an
 * uncolored folder paints no wash at all rather than a fake default color.
 */
function FolderRow({ folder, depth = 0, active = false, onOpen, onEdit, onDelete }) {
  const isRoot = folder == null
  const style = { '--depth': depth }
  if (!isRoot && folder.color) style['--folder'] = folder.color
  const name = isRoot ? 'All Notes' : folder.name
  return (
    <div className={`folder-row${active ? ' is-active' : ''}`} style={style}>
      <button type="button" className="folder-row-main" onClick={() => onOpen(folder)}>
        <span className="folder-row-name">{name}</span>
      </button>
      {!isRoot && (onEdit || onDelete) && (
        <div className="folder-row-actions">
          {onEdit && (
            <button type="button" aria-label={`Edit ${folder.name}`} onClick={() => onEdit(folder)}>
              &#9998;
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              className="folder-row-del"
              aria-label={`Delete ${folder.name}`}
              onClick={() => onDelete(folder)}
            >
              &#10005;
            </button>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The one folder-mutation surface for Notes (SPEC-v31 "UI/UX"): create,
 * rename, recolor, move (reparent), and delete, all inside the shared
 * <Sheet> primitive (SPEC-v29 Phase 3's binding law -- no bespoke inline
 * overlay). `variant="popover"` anchored to a trigger button is the
 * default, matching AgentChat.jsx's ContextSheet exactly; Sheet.jsx itself
 * downgrades to the phone bottom sheet below 901px, this component never
 * branches on width.
 *
 * Deliberately ONE component for both call sites named in the spec:
 *   - "browse into a folder": a caller opens this with `mode="browse"` and
 *     an `onSelectFolder` that changes its own folder/breadcrumb state.
 *   - "move this note to a folder": a caller opens this with `mode="move"`
 *     and an `onSelectFolder` that PATCHes one note's `folder_id`.
 * The component itself has no opinion on what "selecting a row" means --
 * that meaning lives entirely in the callback the caller passes in, the
 * same "one component, two uses" contract NoteRow's onOpen/onPin/onDelete
 * composition already demonstrates elsewhere in this file's own codebase.
 *
 * Props:
 *   open              boolean
 *   onClose           () => void
 *   mode              'browse' | 'move'  -- copy (title/hint text) plus
 *                     whether a row carries its edit/delete actions;
 *                     'move' is a filing gesture, so it offers neither.
 *                     Never branches the data flow itself.
 *   variant           Sheet variant, default 'popover'.
 *   anchor            forwarded to <Sheet anchor=...> for the popover.
 *   activeFolderId    number | null  -- which row (or "All Notes") reads as
 *                     currently selected. null means All Notes.
 *   contextFolderId   number | null | undefined  -- the folder Ian was
 *                     browsing when this sheet was opened, used only as the
 *                     default parent for a brand-new folder ("create inside
 *                     current folder"). Defaults to activeFolderId, so a
 *                     caller that only tracks one "current folder" concept
 *                     need not pass this separately.
 *   onSelectFolder    (folder: object|null) => void  -- fired when a row in
 *                     the top-level list is chosen. null means All Notes.
 *   onMutated         () => void | undefined  -- fired after any create,
 *                     rename, recolor, move, delete, or undo-restore
 *                     actually changes the folders table, so a caller
 *                     holding its own folder/breadcrumb cache knows to
 *                     refetch it.
 *   onFolderDeleted   (folderId: number) => void | undefined  -- fired
 *                     right after a delete succeeds (before the undo
 *                     window), so a caller currently browsing the deleted
 *                     folder can navigate back to All Notes instead of
 *                     showing a folder that no longer exists.
 *   toast             (message, level, undo?) => void  -- this app's
 *                     existing toast/undo pattern (App.jsx's toast()).
 *   emptyTitle/emptyBody  strings shown when zero folders exist yet (osui's
 *                     zero-value-pixel law: no fabricated "0 folders"
 *                     counter). Props, not a hardcoded string, since this
 *                     component does not own NotesPage.jsx's existing
 *                     empty-state copy and a later wiring stage may want to
 *                     hand in that exact wording instead.
 */
export default function NoteFolderSheet({
  open,
  onClose,
  mode = 'browse',
  variant = 'popover',
  anchor = null,
  activeFolderId = null,
  contextFolderId = activeFolderId,
  onSelectFolder,
  onMutated,
  onFolderDeleted,
  toast,
  emptyTitle = 'No folders yet',
  emptyBody = 'Select "+ New folder" below to make one.',
}) {
  const [view, setView] = useState('list') // 'list' | 'form'
  const [tree, setTree] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const cancelledRef = useRef(false)

  function load() {
    cancelledRef.current = false
    setLoading(true)
    setError('')
    return fetchFolderTree(cancelledRef)
      .then((t) => { if (!cancelledRef.current) setTree(t) })
      .catch((err) => { if (!cancelledRef.current) setError(err.message || 'Could not load folders') })
      .finally(() => { if (!cancelledRef.current) setLoading(false) })
  }

  // Re-seed on every open, the BudgetCategorySheet.jsx precedent: a stale
  // fetch resolving after a previous close/reopen must never render last
  // session's tree, and the sheet always starts back on the list view.
  useEffect(() => {
    if (!open) return undefined
    setView('list')
    load()
    return () => { cancelledRef.current = true }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const flatRows = useMemo(() => flattenTree(tree), [tree])

  const excludedIds = useMemo(() => {
    if (!draft.id) return new Set()
    const node = findNode(tree, draft.id)
    return node ? descendantIds(node) : new Set([draft.id])
  }, [draft.id, tree])

  const locationRows = useMemo(
    () => flatRows.filter((r) => !excludedIds.has(r.folder.id)),
    [flatRows, excludedIds],
  )

  function openCreate() {
    setDraft({ ...EMPTY_DRAFT, parentId: contextFolderId ?? null })
    setView('form')
  }

  function openEdit(folder) {
    setDraft({
      id: folder.id,
      name: folder.name,
      color: folder.color || '',
      parentId: folder.parent_id ?? null,
    })
    setView('form')
  }

  async function save() {
    const name = draft.name.trim()
    if (!name) { toast?.('a folder needs a name', 'warn'); return }
    setSaving(true)
    try {
      if (draft.id) {
        const original = findNode(tree, draft.id)
        const fields = {}
        if (!original || name !== original.name) fields.name = name
        const color = draft.color || null
        if (!original || color !== (original.color || null)) fields.color = color
        if (!original || draft.parentId !== (original.parent_id ?? null)) fields.parent_id = draft.parentId
        if (Object.keys(fields).length) {
          await api(`/api/notes/folders/${draft.id}`, 'PATCH', fields)
        }
      } else {
        await api('/api/notes/folders', 'POST', { name, parent_id: draft.parentId, color: draft.color || null })
      }
      await load()
      setView('list')
      onMutated?.()
    } catch (err) {
      toast?.(err.message || 'Could not save this folder', 'warn')
    } finally {
      setSaving(false)
    }
  }

  // No confirm dialog (osui bans them for reversible destructive actions):
  // this fires the delete immediately and leans on the undo toast instead.
  // The count is composed from delete_note_folder_cascade's own response
  // (api/main.py's folder_count/note_count), never guessed client-side, so
  // "and 2 subfolders and 12 notes" is only said when it is actually true.
  async function removeFolder(folder) {
    try {
      const result = await api(`/api/notes/folders/${folder.id}`, 'DELETE')
      await load()
      onFolderDeleted?.(folder.id)
      const subCount = Math.max(0, (result.folder_count || 1) - 1)
      const parts = []
      if (subCount > 0) parts.push(`${subCount} subfolder${subCount === 1 ? '' : 's'}`)
      if (result.note_count > 0) parts.push(`${result.note_count} note${result.note_count === 1 ? '' : 's'}`)
      const msg = parts.length ? `deleted "${folder.name}" and ${parts.join(' and ')}` : `deleted "${folder.name}"`
      toast?.(msg, 'good', async () => {
        await api(`/api/notes/folders/restore/${result.deleted_batch_id}`, 'POST')
        await load()
        onMutated?.()
      })
      onMutated?.()
    } catch (err) {
      toast?.(err.message || 'Could not delete this folder', 'warn')
    }
  }

  const sheetTitle = view === 'form'
    ? (draft.id ? 'Edit Folder' : 'New Folder')
    : (mode === 'move' ? 'Move to Folder' : 'Folders')

  return (
    <Sheet open={open} onClose={onClose} title={sheetTitle} variant={variant} anchor={anchor}>
      {view === 'list' && (
        <>
          {mode === 'move' && <p className="dim folder-sheet-hint">Choose a folder for this note.</p>}
          {loading && <p className="dim">Loading folders…</p>}
          {!loading && error && <p className="ask-agent-error" role="alert">{error}</p>}
          {!loading && !error && (
            <div className="folder-list" role="group" aria-label="Folders">
              <FolderRow
                folder={null}
                active={activeFolderId == null}
                onOpen={() => onSelectFolder?.(null)}
              />
              {flatRows.length === 0 ? (
                <div className="empty folder-empty">
                  <div className="empty-title">{emptyTitle}</div>
                  <p>{emptyBody}</p>
                </div>
              ) : (
                flatRows.map(({ folder, depth }) => (
                  <FolderRow
                    key={folder.id}
                    folder={folder}
                    depth={depth}
                    active={activeFolderId === folder.id}
                    onOpen={() => onSelectFolder?.(folder)}
                    // Managing folders is the browse sheet's job. "Move to
                    // Folder" is a filing gesture, and putting a cascade
                    // delete (folder plus every note under it) one mis-tap
                    // from the row you meant to file into breaks osUI L5's
                    // "destructive actions never adjacent to frequent ones".
                    onEdit={mode === 'move' ? undefined : openEdit}
                    onDelete={mode === 'move' ? undefined : removeFolder}
                  />
                ))
              )}
            </div>
          )}
          <div className="folder-form-actions">
            <button type="button" className="btn add-goal" onClick={openCreate} disabled={loading}>
              + New folder
            </button>
          </div>
        </>
      )}

      {view === 'form' && (
        <>
          <div className="gf-row">
            <label className="gf-field gf-grow">
              <span>Name</span>
              <input
                value={draft.name}
                autoFocus
                placeholder="e.g. Clockwork"
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              />
            </label>
          </div>

          <section className="folder-form-section">
            <h3 className="folder-form-label">Color</h3>
            <div className="folder-color-swatches" role="group" aria-label="Folder color">
              {FOLDER_COLORS.map((c) => (
                <button
                  key={c.hex}
                  type="button"
                  className={`folder-color-swatch${draft.color === c.hex ? ' is-on' : ''}`}
                  style={{ '--swatch': c.hex }}
                  aria-pressed={draft.color === c.hex}
                  aria-label={c.name}
                  title={c.name}
                  // Tapping the already-picked swatch clears it back to no
                  // color, rather than needing a dedicated "None" swatch.
                  onClick={() => setDraft((d) => ({ ...d, color: d.color === c.hex ? '' : c.hex }))}
                />
              ))}
            </div>
          </section>

          <section className="folder-form-section">
            <h3 className="folder-form-label">Location</h3>
            <div className="folder-location-list" role="group" aria-label="Folder location">
              <FolderRow
                folder={null}
                active={draft.parentId == null}
                onOpen={() => setDraft((d) => ({ ...d, parentId: null }))}
              />
              {locationRows.map(({ folder, depth }) => (
                <FolderRow
                  key={folder.id}
                  folder={folder}
                  depth={depth}
                  active={draft.parentId === folder.id}
                  onOpen={() => setDraft((d) => ({ ...d, parentId: folder.id }))}
                />
              ))}
            </div>
          </section>

          <div className="folder-form-actions">
            <button type="button" className="btn ghost" onClick={() => setView('list')} disabled={saving}>
              Back
            </button>
            <button type="button" className="btn" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </>
      )}
    </Sheet>
  )
}
