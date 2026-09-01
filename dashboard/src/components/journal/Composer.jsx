import React, { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence, useReducedMotion } from 'motion/react'
import { playAttach, playClose } from '../../lib/journalSound.js'
import { api } from '../../lib/api.js'

const CLOSE_LINES = ['Day closed.', "That's a wrap.", 'Rest well.', 'Put it down.']

/**
 * Blank nightly composer, no prompts (SPEC-v8/v11). Lives at the top of Journal.
 */
export default function Composer({
  closedToday,
  onComposingChange,
  onClosed,
  toast,
  focusToken = 0,
}) {
  const rm = useReducedMotion()
  const [body, setBody] = useState('')
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const fileRef = useRef(null)
  const taRef = useRef(null)
  const closeTimerRef = useRef(null)

  useEffect(() => {
    if (focusToken) taRef.current?.focus()
  }, [focusToken])

  useEffect(() => () => { if (preview?.url) URL.revokeObjectURL(preview.url) }, [preview])

  // Tapping a tab bar button before the ~2s close ritual finishes unmounts
  // this component; without clearing the timer, a stale closure later fires
  // state-setters and onClosed/onComposingChange against an unmounted tree.
  useEffect(() => () => clearTimeout(closeTimerRef.current), [])

  useEffect(() => {
    const composing = Boolean(done) || document.activeElement === taRef.current || body.trim().length > 0
    onComposingChange?.(composing)
  }, [body, done, onComposingChange])

  const pickFile = (e) => {
    const f = e.target.files?.[0]
    if (!f) return
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setFile(f)
    setPreview({ url: URL.createObjectURL(f), kind: f.type.startsWith('video') ? 'video' : 'photo' })
    playAttach()
  }

  const clearFile = () => {
    if (preview?.url) URL.revokeObjectURL(preview.url)
    setFile(null)
    setPreview(null)
    if (fileRef.current) fileRef.current.value = ''
  }

  const closeDay = async () => {
    if (!body.trim() || busy) return
    setBusy(true)
    try {
      const res = await api('/api/journal', 'POST', { body: body.trim() })
      let entry = res.entry
      if (file) {
        const fd = new FormData()
        fd.append('file', file)
        const up = await fetch(`/api/journal/${res.entry.id}/media`, { method: 'POST', body: fd })
        if (!up.ok) toast("photo didn't attach. Your words are saved", 'warn')
        else entry = await up.json()
      }
      const nights = res.stats?.nights_closed_total ?? 0
      if (!rm) playClose()
      setDone({
        nights,
        line: CLOSE_LINES[nights % CLOSE_LINES.length],
        entry,
        previewUrl: preview?.url || null,
        previewKind: preview?.kind || null,
      })
      setBody('')
      setFile(null)
      // keep preview URL for the fly-in; revoke after ritual
      closeTimerRef.current = setTimeout(() => {
        setDone(null)
        if (preview?.url) URL.revokeObjectURL(preview.url)
        setPreview(null)
        onClosed?.(entry)
        onComposingChange?.(false)
        setBusy(false)
      }, rm ? 400 : 2200)
    } catch (e) {
      toast(e.message, 'crit')
      setBusy(false)
    }
  }

  if (done) {
    return (
      <div className="journal-composer journal-composer-done">
        <AnimatePresence>
          {!rm && (
            <motion.span key="ring" className="journal-ring" aria-hidden="true"
              initial={{ scale: 0.2, opacity: 0.55 }}
              animate={{ scale: 2.6, opacity: 0 }}
              transition={{ duration: 1.2, ease: 'easeOut' }} />
          )}
        </AnimatePresence>
        <motion.div
          className="journal-closed"
          initial={rm ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: rm ? 0 : 0.35, duration: 0.4 }}
        >
          <p className="journal-closed-line">{done.line}</p>
          <p className="journal-closed-count">
            {done.nights} {done.nights === 1 ? 'night' : 'nights'} closed
          </p>
          {done.previewUrl && done.previewKind === 'photo' && (
            <motion.img
              layoutId={done.entry?.id ? `journal-cover-${done.entry.id}` : undefined}
              className="journal-closed-thumb"
              src={done.previewUrl}
              alt=""
            />
          )}
        </motion.div>
      </div>
    )
  }

  return (
    <section className="journal-composer">
      <div className="journal-composer-eyebrow">
        {closedToday ? 'Day closed. Add more if you like.' : 'Tonight'}
      </div>
      <div className="journal-compose-stage">
        <textarea
          ref={taRef}
          className="journal-box"
          placeholder="tonight…"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onFocus={() => onComposingChange?.(true)}
          onBlur={() => { if (!body.trim()) onComposingChange?.(false) }}
          onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') closeDay() }}
          aria-label="tonight's journal, private to you"
        />
        <div className={`journal-composer-media${preview ? ' has-preview' : ''}`}>
          {preview ? (
            <div className="journal-preview">
              {preview.kind === 'video'
                ? <video src={preview.url} preload="metadata" muted controls />
                : <img src={preview.url} alt="attached preview" />}
              <button type="button" className="journal-preview-x" onClick={clearFile} aria-label="remove attachment">✕</button>
            </div>
          ) : (
            <button type="button" className="journal-add-media" onClick={() => fileRef.current?.click()}>
              <span className="journal-add-media-plus">+</span>
              <span>Add photo or video</span>
            </button>
          )}
          <input ref={fileRef} type="file" accept="image/*,video/*" hidden onChange={pickFile}
                 aria-label="attach a photo or video" />
        </div>
      </div>
      <div className="journal-composer-bar">
        <button
          type="button"
          className="btn approve primary journal-close-btn"
          onClick={closeDay}
          disabled={!body.trim() || busy}
        >
          {busy ? 'Closing…' : 'Close the day'}
        </button>
        <p className="journal-privacy">Only you. The team sees only that you closed the day.</p>
      </div>
    </section>
  )
}
