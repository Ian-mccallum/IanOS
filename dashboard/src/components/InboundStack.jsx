import React, { useEffect, useState } from 'react'
import { api } from '../lib/api.js'

/**
 * SPEC-v17: pending demo bookings + messages from beatyourclock.com.
 * Sits ABOVE The Line's brief: an unconfirmed request is a promise with a
 * 24h fuse, the cold queue can wait. Design law: --crit banned, a request
 * older than 24h WILTS (softens), never reddens; no countdown is shown.
 * Renders nothing when the inbox is empty (zero-value pixels are a bug).
 */
export default function InboundStack({ inbound, refresh, toast }) {
  const [busy, setBusy] = useState(null)
  // Clockwork's seam only. Personal correspondence lives on Inbox (SPEC-v19).
  const pending = (inbound?.pending || []).filter((r) => r.source !== 'personal')

  // Opportunistic pull on mount, the plan-sync precedent: server-side
  // cooldown makes this free, and failures are silent (Mac knows best).
  useEffect(() => {
    if (inbound?.configured) api('/api/btc/sync', 'POST').catch(() => {})
  }, [inbound?.configured])

  if (pending.length === 0) return null

  const confirm = async (req, date) => {
    setBusy(req.id)
    try {
      await api(`/api/inbound/${req.id}/confirm`, 'POST', { date })
      toast(`Demo booked: ${req.name || req.email}, ${date}`, 'good')
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setBusy(null)
    }
  }

  const dismiss = async (req) => {
    setBusy(req.id)
    try {
      await api(`/api/inbound/${req.id}/dismiss`, 'POST')
      toast('Dismissed', 'good')
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="inbound-stack">
      <span className="section-label">From the site</span>
      {pending.map((req) => {
        const wilted = Date.now() - Date.parse(req.received_at) > 86400000
        const windows = (req.windows || []).filter((w) => w.date)
        return (
          <div key={req.id} className={`inbound-card${wilted ? ' wilted' : ''}`}>
            <div className="inbound-head">
              <strong>{req.name || req.email}</strong>
              {!!req.company && <span className="dim"> · {req.company}</span>}
              <span className={`inbound-kind ${req.kind}`}>
                {req.kind === 'demo' ? 'demo request' : 'message'}
              </span>
            </div>

            {req.kind === 'demo' ? (
              <>
                {req.topics?.length > 0 && (
                  <p className="inbound-line dim">wants to see: {req.topics.join(' · ')}</p>
                )}
                {!!req.phone && <p className="inbound-line dim">{req.phone}</p>}
                {windows.length > 0 ? (
                  <div className="inbound-windows">
                    {windows.map((w) => (
                      <button key={`${w.date}|${w.window}`} type="button"
                              className="btn log" disabled={busy === req.id}
                              onClick={() => confirm(req, w.date)}>
                        {w.label || `${w.date} ${w.window}`}
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="inbound-line dim">any time works - confirm by email</p>
                )}
              </>
            ) : (
              <>
                {!!req.message && <p className="inbound-line">{req.message}</p>}
                {!!req.email && (
                  <a className="btn log inbound-reply" href={`mailto:${req.email}`}>
                    Reply
                  </a>
                )}
              </>
            )}

            <button type="button" className="inbound-dismiss dim"
                    disabled={busy === req.id} onClick={() => dismiss(req)}>
              dismiss
            </button>
          </div>
        )
      })}
    </div>
  )
}
