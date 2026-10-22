# Job requirement diagnostic

Historical diagnostic: these counts used the strict verified-original-date gate
in effect during the scan. The user subsequently enabled labelled **Unknown
freshness** and **Future-dated** potential matches; those reporting exceptions
are not reflected in the exclusion counts below.

Run: 2026-10-22T09:05:51.070488+00:00. Coverage: 54/56 source scopes complete.
Evaluated candidates: 226. Reportable before location deduplication: 0. Included roles: 0.
Settings: 48-hour verified original freshness; up to 3 nearby office days/week; potential matches included.

| Requirement | Hard failures | Missing evidence | Blocks reporting | Only reporting blocker |
| --- | ---: | ---: | ---: | ---: |
| Original posting within 48 hours | 113 | 104 | 217 | 114 |
| Mandatory experience limit | 59 | 19 | 59 | 5 |
| Portugal hiring eligibility | 58 | 116 | 58 | 0 |
| International travel cap | 12 | 214 | 12 | 0 |
| Mandatory coding / coding assessment | 11 | 11 | 11 | 0 |
| Mandatory languages | 5 | 11 | 5 | 0 |
| Expired application deadline | 3 | 0 | 3 | 0 |
| Office attendance / hybrid arrangement | 2 | 196 | 2 | 0 |
| Residence / relocation restriction | 2 | 0 | 2 | 1 |
| Shift / on-call / weekend requirements | 1 | 11 | 1 | 0 |
| Full job description | 0 | 11 | 0 | 0 |

Evaluated allowed-title candidates only; title preselection and source-unretrieved jobs are not ranked.
Counts overlap because one candidate can fail multiple requirements. Only-reporting-blocker counts have no other current report gate.
Removing one gate is a diagnostic count, not an eligibility recommendation or a change to saved rules.

Missing evidence blocks reporting for original freshness and unavailable Greenhouse application requirements. Other unknown checks can remain potential matches under the current settings.

This diagnostic used a disposable production-state copy; no email was sent and production state was not changed.

## Freshness breakdown

- older_than_window: 113
- unverified_original_date: 103
- verified_within_window: 9
- date_only_or_other_uncertainty: 1

## Method and correction

This diagnostic ran in the cloud workspace using a disposable copy of encrypted
production state at `de26ab3e259092f834b802ef9a11bc2346cd0a97`. Retrieval used code
commit `5bfb322`. The same 226 retrieved candidates were then re-screened at the
original run-start timestamp using corrected screening code `36b575a`; the saved
criteria were not changed. Current settings include a five-year mandatory
experience limit and three nearby hybrid office days per week.

The diagnostic exposed 34 false residence exclusions caused by conditional salary
wording, conditional export-control wording, and a numeric UTC work-hours range.
Those cases were fixed and regression-tested before this final ranking. The
Salsify role explicitly requiring Lisbon residence remains excluded. All 116
unit tests passed locally and in GitHub Checks.

Source coverage was 54/56: OLX had unavailable candidate details and Infineon's
inventory changed during pagination. These retrieval limitations are separate
from the job requirements ranked above. Jobs not retrieved or removed by the
initial title-family preselection cannot be quantified by this diagnostic.

The biggest blocker is original publication freshness: 113 candidates are older
than 48 hours and 104 lack sufficient date evidence. Of the latter, 103 have no
verified original date and one has insufficient date-only evidence. Only nine
candidates pass freshness; all nine fail at least one other hard requirement.
Freshness is the only reporting blocker for 114 candidates, but they may still
have unconfirmed requirements and would be potential matches rather than verified
eligible roles. A wider date window alone does not resolve missing original dates.

Counts overlap; each candidate may fail more than one requirement. The five
experience-only blocked candidates are candidate records before location
variant deduplication, not necessarily five distinct job opportunities. No
eligibility settings were relaxed, no email was sent, and production state was
not modified.
