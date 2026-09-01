import { afterEach, expect, it } from 'vitest'

// SPEC-v37 §7.3 deleted lib/agentInvocations.js along with the Ask sheet,
// inspect mode, and rooms it backed (agent-invocations.test.mjs used to live
// here). The chat-turn invocation-cache slice of it is still load-bearing --
// AgentChat.jsx is its one remaining consumer -- so it moved inline there
// and is exported for this test the same way CommandPage.jsx exports
// visibleActs for command-page.ui.test.jsx. This has to be a .ui.test.jsx
// (vitest+jsdom), not a plain node:test .test.mjs like its predecessor:
// AgentChat.jsx contains JSX, which plain Node can't parse.
import {
  ACTIVE_CHAT_TURN_KEY,
  activeRoomRoles,
  clearActiveChatTurn,
  invocationPollDelay,
  isActiveInvocation,
  isTerminalInvocation,
  readActiveChatTurnId,
  rememberActiveChatTurn,
  toggleRoomRole,
} from '../src/components/AgentChat.jsx'

afterEach(() => {
  window.localStorage.clear()
})

it('consultation polling backs off only after twenty seconds', () => {
  expect(invocationPollDelay(0)).toBe(1500)
  expect(invocationPollDelay(19_999)).toBe(1500)
  expect(invocationPollDelay(20_000)).toBe(3000)
  expect(invocationPollDelay(90_000)).toBe(3000)
})

it('only active statuses keep polling', () => {
  expect(isActiveInvocation('QUEUED')).toBe(true)
  expect(isActiveInvocation('RUNNING')).toBe(true)
  expect(isActiveInvocation('SUCCEEDED')).toBe(false)
  expect(isTerminalInvocation('SUCCEEDED')).toBe(true)
  expect(isTerminalInvocation('FAILED')).toBe(true)
})

it('specialist convening (SPEC-v37 §3.6) stops at three eligible non-chief active roles', () => {
  const roster = [
    { role: 'chief', active: true },
    { role: 'scout', active: true },
    { role: 'cfo', active: true },
    { role: 'watchdog', active: true },
    { role: 'coach', active: false },
  ]
  const eligible = activeRoomRoles(roster)
  expect(eligible.map((item) => item.role)).toEqual(['scout', 'cfo', 'watchdog'])

  let selected = []
  for (const item of eligible) {
    selected = toggleRoomRole(selected, item.role, eligible)
  }
  // A 4th role (not in `eligible`) never gets in, and the cap holds at 3.
  selected = toggleRoomRole(selected, 'coach', eligible)
  expect(selected).toEqual(['scout', 'cfo', 'watchdog'])

  // Toggling an already-selected role removes it.
  selected = toggleRoomRole(selected, 'cfo', eligible)
  expect(selected).toEqual(['scout', 'watchdog'])
})

it('chat turn resume uses its own key and round-trips through localStorage', () => {
  expect(rememberActiveChatTurn(88)).toBe(true)
  expect(window.localStorage.getItem(ACTIVE_CHAT_TURN_KEY)).toBe('88')
  expect(readActiveChatTurnId()).toBe(88)

  // Clearing a different id is a no-op; clearing the right one empties it.
  expect(clearActiveChatTurn(41)).toBe(false)
  expect(readActiveChatTurnId()).toBe(88)
  expect(clearActiveChatTurn(88)).toBe(true)
  expect(readActiveChatTurnId()).toBe(null)
})

it('rejects a non-positive-integer turn id rather than storing garbage', () => {
  expect(rememberActiveChatTurn(0)).toBe(false)
  expect(rememberActiveChatTurn(-3)).toBe(false)
  expect(rememberActiveChatTurn('not a number')).toBe(false)
  expect(readActiveChatTurnId()).toBe(null)
})
