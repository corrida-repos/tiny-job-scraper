# Coverage repairs — 21 October 2026

The 60-employer allowlist, 48-hour scheduled freshness window, salary and
experience rules, daily schedule and persistent production state are unchanged.

| Employer | Repair / current limitation |
| --- | --- |
| Namecheap | Read paginated `window.openingsData` from the public `/careers/openings/` pages instead of the blocked API. Reconcile page numbers, unique IDs and totals. Ignore the internal backend pagination URLs embedded in the response. This works in the cloud workspace; GitHub-hosted runners still receive HTTP 403 on the public HTML page. |
| Fujitsu | Enumerate the public sitemap and retrieve allowed-title job detail pages instead of the robots-disallowed search service. Parse the actual title, description, location and canonical job identity. Publication-start labels and sitemap `lastmod` are not accepted as original posting dates. |
| Infineon | Read the current public PCSX search inventory used by its careers website, with all locations and titles. Reconcile totals and unique IDs across every page, then read matching JobPosting details. A public PCSX detail fallback recovers descriptions without treating `postedTs` as verified original publication. |
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

## Follow-up investigation — current Infineon website

The current careers JavaScript references `/api/pcsx/search` and
`/api/pcsx/position_details`; both are explicitly allowed by the site's robots
rules. These are public vacancy reads and require no account or credentials.
The previously checked `/api/apply/v2/jobs` service is a different route and
remains unused by this adapter.

The two sitemap IDs with missing details (`563808969050021` and
`563808971934068`) returned a structured HTTP 404, `Position not found`, from
the current public detail service. A control job (`563808971834977`) returned
its full details from the same service. Instead of inferring closure from an
empty page or special-casing those IDs, the new adapter enumerates the current
search inventory. A job that disappears between inventory and detail retrieval
still leaves a visible coverage gap.

The search service returns ten records per page. Infineon therefore has a
200-page limit and a 600-second source budget; other sources retain their
existing defaults. An explicit CLI `--max-pages` overrides the source default.
Missing totals, duplicate IDs, changing totals, early termination, limits,
unsuccessful/fallback responses, and unavailable candidate details all prevent
a complete coverage claim. Candidate selection now uses actual listing titles,
not sitemap URL slugs. Job IDs must match before accepting detail data.

Only matched JobPosting `datePosted` establishes original publication. Public
API `postedTs` is retained as metadata, never promoted to verified freshness.
The production freshness window remains 48 hours.

Float's Pinpoint robots file was rechecked and still disallows all crawling.
JTA's sitemap index exposes no vacancy-specific sitemap; its 17-page page sitemap
links only to the same spontaneous-application careers page. These remain
unresolved source limitations. COCUS and Namecheap still need validation from
the GitHub runner because their public boards work in this workspace but have
returned HTTP 403 from GitHub.

Local validation of the new adapter enumerated all 1,298 current search records,
reconciled the reported total, and extracted 38 title candidates with complete
details. All 38 were rejected by the saved screening rules; complete retrieval
does not imply an eligible match. All 79 unit tests pass. GitHub-runner validation
is recorded below when complete.
