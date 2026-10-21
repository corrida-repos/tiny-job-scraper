# GitHub Actions daily runner

The workflow is `.github/workflows/daily-jobs.yml`. Daily delivery was enabled
after the recipient confirmed the test email and paused the original ChatGPT
task. No repository variable is required. To pause it, open Actions → Daily PM
jobs → Disable workflow; re-enable it there when ready.
GitHub schedules may start late; this is an 08:00 Lisbon target, not an exact-time
service guarantee. Two UTC triggers are filtered against the date's Lisbon UTC
offset so only the appropriate trigger runs, including daylight-saving changes.

## Prepared state

`runtime-state` contains only `state.enc`: an AES-256-GCM encrypted ZIP holding
SQLite state, the report, recipient and delivery metadata. It does not contain
plaintext recipient addresses, databases or task settings. Encryption happens
before any Git staging. Git history retains previous encrypted checkpoints;
repository storage grows over time. Keep the encryption key securely backed up:
losing it prevents restoration of these checkpoints. This does not synchronize
back to the original task's Library files.

The initial snapshot comes from the verified migration export (3 runs, 156 jobs,
0 legacy deliveries, 1 comprehensive audit). If the ChatGPT task has run again,
refresh from a new export before cutover. Do not use onboarding databases.

## Required repository settings

Open Settings → Secrets and variables → Actions and add repository secrets:

| Secret | Value |
| --- | --- |
| `STATE_ENCRYPTION_KEY` | Contents of the locally generated key file, supplied separately and never committed |
| `GMAIL_ADDRESS` | Gmail account used to send the existing reports |
| `GMAIL_APP_PASSWORD` | A Google app password for that account, used for TLS-protected SMTP and IMAP |

The recipient is retained inside the encrypted migration snapshot. Do not guess
or replace it with the sender. Enable IMAP access for the account if its settings
or organization policy require it. App passwords require Google 2-Step
Verification and may be unavailable under an organization policy; if unavailable,
stop here and use an OAuth delivery implementation instead of a normal password.

The workflow needs repository contents write permission for the encrypted state
branch. It uses the per-run `GITHUB_TOKEN`; no personal token is needed in Actions.
Allow the workflow's explicit `contents: write` permission in repository Actions
settings. A branch rule on `runtime-state` must permit these normal workflow
commits; no force-push permission is needed.

## Validate, then switch

1. Add `STATE_ENCRYPTION_KEY`. In Actions → Daily PM jobs → Run workflow, leave
   `send_email` unchecked. The run restores a temporary copy, runs the real
   scraper and uploads an encrypted validation artifact. It never sends email
   or updates the production branch. Exit 2 from the scraper is recorded as
   incomplete coverage rather than an empty successful search.
2. Add Gmail secrets. Run the workflow manually with `send_email` checked. This
   is a real report email, not a dummy test message. It persists state and records
   SMTP acceptance. Confirm arrival in your mailbox. Expected source gaps remain
   visible in the report.
3. Pause the old ChatGPT schedule through its task controls, then enable this
   workflow. This cutover is complete: the old task was paused and the workflow
   schedule enabled. Do not restore the old imported database over the newer
   Actions state, which already contains the validated run and receipt.
4. Observe the first scheduled run and its email before declaring migration done.

Tests and setup failures before the runner starts are visible as failed GitHub
Actions runs; they cannot promise an email. A missing key, corrupt snapshot or
unavailable Gmail connection also prevents delivery. GitHub does not guarantee a
scheduled workflow will start at all during an outage. Configure GitHub workflow
failure notifications as the independent operational channel.

## Persistence and retry behaviour

The workflow concurrency group permits only one runner at a time. Every state
checkpoint uses a normal, non-forced Git push; another writer causes a conflict
rather than overwriting newer state. It saves retrieved state/audit, then send
intent, then SMTP receipt. A stable Message-ID based on `GITHUB_RUN_ID` is searched
in Gmail's Sent folder before every production attempt. Rerunning a successful
run does not send again. If a saved intent has no matching Sent message, the
runner refuses automatic resend until the uncertain outcome is reconciled.
New deliveries are blocked while an older delivery is unresolved.

SMTP acceptance is a positive submission acknowledgement, not proof of inbox
arrival. The audit stores its Message-ID; Sent-folder reconciliation also records
IMAP UIDs. Network failures between SMTP submission and checkpointing cannot
provide an absolute exactly-once guarantee. Do not start a new run to bypass an
uncertain send; inspect Sent and the encrypted ledger first. If state saving
fails, the runner attempts one failure email with that same Message-ID and fails
the workflow; inspect the mailbox and state branch before retrying.

## Refreshing the bootstrap

Use a separate checkout of the existing `runtime-state` branch, with no local
changes, and the newest unmodified migration export directory. Install
`requirements-actions.txt` and run from the source checkout:

```bash
.venv/bin/python scripts/bootstrap_actions.py \
  --bundle-dir data/migration-import \
  --state-checkout /path/to/runtime-state-checkout \
  --key-file data/migration-import/STATE_ENCRYPTION_KEY.txt \
  --refresh
```

The script checks manifest hashes and SQLite integrity, keeps the original key,
and refuses to refresh over an unresolved send. It preserves Git history and
uses normal push conflict protection. Only refresh during cutover before the new
runner begins production history: replacing SQLite with an older export after
cutover can discard newer job observations and receipts.

## Expanding access for the Codex environment

For GitHub CLI API calls, allow `api.github.com` in this cloud environment's
Internet settings, save/apply the change and publish as required by the product.
A configured token being present does not establish API authorization. If an API
request then returns an authorization error, grant the connected GitHub app
repository-scoped Actions read/write, Actions secrets write and Metadata read permissions. Repository-variable
management is optional; the active schedule no longer depends on a variable. Updating workflow files may additionally
require Workflows write permission (or the `workflow` scope for an existing
classic token). Existing Git contents access already supports ordinary pushes.
Do not paste tokens or passwords into chat. The cloud environment's network
allowlist does not control GitHub-hosted runners' outbound network access.

## One-off freshness override

Manual dispatch offers `freshness_days=7` for an explicitly requested seven-day
report. It changes only that run's in-memory criteria and is recorded in the
encrypted run metadata and report. Every scheduled event explicitly selects two
days (48 hours), independent of the previous manual inputs. Saved criteria remain
at two days. Manual runs still obey all other screening and delivery rules.
