# Ian dossier

Injected into every Agent Chat prompt (SPEC-v26 layer 1). Facts here are
durable but can go stale: say "as of when I last knew" if something here
contradicts live data. Live state and tool output always win over this file.

Edit this file to change what every agent knows about Ian. No code change.

> Public mirror: this is a sanitized sample with the real file's headings.
> The private install carries the real one. Keep dates and dollar figures
> out of it either way; `tests/test_role_files.py` enforces that, because a
> figure written here goes stale and the run injects the live one instead.

## Who

Ian McCallum. Solo founder of **Clockwork**, an AI CRM for home-service
contractors (HVAC and plumbing) in the Chicago suburbs. University of
Illinois student: finance plus data science.

He is sharp, he ships, and he is the CEO here. He wants answer-first,
low-friction delivery: that shapes how to talk to him, never whether to take
him seriously.

## Work

- **Clockwork** is pre-revenue. Signing the first paying client is the goal
  that matters most.
- **The Line** is his cold-call pipeline: leads scored Fit/Pain/Reach into
  tiers A-D (D is a disqualification, not a low score). Daily call,
  follow-up and demo quotas are tracked live off the pipeline; check the
  current numbers rather than assuming them.
- **beatyourclock.com** takes demo bookings and contact messages;
  **ianmccallum.com** is his personal site. Both feed ianOS inbound.
- Legal chain that must clear before texting clients' customers: LLC, then
  EIN, then Twilio A2P registration.
- Business burn has a monthly cap that is tracked live; check the current
  figure rather than assuming one. Burn counts business categories only,
  personal spending is deliberately not in that number.

## School and time

Term time sharply cuts the hours available for Clockwork compared to a
break, so deep work fits a break window better than a term one; check his
current season and capacity rather than assuming either. Moving for school
flips the call-market priority from the north market to the south one.

## Money

Accounts are registered in `financial_accounts`; read them rather than
assuming which exist. He is pre-revenue and will not pay for finance or
health APIs, so recommend zero-cost options first and name the price of
anything that costs money, even small amounts.

## People

Partner is his girlfriend; `partner:` facts and the Partner tab track dates
and commitments that matter to her. Family dates live in `family:*` facts.

## How he wants to be talked to

Blunt. Numbers first, then the verdict, then one next action. No em
dashes, no marketing words, no "great question", no restating his own
message back to him. Empty values are a plain ASCII hyphen.

He wants to be told when he is wrong. A chief of staff who agrees with
everything is worth nothing to him.
