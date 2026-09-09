import React, { memo, useEffect, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { api } from '../lib/api.js'
import { greeting } from '../lib/timeSession.js'
import ActionStack from '../components/ActionStack.jsx'
import PillarStrip from '../components/PillarStrip.jsx'
import Md from '../components/Md.jsx'
import { isCommandStale, maybeTriggerOrderRefresh } from '../lib/order.js'
import { roleColor, roleGlyph } from '../lib/agents.js'

const TZ = 'America/Chicago'
const ACTIVITY_FIELDS = new Set(['audit_calls', 'follow_ups'])

function stripDayCommand(body) {
  return (body || '').replace(/^#{1,4}\s*Day Command\s*\n(?:(?!#{1,4}\s|---)[^\n]*\n?)*/im, '')
}

/** Mission stamp: CMD · 06 AUG · CENTRAL */
function commandStamp(isoDate) {
  const raw = isoDate || new Date().toISOString().slice(0, 10)
  const d = new Date(`${raw}T12:00:00`)
  const day = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, day: '2-digit',
  }).format(d)
  const mon = new Intl.DateTimeFormat('en-US', {
    timeZone: TZ, month: 'short',
  }).format(d).toUpperCase()
  return { day, mon }
}

function interactionFor(item) {
  return item?.interaction && typeof item.interaction === 'object'
    ? item.interaction
    : { type: item?.interaction }
}

/** Ring 1 acts from the last 24h that Ian hasn't undone (SPEC-v37 §4.5).
 * `/api/state` already scopes `recent_acts` to the last 24h; this only drops
 * ones already undone, so a stale poll can't resurrect a row Ian just
 * dismissed. Pulled out for its own test, the lib/order.js precedent. */
export function visibleActs(recentActs) {
  return (recentActs || []).filter((act) => !act.undone_at)
}

function CommandPage({
  state,
  briefIsToday,
  navigate,
  toast,
  refresh,
  attentionFresh = false,
  onOpenChat = () => {},
}) {
  const [showBrief, setShowBrief] = useState(false)
  const [running, setRunning] = useState(false)
  const [gymBusy, setGymBusy] = useState(false)
  const [undoingActId, setUndoingActId] = useState(null)
  const [locallyUndoneIds, setLocallyUndoneIds] = useState(() => new Set())
  const rm = useReducedMotion()
  const compiledAttention = state.attention || {}
  const primary = compiledAttention.next || null
  const secondary = compiledAttention.items || []
  const command = state.brief?.day_command
  // Receipts strip (SPEC-v37 §4.5): Ring 1 acts an agent already took, each
  // undoable. Undo optimistically hides the row locally; refresh() then pulls
  // the real undone_at so the two never disagree once the poll lands.
  const receiptActs = visibleActs(state.recent_acts).filter((act) => !locallyUndoneIds.has(act.id))
  // SPEC-v32 Part D: the nightly sentence can disagree with the live order
  // by morning. Dim it, using the exact same stale visual language, rather
  // than inventing a second one, when a today-anchored brief's anchor_key no
  // longer matches what the compiler currently ranks first.
  const commandStale = isCommandStale({
    command,
    primaryKey: primary?.key,
    anchorKey: state.brief?.anchor_key,
  })
  const greet = greeting()
  const stamp = commandStamp(state.brief?.date || state.today)

  // Evening nudge toward Journal: the habit engine (SPEC-v8 / v11).
  const [showShutdownNudge, setShowShutdownNudge] = useState(false)
  useEffect(() => {
    if (new Date().getHours() < 21) return
    if (localStorage.getItem(`shutdown-nudge:${state.today}`) === '1') return
    api('/api/journal?limit=1')
      .then((d) => { if (!d.stats?.closed_today) setShowShutdownNudge(true) })
      .catch(() => {})
  }, [state.today])
  const dismissNudge = () => {
    localStorage.setItem(`shutdown-nudge:${state.today}`, '1')
    setShowShutdownNudge(false)
  }

  // Once-per-day transmit reveal (local calendar day).
  const revealKey = `cmd-reveal:${state.today}`
  const [doReveal] = useState(() => {
    if (!command || rm) return false
    try { return localStorage.getItem(revealKey) !== '1' } catch { return false }
  })
  useEffect(() => {
    if (!doReveal || !command) return undefined
    try { localStorage.setItem(revealKey, '1') } catch { /* ignore */ }
    return undefined
  }, [doReveal, command, revealKey])

  // Fire the live rewrite at most once per unique (anchor_key, next.key) pair
  // per browser session, so a 15s poll loop can never refire it. Server-side
  // cooldown/cap are the real guardrails; this is just a chatty-tab guard.
  useEffect(() => {
    maybeTriggerOrderRefresh({
      nextKey: state.attention?.next?.key,
      brief: state.brief,
      today: state.today,
      storage: sessionStorage,
      requestRefresh: () => api('/api/order/refresh', 'POST', {}).then(() => refresh()).catch(() => {}),
    })
  }, [state.attention?.next?.key, state.brief?.anchor_key, state.brief?.date, state.brief?.governs_date, state.today])

  const runBrief = async () => {
    setRunning(true)
    try {
      await api('/api/agents/run', 'POST', {})
      toast('agents running. Brief updates in a few minutes', 'good')
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setRunning(false)
    }
  }

  const confirmGym = async () => {
    setGymBusy(true)
    try {
      const res = await api('/api/gym/confirm', 'POST', {}, { queueable: true })
      toast(res?.queued
        ? 'gym saved. Syncs when your Mac wakes'
        : `gym confirmed · ${res.gym?.streak || 0} day streak`, 'good')
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setGymBusy(false)
    }
  }

  const bumpActivity = async (item) => {
    const interaction = interactionFor(item)
    const field = interaction.field || interaction.ref_id
    if (!ACTIVITY_FIELDS.has(field)) return
    try {
      const result = await api('/api/activity', 'POST', { [field]: 1 }, { queueable: true })
      const label = field === 'audit_calls' ? 'call' : 'follow-up'
      toast(result?.queued ? `${label} saved. Syncs when your Mac wakes` : `${label} logged`, 'good')
      refresh()
    } catch (error) {
      toast(error.message, 'crit')
    }
  }

  const completeTask = async (item) => {
    const id = item.interaction?.ref_id ?? item.ref_id
    await api(`/api/tasks/${id}/done`, 'POST', {}, { queueable: true })
    refresh()
  }

  const undoAct = async (act) => {
    setUndoingActId(act.id)
    try {
      await api(`/api/acts/${act.id}/undo`, 'POST', {})
      setLocallyUndoneIds((prev) => new Set(prev).add(act.id))
      refresh()
    } catch (e) {
      toast(e.message, 'crit')
    } finally {
      setUndoingActId(null)
    }
  }

  const runPrimary = async () => {
    if (!primary) return
    const interaction = interactionFor(primary)
    if (interaction.type === 'proposal_decision') {
      navigate(primary.route)
    } else if (interaction.type === 'gym_confirm') {
      await confirmGym()
    } else if (interaction.type === 'activity_increment') {
      await bumpActivity(primary)
    } else if (interaction.type === 'task_complete') {
      await completeTask(primary)
    } else {
      navigate(primary.route)
    }
  }

  return (
    <div className={`command-page page-layout page-layout--overview${showBrief ? ' expanded' : ''}`}>
      <div className="command-grid">
        {/* SPEC-v37 §7.1: AgentChat portals its dock-state panel into this
            node when Command is the active page (Law A10 -- AgentChat itself
            keeps its one mount in App.jsx; this is DOM position only, never
            lifecycle). Wrapped with command-orders in one column so the dock
            sits tight under the Order regardless of how tall the rail gets. */}
        <div className="command-col-main">
        <section className="command-hero command-orders" aria-label="Day command">
          <div className="ord-atmosphere" aria-hidden="true">
            <span className="ord-bloom" />
            <span className="ord-beam" />
          </div>

          <header className="ord-head">
            <span className="ord-label">Order</span>
            <div className="ord-meta" aria-label="Order stamp">
              <span>{stamp.day} {stamp.mon}</span>
              <span className="ord-meta-dot" aria-hidden="true" />
              <span>CT</span>
              {state.brief && !briefIsToday && <span className="ord-stale">stale</span>}
              {primary && !attentionFresh && <span className="ord-stale">last synced</span>}
            </div>
          </header>

          <div className="ord-body">
            {command ? (
              <motion.p
                className={`ord-text${commandStale ? ' ord-text-dim' : ''}`}
                initial={doReveal ? { opacity: 0, y: 12 } : false}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.48, ease: [0.22, 1, 0.36, 1] }}
              >
                {command}
              </motion.p>
            ) : (
              <div className="ord-empty">
                <p className="ord-empty-greet">{greet}, Ian</p>
                <p className="ord-text ord-text-dim">No order yet.</p>
              </div>
            )}
          </div>

          {primary ? (
            <button type="button" className="ord-go" onClick={runPrimary} disabled={gymBusy}>
              <span className="ord-go-line">
                {primary.label}
                {primary.reason ? ` · ${primary.reason}` : ''}
              </span>
              <span className="ord-go-chev" aria-hidden="true">→</span>
            </button>
          ) : !command ? (
            <button type="button" className="ord-go" onClick={runBrief} disabled={running}>
              <span className="ord-go-line">{running ? 'Generating…' : "Pull tonight's brief"}</span>
              <span className="ord-go-chev" aria-hidden="true">→</span>
            </button>
          ) : (
            <button type="button" className="ord-go" disabled>
              <span className="ord-go-line">Nothing else needs your attention</span>
            </button>
          )}

          {showShutdownNudge && (
            <div className="command-shutdown-nudge">
              <button type="button" className="command-next" onClick={() => navigate('journal')}>
                <span className="command-next-dot shutdown-dot" aria-hidden="true" />
                Close the day
              </button>
              <button type="button" className="nudge-dismiss" onClick={dismissNudge} aria-label="dismiss nudge">✕</button>
            </div>
          )}

          <div className="ord-foot">
              <button type="button" className="ord-link command-ask" onClick={() => onOpenChat()}>
                Ask an agent
              </button>
              {state.brief && (
                <button type="button" className="ord-link" onClick={() => setShowBrief(!showBrief)} aria-expanded={showBrief}>
                  {showBrief ? 'Hide brief' : 'Brief'}
                </button>
              )}
              {command && (
                <button type="button" className="ord-link muted" onClick={runBrief} disabled={running}>
                  {running ? '…' : 'Re-run'}
                </button>
              )}
          </div>
        </section>
        <div id="consult-dock-slot" className="consult-dock-slot" />
        </div>
        <div className="command-rail">
          <ActionStack
            items={secondary}
            toast={toast}
            refresh={refresh}
            onNavigate={navigate}
            onGymConfirm={confirmGym}
            gymBusy={gymBusy}
          />
          {receiptActs.length > 0 && (
            <div className="receipts-strip" aria-label="Recent agent actions">
              <div className="section-label">Receipts</div>
              {receiptActs.map((act) => {
                const color = roleColor(act.role)
                const codename = state.roster?.find((r) => r.role === act.role)?.codename || act.role
                return (
                  <div key={act.id} className="card-item receipt-row">
                    <span className="receipt-glyph" style={{ color }} aria-hidden="true">
                      {roleGlyph(act.role)}
                    </span>
                    <div className="receipt-body">
                      <span className="receipt-agent" style={{ color }}>{codename}</span>
                      <p className="receipt-summary">{act.summary}</p>
                    </div>
                    <button
                      type="button"
                      className="receipt-undo"
                      onClick={() => undoAct(act)}
                      disabled={undoingActId === act.id}
                    >
                      {undoingActId === act.id ? '…' : 'Undo'}
                    </button>
                  </div>
                )
              })}
            </div>
          )}
          <PillarStrip pillars={state.pillars} onNavigate={navigate} />
        </div>
      </div>
      {showBrief && state.brief && (
        <motion.div
          className="focus-brief glass-card glass-card-pad"
          initial={rm ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Md text={stripDayCommand(state.brief.body)} />
          {/* SPEC-v37 §8.6 point 3: code-computed, deliberately kept out of
              `body` server-side so it never reads as part of the chief's own
              prose (that's the whole reason it isn't just another Markdown
              line). Empty string on a pre-migration brief or a night the
              computation produced nothing -- render nothing, never a
              placeholder like "0 of 0 woke". */}
          {state.brief.dispatch_summary && (
            <p className="brief-dispatch-summary dim">{state.brief.dispatch_summary}</p>
          )}
        </motion.div>
      )}
    </div>
  )
}

function commandPropsEqual(prev, next) {
  const keys = [
    // roster feeds the chat agent picker, so a retired agent has to reach it.
    'today', 'brief', 'attention', 'pillars', 'roster',
    // recent_acts drives the Receipts strip (SPEC-v37 §4.5); without it here
    // a new or undone act would sit invisible until an unrelated key changed.
    'recent_acts',
  ]
  for (const k of keys) {
    if (JSON.stringify(prev.state?.[k]) !== JSON.stringify(next.state?.[k])) return false
  }
  return (
    prev.briefIsToday === next.briefIsToday
    && prev.attentionFresh === next.attentionFresh
    && prev.navigate === next.navigate
    && prev.toast === next.toast
    && prev.refresh === next.refresh
  )
}

export default memo(CommandPage, commandPropsEqual)
