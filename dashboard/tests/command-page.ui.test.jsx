import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../src/lib/api.js', () => ({ api: vi.fn(() => Promise.resolve({})) }))

import CommandPage, { visibleActs } from '../src/pages/CommandPage.jsx'
import { api } from '../src/lib/api.js'

// --- visibleActs: the pure filter behind the Receipts strip (SPEC-v37 §4.5) ---

it('drops acts that already carry an undone_at', () => {
  const acts = [
    { id: 1, undone_at: null },
    { id: 2, undone_at: '2026-08-31 10:00:00' },
    { id: 3 },
  ]
  expect(visibleActs(acts).map((a) => a.id)).toEqual([1, 3])
})

it('treats a missing or null recent_acts as no acts, never a crash', () => {
  expect(visibleActs(undefined)).toEqual([])
  expect(visibleActs(null)).toEqual([])
  expect(visibleActs([])).toEqual([])
})

// --- CommandPage: the strip itself ---

const baseState = {
  today: '2026-08-31',
  brief: null,
  attention: { next: null, items: [] },
  pillars: {},
  roster: [{ role: 'watchdog', codename: 'Dumbledore' }],
  recent_acts: [],
}

async function renderCommand(stateOverrides = {}, propOverrides = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const state = { ...baseState, ...stateOverrides }
  await act(async () => {
    root.render(
      <CommandPage
        state={state}
        briefIsToday
        navigate={vi.fn()}
        toast={propOverrides.toast || vi.fn()}
        refresh={propOverrides.refresh || vi.fn()}
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

it('renders no receipts strip at all when there are no recent acts (osui L3)', async () => {
  const view = await renderCommand({ recent_acts: [] })
  expect(view.host.querySelector('.receipts-strip')).toBeNull()
  await view.unmount()
})

it('renders no receipts strip when recent_acts is absent from state entirely', async () => {
  const view = await renderCommand({ recent_acts: undefined })
  expect(view.host.querySelector('.receipts-strip')).toBeNull()
  await view.unmount()
})

it('shows one row per live act with its codename and the summary verbatim, and drops already-undone acts', async () => {
  const view = await renderCommand({
    recent_acts: [
      {
        id: 42, role: 'watchdog', act: 'goal.archive', target_kind: 'goal', target_id: '5',
        summary: 'watchdog archived "Audit calls per day", 22d past deadline.',
        created_at: '2026-08-31 21:34:02', undone_at: null,
      },
      {
        id: 41, role: 'cfo', act: 'transaction.recategorize', target_kind: 'transaction', target_id: '9',
        summary: 'cfo recategorized a $12.40 charge as Software.',
        created_at: '2026-08-31 20:00:00', undone_at: '2026-08-31 20:05:00',
      },
    ],
  })

  const rows = view.host.querySelectorAll('.receipt-row')
  expect(rows.length).toBe(1)
  expect(view.host.textContent).toContain('Dumbledore')
  expect(view.host.textContent).toContain('watchdog archived "Audit calls per day", 22d past deadline.')
  expect(view.host.textContent).not.toContain('cfo recategorized')

  await view.unmount()
})

it('falls back to the raw role id when the roster has no codename for it', async () => {
  const view = await renderCommand({
    roster: [],
    recent_acts: [{ id: 7, role: 'scout', summary: 'scout logged a call.', undone_at: null }],
  })
  expect(view.host.querySelector('.receipt-agent').textContent).toBe('scout')
  await view.unmount()
})

it('undoing a receipt calls the endpoint, removes the row locally, and refreshes state', async () => {
  const refresh = vi.fn()
  vi.mocked(api).mockImplementation((path) => (
    path === '/api/acts/42/undo'
      ? Promise.resolve({ id: 42, undone_at: '2026-08-31 21:40:00' })
      : Promise.resolve({})
  ))
  const view = await renderCommand({
    recent_acts: [{
      id: 42, role: 'watchdog',
      summary: 'watchdog archived "Audit calls per day", 22d past deadline.',
      undone_at: null,
    }],
  }, { refresh })

  const undoBtn = view.host.querySelector('.receipt-undo')
  expect(undoBtn).not.toBeNull()
  await act(async () => { undoBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

  expect(api).toHaveBeenCalledWith('/api/acts/42/undo', 'POST', {})
  expect(view.host.querySelector('.receipts-strip')).toBeNull()
  expect(refresh).toHaveBeenCalled()

  await view.unmount()
})

it('leaves the row in place and surfaces the error on a failed undo, the same toast path other mutations use', async () => {
  const toast = vi.fn()
  vi.mocked(api).mockImplementation((path) => (
    path === '/api/acts/42/undo'
      ? Promise.reject(new Error('already undone'))
      : Promise.resolve({})
  ))
  const view = await renderCommand({
    recent_acts: [{
      id: 42, role: 'watchdog',
      summary: 'watchdog archived "Audit calls per day", 22d past deadline.',
      undone_at: null,
    }],
  }, { toast })

  const undoBtn = view.host.querySelector('.receipt-undo')
  await act(async () => { undoBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

  expect(view.host.querySelector('.receipt-row')).not.toBeNull()
  expect(toast).toHaveBeenCalledWith('already undone', 'crit')

  await view.unmount()
})
