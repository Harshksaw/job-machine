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
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import job_store
from app.models import JobCaptureInput

API = "https://data.fantastic.jobs/v1/active-ats"
USAGE_PATH = Path(__file__).resolve().parent.parent / "data" / "fantastic_usage.json"
TRIAL = {"jobs": 500, "requests": 100}
MAX_LIMIT = 50

_TITLE = (
    "(software | developer | engineer | full <-> stack | backend | frontend | "
    "machine <-> learning | AI | applied <-> AI | forward <-> deployed) & "
    "!(senior | staff | principal | lead | manager | director | head)"
)
_BASE = {
    "title_advanced": _TITLE,
    "ai_experience_level": "0-2,2-5",
    "ai_employment_type": "FULL_TIME",
    "organization_agency": "exclude",
    "description_format": "text",
}
PRESETS: dict[str, dict] = {
    "canada": {
        "label": "Canada, early career engineering",
        "params": {**_BASE, "location_advanced": "Canada"},
    },
    "remote-na": {
        "label": "Remote in Canada or US, early career",
        "params": {
            **_BASE,
            "location_advanced": "Canada | United States",
            "ai_work_arrangement": "Remote Solely,Remote OK",
        },
    },
    "us-sponsor": {
        "label": "US roles that sponsor visas, new grad",
        "params": {
            **_BASE,
            "location_advanced": "United States",
            "ai_experience_level": "0-2",
            "ai_visa_sponsorship": "only",
        },
    },
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
        new, duplicates = [], []
        for job in jobs:
            capture = to_capture(job, session)
            if job_store.find_matching_job(capture.company, capture.role, capture.job_url):
                duplicates.append(f"{capture.company} | {capture.role}")
                continue
            created, _ = job_store.capture_job(capture)
            new.append({"id": created.id, "company": created.company, "role": created.role})
        usage["runs"].append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "preset": preset, "fetched": len(jobs), "new": len(new),
        })
        _save_usage(usage)
    return {"fetched": len(jobs), "new": new, "duplicates": duplicates, "usage": usage_summary()}
