import React, { useState } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'
import Sheet from './Sheet.jsx'

const ALL_LINKS = [
  { id: 'home', label: 'Command', short: 'Cmd', icon: '◈', section: 'top' },
  { id: 'plan', label: 'Plan', short: 'Plan', icon: '▤', section: 'top' },
  { id: 'btc', label: 'Beat the Clock', short: 'BtC', icon: '◆', section: 'pillars' },
  { id: 'body', label: 'Body', short: 'Body', icon: '◉', section: 'pillars' },
  { id: 'partner', label: 'Partner', short: 'Partner', icon: '♥', badge: 'partner', section: 'pillars' },
  { id: 'school', label: 'School', short: 'School', icon: '△', section: 'pillars' },
  { id: 'life', label: 'Life', short: 'Life', icon: '○', section: 'pillars' },
  { id: 'learning', label: 'Learning', short: 'Learn', icon: '✎', section: 'pillars' },
  { id: 'money', label: 'Money', short: 'Money', icon: '$', tone: 'money', section: 'pillars' },
  { id: 'inbox', label: 'Inbox', short: 'Inbox', icon: '◇', badge: 'pending', section: 'system' },
  { id: 'log', label: 'Log', short: 'Log', icon: '+', section: 'system' },
  { id: 'memory', label: 'Memory', short: 'Memory', icon: '❋', section: 'system' },
  { id: 'notes', label: 'Notes', short: 'Notes', icon: '≡', section: 'system' },
  { id: 'roster', label: 'Roster', short: 'Roster', icon: '⬡', section: 'system' },
  { id: 'journal', label: 'Journal', short: 'Jrnl', icon: '☾', section: 'system' },
]

const MOBILE_PRIMARY = ['home', 'plan', 'btc', 'partner']
const ALL_MOBILE_MORE = ['body', 'school', 'life', 'learning', 'money',
                         'inbox', 'log', 'memory', 'notes', 'roster', 'journal']

function NavLink({ link, active, badge, onNavigate, compact }) {
  return (
    <button
      type="button"
      className={`nav-link${active ? ' active' : ''}${compact ? ' nav-link-compact' : ''}`}
      onClick={() => onNavigate(link.id)}
      aria-current={active ? 'page' : undefined}
      title={link.label}
      data-nav-id={link.id}
    >
      {active && !compact && (
        <motion.span
          className="nav-glow"
          layoutId="nav-glow"
          transition={{ type: 'spring', stiffness: 380, damping: 32 }}
        />
      )}
      <span className={`nav-icon${link.tone ? ` nav-icon-${link.tone}` : ''}`}>{link.icon}</span>
      <span className="nav-label">{compact ? link.short : link.label}</span>
      {badge != null && (
        <span className={`nav-badge${link.badge === 'partner' ? ' nav-badge-partner' : ''}${link.badge === 'pending' && link.urgent ? ' urgent' : ''}`}>{badge}</span>
      )}
    </button>
  )
}

function badgeFor(link, pending, partnerOpen, urgent) {
  if (link.badge === 'pending' && pending > 0) return pending
  if (link.badge === 'partner' && partnerOpen > 0) return partnerOpen
  return null
}

export default function Nav({ page, onNavigate, pending = 0, partnerOpen = 0, urgent = false, onOpenPalette }) {
  const [moreOpen, setMoreOpen] = useState(false)
  const LINKS = ALL_LINKS
  const MOBILE_MORE = ALL_MOBILE_MORE
  const moreActive = MOBILE_MORE.includes(page)
  let lastSection = null

  return (
    <>
      <nav className="nav-rail nav-desktop" aria-label="Main navigation">
        <div className="nav-brand-row">
          <a className="nav-brand" href="#home" onClick={(e) => { e.preventDefault(); onNavigate('home') }} aria-label="ianOS home">
            <img className="nav-logo" src="/logo-lockup.png" alt="" width="640" height="306" decoding="async" />
          </a>
        </div>
        {onOpenPalette && (
          <button
            type="button"
            className="nav-jump"
            onClick={onOpenPalette}
            aria-label="Open command palette"
          >
            <span>Jump</span>
            <kbd>⌘K</kbd>
          </button>
        )}
        <ul className="nav-list">
          {LINKS.map((link) => {
            const active = page === link.id
            const badge = badgeFor(link, pending, partnerOpen, urgent)
            const showDivider = lastSection && link.section !== lastSection
            lastSection = link.section
            return (
              <li key={link.id} className={showDivider ? 'nav-divider' : ''}>
                <NavLink link={{ ...link, urgent }} active={active} badge={badge} onNavigate={onNavigate} />
              </li>
            )
          })}
        </ul>
      </nav>

      {/* Portal to <body>: fixed bottom must not inherit a shortened containing
          block from display:contents / transforms inside .app-shell (Safari). */}
      {createPortal(
        <nav className="nav-mobile" aria-label="Mobile navigation">
          {MOBILE_PRIMARY.map((id) => {
            const link = LINKS.find((l) => l.id === id)
            if (!link) return null
            return (
              <NavLink
                key={id}
                link={{ ...link, urgent }}
                active={page === id}
                badge={badgeFor(link, pending, partnerOpen, urgent)}
                onNavigate={onNavigate}
                compact
              />
            )
          })}
          <button
            type="button"
            className={`nav-link nav-link-compact nav-more${moreActive ? ' active' : ''}`}
            onClick={() => setMoreOpen(!moreOpen)}
            aria-expanded={moreOpen}
            aria-haspopup="true"
          >
            <span className="nav-icon">⋯</span>
            <span className="nav-label">More</span>
            {(pending > 0 || moreActive) && pending > 0 && (
              <span className={`nav-badge${urgent ? ' urgent' : ''}`}>{pending}</span>
            )}
          </button>
        </nav>,
        document.body,
      )}

      {/* A list of navigation destinations is drawer weight, not popover or
          dialog (SPEC-v29 Phase 3). Migrating onto <Sheet> fixes the missing
          Escape handler and focus trap for free: this sheet had neither. */}
      <Sheet open={moreOpen} onClose={() => setMoreOpen(false)} title="More" variant="drawer">
        {onOpenPalette && (
          <div className="nav-more-head">
            <button type="button" className="btn ghost"
                    onClick={() => { setMoreOpen(false); onOpenPalette() }}>
              Jump…
            </button>
          </div>
        )}
        {/* Pillars read as a grid of destinations; system pages read as a
            list of tools. Same sheet, two different kinds of thing. */}
        {[['pillars', 'Pillars'], ['system', 'System']].map(([section, heading]) => {
          const ids = MOBILE_MORE.filter(
            (id) => LINKS.find((l) => l.id === id)?.section === section,
          )
          if (!ids.length) return null
          return (
            <div key={section} className="nav-more-group">
              <span className="section-label">{heading}</span>
              <ul className={`nav-more-list nav-more-${section}`}>
                {ids.map((id) => {
                  const link = LINKS.find((l) => l.id === id)
                  return (
                    <li key={id}>
                      <NavLink
                        link={{ ...link, urgent }}
                        active={page === id}
                        badge={badgeFor(link, pending, partnerOpen, urgent)}
                        onNavigate={(pid) => { setMoreOpen(false); onNavigate(pid) }}
                        compact
                      />
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })}
      </Sheet>
    </>
  )
}
