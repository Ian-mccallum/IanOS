import React from 'react'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const { apiMock } = vi.hoisted(() => ({ apiMock: vi.fn() }))

vi.mock('../src/lib/api.js', () => ({ api: apiMock }))

vi.mock('../src/components/Sheet.jsx', () => ({
  default: ({ open, title, onClose, children }) => (open ? (
    <section aria-label={title}>
      <button type="button" onClick={onClose}>Close</button>
      {children}
    </section>
  ) : null),
}))

vi.mock('../src/components/school-notes/SchoolFilesPanel.jsx', () => ({ default: () => null }))
vi.mock('../src/components/school-notes/SchoolStudyPanel.jsx', () => ({ default: () => null }))
vi.mock('../src/components/school-notes/SchoolNoteEditor.jsx', () => ({
  default: ({ onChange }) => (
    <div data-testid="school-note-editor">
      <button type="button" onClick={() => onChange(noteDocument('First edit'))}>Type first edit</button>
      <button type="button" onClick={() => onChange(noteDocument('Second edit'))}>Type second edit</button>
    </div>
  ),
}))

import SchoolNotebookPage from '../src/pages/SchoolNotebookPage.jsx'
import { SCHOOL_NOTEBOOK_INTENT_KEY } from '../src/lib/school-notebook.js'

function noteDocument(text) {
  return {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
  }
}

function session(document = noteDocument('Starting point'), revision = 1) {
  return {
    id: 7,
    course_code: 'ECON 110',
    session_type: 'meeting',
    session_date: '2026-08-24',
    title: 'Supply and demand',
    revision,
    document,
    plain_text: document.content?.[0]?.content?.[0]?.text || '',
    preview: document.content?.[0]?.content?.[0]?.text || '',
    meeting: {
      kind: 'Lecture',
      start_at: '2026-08-24T10:00:00',
      end_at: '2026-08-24T10:50:00',
      location: 'Hall 2',
    },
  }
}

const state = {
  school: {
    today: '2026-08-24',
    next_meetings: [],
    courses: [{
      code: 'ECON 110',
      name: 'Introduction to Economics',
      meetings: [{ days: ['MO'], kind: 'Lecture' }],
      next_meeting: {
        school_item_id: 99,
        kind: 'Lecture',
        start_at: '2026-08-24T10:00:00',
      },
    }],
  },
}

function apiFor(openSession, onPatch = null) {
  apiMock.mockImplementation((path, method = 'GET', body) => {
    if (path === '/api/school/courses/ECON%20110/note-sessions' && method === 'GET') {
      return Promise.resolve({ sessions: [openSession] })
    }
    if (path === '/api/school/note-sessions/7' && method === 'GET') return Promise.resolve(openSession)
    if (path === '/api/school/note-sessions/7' && method === 'PATCH') return onPatch?.(body)
    throw new Error(`Unexpected request: ${method} ${path}`)
  })
}

async function renderNotebook(openSession, onPatch = null) {
  apiFor(openSession, onPatch)
  window.sessionStorage.setItem(SCHOOL_NOTEBOOK_INTENT_KEY, JSON.stringify({ sessionId: 7 }))
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(<SchoolNotebookPage state={state} toast={vi.fn()} onBack={vi.fn()} />)
  })
  await vi.waitFor(() => expect(host.querySelector('[aria-label="Class note title"]')).not.toBeNull())
  return {
    host,
    async unmount() {
      await act(async () => root.unmount())
    },
  }
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

async function pressEscape() {
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  })
}

function hasClasses(element, ...names) {
  return names.every((name) => element.classList.contains(name))
}

beforeEach(() => {
  apiMock.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

it('full screen sets page and body state, then Escape cleans both', async () => {
  const view = await renderNotebook(session())
  const toggle = view.host.querySelector('.school-fullscreen-toggle')

  await click(toggle)
  expect(toggle.getAttribute('aria-pressed')).toBe('true')
  expect(hasClasses(view.host.querySelector('.school-notebook-page'), 'is-full-screen')).toBe(true)
  expect(hasClasses(document.body, 'school-note-editing', 'school-note-fullscreen')).toBe(true)

  await pressEscape()
  expect(toggle.getAttribute('aria-pressed')).toBe('false')
  expect(hasClasses(view.host.querySelector('.school-notebook-page'), 'is-full-screen')).toBe(false)
  expect(hasClasses(document.body, 'school-note-editing')).toBe(true)
  expect(hasClasses(document.body, 'school-note-fullscreen')).toBe(false)

  await view.unmount()
})

it('unmounting while full screen removes every note body class', async () => {
  const view = await renderNotebook(session())

  await click(view.host.querySelector('.school-fullscreen-toggle'))
  expect(hasClasses(document.body, 'school-note-editing', 'school-note-fullscreen')).toBe(true)

  await view.unmount()
  expect(hasClasses(document.body, 'school-note-editing', 'school-note-fullscreen')).toBe(false)
})

it('an edit made during an in-flight save is flushed before mobile back closes the note', async () => {
  vi.useFakeTimers()
  const first = noteDocument('First edit')
  const second = noteDocument('Second edit')
  const requests = []
  let resolveFirst
  const firstSave = new Promise((resolve) => { resolveFirst = resolve })
  const view = await renderNotebook(session(), (body) => {
    requests.push(body)
    if (requests.length === 1) return firstSave
    return Promise.resolve(session(second, 3))
  })

  await click([...view.host.querySelectorAll('button')].find((button) => button.textContent === 'Type first edit'))
  await act(async () => { await vi.advanceTimersByTimeAsync(650) })
  expect(requests).toEqual([{
    expected_revision: 1,
    document: first,
  }])

  await click([...view.host.querySelectorAll('button')].find((button) => button.textContent === 'Type second edit'))
  await click(view.host.querySelector('.school-note-mobile-back'))
  expect(view.host.querySelector('[aria-label="Class note title"]')).not.toBeNull()

  await act(async () => {
    resolveFirst(session(first, 2))
    await Promise.resolve()
  })
  await vi.waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[1]).toEqual({
    expected_revision: 2,
    document: second,
  })

  await vi.waitFor(() => expect(view.host.querySelector('[aria-label="Class note title"]')).toBeNull())
  await view.unmount()
})

it('renders a bounded multi-line title editor for long class-note titles', async () => {
  const view = await renderNotebook(session())
  const title = view.host.querySelector('[aria-label="Class note title"]')

  expect(title.tagName).toBe('TEXTAREA')
  expect(title.getAttribute('rows')).toBe('1')
  expect(title.getAttribute('enterkeyhint')).toBe('done')
  expect(title.getAttribute('aria-describedby')).toBe('school-note-title-hint')
  expect(view.host.querySelector('#school-note-title-hint')).not.toBeNull()

  await view.unmount()
})
