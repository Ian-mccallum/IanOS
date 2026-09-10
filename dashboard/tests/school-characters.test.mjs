import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BASE_LETTER, CHARACTER_SETS, COURSE_CHARACTER_SETS, characterSetFor, jumpIndex, nextIndexForKey,
} from '../src/components/school-notes/characters.js'

test('only Viking Mythology gets a character set', () => {
  assert.deepEqual(Object.keys(COURSE_CHARACTER_SETS), ['SPAN 210'])
  assert.equal(characterSetFor('SPAN 210'), CHARACTER_SETS.old_norse)
  assert.equal(characterSetFor('ECON 110'), null)
  assert.equal(characterSetFor(undefined), null)
})

test('capitals line up with lowercase, letter for letter', () => {
  const { lower, upper } = CHARACTER_SETS.old_norse
  assert.equal(lower.length, upper.length)
  lower.forEach((ch, i) => assert.equal(upper[i], ch.toUpperCase(), `column ${i}`))
})

test('every letter can be reached from the keyboard', () => {
  for (const ch of CHARACTER_SETS.old_norse.lower) {
    assert.ok(BASE_LETTER[ch], `${ch} has no base letter, so no key reaches it`)
  }
})

test('the set is only letters the keyboard does not already type', () => {
  for (const ch of [...CHARACTER_SETS.old_norse.lower, ...CHARACTER_SETS.old_norse.upper]) {
    assert.ok(ch.codePointAt(0) > 127, `${ch} is plain ASCII`)
  }
})

test('typing the plain letter jumps to it, and again moves on', () => {
  const row = CHARACTER_SETS.old_norse.lower
  assert.equal(row[nextIndexForKey(row, 't')], 'þ')
  assert.equal(row[nextIndexForKey(row, 'd')], 'ð')
  const first = nextIndexForKey(row, 'o')
  const second = nextIndexForKey(row, 'o', first)
  assert.deepEqual([row[first], row[second]], ['ó', 'ö'])
  assert.equal(row[nextIndexForKey(row, 'a', nextIndexForKey(row, 'a'))], 'æ')
  const upper = CHARACTER_SETS.old_norse.upper
  assert.equal(upper[nextIndexForKey(upper, 'T')], 'Þ')
  assert.equal(nextIndexForKey(row, 'z'), -1)
  assert.equal(nextIndexForKey(row, 'th'), -1)
})

test('a fresh letter lands on its first variant; the same letter again cycles', () => {
  const row = CHARACTER_SETS.old_norse.lower
  const thorn = row.indexOf('þ')
  const first = jumpIndex(row, 'o', thorn)
  assert.equal(row[first], 'ó', 'o typed while on þ must start at ó, not continue to ö')
  assert.equal(row[jumpIndex(row, 'o', first)], 'ö')
  const last = row.indexOf('œ')
  assert.equal(row[jumpIndex(row, 'o', last)], 'ó', 'cycling wraps back to the first o')
  assert.equal(row[jumpIndex(row, 't', -1)], 'þ')
})
