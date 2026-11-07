"""Check whether job postings behind dossiers are still open, without a browser or an LLM.

    uv run python scripts/check_liveness.py <candidates.json> <results.json>

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
import json
import re
import sys
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "job-machine-liveness/1.0 (personal job search)"}
_ashby_boards: dict[str, set | None] = {}


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


def main() -> None:
    candidates = json.load(open(sys.argv[1]))
    results = {}
    for n, item in enumerate(candidates, 1):
        state, evidence = check(item.get("url", ""))
        results[item["id"]] = {"state": state, "evidence": evidence, "url": item.get("url")}
        if n % 25 == 0:
            print(f"{n}/{len(candidates)}", flush=True)
    json.dump(results, open(sys.argv[2], "w"), indent=1)
    counts: dict[str, int] = {}
    for value in results.values():
        counts[value["state"]] = counts.get(value["state"], 0) + 1
    print(counts)


if __name__ == "__main__":
    main()
