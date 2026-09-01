// SPEC-v32 Part D: pure helpers for the live Order / Day Command surface,
// extracted out of CommandPage.jsx so the dim-on-stale rule and the
// refresh-trigger guard are unit-testable without rendering React.

/** Mirrors CommandPage's `commandStale`: dim the nightly sentence once the
 * live compiler's top pick no longer matches what the brief anchored on.
 * The $0 fallback from SPEC-v32 D3 -- no model call, just a visual demotion. */
export function isCommandStale({ command, primaryKey, anchorKey }) {
  return !!(command && primaryKey && anchorKey && primaryKey !== anchorKey)
}

/** The sessionStorage key that fires POST /api/order/refresh at most once
 * per unique (brief date, anchor_key, next.key) triple per browser session. */
export function orderRefreshGuardKey({ briefDate, anchorKey, nextKey }) {
  return `order-refresh-attempted:${briefDate}:${anchorKey}:${nextKey}`
}

/** Whether the client should even attempt firing the refresh: today's brief
 * exists, carries an anchor, and the live order disagrees with it. The
 * server-side cooldown/cap (SPEC-v32 D2) are the real guardrails; this only
 * decides whether to ask at all. */
export function shouldAttemptOrderRefresh({ nextKey, brief, today }) {
  if (!nextKey || !brief || brief.governs_date !== today) return false
  const anchorKey = brief.anchor_key
  if (!anchorKey || nextKey === anchorKey) return false
  return true
}

/**
 * Attempts the live-order refresh exactly once per unique
 * (brief.date, anchor_key, next.key) triple per browser session (a
 * chatty-tab guard; the server cooldown/cap are the real limits).
 * Returns true only when this call actually fired `requestRefresh`.
 */
export function maybeTriggerOrderRefresh({ nextKey, brief, today, storage, requestRefresh }) {
  if (!shouldAttemptOrderRefresh({ nextKey, brief, today })) return false
  const guardKey = orderRefreshGuardKey({ briefDate: brief.date, anchorKey: brief.anchor_key, nextKey })
  try {
    if (storage.getItem(guardKey) === '1') return false
    storage.setItem(guardKey, '1')
  } catch {
    return false
  }
  requestRefresh()
  return true
}
