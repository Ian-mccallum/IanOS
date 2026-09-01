Sync Ian's Google Calendar into ianOS.

**READ-ONLY PLEDGE, this overrides everything below:** You are syncing data
INTO ianOS. Use the Google Calendar connector to READ only. Never create,
modify, move, or delete any calendar event, and never touch any other connected
account. If a destructive action ever seems needed, stop and tell Ian instead.

**If the Google Calendar connector is unavailable or not authorized:** stop and
tell Ian: "Enable Google Calendar in claude.ai → Settings → Connectors (or via
/mcp in an interactive session), sign in with Google, then run /sync-calendar
again." Do not attempt any workaround.

## Steps

1. Read Ian's primary Google Calendar: events from **7 days ago through 21 days
   from now**.
2. Shape every event as a `calendar_event` record (schema below). Leave
   `category` blank: the loader auto-categorizes, unless you are confident an
   event is work (Clockwork/demo/audit/client) or health (gym/MMA/soccer/run),
   in which case pass `"work"` or `"health"`.
3. If an event is clearly a birthday or anniversary (recurring, personal), ALSO
   emit a `fact` record for it with a `family:` or `partner:` topic namespace : 
   it will land unverified for Ian to confirm on the Memory page.
4. Do NOT emit `note` records from calendar data, except one per event that was
   cancelled in the window (topic "calendar: cancelled: <summary>").
5. Write the JSON to a temp file, run the loader, delete the temp file:
   ```bash
   .venv/bin/python ingest/from_connector.py --source calendar --file /tmp/ianos-sync.json
   rm /tmp/ianos-sync.json
   ```
6. Relay the loader's report verbatim. If it mentions facts needing
   confirmation, add: "Confirm them on the dashboard's Memory page." If the
   loader exits non-zero, show its error output and stop, never retry with
   loosened or guessed data.

## Payload schema (exact)

```json
{
  "records": [
    {"kind": "calendar_event", "date": "YYYY-MM-DD", "start_time": "HH:MM or null",
     "end_time": "HH:MM or null", "summary": "text", "category": ""},
    {"kind": "fact", "topic": "family:mom-birthday", "body": "one-line fact",
     "fact_kind": "date", "date": "YYYY-MM-DD", "recurs": "yearly"}
  ]
}
```

Rules the loader enforces (don't fight them): facts arrive unverified; notes are
priority 1; re-running the same sync changes nothing; transactions are never
written from connector data.
