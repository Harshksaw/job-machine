"""Harvest remote software roles open to Canada from public remote job board feeds.

    uv run python scripts/remote_boards.py [--out candidates.json] [--days 21]

Boards (all public JSON, no login, no browser): Himalayas, Remotive, Jobicy, Working
Nomads, Remote OK. Each listing is normalized, filtered to engineering roles below
senior that a Canada-based candidate can hold remotely, and deduped against the
dossier store with the store's own canonical URL plus a company and role match.

This script only harvests. Fit scoring and `/api/jobs/capture` stay agent steps, as
AGENTS.md requires, so nothing is written to the dossier store here. Remote OK's API
terms ask that it be credited as the source, so its rows carry `source: Remote OK`.
"""
import argparse
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.job_store import canonical_job_url, load_jobs  # noqa: E402

TITLE_KEEP = re.compile(
    r"engineer|developer|programmer|software|full.?stack|back.?end|front.?end|\bml\b|\bai\b|"
    r"machine learning|data engineer|devops|platform|sre\b",
    re.I,
)
TITLE_DROP = re.compile(
    r"senior|\bsr\b|staff|principal|lead|manager|director|head of|architect|\bvp\b|"
    r"intern|co-?op|summer student|\biii\b|\biv\b|recruit|sales|marketing|support|"
    r"review lead|translator|annotat|content|writer|tutor|trainer",
    re.I,
)
# Remote roles must let him work from Canada. A US-only remote role means living in the
# US, which is not the same as the on-site relocation the eligibility policy allows.
LOCATION_OK = re.compile(
    r"canada|north america|americas|worldwide|anywhere|global|remote$|^$", re.I
)
SENIORITY_DROP = re.compile(r"senior|director|executive|lead", re.I)


# An honest client name. Remotive and Remote OK refuse the bare Python-urllib default.
USER_AGENT = "job-machine-remote-boards/1.0 (personal job search)"


def fetch_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def strip_html(text: str) -> str:
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(text)).strip()


def himalayas() -> list[dict]:
    rows = []
    for query in ("software engineer", "developer", "machine learning", "full stack"):
        for seniority in ("Entry-level", "Mid-level"):
            for page in range(1, 6):
                params = urllib.parse.urlencode(
                    {"q": query, "country": "Canada", "seniority": seniority, "page": page}
                )
                data = fetch_json(f"https://himalayas.app/jobs/api/search?{params}")
                for job in data.get("jobs", []):
                    rows.append(
                        {
                            "source": "Himalayas",
                            "company": job.get("companyName", ""),
                            "role": job.get("title", ""),
                            "job_url": job.get("guid") or job.get("applicationLink", ""),
                            "location": ", ".join(job.get("locationRestrictions") or [])
                            or "Worldwide",
                            "seniority": ", ".join(job.get("seniority") or []),
                            "salary": _salary(job.get("minSalary"), job.get("maxSalary"),
                                              job.get("currency"), job.get("salaryPeriod")),
                            "posted": _epoch(job.get("pubDate")),
                            "jd_text": strip_html(job.get("description", "")),
                        }
                    )
                if len(data.get("jobs", [])) < 20:
                    break
                time.sleep(1)
    return rows


def remotive() -> list[dict]:
    data = fetch_json("https://remotive.com/api/remote-jobs?category=software-dev")
    return [
        {
            "source": "Remotive",
            "company": job.get("company_name", ""),
            "role": job.get("title", ""),
            "job_url": job.get("url", ""),
            "location": job.get("candidate_required_location", ""),
            "seniority": "",
            "salary": job.get("salary", ""),
            "posted": (job.get("publication_date") or "")[:10],
            "jd_text": strip_html(job.get("description", "")),
        }
        for job in data.get("jobs", [])
    ]


def jobicy() -> list[dict]:
    rows = []
    for industry in ("engineering", "dev", "data-science"):
        url = f"https://jobicy.com/api/v2/remote-jobs?count=50&geo=canada&industry={industry}"
        for job in fetch_json(url).get("jobs", []):
            rows.append(
                {
                    "source": "Jobicy",
                    "company": job.get("companyName", ""),
                    "role": html.unescape(job.get("jobTitle", "")),
                    "job_url": job.get("url", ""),
                    "location": job.get("jobGeo", ""),
                    "seniority": job.get("jobLevel", ""),
                    "salary": _salary(job.get("salaryMin"), job.get("salaryMax"),
                                      job.get("salaryCurrency"), job.get("salaryPeriod")),
                    "posted": (job.get("pubDate") or "")[:10],
                    "jd_text": strip_html(job.get("jobDescription", "")),
                }
            )
        time.sleep(1)
    return rows


def working_nomads() -> list[dict]:
    return [
        {
            "source": "Working Nomads",
            "company": job.get("company_name", ""),
            "role": job.get("title", ""),
            "job_url": job.get("url", ""),
            "location": job.get("location", ""),
            "seniority": "",
            "salary": "",
            "posted": (job.get("pub_date") or "")[:10],
            "jd_text": strip_html(job.get("description", "")),
        }
        for job in fetch_json("https://www.workingnomads.com/api/exposed_jobs/")
        if job.get("category_name") in ("Development", "Data", "DevOps", "Machine Learning")
    ]


def remote_ok() -> list[dict]:
    data = fetch_json("https://remoteok.com/api")[1:]  # row 0 is the API terms notice
    return [
        {
            "source": "Remote OK",
            "company": job.get("company", ""),
            "role": job.get("position", ""),
            "job_url": job.get("url", ""),
            "location": job.get("location", ""),
            "seniority": "",
            "salary": _salary(job.get("salary_min"), job.get("salary_max"), "USD", "year"),
            "posted": (job.get("date") or "")[:10],
            "jd_text": strip_html(job.get("description", "")),
        }
        for job in data
    ]


def _salary(low, high, currency, period) -> str:
    if not low and not high:
        return ""
    return f"{currency or ''} {low or '?'} to {high or '?'} per {period or 'year'}".strip()


def _epoch(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _company_key(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\b(inc|ltd|llc|corp|co)\b\.?", "", company.lower()))


def _role_key(role: str) -> str:
    """Role identity that ignores parentheticals, 'remote', and punctuation."""
    role = re.sub(r"\([^)]*\)|\[[^\]]*\]|\bremote\b", " ", role.lower())
    return " ".join(re.findall(r"[a-z0-9]+", role))


def keep(row: dict, since: str) -> str:
    """Return a drop reason, or '' to keep the row."""
    if not TITLE_KEEP.search(row["role"]) or TITLE_DROP.search(row["role"]):
        return "title"
    if SENIORITY_DROP.search(row["seniority"]) and "entry" not in row["seniority"].lower():
        return "seniority"
    if not LOCATION_OK.search(row["location"].strip()):
        return "location"
    if row["posted"] and row["posted"] < since:
        return "stale"
    if len(row["jd_text"]) < 300:
        return "no jd"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="remote_candidates.json")
    parser.add_argument("--days", type=int, default=21, help="drop postings older than this")
    args = parser.parse_args()
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()

    rows: list[dict] = []
    for name, harvest in (("Himalayas", himalayas), ("Remotive", remotive), ("Jobicy", jobicy),
                          ("Working Nomads", working_nomads), ("Remote OK", remote_ok)):
        try:
            got = harvest()
            print(f"{name}: {len(got)} listings", file=sys.stderr)
            rows.extend(got)
        except Exception as exc:  # one dead board must not sink the run
            print(f"{name}: FAILED {exc}", file=sys.stderr)

    known_urls = set()
    known_keys = set()
    touched = {}  # company -> statuses, so a new role at a company he already applied to is visible
    for job in load_jobs():
        known_urls.add(canonical_job_url(job.job_url))
        known_keys.add((_company_key(job.company), _role_key(job.role)))
        touched.setdefault(_company_key(job.company), set()).add(job.status)

    kept, seen, dropped = [], set(), {}
    for row in rows:
        reason = keep(row, since)
        key = (_company_key(row["company"]), _role_key(row["role"]))
        statuses = touched.get(key[0], set()) & {"applied", "applying", "interview", "rejected"}
        row["company_history"] = ", ".join(sorted(statuses))
        url = canonical_job_url(row["job_url"])
        if not reason and (url in known_urls or key in known_keys):
            reason = "already in dossiers"
        if not reason and (url in seen or key in seen):
            reason = "duplicate across boards"
        if reason:
            dropped[reason] = dropped.get(reason, 0) + 1
            continue
        seen.update({url, key})
        kept.append(row)

    Path(args.out).write_text(json.dumps(kept, indent=1))
    print(f"kept {len(kept)} of {len(rows)}; dropped {dropped}", file=sys.stderr)
    print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
