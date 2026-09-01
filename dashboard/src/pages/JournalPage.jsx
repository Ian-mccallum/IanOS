import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { api } from '../lib/api.js'
import { setSoundEnabled, soundEnabled } from '../lib/journalSound.js'
import Composer from '../components/journal/Composer.jsx'
import DayDetail from '../components/journal/DayDetail.jsx'
import MonthStrip from '../components/journal/MonthStrip.jsx'

const fmtDay = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
  })
const fmtMonth = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })

function mediaSrc(id) {
  return `/api/journal/media/${id}`
}

function DayCard({ day, onOpen }) {
  return (
    <button type="button" className="journal-day-card" onClick={() => onOpen(day.date)}>
      <div className={`journal-day-card-cover${day.has_media ? '' : ' blank'}`}>
        {day.has_media && day.cover_kind === 'photo' && (
          <motion.img
            layoutId={`journal-cover-${day.cover_entry_id}`}
            src={mediaSrc(day.cover_entry_id)}
            alt=""
            loading="lazy"
          />
        )}
        {day.has_media && day.cover_kind === 'video' && (
          <video src={mediaSrc(day.cover_entry_id)} preload="metadata" muted />
        )}
      </div>
      <div className="journal-day-card-meta">
        <span className="journal-day-card-date">{fmtDay(day.date)}</span>
        <span className="journal-day-card-snip">{day.snippet}</span>
      </div>
    </button>
  )
}

function PhotoDay({ day, onOpen, featured = false }) {
  return (
    <button
      type="button"
      className={`journal-photo-day${day.has_media ? '' : ' text'}${featured ? ' featured' : ''}`}
      onClick={() => onOpen(day.date)}
    >
      {day.has_media && day.cover_kind === 'photo' && (
        <motion.img
          layoutId={`journal-cover-${day.cover_entry_id}`}
          className="journal-photo-day-img"
          src={mediaSrc(day.cover_entry_id)}
          alt=""
          loading="lazy"
        />
      )}
      {day.has_media && day.cover_kind === 'video' && (
        <video className="journal-photo-day-img" src={mediaSrc(day.cover_entry_id)} preload="metadata" muted />
      )}
      <div className="journal-photo-day-veil">
        <span className="journal-photo-day-date">{fmtDay(day.date)}</span>
        <span className="journal-photo-day-snip">{day.snippet}</span>
      </div>
    </button>
  )
}

function PhotoGrid({ days, onOpen }) {
  const withMedia = days.filter((d) => d.has_media)
  if (withMedia.length === 0) {
    return <p className="journal-empty-line">Photos appear when a night has one.</p>
  }
  return (
    <div className="journal-photo-grid">
      {withMedia.map((d, i) => (
        <button
          key={d.date}
          type="button"
          className={`journal-photo-tile${i === 0 ? ' featured' : ''}`}
          onClick={() => onOpen(d.date)}
        >
          {d.cover_kind === 'photo'
            ? <img src={mediaSrc(d.cover_entry_id)} alt="" loading="lazy" />
            : <video src={mediaSrc(d.cover_entry_id)} preload="metadata" muted />}
        </button>
      ))}
    </div>
  )
}

/**
 * One-surface Journal (SPEC-v11): composer + look-back.
 * Phone = stacked day cards. Desktop = sticky composer + wide photo album.
 */
export default function JournalPage({ toast, refresh, onComposingChange, focusCompose = 0 }) {
  const [stats, setStats] = useState(null)
  const [days, setDays] = useState([])
  const [onThisDay, setOnThisDay] = useState([])
  const [browse, setBrowse] = useState(() => localStorage.getItem('journal-browse') || 'days')
  const [detailDate, setDetailDate] = useState(null)
  const [showMonth, setShowMonth] = useState(false)
  const [soundOn, setSoundOn] = useState(() => soundEnabled())
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    try {
      const dayView = await api('/api/journal?view=days&limit=90')
      setDays(dayView.days || [])
      setStats(dayView.stats || {})
      setOnThisDay(dayView.on_this_day || [])
      setLoading(false)
    } catch (e) {
      toast(e.message, 'crit')
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const setBrowseMode = (mode) => {
    setBrowse(mode)
    localStorage.setItem('journal-browse', mode)
  }

  const toggleSound = () => {
    const next = !soundOn
    setSoundEnabled(next)
    setSoundOn(next)
  }

  const months = useMemo(() => {
    let last = null
    let featuredDone = false
    return days.map((d) => {
      const m = fmtMonth(d.date)
      const show = m !== last
      last = m
      const featured = !featuredDone && d.has_media
      if (featured) featuredDone = true
      return { ...d, _month: show ? m : null, _featured: featured }
    })
  }, [days])

  if (detailDate) {
    return (
      <div className="journal-page journal-page-detail">
        <DayDetail
          date={detailDate}
          toast={toast}
          onBack={() => { setDetailDate(null); load() }}
          onChanged={load}
        />
      </div>
    )
  }

  const browseBody = loading ? (
    <p className="dim">Loading…</p>
  ) : days.length === 0 ? (
    <p className="journal-empty-line">Your record starts when you close tonight.</p>
  ) : browse === 'photos' ? (
    <PhotoGrid days={days} onOpen={setDetailDate} />
  ) : (
    <>
      <div className="journal-days-phone">
        {months.map((d) => (
          <React.Fragment key={d.date}>
            {d._month && <div className="journal-month-label">{d._month}</div>}
            <DayCard day={d} onOpen={setDetailDate} />
          </React.Fragment>
        ))}
      </div>
      <div className="journal-days-desktop">
        {months.map((d) => (
          <React.Fragment key={d.date}>
            {d._month && <div className="journal-month-label journal-month-label-desk">{d._month}</div>}
            <PhotoDay day={d} onOpen={setDetailDate} featured={d._featured} />
          </React.Fragment>
        ))}
      </div>
    </>
  )

  return (
    <div className="journal-page">
      <div className="journal-desk-compose">
        <Composer
          closedToday={Boolean(stats?.closed_today)}
          onComposingChange={onComposingChange}
          onClosed={() => { load(); refresh?.() }}
          toast={toast}
          focusToken={focusCompose}
        />
      </div>

      <div className="journal-desk-browse">
        <div className="journal-browse-head">
          <span className="journal-count">{stats?.nights_closed_total || 0} nights closed</span>
          <div className="journal-browse-tools">
            <div className="journal-toggle" role="tablist" aria-label="Browse mode">
              <button type="button" role="tab" aria-selected={browse === 'days'}
                      className={browse === 'days' ? 'on' : ''} onClick={() => setBrowseMode('days')}>Days</button>
              <button type="button" role="tab" aria-selected={browse === 'photos'}
                      className={browse === 'photos' ? 'on' : ''} onClick={() => setBrowseMode('photos')}>Photos</button>
            </div>
            <button type="button" className="journal-act" onClick={() => setShowMonth((v) => !v)}>
              {showMonth ? 'Hide month' : 'Month'}
            </button>
            <button type="button" className="journal-act" onClick={toggleSound} aria-pressed={soundOn}
                    title={soundOn ? 'Sound on' : 'Sound off'}>
              {soundOn ? '♪' : 'muted'}
            </button>
          </div>
        </div>

        {showMonth && (
          <MonthStrip toast={toast} onPickDay={(d) => { setShowMonth(false); setDetailDate(d) }} />
        )}

        {onThisDay.length > 0 && (
          <section className="journal-onthisday">
            <div className="section-label">On this day</div>
            <div className="journal-otd-row">
              {onThisDay.map((e) => (
                <button key={e.id} type="button" className="journal-otd-entry" onClick={() => setDetailDate(e.date)}>
                  <span className="journal-otd-year">{e.date.slice(0, 4)}</span>
                  <p className="journal-body">{e.body}</p>
                  {e.media_kind === 'photo' && (
                    <img className="journal-media" src={mediaSrc(e.id)} alt="" loading="lazy" />
                  )}
                </button>
              ))}
            </div>
          </section>
        )}

        {browseBody}
      </div>
    </div>
  )
}
