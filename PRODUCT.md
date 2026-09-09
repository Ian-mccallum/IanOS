# Product

## Register

product

## Users

One user: Ian, solo founder of Clockwork, checking in from his desk at
night (after sales calls) and in the morning (before them). Dark room, laptop,
usually under two minutes per visit. The job: read the brief, decide pending
proposals, log activity, see if he's on pace, get out.

## Product Purpose

ianOS is a personal agent headquarters. Four AI agents (scout, cfo, watchdog,
chief) run nightly, watch his goals (client #1 by Aug 15, burn under $150/mo,
sales quotas, the LLC→EIN→A2P chain), and file memos and proposals. The
dashboard is mission control: today's brief, approve/reject on proposals,
goals vs actuals, and the agents' memo feed. Success = Ian acts on the brief
every day and no deadline or slippage ever passes unnoticed.

## Brand Personality

Mission control, blunt, alive. A spaceship command deck: the interface should
feel like instrumentation, not decoration. Every glow means something
(status, urgency), numbers are the heroes, and the voice never flatters.
Futuristic but legible; drama comes from real countdown clocks, not ornament.

## Voice (anti-slop)

Ian reads this under time pressure. Copy is instrumentation, not prose.

- **No em dashes.** Use commas, colons, semicolons, periods, or parentheses.
  Missing values render as ASCII `-`, never `—`.
- **No marketing fluff.** Ban seamless / empower / leverage / unlock /
  world-class / cutting-edge / game-changer and kin.
- **No aphoristic stacks.** Do not default to "solemn clause. Punchy denial."
  as the page rhythm. Say the fact once.
- **Blunt over lyrical.** "Gym confirmed. 12 day streak" beats a metaphor.
- **No taglines (SPEC-v41).** A page title stands alone; a second line exists
  only to carry data (a count, a date) or an instruction with a verb, never
  a description of the surface it sits on ("Your day at a glance", "One
  workspace for the week"). `tests/test_mobile_ui.py::test_no_taglines` is
  the executable form of this rule.

## Anti-references

- Generic SaaS admin panels (white cards, gray sidebars, pill badges everywhere).
- Sci-fi cosplay that costs legibility: unreadable techno fonts for data,
  decorative glitch effects, low-contrast neon-on-black body text.
- Dashboard-template energy: identical stat-card grids, gradient hero metrics.

## Design Principles

1. **Numbers are the interface.** The dollar figure, the T-minus count, the
   calls-vs-quota gap: biggest, brightest, first. Chrome serves data.
2. **Urgency is earned, not styled.** Red pulses only when a deadline or cap
   is actually breached; a calm board means a calm business.
3. **Two-minute sessions.** Every daily action (read brief, decide proposal,
   log calls) reachable without navigation, scroll, or mode-switching.
4. **The agents are characters.** Role color and voice stay consistent across
   memos, proposals, and the brief so Ian always knows who's talking.
5. **Instrumentation, not decoration.** Motion and glow communicate state
   change (new memo, decision recorded, meter moving) or they don't exist.
6. **Privacy curtain before chrome.** On phone (and every device), the PWA
   lock screen (SPEC-v12) blanks the UI until Face ID or password. It does
   not replace the LAN token.

## Accessibility & Inclusion

Single known user, but hold the floor: body text ≥4.5:1 contrast, status never
color-alone (always paired with a text label), full keyboard operability for
forms and dialogs, `prefers-reduced-motion` honored everywhere.
