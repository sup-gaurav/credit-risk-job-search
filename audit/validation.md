# Validation and limitations

## Live pilot

Run: `python -m scanner.pilot --output audit/gcc_pilot.json`.
Latest saved run: 20 November 2026, 01:43:27–01:43:31 UTC.
This exercised the scheduled scanner's ATS selection, adapters, merge, scoring,
and digest generation with disposable state. LinkedIn and Naukri were not run.

| New parent | India openings observed in index | Relevant rows read | Passed 30h / 72h filters | Coverage |
|---|---:|---:|---:|---|
| Lloyds Banking Group | 44 | 1 | 0 / 0 | Sitemap read; no reported index cap |
| Sun Life Financial | 0 | 0 | 0 / 0 | Capped global sitemap (100 entries); not evidence of zero India vacancies |
| Synchrony Financial | 7 | 3 | 0 / 0 | Featured subset only |
| Ameriprise Financial | 22 | 2 | 0 / 0 | Capped global sitemap (100 entries) |
| Voya Financial | 143 | 0 | 0 / 0 | Public vacancy table read; no posting dates supplied |

These are observed counts, not an India vacancy census. Workday sitemap location
text can miss additional locations; candidate descriptions are subject to the
existing 12-detail limit. A result marked `ok` means its configured index was read,
not that every job worldwide has been enumerated. The production ATS budget and
workflow timeout are unchanged. Capacity for 200 additional sources is unproven.

Totals: 5 parents verified and configured, 5 indexes successfully read, 2 without
reported index gaps, 3 capped, 0 blocked/unsupported configured sources. Lowe's
and NatWest were blocked during research and were not counted or configured.
The shortfall from 200 verified/configured new parents is 195. Batch expansion
is paused; five distinct recruiting vendors and complete listings coverage have
not been demonstrated.

## Recommendation regression

A saved-archive replay with the clock fixed to 19 November 2026 18:13 UTC gave
identical outputs before and after the scanner integration changes:

- `jobs.json` SHA-256: `bb1d3100c573fe10d55a6768e42402c83604659ee4c97c5c856476dd6873bf77`
- `digest.json` SHA-256: `c295637a64eaaa1b0bdaa302f6c76a7b963927767faf1c617d02e0addc775226`

No scorer, digest selection, freshness window, threshold, employer-scoring
registry, ranking or deduplication changes were made. The five new sources are
discovery-only, so their names do not gain new target-employer points. Their
real job rows can still be scored by the existing rules.

Offline suite: `python -m unittest discover -s tests` — **37 tests passed**.
The three initial failures were fixture/config mismatches: legacy aliases are
now tested against the legacy registry, and mocked ATS scenarios explicitly
supply their three test portal targets. Production employer aliases were not
changed to satisfy these tests. New tests cover blocking, robots restrictions,
budget exhaustion, empty versus malformed responses, capped indexes, original
publication dates, future/unknown dates, and old/newly discovered jobs staying
out of the fresh digest. Local Python: 3.14.5; workflow uses 3.12, not executed
locally here. No new dependencies.

Dashboard `nextRun()` was executed in headless Edge for the four-hour cron:
before 00:30, exactly 00:30, and after the last run of the day; all three passed.
`git diff --check` passed. No commit, push or remote workflow dispatch.

## Data recovery disclosure

During validation, early module import order caused one offline test run to use
production data paths and write mocked results. This was found and fixed with
explicit per-test path patching (in addition to delayed scanner imports).
The affected local files were backed up at:

`C:\Users\GAURAV~1\AppData\Local\Temp\crjs-before-recovery-lhaua3im`

Clean recommendations, config and a clean archived-state replay from the
pre-test snapshot were restored. The recovered jobs and digest have the hashes
above and contain no mocked `apply.example` jobs. The original run-status metadata
was not separately snapshotted: `site/data/status.json` is replay-derived, not an
exact restoration of the original coverage record. Archive compaction/replay
history metadata can differ from the original bytes. A fresh real scan is needed
to refresh source-status metadata. User source/config edits and the original
200-row GCC registry remain in place. This limitation must not be described as
perfect byte-for-byte preservation of all uncommitted generated files.