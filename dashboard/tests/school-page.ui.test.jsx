import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../src/lib/api.js', () => ({ api: vi.fn() }))
vi.mock('../src/components/goals/PillarGoalPanel.jsx', () => ({ default: () => null }))

import SchoolPage from '../src/pages/SchoolPage.jsx'
import { api } from '../src/lib/api.js'

const course = {
  code: 'ANTH 210',
  name: 'Forensic Science',
  meetings: [],
  policies: {},
  grade_categories: [],
}

function schoolState(moveCount = 6) {
  return {
    goals: [],
    school: {
      today: '2026-08-30',
      courses: [course],
      upcoming: Array.from({ length: moveCount }, (_, index) => ({
        id: index + 1,
        title: `Move ${index + 1}`,
        course_code: course.code,
        kind: 'assignment',
        due_at: `2026-09-${String(index + 1).padStart(2, '0')}T17:00:00`,
      })),
      just_done: [],
      summary: { upcoming_count: moveCount, done_count: 0 },
      sync: { connected: true, item_count: moveCount },
    },
  }
}

function setViewport(width = 375, height = 667) {
  window.matchMedia.mockImplementation((query) => {
    const matches = [...query.matchAll(/min-(width|height):\s*(\d+)px/g)]
      .every(([, axis, minimum]) => (axis === 'width' ? width : height) >= Number(minimum))
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }
  })
}

async function renderSchool(moveCount = 6, viewport) {
  setViewport(viewport?.width, viewport?.height)
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const refresh = vi.fn()
  const toast = vi.fn()
  await act(async () => {
    root.render(
      <SchoolPage
        state={schoolState(moveCount)}
        refresh={refresh}
        toast={toast}
        onOpenSchoolNote={vi.fn()}
      />,
    )
  })
  return {
    host,
    refresh,
    toast,
    async unmount() {
      await act(async () => root.unmount())
      host.remove()
    },
  }
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await Promise.resolve()
  })
}

afterEach(() => {
  document.body.replaceChildren()
  api.mockReset()
  vi.clearAllMocks()
})

it('leaves page identity to the global header', async () => {
  const view = await renderSchool()

  expect(view.host.querySelector('.school-command-head h1')).toBeNull()
  expect(view.host.querySelector('.school-command-head p')).toBeNull()
  expect(view.host.querySelector('.school-command-utility[aria-label="School tools"]')).not.toBeNull()
  const workbench = view.host.querySelector('.school-workbench')
  expect(workbench.getAttribute('aria-live')).toBeNull()
  expect(workbench.querySelector('[role="status"]')).not.toBeNull()

  await view.unmount()
})

it('renders three priority moves and reveals the remaining moves accessibly', async () => {
  const view = await renderSchool(7)
  const nextSection = view.host.querySelector('.school-next')
  const toggle = nextSection.querySelector('.school-next-toggle')

  expect(nextSection.querySelectorAll(':scope > .school-next-list .school-deadline')).toHaveLength(3)
  expect(nextSection.querySelectorAll('#school-next-remaining .school-deadline')).toHaveLength(0)
  expect(toggle.textContent).toBe('Show 4 more')
  expect(toggle.getAttribute('aria-expanded')).toBe('false')
  expect(toggle.getAttribute('aria-controls')).toBe('school-next-remaining')

  await click(toggle)

  expect(toggle.textContent).toBe('Show fewer')
  expect(toggle.getAttribute('aria-expanded')).toBe('true')
  expect(nextSection.querySelectorAll('#school-next-remaining .school-deadline')).toHaveLength(4)

  await view.unmount()
})

it('omits the disclosure when there are three or fewer moves', async () => {
  const view = await renderSchool(3)

  expect(view.host.querySelectorAll('.school-next > .school-next-list .school-deadline')).toHaveLength(3)
  expect(view.host.querySelector('.school-next-toggle')).toBeNull()

  await view.unmount()
})

it('keeps the course rail reachable at the true 320px minimum', async () => {
  const view = await renderSchool(19, { width: 320, height: 667 })
  const nextSection = view.host.querySelector('.school-next')

  expect(nextSection.querySelectorAll(':scope > .school-next-list .school-deadline')).toHaveLength(2)
  expect(nextSection.querySelector('.school-next-toggle').textContent).toBe('Show 17 more')

  await view.unmount()
})

it('uses six useful moves on a roomy desktop rather than reserving a blank pane', async () => {
  const view = await renderSchool(7, { width: 1440, height: 900 })
  const nextSection = view.host.querySelector('.school-next')

  expect(nextSection.querySelectorAll(':scope > .school-next-list .school-deadline')).toHaveLength(6)
  expect(nextSection.querySelector('.school-next-toggle').textContent).toBe('Show 1 more')

  await view.unmount()
})

it('crosses off visible and revealed work through the exact reversible API path', async () => {
  api.mockResolvedValue({})
  const view = await renderSchool(4)
  const nextSection = view.host.querySelector('.school-next')

  await click(nextSection.querySelector('.school-next-list .school-deadline-check'))
  expect(api).toHaveBeenLastCalledWith('/api/school/items/1/done', 'POST', { done: true })
  expect(view.refresh).toHaveBeenCalledTimes(1)

  const undo = view.toast.mock.calls.at(-1)[2]
  await act(async () => { await undo() })
  expect(api).toHaveBeenLastCalledWith('/api/school/items/1/done', 'POST', { done: false })

  await click(nextSection.querySelector('.school-next-toggle'))
  await click(nextSection.querySelector('#school-next-remaining .school-deadline-check'))
  expect(api).toHaveBeenLastCalledWith('/api/school/items/4/done', 'POST', { done: true })

  await view.unmount()
})
