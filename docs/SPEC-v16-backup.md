# SPEC v16: the backup (restic + B2)

## Why this exists

`data/ianos.db` is 2.1 MB and it is Ian's entire life OS: 1,958 leads with real
call history, every journal entry, every memo, every goal. Until this spec it
existed in exactly one place on Earth. Time Machine: no destination. iCloud
Desktop sync: off (verified, and good, it would have uploaded the journal in
plaintext). Git: the DB is ignored, correctly. A stolen bag ended the product.

The Framework laptop makes this urgent: migrations are when files die, and the
new machine is Linux, so whatever we build must not be Mac-shaped.

## The two demands, and how both are met

Ian's words: "although i want my data safe, i want it to be accessible."

- **Safe** = client-side encryption. restic encrypts on the laptop before
  upload; Backblaze stores noise it cannot read. Nobody but the password holder
  can read a word of the journal, including Backblaze, including a subpoena to
  Backblaze.
- **Accessible** = any machine + restic + the password = full restore in
  minutes. Versioned, so "last Tuesday" is restorable, not just "latest".

## Laws (each carries its reasoning; tests assert what can be asserted)

1. **The DB is snapshotted with `VACUUM INTO`, never file-copied.** The DB runs
   in WAL mode; a raw copy taken mid-write is silently corrupt, the worst
   possible backup because it looks like one. `VACUUM INTO` takes a
   transactionally consistent snapshot through the WAL while the API keeps
   writing. `-wal`/`-shm` files are never backed up. (sqlite3 >= 3.27 required;
   macOS ships 3.43, any current Linux qualifies.)
2. **Restore never writes into the live tree.** `make restore` materializes
   into a fresh timestamped folder and prints the copy commands; the human
   makes the final move. The one moment you run a restore is the one moment
   the live tree might hold the only surviving copy of something newer.
3. **If git holds it, git backs it up.** The private GitHub repo is the backup
   for code, specs and role files. restic carries only non-git state:
   the staged DB snapshot, `data/journal/`, `data/documents/`, `leads/*.csv`
   (scraper output, gitignored), and `.env`. Logs and `infra_status.json` are
   regenerable noise and stay out.
4. **No silent failure.** A failed scheduled backup writes a `system` memo
   (priority 2), the same channel a crashed agent uses, so it surfaces on the
   dashboard Ian already reads. A backup system that fails quietly is worse
   than none, it retires the fear that would otherwise drive a manual copy.
5. **The repo is ianOS's alone.** One dedicated B2 bucket (or drive folder).
   Retention (`forget --prune`) applies repo-wide, which is only safe when
   nothing else lives there.
6. **Password custody is the accepted single point of failure.** By design,
   losing `RESTIC_PASSWORD` means the backups are permanently unreadable.
   It lives in `.env` (gitignored, and inside every backup, which is harmless:
   reading it requires already having it) AND in Ian's password manager AND on
   paper at home. `docs/BACKUP.md` says this loudly.
7. **Nothing Mac-shaped in the engine.** bash + restic + sqlite3, all three
   identical on Linux. Only the alarm clock is per-OS: launchd plist here,
   a documented systemd timer for the Framework. The engine must run headless:
   launchd jobs get a bare PATH, so the script resolves the restic binary
   itself (the `phone.sh`/tailscale precedent).
8. **Unconfigured is a refusal, not an error.** No `RESTIC_REPOSITORY` in
   `.env` → exit 2 with instructions (the `/api/plan/sync` 501 precedent), and
   `make schedule-backup` refuses to install the schedule at all, so an
   unconfigured machine can never generate a nightly failure memo.

## Configuration (`.env`)

```bash
RESTIC_REPOSITORY=b2:<bucket>:ianos     # or a path: /Volumes/Backup/ianos-restic
RESTIC_PASSWORD=<long, in the password manager AND on paper>
B2_ACCOUNT_ID=<keyID>                   # B2 only
B2_ACCOUNT_KEY=<applicationKey>         # B2 only
```

Real environment variables win over `.env` (tests and one-off overrides rely
on this). A local-path repository is fully supported: same engine, same
restore, useful for an external drive or a scratch drill.

## Retention and integrity

- Nightly: `backup` → `forget --prune --keep-daily 7 --keep-weekly 5
  --keep-monthly 12` → `restic check` (metadata; the corpus is ~12 MB, the
  check is cheap).
- `make backup-verify` is the deep proof: `check --read-data` (every byte
  re-read and re-hashed) plus a test-restore of the DB to a temp dir,
  `PRAGMA integrity_check`, and row counts printed for eyeballing.
- The restore drill in `docs/BACKUP.md` is to be run once at setup. An
  unrehearsed restore is a rumor, not a backup.

## Scheduling

`ops/com.ianos.backup.plist`, daily **21:45**, 15 minutes after the nightly
agent run starts; `VACUUM INTO` is happy alongside a writing runner. launchd
fires a missed interval once on wake, so a 21:45 spent asleep runs when the
lid opens. Logs append to `data/backup.log`. On the Framework the same script
goes under a systemd user timer with `Persistent=true` (example in BACKUP.md).

## Surfaces

```
make backup           # snapshot + prune + check, ~seconds
make backup-status    # configured? last success? recent snapshots
make backup-verify    # read all data + test-restore the DB + integrity_check
make restore          # latest (or SNAPSHOT=<id>) into a NEW folder, never in place
make schedule-backup  # install the 21:45 launchd job (refuses if unconfigured)
```

`scripts/backup.sh` holds run/status/verify as subcommands; `scripts/restore.sh`
is separate because its safety posture is different (law 2).

## Failure modes

| Failure | Behavior |
|---|---|
| Not configured | exit 2 + instructions; scheduling refused (law 8) |
| B2 unreachable / Mac offline | nonzero exit, memo, log; next night self-heals, snapshots are independent |
| Stale restic lock (killed run) | next run fails visibly → memo; `restic unlock` documented in BACKUP.md |
| Wrong password | restic refuses; nothing written; memo on scheduled runs |
| Repo corruption | nightly `check` catches it within a day; restore from the last good snapshot |

## Tests (`tests/test_backup.py`)

Skipped wholesale when restic is not installed. Against a throwaway local repo
and a fake `IANOS_ROOT`:

- unconfigured → exit 2 (law 8)
- two runs → two snapshots; staging cleaned both times
- **WAL consistency**: a row committed on a held-open WAL connection (nothing
  checkpointed) survives backup → restore byte-for-byte (law 1)
- journal media and `.env` restore byte-identical
- wrong password → nonzero exit AND a `system` memo lands in the fake root's
  DB (law 4)

## Out of scope, deliberately

- Backup staleness as a `stale_data_domains` entry on the dashboard: nice
  later; the failure memo covers the acute case.
- A second mirror repository: restic can't fan out in one run; revisit if the
  journal grows into real gigabytes.
- Backing up the OS or applications: this spec protects ianOS state, nothing
  else.
