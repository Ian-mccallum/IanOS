import assert from 'node:assert/strict'
import test from 'node:test'

import { COURSE_TONES, courseTone } from '../src/lib/courseColors.js'

const courses = [
  { code: 'CS 225' },
  { code: 'ECON 202' },
  { code: 'FIN 221' },
]

test('same course code always returns the same tone', () => {
  const first = courseTone('ECON 202', courses)
  const second = courseTone('ECON 202', courses)
  assert.equal(first, second)
  assert.equal(first, COURSE_TONES[1])
})

test('different course codes return different tones', () => {
  const a = courseTone('CS 225', courses)
  const b = courseTone('ECON 202', courses)
  assert.notEqual(a, b)
})

test('an unknown course code returns null', () => {
  assert.equal(courseTone('MATH 999', courses), null)
})

test('missing course code returns null without throwing', () => {
  assert.equal(courseTone(null, courses), null)
  assert.equal(courseTone(undefined, courses), null)
  assert.equal(courseTone('', courses), null)
})

test('missing or malformed courses array returns null without throwing', () => {
  assert.equal(courseTone('CS 225', undefined), null)
  assert.equal(courseTone('CS 225', null), null)
  assert.equal(courseTone('CS 225', 'not-an-array'), null)
  assert.equal(courseTone('CS 225', []), null)
})

test('tone cycles: a 7th course wraps back to the 1st color', () => {
  const sevenCourses = [
    { code: 'A' }, { code: 'B' }, { code: 'C' }, { code: 'D' },
    { code: 'E' }, { code: 'F' }, { code: 'G' },
  ]
  assert.equal(courseTone('A', sevenCourses), COURSE_TONES[0])
  assert.equal(courseTone('G', sevenCourses), COURSE_TONES[0])
  assert.equal(courseTone('F', sevenCourses), COURSE_TONES[5])
})
