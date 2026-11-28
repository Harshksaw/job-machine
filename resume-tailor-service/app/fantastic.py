"""Fantastic Jobs (data.fantastic.jobs) search with a hard budget for the free trial.

The trial allows 500 jobs and 100 requests over 14 days, billed per job returned, so:

- every search is a preset tuned to his eligibility (AGENTS.md): early career, Canada or
  remote North America, no agencies, full time;
- each run asks for a small `limit` and refuses to start if it would cross the budget;
- results are deduped against the dossier store before capture, and only new listings
  are captured, as `discovered` with the full description.

Usage is counted locally in data/fantastic_usage.json because the trial has no usage
endpoint we rely on. Set FANTASTIC_JOBS_API_KEY in .env.
"""
from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import job_store, research_store
from app.models import JobCaptureInput
from app.regions import Classification, classify_location, is_india, open_to_canada

API = "https://data.fantastic.jobs/v1/active-ats"
USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "fantastic_usage.json"
TRIAL = {"jobs": 500, "requests": 100}
MAX_LIMIT = 50

_TITLE = (
    "(software | developer | full <-> stack | backend | frontend | "
    "machine <-> learning | AI | applied <-> AI | forward <-> deployed) & "
    "!(senior | staff | principal | lead | manager | director | head | founding | "
    "support | sales | customer | solutions | GTM | QA | test | consultant | trainer | "
    "mechanical | industrial | manufacturing | hardware | field | success | specialist | "
    "intern | internship)"
)
# Every *_advanced value is a tsquery: a space inside a name is a syntax error (400, "Invalid
# syntax in advanced search expression"), so a multi word place needs <-> ("United <-> States").
_BASE = {
    "title_advanced": _TITLE,
    "ai_employment_type": "FULL_TIME",
    "organization_agency": "exclude",
    "ai_work_arrangement": "Remote Solely",
    "description_format": "text",
}
# Remote only, in this order of priority: Canada, US, UK, Australia, then Europe last
# (AGENTS.md). Every find is tiered by app.regions (A, A2, E; India dropped). No experience level
# filter (the title filter still drops senior and above) and no hybrid. Small companies are
# approximated by the ATSes they use; `is_big_company` sets the rest aside.
_SMALL_ATS = "ashby,lever,workable"
PRESETS: dict[str, dict] = {
    "remote-ca": {
        "label": "Remote Canada (first priority)",
        "default_limit": 25,
        "params": {**_BASE, "location_advanced": "Canada", "source": _SMALL_ATS},
    },
    "remote-us": {
        "label": "Research: remote US",
        "stage": "research",
        "default_limit": 25,
        "params": {**_BASE, "location_advanced": "United <-> States", "source": _SMALL_ATS},
    },
    "remote-au": {
        "label": "Research: remote Australia",
        "stage": "research",
        "default_limit": 10,
        "params": {**_BASE, "location_advanced": "Australia", "source": _SMALL_ATS},
    },
    "remote-uk": {
        "label": "Research: remote UK",
        "stage": "research",
        "default_limit": 10,
        "params": {**_BASE, "location_advanced": "United <-> Kingdom", "source": _SMALL_ATS},
    },
    "remote-eu": {
        "label": "Research: remote Europe",
        "stage": "research",
        "default_limit": 15,
        "params": {**_BASE, "location_advanced": "Europe | Germany | France | Netherlands | "
                   "Ireland | Spain | Portugal | Poland | Sweden | Denmark | Switzerland",
                   "source": _SMALL_ATS},
    },
}

BIG_COMPANY_EMPLOYEES = 1000
_BIG_NAMES = {
    "google", "alphabet", "amazon", "aws", "microsoft", "meta", "apple", "netflix", "oracle",
    "ibm", "salesforce", "adobe", "intel", "nvidia", "cisco", "sap", "dell", "vmware", "uber",
    "lyft", "airbnb", "stripe", "shopify", "paypal", "ebay", "linkedin", "tesla", "spotify",
    "accenture", "deloitte", "pwc", "kpmg", "ey", "capgemini", "infosys", "tcs", "wipro",
    "cognizant", "rbc", "td", "bmo", "scotiabank", "cibc", "jpmorgan", "goldman sachs",
    "morgan stanley", "citi", "wells fargo", "bank of america", "openai", "anthropic",
    "databricks", "snowflake", "atlassian", "workday", "servicenow", "intuit", "walmart",
}


_TOO_SENIOR = re.compile(r"senior|\bsr\b|staff|principal|\blead\b|manager|director|head of", re.I)


def _offices(job: dict) -> str:
    locations = job.get("locations_derived") or []
    return "; ".join(str(p) for p in locations) if isinstance(locations, list) else str(locations)


def classify(job: dict) -> Classification:
    """Tier a find with app.regions. The remote scope decides the place; the office list
    (locations_derived) and the description say where the company is based. Any India
    office drops the find (nothing based in India, even next to another region). Only a
    company whose offices are all in Europe is a European company (Tier E); one Berlin
    office next to a US head office is not."""
    raw = _raw_scope(job)
    offices = _offices(job)
    if is_india(offices):
        return classify_location("India")
    where = classify_location(raw or offices, description=job.get("description_text") or "")
    places = [p for p in (job.get("locations_derived") or []) if str(p).strip()] \
        if isinstance(job.get("locations_derived"), list) else [offices] if offices else []
    european = bool(places) and all(classify_location(str(p)).region == "europe" for p in places)
    if where.tier in ("A", "A2") and european:
        return classify_location("Europe")
    return where


def is_big_company(job: dict) -> str:
    """Reason this employer is a big name (empty string when it looks small)."""
    name = (job.get("organization") or "").strip().lower()
    if name in _BIG_NAMES or any(name.startswith(f"{n} ") for n in _BIG_NAMES):
        return "big name"
    for key in ("linkedin_org_employees", "linkedin_org_size"):
        value = job.get(key)
        if isinstance(value, (int, float)):
            employees = int(value)
        else:
            nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", str(value or ""))]
            employees = min(nums) if nums else 0
        if employees >= BIG_COMPANY_EMPLOYEES:
            return f"{employees}+ employees"
    return ""


def _raw_scope(job: dict) -> str:
    parts = job.get("ai_remote_location_derived") or job.get("ai_remote_location") or []
    if isinstance(parts, str):
        parts = [parts]
    requirements = job.get("location_requirements") or []
    if isinstance(requirements, str):
        requirements = [requirements]
    return "; ".join(str(p) for p in [*parts, *requirements] if p)


def remote_scope(job: dict) -> tuple[str, bool]:
    """Where the employer lets remote hires live, and whether Canada fits (app.regions)."""
    raw = _raw_scope(job)
    return raw or "unspecified", bool(raw) and open_to_canada(raw)


def to_research(job: dict, preset: str) -> dict:
    scope, canada_ok = remote_scope(job)
    if not _raw_scope(job):  # no scope given: the office list is the only place we have
        canada_ok = open_to_canada(_offices(job))
    where = classify(job)
    capture = to_capture(job, "")
    tracked = job_store.find_matching_job(capture.company, capture.role, capture.job_url)
    return {
        "id": f"fj-{job.get('id')}",
        "preset": preset,
        "source": capture.source,
        "company": capture.company,
        "role": capture.role,
        "url": capture.job_url,
        "location": capture.location,
        "remote_scope": scope,
        "open_to_canada": canada_ok,
        "tier": where.tier,
        "region": where.region,
        "visa": job.get("ai_visa_sponsorship"),
        "experience": job.get("ai_experience_level"),
        "salary": " ".join(str(job.get(k) or "") for k in ("ai_salary_min_value", "ai_salary_max_value", "ai_salary_currency")).strip(),
        "posted": (job.get("date_posted") or "")[:10],
        "jd_text": capture.jd_text,
        "tracked_dossier": tracked.id if tracked else None,
    }

_lock = threading.Lock()


def load_usage() -> dict:
    if USAGE_PATH.exists():
        return json.loads(USAGE_PATH.read_text())
    return {"jobs_used": 0, "requests_used": 0, "runs": []}


def usage_summary() -> dict:
    usage = load_usage()
    return {
        "jobs_used": usage["jobs_used"],
        "requests_used": usage["requests_used"],
        "jobs_left": TRIAL["jobs"] - usage["jobs_used"],
        "requests_left": TRIAL["requests"] - usage["requests_used"],
        "configured": bool(os.environ.get("FANTASTIC_JOBS_API_KEY", "").strip()),
        "runs": usage["runs"][-10:],
    }


def _save_usage(usage: dict) -> None:
    USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USAGE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(usage, indent=1))
    tmp.replace(USAGE_PATH)


def _fetch(params: dict) -> list[dict]:
    key = os.environ.get("FANTASTIC_JOBS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("FANTASTIC_JOBS_API_KEY is not set in resume-tailor-service/.env")
    req = urllib.request.Request(
        f"{API}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Bearer {key}", "User-Agent": "job-machine/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    return body if isinstance(body, list) else body.get("jobs", body.get("data", []))


def _work_mode(job: dict) -> str:
    arrangement = job.get("ai_work_arrangement") or ""
    return "remote" if "Remote" in arrangement else arrangement.lower()


def to_capture(job: dict, session: str) -> JobCaptureInput:
    locations = job.get("locations_derived") or []
    where = classify(job)
    return JobCaptureInput(
        company=(job.get("organization") or "").strip() or "Unknown",
        role=(job.get("title") or "").strip() or "Unknown",
        job_url=job.get("url") or "",
        source=f"Fantastic Jobs ({job.get('source') or 'ats'})",
        location="; ".join(locations[:3]) if isinstance(locations, list) else str(locations),
        work_mode=_work_mode(job),
        status="discovered",
        jd_text=job.get("description_text") or "",
        notes=(
            f"Fantastic Jobs id {job.get('id')}, posted {(job.get('date_posted') or '')[:10]}, "
            f"Tier {where.tier} ({where.region}), "
            f"experience {job.get('ai_experience_level') or '?'}, "
            f"visa sponsorship {job.get('ai_visa_sponsorship')}. Needs a fit score."
        ),
        next_action="Score fit (AGENTS.md rule 2)",
        session=session,
    )


def run_search(
    preset: str,
    limit: int = 25,
    time_frame: str = "7d",
    fetch: Callable[[dict], list[dict]] = _fetch,
) -> dict:
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}")
    limit = max(1, min(int(limit), MAX_LIMIT))
    if time_frame not in ("1h", "24h", "7d"):
        raise ValueError("time_frame must be 1h, 24h or 7d")
    with _lock:
        usage = load_usage()
        if usage["requests_used"] + 1 > TRIAL["requests"]:
            raise ValueError("Fantastic Jobs request budget is used up")
        if usage["jobs_used"] + limit > TRIAL["jobs"]:
            raise ValueError(
                f"only {TRIAL['jobs'] - usage['jobs_used']} trial jobs left; lower the limit")
        jobs = fetch({**PRESETS[preset]["params"], "time_frame": time_frame, "limit": limit})
        usage["requests_used"] += 1
        usage["jobs_used"] += len(jobs)
        session = f"Fantastic Jobs {datetime.now(timezone.utc):%Y-%m-%d}"
        new, duplicates, aside = [], [], []
        dropped: dict[str, int] = {}
        staged = PRESETS[preset].get("stage") == "research"
        for job in jobs:
            if _TOO_SENIOR.search(job.get("title") or ""):
                continue
            where = classify(job)
            if where.tier == "drop":  # India, or not remote
                dropped[where.reason] = dropped.get(where.reason, 0) + 1
                continue
            reason = is_big_company(job)
            if reason:
                # Keep it aside, deduped and visible, but out of the queue and out of the way.
                item = to_research(job, preset)
                item["status"] = "dismissed"
                item["aside_reason"] = reason
                research_store.add(item)
                aside.append(f"{item['company']} ({reason})")
            elif staged:
                item, created = research_store.add(to_research(job, preset))
                if created and not item["tracked_dossier"]:
                    new.append({"id": item["id"], "company": item["company"], "role": item["role"],
                                "open_to_canada": item["open_to_canada"],
                                "tier": item.get("tier"), "region": item.get("region")})
                else:
                    duplicates.append(f"{item['company']} | {item['role']}")
            else:
                capture = to_capture(job, session)
                if job_store.find_matching_job(capture.company, capture.role, capture.job_url):
                    duplicates.append(f"{capture.company} | {capture.role}")
                    continue
                created, _ = job_store.capture_job(capture)
                new.append({"id": created.id, "company": created.company, "role": created.role})
        usage["runs"].append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "preset": preset, "fetched": len(jobs), "new": len(new), "aside": len(aside),
            "stage": PRESETS[preset].get("stage", "dossier"),
        })
        _save_usage(usage)
    return {"fetched": len(jobs), "new": new, "aside": aside, "duplicates": duplicates, "dropped": dropped,
            "usage": usage_summary()}
