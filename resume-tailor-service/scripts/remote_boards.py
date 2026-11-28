"""Harvest remote software roles from public remote job board feeds and tier them.

    uv run python scripts/remote_boards.py [--out data/remote_candidates.json] [--days 21]

Boards (all public JSON, no login, no browser): Himalayas, Remotive, Jobicy, Working
Nomads, Remote OK. No board is asked to filter by country: every listing is fetched and
`app.regions.classify_location` tiers it locally, following AGENTS.md:

- Tier A: remote open to Canada, or anywhere.
- Tier A2: remote limited to the US, UK, Australia, New Zealand or another
  country outside India and Europe.
- Tier E: remote limited to Europe (EU, EEA, Switzerland). Kept, worked last.
- Dropped: anything based in India, even when another region also matches.

Country order inside the output: Canada, US, UK, Australia, New Zealand, other, Europe last.
Each kept row carries `tier` and `region`. Rows are also filtered to engineering roles below
senior and deduped against the dossier store with the store's own canonical URL plus a
company and role match.

Output goes to the gitignored `resume-tailor-service/data/` folder by default (it carries
per company application history and the repo is PUBLIC). A funnel summary is written next
to it as `<name>.summary.json`:
{run_at, sources: {name: {fetched, kept: {A, A2, E}, dropped: {reason: n}}}}.

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

SERVICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE))
from app.job_store import canonical_job_url, load_jobs  # noqa: E402
from app.regions import classify_location  # noqa: E402

DEFAULT_OUT = SERVICE / "data" / "remote_candidates.json"
TIERS = ("A", "A2", "E")

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
                # No country filter: every region is tiered locally by classify_location.
                params = urllib.parse.urlencode({"q": query, "seniority": seniority, "page": page})
                data = fetch_json(f"https://himalayas.app/jobs/api/search?{params}")
                for job in data.get("jobs", []):
                    rows.append(
                        {
                            "source": "Himalayas",
                            "company": job.get("companyName", ""),
                            "role": job.get("title", ""),
                            "job_url": job.get("guid") or job.get("applicationLink", ""),
                            "location": _places(job.get("locationRestrictions")),
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
        # No geo filter: every region is tiered locally by classify_location.
        url = f"https://jobicy.com/api/v2/remote-jobs?count=50&industry={industry}"
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


def _places(restrictions) -> str:
    """Himalayas documents objects ({alpha2, name, slug}); the live feed has sent strings."""
    names = [p.get("name", "") if isinstance(p, dict) else str(p) for p in restrictions or []]
    return ", ".join(n for n in names if n) or "Worldwide"


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
    """Return a drop reason, or '' to keep the row. Writes `tier` and `region` on the row."""
    if not TITLE_KEEP.search(row["role"]) or TITLE_DROP.search(row["role"]):
        return "title"
    if SENIORITY_DROP.search(row["seniority"]) and "entry" not in row["seniority"].lower():
        return "seniority"
    where = classify_location(row["location"], row.get("remote_scope", ""))
    row["tier"], row["region"] = where.tier, where.region
    row["_rank"] = where.rank
    if where.tier == "drop":
        return where.reason
    if row["posted"] and row["posted"] < since:
        return "stale"
    if len(row["jd_text"]) < 300:
        return "no jd"
    return ""


SOURCES = (("Himalayas", himalayas), ("Remotive", remotive), ("Jobicy", jobicy),
           ("Working Nomads", working_nomads), ("Remote OK", remote_ok))


def harvest(sources, since: str, known_jobs) -> tuple[list[dict], dict]:
    """Fetch every source, tier and dedupe the rows. Returns (kept rows, funnel summary)."""
    known_urls, known_keys = set(), set()
    touched = {}  # company -> statuses, so a new role at a company he already applied to is visible
    for job in known_jobs:
        known_urls.add(canonical_job_url(job.job_url))
        known_keys.add((_company_key(job.company), _role_key(job.role)))
        touched.setdefault(_company_key(job.company), set()).add(job.status)

    summary = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": {}}
    kept, seen = [], set()
    for name, fetch in sources:
        counts = {"fetched": 0, "kept": {tier: 0 for tier in TIERS}, "dropped": {}}
        summary["sources"][name] = counts
        try:
            rows = fetch()
        except Exception as exc:  # one dead board must not sink the run
            counts["error"] = str(exc)[:300]
            continue
        counts["fetched"] = len(rows)
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
                counts["dropped"][reason] = counts["dropped"].get(reason, 0) + 1
                continue
            seen.update({url, key})
            counts["kept"][row["tier"]] += 1
            kept.append(row)

    # Country order: Canada, US, UK, Australia, New Zealand, other, Europe last.
    kept.sort(key=lambda row: (TIERS.index(row["tier"]), row["_rank"]))
    for row in kept:
        row.pop("_rank", None)
    return kept, summary


def summary_path(out: Path) -> Path:
    return out.with_name(f"{out.stem}.summary.json")


def _report(summary: dict) -> None:
    for name, counts in summary["sources"].items():
        if "error" in counts:
            print(f"{name}: FAILED {counts['error']}", file=sys.stderr)
            continue
        tiers = " ".join(f"{tier} {n}" for tier, n in counts["kept"].items())
        print(f"{name}: fetched {counts['fetched']}, kept {tiers}, dropped {counts['dropped']}",
              file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None,
                        help="default: resume-tailor-service/data/remote_candidates.json (gitignored)")
    parser.add_argument("--days", type=int, default=21, help="drop postings older than this")
    args = parser.parse_args(argv)
    out = args.out or DEFAULT_OUT
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).date().isoformat()

    kept, summary = harvest(SOURCES, since, load_jobs())
    _report(summary)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(kept, indent=1))
    summary_path(out).write_text(json.dumps(summary, indent=1))
    fetched = sum(c["fetched"] for c in summary["sources"].values())
    print(f"kept {len(kept)} of {fetched}", file=sys.stderr)
    print(f"wrote {out} and {summary_path(out).name}", file=sys.stderr)


if __name__ == "__main__":
    main()
