# Coverage repairs — 21 October 2026

The 60-employer allowlist, 48-hour scheduled freshness window, salary and
experience rules, daily schedule and persistent production state are unchanged.

| Employer | Repair / current limitation |
| --- | --- |
| Namecheap | Read paginated `window.openingsData` from the public `/careers/openings/` pages instead of the blocked API. Reconcile page numbers, unique IDs and totals. Ignore the internal backend pagination URLs embedded in the response. This works in the cloud workspace; GitHub-hosted runners still receive HTTP 403 on the public HTML page. |
| Fujitsu | Enumerate the public sitemap and retrieve allowed-title job detail pages instead of the robots-disallowed search service. Parse the actual title, description, location and canonical job identity. Publication-start labels and sitemap `lastmod` are not accepted as original posting dates. |
| Infineon | Use its public careers sitemap and matching JobPosting data on public detail pages. Its API is allowed by robots but returned HTTP 403 in a live check. Missing detail data remains a visible coverage gap. |
| COCUS | Keep the full Sage ATS reader, with a fallback to vacancy cards published on COCUS's own careers page when the ATS is blocked. Fallback results are always partial; generic open applications do not count as vacancies. |
| Float | Its Pinpoint board currently disallows all crawling. Leave this blocked, without using the obsolete commented-out widget or bypassing restrictions. |
| JTA | The official careers page currently provides spontaneous applications, not an enumerated vacancy feed. Keep limited coverage visible; biographies and the whistleblowing portal are not job listings. |

The HTTP client now uses Protego for standards-compliant robots rule precedence.
A more specific `Allow` takes precedence over a broad `Disallow`, while specific
prohibitions, blanket disallow rules, actual endpoint HTTP 403s and human
verification barriers remain enforced. The previous Python standard-library
parser incorrectly denied Infineon's explicitly allowed paths.

Local validation retrieved 25 Namecheap listings (two title candidates), 662
Fujitsu sitemap-listed jobs (22 title candidates), and 1,294 Infineon sitemap-listed
job URLs (37 retained candidates; two missing matching detail data). COCUS's
primary ATS worked locally; a fixture verifies the blocked-ATS fallback remains
partial. These observations are not promises of full worldwide employer coverage.

Sitemap coverage means the declared inventory of sitemap-listed job URLs, with
title filtering based on URL slugs before detail retrieval. It does not establish
coverage of jobs omitted from the employer's sitemap. Sitemap dates never satisfy
the freshness gate. Detail failures, limits and schema changes remain visible;
complete enumeration of URLs alone cannot turn failed candidate extraction into
successful coverage.

All 67 unit tests passed locally and in the GitHub-hosted validation workflow.
The final full check, [Actions run 39602187312](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39602187312),
completed 55/60 declared source scopes, compared with 54/60 before this work.
Fujitsu and Continental completed. COCUS returned its employer-page subset while
its full ATS remained blocked. Infineon returned candidates but retained missing
detail gaps. Float stayed robots-blocked, JTA stayed limited, and Namecheap's
public HTML page returned HTTP 403 from GitHub despite working locally.

Continental's public directory intermittently returned empty page shells; an
uncached retry recovered listings in a live check. It now retries such an empty
page once. Persistent empty or failed pages remain incomplete, and redundant
first-page pagination aliases are normalized. This does not retry access-denied
responses or bypass human-verification barriers.

Validation runs use a disposable decrypted database and do not send email or
update production state. The daily schedule and 48-hour freshness window remain
unchanged. These changes are deployed to main for the next scheduled execution.
