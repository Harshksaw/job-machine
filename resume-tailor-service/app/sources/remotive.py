"""Remotive remote jobs API (https://remotive.com/api/remote-jobs).

One public JSON feed per category. No key. A named User-Agent is required; the bare
urllib client is refused. This module stages finds and does not create dossiers.

    from app.sources import remotive
    remotive.run_search("software")
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

API = "https://remotive.com/api/remote-jobs"
USER_AGENT = "job-machine/1.0 (personal job search)"
PAUSE_SECONDS = 2.0  # Remotive asks callers not to poll the feed

PRESETS: dict[str, dict] = {
    "software": {
        "label": "Remotive: software development",
        "categories": ["software-dev"],
    },
    "data-devops": {
        "label": "Remotive: data and devops",
        "categories": ["data", "devops"],
    },
}

_CANADA_OK = ("canada", "north america", "americas", "worldwide", "anywhere", "global")
_SENIOR = re.compile(r"senior|staff|principal|lead|manager|director|head|\bsr\b", re.I)


class RemotiveError(RuntimeError):
    pass


def _text(markup: str) -> str:
    markup = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
    markup = re.sub(r"<[^>]+>", "", markup)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(markup)).strip()


def _get(category: str) -> dict:
    request = urllib.request.Request(
        f"{API}?category={urllib.parse.quote(category)}",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        raise RemotiveError(
            f"Remotive HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}"
        ) from err


def _open_to_canada(location: str) -> bool:
    text = (location or "").strip().lower()
    if not text:
        return True
    return any(word in text for word in _CANADA_OK)


def to_research(job: dict, preset: str) -> dict:
    url = (job.get("url") or "").strip()
    location = (job.get("candidate_required_location") or "").strip()
    company = (job.get("company_name") or "").strip() or "Unknown"
    role = (job.get("title") or "").strip() or "Unknown"
    tracked = job_store.find_matching_job(company, role, url)
    return {
        "id": "rm-" + hashlib.sha1(url.encode()).hexdigest()[:20],
        "preset": f"remotive-{preset}",
        "source": "Remotive",
        "company": company,
        "role": role,
        "url": url,
        "location": location or "Worldwide",
        "remote_scope": location or "Worldwide",
        "open_to_canada": _open_to_canada(location),
        "visa": None,
        "experience": "",
        "salary": (job.get("salary") or "").strip(),
        "posted": (job.get("publication_date") or "")[:10],
        "jd_text": _text(job.get("description", "")),
        "tracked_dossier": tracked.id if tracked else None,
    }


def run_search(preset: str, fetch: Callable[[str], dict] | None = None) -> dict:
    """Stage new Remotive finds for a preset. Returns counts and the new items."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    getter = fetch or _get
    seen: dict[str, dict] = {}
    categories = PRESETS[preset]["categories"]
    for index, category in enumerate(categories):
        if index and PAUSE_SECONDS:
            time.sleep(PAUSE_SECONDS)
        for job in getter(category).get("jobs", []):
            seen.setdefault(job.get("url") or str(job.get("id") or ""), job)
    new, duplicates, skipped = [], [], 0
    for job in seen.values():
        if _SENIOR.search(job.get("title") or ""):
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
