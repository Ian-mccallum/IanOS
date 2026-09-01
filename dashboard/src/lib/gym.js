// SPEC-v34: pure gate for BodyPage's daily gym-confirm affordance. Extracted
// out of the JSX ternary chain so the confirm-button gating on
// `gym.is_tracked_day` (e.g. a Saturday shows the button under 7-day
// tracking and hides it under 5-day tracking) has a test that does not need
// a React rendering harness -- this dashboard test suite has none, every
// other component-adjacent test exercises a pure lib function instead.
//
// `is_tracked_day` replaced the old `is_weekday` field name (SPEC-v34 §3);
// this is the one read site for that field, so a stale name elsewhere would
// show up here first.
export function gymConfirmState(gym) {
  if (gym?.confirmed_today) return 'confirmed'
  if (gym?.is_tracked_day) return 'confirm'
  return 'rest'
}
