"""Build a SYNTHETIC dataset for local UI checks. Never published: every employer
listing here is invented. Usage: python tests/make_demo.py /tmp/demo-site"""
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
out = Path(sys.argv[1])
shutil.rmtree(out, ignore_errors=True)
shutil.copytree(ROOT / "site", out)
os.environ["CRJS_DATA_DIR"] = str(out / "data")
os.environ["CRJS_STATE_DIR"] = str(out / "_state")
sys.path.insert(0, str(ROOT))
from scanner import ats, linkedin, naukri, pipeline  # noqa: E402

random.seed(7)
RICH = ("Develop IFRS 9 ECL models covering PD, LGD and EAD for retail and wholesale credit portfolios. Basel IRB model "
        "development and model validation, stress testing and scenario analysis for CCAR. Python, SAS, SQL, logistic "
        "regression, survival analysis, XGBoost, backtesting, champion-challenger frameworks.\n" * 3)
THIN = "Work with the risk team on portfolio reporting. Python and SQL required. Credit risk exposure preferred."
ROLES = [
    ("AVP - Credit Risk Modelling (IFRS 9)", "Barclays", "Noida, Uttar Pradesh, India", "3 hours ago", RICH),
    ("Vice President, Model Validation - Wholesale Credit", "JPMorganChase", "Mumbai Metropolitan Region", "7 hours ago", RICH),
    ("Director - Credit Risk Strategy", "HSBC", "Bengaluru, Karnataka, India", "11 hours ago", RICH),
    ("VP - Stress Testing & Scenario Analysis", "Citi", "Pune, Maharashtra, India", "16 hours ago", RICH),
    ("Senior Manager - Credit Risk Analytics", "Genpact", "Gurugram, Haryana, India", "2 hours ago", RICH),
    ("Lead Data Scientist - Credit Risk", "PhonePe", "Bengaluru, Karnataka, India", "20 hours ago", RICH),
    ("Manager - Model Risk Management", "Deloitte", "Hyderabad, Telangana, India", "1 day ago", RICH),
    ("AVP Quantitative Risk Analytics", "Deutsche Bank", "Mumbai, Maharashtra, India", "1 day ago", RICH),
    ("Senior Consultant - FSRM Credit Risk", "EY", "Kolkata, West Bengal, India", "5 hours ago", THIN),
    ("Director, IFRS 9 ECL Modelling", "KPMG India", "Mumbai, Maharashtra, India", "9 hours ago", RICH),
    ("Data Scientist - Lending", "CRED", "Bengaluru, Karnataka, India", "13 hours ago", RICH),
    ("Assistant Vice President - Retail Credit Risk Scorecards", "HDFC Bank", "Mumbai, Maharashtra, India", "2 days ago", RICH),
    ("Credit Risk Analyst", "Goldman Sachs", "Bengaluru, Karnataka, India", "6 hours ago", RICH),
    ("Operational Risk Manager", "Wells Fargo", "Hyderabad, Telangana, India", "4 hours ago", THIN),
    ("Java Developer - Credit Risk Technology", "Morgan Stanley", "Mumbai, Maharashtra, India", "8 hours ago", THIN),
    ("Credit Risk Underwriting Manager", "Axis Bank", "Chennai, Tamil Nadu, India", "10 hours ago", THIN),
    ("Principal Data Scientist, Credit Decisioning", "Experian", "Hyderabad, Telangana, India", "2 days ago", RICH),
    ("VP Portfolio Risk Management", "Standard Chartered", "Chennai, Tamil Nadu, India", "1 day ago", ""),
    ("Risk Analytics Manager", "A Very Long Employer Name Financial Services Private Limited", "Ahmedabad, Gujarat, India", "15 hours ago", THIN),
    ("Senior Manager Basel Regulatory Capital Reporting and RWA Optimisation - Wholesale Banking", "ICICI Bank", "Mumbai, Maharashtra, India", "18 hours ago", RICH),
]


def card(i, r):
    return {"job_id": str(9000 + i), "title": r[0], "company": r[1], "company_slug": r[1].lower().replace(" ", "-"), "location": r[2],
            "posted_text": r[3], "posted_date": None, "badge": "Be an early applicant" if i % 3 == 0 else "",
            "url": f"https://www.linkedin.com/jobs/view/{9000 + i}"}


CARDS = [card(i, r) for i, r in enumerate(ROLES)]
DESC = {c["job_id"]: ROLES[i][4] for i, c in enumerate(CARDS)}


def fake_search(http, keywords, location, seconds, max_pages, budget):
    if "IFRS9" in keywords or '"credit risk" AND AVP' in keywords:
        cards = [c for c in CARDS if "day" not in c["posted_text"] or seconds > 108000 or c["posted_text"].startswith("1 day")]
        return [dict(c) for c in cards], {"state": "ok", "pages": 2, "returned": len(cards), "capped": False}
    if '"UBS"' in keywords:
        raise linkedin.Throttled("HTTP 429")
    return [], {"state": "ok", "pages": 1, "returned": 0, "capped": False}


def fake_detail(http, job_id):
    desc = DESC.get(str(job_id), "")
    n = random.choice([8, 24, 61, 140, 201])
    return {"description": desc, "applicants_n": n, "applicants_text": "Be among the first 25 applicants" if n <= 24 else "Over 200 applicants" if n > 200 else f"{n} applicants",
            "seniority_level": "Mid-Senior level", "employment_type": "Full-time", "apply_url": f"https://careers.example.com/job/{job_id}"}


def fake_ats(http, emp, terms, settings, budget):
    if emp["id"] == "barclays":
        return [{"company": "Barclays", "title": "AVP – Credit Risk Modelling (IFRS 9)", "location": "Noida", "url": "https://search.jobs.barclays/demo", "job_id": "R1", "platform": "workday", "posted_text": "Posted Today"}], {"state": "ok", "returned": 1}
    if emp["id"] == "genpact":
        return [{"company": "Genpact", "title": "Vice President - Credit Risk Modeling", "location": "Gurugram", "url": "https://genpact.example/demo", "job_id": "G1", "platform": "workday", "posted_text": "Posted Today", "description": RICH}], {"state": "ok", "returned": 1}
    if emp["ats"].get("verified"):
        return [], {"state": "ok", "returned": 0}
    return [], {"state": "http_404"} if emp["n"] % 2 else {"state": "error", "error": "ConnectionError: demo"}


linkedin.search, linkedin.fetch_detail, ats.scan_employer = fake_search, fake_detail, fake_ats
linkedin.ThrottleGuard.__init__.__defaults__ = ((0, 0), 0, 3)
naukri.canary = lambda http: ([], {"state": "interaction_required", "http": 406})
os.environ["SCAN_TRIGGER"] = "demo"
sys.argv = ["pipeline", "--max-details", "40"]
if len(sys.argv) and "--empty" in sys.argv[1:]:
    pass
pipeline.main()
print("demo written to", out)
