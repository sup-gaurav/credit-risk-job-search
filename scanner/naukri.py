"""Naukri.com (Section 3.2 Platform 2).

Naukri's search endpoint demands an interactive reCAPTCHA for automated clients.
The scanner sends one canary request per run, records the outcome and never tries
to bypass the check. The dashboard supplies one-click 'Posted today' searches for
every employer and skill query instead.
"""
from __future__ import annotations

from urllib.parse import quote

from .common import Http, relative_bounds

API = "https://www.naukri.com/jobapi/v3/search"


def search_url(k: str, l: str | None = None, experience: int | None = None, ctc=None, job_age: int = 1) -> str:
    slug = "-".join(k.lower().replace("&", "and").replace("'", "").split()) + "-jobs"
    if l:
        slug += "-in-" + "-".join(l.lower().split())
    url = f"https://www.naukri.com/{quote(slug)}?k={quote(k)}"
    if l:
        url += f"&l={quote(l)}"
    if experience is not None:
        url += f"&experience={experience}"
    for band in ctc or []:
        url += f"&ctcFilter={band}"
    return url + f"&jobAge={job_age}"


def canary(http: Http, keyword="credit risk"):
    """Try one search. Returns (rows, status)."""
    try:
        resp = http.get(
            API,
            params={"noOfResults": 50, "urlType": "search_by_keyword", "searchType": "adv", "keyword": keyword,
                    "k": keyword, "pageNo": 1, "jobAge": 1, "seoKey": "credit-risk-jobs", "src": "jobsearchDesk"},
            headers={"appid": "109", "systemid": "Naukri", "Accept": "application/json"},
            retries=0,
        )
    except Exception as exc:
        return [], {"state": "error", "error": str(exc)[:120]}
    text = resp.text[:400].lower()
    if resp.status_code != 200 or "recaptcha" in text or "captcha" in text:
        return [], {"state": "interaction_required", "http": resp.status_code,
                    "note": "Naukri requires an interactive check for automated search; use the launcher links"}
    try:
        jobs = resp.json().get("jobDetails") or []
    except ValueError:
        return [], {"state": "unexpected_response", "http": resp.status_code}
    rows = []
    for job in jobs:
        place = next((p.get("label") for p in job.get("placeholders") or [] if p.get("type") == "location"), "")
        link = job.get("jdURL") or ""
        rows.append({
            "platform": "naukri", "job_id": str(job.get("jobId")), "title": job.get("title", ""),
            "company": job.get("companyName", ""), "location": place,
            "url": link if link.startswith("http") else "https://www.naukri.com" + link,
            "posted_text": job.get("footerPlaceholderLabel", ""), "description": job.get("jobDescription", ""),
            "_bounds": relative_bounds(job.get("footerPlaceholderLabel", "")),
        })
    return rows, {"state": "ok", "returned": len(rows)}
