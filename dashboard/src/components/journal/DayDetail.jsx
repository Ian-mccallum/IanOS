import React, { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api.js'
import { playUndo } from '../../lib/journalSound.js'

function Media({ entry, className = 'journal-media' }) {
  if (!entry.media_kind) return null
  const src = `/api/journal/media/${entry.id}`
  return entry.media_kind === 'video'
    ? <video className={className} src={src} controls preload="metadata" />
    : <img className={className} src={src} alt="" loading="lazy" />
}

function Entry({ entry, onChanged, toast }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(entry.body)
  const fileRef = useRef(null)

  useEffect(() => { setText(entry.body) }, [entry.body])

  const save = async () => {
    if (!text.trim()) { toast('cannot be empty', 'warn'); return }
    try {
      await api(`/api/journal/${entry.id}`, 'PATCH', { body: text.trim() })
      setEditing(false)
      onChanged()
    } catch (e) { toast(e.message, 'crit') }
  }

  const del = () => {
    // Impossible undo: hide now, hard-delete after 8s unless Undo cancels.
    const id = entry.id
    const key = 'journal-pending-delete'
    const pending = JSON.parse(sessionStorage.getItem(key) || '[]')
    if (!pending.includes(id)) {
      pending.push(id)
      sessionStorage.setItem(key, JSON.stringify(pending))
    }
    onChanged()
    let cancelled = false
    const timer = setTimeout(async () => {
      if (cancelled) return
      try {
        await api(`/api/journal/${id}`, 'DELETE')
      } catch (e) {
        toast(e.message, 'crit')
      } finally {
        const left = JSON.parse(sessionStorage.getItem(key) || '[]').filter((x) => x !== id)
        sessionStorage.setItem(key, JSON.stringify(left))
        onChanged()
      }
    }, 8000)
    toast('entry removed', 'good', () => {
      cancelled = true
      clearTimeout(timer)
      const left = JSON.parse(sessionStorage.getItem(key) || '[]').filter((x) => x !== id)
      sessionStorage.setItem(key, JSON.stringify(left))
      playUndo()
      onChanged()
    })
  }

  const share = async () => {
    if (!window.confirm("Send these words to your agents as a note from you? Your photo/video is never shared.")) return
    try {
      await api(`/api/journal/${entry.id}/share`, 'POST')
      toast('shared with the team', 'good')
      onChanged()
    } catch (e) { toast(e.message, 'crit') }
  }

  const uploadMedia = async (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    const fd = new FormData()
    fd.append('file', f)
    try {
      const r = await fetch(`/api/journal/${entry.id}/media`, { method: 'POST', body: fd })
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'upload failed')
      onChanged()
    } catch (err) { toast(err.message, 'crit') }
    if (fileRef.current) fileRef.current.value = ''
  }

  const removeMedia = async () => {
    try {
      await api(`/api/journal/${entry.id}/media`, 'DELETE')
      onChanged()
    } catch (e) { toast(e.message, 'crit') }
  }

  if (editing) {
    return (
      <article className="journal-entry">
        <textarea className="journal-edit" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
        <div className="journal-entry-actions">
          <button type="button" className="btn approve primary" onClick={save}>Save</button>
          <button type="button" className="btn ghost" onClick={() => { setText(entry.body); setEditing(false) }}>Cancel</button>
        </div>
      </article>
    )
  }

  return (
    <article className={`journal-entry${entry.media_kind ? ' has-media' : ''}`}>
      <div className="journal-entry-copy">
        <p className="journal-body">{entry.body}</p>
        <div className="journal-entry-actions">
          <button type="button" className="journal-act" onClick={() => setEditing(true)}>Edit</button>
          {entry.media_kind
            ? <button type="button" className="journal-act" onClick={removeMedia}>Remove media</button>
            : <button type="button" className="journal-act" onClick={() => fileRef.current?.click()}>+ media</button>}
          <button type="button" className="journal-act" onClick={share} disabled={Boolean(entry.shared)}>
            {entry.shared ? 'shared ✓' : 'Share'}
          </button>
          <button type="button" className="journal-act danger" onClick={del}>Delete</button>
          <input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={uploadMedia} />
        </div>
      </div>
      <Media entry={entry} className="journal-media journal-media-hero" />
    </article>
  )
}

const fmtLong = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
  })

export default function DayDetail({ date, toast, onBack, onChanged }) {
  const [entries, setEntries] = useState(null)

  const load = async () => {
    try {
      const d = await api(`/api/journal/day/${date}`)
      const pending = new Set(JSON.parse(sessionStorage.getItem('journal-pending-delete') || '[]'))
      setEntries((d.entries || []).filter((e) => !pending.has(e.id)))
    } catch (e) { toast(e.message, 'crit') }
  }

  useEffect(() => { load() }, [date]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="journal-day-detail">
      <button type="button" className="journal-back" onClick={() => { onChanged?.(); onBack() }}>← Days</button>
      <h2 className="journal-day-title">{fmtLong(date)}</h2>
      {!entries ? (
        <p className="dim">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="dim">Nothing on this day.</p>
      ) : (
        <div className="journal-day-entries">
          {entries.map((e) => (
            <Entry key={e.id} entry={e} toast={toast} onChanged={load} />
          ))}
        </div>
      )}
    </div>
  )
}
