"""Write application outcomes found in email back to the dossiers.

    uv run python scripts/mail_outcomes.py <events.json> [--apply] [--include-uncertain]

<events.json> is a list of outcomes an agent read out of the inbox (the service has no
mail access of its own, so the reading is an agent step; see prompts/mail-sync.md):

    {"id": "<gmail message id>", "company": "...", "role": "...", "date": "YYYY-MM-DD",
     "outcome": "rejected|interview|assessment|reply", "confident": true, "note": "..."}

Each event is matched to a dossier by company name, then by role when a company has
more than one. Without --apply nothing is written: the script prints what it would do,
what it could not match, and what was ambiguous. With --apply each matched event becomes
a dossier activity keyed on the message id, so a rerun never writes the same email twice,
and the status moves to `rejected` or `interview`. Events marked `"confident": false`
(the snippet did not state the outcome) are held back unless --include-uncertain.

Unmatched events are never turned into dossiers here. They are applications made outside
the machine, and whether to track them is Harsh's call.
"""
import argparse
import json
import re
import sys
import urllib.request
from datetime import date

BASE = "http://127.0.0.1:8420"
# Words that vary between an employer's email signature and the dossier's company name.
_NOISE = {
    "inc", "llc", "ltd", "corp", "corporation", "co", "the", "team", "hiring",
    "labs", "lab", "technologies", "technology", "tech", "services", "ai", "hq",
}
_ROLE_NOISE = {"engineer", "software", "developer", "the", "and", "of", "at"}
_POST_APPLY = {"applying", "applied", "outreach", "interview", "offer", "rejected"}
# outcome -> (activity kind, status to set, statuses that outrank it)
_OUTCOMES = {
    "rejected": ("reply", "rejected", {"offer"}),
    "interview": ("interview", "interview", {"offer", "rejected"}),
    "assessment": ("interview", "interview", {"offer", "rejected"}),
    "reply": ("reply", None, set()),
}


def _call(method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _tokens(text: str, noise: set[str]) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in noise}


def match(event: dict, jobs: list[dict]) -> tuple[dict | None, str]:
    """Return (dossier, reason). The dossier is None when unmatched or ambiguous."""
    want = _tokens(event["company"], _NOISE)
    if not want:
        return None, "no company"
    hits = []
    for job in jobs:
        have = _tokens(job["company"], _NOISE)
        if have and (want <= have or have <= want):
            hits.append(job)
    if not hits:
        return None, "no dossier"
    if len(hits) == 1:
        return hits[0], "company"
    # An email is about a role that was applied to, so drop untouched and skipped dossiers.
    live = [j for j in hits if j["status"] in _POST_APPLY]
    if len(live) == 1:
        return live[0], "company + applied status"
    hits = live or hits
    same_title = [j for j in hits if _tokens(j["role"], set()) == _tokens(event.get("role", ""), set())]
    if len(same_title) == 1:
        return same_title[0], "company + exact role"
    role = _tokens(event.get("role", ""), _ROLE_NOISE)
    scored = sorted(
        ((len(role & _tokens(j["role"], _ROLE_NOISE)), j) for j in hits),
        key=lambda pair: -pair[0],
    )
    if role and scored[0][0] > 0 and scored[0][0] > scored[1][0]:
        return scored[0][1], "company + role"
    return None, "ambiguous: " + "; ".join(f"{j['role']} [{j['status']}]" for j in hits)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("events")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-uncertain", action="store_true")
    args = parser.parse_args()

    events = sorted(json.load(open(args.events, encoding="utf-8")), key=lambda e: e["date"])
    jobs = _call("GET", "/api/jobs")
    by_id = {j["id"]: j for j in jobs}
    session = f"Mail sync {date.today().isoformat()}"
    written = held = unmatched = 0

    for event in events:
        kind, new_status, outranked_by = _OUTCOMES[event["outcome"]]
        label = f"{event['date']} {event['outcome']:<10} {event['company']}"
        job, reason = match(event, jobs)
        if job is None:
            unmatched += 1
            print(f"UNMATCHED  {label}  ({reason})")
            continue
        if not event.get("confident", True) and not args.include_uncertain:
            held += 1
            print(f"HELD       {label}  -> {job['company']} / {job['role']} (uncertain)")
            continue
        current = by_id[job["id"]]
        set_status = new_status if new_status and current["status"] not in outranked_by else None
        if set_status == current["status"]:
            set_status = None
        change = f"{current['status']} -> {set_status}" if set_status else current["status"]
        print(f"{'WRITE' if args.apply else 'WOULD'}      {label}  -> {job['role']} [{change}]")
        if not args.apply:
            continue
        _call("POST", f"/api/jobs/{job['id']}/activity", {
            "kind": kind,
            "title": f"Email: {event['outcome']}",
            "detail": event.get("note", ""),
            "session": session,
            "occurred_at": f"{event['date']}T00:00:00+00:00",
            "external_id": f"gmail:{event['id']}",
        })
        if set_status:
            # capture upserts on company + role + URL and patches only what is sent.
            _call("POST", "/api/jobs/capture", {
                "company": job["company"], "role": job["role"], "job_url": job["job_url"],
                "status": set_status, "session": session,
            })
            current["status"] = set_status
        written += 1

    print(f"\n{len(events)} events: {written} written, {held} held, {unmatched} unmatched"
          + ("" if args.apply else " (dry run, nothing written)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
