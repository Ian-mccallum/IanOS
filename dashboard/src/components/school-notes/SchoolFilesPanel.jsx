import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  isUploadableSchoolFile,
  SCHOOL_FILE_ACCEPT,
  SCHOOL_FILE_KINDS,
  SCHOOL_FILE_MAX_BYTES,
  schoolFileKind,
  schoolFileSizeLabel,
} from '../../lib/school-files.js'

function fileDate(value) {
  const parsed = value ? new Date(value) : null
  if (!parsed || Number.isNaN(parsed.getTime())) return ''
  return new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' }).format(parsed)
}

async function schoolFileRequest(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options })
  if (!response.ok) {
    const detail = (await response.json().catch(() => ({}))).detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : ''
    throw new Error(message || `Could not complete the file request (${response.status})`)
  }
  return response.json().catch(() => ({}))
}

function KindFilter({ active, onChange, counts }) {
  const filters = ['all', 'pdf', 'slides', 'docs', 'sheets', 'image', 'text']
  return (
    <div className="school-files-filters" aria-label="Filter class files">
      {filters.map((kind) => {
        const selected = active === kind
        const label = kind === 'all' ? 'All' : SCHOOL_FILE_KINDS[kind].label
        return (
          <button
            key={kind}
            type="button"
            className={`school-files-filter${selected ? ' active' : ''}`}
            aria-pressed={selected}
            onClick={() => onChange(kind)}
          >
            {label}{counts[kind] ? ` ${counts[kind]}` : ''}
          </button>
        )
      })}
    </div>
  )
}

function FileRow({ asset, onDelete, deleting }) {
  const kind = schoolFileKind(asset)
  const label = SCHOOL_FILE_KINDS[kind].label
  const fileUrl = `/api/school/assets/${asset.id}/download`
  return (
    <li className="school-file-row">
      <span className={`school-file-kind kind-${kind}`} aria-label={`${label} file`}>{label}</span>
      <div className="school-file-copy">
        <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="school-file-name" title={asset.display_name}>
          {asset.display_name}
        </a>
        <span className="school-file-meta">
          {schoolFileSizeLabel(asset.byte_size)}{asset.created_at ? ` · ${fileDate(asset.created_at)}` : ''}
          {asset.session_id ? ' · This note' : ''}
        </span>
      </div>
      <div className="school-file-actions">
        <a href={fileUrl} target="_blank" rel="noopener noreferrer" className="school-file-open">Open</a>
        <button
          type="button"
          className="school-file-delete"
          onClick={() => onDelete(asset)}
          disabled={deleting}
          aria-label={`Delete ${asset.display_name}`}
        >
          Delete
        </button>
      </div>
    </li>
  )
}

/**
 * Course-local assets are intentionally a shelf, not a second document app.
 * It receives only a course/session identity, asks the private School API for
 * safe metadata, and never reads or places an uploaded file into AI context.
 */
export default function SchoolFilesPanel({ courseCode, sessionId = null, toast }) {
  const inputId = useId()
  const pickerRef = useRef(null)
  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [deletingId, setDeletingId] = useState(null)
  const [filter, setFilter] = useState('all')
  const [attachToSession, setAttachToSession] = useState(Boolean(sessionId))
  const [dragging, setDragging] = useState(false)

  useEffect(() => { setAttachToSession(Boolean(sessionId)) }, [sessionId])

  const loadAssets = useCallback(async ({ quiet = false } = {}) => {
    if (!courseCode) return
    if (!quiet) setLoading(true)
    setError('')
    try {
      const result = await schoolFileRequest(`/api/school/courses/${encodeURIComponent(courseCode)}/assets`)
      setAssets(Array.isArray(result.assets) ? result.assets : [])
    } catch (requestError) {
      setError(requestError.message || 'Class files could not load')
    } finally {
      if (!quiet) setLoading(false)
    }
  }, [courseCode])

  useEffect(() => { loadAssets() }, [loadAssets])

  const counts = useMemo(() => {
    const next = { all: assets.length }
    assets.forEach((asset) => {
      const kind = schoolFileKind(asset)
      next[kind] = (next[kind] || 0) + 1
    })
    return next
  }, [assets])

  const visibleAssets = useMemo(
    () => filter === 'all' ? assets : assets.filter((asset) => schoolFileKind(asset) === filter),
    [assets, filter],
  )

  const uploadFiles = useCallback(async (fileList) => {
    const files = Array.from(fileList || [])
    if (!files.length || uploading || !courseCode) return
    const invalid = files.filter((file) => !isUploadableSchoolFile(file) || file.size > SCHOOL_FILE_MAX_BYTES)
    const valid = files.filter((file) => isUploadableSchoolFile(file) && file.size <= SCHOOL_FILE_MAX_BYTES)
    if (invalid.length) toast?.('Use PDFs, slides, docs, sheets, images, or text files under 25 MB.', 'warn')
    if (!valid.length) return

    setUploading(true)
    setError('')
    let completed = 0
    try {
      for (const file of valid) {
        const body = new FormData()
        body.append('file', file)
        // File type already gives the shelf its organization. Keep the stored
        // semantic category neutral until Ian chooses a course-specific label.
        body.append('category', 'material')
        if (attachToSession && sessionId) body.append('session_id', String(sessionId))
        await schoolFileRequest(`/api/school/courses/${encodeURIComponent(courseCode)}/assets`, {
          method: 'POST', body,
        })
        completed += 1
      }
      await loadAssets({ quiet: true })
      toast?.(completed === 1 ? 'Class file added' : `${completed} class files added`, 'good')
    } catch (uploadError) {
      setError(uploadError.message || 'File could not upload')
      if (completed) await loadAssets({ quiet: true })
    } finally {
      setUploading(false)
      if (pickerRef.current) pickerRef.current.value = ''
    }
  }, [attachToSession, courseCode, loadAssets, sessionId, toast, uploading])

  const deleteAsset = useCallback(async (asset) => {
    if (!asset || deletingId) return
    if (!window.confirm(`Delete “${asset.display_name}” from ${courseCode}?`)) return
    setDeletingId(asset.id)
    setError('')
    try {
      await schoolFileRequest(`/api/school/assets/${asset.id}`, { method: 'DELETE' })
      setAssets((current) => current.filter((item) => item.id !== asset.id))
      toast?.('Class file deleted', 'good')
    } catch (deleteError) {
      setError(deleteError.message || 'File could not be deleted')
    } finally {
      setDeletingId(null)
    }
  }, [courseCode, deletingId, toast])

  return (
    <section
      className={`school-files${dragging ? ' is-dragging' : ''}`}
      aria-label={`${courseCode || 'Course'} file shelf`}
      onDragOver={(event) => { event.preventDefault(); setDragging(true) }}
      onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false) }}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        uploadFiles(event.dataTransfer?.files)
      }}
    >
      <div className="school-files-head">
        <div>
          <h3>Class files</h3>
          <p>{assets.length ? `${assets.length} in this course` : 'Keep slides, readings, and handouts here.'}</p>
        </div>
        <input
          ref={pickerRef}
          id={inputId}
          type="file"
          className="school-file-picker"
          accept={SCHOOL_FILE_ACCEPT}
          multiple
          onChange={(event) => uploadFiles(event.target.files)}
        />
        <button
          type="button"
          className="school-files-upload"
          onClick={() => pickerRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? 'Adding…' : 'Add files'}
        </button>
      </div>

      {sessionId && <label className="school-files-session-link">
        <input type="checkbox" checked={attachToSession} onChange={(event) => setAttachToSession(event.target.checked)} />
        Link new files to this daily note
      </label>}

      {assets.length > 0 && <KindFilter active={filter} onChange={setFilter} counts={counts} />}

      {error && <div className="school-files-error" role="alert">
        <span>{error}</span>
        <button type="button" onClick={() => loadAssets()}>Retry</button>
      </div>}

      {loading ? <p className="school-files-state">Loading class files…</p>
        : visibleAssets.length ? <ul className="school-files-list">
          {visibleAssets.map((asset) => <FileRow key={asset.id} asset={asset} onDelete={deleteAsset} deleting={deletingId === asset.id} />)}
        </ul>
          : <p className="school-files-state">{assets.length ? 'No files in this view.' : 'Add course material here. Files stay private to School.'}</p>}
    </section>
  )
}
