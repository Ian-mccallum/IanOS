# About this public mirror

ianOS runs one person's real life, so the repo it lives in is private. This
repository is a scrubbed mirror of it, published to show the architecture and
the way it was built. It carries none of the private repo's history: it
began as one snapshot commit and each refresh adds one more.

## What is different from the private repo

- **History.** None of the private repo's. That history contains things a
  public one must not (a server log with private network addresses, a real
  class schedule). Rewriting history is error-prone, so the mirror starts
  from a clean snapshot and each refresh adds one commit.
- **Data.** No database, no leads, no journal, no `.env`. The mirror is built
  from one private commit, so anything uncommitted, untracked or gitignored
  in the private repo cannot be exported by construction. `make setup` seeds
  demo data.
- **The dossier.** `agents/dossier.md` is the file every chat prompt reads
  about the user. The mirror ships a sample with the same headings.
- **The school inventory.** `data/fall_2026_school_seed.json` keeps the real
  schema but placeholder courses, staff, sections, rooms and meeting times.
- **Names.** A partner's name is replaced with the word "partner" everywhere,
  including table and file names, so that pillar still works. A handful of
  example businesses and owner names quoted in specs and tests are replaced
  with fictional ones. Health, age and a few home-area details are removed.
- **Credentials.** None were ever committed. The lock-screen password hash in
  `dashboard/src/lib/lock.js` is the hash of the documented mirror default
  (`ianos`), not the private one.
- **Images.** Re-encoded to drop editor metadata (author, organisation).
- **The operator checklist** (`IAN-SETUP.md`) is omitted. The README it
  pointed at is now `docs/MANUAL.md`, and the README here is new.

## How the mirror is produced

A private script enumerates one private commit, applies an ordered
substitution table, re-encodes images, then scans the output against a deny list and
refuses to finish if anything slipped through. A substitution rule that fires
zero times is reported, so a typo in the table cannot silently stop
redacting. The script and its table live only in the private repo: the map
of what was redacted is exactly what the mirror must not carry.

## What this means for a reader

- Tests pass on the mirror as published; the counts in the README come from
  a run on this exact snapshot.
- Specs are historical records. They reference dates, quotas and figures that
  were true when written; the runtime injects live values instead.
- If you spot something that should not be here, open an issue.
