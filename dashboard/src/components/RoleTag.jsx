import React from 'react'
import { roleColor, roleGlyph } from '../lib/agents.js'

function cap(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

/** Colour and glyph come from lib/agents.js, so an agent looks the same on a
 *  memo, on a proposal and on its roster card. */
export default function RoleTag({ role, roster = {}, className = 'role-tag' }) {
  const codename = roster[role]?.codename
  return (
    <span className={className} style={{ color: roleColor(role) }}>
      <span className="role-glyph" aria-hidden="true">{roleGlyph(role)}</span>
      {codename || cap(role)}
      {codename && <span className="role-sub"> · {role}</span>}
    </span>
  )
}
