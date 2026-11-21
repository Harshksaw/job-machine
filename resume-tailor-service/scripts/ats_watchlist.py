"""Poll configured public ATS boards and stage untracked roles for research.

    cd resume-tailor-service
    python scripts/ats_watchlist.py --companies content/ats_watchlist.yaml

The watchlist is intentionally discovery only. It reads the public Greenhouse,
Lever, and Ashby posting APIs, compares each posting with the current dossier
summaries, then stages only new listings through ``POST /api/research``. It
never captures a dossier, generates a kit, or submits an application.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.job_store import canonical_job_url  # noqa: E402

API_URL = "http://127.0.0.1:8420"
USER_AGENT = "job-machine-ats-watchlist/1.0 (personal job search)"
PROVIDERS = {"greenhouse", "lever", "ashby"}


def _get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def _request_json(url: str, method: str = "GET", payload: dict | None = None) -> object:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Job-Machine": "dashboard",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def load_watchlist(path: Path) -> list[dict]:
    """Load and validate the editable company board list."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    boards = raw.get("boards", raw if isinstance(raw, list) else [])
    if not isinstance(boards, list):
        raise ValueError("watchlist must contain a 'boards' list")
    valid = []
    for index, board in enumerate(boards, 1):
        if not isinstance(board, dict):
            raise ValueError(f"board {index} must be a mapping")
        if board.get("enabled", True) is False:
            continue
        provider = str(board.get("provider", "")).lower()
        company = str(board.get("company", "")).strip()
        token = str(board.get("token", "")).strip()
        if provider not in PROVIDERS:
            raise ValueError(f"board {index}: provider must be one of {sorted(PROVIDERS)}")
        if not company or not token:
            raise ValueError(f"board {index}: company and token are required")
        valid.append({**board, "provider": provider, "company": company, "token": token})
    return valid


def _text(value: object) -> str:
    value = str(value or "")
    value = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", value, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"<[^>]+>", "", html.unescape(value))).strip()


def _join(values: object) -> str:
    if isinstance(values, list):
        return "; ".join(str(value) for value in values if value)
    return str(values or "")


def _posted(value: object) -> str:
    """Return an ISO date when an ATS uses an epoch timestamp, otherwise text."""
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    return str(value or "")[:10]


def greenhouse(board: dict, get_json: Callable[[str], object] = _get_json) -> list[dict]:
    data = get_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board['token']}/jobs?content=true"
    )
    return [
        {
            "company": board["company"], "role": job.get("title", ""),
            "url": job.get("absolute_url", ""), "source": "Greenhouse",
            "location": (job.get("location") or {}).get("name", ""),
            "posted": job.get("updated_at", "")[:10], "jd_text": _text(job.get("content")),
        }
        for job in data.get("jobs", [])
    ]


def lever(board: dict, get_json: Callable[[str], object] = _get_json) -> list[dict]:
    data = get_json(f"https://api.lever.co/v0/postings/{board['token']}?mode=json")
    return [
        {
            "company": board["company"], "role": job.get("text", ""),
            "url": job.get("hostedUrl", ""), "source": "Lever",
            "location": _join((job.get("categories") or {}).get("location")),
            "posted": _posted(job.get("createdAt")),
            "jd_text": _text(job.get("descriptionPlain") or job.get("description")),
        }
        for job in data
    ]


def ashby(board: dict, get_json: Callable[[str], object] = _get_json) -> list[dict]:
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board['token']}")
    return [
        {
            "company": board["company"], "role": job.get("title", ""),
            "url": job.get("jobUrl") or f"https://jobs.ashbyhq.com/{board['token']}/{job.get('id', '')}",
            "source": "Ashby", "location": _join(job.get("location")),
            "posted": job.get("publishedAt", "")[:10],
            "jd_text": _text(job.get("descriptionPlain") or job.get("descriptionHtml")),
        }
        for job in data.get("jobs", [])
    ]


HARVESTERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}


def _key(company: str, role: str) -> tuple[str, str]:
    clean = lambda value: " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))
    return clean(company), clean(role)


def untracked(rows: list[dict], dossiers: list[dict]) -> tuple[list[dict], int]:
    """Exclude existing dossiers and duplicates returned by more than one board."""
    urls = {canonical_job_url(job.get("job_url", "")) for job in dossiers}
    keys = {_key(job.get("company", ""), job.get("role", "")) for job in dossiers}
    seen_urls, seen_keys, new = set(), set(), []
    duplicates = 0
    for row in rows:
        url, key = canonical_job_url(row.get("url", "")), _key(row.get("company", ""), row.get("role", ""))
        if not row.get("role", "").strip() or not url or url in urls or key in keys or url in seen_urls or key in seen_keys:
            duplicates += 1
            continue
        seen_urls.add(url)
        seen_keys.add(key)
        new.append(row)
    return new, duplicates


def poll(
    boards: list[dict], api_url: str = API_URL, *, dry_run: bool = False,
    get_json: Callable[[str], object] = _get_json,
    request_json: Callable[[str, str, dict | None], object] = _request_json,
) -> dict:
    """Fetch boards, dedupe against current dossiers, and stage new research rows."""
    if not boards:
        return {"fetched": 0, "new": 0, "duplicates": 0, "staged": 0, "failures": []}
    rows, failures = [], []
    for board in boards:
        try:
            rows.extend(HARVESTERS[board["provider"]](board, get_json))
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            failures.append(f"{board['company']} ({board['provider']}): {error}")
    dossiers = request_json(f"{api_url.rstrip('/')}/api/jobs", "GET", None)
    new, duplicates = untracked(rows, dossiers)
    staged = []
    if not dry_run:
        for row in new:
            payload = {**row, "preset": "ats-watchlist", "notes": "Public ATS watchlist discovery."}
            result = request_json(f"{api_url.rstrip('/')}/api/research", "POST", payload)
            if result.get("created"):
                staged.append(result["item"])
    return {"fetched": len(rows), "new": len(new), "duplicates": duplicates, "staged": len(staged), "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--companies", type=Path, default=Path("content/ats_watchlist.yaml"))
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--dry-run", action="store_true", help="fetch and dedupe without staging")
    args = parser.parse_args()
    result = poll(load_watchlist(args.companies), args.api_url, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
