# Coverage repairs — 21 October 2026

Latest GitHub validation: **56/60 source scopes complete**, with **96 unit tests
passing**. Noesis's primary inventory worked in both focused and full validation;
its earlier HTTP 403 appears intermittent. COCUS, Float, JTA and Namecheap remain
incomplete. All five now have a verified-employer secondary RSS fallback, and a
separate manual workflow can diagnose one or all five without production secrets.
See [Actions run 39689294359](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39689294359).

The 60-employer allowlist, 48-hour scheduled freshness window, salary and
experience rules, daily schedule and persistent production state are unchanged.

| Employer | Repair / current limitation |
| --- | --- |
| Namecheap | Read paginated `window.openingsData` from the public `/careers/openings/` pages instead of the blocked API. Reconcile page numbers, unique IDs and totals. Ignore the internal backend pagination URLs embedded in the response. This works in the cloud workspace; GitHub-hosted runners still receive HTTP 403 on the public HTML page. |
| Fujitsu | Enumerate the public sitemap and retrieve allowed-title job detail pages instead of the robots-disallowed search service. Parse the actual title, description, location and canonical job identity. Publication-start labels and sitemap `lastmod` are not accepted as original posting dates. |
| Infineon | Read the current public PCSX search inventory used by its careers website, with all locations and titles. Reconcile totals and unique IDs across every page, then read matching JobPosting details. A public PCSX detail fallback recovers descriptions without treating `postedTs` as verified original publication. |
| COCUS | Keep the full Sage ATS reader, with a fallback to vacancy cards published on COCUS's own careers page when the ATS is blocked. Fallback results are always partial; generic open applications do not count as vacancies. |
| Float | Its Pinpoint board disallows crawling. The public We Work Remotely RSS feed now provides secondary discovery; it cannot establish a complete inventory or original posting dates. |
| JTA | The official careers page currently provides spontaneous applications, not an enumerated vacancy feed. Keep limited coverage visible; biographies and the whistleblowing portal are not job listings. |
| Noesis | Its primary listing completed in the latest focused and full GitHub checks after an earlier HTTP 403. Access appears intermittent. A strict Noesis/official-domain WWR fallback is now configured for future incomplete retrieval, but remains partial and cannot establish original publication dates. |

The HTTP client now uses Protego for standards-compliant robots rule precedence.
A more specific `Allow` takes precedence over a broad `Disallow`, while specific
prohibitions, blanket disallow rules, actual endpoint HTTP 403s and human
verification barriers remain enforced. The previous Python standard-library
parser incorrectly denied Infineon's explicitly allowed paths.

The earlier repair pass retrieved 25 Namecheap listings (two title candidates), 662
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

During the earlier repair pass, 67 unit tests passed locally and on GitHub.
That earlier full check, [Actions run 39602187312](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39602187312),
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
unresolved source limitations. COCUS and Namecheap were rechecked on GitHub and still return HTTP 403
from that runner, despite working in this workspace.

Local validation of the new adapter enumerated all 1,298 current search records,
reconciled the reported total, and extracted 38 title candidates with complete
details, including three title candidates absent from the earlier sitemap
reader. The two stale sitemap IDs were absent from the current search results.
All 38 were rejected by the saved screening rules; complete retrieval
does not imply an eligible match. All 79 unit tests passed locally and in the GitHub validation run.

[GitHub validation 39607294698](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39607294698)
completed successfully at code commit `7ba2fdf`, with 56/60 source scopes complete.
Infineon now completes from the actual production runner. The remaining gaps are:

- COCUS: its full Sage inventory returns HTTP 403; its official-page subset is retained as partial.
- Float: the Pinpoint board explicitly disallows crawling.
- JTA: no enumerated vacancy feed was found on its official careers page or page sitemap.
- Namecheap: the public openings page returns HTTP 403 from GitHub.

The run used `send_email=false` and the normal two-day freshness window. It sent
no email and made no production-state writes. The encrypted runtime-state branch
remained at `e7552fd7635e3f82ab4336fe1d09a1109ae6d7e9`. The daily workflow remains
active for 08:00 Europe/Lisbon with the 48-hour rule.

## Public secondary-feed fallback

The four incomplete sources now check the public feed at
`https://weworkremotely.com/remote-jobs.rss` when their primary retrieval is
incomplete. A listing must match both an explicit configured employer name and
the official employer website in the RSS description's `URL:` field. Same-named
companies, lookalike domains, unrelated links and non-job URLs are skipped.
The feed is read normally, with robots and access checks; no account, proxy
rotation, browser impersonation or new hosting service is used.

This is supplementary discovery from recent RSS items, not a replacement for
an employer's inventory. Primary errors remain in the audit and coverage stays
partial even when the secondary feed is readable or empty. Recovered candidates
are retained in results/state for review. RSS `pubDate` is recorded only as
syndication metadata. It cannot pass the verified-original-publication gate or
place an otherwise unverified role into the daily email. Jobs on successful
primary sources use their existing readers without requesting the fallback.

Live investigation confirmed Float's public WWR company profile and the RSS feed.
The profile listed zero jobs, and the current RSS feed had 93 items with no matches
for the four employers. Guessed WWR company profiles for the other three employers
redirected to its homepage and were not treated as employer feeds. They are
monitored only through the strict RSS employer-name and official-website checks.
Remote OK's Float page did not expose usable public job details. COCUS's Portuguese
domain redirects to its existing corporate site. Namecheap's current public
JavaScript exposed no separate RSS feed. JTA still has no enumerated vacancy feed.

Focused local validation completed COCUS (four listings) and Namecheap (25 listings,
two title candidates); both Namecheap candidates were rejected by the saved rules.
Float and JTA successfully checked the secondary RSS feed and remained partial,
with zero matching feed listings. All 88 unit tests passed locally and on GitHub.

[GitHub validation 39686659074](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39686659074)
confirmed successful secondary RSS retrieval for all four configured employers at
code commit `3c554b4`. Each returned zero matching RSS listings and stayed partial.
The run completed 55/60 source scopes. Its additional gap was a new HTTP 403 from
Noesis on `https://opportunities.noesis.pt/jobs`; that same listing page was readable
in a subsequent workspace check, with no alternate feed advertised. Its source
configuration and reader were not changed by the fallback work.

Validation used `send_email=false` and `freshness_days=2`. It sent no email and
left the encrypted production-state branch unchanged at
`e7552fd7635e3f82ab4336fe1d09a1109ae6d7e9`. The daily workflow remains active, using
the 48-hour freshness rule. No always-on user machine or new hosting service is
required for the public RSS fallback; full employer coverage is still unresolved.

## Focused diagnostics and remaining-source investigation

The manual `coverage-check.yml` workflow checks one of the five unresolved
employers or all five. It runs existing adapters against a fresh temporary SQLite
database, with read-only repository permissions and no production secrets. Only
`source-health.json` and a readable summary survive. Listing/candidate counts,
pages/requests and primary/fallback failure reasons are included. Source gaps
produce warnings; invalid/missing audits and execution failures fail the job.
An existing artifact directory is rejected to prevent reuse of stale evidence.

Noesis now has the same secondary RSS fallback, requiring the exact employer
name `Noesis` and an explicit official website of `noesis.pt` or `www.noesis.pt`.
Other same-named companies and lookalike domains are rejected. The fallback
never establishes complete employer coverage or original publication dates.

The latest public-interface inspection found:

- Noesis: its public form submits to `/jobs`; HTMX updates the same job-board
  fragment. No alternate feed is advertised. The linked Bizneo JavaScript asset
  could not be retrieved in this workspace, so its contents remain unverified.
- COCUS: the Sage board and its public recruitment JavaScript advertise no
  separate vacancy feed. The corporate-page subset remains partial when Sage
  is unavailable; it cannot establish a complete vacancy inventory.
- Namecheap: the advertised sitemap index leads to a main sitemap containing
  the careers landing page, but no vacancy inventory. No sitemap adapter was
  added. Its current public JavaScript did not expose a separate vacancy feed.
- Float: the corporate widget points to the same robots-disallowed Pinpoint
  host. The permitted WWR feed remains supplementary discovery only.
- JTA: the advertised page sitemap contains its existing careers page, with
  spontaneous applications rather than an enumerated vacancy feed. This does
  not establish that the employer has zero vacancies.

Local focused validation completed three of five source scopes: COCUS had four
listings, Namecheap 25 (two title candidates), and Noesis 120 (20 candidates).
Float and JTA stayed partial with zero matching secondary-feed listings. These
local successes do not establish access from GitHub-hosted runners. All 96 unit
tests passed, including disposable-state isolation, failed/missing/stale audit
handling, escaped diagnostics and strict Noesis identity matching. Actionlint
accepted the new workflow. The production workflow and 48-hour rule are unchanged.

[Focused GitHub validation 39689169934](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39689169934)
at code commit `40b89be` completed in 39 seconds and uploaded its audit artifact.
It completed one of five source scopes: Noesis's primary reader enumerated 120
listings and 20 title candidates across 30 page/detail requests. Its earlier 403
was not reproduced; this is intermittent access recovery, not evidence that the
new RSS fallback repaired its primary inventory. COCUS retained four listings
from its corporate-page subset after Sage returned 403. Namecheap still returned
403, Float remained robots-disallowed, and JTA still lacked an enumerated feed.
All four incomplete sources checked WWR with zero matching listings and stayed
partial. The new Noesis fallback is regression-tested; this live run did not need
to invoke it. GitHub Checks passed all 96 tests at the same commit.

[Full GitHub validation 39689294359](https://github.com/corrida-repos/tiny-job-scraper/actions/runs/39689294359)
at code commit `40b89be` completed in 3m12s with **56/60 source scopes complete**
and the same four gaps. All 96 tests passed. The run used `send_email=false` and
`freshness_days=2`; no email was sent, and the production-state branch stayed at
`e7552fd7635e3f82ab4336fe1d09a1109ae6d7e9`. The 08:00 Europe/Lisbon daily workflow
remains active. Test-fixture stdout was subsequently captured to prevent fake
coverage warnings from appearing among live GitHub annotations; runtime code is
unchanged from the validated commit.
