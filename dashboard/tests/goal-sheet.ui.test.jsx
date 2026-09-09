import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../src/lib/api.js', () => ({ api: vi.fn(() => Promise.resolve({})) }))

import GoalSheet from '../src/components/goals/GoalSheet.jsx'
import { api } from '../src/lib/api.js'

async function renderSheet(propOverrides = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(
      <GoalSheet
        open
        onClose={propOverrides.onClose || vi.fn()}
        pillar={propOverrides.pillar || 'life'}
        toast={propOverrides.toast || vi.fn()}
        onSaved={propOverrides.onSaved || vi.fn()}
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

function setValue(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window[input.tagName === 'TEXTAREA' ? 'HTMLTextAreaElement' : 'HTMLInputElement'].prototype,
    'value',
  ).set
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

afterEach(() => {
  vi.mocked(api).mockReset()
  vi.mocked(api).mockResolvedValue({})
})

it('Draft posts the typed text and pillar to /api/goals/draft', async () => {
  vi.mocked(api).mockResolvedValueOnce({
    name: 'Join AKPSI', shape: 'milestone', target: '', unit: '', per: '',
    deadline: '2026-10-01', metric_key: '', first_steps: [], hero: false,
  })
  const view = await renderSheet()
  const textarea = document.querySelector('.goal-sheet textarea')
  await act(async () => setValue(textarea, 'Join AKPSI by October'))
  const draftBtn = [...document.querySelectorAll('.goal-sheet button')].find((b) => b.textContent === 'Draft')
  await act(async () => draftBtn.click())

  expect(api).toHaveBeenCalledWith('/api/goals/draft', 'POST', { text: 'Join AKPSI by October', pillar: 'life' })
  await view.unmount()
})

it('Save with only the description filled (no Draft) creates a milestone goal named after the typed text', async () => {
  const view = await renderSheet()
  const textarea = document.querySelector('.goal-sheet textarea')
  await act(async () => setValue(textarea, 'Join AKPSI by October'))
  const saveBtn = [...document.querySelectorAll('.goal-sheet button')].find((b) => b.textContent.startsWith('Save goal'))
  await act(async () => saveBtn.click())

  expect(api).toHaveBeenCalledWith('/api/goals', 'POST', expect.objectContaining({
    name: 'Join AKPSI by October',
    kind: 'deadline',
  }))
  await view.unmount()
})
