# Prepared daily-task handoff

Status: prepared instructions only; the existing ChatGPT task has not moved.
Schedule: every day at **08:00 Europe/Lisbon**, including daylight-saving changes.
Do not enable a second daily task while the original is still active.

An existing ChatGPT task cannot be reassociated with a Codex conversation using
the tools available in this session. A replacement needs a supported scheduler,
an execution environment, durable storage and authorized Gmail access. A Codex
chat alone does not supply those capabilities.

## Replacement run instructions

Use `corrida-repos/tiny-job-scraper` as the code source. Record the exact Git commit
used for each run. Read `docs/current-automation-policy.md` and `UNFINISHED.md`.
Use Python 3.11+ and install `requirements.txt` into `.venv`.

Restore the existing production SQLite state from its durable storage to
`data/state.sqlite3`. Verify its provenance; do not use an onboarding database,
an empty database or a database copied from an unrelated task. Keep a recoverable
backup before the first migrated run. Restore it safely when no other run holds
the database; use SQLite backup support for a live database.

From the repository root, run:

```bash
.venv/bin/python run.py run --require-existing-state \
  --state data/state.sqlite3 --output output/daily
```

Capture the actual exit code: 0 means all configured source scopes completed;
2 means incomplete source coverage with usable reports; 1 means an operational
failure. Do not turn exit 2 into an empty successful search. If dependencies or
Python cannot start, the orchestrator must construct an operational-failure email
itself, because the program cannot generate an artifact without running.

Use only fresh `email.json` and `email.md` from this attempt. They include all
current-run eligible and fresh review roles, not just unreported jobs. Never use
the legacy capped `digest.json` as the daily email. Verify `started_at` in
`results.json` belongs to the current attempt; an old artifact is not a report.
The JSON marks delivery `not_sent`: generating a draft never confirms sending.

Preserve updated SQLite state with a version guard and save the detailed report,
`results.json`, `source-health.json` and `email.json` to durable storage. Do not
replace the good durable state with an empty or invalid file on failure. Update
the email's Saving note truthfully after the actual save; state explicitly if it
failed. Preserve all candidate and alternative-URL evidence in the audit files.

Send exactly one email per attempted run through the authorized Gmail connection
to the existing task's recipient, using subject `Tiny's Daily Job Report` and the
prepared Markdown rendered appropriately for Gmail. Send no-match and failure
reports too. Before sending or retrying, search Sent for the exact `run_marker`
and reconcile uncertain sends. A confirmed existing matching message means do not
send again. Save the successful Gmail message ID and run marker in the durable
audit. If sending fails or its outcome is uncertain, report that explicitly;
never mark delivery successful without evidence. The legacy `ack` ledger does
not reconcile these comprehensive per-run emails.

Honor robots rules and access barriers. Use only the configured 56 employers;
never fall back to broad web search. Do not apply to jobs or contact employers.

## Switch checklist

1. Obtain the existing task's full instructions and durable-state/audit bindings
   through its authorized task interface. Preserve private settings securely.
2. Validate restoration, full-source retrieval, guarded durable saving, Gmail
   access and send reconciliation in the replacement runtime.
3. Move or replace the schedule through supported task controls. Keep only one
   active daily schedule and retain 08:00 Europe/Lisbon.
4. Observe the first scheduled run and confirmed report delivery before declaring
   migration complete.

Cloud validation on 2026-10-21: 60 scopes attempted, 55 complete, five needing
attention (JTA, Float, Infineon, OLX, Fujitsu). These are source-coverage findings,
not evidence of migrated scheduling, durable production storage or Gmail access.
