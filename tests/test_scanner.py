"""Offline tests: no network. Run with `python -m unittest discover -s tests`."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="crjs-test-")
os.environ["CRJS_DATA_DIR"] = os.path.join(_tmp, "data")
os.environ["CRJS_STATE_DIR"] = os.path.join(_tmp, "state")

from scanner import ats, common, linkedin, naukri, pipeline  # noqa: E402
from scanner.scoring import Scorer  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SCORING = common.load_json(common.CONFIG / "scoring.json")
LEGACY_EMPLOYERS = common.load_json(common.CONFIG / "employers.json")
ACTIVE_EMPLOYERS = common.load_json(common.CONFIG / "gcc_employers.json") or LEGACY_EMPLOYERS
SCORER = Scorer(SCORING, ACTIVE_EMPLOYERS)
T0 = datetime(2026, 11, 15, 7, 30, tzinfo=timezone.utc)

RICH = ("Develop IFRS 9 ECL credit risk models covering PD, LGD and EAD for retail and wholesale credit portfolios. Basel IRB model "
        "development and model validation, stress testing and scenario analysis for CCAR. Python, SAS, SQL, logistic "
        "regression, survival analysis, XGBoost, backtesting. " * 2)


def score(title, company, location="Mumbai, Maharashtra, India", age=5, **extra):
    return SCORER.score({"title": title, "company": company, "location": location, "assume_india": False, **extra}, age)


class TimeTests(unittest.TestCase):
    def test_relative_bounds(self):
        self.assertEqual(common.relative_bounds("3 hours ago"), (3.0, 4.0, "hour"))
        self.assertEqual(common.relative_bounds("Just now"), (0.0, 1.0, "hour"))
        self.assertEqual(common.relative_bounds("1 day ago"), (24.0, 48.0, "day"))
        self.assertEqual(common.relative_bounds("Posted Today"), (0.0, 24.0, "day"))
        self.assertEqual(common.relative_bounds("Posted Yesterday"), (24.0, 48.0, "day"))
        self.assertEqual(common.relative_bounds("Posted 30+ Days Ago")[2], "coarse")
        self.assertIsNone(common.relative_bounds("Actively hiring"))

    def test_window_tightens_day_precision(self):
        posted, earliest, latest, precision = common.posted_estimate(T0, common.relative_bounds("1 day ago"), 30)
        self.assertEqual(earliest, T0 - timedelta(hours=30))
        self.assertEqual(latest, T0 - timedelta(hours=24))
        self.assertEqual(posted, T0 - timedelta(hours=27))
        # a 72h query cannot tighten a "1 day ago" reading
        self.assertEqual(common.posted_estimate(T0, common.relative_bounds("1 day ago"), 72)[1], T0 - timedelta(hours=48))


class LinkedInTests(unittest.TestCase):
    def test_parse_cards(self):
        cards = linkedin.parse_cards((FIX / "linkedin_search.html").read_text())
        self.assertEqual([c["job_id"] for c in cards], ["4470000001", "4470000002"])
        first = cards[0]
        self.assertEqual(first["title"], "AVP - Credit Risk Modelling")
        self.assertEqual(first["company"], "Barclays")
        self.assertEqual(first["company_slug"], "barclays-bank")
        self.assertEqual(first["location"], "Noida, Uttar Pradesh, India")
        self.assertEqual(first["posted_text"], "3 hours ago")
        self.assertEqual(first["url"], "https://www.linkedin.com/jobs/view/4470000001")
        self.assertEqual(cards[1]["posted_text"], "1 day ago")

    def test_parse_detail(self):
        detail = linkedin.parse_detail((FIX / "linkedin_detail.html").read_text())
        self.assertIn("IFRS 9 ECL", detail["description"])
        self.assertEqual(detail["seniority_level"], "Mid-Senior level")
        self.assertEqual(detail["applicants_n"], 24)
        self.assertTrue(detail["reposted"])
        self.assertEqual(detail["apply_url"], "https://search.jobs.barclays/job/noida/avp/13015/1")

    def test_applicants(self):
        self.assertEqual(linkedin.parse_applicants("Over 200 applicants"), 201)
        self.assertEqual(linkedin.parse_applicants("37 applicants"), 37)

    def test_blocked_page_is_not_empty_result(self):
        self.assertTrue(linkedin.looks_blocked("<html><body class='authwall'>Sign in to LinkedIn</body></html>"))
        self.assertEqual(linkedin.parse_cards(""), [])

    def test_company_query_matches_master_prompt(self):
        kw = linkedin.company_keywords("Citi", ["credit risk", "IFRS 9"])
        self.assertEqual(kw, '"Citi" AND ("credit risk" OR "IFRS 9")')
        self.assertIn("f_TPR=r86400", linkedin.public_search_url(kw))


class ScoringTests(unittest.TestCase):
    def test_tier1_needs_core_title_senior_grade_and_evidence(self):
        job = score("AVP - Credit Risk Modelling", "Barclays", "Noida, Uttar Pradesh, India", description=RICH, applicants_n=10)
        self.assertGreaterEqual(job["score"]["total"], 90)
        self.assertEqual(job["band"], "Tier 1")
        self.assertEqual(job["employer_id"], "barclays")
        self.assertEqual(job["city"], "Delhi NCR")

    def test_senior_manager_caps_at_tier2(self):
        job = score("Senior Manager Credit Risk Analytics", "Genpact", description=RICH, applicants_n=10)
        self.assertEqual(job["band"], "Tier 2")
        self.assertLessEqual(job["score"]["total"], 89)

    def test_data_scientist_is_tier3_only_with_banking_context(self):
        self.assertEqual(score("Data Scientist", "Flipkart", "Bengaluru")["excluded"], "below_threshold")
        job = score("Data Scientist", "HDFC Bank", description=RICH)
        self.assertIsNone(job["excluded"])
        self.assertEqual(job["band"], "Tier 3")

    def test_exclusions(self):
        self.assertEqual(score("Operational Risk Manager", "HSBC", "Pune")["excluded"], "other_risk")
        self.assertEqual(score("Market Risk Quant VP", "Nomura")["excluded"], "other_risk")
        self.assertIsNone(score("Market and Credit Risk Quant, VP", "Morgan Stanley")["excluded"])
        self.assertEqual(score("Java Developer - Credit Risk Technology", "Citi", "Chennai")["excluded"], "engineering")
        self.assertEqual(score("Credit Risk Underwriting Manager", "Axis Bank")["excluded"], "operations")
        self.assertEqual(score("Credit Risk Intern", "Goldman Sachs")["excluded"], "junior")
        self.assertEqual(score("VP Credit Risk", "Citi", "London, United Kingdom")["excluded"], "non_india")
        self.assertEqual(score("Collections Executive", "Bajaj Finance Limited")["excluded"], "irrelevant")

    def test_market_risk_model_roles_are_not_credit_roles(self):
        self.assertEqual(score("Model validation - Market Risk", "MUFG")["excluded"], "other_risk")
        self.assertEqual(score("Lead Model Validation_Pricing Models", "MUFG")["excluded"], "other_risk")
        self.assertIsNone(score("Vice President, Model Risk Management", "Barclays", description=RICH)["excluded"])
        self.assertEqual(score("Head of APAC Asset & Liability Management Risk", "JPMorganChase")["excluded"], "other_risk")

    def test_adjacent_title_needs_credit_context_once_read(self):
        plain = "Build dashboards for the sales team and track pipeline conversion across regions. " * 5
        self.assertEqual(score("Director, Sales Analytics", "Barclays", description=plain)["excluded"], "no_credit_context")
        self.assertIsNone(score("Director, Analytics", "Barclays", description=RICH)["excluded"])

    def test_senior_risk_analyst_is_not_junior(self):
        self.assertEqual(score("Senior Risk Analyst - Model Validation", "Deutsche Bank")["score"]["seniority_label"], "Senior Analyst / Consultant")

    def test_junior_grades_only_at_top_tier_firms(self):
        self.assertEqual(score("Credit Risk Analyst", "Some Finance Pvt Ltd")["excluded"], "junior_grade")
        top = score("Credit Risk Analyst", "Goldman Sachs", "Bengaluru", description=RICH)
        self.assertIsNone(top["excluded"])
        self.assertEqual(top["band"], "Tier 3")

    def test_employer_aliases(self):
        # These assertions describe the legacy registry; the GCC registry has different aliases and IDs.
        legacy = Scorer(SCORING, LEGACY_EMPLOYERS)
        cases = {"JPMorganChase": "jpmorgan-chase", "Citi": "citi", "Citigroup": "citi", "KPMG India": "kpmg", "EY": "ey",
                 "PwC Acceleration Centers in India": "pwc", "Bajaj Finance Limited": "bajaj-finserv", "SMFG India Credit": "fullerton-india",
                 "S&P Global": "s-p-global-market-intelligence", "Moody's": "moody-s-analytics", "Accenture in India": "accenture",
                 "TD Securities": "td-bank", "Kotak Mahindra Bank": "kotak-mahindra-bank"}
        for name, expected in cases.items():
            hit = legacy.match_employer(name)
            self.assertEqual(hit and hit["id"], expected, name)
        for name in ("Citizens Bank", "Jupiter Wagons", "Credila", "Bain Capital", "ICICI Lombard", "HDFC Life", "Bajaj Auto"):
            self.assertIsNone(legacy.match_employer(name), name)

    def test_freshness_points_decay(self):
        self.assertGreater(SCORER.freshness(5, 10), SCORER.freshness(40, 10))
        self.assertGreater(SCORER.freshness(40, 10), SCORER.freshness(200, 500))


class AtsTests(unittest.TestCase):
    class FakeResp:
        def __init__(self, payload, status=200):
            self.payload, self.status_code = payload, status

        def json(self):
            return self.payload

    def test_workday_filters_india_and_relevance(self):
        listing = {"total": 3, "jobPostings": [
            {"title": "AVP Credit Risk Model Validation", "externalPath": "/job/Mumbai/AVP_R1", "locationsText": "Mumbai", "postedOn": "Posted Today", "bulletFields": ["R1"]},
            {"title": "Credit Risk Lead", "externalPath": "/job/London/Lead_R2", "locationsText": "London", "postedOn": "Posted Today", "bulletFields": ["R2"]},
            {"title": "Receptionist", "externalPath": "/job/Pune/Rec_R3", "locationsText": "Pune", "postedOn": "Posted Today", "bulletFields": ["R3"]}]}
        detail = {"jobPostingInfo": {"jobDescription": "<p>IFRS 9 ECL</p>", "startDate": "2026-11-15", "location": "Mumbai, India"}}

        class FakeHttp:
            requests = 0

            def post(self, url, **kw):
                # tenant rejects the country facet -> adapter must retry without it and filter itself
                if kw["json"]["appliedFacets"]:
                    return AtsTests.FakeResp({}, 400)
                return AtsTests.FakeResp(listing)

            def get(self, url, **kw):
                return AtsTests.FakeResp(detail)

        emp = {"name": "Deutsche Bank", "ats": {"type": "workday", "host": "db.wd3.myworkdayjobs.com", "site": "DBWebsite"}}
        rows, status = ats.scan_employer(FakeHttp(), emp, ["credit risk"], {"max_pages": 1}, common.Budget(60))
        self.assertEqual(status["state"], "ok")
        self.assertEqual([r["title"] for r in rows], ["AVP Credit Risk Model Validation"])
        self.assertEqual(rows[0]["url"], "https://db.wd3.myworkdayjobs.com/DBWebsite/job/Mumbai/AVP_R1")
        self.assertIn("IFRS 9 ECL", rows[0]["description"])
        self.assertEqual(ats.posted_from_row(rows[0], T0)[3], "day")

    def test_failed_portal_is_a_gap_not_zero(self):
        class Boom:
            def post(self, *a, **k):
                raise ConnectionError("dns")
        emp = {"name": "X", "ats": {"type": "workday", "host": "x.wd1.myworkdayjobs.com", "site": "X"}}
        rows, status = ats.scan_employer(Boom(), emp, ["credit risk"], {}, common.Budget(60))
        self.assertEqual((rows, status["state"]), ([], "error"))


class NaukriTests(unittest.TestCase):
    def test_search_url(self):
        self.assertEqual(naukri.search_url("credit risk avp", "mumbai", 10, ["25to50"]),
                         "https://www.naukri.com/credit-risk-avp-jobs-in-mumbai?k=credit%20risk%20avp&l=mumbai&experience=10&ctcFilter=25to50&jobAge=1")

    def test_captcha_is_reported_not_bypassed(self):
        class Resp:
            status_code, text = 406, '{"message":"recaptcha required"}'

        class FakeHttp:
            def get(self, *a, **k):
                return Resp()
        rows, status = naukri.canary(FakeHttp())
        self.assertEqual((rows, status["state"]), ([], "interaction_required"))


class PipelineTests(unittest.TestCase):
    """End-to-end with every network call replaced."""

    def setUp(self):
        # Isolate writes even when another test module imported scanner before this module.
        from scanner import digest
        self.path_patch = patch.multiple(pipeline, DATA=Path(_tmp) / "data", ARCHIVE=Path(_tmp) / "state" / "archive.json")
        self.digest_patch = patch.object(digest, "DATA", Path(_tmp) / "data")
        self.path_patch.start()
        self.digest_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.addCleanup(self.digest_patch.stop)
        self.orig = (linkedin.search, linkedin.fetch_detail, ats.scan_employer, naukri.canary, pipeline.now_utc, linkedin.resolve_company_ids)
        for name in ("data", "state"):
            folder = Path(_tmp) / name
            if folder.exists():
                for f in folder.iterdir():
                    f.unlink()

    def tearDown(self):
        (linkedin.search, linkedin.fetch_detail, ats.scan_employer, naukri.canary, pipeline.now_utc, linkedin.resolve_company_ids) = self.orig

    def run_scan(self, cards_by_query, ats_rows=None, argv=("--max-details", "20"), warm_cache=True):
        def fake_search(http, keywords, location, seconds, max_pages, budget, company_ids=None):
            haystack = keywords + " | " + " ".join(company_ids or [])
            for needle, cards in cards_by_query.items():
                if needle in haystack:
                    return [dict(c) for c in cards if c.get("_max_window", 0) <= 0 or seconds >= c["_max_window"] * 3600], {"state": "ok", "pages": 1, "returned": len(cards), "capped": False}
            return [], {"state": "ok", "pages": 1, "returned": 0, "capped": False}

        def fake_detail(http, job_id):
            return {"description": RICH, "applicants_text": "Be among the first 25 applicants", "applicants_n": 24, "apply_url": f"https://apply.example/{job_id}"}

        def fake_ats(http, emp, terms, settings, budget):
            if ats_rows and emp["id"] in ats_rows:
                return [dict(r) for r in ats_rows[emp["id"]]], {"state": "ok", "returned": len(ats_rows[emp["id"]])}
            return [], {"state": "error", "error": "offline"}

        linkedin.search, linkedin.fetch_detail, ats.scan_employer = fake_search, fake_detail, fake_ats
        # every employer resolves to a fake company id equal to its query term, except UBS (keyword fallback)
        linkedin.resolve_company_ids = lambda http, names, accept: [] if names[0] == "UBS" else [{"id": "id:" + names[0], "name": names[0]}]
        naukri.canary = lambda http: ([], {"state": "interaction_required"})
        sys.argv = ["pipeline", *argv]
        # Mocked portal scenarios need explicit portal targets, not the production source catalog.
        test_portals = {e["id"]: e["ats"] for e in LEGACY_EMPLOYERS["employers"]
                        if e["id"] in {"barclays", "deutsche-bank", "genpact"}}

        def fixture_load(path, default=None):
            if path == pipeline.ARCHIVE and warm_cache and not path.exists():
                return {"learned": {e["id"]: {"ids_rule": pipeline.IDS_RULE, "ids_at": common.iso(common.now_utc()),
                                     "linkedin_ids": [] if e["query"] == "UBS" else [{"id": "id:" + e["query"], "name": e["name"]}]}
                                    for e in ACTIVE_EMPLOYERS["employers"]}}
            if path.name == "gcc_listing_sources.json":
                return []
            if path.name == "gcc_employers.json":
                return {**ACTIVE_EMPLOYERS, "employers": [
                    {**e, "ats": test_portals.get(e["id"])} for e in ACTIVE_EMPLOYERS["employers"]
                ]}
            return common.load_json(path, default)

        with patch.object(pipeline, "load_json", side_effect=fixture_load):
            pipeline.main()
        data = Path(os.environ["CRJS_DATA_DIR"])
        return json.loads((data / "jobs.json").read_text())["jobs"], json.loads((data / "status.json").read_text())

    def card(self, job_id, title, company, location, posted, **extra):
        return {"job_id": job_id, "title": title, "company": company, "company_slug": company.lower().replace(" ", "-"), "location": location,
                "posted_text": posted, "posted_date": None, "badge": "", "url": f"https://www.linkedin.com/jobs/view/{job_id}", **extra}

    def test_dedup_across_queries_and_platforms(self):
        avp = self.card("1", "AVP - Credit Risk Modelling", "Barclays", "Noida, Uttar Pradesh, India", "3 hours ago")
        jobs, status = self.run_scan(
            {"id:Barclays": [avp], "IFRS9": [avp], "id:JPMorgan": [self.card("2", "Vice President, Model Validation", "JPMorganChase", "Mumbai Metropolitan Region", "14 hours ago")]},
            ats_rows={"barclays": [{"company": "Barclays", "title": "AVP – Credit Risk Modelling", "location": "Noida", "url": "https://search.jobs.barclays/x", "job_id": "R9", "platform": "workday", "posted_text": "Posted Today"}]},
        )
        by_title = {j["title"]: j for j in jobs}
        self.assertEqual(len(jobs), 2)
        barclays = by_title["AVP - Credit Risk Modelling"]
        self.assertEqual(barclays["platforms"], ["linkedin", "workday"])
        self.assertEqual(barclays["posted_source"], "linkedin")  # LinkedIn is the source of truth for time
        self.assertEqual(barclays["precision"], "hour")
        self.assertGreaterEqual(len([v for s in barclays["sources"] for v in s["via"]]), 3)
        self.assertEqual(barclays["band"], "Tier 1")
        self.assertEqual(barclays["apply_url"], "https://apply.example/1")
        self.assertEqual(status["state"], "complete")
        self.assertEqual(status["sources"]["naukri"]["state"], "interaction_required")
        self.assertEqual(status["ats"]["barclays"]["state"], "ok")
        self.assertEqual(status["ats"]["deutsche-bank"]["state"], "error")
        self.assertEqual([p["id"] for p in status["phases"]], [1, 2, "2b", 3, 4, 5, 6])

    def test_secondary_window_only_when_primary_is_thin(self):
        many = [self.card(str(100 + i), f"AVP Credit Risk Modelling {i}", "Barclays", "Pune, Maharashtra, India", "2 hours ago") for i in range(12)]
        jobs, status = self.run_scan({"id:Barclays": many})
        self.assertFalse(status["secondary_window_used"])
        self.assertEqual(status["funnel"]["qualified_primary"], 12)

    def test_rescan_keeps_first_reading_and_first_seen(self):
        card = self.card("7", "Director, IFRS 9 ECL", "KPMG India", "Mumbai, Maharashtra, India", "5 hours ago")
        first, _ = self.run_scan({"id:KPMG": [card]})
        second, _ = self.run_scan({"id:KPMG": [dict(card, posted_text="5 hours ago")]})
        self.assertEqual(first[0]["first_seen"], second[0]["first_seen"])
        self.assertEqual(len(second), 1)

    def test_company_filter_and_keyword_fallback(self):
        _, status = self.run_scan({})
        modes = {q["label"]: q["mode"] for q in status["queries"] if q["kind"] == "company" and q["window_hours"] == 30}
        self.assertEqual(modes["Barclays"], "company_filter")
        self.assertEqual(modes["UBS"], "keyword")
        barclays = next(q for q in status["queries"] if q["label"] == "Barclays")
        self.assertNotIn("Barclays", barclays["keywords"])  # the employer is constrained by id, not by keyword
        self.assertTrue(status["secondary_window_used"])

    def test_cold_cache_searches_before_throttled_id_refresh(self):
        order = []
        real_prepare = pipeline.Scan.run_linkedin

        def search(scan, *args):
            order.append("search")
            return real_prepare(scan, *args)

        real_main = pipeline.main

        def main():
            def blocked(*args):
                order.append("lookup")
                raise linkedin.Throttled("HTTP 429")
            linkedin.resolve_company_ids = blocked
            real_main()

        with patch.object(pipeline.Scan, "run_linkedin", search), patch.object(pipeline, "main", main):
            _, status = self.run_scan({}, warm_cache=False)
        phase = status["phases"][0]
        self.assertEqual(order, ["search", "search", "search", "lookup"])
        self.assertEqual(phase["attempted"], phase["queries"])
        self.assertEqual(phase["completed"], phase["queries"])
        self.assertEqual(phase["keyword_fallback"], phase["queries"])
        self.assertEqual(status["sources"]["linkedin"]["id_refresh"], {"attempted": 1, "refreshed": 0, "stopped": "HTTP 429"})

    def test_failed_search_is_attempted_but_not_completed(self):
        real_main = pipeline.main

        def main():
            linkedin.search = lambda *args: ([], {"state": "http_503", "pages": 1, "returned": 0})
            real_main()

        with patch.object(pipeline, "main", main):
            _, status = self.run_scan({}, argv=("--max-queries", "2", "--no-secondary"))
        phase = status["phases"][0]
        self.assertEqual((phase["attempted"], phase["completed"], phase["outcomes"]), (2, 0, {"http_503": 2}))

    def test_invalid_shard_ranges(self):
        for kind in ("employer", "skill"):
            for args in ([f"--{kind}-start", "-1"], [f"--{kind}-start", "2", f"--{kind}-end", "1"]):
                with self.subTest(args=args), patch.object(sys, "argv", ["pipeline", *args]), self.assertRaises(SystemExit) as err:
                    pipeline.main()
                self.assertEqual(err.exception.code, 2)

    def test_primary_shard_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shard-1.json"
            card = self.card("1", "VP Credit Risk Modeling", "Barclays", "Mumbai, India", "2 hours ago")
            with patch.object(sys, "argv", ["pipeline", "--employer-start", "1", "--employer-end", "2", "--skill-end", "1",
                                            "--linkedin-shard-out", str(path)]), patch.object(linkedin, "search", return_value=(
                    [card], {"state": "ok", "returned": 1})), patch.object(pipeline.Scan, "publish", side_effect=AssertionError), \
                    patch.object(naukri, "canary", side_effect=AssertionError):
                pipeline.main()
            data = json.loads(path.read_text())
            self.assertEqual(len(data["queries"]), 2)
            self.assertEqual(data["queries"][0]["id"], "C02")
            self.assertEqual(len(data["observations"]), 2)
            self.assertFalse(pipeline.ARCHIVE.exists())
            (Path(tmp) / "duplicate.json").write_bytes(path.read_bytes())
            with patch.object(pipeline.Scan, "run_linkedin", side_effect=AssertionError):
                jobs, status = self.run_scan({}, argv=("--linkedin-shards-in", tmp, "--no-secondary"))
            self.assertEqual(len(jobs), 1)
            self.assertEqual(status["funnel"]["observations"], 2)
            self.assertEqual(status["phases"][0]["completed"], 1)
            self.assertGreater(status["phases"][0]["outcomes"]["skipped_missing_shard"], 0)
            self.assertEqual(set(jobs[0]["sources"][0]["via"]), {q["id"] for q in data["queries"]})

    def test_generic_grade_title_is_classified_from_description(self):
        generic = self.card("55", "3562971-Manager", "EXL", "Gurugram, Haryana, India", "4 hours ago")
        offtopic = self.card("56", "Receptionist", "EXL", "Gurugram, Haryana, India", "4 hours ago")
        jobs, _ = self.run_scan({"id:EXL": [generic, offtopic]})
        self.assertEqual([j["title"] for j in jobs], ["3562971-Manager"])
        self.assertEqual(jobs[0]["score"]["role"], 30)
        self.assertIn("Generic grade title", jobs[0]["score"]["role_class"])
        # the same bare title from an untargeted skill search is not kept
        jobs, _ = self.run_scan({"IFRS9": [self.card("57", "Manager", "Unknown Co", "Pune", "2 hours ago")]})
        self.assertFalse([j for j in jobs if j["title"] == "Manager"])

    def test_slow_search_phases_do_not_use_up_the_description_allowance(self):
        import time
        real_clock, real_main, clock = time.monotonic, pipeline.main, [0.0]

        def main():
            fake = linkedin.search

            def costly(*a, **k):  # every search costs 20 minutes of clock time, far beyond the description allowance
                clock[0] += 1200
                return fake(*a, **k)
            linkedin.search = costly
            return real_main()
        time.monotonic, pipeline.main = (lambda: clock[0]), main
        try:
            avp = self.card("71", "AVP - Credit Risk Modelling", "Barclays", "Noida, Uttar Pradesh, India", "3 hours ago")
            jobs, status = self.run_scan({"id:Barclays": [avp]}, argv=("--max-details", "20", "--linkedin-minutes", "1000000"))
        finally:
            time.monotonic, pipeline.main = real_clock, real_main
        self.assertEqual(status["sources"]["linkedin"]["details"]["read"], 1)
        self.assertGreater(jobs[0]["score"]["skills"], 0)

    def test_rescore_keeps_the_scan_record(self):
        avp = self.card("81", "AVP - Credit Risk Modelling", "Barclays", "Noida, Uttar Pradesh, India", "3 hours ago")
        _, before = self.run_scan({"id:Barclays": [avp]})
        self.assertGreater(before["funnel"]["observations"], 0)
        before["sources"]["linkedin"].update(requests=195, aborted=True)
        common.save_json(pipeline.DATA / "status.json", before)
        sys.argv = ["pipeline", "--rescore"]
        pipeline.main()
        after = json.loads((Path(os.environ["CRJS_DATA_DIR"]) / "status.json").read_text())
        self.assertEqual(after["funnel"]["observations"], before["funnel"]["observations"])
        self.assertEqual(after["sources"]["linkedin"], before["sources"]["linkedin"])
        self.assertEqual(len(after["queries"]), len(before["queries"]))

    def test_recent_title_only_role_is_read_on_the_next_scan(self):
        avp = self.card("91", "AVP - Credit Risk Modelling", "Barclays", "Noida, Uttar Pradesh, India", "3 hours ago")
        jobs, _ = self.run_scan({"id:Barclays": [avp]}, argv=("--max-details", "0"))
        self.assertTrue(jobs[0]["score"]["title_only"])
        jobs, status = self.run_scan({})  # the listing is not returned again, but it is still recent
        self.assertFalse(jobs[0]["score"]["title_only"])
        self.assertEqual(status["sources"]["linkedin"]["details"]["read"], 1)

    def test_ats_only_role_is_flagged(self):
        jobs, _ = self.run_scan({}, ats_rows={"genpact": [{"company": "Genpact", "title": "Vice President - Credit Risk Modeling", "location": "Gurugram",
                                                         "url": "https://genpact.example/1", "job_id": "G1", "platform": "workday", "posted_text": "Posted Today", "description": RICH}]})
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0]["ats_only"])
        self.assertEqual(jobs[0]["precision"], "day")

    def test_newly_seen_old_or_undated_ats_jobs_are_not_fresh(self):
        rows = [{"company": "Genpact", "title": f"Vice President Credit Risk Modeling {i}",
                 "location": "Gurugram", "url": f"https://genpact.example/{i}", "job_id": f"OLD{i}",
                 "platform": "workday", "description": RICH, **stamp}
                for i, stamp in enumerate(({"posted_iso": "2020-01-01T00:00:00Z"}, {}))]
        _, status = self.run_scan({}, ats_rows={"genpact": rows})
        self.assertEqual(status["funnel"]["qualified_primary"], 0)
        self.assertEqual(status["funnel"]["qualified_secondary"], 0)
        digest = json.loads((Path(os.environ["CRJS_DATA_DIR"]) / "digest.json").read_text())
        self.assertEqual(digest["ids"], [])


if __name__ == "__main__":
    unittest.main()
