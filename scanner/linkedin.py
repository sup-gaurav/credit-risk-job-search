"""LinkedIn public (logged-out) job search: Methods A (company) and B (skill)."""
from __future__ import annotations

import re
import time
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from bs4 import BeautifulSoup

from .common import Budget, Http, Throttled, clean_text, relative_bounds

SEARCH_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/"
PUBLIC_SEARCH = "https://www.linkedin.com/jobs/search/"
TYPEAHEAD_API = "https://www.linkedin.com/jobs-guest/api/typeaheadHits"


def or_terms(skill_terms: list[str]) -> str:
    return " OR ".join(f'"{t}"' for t in skill_terms)


def resolve_company_ids(http: Http, names: list[str], accept) -> list[dict]:
    """Look up LinkedIn company ids so a search can be restricted to one employer.

    LinkedIn's logged-out search treats a company name inside the keywords loosely
    and returns other employers; the company filter (f_C) is exact. `accept(name)`
    decides whether a suggested company really is this employer.
    """
    found, seen = [], set()
    for name in names:
        resp = http.get(TYPEAHEAD_API, params={"typeaheadType": "COMPANY", "query": name}, retries=0)
        if resp.status_code != 200:
            raise ConnectionError(f"company lookup: HTTP {resp.status_code}")
        try:
            hits = resp.json()
        except ValueError as exc:
            raise ConnectionError("company lookup: expected JSON") from exc
        if not isinstance(hits, list):
            raise ConnectionError("company lookup: expected a list")
        for hit in hits:
            cid, label = str(hit.get("id") or ""), hit.get("displayName") or ""
            if cid.isdigit() and cid not in seen and accept(label):
                seen.add(cid)
                found.append({"id": cid, "name": label})
        if found:
            break
    return found[:5]


def company_keywords(term: str, skill_terms: list[str]) -> str:
    """Section 3.2 Method A: [Company] + ("Credit Risk" OR "Risk Analytics" OR ...)."""
    ors = " OR ".join(f'"{t}"' for t in skill_terms)
    return f'"{term}" AND ({ors})'


def public_search_url(keywords: str, location: str = "India", seconds: int = 86400, levels: str = "4,5", company_ids=None) -> str:
    params = {"keywords": keywords, "location": location, "f_TPR": f"r{seconds}", "sortBy": "DD"}
    if company_ids:
        params["f_C"] = ",".join(company_ids)
    if levels:
        params["f_E"] = levels
    return PUBLIC_SEARCH + "?" + urlencode(params, quote_via=quote)


def parse_cards(markup: str) -> list[dict]:
    soup = BeautifulSoup(markup or "", "html.parser")
    cards = []
    for node in soup.select("[data-entity-urn]"):
        urn = node.get("data-entity-urn", "")
        match = re.search(r"jobPosting:(\d+)", urn)
        if not match:
            continue
        job_id = match.group(1)
        title = node.select_one(".base-search-card__title")
        company = node.select_one(".base-search-card__subtitle")
        company_link = node.select_one(".base-search-card__subtitle a")
        location = node.select_one(".job-search-card__location")
        when = node.select_one("time")
        benefit = node.select_one(".job-posting-benefits__text")
        slug = None
        if company_link and company_link.get("href"):
            found = re.search(r"/company/([^/?#]+)", company_link["href"])
            slug = found.group(1) if found else None
        cards.append(
            {
                "job_id": job_id,
                "title": title.get_text(" ", strip=True) if title else "",
                "company": company.get_text(" ", strip=True) if company else "",
                "company_slug": slug,
                "location": location.get_text(" ", strip=True) if location else "",
                "posted_text": when.get_text(" ", strip=True) if when else "",
                "posted_date": when.get("datetime") if when else None,
                "badge": benefit.get_text(" ", strip=True) if benefit else "",
                "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            }
        )
    return cards


def looks_blocked(markup: str) -> bool:
    low = (markup or "")[:6000].lower()
    return "authwall" in low or "sign in to linkedin" in low or "captcha" in low


def search(http: Http, keywords: str, location: str, seconds: int, max_pages: int, budget: Budget, company_ids=None):
    """Run one query. Returns (cards, status) where status records coverage honestly."""
    cards, seen, pages = [], set(), 0
    status = {"state": "ok", "pages": 0, "returned": 0, "capped": False}
    start = 0
    while pages < max_pages:
        if budget.spent:
            status["state"] = "budget_exhausted"
            break
        params = {"keywords": keywords, "location": location, "f_TPR": f"r{seconds}", "sortBy": "DD", "start": start}
        if company_ids:
            params["f_C"] = ",".join(company_ids)
        resp = http.get(SEARCH_API, params=params)
        pages += 1
        if resp.status_code == 400 and start > 0:
            break  # LinkedIn answers 400 past the last page
        if resp.status_code != 200:
            status["state"] = f"http_{resp.status_code}"
            break
        if looks_blocked(resp.text):
            raise Throttled("login wall")
        page = [c for c in parse_cards(resp.text) if c["job_id"] not in seen]
        if not page:
            break
        for card in page:
            seen.add(card["job_id"])
        cards.extend(page)
        start += len(page)
        if pages == max_pages:
            status["capped"] = True
    status["pages"], status["returned"] = pages, len(cards)
    return cards, status


def parse_applicants(text: str):
    if not text:
        return None
    low = text.lower()
    number = re.search(r"(\d[\d,]*)", low)
    if not number:
        return None
    value = int(number.group(1).replace(",", ""))
    if "first" in low or "among" in low:
        return max(0, value - 1)
    if "over" in low or "+" in low:
        return value + 1
    return value


def parse_detail(markup: str) -> dict:
    soup = BeautifulSoup(markup or "", "html.parser")
    out: dict = {}
    body = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    if body:
        out["description"] = clean_text(str(body))
    for item in soup.select(".description__job-criteria-item"):
        head = item.select_one(".description__job-criteria-subheader")
        value = item.select_one(".description__job-criteria-text")
        if head and value:
            key = head.get_text(" ", strip=True).lower()
            text = value.get_text(" ", strip=True)
            if "seniority" in key:
                out["seniority_level"] = text
            elif "employment" in key:
                out["employment_type"] = text
            elif "function" in key:
                out["job_function"] = text
            elif "industr" in key:
                out["industries"] = text
    applicants = soup.select_one(".num-applicants__caption")
    if applicants:
        out["applicants_text"] = applicants.get_text(" ", strip=True)
        out["applicants_n"] = parse_applicants(out["applicants_text"])
    posted = soup.select_one(".posted-time-ago__text")
    if posted:
        out["posted_text"] = posted.get_text(" ", strip=True)
        out["reposted"] = "repost" in out["posted_text"].lower()
    code = soup.select_one("code#applyUrl")
    if code:
        raw = code.decode_contents()
        found = re.search(r'https?://[^"\s<>-][^"\s<>]*', raw)
        if found:
            link = found.group(0).replace("&amp;", "&")
            query = parse_qs(urlparse(link).query)
            out["apply_url"] = unquote(query["url"][0]) if query.get("url") else link
    if soup.select_one(".closed-job") or "no longer accepting applications" in soup.get_text(" ", strip=True).lower()[:4000]:
        out["closed"] = True
    return out


def fetch_detail(http: Http, job_id: str) -> dict:
    resp = http.get(DETAIL_API + str(job_id))
    if resp.status_code == 404:
        return {"closed": True}
    if resp.status_code != 200:
        return {}
    if looks_blocked(resp.text):
        raise Throttled("login wall")
    return parse_detail(resp.text)


class ThrottleGuard:
    """Back off when LinkedIn rate limits; stop the phase rather than hammer it."""

    def __init__(self, waits=(25, 75), cooloff=150, max_strikes=3):
        self.waits, self.cooloff, self.max_strikes = waits, cooloff, max_strikes
        self.strikes = 0
        self.cooled = False
        self.aborted = False
        self.events = 0

    def run(self, fn, budget: Budget):
        """Call fn(); returns its value or None when the call stayed throttled."""
        if self.aborted:
            return None
        for wait in (0,) + tuple(self.waits):
            if wait:
                if budget.left < wait + 5:
                    break
                time.sleep(wait)
            try:
                value = fn()
                self.strikes = 0
                return value
            except Throttled:
                self.events += 1
        self.strikes += 1
        if self.strikes >= self.max_strikes:
            if self.cooled or budget.left < self.cooloff + 30:
                self.aborted = True
            else:
                self.cooled = True
                self.strikes = 0
                time.sleep(self.cooloff)
        return None


def card_bounds(card: dict):
    return relative_bounds(card.get("posted_text", ""))
