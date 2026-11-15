"""Daily scan orchestration: the six phases of Section 3.3.

  1 LinkedIn company scans     4 Career-portal (ATS) checks
  2 LinkedIn skill searches    5 Deduplication, enrichment and ranking
  3 Naukri.com                 6 Scoring, top-10 digest and publication
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from . import ats, linkedin, naukri
from .common import (CONFIG, DATA, STATE, Budget, Http, age_hours, iso, load_json, norm_company, norm_title,
                     now_utc, parse_iso, posted_estimate, save_json, stable_id)
from .scoring import Scorer

PRECISION_RANK = {"hour": 3, "day": 2, "coarse": 1, "updated": 0, None: -1}
ARCHIVE = STATE / "archive.json"


class Scan:
    def __init__(self, args):
        self.args = args
        self.employers = load_json(CONFIG / "employers.json")
        self.scoring = load_json(CONFIG / "scoring.json")
        self.search = load_json(CONFIG / "search.json")
        self.scorer = Scorer(self.scoring, self.employers)
        self.archive = load_json(ARCHIVE, {}) or {}
        self.archive.setdefault("jobs", {})
        self.archive.setdefault("sources", {})
        self.archive.setdefault("learned", {})
        self.archive.setdefault("history", [])
        self.started = now_utc()
        self.phases, self.queries, self.ats_status = [], [], {}
        self.observations = []
        self.sources = {}
        self.funnel = {}
        self.windows = self.scoring["windows"]
        self.li_http = Http(min_gap=float(os.environ.get("LI_MIN_GAP", 1.6)), max_gap=float(os.environ.get("LI_MAX_GAP", 3.2)))
        self.guard = linkedin.ThrottleGuard()
        self.secondary_used = False

    # ------------------------------------------------------------ helpers
    def phase(self, number, name):
        entry = {"id": number, "name": name, "state": "running", "started": iso(now_utc())}
        self.phases.append(entry)
        entry["_t"] = time.monotonic()
        print(f"\n== Phase {number}: {name}", flush=True)
        return entry

    def close(self, entry, state, **detail):
        entry["state"] = state
        entry["seconds"] = round(time.monotonic() - entry.pop("_t"), 1)
        entry.update(detail)
        print(f"   -> {state} in {entry['seconds']}s {detail}", flush=True)

    def observe(self, row, seen_at, estimate, via, window=None, assume_india=False):
        self.observations.append({**row, "seen_at": seen_at, "estimate": estimate, "via": via, "window": window, "assume_india": assume_india})

    # ------------------------------------------------------------ LinkedIn
    def linkedin_queries(self):
        li = self.search["linkedin"]
        company, skill = [], []
        for emp in self.employers["employers"]:
            if emp.get("same_as"):
                continue
            company.append({"id": f"C{emp['n']:02d}", "kind": "company", "label": emp["name"], "employer_id": emp["id"],
                            "keywords": linkedin.company_keywords(emp["query"], li["company_terms"]),
                            "location": "India", "max_pages": li["max_pages_company"]})
        for q in li["skill_queries"]:
            for index, location in enumerate(q.get("locations") or ["India"]):
                skill.append({"id": q["id"] + (chr(97 + index) if q.get("locations") else ""), "kind": "skill", "label": q["label"],
                              "set": q["set"], "keywords": q["keywords"], "location": location, "max_pages": li["max_pages_skill"]})
        if self.args.max_queries:
            company, skill = company[: self.args.max_queries], skill[: max(1, self.args.max_queries // 3)]
        return company, skill

    def run_linkedin(self, queries, hours, budget):
        seconds, done = int(hours * 3600), 0
        for q in queries:
            record = {k: q[k] for k in ("id", "kind", "label", "keywords", "location") if k in q}
            record.update(employer_id=q.get("employer_id"), set=q.get("set"), window_hours=hours)
            if self.guard.aborted or budget.spent:
                record.update(state="skipped_throttled" if self.guard.aborted else "skipped_budget", returned=0)
                self.queries.append(record)
                continue
            seen_at = now_utc()
            result = self.guard.run(lambda q=q: linkedin.search(self.li_http, q["keywords"], q["location"], seconds, q["max_pages"], budget), budget)
            if result is None:
                record.update(state="throttled", returned=0)
            else:
                cards, status = result
                record.update(status)
                for card in cards:
                    estimate = posted_estimate(seen_at, linkedin.card_bounds(card), hours)
                    self.observe({**card, "platform": "linkedin"}, seen_at, estimate, q["id"], window=hours, assume_india=True)
                done += 1
            self.queries.append(record)
            print(f"   {record['id']} {record['label'][:34]:34} {hours}h -> {record.get('state')} {record.get('returned', 0)}", flush=True)
        return done

    def qualified_in_window(self, hours):
        """Distinct roles from this run that clear the threshold on title evidence."""
        seen = set()
        for obs in self.observations:
            est = obs["estimate"]
            age = age_hours(est[0], obs["seen_at"]) if est else None
            if age is None or age > hours:
                continue
            probe = self.scorer.score({"title": obs["title"], "company": obs["company"], "location": obs["location"],
                                        "assume_india": obs["assume_india"]}, age)
            if probe["score"] and not probe["excluded"]:
                seen.add((norm_company(obs["company"]), norm_title(obs["title"]), probe["city"]))
        return len(seen)

    # ------------------------------------------------------------ ATS
    def run_ats(self, budget):
        targets = [e for e in self.employers["employers"] if e.get("ats") and not e.get("same_as")]
        if self.args.max_queries:
            targets = targets[: self.args.max_queries]
        settings, terms = self.search["ats"], self.search["ats"]["search_terms"]

        def work(emp):
            http = Http(min_gap=0.5, max_gap=1.1, timeout=20)
            seen_at = now_utc()
            rows, status = ats.scan_employer(http, emp, terms, settings, budget)
            return emp, rows, status, seen_at, http.requests

        with ThreadPoolExecutor(max_workers=10) as pool:
            for emp, rows, status, seen_at, requests_made in pool.map(work, targets):
                status.update(type=emp["ats"]["type"], requests=requests_made, previously_verified=bool(emp["ats"].get("verified")))
                self.ats_status[emp["id"]] = status
                key = "ats:" + emp["id"]
                src = self.archive["sources"].setdefault(key, {})
                if status["state"] == "ok":
                    src.setdefault("first_ok", iso(seen_at))
                    src["last_ok"] = iso(seen_at)
                for row in rows:
                    self.observe(row, seen_at, ats.posted_from_row(row, seen_at), key, assume_india=True)
                print(f"   {emp['name'][:30]:30} {emp['ats']['type']:15} {status['state']} {status.get('returned', '')} {status.get('error', '')}", flush=True)

    # ------------------------------------------------------------ merge
    def merge(self):
        """Phase 5: cross-platform dedup. LinkedIn is the source of truth for posting time."""
        jobs, now = self.archive["jobs"], iso(self.started)
        touched = set()
        skipped = 0
        for obs in self.observations:
            if not self.scorer.role_fit(obs["title"])[0]:
                skipped += 1  # no credit, risk or analytics signal in the title: never archived
                continue
            emp = self.scorer.match_employer(obs["company"])
            place = self.scorer.locate(obs["location"], obs["assume_india"])
            company_key = emp["id"] if emp else norm_company(obs["company"])
            key = stable_id(company_key, norm_title(obs["title"]), place["city"])
            job = jobs.get(key)
            if not job:
                job = jobs[key] = {"id": key, "title": obs["title"], "company": emp["name"] if emp else obs["company"],
                                   "company_raw": obs["company"], "location": obs["location"], "first_seen": now, "sources": {}}
            touched.add(key)
            job["last_seen"] = now
            job["assume_india"] = job.get("assume_india") or obs["assume_india"]
            sid = f"{obs['platform']}:{obs['job_id']}"
            src = job["sources"].setdefault(sid, {"platform": obs["platform"], "job_id": obs["job_id"], "url": obs["url"],
                                                  "first_seen": now, "via": []})
            src["last_seen"] = now
            src["url"] = obs["url"]
            src["posted_text"] = obs.get("posted_text") or obs.get("posted_date") or obs.get("posted_iso") or ""
            if obs["via"] not in src["via"]:
                src["via"].append(obs["via"])
            if obs.get("window"):
                src["window_hours"] = min(obs["window"], src.get("window_hours") or obs["window"])
            if obs["estimate"]:
                self.update_posted(src, obs["estimate"])
            if obs["platform"] == "linkedin":
                job["title"], job["location"] = obs["title"], obs["location"]
                if obs.get("badge"):
                    job["badge"] = obs["badge"]
                if emp and obs.get("company_slug"):
                    self.archive["learned"].setdefault(emp["id"], {})["linkedin_slug"] = obs["company_slug"]
            if obs.get("apply_url"):
                job["apply_url"] = obs["apply_url"]
            if obs.get("description") and len(obs["description"]) > max(job.get("desc_chars", 0), len(job.get("description") or "")):
                job["description"] = obs["description"]
        self.funnel["irrelevant_titles"] = skipped
        self.touched = touched
        return touched

    def compact(self):
        """Keep keyword hits and an excerpt, not full descriptions, so the archive stays small."""
        for job in self.archive["jobs"].values():
            desc = job.get("description") or ""
            if len(desc) >= 200:
                job["skill_hits"] = self.scorer.skills(job["title"] + "\n" + desc)[1]
                job["desc_chars"], job["excerpt"] = len(desc), desc[:700]
                del job["description"]

    @staticmethod
    def update_posted(src, estimate):
        posted, earliest, latest, precision = estimate
        old = parse_iso(src.get("posted_at"))
        if old:
            inside = (earliest is None or old >= earliest - timedelta(minutes=5)) and old <= latest + timedelta(minutes=5)
            if inside and PRECISION_RANK.get(src.get("precision"), -1) >= PRECISION_RANK.get(precision, -1):
                return  # the earlier, finer reading still agrees with what the source shows now
            if not inside and latest > old + timedelta(hours=12):
                src["reposted"] = True  # source now shows it as newer than first recorded
        src.update(posted_at=iso(posted), posted_earliest=iso(earliest), posted_latest=iso(latest), precision=precision)

    def best_posted(self, job):
        """LinkedIn first, then the finest-grained other source."""
        ranked = sorted(
            (s for s in job["sources"].values() if s.get("posted_at")),
            key=lambda s: (s["platform"] == "linkedin", PRECISION_RANK.get(s.get("precision"), -1), s["posted_at"]),
            reverse=True,
        )
        return ranked[0] if ranked else None

    # ------------------------------------------------------------ enrich
    def enrich(self, budget):
        """Read LinkedIn descriptions for the most promising unread roles."""
        candidates = []
        for key in self.touched:
            job = self.archive["jobs"][key]
            if job.get("detail_at") or job.get("skill_hits") or len(job.get("description") or "") >= 200:
                continue
            li = next((s for s in job["sources"].values() if s["platform"] == "linkedin"), None)
            if not li:
                continue
            best = self.best_posted(job)
            age = age_hours(parse_iso(best["posted_at"]), self.started) if best else None
            probe = self.scorer.score(dict(job), age)
            if not probe["score"] or probe["excluded"] in ("non_india", "junior", "other_risk", "engineering", "operations", "junior_grade", "irrelevant"):
                continue
            if probe["score"]["role"] < 20:
                continue
            candidates.append((age is None or age > self.windows["primary_hours"], -probe["score"]["base"], key, li["job_id"]))
        candidates.sort()
        limit = self.args.max_details
        read = failed = 0
        for _, _, key, job_id in candidates[:limit]:
            if budget.spent or self.guard.aborted:
                break
            detail = self.guard.run(lambda job_id=job_id: linkedin.fetch_detail(self.li_http, job_id), budget)
            if detail is None:
                failed += 1
                continue
            job = self.archive["jobs"][key]
            job["detail_at"] = iso(now_utc())
            for field in ("description", "seniority_level", "employment_type", "job_function", "industries",
                          "applicants_text", "applicants_n", "apply_url", "closed"):
                if detail.get(field) not in (None, ""):
                    job[field] = detail[field][:8000] if field == "description" else detail[field]
            if detail.get("reposted"):
                job["reposted"] = True
            read += 1
        return {"candidates": len(candidates), "read": read, "failed": failed, "unread": max(0, len(candidates) - read)}

    # ------------------------------------------------------------ publish
    def publish(self, finished=True):
        now = now_utc()
        self.compact()
        jobs = self.archive["jobs"]
        cutoff = now - timedelta(days=self.windows["retain_days"])
        for key in [k for k, j in jobs.items() if (parse_iso(j.get("last_seen")) or now) < cutoff]:
            del jobs[key]
        out, dropped = [], 0
        for job in jobs.values():
            best = self.best_posted(job)
            posted = parse_iso(best["posted_at"]) if best else None
            scored = self.scorer.score(dict(job), age_hours(posted, now))
            if not scored["score"]:
                dropped += 1
                continue
            if scored["excluded"] and scored["score"]["role"] < 30:
                dropped += 1
                continue
            platforms = sorted({s["platform"] for s in job["sources"].values()})
            ats_only = "linkedin" not in platforms and "naukri" not in platforms
            source_keys = {v for s in job["sources"].values() for v in s["via"] if v.startswith("ats:")}
            new_to_source = any(
                (self.archive["sources"].get(k, {}).get("first_ok") or "") < job["first_seen"] for k in source_keys
            )
            out.append({
                "id": job["id"], "title": job["title"], "company": job["company"],
                "company_raw": job.get("company_raw") if job.get("company_raw") != job["company"] else None,
                "employer_id": scored["employer_id"], "category": scored["category"], "tier": scored["tier"],
                "location": job["location"], "city": scored["city"], "cities": scored["cities"], "city_group": scored["city_group"],
                "posted_at": best["posted_at"] if best else None, "posted_earliest": best.get("posted_earliest") if best else None,
                "posted_latest": best.get("posted_latest") if best else None, "precision": best.get("precision") if best else None,
                "posted_source": best["platform"] if best else None, "posted_text": best.get("posted_text") if best else None,
                "first_seen": job["first_seen"], "last_seen": job["last_seen"], "in_latest_scan": job["id"] in getattr(self, "touched", set()),
                "platforms": platforms, "ats_only": ats_only, "new_to_source": new_to_source,
                "reposted": bool(job.get("reposted") or any(s.get("reposted") for s in job["sources"].values())),
                "sources": [{"platform": s["platform"], "url": s["url"], "posted_text": s.get("posted_text"), "via": s["via"]}
                            for s in job["sources"].values()],
                "apply_url": job.get("apply_url"), "applicants_text": job.get("applicants_text"), "applicants_n": job.get("applicants_n"),
                "badge": job.get("badge"), "seniority_level": job.get("seniority_level"), "employment_type": job.get("employment_type"),
                "closed": bool(job.get("closed")), "excerpt": job.get("excerpt") or (job.get("description") or "")[:700],
                "desc_chars": job.get("desc_chars") or len(job.get("description") or ""),
                "score": scored["score"], "matched": scored["matched"], "excluded": scored["excluded"], "band": scored["band"],
            })
        out.sort(key=lambda j: (j["excluded"] is not None, -(j["score"]["total"]), j["posted_at"] or ""))
        primary, secondary = self.windows["primary_hours"], self.windows["secondary_hours"]

        def within(job, hours):
            posted = parse_iso(job["posted_at"])
            return posted is not None and age_hours(posted, now) <= hours

        qualified = [j for j in out if not j["excluded"] and not j["closed"]]
        q30, q72 = [j for j in qualified if within(j, primary)], [j for j in qualified if within(j, secondary)]
        self.funnel.update(
            observations=len(self.observations), roles_in_archive=len(jobs), published=len(out), dropped_low_relevance=dropped,
            qualified_total=len(qualified), qualified_primary=len(q30), qualified_secondary=len(q72),
            tier1_primary=sum(1 for j in q30 if j["band"] == "Tier 1"), tier2_primary=sum(1 for j in q30 if j["band"] == "Tier 2"),
            tier3_primary=sum(1 for j in q30 if j["band"] == "Tier 3"),
        )
        li_queries = [q for q in self.queries if q["kind"] in ("company", "skill")]
        li_ok = sum(1 for q in li_queries if q.get("state") == "ok")
        ats_ok = sum(1 for s in self.ats_status.values() if s["state"] == "ok")
        self.sources.setdefault("linkedin", {}).update(
            queries=len(li_queries), ok=li_ok, capped=sum(1 for q in li_queries if q.get("capped")),
            throttle_events=self.guard.events, aborted=self.guard.aborted, requests=self.li_http.requests,
            state="not_run" if not li_queries else "ok" if li_ok == len(li_queries) else "partial" if li_ok else "failed",
        )
        self.sources["ats"] = {"configured": len(self.ats_status), "ok": ats_ok,
                               "state": "not_run" if not self.ats_status else "ok" if ats_ok == len(self.ats_status) else "partial" if ats_ok else "failed"}
        run_id = os.environ.get("GITHUB_RUN_ID")
        repo = os.environ.get("GITHUB_REPOSITORY")
        status = {
            "schema": 1, "state": "complete" if finished else "running", "started": iso(self.started), "finished": iso(now) if finished else None,
            "duration_seconds": round((now - self.started).total_seconds()), "trigger": os.environ.get("SCAN_TRIGGER") or os.environ.get("GITHUB_EVENT_NAME") or "local",
            "run_id": run_id, "run_url": f"https://github.com/{repo}/actions/runs/{run_id}" if run_id and repo else None,
            "secondary_window_used": self.secondary_used, "phases": [{k: v for k, v in p.items() if not k.startswith("_")} for p in self.phases],
            "sources": self.sources, "funnel": self.funnel, "queries": self.queries, "ats": self.ats_status,
            "coverage_note": "Counts reflect what public, logged-out sources returned to this runner. A failed, capped or blocked source is a gap, not zero vacancies.",
        }
        if finished:
            self.archive["history"] = (self.archive["history"] + [{
                "started": status["started"], "duration_seconds": status["duration_seconds"], "trigger": status["trigger"],
                "qualified_primary": len(q30), "qualified_secondary": len(q72), "linkedin_ok": li_ok, "linkedin_queries": len(li_queries),
                "ats_ok": ats_ok, "observations": len(self.observations),
            }])[-45:]
        status["history"] = self.archive["history"]
        save_json(DATA / "jobs.json", {"generated_at": iso(now), "scan_started": iso(self.started), "jobs": out})
        save_json(DATA / "status.json", status, indent=1)
        save_json(DATA / "config.json", self.site_config())
        save_json(ARCHIVE, self.archive)
        from .digest import write_digest
        write_digest(out, status, self.scoring, now)
        return status

    def site_config(self):
        learned = self.archive.get("learned", {})
        employers = []
        for emp in self.employers["employers"]:
            entry = {k: emp[k] for k in ("n", "id", "name", "category", "tier", "focus", "conditional", "query", "careers_url", "same_as", "note")}
            entry["ats_type"] = (emp.get("ats") or {}).get("type")
            entry["linkedin_slug"] = learned.get(emp["id"], {}).get("linkedin_slug")
            entry["linkedin_keywords"] = linkedin.company_keywords(emp["query"], self.search["linkedin"]["company_terms"])
            employers.append(entry)
        return {"categories": self.employers["categories"], "tiers": self.employers["tiers"], "employers": employers,
                "scoring": self.scoring, "search": self.search}

    # ------------------------------------------------------------ run
    def run(self):
        args = self.args
        if args.init or args.rescore:
            self.touched = set()
            status = load_json(DATA / "status.json")
            if args.rescore and status and status.get("state") == "complete":
                # keep the last scan's coverage record; only scores and config change
                self.phases, self.queries, self.ats_status = status.get("phases", []), status.get("queries", []), status.get("ats", {})
                self.sources, self.funnel = status.get("sources", {}), status.get("funnel", {})
                self.started = parse_iso(status.get("started")) or self.started
                self.guard.events = self.sources.get("linkedin", {}).get("throttle_events", 0)
                self.touched = {j["id"] for j in (load_json(DATA / "jobs.json", {}) or {}).get("jobs", []) if j.get("in_latest_scan")}
                self.publish_rescore(status)
            else:
                save_json(DATA / "config.json", self.site_config())
                if not (DATA / "status.json").exists():
                    save_json(DATA / "status.json", {"schema": 1, "state": "never_run", "history": []}, indent=1)
                    save_json(DATA / "jobs.json", {"generated_at": None, "jobs": []})
            return

        company, skill = self.linkedin_queries()
        primary, secondary = self.windows["primary_hours"], self.windows["secondary_hours"]
        li_budget = Budget(args.linkedin_minutes * 60)

        p1 = self.phase(1, "LinkedIn company scans")
        done = self.run_linkedin(company, primary, li_budget)
        self.close(p1, "ok" if done == len(company) else "partial" if done else "failed", queries=len(company), completed=done, window_hours=primary)

        p2 = self.phase(2, "LinkedIn skill searches")
        done = self.run_linkedin(skill, primary, li_budget)
        self.close(p2, "ok" if done == len(skill) else "partial" if done else "failed", queries=len(skill), completed=done, window_hours=primary)

        found = self.qualified_in_window(primary)
        self.funnel["qualified_primary_before_supplement"] = found
        if found < self.windows["secondary_trigger_below"] and not args.no_secondary:
            self.secondary_used = True
            p2b = self.phase("2b", f"Secondary window ({secondary}h) volume supplement")
            done = self.run_linkedin(skill + company, secondary, li_budget)
            self.close(p2b, "ok" if done == len(skill) + len(company) else "partial" if done else "failed",
                       reason=f"only {found} roles cleared the threshold in {primary}h", queries=len(skill) + len(company), completed=done)

        p3 = self.phase(3, "Naukri.com")
        rows, nk = naukri.canary(Http(min_gap=1, max_gap=2))
        seen_at = now_utc()
        for row in rows:
            bounds = row.pop("_bounds", None)
            self.observe(row, seen_at, posted_estimate(seen_at, bounds, 24), "naukri", assume_india=True)
        self.sources["naukri"] = nk
        self.close(p3, "ok" if nk["state"] == "ok" else "manual", **{("source_state" if k == "state" else k): v for k, v in nk.items()})

        p4 = self.phase(4, "Career-portal (ATS) checks")
        self.run_ats(Budget(args.ats_minutes * 60))
        ok = sum(1 for s in self.ats_status.values() if s["state"] == "ok")
        self.close(p4, "ok" if ok == len(self.ats_status) else "partial" if ok else "failed", portals=len(self.ats_status), responded=ok)

        p5 = self.phase(5, "Deduplication, enrichment and ranking")
        touched = self.merge()
        detail = self.enrich(Budget(args.detail_minutes * 60))
        self.sources["linkedin"] = {"details": detail}
        self.close(p5, "ok" if not detail["failed"] and not detail["unread"] else "partial", unique_roles=len(touched), descriptions=detail)

        p6 = self.phase(6, "Scoring, top-10 digest and publication")
        self.close(p6, "ok")
        status = self.publish()
        print("\nFunnel:", status["funnel"], flush=True)

    def publish_rescore(self, previous):
        status = self.publish(finished=False)
        for field in ("state", "finished", "duration_seconds", "trigger", "run_id", "run_url", "secondary_window_used"):
            status[field] = previous.get(field)
        status["rescored_at"] = iso(now_utc())
        save_json(DATA / "status.json", status, indent=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--init", action="store_true", help="write site config and an empty state without scanning")
    parser.add_argument("--rescore", action="store_true", help="re-apply scoring to the archive without any network calls")
    parser.add_argument("--max-queries", type=int, default=0, help="limit queries per phase (smoke test)")
    parser.add_argument("--max-details", type=int, default=int(os.environ.get("MAX_DETAILS", 150)))
    parser.add_argument("--no-secondary", action="store_true")
    parser.add_argument("--linkedin-minutes", type=float, default=float(os.environ.get("LINKEDIN_MINUTES", 32)))
    parser.add_argument("--detail-minutes", type=float, default=float(os.environ.get("DETAIL_MINUTES", 12)))
    parser.add_argument("--ats-minutes", type=float, default=float(os.environ.get("ATS_MINUTES", 8)))
    Scan(parser.parse_args()).run()


if __name__ == "__main__":
    main()
