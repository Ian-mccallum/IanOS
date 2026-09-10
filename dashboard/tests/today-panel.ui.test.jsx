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

it('a finished task can be sent back to Today', async () => {
  // The one write in this product with no way back: the ring in the Done
  // disclosure was an inert <span>, so a mis-tap on a 52px row was final,
  // even though the endpoint has taken {undo: true} since SPEC-v41 shipped.
  const view = await renderPanel({
    tasksToday: [],
    tasksDoneToday: [task({ id: 7, title: 'Mail the form' })],
  })
  const ring = view.host.querySelector('.today-done-reveal .trow-check')
  expect(ring.tagName).toBe('BUTTON')
  expect(ring.getAttribute('aria-label')).toBe('Move "Mail the form" back to Today')

  await act(async () => ring.click())
  expect(api).toHaveBeenCalledWith('/api/tasks/7/done', 'POST', { undo: true }, { queueable: true })
  await view.unmount()
})

it('the done list opens itself once nothing is left open', async () => {
  // Finishing the list left the panel looking empty while the day's actual
  // work sat collapsed behind a disclosure.
  const done = [task({ id: 7, title: 'Mail the form' })]

  const cleared = await renderPanel({ tasksToday: [], tasksDoneToday: done })
  expect(cleared.host.querySelector('.today-done-reveal').open).toBe(true)
  await cleared.unmount()

  const working = await renderPanel({ tasksDoneToday: done })
  expect(working.host.querySelector('.today-done-reveal').open).toBe(false)
  await working.unmount()
})

it('a rejected completion does not leave the row claiming it is done', async () => {
  // `completing` is local state, so it outlives the 15s poll: a failed write
  // used to leave the row struck through, greyed and ring-filled forever,
  // with no toast to say the write never landed.
  const toast = vi.fn()
  vi.mocked(api).mockRejectedValue(new Error('offline. Your Mac is not reachable'))
  const view = await renderPanel({ toast })

  await act(async () => view.host.querySelector('.trow-check').click())
  expect(view.host.querySelector('.trow').className).toContain('completing')

  await act(async () => { await new Promise((r) => setTimeout(r, 400)) })
  expect(view.host.querySelector('.trow').className).not.toContain('completing')
  expect(toast).toHaveBeenCalledWith('offline. Your Mac is not reachable', 'crit')
  await view.unmount()
})

it('clearing the last open task says so in the composer', async () => {
  // SPEC-v41 §4.6's fourth delight item, specified and never built.
  const view = await renderPanel()
  expect(view.host.querySelector('.trow-input').placeholder).toBe('New task')

  await act(async () => view.host.querySelector('.trow-check').click())
  await act(async () => { await new Promise((r) => setTimeout(r, 400)) })
  expect(view.host.querySelector('.trow-input').placeholder).toBe('Done for today')
  await view.unmount()
})

it('a committed rename paints before the write comes back', async () => {
  // The row rendered task.title, which does not change until /api/state has
  // been refetched, so pressing Enter flashed the OLD text back at Ian.
  let settle
  vi.mocked(api).mockReturnValue(new Promise((r) => { settle = r }))
  const view = await renderPanel()

  await act(async () => view.host.querySelector('.trow-title').click())
  const field = view.host.querySelector('.trow-edit')
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => {
    setValue.call(field, 'Renew permit at city hall')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => {
    field.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
  })

  expect(view.host.querySelector('.trow-title').textContent).toBe('Renew permit at city hall')
  await act(async () => { settle({}) })
  await view.unmount()
})
