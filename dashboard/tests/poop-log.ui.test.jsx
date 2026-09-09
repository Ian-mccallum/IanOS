import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

// jsdom's first environment build in a cold parallel run has been measured at
// over 20s on this machine, which blows vitest's 5s default before the first
// assertion runs. Nothing here waits on a timer; the assertions are about DOM
// structure, so a generous ceiling costs nothing and stops a green suite from
// failing on load alone.
vi.setConfig({ testTimeout: 30000 })

vi.mock('../src/lib/api.js', () => ({ api: vi.fn(() => Promise.resolve({})) }))

const reducedMotion = { value: false }
vi.mock('motion/react', async () => {
  const actual = await vi.importActual('motion/react')
  return { ...actual, useReducedMotion: () => reducedMotion.value }
})

import PoopLog from '../src/components/PoopLog.jsx'
import { api } from '../src/lib/api.js'

const DAY = '2026-09-09'

function serverState(overrides = {}) {
  return {
    day: DAY,
    today_count: 2,
    entries: [
      { id: 1, day: DAY, logged_at: `${DAY} 07:12:00`, bristol: 4, note: '' },
      { id: 2, day: DAY, logged_at: `${DAY} 13:41:00`, bristol: null, note: '' },
    ],
    rail: [
      { day: '2026-09-03', count: 1 }, { day: '2026-09-04', count: 3 },
      { day: '2026-09-05', count: 2 }, { day: '2026-09-06', count: 0 },
      { day: '2026-09-07', count: 2 }, { day: '2026-09-08', count: 1 },
      { day: DAY, count: 2 },
    ],
    per_day_avg: 1.6,
    window_days: 7,
    last_logged_at: `${DAY} 13:41:00`,
    ...overrides,
  }
}

async function renderPanel(props = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(<PoopLog toast={props.toast || vi.fn()} />)
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
  reducedMotion.value = false
  vi.mocked(api).mockReset()
  vi.mocked(api).mockResolvedValue({})
})

it('reads the day off its own no-store route, never the polled state', async () => {
  vi.mocked(api).mockResolvedValue(serverState())
  const panel = await renderPanel()

  const [path, method, body, opts] = vi.mocked(api).mock.calls[0]
  expect(path).toMatch(/^\/api\/poop\/today/)
  expect(method).toBe('GET')
  expect(body).toBeUndefined()
  expect(opts).toEqual({ cache: 'no-store' })
  expect(panel.host.querySelector('.poop-count').textContent).toBe('2')
  await panel.unmount()
})

it('a tap logs once, queueably, and moves the count on the same frame', async () => {
  vi.mocked(api).mockResolvedValue(serverState())
  const toast = vi.fn()
  const panel = await renderPanel({ toast })

  vi.mocked(api).mockResolvedValue({
    entry: { id: 3, day: DAY, logged_at: `${DAY} 15:02:00`, bristol: null, note: '' },
    state: serverState({ today_count: 3 }),
  })
  await act(async () => { panel.host.querySelector('.poop-log-btn').click() })

  const [path, method, , opts] = vi.mocked(api).mock.calls[1]
  expect(path).toBe('/api/poop')
  expect(method).toBe('POST')
  // The phone must be able to log with the Mac asleep, day-stamped at the tap.
  expect(opts.queueable).toBe(true)
  expect(panel.host.querySelector('.poop-count').textContent).toBe('3')
  // The tap is undoable from the toast itself, not only from the row.
  expect(typeof toast.mock.calls.at(-1)[2]).toBe('function')
  await panel.unmount()
})

it('an offline tap still counts before the server has a row for it', async () => {
  vi.mocked(api).mockResolvedValue(serverState())
  const panel = await renderPanel()

  vi.mocked(api).mockResolvedValue({ queued: true, mutation_id: 'x' })
  await act(async () => { panel.host.querySelector('.poop-log-btn').click() })

  expect(panel.host.querySelector('.poop-count').textContent).toBe('3')
  expect(panel.host.textContent).toContain('saved on this phone')
  await panel.unmount()
})

it('reduced motion swaps the thrown burst for a held one', async () => {
  reducedMotion.value = true
  vi.mocked(api).mockResolvedValue(serverState())
  const panel = await renderPanel()

  vi.mocked(api).mockResolvedValue({ entry: { id: 3 }, state: serverState({ today_count: 3 }) })
  await act(async () => { panel.host.querySelector('.poop-log-btn').click() })

  expect(panel.host.querySelector('.poop-coil')).toBeNull()
  expect(panel.host.querySelector('.poop-burst-quiet')).not.toBeNull()
  await panel.unmount()
})

it('nothing on this surface can read as a verdict on Ian', async () => {
  vi.mocked(api).mockResolvedValue(serverState({ today_count: 0, entries: [], per_day_avg: 0 }))
  const panel = await renderPanel()

  const text = panel.host.textContent.toLowerCase()
  for (const banned of ['goal', 'target', 'streak', 'behind', 'should', '%']) {
    expect(text).not.toContain(banned)
  }
  // "missed" is allowed in exactly one place, and it is about a log Ian forgot
  // to write, never about a day he failed at.
  expect(text.match(/missed/g)).toHaveLength(1)
  expect(panel.host.querySelector('.poop-missed-btn').textContent).toBe('Add one you missed')
  expect(panel.host.querySelector('[class*="crit"]')).toBeNull()
  await panel.unmount()
})
