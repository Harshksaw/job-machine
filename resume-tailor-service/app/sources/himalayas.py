"""Himalayas remote jobs API (https://himalayas.app/docs/remote-jobs-api).

A free key allows 60 requests a minute and 10,000 a UTC day, shared across the account, and
cached responses do not count. The key goes in an Authorization header, never a URL. The
API has no company size filter, so startups are picked by the agent that scores the find.

Usage terms: apply through `applicationLink` and show Himalayas as the source. Both are
kept on every staged item (`url`, `source`).

    from app.sources import himalayas
    himalayas.run_search("us-entry")   # stages new finds, returns counts
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app import job_store, research_store

API = "https://himalayas.app/jobs/api/search"
USER_AGENT = "job-machine/1.0 (personal job search)"
MAX_PAGES = 5
PAUSE_SECONDS = 1.1  # stays well under 60 requests a minute

# `countries` run one by one because the API takes a single country; `queries` are crossed
# with them.
PRESETS: dict[str, dict] = {
    "canada-entry": {
        "label": "Himalayas: Canada remote, entry level",
        "countries": ["Canada"],
        "queries": ["software engineer", "developer", "machine learning", "full stack"],
        "seniority": "Entry-level",
    },
    "us-entry": {
        "label": "Himalayas: US remote, entry level",
        "countries": ["US"],
        "queries": ["software engineer", "developer", "machine learning", "full stack"],
        "seniority": "Entry-level",
    },
    "worldwide-entry": {
        "label": "Himalayas: worldwide remote, entry level",
        "countries": [None],
        "worldwide": True,
        "queries": ["software engineer", "developer", "machine learning", "full stack"],
        "seniority": "Entry-level",
    },
    "uk-au-entry": {
        "label": "Himalayas: UK and Australia remote, entry level",
        "countries": ["UK", "Australia"],
        "queries": ["software engineer", "developer"],
        "seniority": "Entry-level",
    },
}

_CANADA_OK = ("canada", "north america", "americas", "worldwide", "anywhere", "global")
_SENIOR = re.compile(r"senior|staff|principal|lead|manager|director|head|\bsr\b", re.I)


class HimalayasError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("HIMALAYAS_API_KEY", "").strip()
    if not key:
        raise HimalayasError("HIMALAYAS_API_KEY is not set in resume-tailor-service/.env")
    return key


def _get(params: dict, key: str) -> dict:
    request = urllib.request.Request(
        f"{API}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as err:
            if err.code == 429 and attempt < 2:
                wait = int(err.headers.get("Retry-After") or 5)
                if wait > 90:  # the daily cap, not a burst: stop instead of sleeping
                    raise HimalayasError(f"Himalayas daily limit reached, retry after {wait}s")
                time.sleep(wait)
                continue
            raise HimalayasError(f"Himalayas HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}")
    raise HimalayasError("Himalayas kept rate limiting")


def _text(markup: str) -> str:
    markup = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
    markup = re.sub(r"<[^>]+>", "", markup)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(markup)).strip()


def _salary(job: dict) -> str:
    low, high = job.get("minSalary"), job.get("maxSalary")
    if not (low or high):
        return ""
    period = job.get("salaryPeriod") or "annual"
    return f"{low or ''}-{high or ''} {job.get('currency') or ''} {period}".strip()


def to_research(job: dict, preset: str) -> dict:
    # Documented as objects ({alpha2, name, slug}); the live feed has sent plain strings.
    places = [p.get("name", "") if isinstance(p, dict) else str(p) for p in job.get("locationRestrictions") or []]
    scope = ", ".join(p for p in places if p) or "Worldwide"
    url = job.get("applicationLink") or job.get("guid") or ""
    tracked = job_store.find_matching_job(job.get("companyName") or "", job.get("title") or "", url)
    return {
        "id": "hm-" + hashlib.sha1((job.get("guid") or url).encode()).hexdigest()[:20],  # ids are 64 chars at most
        "preset": f"himalayas-{preset}",
        "source": "Himalayas",
        "company": (job.get("companyName") or "").strip() or "Unknown",
        "role": (job.get("title") or "").strip() or "Unknown",
        "url": url,
        "location": scope,
        "remote_scope": scope,
        "open_to_canada": any(word in scope.lower() for word in _CANADA_OK),
        "visa": None,
        "experience": ", ".join(job.get("seniority") or []),
        "salary": _salary(job),
        "posted": time.strftime("%Y-%m-%d", time.gmtime(job["pubDate"])) if job.get("pubDate") else "",
        "jd_text": _text(job.get("description", "")),
        "tracked_dossier": tracked.id if tracked else None,
    }


def _search(preset: dict, fetch: Callable[[dict], dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for country in preset["countries"]:
        for query in preset["queries"]:
            for page in range(1, MAX_PAGES + 1):
                params = {"q": query, "seniority": preset["seniority"], "sort": "recent", "page": page}
                if country:
                    params["country"] = country
                if preset.get("worldwide"):
                    params["worldwide"] = "true"
                jobs = fetch(params).get("jobs", [])
                if not jobs:
                    break
                for job in jobs:
                    seen.setdefault(job.get("guid") or job.get("applicationLink") or "", job)
                time.sleep(PAUSE_SECONDS)
    return list(seen.values())


def run_search(preset: str, fetch: Callable[[dict], dict] | None = None) -> dict:
    """Stage new Himalayas finds for a preset. Returns counts and the new items."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    key = "" if fetch else _key()
    jobs = _search(PRESETS[preset], fetch or (lambda params: _get(params, key)))
    new, duplicates, skipped = [], [], 0
    for job in jobs:
        if _SENIOR.search(job.get("title") or ""):
            skipped += 1
            continue
        item, created = research_store.add(to_research(job, preset))
        if created and not item["tracked_dossier"]:
            new.append({"id": item["id"], "company": item["company"], "role": item["role"],
                        "open_to_canada": item["open_to_canada"], "salary": item["salary"]})
        else:
            duplicates.append(f"{item['company']} | {item['role']}")
    return {"fetched": len(jobs), "new": new, "duplicates": duplicates, "senior_skipped": skipped}
