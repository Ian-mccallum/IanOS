const START_COMMAND = /^(ask|tell)\s+(\S+)\s+(\S[\s\S]*)$/i

/**
 * Recognize "ask/tell <agent> <question>" syntax only.
 *
 * SPEC-v37 7.3 deleted /api/agent-commands (the server-side resolver this
 * used to hand off to) along with the whole Ask sheet it opened. Role/
 * codename resolution moved here, client-side, resolved against the same
 * roster the Roster page already renders (state.roster) -- there is no
 * server round trip left to defer it to, and the roster is small enough
 * that this needs no fuzzy matching, just the same prefix-match precedence
 * the deleted server code used.
 */
export function parseAgentCommand(value) {
  const command = String(value || '').trim()
  if (!command) return null
  if (START_COMMAND.test(command)) return { type: 'start', command }
  return null
}

/**
 * Resolve "ask/tell <agent> <question>" against the active roster.
 * Longest matching role/codename label wins; an ambiguous or unmatched
 * label returns null rather than guessing.
 */
export function resolveAgentCommand(value, roster) {
  const match = String(value || '').trim().match(START_COMMAND)
  if (!match) return null
  const remainder = match[2] + ' ' + match[3]
  const folded = remainder.toLowerCase()

  const matches = []
  for (const agent of roster || []) {
    if (!agent?.active) continue
    const labels = new Set()
    if (agent.role) labels.add(String(agent.role))
    if (agent.codename) {
      labels.add(String(agent.codename))
      labels.add(String(agent.codename).split(/\s+/)[0])
    }
    for (const label of labels) {
      if (!label) continue
      const labelFolded = label.toLowerCase()
      const prefix = `${labelFolded} `
      if (folded.startsWith(prefix)) {
        const question = remainder.slice(label.length).trim()
        matches.push({ length: label.length, role: agent.role, question })
      }
    }
  }
  if (!matches.length) return null
  const longest = Math.max(...matches.map((m) => m.length))
  const finalists = matches.filter((m) => m.length === longest)
  const byRole = new Map(finalists.map((m) => [m.role, m]))
  if (byRole.size !== 1) return null
  const picked = finalists[0]
  if (!picked.question) return null
  return { role: picked.role, question: picked.question.slice(0, 1500) }
}
