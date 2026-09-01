import assert from 'node:assert/strict'
import test from 'node:test'

import {
  isUploadableSchoolFile,
  SCHOOL_FILE_ACCEPT,
  schoolFileKind,
  schoolFileSizeLabel,
} from '../src/lib/school-files.js'

test('School file classification handles a browser with an empty MIME type', () => {
  // Arrange: iOS and share sheets can omit a file MIME type entirely.
  const file = { name: 'lecture-slides.PPTX', type: '' }

  // Act / Assert: extension fallback preserves the allowed upload path.
  assert.equal(schoolFileKind(file), 'slides')
  assert.equal(isUploadableSchoolFile(file), true)
})

test('School file classification refuses executable and unknown formats', () => {
  // Arrange / Act / Assert: the client rejects bad categories before a round
  // trip; the server remains the authoritative validation wall.
  assert.equal(schoolFileKind({ name: 'notes.exe', type: 'application/octet-stream' }), 'other')
  assert.equal(isUploadableSchoolFile({ name: 'notes.exe', type: 'application/octet-stream' }), false)
  assert.equal(schoolFileKind({ display_name: 'module.pdf', category: 'slides' }), 'slides')
})

test('School file affordances expose useful accepted formats and stable sizes', () => {
  assert.match(SCHOOL_FILE_ACCEPT, /\.pdf/)
  assert.match(SCHOOL_FILE_ACCEPT, /\.pptx/)
  assert.equal(schoolFileSizeLabel(764), '764 B')
  assert.equal(schoolFileSizeLabel(1024 * 1024 * 2.4), '2.4 MB')
  assert.equal(schoolFileSizeLabel(-1), '-')
})
