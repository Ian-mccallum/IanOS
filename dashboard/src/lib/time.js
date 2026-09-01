/** "now" / "12m ago" / "3h ago" / "2d ago". SQLite stores 'YYYY-MM-DD HH:MM:SS'
 *  local time, which Safari will not parse without the T. */
export function relTime(ts) {
  if (!ts) return ''
  const then = new Date(String(ts).replace(' ', 'T'))
  const mins = Math.round((Date.now() - then.getTime()) / 60000)
  if (mins < 1) return 'now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`
  return `${Math.round(mins / 1440)}d ago`
}
