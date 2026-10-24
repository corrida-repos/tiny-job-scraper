# Configure job reporting

Edit [config/criteria.json](../config/criteria.json) using
[GitHub's editor](https://github.com/corrida-repos/tiny-job-scraper/edit/main/config/criteria.json).
Commit the changes to `main`, then check that the **Checks** workflow passes.
The next scheduled run reads those settings automatically. No ChatGPT session,
new deployment, or secret changes are needed.

To preview a change, run **Actions → Daily PM jobs → Run workflow**, leave
`send_email` false and `freshness_days` set to `configured`. This retrieves jobs
using your settings without emailing or updating production state. The normal
08:00 Europe/Lisbon schedule continues independently.

## Settings you can change

These are the current defaults; the committed JSON file is authoritative.

| Setting | Default | Effect |
| --- | --- | --- |
| `role_families` | 45 listed titles | Only these title families become candidates. Remove or add titles in this array. Added qualifiers and direct configured translations are accepted. |
| `allowed_languages` | English, Portuguese, Spanish | Recognized mandatory languages outside this list exclude a job. Optional languages do not. |
| `require_portugal_eligibility` | `true` | Withhold roles without affirmative Portugal eligibility, including potential matches and Unknown Freshness. Explicit foreign-country restrictions remain hard exclusions. |
| `max_mandatory_experience_years` | `4` | Base ceiling for mandatory minimums: 4+ years is accepted; mandatory 5+ is excluded until the ceiling increases. Preferences do not exclude a job. Valid range: 0–50. |
| `experience_growth_anchor` | `2026-09-01` | Add one to the base ceiling per completed anniversary, using Europe/Lisbon. First increase: 1 September 2027. Remove this setting for a fixed ceiling. |
| `nearby_locations` | Porto, Braga and listed nearby towns | Locations eligible for the nearby-office rule. This is a text-match list, not a distance calculator. |
| `allowed_residence_locations` | Santo Tirso, Porto, Braga and listed nearby towns | Reject explicit requirements to live, be based or relocate elsewhere. Country-wide Portugal/EU residence requirements remain compatible with Santo Tirso. This is independent of the office attendance allowance. |
| `max_office_days_per_week` | `3` | Maximum explicitly stated nearby-office attendance. Valid range: 0–5. |
| `max_distant_office_visits_per_quarter` | `1` | Maximum explicitly stated quarterly visits for distant offices in a remote arrangement. Set `0` to reject quarterly office visits. Valid range: 0–12. Routine weekly/monthly distant-office patterns remain excluded; the parser does not convert these into a quarterly allowance. |
| `max_abroad_calendar_days_per_quarter` | `7` | Maximum required days abroad per quarter, including transit and all trips. Valid range: 0–90. Annual averages and ambiguous travel percentages do not establish compliance. |
| `exclude_mandatory_coding` | `true` | Reject mandatory code-writing or coding assessments. Set `false` to stop using this as an exclusion. |
| `exclude_shift_on_call` | `true` | Reject recognized required shift/on-call/weekend patterns. Set `false` to stop using this as an exclusion. |
| `max_post_age_days` | `2` | Accepted posting/repost date must fall within this many days before the run. `2` = 48 hours; `7` = one week. Valid range: 1–30. Scheduled runs use this value. |
| `accept_employer_dates` | `true` | Accept employer-declared publication and repost dates, while preserving earliest original dates. Set `false` to require original-publication evidence. Modification/creation dates do not qualify. |
| `include_potential_matches` | `true` | Include review-status roles alongside verified eligible roles, subject to the freshness switches below. Set `false` to report only verified eligible roles. Hard failures remain excluded. |
| `include_unknown_freshness` | `true` | Include roles lacking an accepted publication date or sufficient date precision, labelled **Unknown freshness**. Requires `include_potential_matches=true`. Known old postings are excluded unless there is a fresh employer-declared repost. |
| `include_future_dated` | `true` | Include roles whose available posting date is in the future, labelled **Unknown freshness**, the same category as missing original-date evidence. They remain unverified potential matches, rather than verified recent postings. Requires `include_potential_matches=true`. |

Supported language names (use these exact names): English, Portuguese, Spanish,
German, French, Dutch, Italian, Polish, Czech, Danish, Swedish, Norwegian,
Finnish, Mandarin, Japanese and Arabic. Recognition uses English and selected
Portuguese aliases; this is rule-based extraction, not exhaustive language
understanding.

For example, change `max_mandatory_experience_years` from `4` to `7` to allow
roles requiring seven years; change `include_potential_matches` to `false` for
verified matches only. Change `max_post_age_days` to `7` for a persistent
seven-day window. The manual workflow's `2` or `7` freshness choices override
that setting for one run only and never rewrite the saved file.

Keep valid JSON: double-quoted strings, lowercase `true`/`false`, numbers without
quotes, no comments and no trailing commas. Unknown setting names, unsupported
languages, wrong types and out-of-range values fail validation before retrieval.

## Scope and evidence rules

- The Top 56 employers and their report priority come from
  [companies.json](../config/companies.json) and the
  [shortlist](employer-shortlist.md). Criteria changes do not add employers.
- `excluded_companies` can further exclude named employers from reporting;
  `explicit_inclusions` is descriptive and does not expand the source list.
- `portuguese_titles` maps translated titles to families. A translation is
  active only when its target family is enabled in `role_families`.
- `home`, `timezone` and `notes` are context. Editing them does not relocate the
  Portugal eligibility logic or change the 08:00 Lisbon schedule.
- Portugal hiring eligibility, senior-leadership exclusions, publication-date
  evidence, salary neutrality and freshness/company/position grouping remain fixed. Unknown
  and future dates never become verified dates merely because they are included
  in a report. Salary has no minimum requirement or ranking effect.
- Unknown evidence stays unknown. Relaxing one configurable exclusion never
  removes an unrelated failure. Work-life balance cannot be guaranteed by a
  posting, and numerical travel caps still require explicit supporting evidence.
- Mandatory residence outside the permitted Porto/Braga area is a hard exclusion
  even if a vacancy says "Remote – Portugal". Greenhouse application questions
  and descriptions are included in residence screening. If those questions
  cannot be checked, the candidate is retained in the audit and withheld from
  email, including potential-match emails. Other adapters currently screen the
  public job evidence they retrieve; application-form coverage is not universal.

Each run records its effective criteria in `results.json`, alongside its job
assessments, so a report can be traced to the settings actually used. Historical
records are preserved; changes apply when the next run evaluates current jobs.

## Local validation

```bash
.venv/bin/python run.py validate-criteria
.venv/bin/python run.py validate-criteria --criteria /path/to/proposed-criteria.json
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Validation reads settings only; it does not contact job sites, change state or
send email. Automated regression tests use a fixed fixture so supported changes
to your preferences do not require rewriting tests. GitHub separately validates
the actual committed settings on every code/configuration push and daily run.
## Posting and repost dates

`accept_employer_dates` is currently `true`: employer-declared posting/repost dates
can establish freshness within `max_post_age_days`. Set it to `false` to require
original-publication evidence. Neither mode treats modification, internal creation
or first-seen timestamps as fresh publication. Missing years and future dates
remain Unknown Freshness; date evidence is shown beneath each position.
