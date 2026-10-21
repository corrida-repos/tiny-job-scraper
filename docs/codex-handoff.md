# Codex development handoff

Development continues in the Codex conversation associated with this checkout.
Repository: `corrida-repos/tiny-job-scraper`.
Source conversation: `6ad60db6-d974-83eb-881d-99895f074a3a` (Tiny's Job Scraper).

On 2026-10-21, all 27 payload files listed in `MANIFEST.json` matched their
exported SHA-256 hashes. The recovered source, tests, configuration and automation
policy are already versioned in main at `b3042412c3cf3c2dfaa1a24981cf113202e54572`.
The existing suite passed all 31 tests in the cloud development environment.
The manifest describes that original export; subsequent development uses Git history.

## Rules and unfinished implementation

Use `docs/current-automation-policy.md` for the intended daily workflow and
`UNFINISHED.md` for differences from the executable baseline. Preserve the exact
60 employers, location preference (Braga, Porto, elsewhere in Portugal, Nordic
countries, rest of the EU), no minimum salary requirement, exclusion of mandatory
experience above five years, verified original publication within 48 hours,
and at most seven calendar days abroad per quarter. Preserve the remaining
language, location, noncoding and travel constraints in the policy.

These requirements are not all implemented by the recovered CLI. Development
must close those gaps before treating the standalone CLI as the production
replacement. Do not interpret baseline defaults as changes to the user's rules.

## Scheduled task migration: pending

No scheduler was transferred, created, disabled or enabled during this handoff.
This Codex session has no tool for administering the existing ChatGPT scheduled
task or attaching it to this conversation. Moving development context does not
move the automation or its runtime data.

When scheduler administration is available:

1. Inspect the existing task and preserve its current instructions and daily
   08:00 Europe/Lisbon schedule, including daylight-saving behavior.
2. Connect the target runtime to this repository and preserve the actual durable
   SQLite state and audit history. They are excluded from the source export;
   never substitute the onboarding smoke database or a new empty database.
3. Verify access to employer/ATS endpoints, durable storage and the authorized
   Gmail recipient through secure configuration. Do not commit private IDs,
   recipient details, credentials or runtime data.
4. Implement or provide the documented policy overrides, comprehensive per-run
   report, delivery reconciliation and persistence before switching execution.
5. Validate the replacement runtime and delivery path, then switch the schedule
   with only one active daily task. Record the first observed scheduled outcome.

The cloud environment's dependency installation and unit tests were verified.
The representative live source check was blocked by the network proxy; required
domains and reusable install/start instructions were saved in the environment
configuration draft. Saving that draft does not apply or publish it, and does
not validate a future scheduled run.

## Implementation progress — 2026-10-21

Current code now implements the 48-hour, salary and experience screening updates
and complete per-run email draft generation. See the current update at the top
of `UNFINISHED.md` and `schedule/codex-task.md`. A fresh focused network check
passed; the full audit completed 55/60 configured source scopes with five recorded
gaps. Scheduler transfer, production-state access and Gmail delivery remain
unverified and unchanged.

## Migration bundle received and verified

The supplied active-task export, SQLite state and audit report match their
manifest SHA-256 hashes and their copies in the migration ZIP. The manifest has
a literal escaped newline after the JSON object; the original is preserved and
that known trailing export defect was explicitly accounted for during parsing.

The imported database passed integrity checking: 3 runs, 156 jobs, 0 legacy
deliveries and 1 comprehensive run audit. The current application's state
initialization was tested on a disposable copy and preserved every table and
row, including the comprehensive audit. All 42 unit tests passed.

The verified state is restored locally at `data/state.sqlite3`; the original
bundle, task export, audit, validation summary and a disabled replacement task
specification are retained under ignored `data/migration-import/`. Private
bindings, recipient information and runtime history are intentionally excluded
from Git. The replacement specification is a preparation artifact, not a task
created or imported through a scheduler API.

The exported task records an enabled daily 08:00 Europe/Lisbon schedule. Its
current policy sections agree with the repository documentation. No task was
changed or email sent by this session. Scheduler control, Gmail access and
guarded synchronization to the existing durable Library files remain unavailable.
The restored database is an import snapshot, not a live synchronized production
database. Refresh it from the active task's latest durable state before cutover
if that task has run again. A cloud filesystem snapshot alone does not establish
ongoing durable synchronization or successful scheduled execution.

## GitHub Actions replacement prepared

The gated Actions workflow and encrypted-state/Gmail runner are implemented; see
`schedule/github-actions.md`. The `runtime-state` branch holds an encrypted copy
of the verified imported snapshot. The key and recipient are absent from tracked
source files. All 49 tests passed locally and in GitHub's Checks workflow.

An end-to-end local runner validation restored that encrypted snapshot, checked
all 60 sources (55 complete, five coverage gaps), generated an encrypted report,
and left the production branch and original database unchanged. Its temporary
copy advanced from 156 jobs/3 runs to 165 jobs/4 runs; no email was sent.

GitHub API connectivity now works. Integration authorization still rejects
Actions secrets/variables endpoints, including the secret-encryption public key.
Required repository secrets therefore remain to be entered securely through
repository settings, or through an integration with those specific permissions.
Remote Daily PM jobs validation, actual Gmail submission and scheduled cutover
remain pending. Keep `DAILY_ENABLED` unset until manual validation and observed
delivery succeed and the original ChatGPT schedule is paused.

## Successful manual Actions delivery — 2026-10-21

After the Gmail credential was updated, Actions run `39585902373` completed.
Gmail SMTP accepted the real daily report; the encrypted runtime-state branch
contains its receipt and updated database, which passed integrity checking.
The database now has 165 jobs, 4 runs and 2 comprehensive audits. The source audit
reported 54 complete scopes and six gaps: COCUS and Namecheap access blocks,
Float/Fujitsu/Infineon robots restrictions, and JTA's limited vacancy feed.

All 51 tests passed. Inbox arrival requires recipient confirmation. The Actions
schedule remains gated by `DAILY_ENABLED`; this session has not changed the
existing ChatGPT schedule. Confirm receipt and pause the original schedule
before enabling the replacement. Do not refresh the new production database
from the older imported snapshot, which would discard this run and receipt.
