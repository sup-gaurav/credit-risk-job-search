"""Phase 6 alert: top-10 list with direct apply links, as Markdown and JSON."""
from __future__ import annotations

from datetime import timedelta, timezone

from .common import DATA, age_hours, parse_iso, save_json

IST = timezone(timedelta(hours=5, minutes=30))


def _age(hours, precision=None):
    if hours is None:
        return "age unknown"
    if (precision == "day" and hours >= 20) or hours >= 48:
        return f"{max(1, int(hours // 24))}d ago"  # day-level sources are quoted in days, as they state it
    return f"{round(hours)}h ago"


def write_digest(jobs, status, scoring, now):
    windows = scoring["windows"]
    live = [j for j in jobs if not j["excluded"] and not j["closed"] and j["posted_at"]]
    for job in live:
        job["_age"] = age_hours(parse_iso(job["posted_at"]), now)
    primary = [j for j in live if j["_age"] <= windows["primary_hours"]]
    picks, window = primary, windows["primary_hours"]
    if len(primary) < windows["secondary_trigger_below"]:
        extra = [j for j in live if windows["primary_hours"] < j["_age"] <= windows["secondary_hours"]]
        picks, window = primary + extra, windows["secondary_hours"]
    picks = sorted(picks, key=lambda j: (-j["score"]["total"], j["_age"]))[:10]
    stamp = now.astimezone(IST).strftime("%d %b %Y, %H:%M IST")
    lines = [f"# Top {len(picks)} credit risk roles", "", f"Scan finished {stamp}. Window: last {window} hours. "
             f"{len(primary)} roles cleared the threshold in the last {windows['primary_hours']} hours.", ""]
    if not picks:
        lines.append("No role cleared the threshold in this window. Check source coverage on the dashboard before treating this as a quiet day.")
    for rank, job in enumerate(picks, 1):
        verified = len(job["platforms"]) >= 2 or job["_age"] < windows["verified_single_platform_hours"]
        fresh = "verified fresh" if verified and job["_age"] <= windows["primary_hours"] else "fresh, single source" if job["_age"] <= windows["primary_hours"] else "recent"
        link = job.get("apply_url") or job["sources"][0]["url"]
        listing = next((s["url"] for s in job["sources"] if s["platform"] == "linkedin"), job["sources"][0]["url"])
        lines += [
            f"{rank}. **{job['title']}** · {job['company']} · {job['city']}",
            f"   Score {job['score']['total']} ({job['band']}) · {_age(job['_age'], job.get('precision'))} · {fresh}"
            + (f" · {job['applicants_text']}" if job.get("applicants_text") else ""),
            f"   [Apply]({link}) · [Listing]({listing})",
        ]
    li = status["sources"].get("linkedin", {})
    lines += ["", f"Coverage: LinkedIn {li.get('ok', 0)}/{li.get('queries', 0)} queries answered, "
              f"career portals {status['sources'].get('ats', {}).get('ok', 0)}/{status['sources'].get('ats', {}).get('configured', 0)}, "
              f"Naukri {status['sources'].get('naukri', {}).get('state', 'not run')}."]
    for job in live:
        job.pop("_age", None)
    (DATA / "digest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    save_json(DATA / "digest.json", {"generated_at": status.get("finished") or status.get("started"), "window_hours": window, "ids": [j["id"] for j in picks]})
