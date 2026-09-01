import assert from 'node:assert/strict'
import test from 'node:test'

const plaid = await import('../src/lib/plaid.js')

test('Plaid UI has a fixed local account vocabulary', () => {
  assert.deepEqual(plaid.PLAID_ITEM_KEYS, ['chase', 'capital_one'])
  assert.equal(plaid.PLAID_OAUTH_SESSION_KEY.includes('token'), false)
})
