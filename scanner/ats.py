"""Employer career-portal adapters (Section 3.2 Platform 3).

Each adapter uses the vendor's public JSON job feed. An adapter that fails, is
blocked or returns an unexpected shape is reported as a coverage gap, never as
zero vacancies.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .common import Budget, Http, clean_text, iso, now_utc, parse_iso, relative_bounds

INDIA = re.compile(
    r"india|mumbai|bengaluru|bangalore|pune|gurugram|gurgaon|delhi|noida|hyderabad|chennai|kolkata|"
    r"ahmedabad|gandhinagar|gift city|jaipur|kochi|coimbatore|indore|chandigarh|thane|powai|\bIN\b",
    re.I,
)
RELEVANT = re.compile(
    r"risk|credit|model|quant|ifrs|basel|\becl\b|cecl|ccar|scorecard|analytics|data scien|impairment|capital|stress",
    re.I,
)
WORKDAY_INDIA = "c4f78be1a8f14da0ab49ce1162348a5e"


def _row(company, title, location, url, job_id, platform, **extra):
    row = {"company": company, "title": title or "", "location": location or "", "url": url, "job_id": str(job_id), "platform": platform}
    row.update({k: v for k, v in extra.items() if v not in (None, "")})
    return row


def _day_bounds(date_text: str, seen: datetime):
    """A date-only ATS field: the posting happened sometime during that UTC day."""
    dt = parse_iso(date_text[:10]) if date_text else None
    if not dt:
        return None
    latest = min(seen, dt + timedelta(hours=24))
    return dt + (latest - dt) / 2, dt, latest, "day"


def workday(http: Http, emp: dict, cfg: dict, terms: list[str], settings: dict, budget: Budget):
    host, site = cfg["host"], cfg["site"]
    tenant = host.split(".")[0]
    root = f"https://{host}/wday/cxs/{tenant}/{site}"
    seen_paths, rows = {}, []
    india_only = cfg.get("india_only")
    facet_ok = not india_only
    for term in terms:
        for page in range(settings.get("max_pages", 2)):
            if budget.spent:
                return rows, "budget_exhausted"
            body = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term}
            if facet_ok:
                body["appliedFacets"] = {"locationCountry": [WORKDAY_INDIA]}
            resp = http.post(root + "/jobs", json=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
            if resp.status_code in (400, 422) and facet_ok:
                facet_ok = False  # this tenant names its country facet differently
                body["appliedFacets"] = {}
                resp = http.post(root + "/jobs", json=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
            if resp.status_code != 200:
                return rows, f"http_{resp.status_code}"
            data = resp.json()
            postings = data.get("jobPostings")
            if not isinstance(postings, list):
                return rows, "unexpected_response"
            def evidence(post):
                return bool(INDIA.search(post.get("locationsText") or "") or INDIA.search((post.get("externalPath") or "").replace("-", " ")))

            # Trust the country facet only when most of what came back visibly is in India;
            # some tenants ignore an unknown facet and return every country.
            facet_works = facet_ok and postings and sum(map(evidence, postings)) >= 0.6 * len(postings)
            for post in postings:
                path = post.get("externalPath") or ""
                if not path or path in seen_paths:
                    continue
                location = post.get("locationsText") or ""
                in_india = india_only or facet_works or evidence(post)
                seen_paths[path] = True
                if not in_india or not RELEVANT.search(post.get("title") or ""):
                    continue
                rows.append(
                    _row(emp["name"], post.get("title"), location if INDIA.search(location) else (location + ", India").strip(", "),
                         f"https://{host}/{site}{path}", (post.get("bulletFields") or [path.rsplit('_', 1)[-1]])[0],
                         "workday", posted_text=post.get("postedOn"), _detail=root + path)
                )
            if len(postings) < 20:
                break
    for row in rows[: settings.get("max_details_per_employer", 12)]:
        if budget.spent:
            break
        try:
            info = http.get(row["_detail"], headers={"Accept": "application/json"}).json().get("jobPostingInfo", {})
        except Exception:  # detail is an enrichment; the listing itself stands
            continue
        row["description"] = clean_text(info.get("jobDescription", ""))
        row["start_date"] = info.get("startDate")
        if info.get("externalUrl"):
            row["url"] = info["externalUrl"]
        if info.get("location") and INDIA.search(info["location"]):
            row["location"] = info["location"]
    for row in rows:
        row.pop("_detail", None)
    return rows, "ok"


def greenhouse(http: Http, emp: dict, cfg: dict, terms, settings, budget: Budget):
    resp = http.get(f"https://boards-api.greenhouse.io/v1/boards/{cfg['board']}/jobs", params={"content": "true"})
    if resp.status_code != 200:
        return [], f"http_{resp.status_code}"
    rows = []
    for job in resp.json().get("jobs", []):
        location = (job.get("location") or {}).get("name", "")
        offices = " ".join(o.get("name", "") + " " + (o.get("location") or "") for o in job.get("offices") or [])
        if not RELEVANT.search(job.get("title", "")) or not INDIA.search(location + " " + offices):
            continue
        rows.append(
            _row(emp["name"], job.get("title"), location, job.get("absolute_url"), job.get("id"), "greenhouse",
                 description=clean_text(clean_text(job.get("content", ""))),
                 posted_iso=job.get("first_published"), updated_iso=job.get("updated_at"))
        )
    return rows, "ok"


def lever(http: Http, emp: dict, cfg: dict, terms, settings, budget: Budget):
    resp = http.get(f"https://api.lever.co/v0/postings/{cfg['company']}", params={"mode": "json"})
    if resp.status_code != 200:
        return [], f"http_{resp.status_code}"
    rows = []
    for job in resp.json():
        cats = job.get("categories") or {}
        location = cats.get("location") or ""
        every = " ".join(cats.get("allLocations") or []) + " " + location + " " + (job.get("country") or "")
        if not RELEVANT.search(job.get("text", "")) or not INDIA.search(every):
            continue
        created = job.get("createdAt")
        rows.append(
            _row(emp["name"], job.get("text"), location, job.get("hostedUrl"), job.get("id"), "lever",
                 description=clean_text((job.get("descriptionPlain") or "") + "\n" + (job.get("additionalPlain") or "")
                                        + "\n" + " ".join(clean_text(l.get("content", "")) for l in job.get("lists") or [])),
                 posted_iso=iso(datetime.fromtimestamp(created / 1000, timezone.utc)) if created else None,
                 apply_url=job.get("applyUrl"))
        )
    return rows, "ok"


def smartrecruiters(http: Http, emp: dict, cfg: dict, terms, settings, budget: Budget):
    rows, seen = [], set()
    for term in terms[:3]:
        resp = http.get(f"https://api.smartrecruiters.com/v1/companies/{cfg['company']}/postings",
                        params={"country": "in", "q": term, "limit": 100})
        if resp.status_code != 200:
            return rows, f"http_{resp.status_code}"
        for job in resp.json().get("content", []):
            if job.get("id") in seen or not RELEVANT.search(job.get("name", "")):
                continue
            seen.add(job.get("id"))
            loc = job.get("location") or {}
            place = ", ".join(x for x in [loc.get("city"), loc.get("region"), "India"] if x)
            rows.append(_row(emp["name"], job.get("name"), place + (" (Remote)" if loc.get("remote") else ""),
                             f"https://jobs.smartrecruiters.com/{cfg['company']}/{job.get('id')}", job.get("id"),
                             "smartrecruiters", posted_iso=job.get("releasedDate")))
    return rows, "ok"


def oracle(http: Http, emp: dict, cfg: dict, terms, settings, budget: Budget):
    host, site = cfg["host"].rstrip("/"), cfg["site"]
    rows, seen = [], set()
    for term in terms:
        if budget.spent:
            return rows, "budget_exhausted"
        finder = f'findReqs;siteNumber={site},facetsList=LOCATIONS;POSTING_DATES,limit=25,keyword="{term}",sortBy=POSTING_DATES_DESC'
        if cfg.get("location_id"):
            finder += f",locationId={cfg['location_id']}"
        resp = http.get(f"{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                        params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder})
        if resp.status_code != 200:
            return rows, f"http_{resp.status_code}"
        items = resp.json().get("items") or []
        for req in (items[0].get("requisitionList") if items else []) or []:
            rid = str(req.get("Id"))
            location = req.get("PrimaryLocation") or ""
            country = req.get("PrimaryLocationCountry") or ""
            in_india = cfg.get("india_only") or cfg.get("location_id") or country == "IN" or INDIA.search(location)
            if rid in seen or not in_india or not RELEVANT.search(req.get("Title", "")):
                continue
            seen.add(rid)
            rows.append(_row(emp["name"], req.get("Title"), location or "India",
                             f"{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}", rid, "oracle",
                             posted_date=req.get("PostedDate"), description=clean_text(req.get("ShortDescriptionStr") or "")))
    return rows, "ok"


ADAPTERS = {"workday": workday, "greenhouse": greenhouse, "lever": lever, "smartrecruiters": smartrecruiters, "oracle": oracle}


def posted_from_row(row: dict, seen: datetime):
    """Best ATS posting estimate -> (posted_at, earliest, latest, precision) or None."""
    stamp = parse_iso(row.get("posted_iso"))
    if stamp:
        return stamp, stamp, stamp, "hour"
    if row.get("posted_date"):
        return _day_bounds(row["posted_date"], seen)
    bounds = relative_bounds(row.get("posted_text", ""))
    if bounds:
        low, high, precision = bounds
        mid = (low + high) / 2
        return seen - timedelta(hours=mid), seen - timedelta(hours=high), seen - timedelta(hours=low), precision
    if row.get("start_date"):
        return _day_bounds(row["start_date"], seen)
    stamp = parse_iso(row.get("updated_iso"))
    if stamp:
        return stamp, None, stamp, "updated"
    return None


def scan_employer(http: Http, emp: dict, terms: list[str], settings: dict, budget: Budget):
    cfg = emp.get("ats") or {}
    adapter = ADAPTERS.get(cfg.get("type"))
    if not adapter:
        return [], {"state": "no_adapter"}
    started = now_utc()
    try:
        rows, state = adapter(http, emp, cfg, terms, settings, budget)
    except Exception as exc:  # network, JSON shape, throttling: all are gaps
        return [], {"state": "error", "error": f"{type(exc).__name__}: {exc}"[:160]}
    return rows, {"state": state, "returned": len(rows), "seconds": round((now_utc() - started).total_seconds(), 1)}
