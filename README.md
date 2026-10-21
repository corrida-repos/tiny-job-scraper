> **Recovery export:** Read [UNFINISHED.md](UNFINISHED.md) and [current automation rules](docs/current-automation-policy.md) before deployment. Several newer screening/email rules are external orchestration overrides, not implemented by this CLI.

# PM careers scraper — 60 employers

A Python scraper for the exact 60 employers in `config/companies.json`, including Bosch, Vestas, DACHSER and JTA. It replaces broad daily web searches with repeatable retrieval from employer boards. The saved employer shortlist supplies context; the current job posting supplies screening evidence.

## Run

Requires Python 3.11+ and `lxml`. No ATS API keys or browser login are needed.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run.py run --state data/state.sqlite3 --output output/latest
```

On Windows, use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.

Use `python run.py sources` to list all 60 IDs. For a focused check, use `python run.py run --only 20,23,35,1 --state data/state.sqlite3 --output output/focused` (Bosch, DACHSER, Vestas, JTA). Focused runs produce a focused report; they do not replace a full 60-source audit.

Exit code **0** means all configured sources completed, **2** means reports were written but at least one source needs attention, and other nonzero exits indicate a runtime/configuration failure. A partial run still returns usable results from sources that worked. Treat exit 2 as an operational warning, never as an empty successful search.

## Daily output

| File | Purpose |
|---|---|
| `report.md` | New eligible roles, roles needing confirmation, and source health |
| `results.json` | Complete candidate descriptions, evidence, reasons and source audit |
| `roles.csv` | Flat export of candidates and decisions |
| `source-health.json` | Coverage, counts, errors and checked URLs for each employer |
| `digest.json` | Up to 10 newly eligible, unreported roles and a delivery ID |

Results have three states: **eligible**, **review**, or **rejected**. Unknown travel, attendance, Portugal eligibility or original publication date stays in review. A review entry is not a confirmed match. Salary missing from a posting is flagged without automatic rejection. Work-life balance cannot be guaranteed from advertising; the report preserves employer context and flags explicit shift/on-call requirements.

The numeric priority score is a transparent rule-based convenience (remote/location, travel evidence and freshness). It is not an employee-review or work-life-balance rating. Ties use the saved employer shortlist order.

## Your criteria

- Exact 45 allowed title families, with added qualifiers and defined direct Portuguese translations; excluded top-level leadership titles. Engineering Manager and Team Lead are included.
- No mandatory code writing or coding tests. Reading/reviewing code is acceptable.
- Santo Tirso base; nearby northern hybrid roles require at most two office days weekly. Distant offices require remote work and quarterly-or-less visits.
- **No more than seven calendar days abroad in any quarter**, across all business trips, onboarding, training, retreats/offsites and transit. Annual averages and percentages alone do not establish this cap.
- Mandatory languages limited to Portuguese, English and Spanish.
- Original publication less than seven days ago. Last-published, refreshed, modified and first-seen timestamps are not accepted as original publication.
- EUR 55,000 gross annual target; an explicit annual EUR salary ceiling below it is rejected.
- Only the configured 60 employers; no inferred sector exclusion. Bosch and Vestas remain included.

The parser uses explicit evidence and conservative pattern rules. It cannot understand every phrasing. Check the retained evidence before applying. To resolve a specific ambiguity, add an entry keyed by job ID to `config/verified-overrides.json` with `verified_at`, `evidence`, and supported `checks` set to `pass` or `fail`. Evidence expires after 90 days. Do not fabricate verification. See `docs/verified-override-example.json`.

## Daily state and notifications

Keep `data/state.sqlite3` between runs. It retains stable ATS IDs, first/last observation, earliest original date, content changes, source runs and successful notifications. An edited job does not become new again. Failed/partial boards do not mark jobs missing. Two complete healthy absences mark a job `missing_unconfirmed`; this is not a claim that the employer closed it.

The scraper **does not send email itself**. The scheduled ChatGPT task uses the connected Gmail account for the already-authorized digest. A separate delivery acknowledgement prevents retrieval failures or unsent drafts from counting as notifications:

```bash
python run.py ack pm-DELIVERY_ID --receipt GMAIL_MESSAGE_ID --state data/state.sqlite3
```

Only run `ack` after a confirmed successful send. A retry produces the same pending delivery ID. Before retrying an uncertain email send, search Sent for that ID to prevent duplicate mail. If `digest.json.jobs` is empty, send no job digest. Save the report regardless so source failures and review candidates remain visible.

The original downloadable ZIP included a one-off audit snapshot. This Git import intentionally excludes `audit/` and mutable databases; preserve production state separately. See `docs/import-notes.md` for differences between this source baseline and the latest requested changes.

## Scheduling

The replacement ChatGPT task retains 08:00 Europe/Lisbon and materializes the saved code plus the latest state on each run. It saves updated state and a new version of the report. Local workspace paths are not assumed to survive between runs. Code execution, network access and connected apps must be available in the scheduled run; if unavailable the task must report that failure, preserve state and never substitute a broad web search or claim zero matches.

For independent local deployment, `schedule/` contains systemd and Windows Task Scheduler setup examples. Do not enable both that schedule and the ChatGPT schedule unless you intentionally want two retrievals. A host running a local schedule must stay available. No additional scheduler is installed by this package.

## Source-specific readers and limitations

Adapters include Greenhouse, Ashby public/embedded boards, Lever US/EU, Recruitee, Teamtailor HTML, SmartRecruiters, Workday, SAP SuccessFactors HTML and unified search, Phenom, WordPress AJAX, Astro server islands, Namecheap Vue data, Bizneo, BambooHR, Workable, Pinpoint and employer-specific HTML patterns. All 60 entries retain the original careers link and a dated source mapping.

Pagination checks totals/end markers where supplied; repeated pages, page caps, failed detail extraction, schema changes and access errors are visible. Workday searches Portugal, Porto, Braga, Remote, EMEA, Europe and Worldwide; this is a defined search scope, not proof of exhaustive worldwide coverage. Bosch, SAP and Phenom searches use Portugal. Other global feeds are screened for Portugal eligibility after retrieval.

Requests use an honest User-Agent, per-host pacing, bounded retries, size/time/page/detail limits and read-only public endpoints. Web crawling follows robots rules. A missing robots resource with a 4xx status follows RFC 9309; actual job endpoint 401/403 responses still stop access. SmartRecruiters uses its explicitly documented unauthenticated public Posting API rather than its authenticated APIs. No private/internal postings, job applications, challenges or login barriers are accessed.

Some sources cannot currently provide complete machine-readable coverage; the original ZIP contained a dated `audit/source-health.json` snapshot, intentionally excluded from source control. JTA's page currently accepts spontaneous applications without an enumerated vacancy feed. This remains visible as limited coverage. Public pages and ATS schemas can change; a successful check today is not a promise of permanent coverage.

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
