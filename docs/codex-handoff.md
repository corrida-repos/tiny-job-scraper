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
