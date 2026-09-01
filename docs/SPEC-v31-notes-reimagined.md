# SPEC v31: Notes, reimagined

Status: **spec only, implementation deferred**. Ian explicitly chose "spec
first, build later" for this one. Born from a judge-panel workflow: three
independently-lensed proposals ("Verbatim," "ianOS-native," "agent-aware"),
scored and synthesized by a fourth agent that re-verified every citation
against source. Winner: **ianOS-native**. This document is my own synthesis
on top of that judging, re-verified again before writing it down.

## Ian's own words, verbatim

"i want the notes to be better as well. i want it to be exactly like apple
notes, with image featuring stuff like that ... i genuinely want folder
capabilites and everything. it should be highly advanced." Confirmed scope
for this pass: **nested folders, inline images, and basic rich text**
(bold/italic/lists/checklists) — not tags, smart folders, full-text search,
sketches, scanning, or collaboration. Those are explicitly out of scope,
not forgotten.

## Why "ianOS-native" won, not "Verbatim"

The literal-fidelity direction ("Verbatim") proposed a permanent folder
sidebar on desktop, matching Notes.app's own always-visible tree. Verified
directly against `PRODUCT.md`'s own Anti-references section: it names
**"gray sidebars... SaaS admin panel energy"** as a banned pattern. No other
surface in this app carries a persistent tree nav, and `NotesPage.jsx`'s own
existing code comment already frames desktop as "the enhancement," not a
chrome-upgrade opportunity. A faithful port that never checks itself against
the product's own stated visual law is the wrong trade. "Verbatim" also
proposed a structured JSON document body (matching Apple's own
NSAttributedString model) that admits, in its own text, an unresolved
regression: `list_notes`'s plain `LIKE` search stops reliably finding a word
inside nested JSON. The winning direction's Markdown-in-TEXT answer has no
such gap, for reasons tied to real existing code, not a general preference
(see Rich text below).

The third direction ("agent-aware") made the sharpest single catch of the
three — that `chat_write_note` (SPEC-v29 Phase 6) is a real, narrow,
existing write path that predates and evades the "no writing counterpart
anywhere" comment and its own test — but its own agent-visibility answer
contradicted itself: it claimed images stay invisible via "absence, not
redaction," while its own rich-text section commits `read_notes` to shipping
the raw body straight through, which would leak the inline image token (and
any caption) as plain text. That real catch is carried into this document;
the contradiction is not.

## Architecture

### Folders: a new self-referencing table, zero-touch migration

```sql
CREATE TABLE IF NOT EXISTS note_folders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    parent_id        INTEGER REFERENCES note_folders(id),  -- NULL = top-level
    color            TEXT,                                  -- closed palette key
    position         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at       TEXT,
    deleted_batch_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_note_folders_parent ON note_folders(parent_id, deleted_at);
```

`notes` gains two nullable columns, `folder_id INTEGER REFERENCES
note_folders(id)` and `deleted_batch_id TEXT`, through `_migrate_columns`'s
plain ADD-COLUMN loop (`core/db.py:660-716`) — the exact mechanism that
already added `goals.hero`, `goals.depends_on_goal_id` (a self-reference,
no CHECK), and `agent_invocations.parent_id` (a self-referencing FK, no
CHECK). Verified: neither new column carries a CHECK, so this is **not**
the SQLite full-table-rebuild trap (`_migrate_goals_school_domain`,
`core/db.py:718-747`) that a CHECK-widening column requires. No table
rebuild, no downtime, no special-cased migration function beyond the
existing loop.

**Migration for the ~existing rows costs nothing.** A nullable `folder_id`
defaults to NULL on ADD COLUMN, and NULL already means "unfiled / All
Notes" with zero backfill required — no synthetic root folder row to
insert, no UPDATE, no partial-failure risk. (The losing "Verbatim"
direction proposed seeding a literal root folder and reassigning every
existing row to it — real, avoidable migration risk for no functional
gain, since NULL already does that job for free.)

**Cycle prevention is enforced in code, never in the schema** — SQLite
cannot declaratively forbid a self-reference cycle. `move_note_folder(conn,
folder_id, new_parent_id)` walks `new_parent_id`'s ancestor chain with a
`WITH RECURSIVE` CTE and refuses the move if `folder_id` appears in it or
equals it. Same "guardrails live in code" discipline `all_goals()`'s
archived filter and `_lead_filter()` already use.

**Cascade delete/restore reuses this codebase's one real precedent for
exactly this shape**, verified line-for-line: `archive_partner_task`/
`restore_partner_archive` (`core/db.py:3637-3714`). `delete_note_folder_cascade(conn,
folder_id)` walks the full descendant closure (folders and notes) via
`WITH RECURSIVE`, stamping every affected row in both tables with one
shared `deleted_batch_id` — a random token (matching the same generation
style as attachment tokens below), **not** a timestamp match, which risks
collision when two deletes land in the same second. `restore_note_folder_cascade(conn,
batch_id)` reverses by matching that id exactly, generalizing partner's
one-level walk to arbitrary depth. Partner's `PartnerHierarchyConflict`
restore-order guard is deliberately dropped: a note whose folder is still
independently deleted just shows unfiled until re-filed, a harmless state
with none of partner's progress-math dependency.

**`domain` stays completely untouched** (`core/db.py:415`). Verified zero
live readers today: `read_notes` never projects it, `list_notes` never
filters on it, `NotesPage.jsx` never sends or displays it. It remains what
its own comment says — a dormant routing hook for a future agent read,
orthogonal to Ian's own filing tree. Folding the two together would either
collapse an arbitrarily-deep folder tree onto five fixed enum values, or
give every folder implicit agent-routing meaning Ian never consented to.
Keep them separate. `chat_write_note`'s tool schema stays exactly `{body,
domain}` — see Agent visibility for why it never gains a `folder_id`.

**Color** reuses the exact `--agent-soft`/`--agent-line` `color-mix`
formula already in production (`styles.css:3005-3011`, 14%/34% mixes) via
a new `--folder` custom property, set inline the same way `RosterPage.jsx:23`
sets `--agent`. A closed set of keys, not a free hex field.

**Ordering**: folders before notes at every level, alphabetical by
default, matching the confirmed "no smart folders" scope cut. `position`
exists in the schema for a later drag-to-reorder pass but is not required
to ship this one — named and deferred, not silently dropped.

### Images: a new child table, caption lives in exactly one place

```sql
CREATE TABLE IF NOT EXISTS note_attachments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id     INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    token       TEXT NOT NULL UNIQUE,   -- opaque id embedded in body text
    path        TEXT NOT NULL,          -- ROOT-relative, data/notes/YYYY/MM/<note_id>-<token>.<ext>
    kind        TEXT NOT NULL DEFAULT 'photo',
    width       INTEGER,
    height      INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_note_attachments_note ON note_attachments(note_id, deleted_at);
```

A note routinely needs many images at different points in one body — the
same one-to-many shape `lead_touches`→`leads` already uses, not
`journal_entries`' single `media_path`/`media_kind` columns (that table is
genuinely 1:1, one day, at most one photo; a note is not).

**Deliberately no `caption`/`alt_text` column.** One of the three
brainstormed directions stored caption text both as a DB column and inline
in the Markdown embed's quoted string — two copies of one fact with no
stated sync rule, exactly the drift the data skill's single-read-path law
warns against. Caption lives in exactly one place: the note body's own
Markdown, `![caption](note-image:TOKEN)` — standard syntax any editor
library already parses and re-serializes.

**Storage: its own tree, `data/notes/YYYY/MM/<note_id>-<token>.<ext>`**,
gitignored, deliberately never inside `data/journal/` even though the
month-sharding shape is copied verbatim from it. Journal is this app's
privacy-critical tree (no agent tool and no non-journal route points at
it); a physically separate directory keeps that distinction legible on
disk, not just in code, and forecloses a future accidental cross-wire.
**`data/notes/` must be added to `.gitignore` and to `scripts/backup.sh`'s
`paths` array in the same commit that creates it** — the data skill's D9
law ("a new directory rides free inside nothing") applies here exactly as
documented.

Upload reuses journal's already-correct streamed-write pattern nearly
verbatim: stream to disk in chunks, reject and unlink an oversized file
with a real error rather than silent truncation, store the
`dest.relative_to(ROOT)` path, name the file `{note_id}-{token_hex(4)}.{ext}`.
Cap at 25MB (photos only, no video — Ian's own wording named "image," not
video). Its own independent extension whitelist (jpg/jpeg/png/heic/webp/gif),
not a shared import of journal's, so a future widening of one whitelist
can never silently widen the other across the privacy boundary.

Upload flow is **picker-first**, per osui's mobile-first law: a hidden
`<input type="file" accept="image/*" multiple>` behind a toolbar glyph is
the primary path everywhere, including iOS's native camera/photo-library
sheet. Drag-drop onto the editor and clipboard paste are desktop-only
enhancement-layer additions on top, never the only path.

**Position in the text flow lives in the body text itself** — the token
embed sits exactly where the cursor was on insert, no stored order integer
to keep in sync, reordering an image is just reordering text. A new
`GET /api/notes/attachments/{token}` mirrors `/api/journal/media/{entry_id}`
exactly: resolve the stored path only, from server state, confirm the
token's `note_id` belongs to a live note, no client input, no traversal.
Deleting an attachment from the body soft-deletes the row lazily on next
autosave; a stray token left behind renders as a broken-image placeholder
rather than silently collapsing, so surrounding text never jumps.

### Rich text: Markdown-in-TEXT, not a JSON document tree

`notes.body` stays a single TEXT column. Its contract becomes a
**constrained Markdown dialect**: `**bold**`, `*italic*`, `- `/`1. ` lists,
`- [ ]`/`- [x]` checklists, `![caption](note-image:TOKEN)` inline images.
Explicitly not a structured JSON document (ProseMirror/Slate/Lexical's
native shape) and not raw HTML. Four reasons, each tied to code actually
read for this spec, not a general preference:

1. **Zero migration for existing content.** Every note row today is already
   valid plain text, a strict subset of Markdown. A JSON-tree body would
   need every historical row rewritten before a new editor could open a
   single old note.
2. **`note_title_from` already half-expects it.** Verified:
   `line.strip().lstrip('#').strip()` (`core/db.py:2749-2756`) already
   strips a leading `#` before deriving the stored title. Markdown needs
   zero changes here; a JSON tree would need an entirely different
   first-block traversal.
3. **`read_notes` needs no translation layer for text.** Verified:
   `agents/runner.py:673-684` ships `body` to chief/archivist as a plain
   string with zero transform today. Markdown stays exactly as agent-legible
   as plain text; a JSON tree would need a bespoke flatten step invented for
   no other reason than making an agent able to read it.
4. **Search stays a one-line `LIKE`.** Verified: `list_notes`'s search
   (`title LIKE ? OR body LIKE ?`, `core/db.py:2807-2809`) keeps working
   unmodified over Markdown text, including inside a checklist item or a
   bold span. A JSON tree breaks that substring search entirely and forces
   a second plain-text projection column — exactly the extra read path the
   data skill's single-read-path law (D5) warns against.

The grammar is **closed and validated server-side on write**: reject or
strip anything outside the six node kinds above (raw HTML tags, tables,
footnotes, anything else). Same "closed, versioned, validated shape"
discipline CLAUDE.md already states for `create_proposal` drafts and chat's
model/effort CHECK enums — without needing a full node-tree parser or a
bespoke agent-facing flatten step to get there.

Checklist toggling is a one-character body mutation (`- [ ]` → `- [x]`)
through the exact same autosave PATCH path already in production
(`NotesPage.jsx:70-85`, 600ms debounce) — no new endpoint, no new column.
A checklist item has no independent identity worth its own row (it can't
be reordered or queried independent of its paragraph), the same
"events over ceremony" instinct that keeps `streak_events`/`lead_touches`
as append-only logs rather than mutable counters.

**Editor library choice is implementation's call, not this spec's**,
exactly as scoped. The binding, spec-level commitment is the wire format
alone: whatever renders the toolbar must serialize to and parse from this
one Markdown string on `PATCH /api/notes/{id}` — no new body-shaped
column, no second table for "formatted content." The rendering requirement
is touch-first WYSIWYG at 375px (bold looks bold as you type, a checked
box strikes through), never a raw-Markdown `<textarea>` the way
`NotesPage.jsx:163-170` works today. The formatting toolbar rides the
`--kb` keyboard-inset custom property this repo already built (commit
`fa4e33c`) rather than re-deriving keyboard-avoidance math.

### Agent visibility: the wall's shape doesn't move, one real narrowing gets wired in

Ground truth, verified directly: `NOTE_READERS = {"chief", "archivist"}`
(`agents/runner.py:80`), enforced twice — once via each role's `ALLOWLISTS`
entry, once inside `read_notes` itself — the same belt-and-braces shape
`PIPELINE_READERS` uses. `read_notes`'s current payload is exactly
`{title, body, updated_at}` per note. There is no *nightly* writing
counterpart. This pass leaves `NOTE_READERS`, its double enforcement, and
`read_notes`'s top-level key shape completely unchanged.

**A stale claim gets corrected, not perpetuated.** The comment at
`core/db.py:2743-2744` ("there is no writing counterpart anywhere") and
`tests/test_notes.py::test_no_agent_can_write_a_note` both predate
`chat_write_note` (`agents/runner.py:860-874`, SPEC-v29 Phase 6's
instant-write exception) — verified directly: the test greps for
`@tool("write_note`/`@tool("create_note`/etc. and scans `ALLOWLISTS` for
tools ending in `_note`/`_notes`, and `chat_write_note` matches neither
pattern (it lives in the separate `INSTANT_WRITE_TOOLS` set, never in
`ALLOWLISTS`). This is a real, narrow, human-triggered write path the
test's pattern-matching doesn't catch, not a security hole (it's exactly
the deliberate SPEC-v29 exception, correctly walled by its own separate
mechanism) but a comment and a test that no longer describe reality.
**Required fix**: correct the comment to say "no *nightly* writing
counterpart, and the one instant-write exception is schema-frozen," and
add a test asserting `chat_write_note`'s tool schema stays exactly `{body,
domain}` forever — no `folder_id` ever — so the wall's real shape stays
legible in code instead of drifting further under an outdated docstring.

**Folders: not exposed.** No `folder_id`, no folder name, added to
`read_notes`'s payload. A folder's name could itself be sensitive in a way
the original SPEC-v10 grant never anticipated (a folder named after a
person, a health matter, a legal situation), and neither chief's nightly
brief nor archivist's distillation job needs it to do their jobs.

**Images: the one place a narrowing must be actively engineered, not
merely asserted.** Because `read_notes` ships `body` straight through with
zero transform, the raw Markdown embed token (and any inline caption)
would otherwise leak into chief/archivist's context exactly like the rest
of the text. `read_notes` must run `body` through a resolve pass before
returning it: every `![caption](note-image:TOKEN)` becomes its caption
text if Ian wrote one, or a bare `[image]` placeholder if he didn't — never
bytes, paths, or dimensions. Mirrors `journal.agent_signal()`'s "a count,
never the picture" precedent and `read_pipeline`'s withheld run/heat data.
Implement as a pure function in a new `core/notes.py` (a sibling to
`core/journal.py`/`core/plan.py`), called from `read_notes`, not inline
regex inside the tool body — the same "date math precomputed in Python,
never left to the model" precedent CLAUDE.md states elsewhere.

`chat_write_note`'s tool schema stays exactly `{body, domain}`, gaining no
`folder_id` parameter — a chat-created note lands unfiled, never a folder
chosen as a side effect of writing text, matching `INSTANT_WRITE_TOOLS`'s
own closed-set discipline: the fix for "chat should not silently reorganize
Ian's filing system" is the one already used everywhere else in this
codebase for that shape of problem — no tool exists for it, not a blocked
one.

Net effect: `read_notes`'s returned keys and reader set are byte-for-byte
unchanged. The only new code is one resolve pass over `body` immediately
before it's handed back — and that pass is where this feature's one real
narrowing decision actually lives, wired in, not just claimed.

### UI/UX: no new tab, no permanent sidebar, the existing patterns extended

Notes stays exactly where it lives today: behind More, not a sixth tab
(`Nav.jsx:18`, `section: 'system'`; `App.jsx`'s `PAGES` includes `notes`,
`TAB_PAGES` does not). Folders are page-internal state (a new `folderId`
alongside the existing `open` note state), never a navigation-law change.

A permanent desktop folder sidebar is explicitly rejected — see "Why
ianOS-native won" above. Instead: a slim breadcrumb line above the search
bar ("All Notes › Clockwork › Leases"), defaulting to today's unscoped "All
Notes" view unchanged. On phone, opening a folder pushes a screen reusing
the exact existing `‹ Notes` back-chevron pattern (`NotesPage.jsx:159-160`,
`.note-back`) one level deeper per folder. On desktop (≥901px, the existing
two-pane breakpoint), the breadcrumb stays persistently visible above the
list pane instead of a back button, since that pane already has the width
for it.

All folder mutation (create, rename, move-to, color, delete) routes
through the existing `<Sheet>` primitive: `variant="popover"` anchored to a
"+"/"Move to folder" control on desktop, the phone bottom-sheet everywhere
else. This is SPEC-v29 Phase 3's own binding law — every overlay in this
codebase migrates onto `<Sheet>` — and a bespoke inline-rename affordance
here would be exactly the regression that spec exists to prevent. Folder
rows use the `--folder` color-wash technique described above, one governed
palette, not a new color picker.

Folder delete carries no confirm dialog (osui bans them for reversible
destructive actions); the existing soft-delete-plus-undo-toast idiom
(`NotesPage.jsx:106-117`) fires with an honest count ("deleted 'Groceries'
and 12 notes"), and Undo restores the entire cascade atomically via the
`deleted_batch_id` match. New-note creation keeps the exact one-tap "✎ New"
flow (`NotesPage.jsx:87-94`, no dialog, no title field): created while
browsing a folder, it's pre-filed there with zero interruption; from "All
Notes," it's unfiled, same as every note today. Image insertion is the
toolbar-glyph picker as the phone-first primary path, drag-drop/paste as
the desktop-only layer on top; images render inline at natural aspect
ratio using stored `width`/`height` to reserve layout before load, and
tapping one opens it full-bleed via `Sheet variant="dialog"` with a delete
control. Empty folders reuse the existing empty-state card rather than a
fabricated "0 notes" counter, honoring osui's zero-value-pixel law.

## Explicitly out of scope for this pass

Tags, smart folders, full-text search beyond the existing `title LIKE ?
OR body LIKE ?`, sketches, document scanning, collaboration/sharing. Named
here so a future implementer doesn't quietly widen scope mid-build; each
of these is a legitimate follow-up spec of its own, not a forgotten
requirement.

## What implementation will need to get right, named in advance

1. The `_migrate_columns` additions (`note_folders`, `notes.folder_id`,
   `notes.deleted_batch_id`) and the two new tables' `CREATE TABLE`
   statements.
2. `move_note_folder()`'s cycle guard, and `delete_note_folder_cascade()`/
   `restore_note_folder_cascade()`'s batch-id-based cascade, mirroring
   `archive_partner_task`/`restore_partner_archive` but generalized to
   arbitrary depth via `WITH RECURSIVE`.
3. `data/notes/` added to `.gitignore` and `scripts/backup.sh` in the same
   commit that starts writing to it.
4. The `core/notes.py` resolve-pass function, wired into `read_notes`
   before any other change to that tool ships, not after.
5. The corrected comment and the new schema-frozen test for
   `chat_write_note`.
6. Server-side validation rejecting any Markdown construct outside the six
   closed node kinds.
