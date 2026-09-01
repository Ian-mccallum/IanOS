import React, { Fragment } from 'react'

/**
 * The slim "All Notes › Clockwork › Leases" line (SPEC-v31 "UI/UX"), the
 * direct replacement for a permanent folder sidebar -- PRODUCT.md's own
 * Anti-references section bans exactly that shape ("gray sidebars... SaaS
 * admin panel energy"), and no other surface in this app carries a
 * persistent tree nav.
 *
 * Desktop-only by design, not by accident: the spec is explicit that on
 * phone, opening a folder pushes a screen reusing the existing `‹ Notes`
 * back-chevron pattern (NotesPage.jsx's `.note-back`) one level per folder,
 * and this line "stays persistently visible" only "on desktop (>=901px, the
 * existing two-pane breakpoint)... since that pane already has the width
 * for it." Rendering both at once on a phone would be a second, redundant
 * nav for the same one decision, so `.note-breadcrumb`'s only display rule
 * lives behind a min-width query (styles.css) -- this component always
 * renders its markup, CSS alone decides whether it is ever seen, the same
 * "hidden only by a min-width query" law the mobile tab bar itself follows.
 *
 * Purely presentational, no fetching of its own: the ancestor chain is
 * supplied as `path`, since a later NotesPage wiring stage already holds
 * (or can trivially derive from) the folder tree this same feature's
 * NoteFolderSheet fetches, and inventing a second "get ancestors" read path
 * here would just be a second source of truth for one fact.
 *
 * Props:
 *   path          Array<{id, name, color}>  ancestors from the top-level
 *                 folder down to and including the folder currently open.
 *                 Empty (or omitted) means All Notes itself is current.
 *   onNavigate    (folderId: number|null) => void  -- fired when a
 *                 non-current crumb is chosen. null means All Notes.
 *   onOpenFolders (() => void) | undefined  -- optional trailing "Folders"
 *                 control that opens NoteFolderSheet in browse mode.
 *                 Omitted entirely (not disabled) when the caller has none,
 *                 the same convention AccountSheet.jsx's optional props use.
 */
export default function NoteBreadcrumb({ path = [], onNavigate, onOpenFolders }) {
  const atRoot = path.length === 0

  return (
    <nav className="note-breadcrumb" aria-label="Folder path">
      <div className="note-breadcrumb-trail">
        <button
          type="button"
          className={`note-breadcrumb-crumb${atRoot ? ' is-current' : ''}`}
          onClick={() => onNavigate?.(null)}
          disabled={atRoot}
          aria-current={atRoot ? 'page' : undefined}
        >
          All Notes
        </button>
        {path.map((folder, i) => {
          const isLast = i === path.length - 1
          return (
            <Fragment key={folder.id}>
              <span className="note-breadcrumb-sep" aria-hidden="true">›</span>
              <button
                type="button"
                className={`note-breadcrumb-crumb${isLast ? ' is-current' : ''}`}
                onClick={() => onNavigate?.(folder.id)}
                disabled={isLast}
                aria-current={isLast ? 'page' : undefined}
              >
                {isLast && folder.color && (
                  <span className="note-breadcrumb-dot" style={{ background: folder.color }} aria-hidden="true" />
                )}
                {folder.name}
              </button>
            </Fragment>
          )
        })}
      </div>
      {onOpenFolders && (
        <button type="button" className="note-breadcrumb-manage" onClick={onOpenFolders}>
          Folders
        </button>
      )}
    </nav>
  )
}
