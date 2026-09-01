import assert from 'node:assert/strict'
import test from 'node:test'

import { draftLabel, draftPlainText, formatProposalDue } from '../src/lib/proposals.js'

test('draft text is a closed plain-text projection', () => {
  const attachment = {
    type: 'email_draft',
    to_label: 'Partner',
    subject: 'Dinner',
    body: 'Are you free Friday?',
    html: '<a href="https://example.com">send</a>',
    provider: 'gmail',
  }
  assert.equal(draftPlainText(attachment), 'To: Partner\nSubject: Dinner\n\nAre you free Friday?')
  assert.equal(draftPlainText({ type: 'unknown', body: 'hidden' }), '')
  assert.equal(draftLabel('message_draft'), 'Message draft')
})

test('proposal due formatting is safe for missing and invalid values', () => {
  assert.equal(formatProposalDue(null), '')
  assert.equal(formatProposalDue('not-a-date'), '')
  assert.ok(formatProposalDue('2026-08-18T15:00:00'))
})

