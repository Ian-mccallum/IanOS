import React, { useEffect, useMemo, useRef, useState } from 'react'
import { PILLAR_ORDER, isPartnerGoal } from '../lib/pillars.js'
import { useFocusTrap } from '../lib/useFocusTrap.js'
import { parseAgentCommand, resolveAgentCommand } from '../lib/agentCommands.js'

const PAGES = [
  { id: 'home', label: 'Command', kw: 'command home today brief chat fury ask agent consult' },
  { id: 'plan', label: 'Plan', kw: 'calendar day schedule time block plan' },
  { id: 'journal', label: 'Journal', kw: 'journal diary memory look back reflect photos on this day shutdown close tonight' },
  { id: 'btc', label: 'Beat the Clock', kw: 'business client sales clockwork' },
  { id: 'btc', label: 'Start a run', kw: 'call calls line run dial lead leads prospect cold call callbacks' },
  { id: 'body', label: 'Body', kw: 'gym health workout sleep' },
  { id: 'partner', label: 'Partner', kw: 'girlfriend relationship' },
  { id: 'school', label: 'School', kw: 'uiuc college move-in' },
  { id: 'life', label: 'Life', kw: 'personal passport admin' },
  { id: 'money', label: 'Money', kw: 'finance portfolio checking burn' },
  { id: 'inbox', label: 'Inbox', kw: 'proposals approve' },
  { id: 'log', label: 'Log', kw: 'calls wellness activity' },
  { id: 'memory', label: 'Memory', kw: 'facts remember' },
  { id: 'notes', label: 'Notes', kw: 'memos agents' },
  { id: 'roster', label: 'Roster', kw: 'agents track record codenames cadence' },
]

function score(query, text) {
  const q = query.toLowerCase().trim()
  if (!q) return 1
  const t = text.toLowerCase()
  if (t.includes(q)) return 10
  const words = q.split(/\s+/).filter(Boolean)
  return words.reduce((n, w) => n + (t.includes(w) ? 3 : 0), 0)
}

export default function CommandPalette({ open, onClose, onNavigate, onAskAgent, state }) {
  const [q, setQ] = useState('')
  const [idx, setIdx] = useState(0)
  const [commandError, setCommandError] = useState('')
  const inputRef = useRef(null)
  const panelRef = useRef(null)
  useFocusTrap(open, panelRef)

  useEffect(() => {
    if (open) {
      setQ('')
      setIdx(0)
      setCommandError('')
      setTimeout(() => inputRef.current?.focus(), 0)
    }
  }, [open])

  const results = useMemo(() => {
    const items = []
    const agentCommand = parseAgentCommand(q)
    if (agentCommand?.type === 'start') {
      items.push({
        type: 'agent-command',
        id: agentCommand.command,
        label: 'Ask an agent',
        sub: 'Opens a consult thread',
        score: 1000,
        command: agentCommand.command,
      })
    }
    for (const p of PAGES) {
      const s = score(q, `${p.label} ${p.kw}`)
      // L3: a generic "Go to page" caption under every one of 15 rows is
      // zero-value pixels, delete rather than shrink it.
      if (s > 0) items.push({ type: 'page', id: p.id, label: p.label, sub: '', score: s })
    }
    if (state?.pillars) {
      for (const pid of PILLAR_ORDER) {
        const p = state.pillars[pid]
        if (!p) continue
        const s = score(q, `${p.label} ${p.detail}`)
        if (s > 0) items.push({ type: 'pillar', id: pid, label: p.label, sub: p.detail, score: s + 1 })
      }
    }
    for (const g of state?.goals || []) {
      const s = score(q, `${g.name} ${g.domain} ${g.notes || ''}`)
      if (s > 0) {
        // The single source of truth for partner-vs-life routing (lib/pillars.js),
        // not a re-typed copy: a goal named "Plan Partner's birthday" with no
        // #partner note tag used to misroute to Life here while classifying
        // correctly everywhere else in the app.
        const page = g.domain === 'business' ? 'btc'
          : g.domain === 'health' ? 'body'
          : g.domain === 'finance' ? 'money'
          : g.domain === 'school' ? 'school'
          : isPartnerGoal(g) ? 'partner' : 'life'
        items.push({ type: 'goal', id: page, label: g.name, sub: `${g.status} · ${g.domain}`, score: s })
      }
    }
    // Facts are the app's only page-scoped memory store with no other search
    // surface; "jump anywhere" should reach a fact, not just a page. Journal
    // stays out (the privacy wall), it has no exception here.
    for (const f of state?.facts || []) {
      const s = score(q, `${f.topic} ${f.body} ${f.domain}`)
      if (s > 0) items.push({ type: 'fact', id: 'memory', label: f.topic, sub: f.body, score: s })
    }
    return items.sort((a, b) => b.score - a.score).slice(0, 12)
  }, [q, state])

  useEffect(() => { setIdx(0) }, [q])

  const pick = (item) => {
    if (item.type === 'agent-command') {
      const resolved = resolveAgentCommand(item.command, state?.roster)
      if (!resolved) {
        setCommandError('Unknown or ambiguous agent. Try a full codename.')
        return
      }
      setCommandError('')
      onAskAgent?.(resolved.role, resolved.question)
      onClose()
      return
    }
    onNavigate(item.id)
    onClose()
  }

  const onKey = (e) => {
    if (e.key === 'Escape') { onClose(); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx((i) => Math.min(i + 1, results.length - 1)); return }
    if (e.key === 'ArrowUp') { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); return }
    if (e.key === 'Enter' && results[idx]) { e.preventDefault(); pick(results[idx]) }
  }

  if (!open) return null

  return (
    <div className="cmdk-backdrop" onClick={onClose} role="presentation">
      <div ref={panelRef} className="cmdk-panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Command palette">
        <input
          ref={inputRef}
          className="cmdk-input"
          placeholder="Jump, or ask an agent…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          aria-activedescendant={results[idx] ? `cmdk-${idx}` : undefined}
        />
        <ul className="cmdk-list" role="listbox">
          {results.length === 0 && <li className="cmdk-empty dim">No matches</li>}
          {results.map((r, i) => (
            <li key={`${r.type}-${r.label}-${i}`}>
              <button
                id={`cmdk-${i}`}
                type="button"
                role="option"
                tabIndex={-1}
                aria-selected={i === idx}
                className={`cmdk-item${i === idx ? ' active' : ''}`}
                onClick={() => pick(r)}
                onMouseEnter={() => setIdx(i)}
              >
                <span className="cmdk-label">{r.label}</span>
                {r.sub && <span className="cmdk-sub dim">{r.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
        {commandError && <p className="cmdk-error" role="alert">{commandError}</p>}
        <p className="cmdk-hint dim">↑↓ navigate · Enter open · Esc close</p>
      </div>
    </div>
  )
}

export function useCommandPalette() {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return { open, setOpen }
}
