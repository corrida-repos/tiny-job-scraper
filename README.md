> **Daily operation:** GitHub Actions runs this scraper independently of ChatGPT. The repository holds code, settings and encrypted persistent state; GitHub secrets supply Gmail credentials. See [runner setup](schedule/github-actions.md) and [criteria settings](docs/configuring-criteria.md).

# PM careers scraper — 56 employers

A Python scraper for the exact 56 employers in `config/companies.json`, including Bosch, Vestas and DACHSER. It replaces broad daily web searches with repeatable retrieval from employer boards. The saved employer shortlist supplies context; the current job posting supplies screening evidence.

## Run

Requires Python 3.11+ and `lxml`. No ATS API keys or browser login are needed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py run --state data/state.sqlite3 --output output/latest
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

Use `python run.py sources` to list all 56 IDs. For a focused check, use `python run.py run --only bosch,dachser,vestas --state data/state.sqlite3 --output output/focused` (Bosch, DACHSER, Vestas). Focused runs produce a focused report; they do not replace a full 56-source audit.

Exit code **0** means all configured sources completed, **2** means reports were written but at least one source needs attention, and other nonzero exits indicate a runtime/configuration failure. A partial run still returns usable results from sources that worked. Treat exit 2 as an operational warning, never as an empty successful search.

## Daily output

The report and email group positions by **Verified Freshness / Unknown Freshness
→ Company → Position**. Company priority is preserved within each freshness
category; future-dated roles share Unknown Freshness. Category labels appear
once per section, while job titles remain bold subheadings.

| File | Purpose |
|---|---|
| `report.md` | New eligible roles, roles needing confirmation, and source health |
| `results.json` | Complete candidate descriptions, evidence, reasons and source audit |
| `roles.csv` | Flat export of candidates and decisions |
| `source-health.json` | Coverage, counts, errors and checked URLs for each employer |
| `digest.json` | Legacy capped/new-only digest; do not use for the daily email |
| `email.md`, `email.json` | Complete current-run daily email draft, subject, run marker and alternative URLs; not sent |

Results have three states: **eligible**, **review**, or **rejected**. Unknown travel, attendance, Portugal eligibility or original publication date stays in review. A review entry is not a confirmed match. Missing salary has no effect on screening or ranking. Work-life balance cannot be guaranteed from advertising; the report preserves employer context and flags explicit shift/on-call requirements.

The numeric priority score is a transparent rule-based convenience (remote/location, travel evidence and freshness). It is not an employee-review or work-life-balance rating. Ties use the saved employer shortlist order.

## Your criteria

Edit [config/criteria.json](config/criteria.json) to change screening and reporting
preferences. See [the settings guide](docs/configuring-criteria.md) for supported
controls and a direct GitHub edit link. Scheduled runs use the committed settings;
the following list describes the current defaults.

- Exact 45 allowed title families, with added qualifiers and defined direct Portuguese translations; excluded top-level leadership titles. Engineering Manager and Team Lead are included.
- No mandatory code writing or coding tests. Reading/reviewing code is acceptable.
- Santo Tirso base; nearby northern hybrid roles require at most three office days weekly. Distant offices require remote work and quarterly-or-less visits.
- Exclude jobs requiring residence or relocation outside the permitted Porto/Braga area. Explicit residence requirements override remote labels; Greenhouse application questions are checked as well as descriptions.
- **No more than seven calendar days abroad in any quarter**, across all business trips, onboarding, training, retreats/offsites and transit. Annual averages and percentages alone do not establish this cap.
- Mandatory languages limited to Portuguese, English and Spanish.
- Verified original publication within 48 hours of run start qualifies as fresh. Roles lacking sufficient date evidence are included as **Unknown freshness**; future-dated postings are also included as **Unknown freshness**. Both remain unverified potential matches. Verified original dates older than 48 hours are excluded. Last-published, refreshed, modified and first-seen timestamps are not accepted as original publication.
- No salary threshold or ranking effect; explicit gross annual EUR45k+ salary is an optional positive in the email draft.
- Mandatory experience minimums above five years are excluded; ambiguous requirements remain in review.
- Only the configured 56 employers; no inferred sector exclusion. Bosch and Vestas remain included.

The parser uses explicit evidence and conservative pattern rules. It cannot understand every phrasing. Check the retained evidence before applying. To resolve a specific ambiguity, add an entry keyed by job ID to `config/verified-overrides.json` with `verified_at`, `evidence`, and supported `checks` set to `pass` or `fail`. Evidence expires after 90 days. Do not fabricate verification. See `docs/verified-override-example.json`.

## Daily state and notifications

Keep `data/state.sqlite3` between runs. It retains stable ATS IDs, first/last observation, earliest original date, content changes, source runs and successful notifications. An edited job does not become new again. Failed/partial boards do not mark jobs missing. Two complete healthy absences mark a job `missing_unconfirmed`; this is not a claim that the employer closed it.

The scraper **does not send email itself**. The scheduled ChatGPT task uses the connected Gmail account for the already-authorized digest. A separate delivery acknowledgement prevents retrieval failures or unsent drafts from counting as notifications:

```bash
python run.py ack pm-DELIVERY_ID --receipt GMAIL_MESSAGE_ID --state data/state.sqlite3
```

Only run `ack` after a confirmed successful send. A retry produces the same pending delivery ID. Before retrying an uncertain email send, search Sent for that ID to prevent duplicate mail. The legacy digest is not the daily email. Use `email.json` / `email.md` for every attempted run, including no-match and failure reports. They include all qualifying current-run roles, even previously reported ones, without the legacy ten-role cap. Draft generation never confirms sending; reconcile the run marker in Gmail Sent and record a receipt only after successful delivery. Save the report regardless so source failures and review candidates remain visible.

The original downloadable ZIP included a one-off audit snapshot. This Git import intentionally excludes `audit/` and mutable databases; preserve production state separately. See `docs/import-notes.md` for differences between this source baseline and the latest requested changes.

## Scheduling

GitHub Actions runs the scraper at 08:00 Europe/Lisbon, restores the encrypted
state from the `runtime-state` branch, evaluates jobs and delivers the report
through Gmail. It does not require ChatGPT, Codex, this chat or an always-on user
computer. The original ChatGPT scheduled task is paused. GitHub's scheduler may
start a run later than the requested time.

For independent local deployment, `schedule/` contains systemd and Windows Task
Scheduler examples. Avoid enabling a second scheduler alongside GitHub Actions
unless you intentionally want two retrievals. A local scheduler requires an
available host.

## Source-specific readers and limitations

Adapters include Greenhouse, Ashby public/embedded boards, Lever US/EU, Recruitee, Teamtailor HTML, SmartRecruiters, Workday, SAP SuccessFactors HTML and unified search, Phenom, WordPress AJAX, Astro server islands, Namecheap Vue data, Bizneo, BambooHR, Workable, Pinpoint and employer-specific HTML patterns. All 56 entries retain the original careers link and a dated source mapping.

Pagination checks totals/end markers where supplied; repeated pages, page caps, failed detail extraction, schema changes and access errors are visible. Workday searches Portugal, Porto, Braga, Remote, EMEA, Europe and Worldwide; this is a defined search scope, not proof of exhaustive worldwide coverage. Bosch, SAP and Phenom searches use Portugal. Other global feeds are screened for Portugal eligibility after retrieval.

Requests use an honest User-Agent, per-host pacing, bounded retries, size/time/page/detail limits and read-only public endpoints. Web crawling follows robots rules. A missing robots resource with a 4xx status follows RFC 9309; actual job endpoint 401/403 responses still stop access. SmartRecruiters uses its explicitly documented unauthenticated public Posting API rather than its authenticated APIs. No private/internal postings, job applications, challenges or login barriers are accessed.

Some sources cannot currently provide complete machine-readable coverage; the original ZIP contained a dated `audit/source-health.json` snapshot, intentionally excluded from source control. COCUS, Float, JTA and Namecheap have been removed from the active watchlist at the user's request because their inventories remained incomplete. Public pages and ATS schemas can change; a successful check today is not a promise of permanent coverage.

## Checks and maintenance

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

On Windows PowerShell, set `$env:PYTHONPATH='src'` before the same Python command. Tests cover title boundaries, coding/languages, quarterly travel, commute constraints, date provenance, duplicate notifications, source failures, persistent dates and pagination. Live network checks are separate and recorded in the audit.

Adjust a source's `budget_seconds` only for a concrete time-budget failure. Defaults are 180 seconds per employer, one request per second per host, 60 listing pages and 250 candidate details. CLI options can tighten these limits. Hitting a limit always produces an incomplete status.

## Primary implementation references

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) — `first_published` versus `updated_at`.
- [Ashby public job posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) — `publishedAt` means last publication.
- [Lever postings API](https://github.com/lever/postings-api) — public listings and pagination.
- [SmartRecruiters authentication](https://developers.smartrecruiters.com/docs/authentication) and [Posting API endpoints](https://developers.smartrecruiters.com/docs/endpoints).
- [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) — robots handling.
- [ChatGPT scheduled tasks](https://learn.chatgpt.com/docs/automations) — durable inputs, connected tools and unattended execution.

Employer-specific endpoint mappings were obtained from the employers' public careers pages and their linked public client code on 19 October 2026. They are data retrieval routes, not credentials or application-submission routes.

## Codex migration

See [the prepared scheduled-run instructions](schedule/codex-task.md). The daily
ChatGPT task has not been transferred to Codex. Production runs must restore the
real state first and use `--require-existing-state`; onboarding databases are
isolated checks and must never replace it. Network validation on 2026-10-21
completed 55 of 60 configured source scopes; five coverage gaps were recorded in that historical run. The active watchlist now contains 56 employers.

## GitHub Actions runner

A repository-based replacement is implemented in
[the Actions workflow](.github/workflows/daily-jobs.yml); follow
[setup and cutover instructions](schedule/github-actions.md). Daily delivery is enabled for 08:00 Europe/Lisbon; use GitHub Actions
“Disable workflow” to pause it. The encrypted `runtime-state` branch
preserves job and delivery history. Gmail delivery was validated and the user confirmed the original ChatGPT task
is paused. The [scheduled run on 22 October 2026](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39742353371)
completed successfully and persisted its delivery receipt.

## Source coverage repairs

Run **Actions → Focused coverage check → Run workflow** to check
Noesis, whose primary board has shown intermittent access failures. This manual
workflow uses a disposable database, read-only repository permissions and no
production secrets. It sends no email and cannot update production state.
The job summary and `coverage-audit` artifact contain source statuses, listing
and candidate counts, pages/requests and failure reasons. A green diagnostic job
means the check ran successfully; inspect the summary for incomplete coverage.
Missing, inconsistent or failed audit output fails the job.

Locally, use a new artifact directory for each check:

```bash
PYTHONPATH=src .venv/bin/python -m pm_scraper.coverage_check --source noesis --artifact-dir output/coverage-check-1
```

The diagnostic retains only `source-health.json` and `summary.md`; its database,
candidate details and email drafts are discarded. It uses the saved screening
criteria, currently a 48-hour freshness window. The daily schedule is independent.

See [coverage status](docs/coverage-status.md) for the public HTML/sitemap readers
and historical investigations. The active Top 56 excludes COCUS, Float, JTA and
Namecheap; historical audits and job/delivery records remain preserved. Scheduled
runs use the saved freshness window, currently 48 hours.
