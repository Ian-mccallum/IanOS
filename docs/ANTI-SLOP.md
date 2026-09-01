# Anti-slop copy (2026-08-06)

Binding voice rule for ianOS UI, docs, and agent-facing prose. Origin: PRODUCT.md
"Voice (anti-slop)" + osUI Copy section. Enforced in review; not a runtime gate.

## What changed

1. **Removed every Unicode em dash (`—`) and en dash used as punctuation (`–`)**
   from the active tree (dashboard, api, core, docs, agents, tests, README,
   CLAUDE, IAN-SETUP, PRODUCT, etc.). Skipped `.claude/worktrees/` archives.
2. **Empty / missing values** in the UI that used `'—'` now use ASCII `'-'`.
3. **User-facing strings** re-punctuated by hand where the bulk pass left awkward
   commas or leading periods (toasts, Journal privacy line, The Line exit,
   offline banners, Partner / Money / School empty hints).
4. **Documented the rule** in `PRODUCT.md` (Voice) and `.claude/skills/osui/SKILL.md`
   (Copy) so future agents do not reintroduce slop.

## Rules (short)

| Ban | Use instead |
|---|---|
| Em dash `—` as punctuation | `,` `:` `;` `.` or `(...)` |
| En dash `–` as punctuation | `-` or rephrase |
| Empty sentinel `—` | `-` |
| Marketing buzzwords | Concrete noun + verb |
| Aphoristic cadence stacks | One clear sentence |

## Examples (after)

- `Day closed. Add more if you like.`
- `Only you. The team sees only that you closed the day.`
- `gym saved. Syncs when your Mac wakes`
- `Leave the line (Esc)`
- `offline. Your Mac is not reachable`

## Scope note

Historical git history still contains em dashes. New commits must not. If you
paste from an old SPEC, strip dashes before saving.
