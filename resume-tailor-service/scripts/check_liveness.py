"""Check whether job postings behind dossiers are still open, without a browser or an LLM.

    uv run python scripts/check_liveness.py <candidates.json> <results.json>
    uv run python scripts/check_liveness.py --service-url http://127.0.0.1:8420 \
        --report /path/to/liveness-report.json

<candidates.json> is a list of {"id", "url"}. Each posting is checked on its own site:

- LinkedIn: the public jobs-guest posting endpoint. A 404, or the "No longer accepting
  applications" banner, means closed.
- Greenhouse / Lever: the public posting API. 404 means closed.
- Ashby: the org's public job board; a posting id missing from it means closed.
- Y Combinator: the job page. 404, or a redirect off the job id, means closed.

Anything else (Wellfound blocks scripts, Indeed, company sites) and any rate limit or
network error comes back "unknown". Only "closed" is evidence a posting is gone, so a
cleanup must never delete on "unknown".
"""
import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "job-machine-liveness/1.0 (personal job search)"}
_ashby_boards: dict[str, set | None] = {}
PROTECTED_STATUSES = {"applied", "interview", "offer", "rejected", "archived"}


def _get(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as error:
        return error.code, url, ""
    except Exception as error:  # network trouble is "unknown", never "closed"
        return 0, url, str(error)


def check(url: str) -> tuple[str, str]:
    url = url or ""
    if "linkedin.com" in url:
        match = re.search(r"(?:/view/(?:[^/?]*-)?|currentJobId=)(\d{8,})", url)
        if not match:
            return "unknown", "no LinkedIn job id in url"
        status, _, body = _get(
            f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{match.group(1)}")
        time.sleep(1.5)  # the guest endpoint rate limits fast
        if status == 404:
            return "closed", "linkedin 404"
        if status == 200:
            if "No longer accepting applications" in body:
                return "closed", "linkedin: no longer accepting applications"
            return "live", "linkedin 200"
        return "unknown", f"linkedin http {status}"
    match = re.search(r"greenhouse\.io/([\w-]+)/jobs/(\d+)", url)
    if match:
        status, _, _ = _get(
            f"https://boards-api.greenhouse.io/v1/boards/{match.group(1)}/jobs/{match.group(2)}")
        if status == 404:
            return "closed", "greenhouse 404"
        return ("live", "greenhouse 200") if status == 200 else ("unknown", f"greenhouse http {status}")
    match = re.search(r"jobs\.lever\.co/([\w-]+)/([0-9a-f-]{36})", url)
    if match:
        status, _, _ = _get(f"https://api.lever.co/v0/postings/{match.group(1)}/{match.group(2)}")
        if status == 404:
            return "closed", "lever 404"
        return ("live", "lever 200") if status == 200 else ("unknown", f"lever http {status}")
    match = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if match:
        org, posting = match.groups()
        if org not in _ashby_boards:
            status, _, body = _get(f"https://api.ashbyhq.com/posting-api/job-board/{org}")
            _ashby_boards[org] = (
                {job["id"] for job in json.loads(body).get("jobs", [])} if status == 200 else None)
        board = _ashby_boards[org]
        if board is None:
            return "unknown", "ashby board unavailable"
        return ("live", "on ashby board") if posting in board else ("closed", "not on ashby board")
    match = re.search(r"ycombinator\.com/companies/[^/]+/jobs/([\w-]+)", url)
    if match:
        status, final, _ = _get(url)
        if status == 404:
            return "closed", "yc 404"
        if status == 200 and match.group(1) not in final:
            return "closed", "yc redirected away from the job"
        return ("live", "yc 200") if status == 200 else ("unknown", f"yc http {status}")
    return "unknown", "no checker for this site"


def _api_request(url: str, *, method: str = "GET") -> tuple[int, str]:
    """Make a loopback service request without treating failures as closures."""
    request = urllib.request.Request(url, method=method, headers=UA)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "ignore")
    except Exception as error:
        return 0, str(error)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (AttributeError, ValueError):
        return None


def _nightly_candidates(jobs: list[dict], *, older_than_days: int) -> list[dict]:
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    candidates = []
    for job in jobs:
        if job.get("status") in PROTECTED_STATUSES or not job.get("job_url"):
            continue
        updated_at = _parse_timestamp(job.get("updated_at", ""))
        if updated_at is not None and updated_at <= cutoff:
            candidates.append({"id": job["id"], "url": job["job_url"]})
    return candidates


def run_nightly(
    service_url: str,
    *,
    older_than_days: int,
    dry_run: bool = False,
) -> dict:
    """Check stale, unapplied dossiers and delete only confirmed closed postings."""
    service_url = service_url.rstrip("/")
    status, body = _api_request(f"{service_url}/api/jobs")
    if status != 200:
        raise RuntimeError(f"could not list dossiers: http {status}: {body}")
    try:
        jobs = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("could not decode dossiers response") from error
    if not isinstance(jobs, list):
        raise RuntimeError("dossiers response was not a list")

    results: dict[str, dict] = {}
    for item in _nightly_candidates(jobs, older_than_days=older_than_days):
        state, evidence = check(item["url"])
        result = {"state": state, "evidence": evidence, "url": item["url"]}
        # This is intentionally an equality test. Unknown, live, failed requests, and
        # any future state must retain their dossiers.
        if state == "closed" and not dry_run:
            delete_status, delete_body = _api_request(
                f"{service_url}/api/jobs/{item['id']}", method="DELETE"
            )
            if delete_status == 204:
                result["action"] = "deleted"
            else:
                result["action"] = "delete_failed"
                result["delete_evidence"] = f"http {delete_status}: {delete_body}"
        elif state == "closed":
            result["action"] = "would_delete"
        else:
            result["action"] = "retained"
        results[item["id"]] = result

    counts: dict[str, int] = {}
    for value in results.values():
        counts[value["state"]] = counts.get(value["state"], 0) + 1
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "eligible_count": len(results),
        "counts": counts,
        "results": results,
    }


def _write_json(path: str, payload: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", nargs="?", help="JSON list of {id, url}")
    parser.add_argument("results", nargs="?", help="where to write legacy check results")
    parser.add_argument("--service-url", help="dashboard URL for a nightly sweep")
    parser.add_argument("--report", help="where to write the nightly sweep report")
    parser.add_argument("--older-than-days", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.service_url:
        if args.candidates or args.results or not args.report:
            parser.error("nightly mode requires --service-url and --report only")
        if args.older_than_days < 1:
            parser.error("--older-than-days must be at least 1")
        report = run_nightly(
            args.service_url,
            older_than_days=args.older_than_days,
            dry_run=args.dry_run,
        )
        _write_json(args.report, report)
        print(report["counts"])
        return
    if not args.candidates or not args.results:
        parser.error("provide <candidates.json> <results.json> or --service-url with --report")

    candidates = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    results = {}
    for n, item in enumerate(candidates, 1):
        state, evidence = check(item.get("url", ""))
        results[item["id"]] = {"state": state, "evidence": evidence, "url": item.get("url")}
        if n % 25 == 0:
            print(f"{n}/{len(candidates)}", flush=True)
    _write_json(args.results, results)
    counts: dict[str, int] = {}
    for value in results.values():
        counts[value["state"]] = counts.get(value["state"], 0) + 1
    print(counts)


if __name__ == "__main__":
    main()
