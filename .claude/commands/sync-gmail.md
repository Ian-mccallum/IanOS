Sync signal from Ian's Gmail into ianOS.

**READ-ONLY PLEDGE, this overrides everything below:** You are syncing data
INTO ianOS. Use the Gmail connector to READ only. Never send, reply, forward,
archive, label, mark, or delete any email, and never touch any other connected
account. If a destructive action ever seems needed, stop and tell Ian instead.

**If the Gmail connector is unavailable or not authorized:** stop and tell Ian:
"Enable Gmail in claude.ai → Settings → Connectors (or via /mcp in an
interactive session), sign in with Google, then run /sync-gmail again." Do not
attempt any workaround.

## What to extract, these four signal types ONLY, ignore everything else

Search the INBOX for the **last 14 days** (skip spam/promotions):

1. **Prospect replies**: senders that look like HVAC/plumbing/home-service
   businesses, or threads mentioning Clockwork, demo, or audit →
   `note` record. Topic: `email: <business name>`. Body: a one-sentence gist
   with the date (e.g. "Owner replied 7/15: wants pricing in writing before
   Friday."). Never paste email bodies.
2. **Legal/registration confirmations**. Illinois Secretary of State, IRS/EIN,
   Twilio A2P/10DLC → a `note`, plus a `fact` (fact_kind "date") whenever the
   email states a concrete date (approval date, filing deadline).
3. **Renewal / price-change notices**: domains, subscriptions, SaaS → a dated
   `fact` (topic like `market:namecheap-renewal` for personal-finance items or
   a plain business slug like `content:canva-renewal`; body includes the amount
   AS TEXT for cfo context). **Never emit a transaction, the loader will
   reject it; bank data comes only from Ian's CSV/SimpleFIN.**
4. **UIUC email**, bursar, registrar, housing, orientation → a dated `fact`
   with a `uiuc:` topic, and/or a `note` for context.

**Privacy rules:** extract nothing from personal or private threads outside
these four types. Gist summaries only, max 500 characters, no forwarded
content, no email addresses or links unless the link/date IS the signal.

## Steps

1. Read + filter per the four types above.
2. Shape records (schema below).
3. Write the JSON to a temp file, run the loader, delete the temp file:
   ```bash
   .venv/bin/python ingest/from_connector.py --source gmail --file /tmp/ianos-sync.json
   rm /tmp/ianos-sync.json
   ```
4. Relay the loader's report verbatim; if facts were loaded, add: "Confirm them
   on the dashboard's Memory page." On a non-zero exit, show the error and stop
  , never retry with loosened or guessed data.

## Payload schema (exact)

```json
{
  "records": [
    {"kind": "note", "topic": "email: Riverbend Plumbing",
     "body": "Owner replied 7/15: wants pricing in writing before Friday."},
    {"kind": "fact", "topic": "uiuc:tuition-due", "body": "Fall tuition due per bursar email 7/14",
     "fact_kind": "date", "date": "YYYY-MM-DD", "recurs": ""}
  ]
}
```

Rules the loader enforces (don't fight them): facts arrive unverified; notes are
pinned to priority 1; identical notes within 7 days dedupe; transactions are
never written from connector data.
