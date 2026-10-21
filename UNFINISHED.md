# Coverage work update

Namecheap, Fujitsu and Infineon now use public HTML/sitemap readers; COCUS has a
partial employer-page fallback for blocked ATS requests. Robots rule precedence
is corrected using Protego. See `docs/coverage-status.md` for the exact declared
scopes and unresolved restrictions. Float and JTA remain gaps; incomplete
Infineon details and blocked COCUS inventories are never reported as complete.
The historical notes below describe earlier implementation states.

# GitHub Actions implementation update

The repository now includes a manually runnable Actions replacement with encrypted
state checkpoints, Gmail SMTP/IMAP reconciliation and tests. See
`schedule/github-actions.md`. The encrypted bootstrap branch is published.
Scheduled delivery is now enabled after user-confirmed inbox receipt and pause
of the original ChatGPT task. Repository secrets and the
manual Actions delivery path were validated on 2026-10-21: Gmail accepted the
report and the encrypted state/receipt were persisted. Recipient inbox arrival and the scheduled cutover were confirmed; the first
automatic scheduled run remains to be observed.
The original ChatGPT schedule was paused by the user. Actions uses its newer
encrypted state branch; the local imported snapshot is historical and is not a
live Library synchronization.

# Current implementation update — 21 October 2026

Implemented in the Codex checkout; all 42 tests pass:
- 48-hour original-publication screening at run start, future/date-only handling.
- Salary informational only; mandatory experience minimums above five excluded.
- Complete current-run `email.md` / `email.json` drafts without the legacy cap,
  including fresh review roles, employer-rank ordering, conservative identical-role
  location deduplication and the compact Pros/Cons layout.
- Failure drafts, stable per-attempt run markers, explicit not-sent status and
  `--require-existing-state` protection for production migration.

Pending: actual Gmail delivery/reconciliation and receipts, durable production
state/audit storage access, transfer of the existing ChatGPT schedule and first
observed scheduled run. No schedule was changed and no email was sent.
Location deduplication deliberately preserves uncertain duplicates: only identical
normalized descriptions, titles, salary and check statuses are merged.

The live 60-source check on 2026-10-21 returned 55 complete scopes and five needing
attention: JTA limited feed, Float/Infineon/Fujitsu robots restrictions and OLX
partial detail retrieval. Intellias completed its configured scope in that run.
The historical export notes below describe the earlier baseline, not current code.

---

# Export status — 20 October 2026

This is a source-only recovery export for corrida-repos/tiny-job-scraper. No GitHub write or production scheduler change was made while exporting.

## Included coverage repairs

Reconstructed from the recorded edits after the temporary working tree was lost:

| Employer | Repair | Earlier targeted live observation |
|---|---|---|
| Mindera | Workable account minderacraft; public v2 detail API; countryCode handling | 39 listings, 4 title candidates |
| Loka | Greenhouse board lokainc instead of stale BambooHR | 17 listings, 1 title candidate |
| Devexperts | Public SmartRecruiters Portugal feed | 6 listings, 0 title candidates |
| Remote | Public jobs API; structured advert sections parser | 49 listings, 2 title candidates |
| Stellaxius | Read titles from listing cards; single-post content selector; skip unrelated detail pages | 2 listings, 0 title candidates |

These counts are historical retrieval observations, not current vacancy guarantees. This export was unit-tested, not live-crawled again. Publication fields such as opened_at and published remain unverified original dates; they must not satisfy the 48-hour gate automatically.

## Coverage still unfinished

- Intellias: public AJAX responded during investigation, but a complete final run was not observed. Keep existing adapter and visible failures.
- JTA: https://jta.factorialhr.pt/ is an alternative employer board, but its jobs area was empty. Employee biographies must never become vacancies. Not wired into the adapter.
- Float: the official widget uses /postings.json on float.pinpointhq.com; robots rules disallowed both this and the former feed. No bypass implemented.
- Infineon: public careers/API retrieval remains robots-blocked. No complete alternative verified.
- Fujitsu: /sitemap.xml was accessible, but sitemap enumeration, job extraction and completeness reconciliation were not implemented. Sitemap modification dates are not original posting dates.

## Code versus automation rules

The full current orchestration policy is in docs/current-automation-policy.md. Private deployment identifiers and recipient are redacted. It is documentation, not an executable scheduler.

The Python baseline still has older seven-day freshness, EUR55k salary screening and a capped eligible-only delivery ledger. The external scheduled agent overrides these. Before using the CLI as an independent production job, implement and test:

1. Verified original publication within 48 hours, including strict future/date-only handling; unknown dates excluded from email.
2. No salary acceptance threshold or ranking effect; explicit annual EUR45k+ only an informational Pros item.
3. Exclude mandatory experience minimums above five years.
4. Remote duplicate location selection: Braga, Porto, other Portugal, Nordic countries, rest of EU.
5. Full per-run email, including fresh review candidates and previously reported roles; no ten-role cap; failure/no-match emails.
6. Compact title/direct link/careers link/Pros/Cons format, company-rank-first ordering, run notes at the end.
7. Safe per-run send reconciliation, persistence and delivery receipts. This code does not send email itself.

Keep existing location, language, noncoding, seniority and quarterly travel constraints. Do not make a one-off seven-day report exception the permanent default.

## Excluded from export

No database, run output, scraped job content, CV, inbox content, recipient address, private Library/task identifiers, credentials, cookies, tokens, environment files or git credentials. Static search preferences and the public employer shortlist are included as requested configuration.
