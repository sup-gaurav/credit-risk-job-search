"""Source diagnostics: compares LinkedIn query forms so the scan uses the one that
actually constrains results. Run from GitHub Actions (workflow: Source diagnostics)."""
from __future__ import annotations

import json
import re
import sys

from . import linkedin
from .common import CONFIG, Budget, Http, Throttled, load_json
from .scoring import Scorer

scorer = Scorer(load_json(CONFIG / "scoring.json"), load_json(CONFIG / "gcc_employers.json") or load_json(CONFIG / "employers.json"))
http = Http(min_gap=1.8, max_gap=3.0)
OR_TERMS = '"credit risk" OR "risk analytics" OR "risk modeling" OR "IFRS 9" OR "Basel" OR "model risk" OR "model validation"'


def run(label, params, employer_id=None, pages=2):
    cards, start = [], 0
    try:
        for _ in range(pages):
            resp = http.get(linkedin.SEARCH_API, params={**params, "start": start})
            if resp.status_code != 200:
                print(f"  {label}: HTTP {resp.status_code}")
                break
            page = linkedin.parse_cards(resp.text)
            if not page:
                break
            cards += page
            start += len(page)
    except Throttled as exc:
        print(f"  {label}: throttled {exc}")
    emp_hits = sum(1 for c in cards if employer_id and (scorer.match_employer(c["company"]) or {}).get("id") == employer_id)
    relevant = sum(1 for c in cards if scorer.role_fit(c["title"])[0] in ("core", "strong"))
    print(f"  {label}: {len(cards)} cards, employer match {emp_hits}, core/strong titles {relevant}")
    for c in cards[:5]:
        print(f"      {c['title'][:60]} | {c['company'][:28]} | {c['posted_text']}")
    return cards


def typeahead(name):
    out = []
    for url, params in (
        ("https://www.linkedin.com/jobs-guest/api/typeaheadHits", {"typeaheadType": "COMPANY", "query": name}),
        ("https://www.linkedin.com/jobs-guest/api/typeaheadHits", {"origin": "jserp", "typeaheadType": "COMPANY", "query": name}),
    ):
        try:
            resp = http.get(url, params=params)
            out.append((resp.status_code, resp.text[:300].replace("\n", " ")))
            if resp.status_code == 200 and resp.text.strip().startswith("["):
                return json.loads(resp.text), out
        except Exception as exc:
            out.append(("err", str(exc)[:100]))
    return None, out


def company_page_id(slug):
    try:
        resp = http.get(f"https://www.linkedin.com/company/{slug}")
        ids = re.findall(r"f_C=(\d+)|urn:li:(?:organization|company):(\d+)|companyId[\"=:]+(\d+)", resp.text)
        flat = [x for t in ids for x in t if x]
        return resp.status_code, len(resp.text), sorted(set(flat), key=flat.count, reverse=True)[:3]
    except Exception as exc:
        return "err", 0, [str(exc)[:80]]


def main():
    week = "r604800"
    targets = [("JPMorgan", "jpmorgan-chase", "jpmorganchase"), ("Barclays", "barclays", "barclays-bank"), ("EXL", "exl-service", "exl-service"), ("Genpact", "genpact", "genpact")]
    ids = {}
    print("== company typeahead")
    for name, emp_id, slug in targets:
        hits, trace = typeahead(name)
        print(" ", name, "->", json.dumps(hits)[:400] if hits else trace)
        if hits:
            first = hits[0]
            ids[emp_id] = str(first.get("id") or first.get("entityId") or "")
    print("== company page ids")
    for name, emp_id, slug in targets[:2]:
        print(" ", slug, company_page_id(slug))
    print("== company query forms (7 days, India)")
    for name, emp_id, slug in targets:
        print(name)
        base = {"location": "India", "f_TPR": week}
        run("boolean DD", {**base, "keywords": linkedin.company_keywords(name, ["credit risk", "risk analytics", "risk modeling", "IFRS 9", "Basel", "model risk", "model validation"]), "sortBy": "DD"}, emp_id)
        run("boolean R ", {**base, "keywords": linkedin.company_keywords(name, ["credit risk", "risk analytics", "risk modeling", "IFRS 9", "Basel", "model risk", "model validation"]), "sortBy": "R"}, emp_id)
        run("plain R   ", {**base, "keywords": f"{name} credit risk", "sortBy": "R"}, emp_id)
        if ids.get(emp_id):
            run("f_C + credit risk DD", {**base, "keywords": "credit risk", "f_C": ids[emp_id], "sortBy": "DD"}, emp_id)
            run("f_C + OR terms DD   ", {**base, "keywords": OR_TERMS, "f_C": ids[emp_id], "sortBy": "DD"}, emp_id)
            run("f_C + risk DD       ", {**base, "keywords": "risk", "f_C": ids[emp_id], "sortBy": "DD"}, emp_id, pages=3)
    print("== skill query forms (30h, India)")
    for label, kw in (("IFRS 9", '"IFRS 9" OR IFRS9'), ("model development + credit", '"model development" AND credit'), ("credit risk", '"credit risk"'), ("credit risk modeling", "credit risk modeling")):
        print(label)
        for sort in ("DD", "R"):
            run(f"sort {sort}", {"location": "India", "f_TPR": "r108000", "keywords": kw, "sortBy": sort}, pages=3)
        run("title-ish R + levels", {"location": "India", "f_TPR": "r108000", "keywords": kw, "sortBy": "R", "f_E": "4,5,6"}, pages=2)
    print("requests", http.requests)


if __name__ == "__main__":
    sys.exit(main())
