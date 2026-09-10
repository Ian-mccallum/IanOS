import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, it, expect, vi } from 'vitest'
import LearningPage from '../src/pages/LearningPage.jsx'

function baseState(overrides = {}) {
  return {
    learning: { topics: [], today: null, streak: { streak: 0, stools: 2 } },
    pending_proposals: [],
    ...overrides,
  }
}

async function renderPage(propOverrides = {}) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(
      <LearningPage
        state={propOverrides.state || baseState()}
        refresh={propOverrides.refresh || vi.fn()}
        toast={propOverrides.toast || vi.fn()}
        requestConsult={propOverrides.requestConsult || vi.fn()}
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

function textOf(el) {
  return (el.textContent || '').trim()
}

describe('LearningPage', () => {
  it('test_zero_topics_shows_only_the_composer', async () => {
    // Arrange: state with no topics and no today session.
    // Act: render the page.
    // Assert: the add-a-topic field is present and no other copy renders.
    const view = await renderPage()
    const field = view.host.querySelector('textarea[placeholder="Add a topic"]')
    expect(field).toBeTruthy()
    expect(view.host.textContent).not.toMatch(/no active topic/i)
    await view.unmount()
  })

  it('test_today_row_opens_consult_with_seed_text', async () => {
    // Arrange: state with an open, threadless today session carrying a task prompt.
    // Act: click the practice row.
    // Assert: requestConsult is called with the tutor role and the task prompt as seed text.
    const requestConsult = vi.fn()
    const state = baseState({
      learning: {
        topics: [],
        today: { task_prompt: 'walk one case', thread_id: null, status: 'open' },
        streak: { streak: 1, stools: 2 },
      },
    })
    const view = await renderPage({ state, requestConsult })
    const row = view.host.querySelector('.today-row--practice')
    await act(async () => row.click())
    expect(requestConsult).toHaveBeenCalledWith({ role: 'tutor', seedText: 'walk one case' })
    await view.unmount()
  })

  it('test_clarifying_topic_renders_unfinished_card_not_a_growth_topic', async () => {
    // Arrange: one mid-onboarding topic (status='clarifying' server-side,
    // surfaced under the separate `clarifying` key) and zero active topics.
    // Act: render the page, then click the unfinished-setup card.
    // Assert: it renders as its own distinct, dimmer card (not a TopicCard/
    // GrowthMark), and tapping it reopens the tutor thread with an empty
    // seedText -- the same thread-reuse behavior as an active topic, never
    // a forced or overwritten message.
    const requestConsult = vi.fn()
    const state = baseState({
      learning: {
        topics: [],
        clarifying: [{ id: 1, name: 'Ai', created_at: '2026-09-09 19:04:52' }],
        today: null,
        streak: { streak: 0, stools: 2 },
      },
    })
    const view = await renderPage({ state, requestConsult })
    expect(view.host.textContent).toMatch(/Setting up: Ai/i)
    expect(view.host.textContent).toMatch(/Unfinished setup/i)
    expect(view.host.querySelector('.growth-mark')).toBeFalsy()
    const card = view.host.querySelector('.learning-topic-card--clarifying')
    expect(card).toBeTruthy()
    expect(card.className).not.toMatch(/\btoday-row\b/)
    await act(async () => card.click())
    expect(requestConsult).toHaveBeenCalledWith({ role: 'tutor', seedText: '' })
    await view.unmount()
  })

  it('test_suggested_topic_card_prefills_composer', async () => {
    // Arrange: one pending tutor-authored task proposal.
    // Act: click Start this topic.
    // Assert: the composer field's value becomes the proposal's action text.
    const state = baseState({
      pending_proposals: [{ id: 1, role: 'tutor', status: 'PENDING', kind: 'task', action: 'Start learning: negotiation' }],
    })
    const view = await renderPage({ state })
    const startBtn = [...view.host.querySelectorAll('button')].find((b) => textOf(b) === 'Start this topic')
    expect(startBtn).toBeTruthy()
    await act(async () => startBtn.click())
    const field = view.host.querySelector('textarea[placeholder="Add a topic"]')
    expect(field.value).toBe('Start learning: negotiation')
    await view.unmount()
  })
})
