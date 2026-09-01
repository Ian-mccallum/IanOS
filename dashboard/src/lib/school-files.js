export const SCHOOL_FILE_MAX_BYTES = 25 * 1024 * 1024

export const SCHOOL_FILE_KINDS = {
  pdf: { label: 'PDF', extensions: ['pdf'], mime: ['application/pdf'] },
  slides: {
    label: 'Slides',
    extensions: ['ppt', 'pptx'],
    mime: [
      'application/vnd.ms-powerpoint',
      'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ],
  },
  docs: {
    label: 'Docs',
    extensions: ['doc', 'docx'],
    mime: [
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ],
  },
  sheets: {
    label: 'Sheets',
    extensions: ['xls', 'xlsx'],
    mime: [
      'application/vnd.ms-excel',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    ],
  },
  image: {
    label: 'Images',
    extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'heic', 'heif', 'bmp', 'tif', 'tiff'],
    mime: [
      'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/heic',
      'image/heif', 'image/bmp', 'image/tiff',
    ],
  },
  text: { label: 'Text', extensions: ['txt', 'md', 'markdown'], mime: ['text/plain', 'text/markdown', 'text/x-markdown'] },
  other: { label: 'Other', extensions: [], mime: [] },
}

export const SCHOOL_FILE_ACCEPT = Object.values(SCHOOL_FILE_KINDS)
  .flatMap((kind) => [...kind.extensions.map((extension) => `.${extension}`), ...kind.mime])
  .join(',')

function extension(value) {
  const parts = String(value || '').toLowerCase().split('.')
  return parts.length > 1 ? parts[parts.length - 1] : ''
}

/** Deterministic type projection from safe server metadata or a local File.
 * The server independently validates it before ever writing a byte. */
export function schoolFileKind({ display_name, name, mime_type, type, category } = {}) {
  const safeCategory = String(category || '').toLowerCase()
  if (SCHOOL_FILE_KINDS[safeCategory]) return safeCategory
  const ext = extension(display_name || name)
  const mime = String(mime_type || type || '').toLowerCase()
  return Object.entries(SCHOOL_FILE_KINDS).find(([, kind]) => (
    kind.extensions.includes(ext) || kind.mime.includes(mime)
  ))?.[0] || 'other'
}

export function isUploadableSchoolFile(file) {
  return Boolean(file) && schoolFileKind(file) !== 'other'
}

export function schoolFileSizeLabel(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(bytes >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}
