import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../src/lib/api.js', () => ({ api: vi.fn() }))

import MemoryPage from '../src/pages/MemoryPage.jsx'

const facts = [
  {
    id: 1,
    domain: 'personal',
    topic: 'passport renewal',
    body: 'Bring the passport photo and the renewal form.',
    kind: 'date',
    verified: false,
    days_until: 4,
  },
  {
    id: 2,
    domain: 'personal',
    topic: 'favorite coffee',
    body: 'Cold brew from the cafe near campus.',
    kind: 'preference',
    verified: true,
  },
]

async function renderMemory() {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(<MemoryPage facts={facts} toast={vi.fn()} onChange={vi.fn()} />)
  })
  return {
    host,
    async unmount() {
      await act(async () => root.unmount())
      host.remove()
    },
  }
}

async function type(element, value) {
  await act(async () => {
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    valueSetter.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function click(element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

afterEach(() => {
  document.body.replaceChildren()
  vi.clearAllMocks()
})

it('searches confirmed and unconfirmed memory as one result set', async () => {
  const view = await renderMemory()
  const search = view.host.querySelector('[aria-label="Search memory"]')

  await type(search, 'passport')
  expect(view.host.textContent).toContain('passport renewal')
  expect(view.host.textContent).not.toContain('favorite coffee')
  expect(view.host.textContent).not.toContain('Nothing matches')

  await type(search, 'not in memory')
  expect(view.host.textContent).toContain('Nothing matches "not in memory".')
  expect(view.host.querySelector('.fact-card')).toBeNull()
  expect(view.host.querySelector('.fact-row')).toBeNull()

  await view.unmount()
})

it('keeps a stable disclosure trigger and named record section while a fact expands', async () => {
  const view = await renderMemory()
  const trigger = view.host.querySelector('.fact-row')

  expect(view.host.querySelector('section[aria-labelledby="memory-confirm-heading"]')).not.toBeNull()
  expect(view.host.querySelector('section[aria-labelledby="memory-domain-personal"]')).not.toBeNull()
  trigger.focus()
  await click(trigger)

  expect(trigger.isConnected).toBe(true)
  expect(document.activeElement).toBe(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  expect(view.host.querySelector('#fact-detail-2')).not.toBeNull()

  await click(trigger)
  expect(trigger.isConnected).toBe(true)
  expect(document.activeElement).toBe(trigger)
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(view.host.querySelector('#fact-detail-2')).toBeNull()

  await view.unmount()
})
