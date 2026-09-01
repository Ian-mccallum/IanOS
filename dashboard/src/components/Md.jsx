import React from 'react'

/** Exported because App.jsx renders memo bodies with it too. It was used there
 *  without an import for months, which threw "bold is not defined" and took the
 *  whole app down, a blank screen, not a broken paragraph. */
export const bold = (s) =>
  (s || '')
    // SPEC-v26: chat replies are prose, so inline code and links have to
    // survive too. Split on all three at once; order inside the alternation
    // decides precedence when they abut.
    .split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((?:https?:\/\/|#|\/)[^\s)]+\))/g)
    .map((part, i) => {
      if (!part) return part
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i}>{part.slice(2, -2)}</strong>
      }
      if (part.startsWith('`') && part.endsWith('`')) {
        return <code key={i}>{part.slice(1, -1)}</code>
      }
      const link = /^\[([^\]]+)\]\(([^\s)]+)\)$/.exec(part)
      if (link) {
        const href = link[2]
        // Only same-origin or hash targets open in place; anything external
        // gets noopener so a model-authored link cannot reach window.opener.
        const external = /^https?:\/\//.test(href)
        return (
          <a
            key={i}
            href={href}
            {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
          >
            {link[1]}
          </a>
        )
      }
      return part
    })

/** Tiny markdown renderer for chief briefs (#, ##, **, -, |tables|). */
export default function Md({ text }) {
  const out = []
  let list = null
  let table = null
  let blockKey = 0
  const flush = () => {
    if (list) { out.push(<ul key={`ul-${blockKey++}`}>{list}</ul>); list = null }
    if (table) {
      out.push(
        <div className="md-table-wrap" key={`tb-${blockKey++}`}>
          <table><tbody>{table}</tbody></table>
        </div>)
      table = null
    }
  }
  const inline = bold
  for (const [i, raw] of (text || '').split('\n').entries()) {
    const line = raw.trimEnd()
    if (/^#{1,3} /.test(line)) {
      flush()
      const level = line.match(/^#+/)[0].length
      const Tag = `h${Math.min(level + 1, 4)}`
      out.push(<Tag key={`h-${i}`}>{inline(line.replace(/^#+ /, ''))}</Tag>)
    } else if (/^\|/.test(line)) {
      if (list) flush()
      if (/^\|[\s\-|:]+\|$/.test(line)) continue
      table = table || []
      const cells = line.replace(/^\||\|$/g, '').split('|').map((c) => c.trim())
      table.push(
        <tr key={`tr-${i}`}>
          {cells.map((c, j) =>
            table.length === 0
              ? <th key={j}>{inline(c)}</th>
              : <td key={j}>{inline(c)}</td>)}
        </tr>)
    } else if (/^[-*] /.test(line)) {
      if (table) flush()
      list = list || []
      list.push(<li key={`li-${i}`}>{inline(line.slice(2))}</li>)
    } else if (/^-{3,}$/.test(line.trim())) {
      flush()
      out.push(<hr key={`hr-${i}`} />)
    } else if (line.trim() === '') {
      flush()
    } else {
      flush()
      out.push(<p key={`p-${i}`}>{inline(line)}</p>)
    }
  }
  flush()
  return <div className="md">{out}</div>
}
