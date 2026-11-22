"""Remote OK public jobs API (https://remoteok.com/api).

The first row of the feed is Remote OK's terms notice, not a job, and is dropped.
Their terms ask that Remote OK be credited as the source, so every staged item
uses source "Remote OK". No key. Stages finds and does not create dossiers.

    from app.sources import remote_ok
    remote_ok.run_search("software")
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

API = "https://remoteok.com/api"
USER_AGENT = "job-machine/1.0 (personal job search)"
SOURCE = "Remote OK"

PRESETS: dict[str, dict] = {
    "software": {
        "label": "Remote OK: software roles",
    },
}

_CANADA_OK = ("canada", "north america", "americas", "worldwide", "anywhere", "global")
_SENIOR = re.compile(r"senior|staff|principal|lead|manager|director|head|\bsr\b", re.I)
_ENGINEERING = re.compile(
    r"engineer|developer|programmer|software|full.?stack|back.?end|front.?end|\bml\b|\bai\b|"
    r"machine learning|data engineer|devops|platform|sre\b",
    re.I,
)


class RemoteOkError(RuntimeError):
    pass


def _text(markup: str) -> str:
    markup = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", markup or "", flags=re.I)
    markup = re.sub(r"<[^>]+>", "", markup)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(markup)).strip()


def _salary(low, high) -> str:
    if not low and not high:
        return ""
    return f"USD {low or '?'} to {high or '?'} per year"


def _get() -> list:
    request = urllib.request.Request(API, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        raise RemoteOkError(
            f"Remote OK HTTP {err.code}: {err.read()[:200].decode('utf-8', 'replace')}"
        ) from err


def _open_to_canada(location: str) -> bool:
    text = (location or "").strip().lower()
    if not text:
        return True
    return any(word in text for word in _CANADA_OK)


def to_research(job: dict, preset: str) -> dict:
    url = (job.get("url") or "").strip()
    location = (job.get("location") or "").strip()
    company = (job.get("company") or "").strip() or "Unknown"
    role = (job.get("position") or "").strip() or "Unknown"
    tracked = job_store.find_matching_job(company, role, url)
    posted = (job.get("date") or "")[:10]
    return {
        "id": "ro-" + hashlib.sha1((url or str(job.get("id") or "")).encode()).hexdigest()[:20],
        "preset": f"remote-ok-{preset}",
        "source": SOURCE,
        "company": company,
        "role": role,
        "url": url,
        "location": location or "Worldwide",
        "remote_scope": location or "Worldwide",
        "open_to_canada": _open_to_canada(location),
        "visa": None,
        "experience": "",
        "salary": _salary(job.get("salary_min"), job.get("salary_max")),
        "posted": posted,
        "jd_text": _text(job.get("description", "")),
        "tracked_dossier": tracked.id if tracked else None,
    }


def run_search(preset: str, fetch: Callable[[], list] | None = None) -> dict:
    """Stage new Remote OK finds for a preset. Returns counts and the new items.

    Remote OK wants credit as the source. `source` on every item is "Remote OK".
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    rows = (fetch or _get)()
    jobs = [row for row in rows if isinstance(row, dict) and row.get("position")]
    new, duplicates, skipped = [], [], 0
    for job in jobs:
        title = job.get("position") or ""
        if not _ENGINEERING.search(title) or _SENIOR.search(title):
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
    return {
        "fetched": len(jobs), "new": new, "duplicates": duplicates, "senior_skipped": skipped,
    }
