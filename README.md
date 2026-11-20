# Credit Risk Job Search System v1.0

A free, self-refreshing dashboard for senior credit risk modeling roles in India. A GitHub Actions workflow runs the search every four hours and on demand, scores every role, and publishes a static dashboard on GitHub Pages. No paid API, server or AI model is involved in a refresh.

**Dashboard:** https://sup-gaurav.github.io/credit-risk-job-search/

## What it does

Each scan follows the six phases of the master prompt.

| Phase | What runs | Source |
| --- | --- | --- |
| 1 | One query per target employer, restricted to that employer with LinkedIn's company filter: `"credit risk" OR "risk analytics" OR "risk modeling" OR "IFRS 9" OR "Basel" OR "model risk" OR "model validation"`, India, last 30 hours, up to 3 pages. Company ids are looked up once and cached for 30 days; an employer LinkedIn cannot identify falls back to `"<Company>" AND (...)` as a keyword match | LinkedIn public job search |
| 2 | The 15 skill queries (core credit risk, technical skills, functional areas), India, last 30 hours, up to 8 pages | LinkedIn public job search |
| 2b | Phases 1 and 2 again over 72 hours, only when fewer than 10 roles cleared the threshold in 30 hours after their descriptions were read | LinkedIn public job search |
| 3 | One probe. Naukri asks automated clients for an interactive check, so the scanner records that and stops; the dashboard provides one-click "posted today" searches instead | Naukri.com |
| 4 | Public job feeds for employers that expose one, searched for credit risk terms and filtered to India | Workday, Oracle HCM, Greenhouse, Lever, SmartRecruiters |
| 5 | Cross-platform deduplication on employer + normalised title + city; LinkedIn is the source of truth for posting time. Descriptions, applicant counts and apply links are read for the most promising unread roles | LinkedIn job pages |
| 6 | Scoring, tiering, top-10 digest, publication | — |

Failed, capped, rate-limited or blocked sources are recorded as coverage gaps and shown on the Coverage tab. They are never reported as zero vacancies.

## Dashboard

- **Shortlist** — KPIs, the top 10 to apply to, and every scored role with filters for posting window (30h, 72h, 7 days, all), tier, employer category, city, platform, target employers and verified-fresh roles. Each role opens a panel with its score breakdown, freshness evidence, matched keywords and source links. Saved, Applied and Skip marks are stored in the browser. CSV export.
- **Employers** — all 95 entries in the target universe by category and tier, with roles found in 30h and 72h, career-portal feed status, and one-click LinkedIn (past 24 hours), Naukri (posted today) and careers-page searches.
- **Search launcher** — the 15 LinkedIn skill queries with last-scan results, Naukri advanced searches, and the weekly and monthly manual platforms (iimjobs, eFinancialCareers, Instahyre, Wellfound, Cutshort) with due reminders.
- **Coverage** — phase timings, per-query and per-portal outcomes, and run history.
- **Logic** — the scoring formula, bands, keyword lists, exclusions and time-window rules, rendered from the same config the scanner used.

## Refreshing

| How | Steps |
| --- | --- |
| Automatic | Every four hours at 00:30, 04:30, 08:30, 12:30, 16:30 and 20:30 UTC (02:00, 06:00, 10:00, 14:00, 18:00 and 22:00 IST). No open browser is required. GitHub may start scheduled runs late. |
| Dashboard, no setup | Refresh → Open scan request → press Create on GitHub. The workflow runs only for issues opened by the repository owner with a title starting `[SCAN]`, and closes the issue with the top-10 when it finishes. |
| Dashboard, one click | Refresh → paste a fine-grained personal access token limited to this repository with **Actions: Read and write**. It is stored only in that browser. |
| GitHub | Actions → Credit risk job scan → Run workflow. |

A scan takes roughly 15 to 40 minutes. The dashboard shows "Scan running" and reloads itself when the run completes.

After each scheduled scan the workflow opens a GitHub issue with the top 10 and direct apply links, which GitHub emails to the repository owner. Set the repository variable `DIGEST_ISSUE` to `off` to stop it.

## GCC portal pilot (partial expansion)

Five additional parent companies are configured separately in
`config/gcc_listing_sources.json`. The scheduled scanner reads these sources in
its existing ATS phase. They are not added to the scoring registry or LinkedIn
queries; India, freshness, deduplication, score, ranking and digest rules remain
unchanged. The requested 200-addition expansion is **not complete**: the pilot has
three capped sources, so expansion is paused. See `audit/gcc_employers.md` for
public evidence and `audit/gcc_pilot.json` for live coverage counts.

Re-run only portal discovery and the recommendation path with temporary state:

```sh
python -m scanner.pilot --output audit/gcc_pilot.json
```

The pilot does not call LinkedIn or Naukri, and does not overwrite dashboard or
archive files. Its India counts are observations from the specified index, not
a guarantee of total vacancies. A missing date stays unknown; first seen and
page update timestamps are never substituted for job publication dates by the
new adapters. Capped, blocked, unsupported and failed sources are coverage gaps.

The four-hour schedule takes effect only after the workflow is published on the
repository's default branch and Actions is enabled. No commit or push is done
by this local task.

## Scoring formula

```
FINAL_SCORE = min(cap, role fit (0-35) + skills match (0-25) + employer tier (0-15)
                       + seniority (0-10) + location (0-5) + freshness (0-10))
```

| Band | Score |
| --- | --- |
| Tier 1 | 90-100 |
| Tier 2 | 75-89 |
| Tier 3 | 60-74 |
| Filtered out | below 60 |

- **Role fit** comes from the title: core credit-risk modeling titles 35, credit risk and risk analytics titles 30, adjacent analytical titles 20 (27 when the description names three or more core credit-risk terms).
- **Skills match** counts core terms (IFRS 9, ECL, PD, LGD, EAD, Basel, CCAR, CECL, IRB, stress testing, model validation and others), techniques and stack in the description.
- **Generic titles**: some employers post bare grades ("Manager", "Assistant Vice President"). When one comes back from an employer-restricted credit-risk search, its description is read and it is kept only if it names "credit risk" and at least four core terms.
- **Seniority** also sets a cap so grades land in the bands the master prompt assigns: only VP, AVP and Director titles can reach Tier 1; Senior Manager and Manager cap at Tier 2; Senior Analyst caps at Tier 3 outside tier-1 banks.
- **Freshness** is recalculated in the browser, so a score drifts down as a listing ages.
- **Exclusions**: interns and trainees; operational, market, fraud and other non-credit risk; software engineering and delivery roles without modeling; collections, recovery and underwriting operations; locations outside India; Analyst and Associate grades below the top-tier firms.

The master prompt's Section 3.4 formula was cut off after "FINA", so these weights are an implementation of the tier, exclusion, geography and freshness rules it does state. Everything is in [`config/scoring.json`](config/scoring.json); change it and push, and the dashboard re-scores stored roles without searching again.

## Freshness rules

- Primary window: last 30 hours. Secondary window: 72 hours, used only as a volume supplement.
- "Verified fresh" = inside 30 hours and found on two or more platforms, or a single-platform timestamp under 12 hours.
- A role seen only on an employer portal is flagged "Portal date · verify", because portal dates are often stale.
- LinkedIn's "1 day ago" covers 24 to 48 hours; a listing returned by the 30-hour filter is placed between 24 and 30 hours.
- Roles are kept for 14 days after they were last seen.

## Repository layout

```
config/employers.json   95 employers: category, tier, aliases, LinkedIn query term, careers URL, job-feed adapter
config/search.json      LinkedIn queries, portal search terms, Naukri and manual-platform launch links, schedule
config/scoring.json     weights, bands, keyword lists, exclusions, time windows
scanner/                linkedin.py, ats.py, naukri.py, scoring.py, pipeline.py, digest.py
site/                   static dashboard (index.html, app.js, styles.css) and published data
state/archive.json      roles seen in the last 14 days, used for deduplication and first-seen times
tests/                  offline tests; no test touches the network
.github/workflows/      scan.yml (search + publish), pages.yml (publish only, on code or config change)
```

## Changing things

- **Add or edit an employer**: edit `config/employers.json`. `aliases` decide which company names map to it; `query` is the term used in the LinkedIn company search; `ats` selects a job-feed adapter (`workday`, `oracle`, `greenhouse`, `lever`, `smartrecruiters`).
- **Change a query**: edit `config/search.json`.
- **Change weights, keywords or windows**: edit `config/scoring.json`.
- **Change the schedule**: edit the cron line in `.github/workflows/scan.yml` (UTC) and `schedule` in `config/search.json` (display only).

Run locally:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests        # offline
python -m scanner.pipeline --rescore        # re-apply scoring, no network
python -m scanner.pipeline --max-queries 5  # small live smoke test
python -m scanner.pipeline                  # full scan
python -m http.server --directory site      # view the dashboard
```

## Limits

- Sources are read logged-out with polite pacing. LinkedIn rate-limits shared runner addresses at times; the scanner backs off, then stops and reports the gap rather than retrying aggressively. No login, proxy or CAPTCHA bypass is used.
- LinkedIn's logged-out search matches keywords loosely, so skill searches return many unrelated listings; titles with no credit, risk or analytics signal are discarded before scoring.
- Career-portal feeds are configured for the employers whose public job feed answered the first scan. Others (for example Goldman Sachs, HSBC, UBS, the Indian private banks) are reached through LinkedIn and the careers links only.
- Naukri, iimjobs, eFinancialCareers, Instahyre, Wellfound and Cutshort are launch links, not automated sources.
- Scores are rule-based points, not a résumé match, and a listing may close after it is scanned.
- The repository and its job data are public, which GitHub Pages requires on the free plan. It holds no résumé, credentials or application history.
