/**
 * Upload one image to POST /api/notes/{note_id}/attachments (SPEC-v31).
 * Raw fetch + FormData, not lib/api.js's `api()` helper -- that helper
 * always JSON.stringifies its body, which cannot carry multipart file data.
 * Mirrors dashboard/src/components/journal/Composer.jsx's own upload call
 * (same FormData shape, same "file" field name, same raw-fetch pattern) --
 * verified against api/main.py's `note_attachment_upload(note_id, file:
 * UploadFile = File(...))`, so the field name is not a guess.
 *
 * Resolves to the created attachment row
 * ({id, note_id, token, path, kind, width, height, created_at, deleted_at}),
 * or throws with the server's `detail` message on failure (400 wrong
 * extension, 404 note not found, 413 too large).
 */
export async function uploadNoteAttachment(noteId, file) {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`/api/notes/${noteId}/attachments`, { method: 'POST', body: fd })
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail
    const msg = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : `${r.status}`
    throw new Error(msg || `${r.status}`)
  }
  return r.json()
}

/** Only files this note's own upload whitelist accepts (api/main.py's
 * _NOTES_PHOTO_EXT); anything else is rejected client-side before spending
 * a round trip on a 400.
 *
 * The extension fallback is not belt-and-braces, it is the primary path on
 * a phone: a file the OS reports with an EMPTY `type` (iOS hands back "" for
 * HEIC often enough, and any file arriving from a share sheet or a synced
 * folder can) used to be filtered out silently, so the picker looked like
 * it simply did nothing. The server re-checks the extension anyway, so a
 * mislabelled file costs one 400, never a bad write. */
const IMAGE_TYPE_RE = /^image\//
const IMAGE_EXT = new Set(['jpg', 'jpeg', 'png', 'heic', 'webp', 'gif'])

export function isUploadableImage(file) {
  if (!file) return false
  if (IMAGE_TYPE_RE.test(file.type || '')) return true
  const ext = (file.name || '').split('.').pop()
  return !!ext && IMAGE_EXT.has(ext.toLowerCase())
}
