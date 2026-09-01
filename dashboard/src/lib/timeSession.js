/** Morning = before noon, evening = noon and after. Used for action ordering. */
export function sessionKind(date = new Date()) {
  return date.getHours() < 12 ? 'morning' : 'evening'
}

export function greeting(date = new Date()) {
  const h = date.getHours()
  if (h < 5) return 'Late night'
  if (h < 12) return 'Good morning'
  if (h < 17) return 'Good afternoon'
  return 'Good evening'
}
