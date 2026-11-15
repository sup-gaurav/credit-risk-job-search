"""Scoring, tiering and exclusion rules (Section 1 tiers + Section 3.4).

Every number here comes from config/scoring.json so the dashboard can show the
same logic it was scored with.
"""
from __future__ import annotations

import re

from .common import norm, norm_company


def _rx(pattern: str):
    return re.compile(pattern, re.I)


class Scorer:
    def __init__(self, scoring: dict, employers: dict):
        self.cfg = scoring
        self.employers = {e["id"]: e for e in employers["employers"]}
        self.single, self.multi = {}, []
        for emp in employers["employers"]:
            target = self.employers[emp["same_as"]] if emp.get("same_as") else emp
            for alias in emp["aliases"]:
                key = norm(alias)
                if " " in key:
                    self.multi.append((re.compile(r"\b" + re.escape(key) + r"\b"), target))
                else:
                    self.single[key] = target
        role = scoring["role"]
        self.role_classes = [(name, role[name], [_rx(p) for p in role[name]["patterns"]]) for name in ("core", "strong", "adjacent", "weak")]
        self.skill_groups = [
            (name, grp, [(label, _rx(pat)) for label, pat in grp["terms"].items()])
            for name, grp in scoring["skills"].items() if isinstance(grp, dict)
        ]
        sen = scoring["seniority"]
        self.levels = [(lvl, _rx(lvl["pattern"])) for lvl in sen["levels"]]
        self.overrides = [(_rx(o["pattern"]), o["level"]) for o in sen.get("overrides", [])]
        loc = scoring["location"]
        self.cities = []
        for group in ("primary", "secondary"):
            for city, pattern in loc[group]["cities"].items():
                self.cities.append((city, group, loc[group]["points"], _rx(pattern)))
        self.remote_rx, self.india_rx = _rx(loc["remote"]["pattern"]), _rx(loc["other_india"]["pattern"])
        self.exclusions = [
            (x, _rx(x["title"]), _rx(x["unless_title"]) if x.get("unless_title") else None)
            for x in scoring["exclusions"] if x.get("title")
        ]
        emp_cfg = scoring["employer"]
        self.fin_rx = _rx(emp_cfg["financial_hint"])
        self.top_tier = set(emp_cfg["top_tier_ids"])
        self.tier1_tiers = set(emp_cfg["tier1_firm_tiers"])

    # ------------------------------------------------------------ employer
    def match_employer(self, company: str):
        full = norm(company)
        if not full:
            return None
        hit = self.single.get(full) or self.single.get(norm_company(company))
        if hit:
            return hit
        for rx, emp in self.multi:
            if rx.search(full):
                return emp
        return None

    # ------------------------------------------------------------ location
    def locate(self, location: str, assume_india: bool):
        text = location or ""
        found = [(city, group, pts) for city, group, pts, rx in self.cities if rx.search(text)]
        if found:
            best = max(found, key=lambda f: f[2])
            return {"city": best[0], "cities": [f[0] for f in found], "group": best[1], "points": best[2], "india": True}
        loc = self.cfg["location"]
        india = bool(self.india_rx.search(text))
        if self.remote_rx.search(text) and (india or assume_india):
            return {"city": "Remote / hybrid", "cities": ["Remote / hybrid"], "group": "remote", "points": loc["remote"]["points"], "india": True}
        if india or (assume_india and not text.strip()) or assume_india:
            return {"city": "Other India", "cities": ["Other India"], "group": "other", "points": loc["other_india"]["points"], "india": True}
        return {"city": "Outside India", "cities": [], "group": "none", "points": 0, "india": False}

    # ------------------------------------------------------------ pieces
    def role_fit(self, title: str):
        low = norm(title).replace(" 9", " 9")
        raw = (title or "").lower()
        for name, cfg, patterns in self.role_classes:
            if any(p.search(raw) or p.search(low) for p in patterns):
                return name, cfg
        return None, None

    def skills(self, text: str):
        matched, points = {}, 0
        for name, grp, terms in self.skill_groups:
            hits = [label for label, rx in terms if rx.search(text)]
            matched[name] = hits
            points += min(grp["cap"], len(hits) * grp["each"])
        return points, matched

    def seniority(self, title: str):
        low = (title or "").lower()
        for rx, index in self.overrides:
            if rx.search(low):
                return self.levels[index][0]
        for level, rx in self.levels:
            if rx.search(low):
                return level
        return None

    def freshness(self, age_hours, applicants):
        cfg = self.cfg["freshness"]
        pts = cfg["unknown_age_points"]
        if age_hours is not None:
            pts = next((b["points"] for b in cfg["age_points"] if age_hours <= b["max_hours"]), 0)
        bonus = cfg["unknown_applicant_points"]
        if applicants is not None:
            bonus = next((b["points"] for b in cfg["applicant_points"] if applicants <= b["max"]), 0)
        return min(self.cfg["weights"]["freshness"], pts + bonus)

    # ------------------------------------------------------------ main
    def title_exclusion(self, title: str, emp):
        low = (title or "").lower()
        for rule, rx, unless in self.exclusions:
            if not rx.search(low):
                continue
            if unless and unless.search(low):
                if rule.get("unless_top_tier_only") and not (emp and emp["id"] in self.top_tier):
                    return rule["id"]
                continue
            return rule["id"]
        return None

    def score(self, job: dict, age_hours=None):
        """Mutates and returns job with employer, location and score fields."""
        cfg, w = self.cfg, self.cfg["weights"]
        emp = self.match_employer(job.get("company", ""))
        title = job.get("title", "")
        desc = job.get("description") or ""
        place = self.locate(job.get("location", ""), job.get("assume_india", False))
        job.update(
            employer_id=emp["id"] if emp else None, category=emp["category"] if emp else None,
            tier=emp["tier"] if emp else None, city=place["city"], cities=place["cities"], city_group=place["group"],
        )
        cls, role_cfg = self.role_fit(title)
        if not cls:
            job["score"] = None
            job["excluded"] = "irrelevant"
            return job
        stored = job.get("skill_hits")
        if stored and len(desc) < 200:
            # description was read on an earlier scan; only its keyword hits are kept
            matched = stored
            skill_pts = sum(min(grp["cap"], len(stored.get(name, [])) * grp["each"]) for name, grp, _ in self.skill_groups)
        else:
            skill_pts, matched = self.skills(title + "\n" + desc)
        core_hits = len(matched.get("core", []))
        role_pts, cap = role_cfg["points"], role_cfg.get("cap", 100)
        if cls == "adjacent" and core_hits >= role_cfg["boost_core_hits"]:
            role_pts, cap = role_cfg["boost_points"], role_cfg["boost_cap"]
        title_only = len(desc) < 200 and not stored
        if title_only:
            skill_pts = round(w["skills"] * cfg["skills"]["title_only_scale"] * role_pts / w["role"])
        skill_pts = min(w["skills"], skill_pts)

        if emp:
            emp_pts = emp.get("points") or cfg["employer"]["tier_points"].get(emp["tier"], 10)
        else:
            emp_pts = cfg["employer"]["non_target_financial"] if self.fin_rx.search(job.get("company", "") + " " + (job.get("industries") or "")) else cfg["employer"]["non_target_other"]

        level = self.seniority(title)
        top_tier = bool(emp and emp["id"] in self.top_tier)
        tier1_firm = bool(emp and (emp["tier"] in self.tier1_tiers or top_tier))
        if level:
            sen_pts, sen_label, sen_cap = level["points"], level["label"], level.get("cap", 100)
            if tier1_firm and "tier1_points" in level:
                sen_pts, sen_cap = level["tier1_points"], level.get("tier1_cap", sen_cap)
            if top_tier and "top_tier_points" in level:
                sen_pts = level["top_tier_points"]
        else:
            sen_pts, sen_label, sen_cap = cfg["seniority"]["unknown_points"], "Not stated", cfg["seniority"]["unknown_cap"]
        cap = min(cap, sen_cap)
        if re.search(r"\bjunior\b|\bjr\b", title.lower()):
            cap = min(cap, cfg["junior_title_cap"])

        base = role_pts + skill_pts + emp_pts + sen_pts + place["points"]
        fresh = self.freshness(age_hours, job.get("applicants_n"))
        total = min(cap, base + fresh)

        excluded = None
        if not place["india"]:
            excluded = "non_india"
        if not excluded:
            excluded = self.title_exclusion(title, emp)
        if not excluded and level and level.get("junior") and not top_tier:
            excluded = "junior_grade"
        if not excluded and total < cfg["threshold"]:
            excluded = "below_threshold"

        job["score"] = {
            "total": total, "base": base, "cap": cap, "role": role_pts, "skills": skill_pts, "employer": emp_pts,
            "seniority": sen_pts, "location": place["points"], "fresh": fresh,
            "role_class": role_cfg["label"] + (" (credit context in description)" if cls == "adjacent" and role_pts > role_cfg["points"] else ""),
            "seniority_label": sen_label, "title_only": title_only,
        }
        job["matched"] = matched
        job["excluded"] = excluded
        job["band"] = self.band(total) if not excluded else None
        return job

    def band(self, total):
        for band in self.cfg["bands"]:
            if total >= band["min"]:
                return band["label"]
        return None
