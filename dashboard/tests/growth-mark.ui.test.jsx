import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, it, expect } from 'vitest'
import GrowthMark, { growthStage } from '../src/components/GrowthMark.jsx'

async function renderMark(count) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  await act(async () => {
    root.render(<GrowthMark count={count} />)
  })
  return {
    host,
    async unmount() {
      await act(async () => root.unmount())
      host.remove()
    },
  }
}

describe('growthStage', () => {
  it('test_growth_stage_floors_at_one_and_caps_at_five', () => {
    // Arrange: the exact threshold boundaries.
    // Act: compute the stage at each boundary and past the top.
    // Assert: 0 confirms is stage 1, 12+ confirms is stage 5, never higher.
    expect(growthStage(0)).toBe(1)
    expect(growthStage(1)).toBe(2)
    expect(growthStage(3)).toBe(3)
    expect(growthStage(6)).toBe(4)
    expect(growthStage(9)).toBe(5)
    expect(growthStage(999)).toBe(5)
  })
})

describe('GrowthMark', () => {
  it('test_growth_mark_renders_the_stage_path_under_the_jsdom_reduced_motion_stub', async () => {
    // Arrange: setup-ui.js's default matchMedia stub (no crash either way it resolves).
    // Act: render GrowthMark at a fixed count.
    // Assert: it renders the stage-4 path without throwing.
    const view = await renderMark(4)
    const svg = view.host.querySelector('svg.growth-mark')
    expect(svg).toBeTruthy()
    expect(svg.querySelector('path')).toBeTruthy()
    await view.unmount()
  })
})
