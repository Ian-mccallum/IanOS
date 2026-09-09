# Anti-slop copy (2026-08-06, taglines added 2026-09-02)

Binding voice rule for ianOS UI, docs, and agent-facing prose. Origin: PRODUCT.md
"Voice (anti-slop)" + osUI Copy section. The dash rules below are enforced in
review only; the no-taglines rule (SPEC-v41) is also a runtime gate,
`tests/test_mobile_ui.py::test_no_taglines`.

## No taglines (SPEC-v41, 2026-09-02)

Ian: "Get rid of all cliché text." A page title stands alone. A second line
survives only when it carries data (a count, a date, a next time) or an
instruction with a verb ("Tap any hour to add a block"); otherwise delete
it, don't shrink it. Banned constructions: "one place for", "one workspace",
"at a glance", "your X, one Y at a time", "workspace" as a noun for a page,
any motto/whisper pool (an array literal named `*_WHISPERS`/`*_MOTTOS`/
`*_TAGLINES`), any sentence that would read the same on a template. A
page's name is its own description. 18 static subtitles and Partner's
rotating whispers were the worst offenders; see
`docs/SPEC-v41-arc-taglines-life.md` §3 for the full deletion list.

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
