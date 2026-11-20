"""Offline coverage and timestamp tests for official vacancy indexes."""
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

BOARD = "https://example.com"
INDEX = BOARD + "/Example/siteMap.xml"
JOB = BOARD + "/Example/job/Bengaluru/Director-Credit-Risk_1"
OTHER = BOARD + "/Example/job/Pune/Receptionist_2"
SITEMAP = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>{JOB}</loc></url><url><loc>{OTHER}</loc></url></urlset>'


def response(body, code=200):
    return SimpleNamespace(status_code=code, text=body, content=body.encode())


class PublicListingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Import after discovery so test_scanner can install its temporary data/state paths.
        global ats, common
        from scanner import ats, common

    def run_adapter(self, routes, fmt="workday_sitemap", url=INDEX, budget=None):
        calls = []

        class FakeHttp:
            def get(self, url, **kwargs):
                calls.append(("GET", url))
                return routes[url]

            def post(self, url, **kwargs):
                calls.append(("POST", url))
                return routes[url]

        emp = {"name": "Example", "ats": {"type": "public_listings", "format": fmt, "url": url}}
        rows, status = ats.scan_employer(FakeHttp(), emp, [], {"max_details_per_employer": 12},
                                         budget if budget is not None else common.Budget(60))
        return rows, status, calls

    def test_reads_listings_and_uses_original_date(self):
        for published in ("2024-01-01", None, "2099-01-01"):
            with self.subTest(published=published):
                job = {"@type": "JobPosting", "title": "Director Credit Risk", "datePosted": published,
                       "dateModified": "2026-11-19", "jobLocation": {"address": {"addressCountry": "IN", "addressLocality": "Bengaluru"}}}
                detail = f'<script type="application/ld+json">{json.dumps(job)}</script>'
                rows, status, calls = self.run_adapter({BOARD + "/robots.txt": response("User-agent: *"),
                                                        INDEX: response(SITEMAP), JOB: response(detail)})
                self.assertEqual((status["state"], status["india_observed"], status["returned"]), ("ok", 2, 1))
                self.assertNotIn(("GET", OTHER), calls)
                estimate = ats.posted_from_row(rows[0], datetime(2026, 11, 20, tzinfo=timezone.utc))
                self.assertEqual(estimate[0].year if estimate else None, 2024 if published == "2024-01-01" else None)

    def test_valid_empty_index_is_not_a_block_or_bad_payload(self):
        for body, code, expected in [("<urlset/>", 200, "ok"), ("<html>Sign in</html>", 200, "error"), ("", 403, "blocked")]:
            with self.subTest(expected=expected):
                _, status, _ = self.run_adapter({BOARD + "/robots.txt": response("", 404), INDEX: response(body, code)})
                self.assertEqual(status["state"], expected)
                self.assertEqual(status["india_observed"], 0 if expected == "ok" else None)

    def test_robots_and_expired_budget_prevent_requests(self):
        _, status, calls = self.run_adapter({BOARD + "/robots.txt": response("User-agent: *\nDisallow: /Example/")})
        self.assertEqual((status["state"], calls), ("blocked", [("GET", BOARD + "/robots.txt")]))
        _, status, calls = self.run_adapter({}, budget=common.Budget(0))
        self.assertEqual((status["state"], calls), ("budget_exhausted", []))

    def test_voya_reads_vacancies_without_guessing_dates(self):
        endpoint = BOARD + "/wp-admin/admin-ajax.php"
        table = '''<table class="jobtable"><tr><th>Req ID</th><th>Title</th><th>Location</th></tr>
                <tr><td>12</td><td><a href="/career-inner-page/12/">VP Credit Risk</a></td><td>India</td></tr></table>'''
        rows, status, calls = self.run_adapter({BOARD + "/robots.txt": response("", 404), endpoint: response(table)},
                                               fmt="voya_india", url=endpoint)
        self.assertEqual(calls[-1], ("POST", endpoint))
        self.assertEqual((status["state"], status["india_observed"], rows[0]["job_id"]), ("ok", 1, "12"))
        self.assertIsNone(ats.posted_from_row(rows[0], common.now_utc()))

    def test_featured_vacancies_are_always_partial_coverage(self):
        cards = f'''<div class="job-list__content"><a class="job-list__job-link" href="{JOB}">VP Credit Risk</a>
                 <span class="job-desc-location">India</span></div>'''
        job = {"@type": "JobPosting", "title": "VP Credit Risk", "datePosted": "2024-01-01",
               "jobLocation": {"address": {"addressCountry": "India"}}}
        rows, status, _ = self.run_adapter({BOARD + "/robots.txt": response("", 404), INDEX: response(cards),
                                            JOB: response(f'<script type="application/ld+json">{json.dumps(job)}</script>')},
                                           fmt="featured_cards")
        self.assertEqual((len(rows), status["state"], status["listings_read"]), (1, "capped", True))

    def test_sitemap_of_100_is_a_gap_even_with_no_india_urls(self):
        urls = ''.join(f'<url><loc>{BOARD}/Example/job/London/Risk_{i}</loc></url>' for i in range(100))
        _, status, _ = self.run_adapter({BOARD + "/robots.txt": response("", 404), INDEX: response(f'<urlset>{urls}</urlset>')})
        self.assertEqual((status["state"], status["india_observed"]), ("capped", 0))