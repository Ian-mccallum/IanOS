import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../src/lib/api.js', () => ({ api: vi.fn(() => Promise.resolve({})) }))

import TodayPanel from '../src/components/TodayPanel.jsx'
import { api } from '../src/lib/api.js'

const TODAY = '2026-09-04'

function task(overrides = {}) {
  return { id: 1, title: 'Renew parking permit', due_date: TODAY, priority: 0, ...overrides }
}

async function renderPanel(props = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(
      <TodayPanel
        tasksToday={props.tasksToday || [task()]}
        tasksDoneToday={props.tasksDoneToday || []}
        today={TODAY}
        refresh={props.refresh || vi.fn()}
        toast={props.toast || vi.fn()}
        onFlyPriorityDot={props.onFlyPriorityDot || vi.fn()}
      />,
    )
  })
  return {
    host,
    async unmount() {
      await act(async () => root.unmount())
      host.remove()
    },
  }
}

afterEach(() => {
  vi.mocked(api).mockReset()
  vi.mocked(api).mockResolvedValue({})
})

it('an unstarred task draws a hollow star that says what it will do', async () => {
  const view = await renderPanel()
  const star = view.host.querySelector('.trow-star')
  // Drawn, not a Unicode glyph: hollow means fill="none" on the path.
  expect(star.querySelector('svg.starmark path').getAttribute('fill')).toBe('none')
  expect(star.getAttribute('aria-label')).toBe('Star "Renew parking permit" for Command')
  await view.unmount()
})

it('a starred task draws a filled star and offers to unstar', async () => {
  const view = await renderPanel({ tasksToday: [task({ priority: 1 })] })
  const star = view.host.querySelector('.trow-star')
  expect(star.querySelector('svg.starmark path').getAttribute('fill')).toBe('currentColor')
  expect(star.className).toContain('on')
  expect(star.getAttribute('aria-label')).toBe('Unstar "Renew parking permit"')
  await view.unmount()
})

it('tapping the star promotes the task and names where it went', async () => {
  // The whole point of the control: the tap has to have a legible outcome,
  // because the flying dot is invisible under reduced motion.
  const toast = vi.fn()
  const view = await renderPanel({ toast })
  const star = view.host.querySelector('.trow-star')
  await act(async () => star.click())

  expect(api).toHaveBeenCalledWith('/api/tasks/1', 'PATCH', { priority: 1 }, { queueable: true })
  expect(toast).toHaveBeenCalledWith('starred · now on Command', 'good')
  await view.unmount()
})

it('a task row reveals only Delete, never a dead Edit button', async () => {
  // SwipeRow is shared with goal rows, which do have an editor. A task's
  // text is its whole content, so an "Edit" wired to a no-op shipped a
  // control that did nothing when tapped. Renaming happens in the row now.
  const view = await renderPanel()
  const actions = [...view.host.querySelectorAll('.swipe-actions button')].map((b) => b.textContent.trim())
  expect(actions).toEqual(['Delete'])
  await view.unmount()
})

it('tapping the title edits it in place and saves the new text', async () => {
  // Apple's core to-do interaction: the text is the editor. No modal, no
  // separate edit mode, and the field sits exactly where the text was.
  const view = await renderPanel()
  await act(async () => view.host.querySelector('.trow-title').click())

  const field = view.host.querySelector('.trow-edit')
  expect(field).toBeTruthy()
  expect(field.value).toBe('Renew parking permit')

  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setValue.call(field, 'Renew parking permit at city hall')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => {
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  })

  expect(api).toHaveBeenCalledWith(
    '/api/tasks/1', 'PATCH', { title: 'Renew parking permit at city hall' }, { queueable: true },
  )
  await view.unmount()
})

it('an unchanged or emptied title never fires a write', async () => {
  const view = await renderPanel()
  await act(async () => view.host.querySelector('.trow-title').click())
  const field = view.host.querySelector('.trow-edit')
  await act(async () => field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  expect(api).not.toHaveBeenCalled()
  await view.unmount()
})

it('the composer keeps focus after a save so the next line costs nothing', async () => {
  const view = await renderPanel({ tasksToday: [] })
  const field = view.host.querySelector('.trow-input')
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setValue.call(field, 'Book dentist')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => field.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })))

  expect(api).toHaveBeenCalledWith('/api/tasks', 'POST', { title: 'Book dentist' }, { queueable: true })
  expect(document.activeElement).toBe(field)
  expect(field.value).toBe('')
  await view.unmount()
})
