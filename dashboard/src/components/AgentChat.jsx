import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from '../lib/api.js'
import { roleColor, roleGlyph } from '../lib/agents.js'
import { draftLabel, draftPlainText } from '../lib/proposals.js'
import { relTime } from '../lib/time.js'
import Md from './Md.jsx'
import Sheet from './Sheet.jsx'

const MAX_QUESTION = 1500
const CHAT_RETURN_KEY = 'ianos:chat-return'
const DEFAULT_MODEL = 'claude-sonnet-5'
const MODELS = [
  { id: 'claude-haiku-4-5', label: 'Haiku', hint: 'fastest' },
  { id: 'claude-sonnet-5', label: 'Sonnet', hint: 'default' },
  { id: 'claude-opus-5', label: 'Opus', hint: 'deepest' },
  { id: 'claude-fable-5', label: 'Fable', hint: 'creative' },
]
const CHIP_LABELS = {
  money: 'Money', mail: 'Mail', calendar: 'Calendar',
  documents: 'Documents', web: 'Web search',
  // SPEC-v37 §2.7 Capability row: files/workspace/shell, rendered in
  // ReasoningSheet rather than ContextSheet's connector list (see below).
  files: 'Files', workspace: 'Workspace', shell: 'Shell',
}
// SPEC-v37 §2.7: the three capability chips that are always available (no
// connector, no "not connected" state), toggled through the exact same
// granted_chips replace-whole-array PATCH the connector chips already use.
// Mail/Calendar/Drive rows from the spec's table are deliberately NOT built
// here: there is no backend support yet, and a chip that grants nothing is
// an osui L3 zero-value-pixel bug.
const CAPABILITY_CHIPS = [
  { id: 'files', label: 'Files' },
  { id: 'workspace', label: 'Workspace' },
  { id: 'shell', label: 'Shell' },
]
const CAPABILITY_CHIP_IDS = new Set(CAPABILITY_CHIPS.map((c) => c.id))
const DEFAULT_EFFORT = 'high'
const EFFORTS = [
  { id: 'low', label: 'Low', hint: 'fastest' },
  { id: 'medium', label: 'Medium', hint: 'quick' },
  { id: 'high', label: 'High', hint: 'default' },
  { id: 'max', label: 'Max', hint: 'slowest' },
]

// SPEC-v37 §7.1: the consult surface lives in Command, but the mount stays in
// App.jsx (Law A10). SPEC-v40 §2.1 cut the view states to two, dock / open,
// held in sessionStorage (never a route, never localStorage: this is a
// per-tab UI position, not a durable preference), so a reload lands back
// wherever Ian left it with the thread intact. The retired 'expanded' and
// 'fullscreen' values read as 'open'.
const CONSULT_VIEW_KEY = 'ianos:consult-view'
const VALID_VIEWS = new Set(['dock', 'open'])
const LEGACY_OPEN_VIEWS = new Set(['expanded', 'fullscreen'])
const DOCK_SLOT_ID = 'consult-dock-slot'
// Matches the app's one mobile/desktop breakpoint (styles.css uses this exact
// pair everywhere else); Sheet.jsx hardcodes the same number for its own
// popover anchor math rather than sharing a constant, so this follows suit.
const MOBILE_QUERY = '(max-width: 900px)'

function readConsultView() {
  try {
    const raw = sessionStorage.getItem(CONSULT_VIEW_KEY)
    if (LEGACY_OPEN_VIEWS.has(raw)) return 'open'
    return VALID_VIEWS.has(raw) ? raw : 'dock'
  } catch {
    return 'dock'
  }
}
function writeConsultView(view) {
  try { sessionStorage.setItem(CONSULT_VIEW_KEY, view) } catch { /* not load-bearing */ }
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => {
    try { return window.matchMedia(MOBILE_QUERY).matches } catch { return false }
  })
  useEffect(() => {
    let mql
    try { mql = window.matchMedia(MOBILE_QUERY) } catch { return undefined }
    const onChange = () => setIsMobile(mql.matches)
    if (mql.addEventListener) mql.addEventListener('change', onChange)
    else mql.addListener(onChange)
    return () => {
      if (mql.removeEventListener) mql.removeEventListener('change', onChange)
      else mql.removeListener(onChange)
    }
  }, [])
  return isMobile
}

// ---------------------------------------------------------------------------
// The chat-turn invocation-cache helpers used to live in lib/agentInvocations.js
// alongside the Ask sheet/rooms code that SPEC-v37 §7.3 deletes. AgentChat is
// the one remaining consumer of this slice of it, so it moves in here rather
// than surviving as a near-empty shared file. Exported (not just used
// locally) so dashboard/tests/agent-chat-helpers.ui.test.jsx can keep
// unit-testing this pure logic directly, the same way CommandPalette.jsx
// exports useCommandPalette for its own test.
export const ACTIVE_CHAT_TURN_KEY = 'ianos:active-chat-turn'
const ACTIVE_INVOCATION_STATUSES = new Set(['QUEUED', 'RUNNING'])
const TERMINAL_INVOCATION_STATUSES = new Set(['SUCCEEDED', 'FAILED'])
const ROOM_MAX_ROLES = 3

function canonicalRole(value) {
  return typeof value === 'string' ? value.trim() : ''
}
function uniqueRoomRoleIds(values) {
  const seen = new Set()
  const roles = []
  for (const value of values || []) {
    const role = canonicalRole(typeof value === 'string' ? value : value?.role)
    if (!role || role === 'chief' || seen.has(role)) continue
    seen.add(role)
    roles.push(role)
  }
  return roles
}
export function activeRoomRoles(roster) {
  const seen = new Set()
  return (Array.isArray(roster) ? roster : []).filter((record) => {
    const role = canonicalRole(record?.role)
    if (!role || role === 'chief' || record?.active === false || seen.has(role)) return false
    seen.add(role)
    return true
  })
}
export function toggleRoomRole(selected, role, eligible) {
  const allowed = new Set(uniqueRoomRoleIds(eligible))
  const target = canonicalRole(role)
  const current = uniqueRoomRoleIds(selected).filter((item) => allowed.has(item))
  if (!allowed.has(target)) return current
  if (current.includes(target)) return current.filter((item) => item !== target)
  if (current.length >= ROOM_MAX_ROLES) return current
  return [...current, target]
}
export function invocationPollDelay(elapsedMs) {
  return elapsedMs >= 20_000 ? 3_000 : 1_500
}
export function isActiveInvocation(status) {
  return ACTIVE_INVOCATION_STATUSES.has(status)
}
export function isTerminalInvocation(status) {
  return TERMINAL_INVOCATION_STATUSES.has(status)
}
export function readActiveChatTurnId() {
  try {
    const raw = localStorage.getItem(ACTIVE_CHAT_TURN_KEY)
    if (!raw || !/^\d+$/.test(raw)) return null
    const id = Number(raw)
    return Number.isSafeInteger(id) && id > 0 ? id : null
  } catch {
    return null
  }
}
export function rememberActiveChatTurn(id) {
  if (!Number.isSafeInteger(Number(id)) || Number(id) <= 0) return false
  try {
    localStorage.setItem(ACTIVE_CHAT_TURN_KEY, String(id))
    return true
  } catch {
    return false
  }
}
export function clearActiveChatTurn(id) {
  try {
    const current = readActiveChatTurnId()
    if (id != null && current !== Number(id)) return false
    localStorage.removeItem(ACTIVE_CHAT_TURN_KEY)
    return true
  } catch {
    return false
  }
}
/** SPEC-v40 §2.3 / §4: split a thread's turns at its last Compact. `earlier`
 *  is what the stored summary already covers (collapsed behind "Show
 *  earlier"), `recent` is everything since. Pure; exported for its test. */
export function partitionCompacted(turns, summaryTurnCount) {
  const list = Array.isArray(turns) ? turns : []
  const n = Math.max(0, Math.min(list.length, Number(summaryTurnCount) || 0))
  return { earlier: list.slice(0, n), recent: list.slice(n) }
}

/** SPEC-v40 §5: threads grouped under their agent in roster order, newest
 *  first inside each group (the API already lists newest activity first).
 *  Agents with no thread still get a row, so "New chat" exists for them. */
export function groupThreadsByRole(threads, roster) {
  const byRole = new Map()
  for (const t of Array.isArray(threads) ? threads : []) {
    if (!t?.role) continue
    if (!byRole.has(t.role)) byRole.set(t.role, [])
    byRole.get(t.role).push(t)
  }
  const out = []
  const seen = new Set()
  for (const item of Array.isArray(roster) ? roster : []) {
    if (!item?.role || item.active === false || seen.has(item.role)) continue
    seen.add(item.role)
    out.push({ role: item.role, codename: item.codename || item.role, threads: byRole.get(item.role) || [] })
  }
  return out
}
// ---------------------------------------------------------------------------

/** Identity colour for chat. Dumbledore is --crit everywhere else in the
 *  product, and --crit is banned on this surface, so he borrows amber here
 *  rather than turning the room red while Ian is just talking. */
function chatRoleColor(role) {
  const raw = roleColor(role)
  return raw === 'var(--crit)' ? '#fbbf24' : raw
}

// "Ask Jordan Belfort" overflows the pill at 375px and a textarea cannot
// ellipsize a placeholder, so it clips. Use the given name, except where the
// first word is a title and dropping the rest would be nonsense.
const NAME_TITLES = new Set(['dr.', 'mr.', 'ms.', 'mrs.', 'uncle', 'aunt'])

function shortName(codename) {
  const full = String(codename || '').trim()
  const [first] = full.split(/\s+/)
  if (!first || NAME_TITLES.has(first.toLowerCase())) return full
  return first
}

function effortLabel(id) {
  return EFFORTS.find((e) => e.id === id)?.label || 'High'
}

function modelLabel(id) {
  return MODELS.find((m) => m.id === id)?.label || 'Sonnet'
}

function Glyph({ role }) {
  return (
    <span className="ac-glyph" style={{ color: chatRoleColor(role) }} aria-hidden="true">
      {roleGlyph(role)}
    </span>
  )
}

/** One exchange: what Ian said, then what the agent said back. */
function Exchange({
  turn, role, codename, onFileDraft, onCopyDraft, onRetry, onTapMissing,
  onUndoWrite, undoneWrites, showWriteHint,
}) {
  const status = turn?.status
  const running = isActiveInvocation(status)
  const failed = status === 'FAILED'
  const evidence = Array.isArray(turn?.evidence) ? turn.evidence : []
  const missing = Array.isArray(turn?.missing_access) ? turn.missing_access : []
  const numbers = Array.isArray(turn?.numbers) ? turn.numbers : []
  const specialists = Array.isArray(turn?.specialists) ? turn.specialists : []
  const writes = Array.isArray(turn?.writes) ? turn.writes : []
  const draft = turn?.draft
  // SPEC-v26: small talk carries no verdict. Rendering "-" would be a
  // zero-value pixel (osui L3), so the card only appears when it says
  // something.
  const hasVerdict = Boolean(turn?.verdict) && turn.verdict !== '-'
  const hasNext = Boolean(turn?.next_action) && turn.next_action !== '-'

  return (
    <div className="ac-exchange">
      {turn.question ? (
        <div className="ac-row ac-row-user">
          <p className="ac-said">{turn.question}</p>
        </div>
      ) : null}

      <div className="ac-row ac-row-agent">
        <Glyph role={role} />
        <div className="ac-said-agent">
          {running && (
            <p className="ac-thinking" role="status" aria-live="polite">
              <span className="ac-dots" aria-hidden="true"><span /><span /><span /></span>
              <span className="sr-only">{codename} is reading the record</span>
            </p>
          )}

          {status === 'SUCCEEDED' && (
            <>
              <Md text={turn.body || '-'} />

              {(hasVerdict || hasNext) && (
                <div className="ac-verdict">
                  {hasVerdict && <p className="ac-verdict-line">{turn.verdict}</p>}
                  {hasNext && (
                    <p className="ac-verdict-next"><span>Next</span> {turn.next_action}</p>
                  )}
                  {draft && (
                    <div className="ac-draft">
                      <span className="ac-draft-label">{draftLabel(draft)}</span>
                      <div className="ac-draft-actions">
                        <button type="button" className="btn ghost" onClick={() => onCopyDraft(draft)}>
                          Copy
                        </button>
                        <button type="button" className="btn" onClick={() => onFileDraft(turn)}>
                          File in Inbox
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {writes.length > 0 && (
                <div className="ac-writes">
                  {writes.map((w, i) => {
                    if (!w?.label) return null
                    const key = `${turn.id}:${i}`
                    const undone = undoneWrites?.has(key)
                    return (
                      <div key={key} className={`ac-write${undone ? ' is-undone' : ''}`}>
                        <span className="ac-write-check" aria-hidden="true">&#10003;</span>
                        <p className="ac-write-label">{undone ? `Undone: ${w.label}` : w.label}</p>
                        {!undone && (
                          <button
                            type="button"
                            className="ac-write-undo"
                            onClick={() => onUndoWrite(w, key)}
                          >
                            Undo
                          </button>
                        )}
                      </div>
                    )
                  })}
                  {showWriteHint && (
                    <p className="ac-hint">
                      {codename} can write to your plan, goals, and notes directly. Money and calls always ask first.
                    </p>
                  )}
                </div>
              )}

              {numbers.length > 0 && (
                <ul className="ac-numbers">
                  {numbers.map((item) => (
                    <li key={`${item.label}-${item.source}`}>
                      <span>{item.label}</span>
                      <code>{item.value || '-'}</code>
                    </li>
                  ))}
                </ul>
              )}

              {specialists.length > 0 && (
                <p className="ac-specialists">
                  {specialists.map((s) => s.codename || s.role).join(' · ')}
                </p>
              )}

              {missing.length > 0 && (
                <p className="ac-missing">
                  {missing.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      className="ac-missing-chip"
                      onClick={() => onTapMissing(chip)}
                    >
                      Turn on {CHIP_LABELS[chip] || chip}
                    </button>
                  ))}
                </p>
              )}

              {evidence.length > 0 && <p className="ac-evidence">{evidence.join(' · ')}</p>}
            </>
          )}

          {failed && (
            <div className="ac-failed">
              <p>{turn.error?.message || 'That did not go through.'}</p>
              <button type="button" className="btn ghost" onClick={() => onRetry(turn)}>
                Try again
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function FileDraftDialog({ draft, busy, onCancel, onConfirm }) {
  return (
    <Sheet open onClose={onCancel} title="File in Inbox" variant="dialog">
      <p className="dim">Records a decision for you to approve. Filing never sends anything.</p>
      <pre className="chat-draft-preview">{draftPlainText(draft)}</pre>
      <div className="chat-file-actions">
        <button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="button" className="btn" onClick={onConfirm} disabled={busy}>
          {busy ? 'Filing…' : 'File it'}
        </button>
      </div>
    </Sheet>
  )
}

/** Sources this agent can be granted. Rows that would grant nothing are
 *  filtered out server-side, so every row here does something. */
function ContextSheet({ chips, granted, wanted, accent, anchor, onToggle, onClose }) {
  return (
    <Sheet open onClose={onClose} title="Add context" variant="popover" anchor={anchor}>
      <div style={{ '--agent': accent }}>
        <p className="dim">What this agent may read while it answers.</p>
        <ul className="ac-source-list">
          {chips.map((chip) => {
            const on = granted.includes(chip.id)
            const state = on ? 'on' : chip.connected ? 'off' : 'not connected'
            return (
              <li key={chip.id}>
                <button
                  type="button"
                  className={`ac-source-row${on ? ' is-on' : ''}${wanted === chip.id ? ' is-wanted' : ''}`}
                  aria-pressed={on}
                  onClick={() => onToggle(chip)}
                >
                  <span className="ac-source-name">
                    {chip.label || CHIP_LABELS[chip.id] || chip.id}
                    {/* The one source that leaves the Mac says so, every time. */}
                    {chip.external && <span className="ac-source-tag">leaves your Mac</span>}
                  </span>
                  <span className="ac-source-state">{state}</span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </Sheet>
  )
}

/** With what, and how hard: model, effort, capability, specialists. Who
 *  answers moved to ThreadsSheet (SPEC-v40 §5). */
function ReasoningSheet({
  model, effort, running,
  askSpecialists, specialistRoles, specialistRoster, accent,
  grantedCapabilities, onToggleCapability,
  onPickModel, onPickEffort, onToggleSpecialists, onToggleRole, onClose,
}) {
  return (
    <Sheet open onClose={onClose} title="Reasoning" variant="dialog">
      <div style={{ '--agent': accent }}>
        <h3 className="ac-group-label">Model</h3>
        <div className="ac-option-group" role="group" aria-label="Model">
          {MODELS.map((m) => (
            <button
              key={m.id}
              type="button"
              className={`ac-chip${model === m.id ? ' is-on' : ''}`}
              aria-pressed={model === m.id}
              disabled={running}
              onClick={() => onPickModel(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>

        <h3 className="ac-group-label">Effort</h3>
        <div className="ac-option-group" role="group" aria-label="Effort">
          {EFFORTS.map((e) => (
            <button
              key={e.id}
              type="button"
              className={`ac-chip${effort === e.id ? ' is-on' : ''}`}
              aria-pressed={effort === e.id}
              disabled={running}
              onClick={() => onPickEffort(e.id)}
            >
              {e.label}
            </button>
          ))}
        </div>

        {/* SPEC-v37 §2.7: Files/Workspace/Shell. Always available, no
            connector, no "not connected" state, so these render as plain
            on/off chips (the ContextSheet "not connected" treatment above
            does not apply). Toggled through the same granted_chips
            replace-whole-array PATCH the connector chips use. Web already
            lives in "Add context" (the one source that leaves the Mac); it
            stays there rather than being duplicated here. */}
        <h3 className="ac-group-label">Capability</h3>
        <div className="ac-option-group" role="group" aria-label="Capability">
          {CAPABILITY_CHIPS.map((c) => {
            const on = grantedCapabilities.includes(c.id)
            return (
              <button
                key={c.id}
                type="button"
                className={`ac-chip${on ? ' is-on' : ''}`}
                aria-pressed={on}
                onClick={() => onToggleCapability(c.id)}
              >
                {c.label}
              </button>
            )
          })}
        </div>

        <h3 className="ac-group-label">Consult specialists</h3>
        <div className="ac-option-group" role="group" aria-label="Specialists">
          <button
            type="button"
            className={`ac-chip${askSpecialists ? ' is-on' : ''}`}
            aria-pressed={askSpecialists}
            onClick={onToggleSpecialists}
          >
            {askSpecialists ? 'On' : 'Off'}
          </button>
          {askSpecialists && specialistRoster.map((item) => (
            <button
              key={item.role}
              type="button"
              className={`ac-chip${specialistRoles.includes(item.role) ? ' is-on' : ''}`}
              aria-pressed={specialistRoles.includes(item.role)}
              onClick={() => onToggleRole(item.role)}
            >
              {item.codename || item.role}
            </button>
          ))}
        </div>
        {askSpecialists && specialistRoles.length < 2 && (
          <p className="ac-hint">Pick 2 or 3, or turn this off.</p>
        )}
      </div>
    </Sheet>
  )
}

const THREADS_PER_AGENT = 5

/** SPEC-v40 §5: every agent, its threads under it, New chat per agent.
 *  Rows are 44px. Tapping a thread loads it (reopening if archived). */
function ThreadsSheet({ roster, threads, currentThreadId, accent, onOpenThread, onNewThread, onClose }) {
  const groups = useMemo(() => groupThreadsByRole(threads, roster), [threads, roster])
  const [expanded, setExpanded] = useState(() => new Set())
  return (
    <Sheet open onClose={onClose} title="Threads" variant="dialog">
      <div style={{ '--agent': accent }}>
        {groups.map((group) => {
          const showAll = expanded.has(group.role)
          const shown = showAll ? group.threads : group.threads.slice(0, THREADS_PER_AGENT)
          const hidden = group.threads.length - shown.length
          return (
            <section key={group.role} className="ac-thread-group" style={{ '--agent': chatRoleColor(group.role) }}>
              <div className="ac-thread-agent">
                <Glyph role={group.role} />
                <span className="ac-thread-agent-name">{group.codename}</span>
                <button type="button" className="ac-thread-new" onClick={() => onNewThread(group.role)}>
                  New chat
                </button>
              </div>
              {shown.length > 0 && (
                <ul className="ac-thread-list">
                  {shown.map((t) => {
                    const isCurrent = t.id === currentThreadId
                    const tags = []
                    if (t.has_summary) tags.push('compacted')
                    if (t.status === 'CLOSED') tags.push('archived')
                    return (
                      <li key={t.id}>
                        <button
                          type="button"
                          className={`ac-thread-row${isCurrent ? ' is-current' : ''}`}
                          onClick={() => onOpenThread(t)}
                          aria-current={isCurrent ? 'true' : undefined}
                        >
                          <span className="ac-thread-title">{t.title || 'New chat'}</span>
                          <span className="ac-thread-meta">
                            {relTime(t.updated_at)}
                            {t.turn_count > 0 ? ` · ${t.turn_count} ${t.turn_count === 1 ? 'turn' : 'turns'}` : ''}
                            {tags.length ? ` · ${tags.join(' · ')}` : ''}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
              {hidden > 0 && (
                <button
                  type="button"
                  className="ac-thread-more"
                  onClick={() => setExpanded((cur) => new Set(cur).add(group.role))}
                >
                  {hidden} older
                </button>
              )}
            </section>
          )
        })}
      </div>
    </Sheet>
  )
}

/** The thread's own menu: Compact, Archive, New chat. Compact is disabled
 *  (with the reason) below the server's minimum; the server enforces it
 *  again. */
function ThreadMenuSheet({
  codename, accent, anchor, compactable, compactReason, busy,
  onCompact, onArchive, onNewThread, onClose,
}) {
  return (
    <Sheet open onClose={onClose} title="This thread" variant="popover" anchor={anchor}>
      <div className="ac-thread-menu" style={{ '--agent': accent }}>
        <button type="button" className="ac-thread-menu-row" onClick={onCompact} disabled={!compactable || busy}>
          <span>{busy ? 'Compacting…' : 'Compact this thread'}</span>
          <span className="ac-thread-menu-hint">
            {compactable ? 'Summarize it and start the model fresh. Nothing is deleted.' : compactReason}
          </span>
        </button>
        <button type="button" className="ac-thread-menu-row" onClick={onNewThread} disabled={busy}>
          <span>New chat with {codename}</span>
          <span className="ac-thread-menu-hint">This one stays in Threads.</span>
        </button>
        <button type="button" className="ac-thread-menu-row" onClick={onArchive} disabled={busy}>
          <span>Archive</span>
          <span className="ac-thread-menu-hint">Reopen it any time from Threads.</span>
        </button>
      </div>
    </Sheet>
  )
}

/** The small re-entry affordance shown when the view is 'dock' but Command
 *  isn't the active page: no portal target exists there, and floating a
 *  composer over every other page would be an osui L2/L3 violation (a second
 *  job on someone else's screen). CSS hides it under the committed modes
 *  (call, journal, shutdown, any open sheet, note editing). */
function DockPill({ role, codename, running, onExpand }) {
  return createPortal(
    <div className="consult-fixed">
      <button
        type="button"
        className="consult-pill"
        style={{ '--agent': chatRoleColor(role) }}
        onClick={onExpand}
      >
        <Glyph role={role} />
        <span className="consult-pill-label">{shortName(codename)}</span>
        {running && <span className="consult-pill-dot" aria-hidden="true" />}
      </button>
    </div>,
    document.body,
  )
}

/** First line of the last thing the agent said, for the mobile dock row. */
function lastReplyLine(turns) {
  for (let i = turns.length - 1; i >= 0; i -= 1) {
    const t = turns[i]
    if (t?.status !== 'SUCCEEDED') continue
    const line = String(t.verdict && t.verdict !== '-' ? t.verdict : t.body || '')
      .split('\n').map((s) => s.trim()).find(Boolean) || ''
    return line.replace(/[*_`#>]/g, '').slice(0, 120)
  }
  return ''
}

/** SPEC-v40 §2.1, mobile dock: one 44px row under the Order. No composer,
 *  no scroller, so Command keeps a single scroller; tapping opens the
 *  conversation and focuses the composer in the same gesture. */
function DockRow({ role, codename, turns, running, onOpen }) {
  const line = lastReplyLine(turns)
  return (
    <button
      type="button"
      className="consult-dock-row"
      style={{ '--agent': chatRoleColor(role) }}
      onClick={onOpen}
      aria-label={`Open chat with ${codename}`}
    >
      <Glyph role={role} />
      <span className="consult-dock-row-text">
        <span className="consult-dock-row-name">{codename}</span>
        {running ? (
          <span className="consult-dock-row-line ac-thinking" aria-live="polite">
            <span className="ac-dots" aria-hidden="true"><span /><span /><span /></span>
          </span>
        ) : (
          <span className="consult-dock-row-line">{line || `Ask ${shortName(codename)}`}</span>
        )}
      </span>
      <span className="consult-dock-row-chevron" aria-hidden="true">›</span>
    </button>
  )
}

export default function AgentChat({
  toast, navigate, roster = [], onBusyChange,
  // SPEC-v37 §7.1-7.3: `page` lets the dock re-locate its portal target
  // whenever Command becomes (or stops being) the active page.
  // `consultRequest` / `onConsultRequestHandled` are the unified replacement
  // for the old Ask sheet / inspect mode: App.jsx hands over
  // { role, seedText, view } and this component opens (or creates) that
  // agent's thread, seeds the composer without sending, and switches view.
  page, consultRequest, onConsultRequestHandled,
}) {
  // Set by whatever opens the conversation on purpose (dock row tap, Ask an
  // agent, Roster, Inspect); consumed by the focus layout effect below.
  const wantFocus = useRef(false)
  // The pill on non-Command pages is a re-entry affordance, not an
  // advertisement: it renders only once the conversation has been opened
  // this session (or a turn is running), see SPEC-v40 §2.5.
  const openedThisSession = useRef(false)
  const [thread, setThread] = useState(null)
  const [threads, setThreads] = useState([])
  const [chips, setChips] = useState([])
  const [question, setQuestion] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [offline, setOffline] = useState(false)
  const [expired, setExpired] = useState('')
  const [fileDraft, setFileDraft] = useState(null)
  const [filing, setFiling] = useState(false)
  const [showContext, setShowContext] = useState(false)
  const [showReasoning, setShowReasoning] = useState(false)
  // SPEC-v40 §5: the Threads sheet (who + which thread) and the thread menu.
  const [showThreads, setShowThreads] = useState(false)
  const [showThreadMenu, setShowThreadMenu] = useState(false)
  const [showEarlier, setShowEarlier] = useState(false)
  const [compacting, setCompacting] = useState(false)
  const menuTriggerRef = useRef(null)
  const [refreshMoney, setRefreshMoney] = useState(false)
  const [askSpecialists, setAskSpecialists] = useState(false)
  const [specialistRoles, setSpecialistRoles] = useState([])
  const [missingHighlight, setMissingHighlight] = useState('')
  const [undoneWrites, setUndoneWrites] = useState(() => new Set())
  const [writeHintTurnId, setWriteHintTurnId] = useState(null)
  const fieldRef = useRef(null)
  // SPEC-v29 Phase 3: ContextSheet is a desktop popover anchored to the
  // trigger that opens it, so the "+" button needs a ref to hand Sheet.
  const contextTriggerRef = useRef(null)
  // Turn ids present the moment a thread is (re)loaded: history, never
  // toasted. Only a write that lands DURING this open session fires a toast.
  const baselineTurnIds = useRef(new Set())
  const toastedWriteTurnIds = useRef(new Set())

  // SPEC-v37 §7.2: dock / expanded / fullscreen, persisted per-session.
  const [view, setView] = useState(() => readConsultView())
  useEffect(() => { writeConsultView(view) }, [view])
  const isMobile = useIsMobile()
  // The portal target CommandPage renders "under the Order". Re-resolved
  // whenever the active page changes (it only exists while page === 'home')
  // or the view changes (so switching into 'dock' immediately re-checks it).
  const [dockNode, setDockNode] = useState(null)
  useLayoutEffect(() => {
    setDockNode(document.getElementById(DOCK_SLOT_ID))
  }, [page, view])

  // A textarea does not size to its content, so a wrapped line is clipped
  // rather than shown. Reset then set from scrollHeight, which is the only
  // way to let it shrink again after a delete.
  const autoGrow = useCallback(() => {
    const node = fieldRef.current
    if (!node) return
    node.style.height = 'auto'
    node.style.height = `${node.scrollHeight}px`
  }, [])
  const pollStartedAt = useRef(Date.now())
  // The turn being polled is STATE, not a ref: the poll effect must re-arm
  // whenever it changes, including the mount-time resume path, which used to
  // set a ref after the effect had already run and so never started a timer
  // (dots forever after a reload mid-turn).
  const [pollTurnId, setPollTurnId] = useState(null)

  const fullRoster = useMemo(
    () => (Array.isArray(roster) ? roster : []).filter((r) => r?.role && r.active !== false),
    [roster],
  )
  const specialistRoster = useMemo(() => activeRoomRoles(roster), [roster])
  // SPEC-v37 3.5: before the thread loads, assume the default agent
  // (Alfred), not Fury -- the loading flash should never show the wrong name.
  const role = thread?.role || 'steward'
  const codename = useMemo(
    () => fullRoster.find((r) => r.role === role)?.codename || 'Alfred',
    [fullRoster, role],
  )
  const granted = thread?.granted_chips || []
  // "Add context" is specifically external/connector sources; Capability
  // (files/workspace/shell) is a different kind of grant, shown and counted
  // in ReasoningSheet instead. The backend's chip list already includes the
  // three capability ids alongside money/mail/calendar/etc, so both the
  // rendered rows and this badge filter them out here rather than showing
  // the same three toggles in two different sheets.
  const contextChips = useMemo(
    () => chips.filter((c) => !CAPABILITY_CHIP_IDS.has(c.id)),
    [chips],
  )
  const grantedCount = granted.filter((id) => !CAPABILITY_CHIP_IDS.has(id)).length
  const turns = thread?.turns || []
  const running = turns.some((t) => isActiveInvocation(t.status)) || submitting

  useEffect(() => { onBusyChange?.(running) }, [running, onBusyChange])

  // Reset the baseline the moment a thread (re)loads, so switching to an
  // agent with old write receipts never replays them as fresh toasts.
  useEffect(() => {
    if (!thread?.id) return
    baselineTurnIds.current = new Set(turns.map((t) => t.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thread?.id])

  // SPEC-v29 Phase 6: fire the toast the instant a write lands. Only a turn
  // that arrived after the baseline above (i.e. this session actually saw it
  // happen) qualifies, and each turn toasts at most once even if it re-renders
  // on every poll tick.
  useEffect(() => {
    for (const t of turns) {
      if (baselineTurnIds.current.has(t.id)) continue
      if (t.status !== 'SUCCEEDED') continue
      const writes = Array.isArray(t.writes) ? t.writes : []
      if (!writes.length || toastedWriteTurnIds.current.has(t.id)) continue
      toastedWriteTurnIds.current.add(t.id)
      writes.forEach((w, i) => {
        if (!w?.label) return
        toast?.(w.label, 'good', () => undoWrite(w, `${t.id}:${i}`))
      })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [turns])

  // The once-per-thread teach line: the first write ianOS sees in this
  // thread, gated in localStorage so it never repeats once shown.
  useEffect(() => {
    if (!thread?.id) return
    const firstWriteTurn = turns.find(
      (t) => Array.isArray(t.writes) && t.writes.some((w) => w?.label),
    )
    if (!firstWriteTurn || writeHintSeen(thread.id)) return
    markWriteHintSeen(thread.id)
    setWriteHintTurnId(firstWriteTurn.id)
  }, [turns, thread?.id])

  const loadThread = useCallback(async (id) => {
    const detail = await api(`/api/chat/threads/${id}`, 'GET', undefined, { cache: 'no-store' })
    setThread(detail)
    return detail
  }, [])

  // SPEC-v40 §3: every thread, every status, newest activity first. The
  // Threads sheet shows archived ones too (they reopen with a tap).
  const listThreads = useCallback(async () => {
    const listed = await api('/api/chat/threads', 'GET', undefined, { cache: 'no-store' })
    const all = listed.threads || []
    setThreads(all)
    return all
  }, [])

  // An agent's current thread is its newest OPEN one; none means a new one.
  const openFor = useCallback(async (wanted) => {
    const all = await listThreads()
    const existing = all.find((t) => t.role === wanted && t.status === 'OPEN')
    if (existing) return loadThread(existing.id)
    const created = await api('/api/chat/threads', 'POST', { role: wanted })
    await listThreads()
    return loadThread(created.id)
  }, [listThreads, loadThread])

  useEffect(() => {
    let cancelled = false
    // SPEC-v37 3.5: Alfred (steward) is the default agent, not Fury.
    // chat_prefs.default_role is the one source of truth for it.
    const init = async () => {
      const defaultRole = await api('/api/chat/prefs', 'GET', undefined, { cache: 'no-store' })
        .then((prefs) => prefs?.default_role || 'steward')
        .catch(() => 'steward')
      const [chipPayload, detail] = await Promise.all([
        api(`/api/chat/chips?role=${defaultRole}`, 'GET', undefined, { cache: 'no-store' }),
        openFor(defaultRole),
      ])
      if (cancelled) return
      setChips(chipPayload.chips || [])
      const stored = readActiveChatTurnId()
      if (!stored) return
      const found = (detail?.turns || []).find((t) => t.id === stored)
      if (found && isActiveInvocation(found.status)) {
        pollStartedAt.current = Date.now()
        setPollTurnId(stored)
      } else {
        clearActiveChatTurn(stored)
        if (!found) setExpired('That turn expired. Ask again.')
      }
    }
    init().catch((error) => {
      if (cancelled) return
      if (/offline/i.test(error.message || '')) setOffline(true)
      else toast?.(error.message, 'warn')
    })
    return () => { cancelled = true }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // SPEC-v37 §7.3: the unified replacement for the Ask sheet and inspect
  // mode. App.jsx hands over { role, seedText, view } from Roster's "Ask
  // <Codename>", a record's "Inspect" trigger, or a generic "open chat"
  // call; this opens (or creates) that agent's thread, seeds the composer
  // WITHOUT sending (Ian reviews and sends it himself), and switches view.
  useEffect(() => {
    if (!consultRequest) return undefined
    let cancelled = false
    const run = async () => {
      try {
        if (consultRequest.role && consultRequest.role !== role) {
          await openFor(consultRequest.role)
        }
      } catch (error) {
        if (!cancelled) toast?.(error.message, 'warn')
      }
      if (cancelled) return
      if (consultRequest.seedText) setQuestion(consultRequest.seedText)
      wantFocus.current = true
      setView('open')
      onConsultRequestHandled?.()
    }
    run()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consultRequest])

  // Poll the THREAD, not a per-invocation route: /api/agent-invocations/{id}
  // was deleted by SPEC-v37 §7.3 and this loop kept calling it, so every tick
  // threw before the thread refresh and the "thinking" dots never cleared
  // until a manual reload. The thread detail is the one shape the page load
  // already renders, so polling and reloading can no longer disagree.
  useEffect(() => {
    const id = pollTurnId
    if (!id || !thread?.id) return undefined
    const threadId = thread.id
    let cancelled = false
    let timer = 0
    const finish = () => {
      clearActiveChatTurn(id)
      setPollTurnId((current) => (current === id ? null : current))
      // An auto-Compact may have landed with this turn (SPEC-v40 §4.3).
      listThreads().catch(() => {})
    }
    const tick = async () => {
      try {
        const detail = await loadThread(threadId)
        if (cancelled) return
        const turn = (detail?.turns || []).find((t) => t.id === id)
        if (!turn) {
          finish()
          setExpired('That turn expired. Ask again.')
          return
        }
        if (isTerminalInvocation(turn.status)) {
          finish()
          return
        }
      } catch (error) {
        if (cancelled) return
        if (/offline/i.test(error.message || '')) setOffline(true)
      }
      timer = window.setTimeout(tick, invocationPollDelay(Date.now() - pollStartedAt.current))
    }
    timer = window.setTimeout(tick, invocationPollDelay(0))
    return () => { cancelled = true; window.clearTimeout(timer) }
    // thread.id is read once at arm time on purpose: an agent switch clears
    // pollTurnId itself (pickAgent), so the loop must not chase a new thread.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollTurnId, loadThread, listThreads])

  useEffect(() => { autoGrow() }, [question, codename, view, autoGrow])

  // Newest at the bottom with no JS: the stream is a column-reverse flex
  // column (SPEC-v40 §2.2), so a reply landing, a poll refresh, or opening
  // the surface never jumps the scroll position.

  // Opening the conversation focuses the composer inside the same gesture
  // (a layout effect runs before paint, still within the tap's task, which
  // is what iOS requires to raise the keyboard).
  useLayoutEffect(() => {
    if (view !== 'open' || !wantFocus.current) return
    wantFocus.current = false
    fieldRef.current?.focus?.()
  }, [view])

  // SPEC-v27: the source list is filtered by what THIS agent can be granted,
  // so it has to follow the thread rather than being fetched once.
  useEffect(() => {
    if (!thread?.role) return undefined
    let cancelled = false
    api(`/api/chat/chips?role=${encodeURIComponent(thread.role)}`, 'GET', undefined, { cache: 'no-store' })
      .then((payload) => { if (!cancelled) setChips(payload.chips || []) })
      .catch(() => { /* the composer still works without the list */ })
    return () => { cancelled = true }
  }, [thread?.role])

  async function patchThread(body) {
    if (!thread?.id) return
    const id = thread.id
    // Optimistic: a picker that waits on a round trip reads as broken, and
    // the second tap that follows is the actual bug report.
    setThread((current) => (current && current.id === id ? { ...current, ...body } : current))
    try {
      const updated = await api(`/api/chat/threads/${id}`, 'PATCH', body)
      // Ignore a late response for a thread Ian has already switched away
      // from, or it would repaint the new thread with the old one's settings.
      setThread((current) => (current && current.id === id ? { ...current, ...updated } : current))
    } catch (error) {
      // Put the truth back rather than leaving a lie on screen.
      loadThread(id).catch(() => {})
      throw error
    }
  }

  // ---- SPEC-v40 §5: thread actions ---------------------------------------
  // (Agent switching is a thread choice now; the Threads sheet replaces the
  // old pickAgent. A turn still running on the previous thread finishes on
  // its own, so every switch below clears pollTurnId first rather than
  // polling the old turn against the new thread.)
  async function openThread(item) {
    if (!item?.id) return
    setShowThreads(false)
    if (item.id === thread?.id) return
    try {
      setExpired('')
      setShowEarlier(false)
      setPollTurnId(null)
      if (item.status === 'CLOSED') {
        await api(`/api/chat/threads/${item.id}`, 'PATCH', { status: 'OPEN' })
      }
      await loadThread(item.id)
      listThreads().catch(() => {})
    } catch (error) {
      toast?.(error.message, 'warn')
    }
  }

  async function newThread(wanted = role) {
    setShowThreads(false)
    setShowThreadMenu(false)
    try {
      setExpired('')
      setShowEarlier(false)
      setPollTurnId(null)
      const created = await api('/api/chat/threads', 'POST', { role: wanted })
      await loadThread(created.id)
      listThreads().catch(() => {})
    } catch (error) {
      toast?.(error.message, 'warn')
    }
  }

  async function archiveThread() {
    if (!thread?.id) return
    setShowThreadMenu(false)
    const archivedRole = role
    try {
      await api(`/api/chat/threads/${thread.id}`, 'PATCH', { status: 'CLOSED' })
      toast?.('Archived. Find it under Threads.', 'good')
      await openFor(archivedRole)
    } catch (error) {
      toast?.(error.message, 'warn')
    }
  }

  // Succeeded turns since the last Compact: the same count the server gates
  // on, so the menu can say why Compact is greyed rather than 409ing later.
  const { earlier: earlierTurns, recent: recentTurns } = partitionCompacted(turns, thread?.summary_turn_count)
  const compactableTurns = recentTurns.filter((t) => t.status === 'SUCCEEDED').length
  const COMPACT_MIN = 4
  const compactable = compactableTurns >= COMPACT_MIN && !running
  const compactReason = running
    ? 'Wait for the reply first.'
    : `Needs ${COMPACT_MIN} answered turns since the last one (${compactableTurns} so far).`

  async function compactThread() {
    if (!thread?.id || !compactable) return
    setCompacting(true)
    try {
      await api(`/api/chat/threads/${thread.id}/compact`, 'POST', {})
      await loadThread(thread.id)
      listThreads().catch(() => {})
      setShowThreadMenu(false)
      setShowEarlier(false)
      toast?.('Compacted. The thread starts fresh from its summary.', 'good')
    } catch (error) {
      toast?.(error.message, 'warn')
    } finally {
      setCompacting(false)
    }
  }

  async function toggleChip(chip) {
    setMissingHighlight('')
    const current = thread?.granted_chips || []
    if (current.includes(chip.id)) {
      await patchThread({ granted_chips: current.filter((id) => id !== chip.id) })
      if (chip.id === 'money') setRefreshMoney(false)
      return
    }
    if (!chip.connected) {
      if (chip.connect_page === 'money') {
        try { sessionStorage.setItem(CHAT_RETURN_KEY, '1') } catch { /* ignore */ }
        navigate?.('money')
        return
      }
      toast?.(chip.sync_needed_copy, 'warn')
      return
    }
    await patchThread({ granted_chips: [...current, chip.id] })
  }

  // SPEC-v37 §2.7: files/workspace/shell need none of toggleChip's connected/
  // connect-page handling, just the same replace-whole-array PATCH.
  async function toggleCapability(id) {
    const current = thread?.granted_chips || []
    const next = current.includes(id) ? current.filter((c) => c !== id) : [...current, id]
    try {
      await patchThread({ granted_chips: next })
    } catch (error) {
      toast?.(error.message, 'warn')
    }
  }

  async function submit(nextQuestion = question, workflows) {
    if (!thread?.id || running) return
    const text = String(nextQuestion || '').trim()
    if (!text || text.length > MAX_QUESTION) return
    setSubmitting(true)
    setOffline(false)
    setExpired('')
    // Copy: never mutate a caller's array (SPEC-v25 review finding).
    const flow = [...(workflows || [])]
    if (refreshMoney) flow.push('refresh_money')
    if (askSpecialists && specialistRoles.length >= 2) {
      flow.push({ kind: 'consult_specialists', roles: specialistRoles })
    }
    const payload = { question: text }
    if (flow.length) payload.workflows = flow
    try {
      const created = await api(`/api/chat/threads/${thread.id}/turns`, 'POST', payload)
      rememberActiveChatTurn(created.id)
      pollStartedAt.current = Date.now()
      setQuestion('')
      setRefreshMoney(false)
      await loadThread(thread.id)
      setPollTurnId(created.id)
      // The first question titles the thread (SPEC-v40 §3.2).
      listThreads().catch(() => {})
    } catch (error) {
      const message = error.message || ''
      if (/offline/i.test(message)) setOffline(true)
      else if (message.includes('is not connected')) {
        try { sessionStorage.setItem(CHAT_RETURN_KEY, '1') } catch { /* ignore */ }
        navigate?.('money')
      } else toast?.(message, 'warn')
    } finally {
      setSubmitting(false)
    }
  }

  // SPEC-v29 Phase 6 undo: reuses the app's own write/undo endpoints per
  // domain rather than growing a second implementation (README precedent).
  // agents/runner.py's write descriptor now carries the created record's row
  // id (api/main.py's _stored_chat_fields sanitizes it to an int or null),
  // so every domain reverses the SPECIFIC row it created; a missing id still
  // fails safe with an honest message instead of guessing one. These are
  // interactive deletes, not offline-queued daily-capture writes, so the
  // api() calls below take no extra options (see lib/api.js's own note on
  // that distinction).
  async function reverseWrite(write) {
    const tool = write?.tool
    if (tool === 'chat_confirm_gym') {
      await api('/api/gym/unconfirm', 'POST', {})
      return
    }
    const id = write?.id
    if (id == null) {
      throw new Error("Can't undo this one yet, undo it from its own page instead.")
    }
    if (tool === 'chat_write_goal') { await api(`/api/goals/${id}/archive`, 'POST'); return }
    if (tool === 'chat_write_plan_block') { await api(`/api/plan/blocks/${id}`, 'DELETE'); return }
    if (tool === 'chat_write_note') { await api(`/api/notes/${id}`, 'DELETE'); return }
    if (tool === 'chat_write_partner_task') { await api(`/api/partner-tasks/${id}`, 'DELETE'); return }
    if (tool === 'chat_write_task') { await api(`/api/tasks/${id}`, 'DELETE'); return }
    if (tool === 'write_fact') { await api(`/api/facts/${id}`, 'DELETE'); return }
    if (tool === 'chat_write_learning_profile') {
      throw new Error("Learning profiles can't be undone from here, edit the topic on the Learning page.")
    }
    throw new Error('Nothing to undo for this one.')
  }

  async function undoWrite(write, key) {
    try {
      await reverseWrite(write)
      setUndoneWrites((cur) => new Set(cur).add(key))
    } catch (error) {
      toast?.(error.message || "Undo didn't go through", 'warn')
    }
  }

  async function copyDraft(draft) {
    try {
      await navigator.clipboard.writeText(draftPlainText(draft))
      toast?.('Copied', 'good')
    } catch {
      toast?.('Copy failed', 'warn')
    }
  }

  async function confirmFile() {
    if (!fileDraft || !thread?.id) return
    setFiling(true)
    try {
      await api(`/api/chat/threads/${thread.id}/turns/${fileDraft.id}/file`, 'POST', {})
      toast?.('Filed in Inbox', 'good')
      setFileDraft(null)
    } catch (error) {
      toast?.(error.message, 'warn')
    } finally {
      setFiling(false)
    }
  }

  const specialistsReady = !askSpecialists || specialistRoles.length >= 2
  // Desktop: Enter sends, Shift+Enter newlines. Phone: there is no Shift+Enter,
  // so Enter newlines and only the 44px send button sends (SPEC-v40 §2.4).
  const enterSends = !isMobile

  function openConversation() {
    wantFocus.current = true
    openedThisSession.current = true
    setView('open')
  }
  function closeConversation() {
    setView('dock')
  }

  // ---- the conversation: header + stream + composer, one flex column -----
  // mode 'dock' is the desktop card under the Order (last exchange + composer,
  // no inner scroller); mode 'open' is the full-height surface (phone: fixed
  // inset 0; desktop: the right-anchored drawer). Same component either way,
  // so the composer, its draft, and every sub-sheet's state carry across.
  function renderPanel(mode) {
    const compact = mode === 'dock'
    const shownTurns = compact ? turns.slice(-1) : turns
    // column-reverse pins the newest message to the bottom with no JS, so the
    // DOM order is newest-first; the empty state and banners come last in
    // DOM, i.e. sit above the oldest message. A compacted thread shows its
    // recent turns, then a divider, then (on request) the summarized ones.
    const compacted = !compact && earlierTurns.length > 0
    const ordered = compact ? [...shownTurns].reverse() : [...recentTurns].reverse()
    const olderOrdered = compacted && showEarlier ? [...earlierTurns].reverse() : []
    const renderTurn = (turn) => (
      <Exchange
        key={turn.id}
        turn={turn}
        role={role}
        codename={codename}
        onCopyDraft={copyDraft}
        onFileDraft={setFileDraft}
        onRetry={(item) => submit(item.question, [])}
        onTapMissing={(chip) => {
          setMissingHighlight(chip)
          setShowContext(true)
        }}
        onUndoWrite={undoWrite}
        undoneWrites={undoneWrites}
        showWriteHint={turn.id === writeHintTurnId}
      />
    )
    return (
      <div className={`consult-panel consult-panel--${mode}`} style={{ '--agent': chatRoleColor(role) }}>
        <header className="consult-panel-head">
          <button
            type="button"
            className="consult-panel-agent"
            onClick={() => setShowThreads(true)}
            aria-haspopup="dialog"
            aria-label={`${codename}: switch agent or thread`}
          >
            <Glyph role={role} />
            <span className="consult-panel-agent-name">{codename}</span>
            <span className="ac-caret" aria-hidden="true">▾</span>
          </button>
          <div className="consult-panel-actions">
            {!compact && (
              <button
                type="button"
                ref={menuTriggerRef}
                className="consult-icon-btn"
                onClick={() => setShowThreadMenu(true)}
                aria-haspopup="dialog"
                aria-label="Thread menu"
              >
                <span aria-hidden="true">⋯</span>
              </button>
            )}
            {compact ? (
              <button
                type="button"
                className="consult-icon-btn"
                onClick={openConversation}
                aria-label="Open chat"
              >
                <span aria-hidden="true">⤢</span>
              </button>
            ) : (
              <button
                type="button"
                className="consult-icon-btn"
                onClick={closeConversation}
                aria-label="Close chat"
              >
                <span aria-hidden="true">×</span>
              </button>
            )}
          </div>
        </header>

        <div className="ac-stream">
          {ordered.map(renderTurn)}

          {compacted && (
            <div className="ac-compacted" role="separator" aria-label="Compacted">
              <span className="ac-compacted-line" aria-hidden="true" />
              <span className="ac-compacted-text">
                Compacted · {earlierTurns.length} {earlierTurns.length === 1 ? 'turn' : 'turns'}
                {thread?.compacted_at ? ` · ${relTime(thread.compacted_at)}` : ''}
              </span>
              <button
                type="button"
                className="ac-compacted-toggle"
                onClick={() => setShowEarlier((v) => !v)}
                aria-expanded={showEarlier}
              >
                {showEarlier ? 'Hide earlier' : 'Show earlier'}
              </button>
              <span className="ac-compacted-line" aria-hidden="true" />
            </div>
          )}
          {olderOrdered.map(renderTurn)}

          {shownTurns.length === 0 && !offline && (
            <div className="ac-empty">
              <span className="ac-empty-mark" aria-hidden="true">{roleGlyph(role)}</span>
              <p className="ac-empty-name">{codename}</p>
              <p className="ac-empty-line">Reads your record. Never acts on it.</p>
            </div>
          )}
          {expired && <p className="ac-banner" role="status">{expired}</p>}
          {offline && (
            <p className="ac-banner" role="status">Offline. Your Mac is not reachable.</p>
          )}
        </div>

        <form
          className="ac-dock"
          onSubmit={(event) => { event.preventDefault(); submit() }}
        >
          <div className="ac-bar">
            <button
              type="button"
              ref={contextTriggerRef}
              className="ac-plus"
              onClick={() => setShowContext(true)}
              aria-haspopup="dialog"
              aria-label="Add context"
            >
              +
              {grantedCount > 0 && <span className="ac-plus-count">{grantedCount}</span>}
            </button>

            <label className="sr-only" htmlFor="ac-question">Ask {codename}</label>
            <textarea
              id="ac-question"
              ref={fieldRef}
              value={question}
              onChange={(event) => {
                setQuestion(event.target.value.slice(0, MAX_QUESTION))
                autoGrow()
              }}
              rows={1}
              maxLength={MAX_QUESTION}
              placeholder={`Ask ${shortName(codename)}`}
              enterKeyHint={enterSends ? 'send' : 'enter'}
              autoCapitalize="sentences"
              onKeyDown={(event) => {
                if (enterSends && event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  if (!running && question.trim() && specialistsReady) submit()
                }
              }}
            />

            <button
              type="button"
              className="ac-reasoning"
              onClick={() => setShowReasoning(true)}
              aria-haspopup="dialog"
            >
              {modelLabel(thread?.model)} <span aria-hidden="true">·</span> {effortLabel(thread?.effort)}
              <span className="ac-caret" aria-hidden="true">▾</span>
            </button>

            <button
              type="submit"
              className="ac-send"
              disabled={running || !question.trim() || !specialistsReady}
              aria-label="Send"
            >
              ↑
            </button>
          </div>
          {!specialistsReady && (
            <p className="ac-hint">Pick 2 or 3 specialists, or turn that off.</p>
          )}
        </form>
      </div>
    )
  }

  // Sub-sheets are siblings of the conversation, never children (SPEC-v40
  // §2.4): a sheet inside the open conversation's own Sheet would nest two
  // focus traps, and Escape would close both at once.
  const sheets = (
    <>
      {showContext && (
        <ContextSheet
          chips={contextChips}
          granted={granted}
          wanted={missingHighlight}
          accent={chatRoleColor(role)}
          anchor={contextTriggerRef}
          onToggle={(chip) => toggleChip(chip).catch((e) => toast?.(e.message, 'warn'))}
          onClose={() => { setShowContext(false); setMissingHighlight('') }}
        />
      )}
      {showThreads && (
        <ThreadsSheet
          roster={fullRoster}
          threads={threads}
          currentThreadId={thread?.id}
          accent={chatRoleColor(role)}
          onOpenThread={openThread}
          onNewThread={newThread}
          onClose={() => setShowThreads(false)}
        />
      )}
      {showThreadMenu && (
        <ThreadMenuSheet
          codename={codename}
          accent={chatRoleColor(role)}
          anchor={menuTriggerRef}
          compactable={compactable}
          compactReason={compactReason}
          busy={compacting}
          onCompact={compactThread}
          onArchive={archiveThread}
          onNewThread={() => newThread(role)}
          onClose={() => setShowThreadMenu(false)}
        />
      )}
      {showReasoning && (
        <ReasoningSheet
          model={thread?.model || DEFAULT_MODEL}
          effort={thread?.effort || DEFAULT_EFFORT}
          running={running}
          askSpecialists={askSpecialists}
          specialistRoles={specialistRoles}
          specialistRoster={specialistRoster}
          accent={chatRoleColor(role)}
          grantedCapabilities={granted}
          onToggleCapability={toggleCapability}
          onPickModel={(id) => patchThread({ model: id }).catch((e) => toast?.(e.message, 'warn'))}
          onPickEffort={(id) => patchThread({ effort: id }).catch((e) => toast?.(e.message, 'warn'))}
          onToggleSpecialists={() => setAskSpecialists((v) => { if (v) setSpecialistRoles([]); return !v })}
          onToggleRole={(r) => setSpecialistRoles((cur) => toggleRoomRole(cur, r, specialistRoster))}
          onClose={() => setShowReasoning(false)}
        />
      )}
      {fileDraft && (
        <FileDraftDialog
          draft={fileDraft.draft}
          busy={filing}
          onCancel={() => setFileDraft(null)}
          onConfirm={confirmFile}
        />
      )}
    </>
  )

  // ---- SPEC-v40 §2.1: two states, and the render target for each -------
  if (view === 'dock') {
    if (dockNode) {
      return (
        <>
          {createPortal(
            isMobile
              ? <DockRow role={role} codename={codename} turns={turns} running={running} onOpen={openConversation} />
              : renderPanel('dock'),
            dockNode,
          )}
          {sheets}
        </>
      )
    }
    // Command isn't the active page: a compact re-entry pill, and only once
    // the conversation has actually been used this session (or is answering).
    if (running || openedThisSession.current) {
      return (
        <>
          <DockPill role={role} codename={codename} running={running} onExpand={openConversation} />
          {sheets}
        </>
      )
    }
    return sheets
  }

  // view === 'open'. Phone: the conversation IS the screen (fixed inset 0,
  // tab bar hidden via body.sheet-open, Escape/focus trap from Sheet).
  // Desktop: a right-anchored drawer; the page stays usable behind it.
  // Sheet's own head is hidden by CSS on both: the panel's header carries the
  // identity button and the close control.
  return (
    <>
      <Sheet
        open
        onClose={closeConversation}
        title={codename}
        variant={isMobile ? 'dialog' : 'drawer'}
        className={isMobile ? 'consult-sheet consult-sheet--full' : 'consult-sheet consult-sheet--drawer'}
      >
        {renderPanel('open')}
      </Sheet>
      {sheets}
    </>
  )
}
