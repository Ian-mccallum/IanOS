# Backups

Every night at 21:45 your Mac encrypts a snapshot of everything that matters
(database, journal, documents, lead CSVs, `.env`) and uploads it to Backblaze.
Backblaze stores noise it cannot read; only your password can unscramble it.
Reasoning and laws: [SPEC-v16](SPEC-v16-backup.md).

**The one sacred thing: the password.** Lose it and every backup is
permanently unreadable, by design. It goes in your password manager AND on
paper at home, the day you create it, before anything else.

---

## Setup (once, ~5 minutes)

1. **Create the bucket.** [backblaze.com](https://www.backblaze.com/sign-up/cloud-storage)
   → free account (card required, $0 at ianOS's ~11 MB) → **Buckets → Create a
   Bucket**: name like `ianos-backup-<random>`, private, encryption off
   (restic brings its own). Then **Application Keys → Add a New Application
   Key**, scoped to that one bucket. Note the `keyID` and `applicationKey`.
2. **Pick the password.** Long and random, from your password manager's
   generator. Store it there AND on paper now.
3. **Configure.** Add to `ianOS/.env`:

   ```bash
   RESTIC_REPOSITORY=b2:<bucket-name>:ianos
   RESTIC_PASSWORD=<the password>
   B2_ACCOUNT_ID=<keyID>
   B2_ACCOUNT_KEY=<applicationKey>
   ```

4. **First backup + proof:**

   ```bash
   make backup          # creates the repo, uploads everything
   make backup-verify   # re-reads every byte, test-restores the DB
   ```

5. **The restore drill.** Run `make restore` once, today. It restores into a
   fresh folder in your home directory and touches nothing live; look at the
   folder, then delete it. An unrehearsed restore is a rumor, not a backup.
6. **Schedule it:** `make schedule-backup` (nightly 21:45; a night spent
   asleep runs when the lid next opens).

## Day to day

Nothing. `make backup-status` if you're curious. If a scheduled backup fails
you'll see a memo from `system` on the dashboard; `data/backup.log` has the
detail. One failed night is not an emergency, snapshots are independent and
the next one self-heals.

An external drive works as a repository too, same engine:
`RESTIC_REPOSITORY=/Volumes/Backup/ianos-restic` (no B2 keys needed).

## The disaster runbook (lost / dead / stolen laptop)

On any machine:

```bash
brew install restic        # Mac        (Framework: sudo apt install restic)
git clone https://github.com/Ian-mccallum/ianOS-private && cd ianOS-private
export RESTIC_REPOSITORY='b2:<bucket-name>:ianos'
export RESTIC_PASSWORD='<from your password manager / the paper>'
export B2_ACCOUNT_ID='<keyID>'          # any valid key for the bucket works,
export B2_ACCOUNT_KEY='<applicationKey>'  # make a new one if the old is lost
bash scripts/restore.sh
```

It restores into `~/ianos-restore-<timestamp>`, integrity-checks the DB, and
prints the exact copy commands to adopt it. Then `make setup` and you're back.
You lose at most the day since the last snapshot. An older point in time:
`restic snapshots`, then `SNAPSHOT=<id> bash scripts/restore.sh`.

## Moving to the Framework (Linux)

The engine is bash + restic + sqlite3 and runs unchanged; only the 21:45 alarm
clock is per-OS. Instead of `make schedule-backup`, create
`~/.config/systemd/user/ianos-backup.service`:

```ini
[Unit]
Description=ianOS nightly backup

[Service]
Type=oneshot
WorkingDirectory=%h/ianOS
ExecStart=/bin/bash %h/ianOS/scripts/backup.sh
```

and `~/.config/systemd/user/ianos-backup.timer`:

```ini
[Unit]
Description=ianOS nightly backup at 21:45

[Timer]
OnCalendar=*-*-* 21:45
Persistent=true

[Install]
WantedBy=timers.target
```

Then `systemctl --user enable --now ianos-backup.timer`. `Persistent=true` is
the launchd missed-while-asleep behavior.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Not configured" / exit 2 | Add the four `RESTIC_*`/`B2_*` lines to `.env` (Setup step 3). |
| Memo: "Nightly backup FAILED" | `tail data/backup.log`, then `make backup` to retry by hand. |
| "repository is already locked" | A run was killed mid-flight: `restic unlock`, then `make backup`. |
| "wrong password or no key found" | The `.env` password does not match the repo. Fetch the real one from the manager/paper. Never re-init over a repo you still need. |
| `make backup-verify` reports errors | Restore now from the last good snapshot (`restic snapshots`, pick one, restore drill), then rebuild the repo fresh. |
| Changed laptops | Disaster runbook above, then re-schedule on the new machine. |
