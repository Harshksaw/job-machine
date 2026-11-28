"""Working Nomads public jobs feed (https://www.workingnomads.com/api/exposed_jobs/).

One JSON list, no key. The development preset keeps Development, Data, DevOps and
Machine Learning. Stages finds and does not create dossiers.

    from app.sources import working_nomads
    working_nomads.run_search("development")
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from typing import Callable

from app import job_store, research_store
from app.regions import tag_item

API = "https://www.workingnomads.com/api/exposed_jobs/"
USER_AGENT = "job-machine/1.0 (personal job search)"

PRESETS: dict[str, dict] = {
    "development": {
        "label": "Working Nomads: development and data",
        "categories": ["Development", "Data", "DevOps", "Machine Learning"],
    },
}

_SENIOR = re.compile(r"senior|staff|principal|lead|manager|director|head|\bsr\b", re.I)


class WorkingNomadsError(RuntimeError):
    pass


def _text(markup: str) -> str:
    markup = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
    markup = re.sub(r"<[^>]+>", "", markup)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(markup)).strip()


def _get() -> list:
    request = urllib.request.Request(API, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        raise WorkingNomadsError(
            f"Working Nomads HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}"
        ) from err


def to_research(job: dict, preset: str) -> dict:
    url = (job.get("url") or "").strip()
    location = (job.get("location") or "").strip()
    company = (job.get("company_name") or "").strip() or "Unknown"
    role = (job.get("title") or "").strip() or "Unknown"
    tracked = job_store.find_matching_job(company, role, url)
    item = {
        "id": "wn-" + hashlib.sha1(url.encode()).hexdigest()[:20],
        "preset": f"working-nomads-{preset}",
        "source": "Working Nomads",
        "company": company,
        "role": role,
        "url": url,
        "location": location or "Worldwide",
        "remote_scope": location or "Worldwide",
        "visa": None,
        "experience": (job.get("category_name") or "").strip(),
        "salary": "",
        "posted": (job.get("pub_date") or "")[:10],
        "jd_text": _text(job.get("description", "")),
        "tracked_dossier": tracked.id if tracked else None,
    }
    tag_item(item)  # tier, region and open_to_canada from app.regions
    return item


def run_search(preset: str, fetch: Callable[[], list] | None = None) -> dict:
    """Stage new Working Nomads finds for a preset. Returns counts and the new items."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    categories = set(PRESETS[preset]["categories"])
    jobs = (fetch or _get)()
    kept, skipped, off_category = [], 0, 0
    for job in jobs:
        if job.get("category_name") not in categories:
            off_category += 1
            continue
        if _SENIOR.search(job.get("title") or ""):
            skipped += 1
            continue
        kept.append(job)
    new, duplicates = [], []
    dropped: dict[str, int] = {}
    for job in kept:
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
    return {
        "fetched": len(jobs), "new": new, "duplicates": duplicates, "dropped": dropped,
        "senior_skipped": skipped, "off_category": off_category,
    }
