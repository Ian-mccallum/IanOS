const DRAFT_TYPES = new Set(['email_draft', 'message_draft', 'document_outline'])

export function draftLabel(type) {
  if (type === 'email_draft') return 'Email draft'
  if (type === 'message_draft') return 'Message draft'
  if (type === 'document_outline') return 'Document outline'
  return 'Draft'
}

export function draftPlainText(attachment) {
  if (!attachment || typeof attachment !== 'object' || !DRAFT_TYPES.has(attachment.type)) return ''
  const lines = []
  if (attachment.to_label) lines.push(`To: ${String(attachment.to_label)}`)
  if (attachment.subject) lines.push(`Subject: ${String(attachment.subject)}`)
  if (attachment.title) lines.push(String(attachment.title))
  if (attachment.body) {
    if (lines.length) lines.push('')
    lines.push(String(attachment.body))
  }
  return lines.join('\n').trim()
}

export function formatProposalDue(value) {
  if (!value) return ''
  const date = new Date(String(value).replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

