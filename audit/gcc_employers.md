# GCC expansion audit — pilot, not a completed 200-employer expansion

Public sources reviewed during this task (19–20 November 2026 UTC).
The original 200-row `config/gcc_employers.json` is preserved, not re-certified and
not counted as 200 additions. Five new parents are configured in
`config/gcc_listing_sources.json`. This discovery-only registry is deliberately
not passed to the scorer or LinkedIn query builder: otherwise adding names or
aliases can change scores and deduplication for the same inputs.

## Accepted pilot parents and evidence

### Lloyds Banking Group — United Kingdom
- India in-house evidence and official careers page: https://www.lloydstechnologycentre.com/
  states: “a tech and data company located in Hyderabad, India” and “part of
  Lloyds Banking Group”; its specialists deliver outcomes for the group's customers.
- Foreign parent evidence: https://find-and-update.company-information.service.gov.uk/company/SC095000
  identifies Lloyds Banking Group plc and its Edinburgh registered office.
- The centre's “Search and apply” link points to
  https://lbg.wd3.myworkdayjobs.com/Lloyds_Technology_Centre .
- The portal's robots.txt advertises the vacancy sitemap used by the adapter:
  https://lbg.wd3.myworkdayjobs.com/Lloyds_Technology_Centre/siteMap.xml .
- Credit-search relevance: banking technology/data; no claim that every India job is credit risk.

### Sun Life Financial — Canada
- India evidence: https://www.sunlife.com/slgs/en/ describes 20 years of India
  operations; https://www.sunlife.com/slgs/en/careers/ explicitly describes
  technology, business operations and knowledge-services support to Sun Life's global businesses.
- Foreign headquarters evidence: https://www.sunlife.com/en/about-us/
  explicitly identifies its “Global headquarters in Toronto”.
- Official careers “Join us” link:
  https://sunlife.wd3.myworkdayjobs.com/Experienced-Jobs .
- Advertised sitemap: https://sunlife.wd3.myworkdayjobs.com/Experienced-Jobs/siteMap.xml .
- Relevance: insurance, asset management, financial analytics. The 100-entry global
  sitemap is capped coverage; zero India URLs in that subset does NOT mean no India vacancies.

### Synchrony Financial — United States
- India evidence and employer careers portal:
  https://www.synchronycareers.com/About-Us-India describes over 5,600 colleagues
  across Synchrony global teams, including credit decision-making, analytics,
  technology and operations, with Hyderabad and other India hubs.
- Foreign corporate office: https://investors.synchrony.com/ lists Synchrony
  Financial, 777 Long Ridge Road, Stamford, Connecticut, United States.
- Adapter reads the actual vacancy cards on the India page and their individual
  JobPosting metadata, NOT just the page headline.
- Relevance: consumer credit and risk analytics. The page is a featured subset,
  not the complete board. robots.txt disallows `/search-jobs/`; no restricted
  search endpoint is used to circumvent this limit.

### Ameriprise Financial — United States
- India in-house and careers evidence:
  https://www.ameriprise.com/careers/india-jobs explicitly identifies Ameriprise
  India LLP as a 100%-owned subsidiary and says its employees support business
  segments and staff groups. This is not inferred from a sales-office address.
- Foreign corporate address: Organization JSON-LD on
  https://www.ameriprise.com/customer-service identifies Ameriprise Financial,
  901 3rd Avenue South, Minneapolis, Minnesota, US.
- Official India careers page exposes “Search and apply” to
  https://ameriprise.wd5.myworkdayjobs.com/Ameriprise .
- Advertised sitemap: https://ameriprise.wd5.myworkdayjobs.com/Ameriprise/siteMap.xml .
- Relevance: investment, wealth and financial-risk analytics. Sitemap returns 100
  jobs and is reported capped, not complete.

### Voya Financial — United States
- India evidence: https://www.voyaindia.com/ explicitly calls Voya India the
  strategic Global Capability Center for Voya Financial.
- https://www.voyaindia.com/career-inner-page/36480/ states the India entity has
  been wholly owned by Voya Financial since August 2023 and supports its
  Retirement, Employee Benefits and Investment Management businesses.
- Foreign parent: Organization JSON-LD on https://www.voya.com/ identifies
  Voya Financial as an American company with address 200 Park Ave, New York, US.
- Official careers page: https://www.voyaindia.com/career/ . Its own page script
  makes a public POST to https://www.voyaindia.com/wp-admin/admin-ajax.php with
  `action=fetch_job_listings`, empty `search` and `location`. The adapter uses
  that exact published request and reads the vacancy table and job links.
- Relevance: financial services and enterprise risk. The table has no job posting
  dates. Generic WebPage publication/modification dates are deliberately NOT used
  as vacancy dates. No undated role can enter the freshness-based digest from this source alone.

## Research not counted

- Target, Tesco, Walmart, PepsiCo and Best Buy already appear in the original
  registry, sometimes under a finance/GCC display name. They are not new parents.
- Lowe's India: https://www.lowes.co.in/ provides in-house/global-service evidence
  through the public web retrieval service, but the local runner received HTTP 403.
  Not configured or counted as an accepted pilot source.
- NatWest careers https://jobs.natwestgroup.com/pages/india returned a challenge/403.
  Not configured or counted; no bypass attempted.
- General Mills has an employer-linked Workday board, but reviewed pages did not
  establish sufficiently specific India in-house GCC evidence. Not counted.
- Other exploratory links returning 404, redirecting to generic homepages, or
  showing private authentication were rejected as evidence, not turned into invented endpoints.

## Expansion gate

Five accepted parents, five configured, five listing indexes read in the pilot;
two without a reported index gap, three capped, zero blocked/unsupported among
configured sources. Two additional research sites were blocked/challenged; those
are NOT included in configured-source totals. No batch expansion yet: the pilot
does not establish complete coverage across five different recruiting vendors.
It exercises Workday, Synchrony's employer portal, and Voya's own vacancy table.
The verified/configured shortfall from the requested 200 additions is **195**.
Do not present this as a completed 200-employer implementation.