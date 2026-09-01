import assert from 'node:assert/strict'
import test from 'node:test'

import { parseAgentCommand, resolveAgentCommand } from '../src/lib/agentCommands.js'

const ROSTER = [
  { role: 'chief', codename: 'Nick Fury', active: true },
  { role: 'cfo', codename: 'Jordan', active: true },
  { role: 'scout', codename: 'Dwight', active: true },
  { role: 'archivist', codename: 'Samwell Tarly', active: true },
  { role: 'advisor', codename: 'Hermione', active: false },
]

test('ask and tell commands are recognized without client role resolution', () => {
  assert.deepEqual(parseAgentCommand('ask chief What should I do next?'), {
    type: 'start',
    command: 'ask chief What should I do next?',
  })
  assert.deepEqual(parseAgentCommand('  TELL Jordan review the next two days  '), {
    type: 'start',
    command: 'TELL Jordan review the next two days',
  })
  assert.equal(parseAgentCommand('ask chief'), null)
  assert.equal(parseAgentCommand('message chief do this'), null)
})

test('resolveAgentCommand matches role id, full codename, or first word', () => {
  assert.deepEqual(
    resolveAgentCommand('ask chief What should I do next?', ROSTER),
    { role: 'chief', question: 'What should I do next?' },
  )
  assert.deepEqual(
    resolveAgentCommand('tell Jordan review the burn', ROSTER),
    { role: 'cfo', question: 'review the burn' },
  )
  assert.deepEqual(
    resolveAgentCommand('ask Samwell Tarly what changed', ROSTER),
    { role: 'archivist', question: 'what changed' },
  )
})

test('resolveAgentCommand refuses an inactive role, an unmatched label, or a blank question', () => {
  assert.equal(resolveAgentCommand('ask Hermione about UIUC', ROSTER), null)
  assert.equal(resolveAgentCommand('ask nobody what is up', ROSTER), null)
  assert.equal(resolveAgentCommand('ask chief', ROSTER), null)
  assert.equal(resolveAgentCommand('not a command', ROSTER), null)
})
