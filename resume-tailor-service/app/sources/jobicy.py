"""Jobicy remote jobs API (https://jobicy.com/api/v2/remote-jobs).

Public JSON, no key. `geo=canada` is the feed this preset uses. One request per
industry, with a pause between them. Stages finds and does not create dossiers.

    from app.sources import jobicy
    jobicy.run_search("canada")
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from app import job_store, research_store

API = "https://jobicy.com/api/v2/remote-jobs"
USER_AGENT = "job-machine/1.0 (personal job search)"
PAUSE_SECONDS = 1.0

PRESETS: dict[str, dict] = {
    "canada": {
        "label": "Jobicy: Canada remote engineering",
        "geo": "canada",
        "industries": ["engineering", "dev", "data-science"],
        "count": 50,
    },
}

_CANADA_OK = ("canada", "north america", "americas", "worldwide", "anywhere", "global")
_SENIOR = re.compile(r"senior|staff|principal|lead|manager|director|head|\bsr\b", re.I)


class JobicyError(RuntimeError):
    pass


def _text(markup: str) -> str:
    markup = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
    markup = re.sub(r"<[^>]+>", "", markup)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(markup)).strip()


def _salary(low, high, currency, period) -> str:
    if not low and not high:
        return ""
    return f"{currency or ''} {low or '?'} to {high or '?'} per {period or 'year'}".strip()


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        raise JobicyError(
            f"Jobicy HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}"
        ) from err


def _open_to_canada(location: str) -> bool:
    text = (location or "").strip().lower()
    if not text:
        return True
    return any(word in text for word in _CANADA_OK)


def to_research(job: dict, preset: str) -> dict:
    url = (job.get("url") or "").strip()
    location = (job.get("jobGeo") or "").strip()
    company = (job.get("companyName") or "").strip() or "Unknown"
    role = html.unescape((job.get("jobTitle") or "").strip()) or "Unknown"
    tracked = job_store.find_matching_job(company, role, url)
    return {
        "id": "jc-" + hashlib.sha1(url.encode()).hexdigest()[:20],
        "preset": f"jobicy-{preset}",
        "source": "Jobicy",
        "company": company,
        "role": role,
        "url": url,
        "location": location or "Canada",
        "remote_scope": location or "Canada",
        "open_to_canada": _open_to_canada(location or "canada"),
        "visa": None,
        "experience": (job.get("jobLevel") or "").strip(),
        "salary": _salary(
            job.get("salaryMin"), job.get("salaryMax"),
            job.get("salaryCurrency"), job.get("salaryPeriod"),
        ),
        "posted": (job.get("pubDate") or "")[:10],
        "jd_text": _text(job.get("jobDescription", "")),
        "tracked_dossier": tracked.id if tracked else None,
    }


def _url(preset: dict, industry: str) -> str:
    query = urllib.parse.urlencode({
        "count": preset["count"], "geo": preset["geo"], "industry": industry,
    })
    return f"{API}?{query}"


def run_search(preset: str, fetch: Callable[[str], dict] | None = None) -> dict:
    """Stage new Jobicy finds for a preset. Returns counts and the new items."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    chosen = PRESETS[preset]
    getter = fetch or _get
    seen: dict[str, dict] = {}
    for index, industry in enumerate(chosen["industries"]):
        if index and PAUSE_SECONDS:
            time.sleep(PAUSE_SECONDS)
        for job in getter(_url(chosen, industry)).get("jobs", []):
            seen.setdefault(job.get("url") or str(job.get("id") or ""), job)
    new, duplicates, skipped = [], [], 0
    for job in seen.values():
        title = html.unescape(job.get("jobTitle") or "")
        level = job.get("jobLevel") or ""
        if _SENIOR.search(title) or (_SENIOR.search(level) and "entry" not in level.lower()):
            skipped += 1
            continue
        item, created = research_store.add(to_research(job, preset))
        if created and not item["tracked_dossier"]:
            new.append({
                "id": item["id"], "company": item["company"], "role": item["role"],
                "open_to_canada": item["open_to_canada"], "salary": item["salary"],
            })
        else:
            duplicates.append(f"{item['company']} | {item['role']}")
    return {"fetched": len(seen), "new": new, "duplicates": duplicates, "senior_skipped": skipped}
