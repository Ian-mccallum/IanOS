export const METRIC_OPTIONS = {
  btc: [
    { value: 'clients_signed', label: 'Clients signed' },
    { value: 'audit_calls_today', label: 'Audit calls today' },
    { value: 'follow_ups_today', label: 'Follow-ups today' },
    { value: 'demos_last_7d', label: 'Demos, last 7 days' },
    { value: 'burn_this_month', label: 'Burn this month' },
    { value: '', label: 'Manual' },
  ],
  body: [
    { value: 'gym_weekdays_this_week', label: 'Gym weekdays this week' },
    { value: 'workouts_this_week', label: 'Workouts this week' },
    { value: 'sleep_avg_7d', label: 'Sleep avg, last 7 days' },
    { value: 'steps_today', label: 'Steps today' },
    { value: '', label: 'Manual' },
  ],
  money: [
    { value: 'portfolio_value', label: 'Portfolio value' },
    { value: 'checking_balance', label: 'Checking balance' },
    { value: '', label: 'Manual' },
  ],
  life: [
    { value: 'tasks_done_this_week', label: 'Tasks done this week' },
    { value: 'tasks_done_for_goal', label: 'Steps done for this goal' },
    { value: '', label: 'Manual' },
  ],
  partner: [{ value: '', label: 'Manual' }],
  school: [{ value: '', label: 'Manual' }],
}
