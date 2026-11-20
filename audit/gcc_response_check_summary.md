# Limited response check — 20 November 2026

## Scope

The existing GCC registry has 200 entries, all without an ATS adapter. These are
not 200 verified new additions. Only five additional employers are configured
as listing sources. No employer/config/scoring/schedule changes were made for
this check.

## Existing 200-entry registry

Run: 01:58:21–01:59:42 UTC (81 seconds). Six workers, six-second request timeout,
zero retries, per-host pacing, robots policy checked before a careers-page HEAD
request. Redirects were recorded, not followed. No captcha/authentication bypass.

| Result | Entries |
|---|---:|
| Careers page returned HTTP 2xx to HEAD | 56 |
| Redirect recorded; destination not tested | 59 |
| Could not establish robots policy | 37 |
| Network or timeout failure | 17 |
| Other HTTP error | 16 |
| Declared crawl rate requires review | 9 |
| Blocked or rate limited | 5 |
| Robots disallowed the page | 1 |
| **Total** | **200** |

Every entry returned `no_adapter` from scanner dispatch. No listings were read
for these 200 entries; India-opening and passed-filter counts are unknown, NOT
zero. HEAD 2xx does not establish real vacancy coverage or valid GCC evidence.
Policy failures can include redirects/errors on robots.txt; they are not proof
that the careers page itself is unavailable.

Detailed per-employer report: `gcc_200_response_check.json`.

## Five configured additional listing sources

Separate 30-second-budget pilot, completed 01:55:50–01:55:54 UTC in four seconds.
Same scanner ATS, merge, scoring and digest path, temporary state only.

| Employer | State | India openings observed in index | Passed 30h / 72h |
|---|---|---:|---:|
| Lloyds Banking Group | ok | 44 | 0 / 0 |
| Sun Life Financial | capped sitemap | 0 | 0 / 0 |
| Synchrony Financial | featured subset | 7 | 0 / 0 |
| Ameriprise Financial | capped sitemap | 22 | 0 / 0 |
| Voya Financial | ok | 143 | 0 / 0 |

All five listing indexes responded. Only two had no reported index gap; three
remain capped. Sun Life's zero is for its 100-entry subset, not all India jobs.
Voya supplied no job publication dates. No configured pilot source was blocked
or unsupported. Detailed report: `gcc_pilot_response_check.json`.

## Validation

- 37 offline tests passed.
- Production dashboard files and archive hashes remained identical before and
  after both live checks and tests (see `response_check_baseline.json`).
- No recommendations published, no commit/push, no schedule change.
- This does not complete or validate a 200-new-employer expansion; 195 verified
  additions are still missing.