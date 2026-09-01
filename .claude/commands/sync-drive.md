Register pending contracts from Ian's Google Drive into ianOS.

**READ-ONLY PLEDGE, this overrides everything below:** You are syncing data
INTO ianOS. Use the Google Drive connector to READ only (list/search). Never
create, modify, move, share, or delete any Drive file, and never touch any
other connected account. If a destructive action ever seems needed, stop and
tell Ian instead.

**If the Google Drive connector is unavailable or not authorized:** stop and
tell Ian: "Enable Google Drive in claude.ai → Settings → Connectors (or via
/mcp in an interactive session), sign in with Google, then run /sync-drive
again." Do not attempt any workaround.

## Steps

1. Search Drive folders whose names match **Clockwork**, **Contracts**, or
   **Legal**. If none exist, tell Ian: "No Clockwork/Contracts/Legal folder
   found: tell me which folder holds your contracts and I'll note it in this
   command for next time," then stop.
2. For each PDF/doc that looks like a contract, agreement, or terms document
   (by filename/type) → a `document` record. `path` = the Drive URL. **Do not
   open, download, or quote file contents**, this sync only registers that a
   document exists and is pending; Harvey Specter (counsel) reviews what Ian
   provides later.
3. Write the JSON to a temp file, run the loader, delete the temp file:
   ```bash
   .venv/bin/python ingest/from_connector.py --source drive --file /tmp/ianos-sync.json
   rm /tmp/ianos-sync.json
   ```
4. Relay the loader's report verbatim. If documents were loaded, add: "Pending
   documents wake Harvey Specter (counsel) on tonight's run, check `make plan`."
   On a non-zero exit, show the error and stop.

## Payload schema (exact)

```json
{
  "records": [
    {"kind": "document", "name": "Riverbend service agreement",
     "path": "https://drive.google.com/file/d/…",
     "doc_kind": "contract", "notes": "found in Clockwork/Contracts, modified 7/15"}
  ]
}
```

Rules the loader enforces (don't fight them): documents dedupe on (name, path);
re-running the same sync changes nothing.
