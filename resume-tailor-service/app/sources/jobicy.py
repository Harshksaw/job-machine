"""Jobicy remote jobs API (https://jobicy.com/api/v2/remote-jobs).

Public JSON, no key. No `geo` filter: every region comes back and
`app.regions.classify_location` tiers each find (A, A2, E for Europe; India based finds are
not staged and are counted under `dropped`). One request per industry, with a pause between
them. Stages finds and does not create dossiers.

    from app.sources import jobicy
    jobicy.run_search("remote")
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
from app.regions import tag_item

API = "https://jobicy.com/api/v2/remote-jobs"
USER_AGENT = "job-machine/1.0 (personal job search)"
PAUSE_SECONDS = 1.0

PRESETS: dict[str, dict] = {
    "remote": {
        "label": "Jobicy: remote engineering, all regions (tiered locally)",
        "industries": ["engineering", "dev", "data-science"],
        "count": 50,
    },
}

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


def to_research(job: dict, preset: str) -> dict:
    url = (job.get("url") or "").strip()
    location = (job.get("jobGeo") or "").strip()
    company = (job.get("companyName") or "").strip() or "Unknown"
    role = html.unescape((job.get("jobTitle") or "").strip()) or "Unknown"
    tracked = job_store.find_matching_job(company, role, url)
    item = {
        "id": "jc-" + hashlib.sha1(url.encode()).hexdigest()[:20],
        "preset": f"jobicy-{preset}",
        "source": "Jobicy",
        "company": company,
        "role": role,
        "url": url,
        "location": location,
        "remote_scope": location,
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
    tag_item(item)  # tier, region and open_to_canada from app.regions
    return item


def _url(preset: dict, industry: str) -> str:
    query = urllib.parse.urlencode({"count": preset["count"], "industry": industry})
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
    dropped: dict[str, int] = {}
    for job in seen.values():
        title = html.unescape(job.get("jobTitle") or "")
        level = job.get("jobLevel") or ""
        if _SENIOR.search(title) or (_SENIOR.search(level) and "entry" not in level.lower()):
            skipped += 1
            continue
        item = to_research(job, preset)
        where = tag_item(item)
        if where.tier == "drop":  # India, or not remote
            dropped[where.reason] = dropped.get(where.reason, 0) + 1
            continue
        item, created = research_store.add(item)
        if created and not item["tracked_dossier"]:
            new.append({
                "id": item["id"], "company": item["company"], "role": item["role"],
                "open_to_canada": item["open_to_canada"],
                "tier": item["tier"], "region": item["region"], "salary": item["salary"],
            })
        else:
            duplicates.append(f"{item['company']} | {item['role']}")
    return {"fetched": len(seen), "new": new, "duplicates": duplicates, "dropped": dropped, "senior_skipped": skipped}
