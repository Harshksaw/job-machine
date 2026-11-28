"""Feed the backlog to Cursor in small batches, one lane at a time, so nothing floods.

    .venv/bin/python scripts/cursor_queue.py plan                 # analyse and print the lanes
    .venv/bin/python scripts/cursor_queue.py cleanup [--apply]    # skip non remote / wrong role
    .venv/bin/python scripts/cursor_queue.py run score            # no browser: size, tier, rescore
    .venv/bin/python scripts/cursor_queue.py run apply            # Ego Lite form fills
    .venv/bin/python scripts/cursor_queue.py run outreach         # people and drafts

Targeting (AGENTS.md "Search policy since 2026-11-25"): remote only, nothing based in India,
small startups first, big companies set aside. Tier A (open to Canada or anywhere) first,
then Tier A2 (limited to the US, UK, Australia, New Zealand or another non India country),
then Tier B, Tier E (European companies or Europe only roles) last. Outreach is Tier A only. Each `run` starts one `cursor-agent -p` per batch, waits for it, then
starts the next, so a lane never holds more than one agent. A lock file per lane stops a
second copy. Run at most `score` plus one browser lane at once; `apply` and `outreach`
each cap their own tab count in the prompt.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "http://127.0.0.1:8420"
SERVICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE))
from app.regions import is_india  # noqa: E402
REPO = SERVICE.parent
STATE = SERVICE / "data" / "cursor_queue_state.json"
LOG_DIR = REPO / "logs" / "cursor-queue"
CURSOR = ["cursor-agent", "-p", "--force", "--trust", "--model", "grok-4.7-medium", "--output-format", "text"]
# Fallback when Cursor credits run out: OpenCode on its free model (prompt is the last argument).
TOOLS = {
    "cursor": CURSOR,
    "opencode": ["opencode", "run", "--auto", "-m", "opencode/big-pickle"],
    # AI Studio key from .env; only flash-lite answered on 2026-11-25 (3.5 pro 404, 3.5 flash failed).
    "gemini": ["gemini", "--skip-trust", "--yolo", "-m", "gemini-3.5-flash-lite", "-p"],
}
BATCH_TIMEOUT = 45 * 60

_SENIOR = re.compile(r"senior|\bsr\b|staff|principal|\blead\b|manager|director|head of", re.I)
_ENG = re.compile(r"software|developer|full.?stack|back.?end|front.?end|machine learning|\bml\b|\bai\b|"
                  r"forward deployed|platform|engineer", re.I)
_OFF_ROLE = re.compile(r"support|sales|customer|solutions|gtm|\bqa\b|test|consult|trainer|mechanical|"
                       r"industrial|manufactur|hardware|field|success|specialist|intern", re.I)
_NOT_REMOTE = re.compile(r"hybrid|on.?site|onsite|in.person|office", re.I)

LANES = {
    # SUPERSEDED (M7, spec section 9): see SUPERSEDED below. Kept until the pipeline has
    # run cleanly for a week.
    "score": {"batch": 8, "browser": False},
    "apply": {"batch": 3, "browser": True},
    "outreach": {"batch": 4, "browser": True},
    "review": {"batch": 2, "browser": False},
}
# Lanes the agent orchestrator replaced (M7). `apply` and `outreach` stay: the pipeline
# stops at the apply packet and never drives a browser to submit or contact anyone.
SUPERSEDED = {
    "score": "the eligibility and fit_score steps of the packet pipeline (Pipeline tab, "
             "POST /api/pipeline/runs or the job-machine MCP server)",
}

_COMMON = """You are a Cursor agent for Harsh Saw's Job Machine. Read AGENTS.md and docs/AGENT-PLAYBOOK.md
first; their rules win. Targeting: remote only, nothing based in India (even when another region
is also listed), small startups (under about 200 people, seed to Series B) first, big companies
(big names or 1,000+ staff) skipped with note "big company, set aside". Country order: Canada, US,
UK, Australia, New Zealand, other, Europe last. Remote open to Canada or anywhere is "Tier A".
Remote limited to US, UK, Australian, New Zealand or another non India country's residents is NOT
a skip: with fit 7+ write "Tier A2" (second priority). A European company or a Europe only role is
"Tier E" (last), unless it is really good (remote, fit 8+, posted in the last 14 days): then "Tier A2".
Answer Tier A2 and Tier E forms authorized there No, sponsorship Yes. Claim each
dossier before you work it (AGENTS.md) with the title "Claimed by cursor_queue <lane>". A claim with that same title is yours from an
earlier batch: take it over. Only other titles count as another agent and skip any claimed by another agent in the last 2 hours.
Never fabricate: every claim traces to resume-tailor-service/content/resume_bank.yaml. Never press
Submit, Send or Apply. No em dashes, no hyphenated compound words. Never write to resume.pdf.
Any step past 3 attempts or about 5 minutes: park the item with the exact blocker and move on.
Work ONLY the items listed below, then stop and print one line per item: id, company, result.
"""

_TASKS = {
    "score": _COMMON + """
Lane: score. NO BROWSER. Use web fetch and the job API only.
For each item: confirm the role is fully remote and which countries a hire may live in (read the full
description), find company size, stage and funding from public pages, then:
- dossier: rescore fit against the bank (no experience level penalty for a 2 to 5 year band), write
  `Tier A`, `Tier A2`, `Tier E` or `Tier B` plus size, stage and source links at the start of research_brief, and set
  status `skipped` with the reason if it fails targeting. GET fresh before PUT and send every field.
- research item: POST /api/research/<id>/promote (header X-Job-Machine: dashboard) if it passes,
  otherwise POST /api/research/<id>/dismiss. After promoting, score the new dossier the same way.
""",
    "apply": _COMMON + """
Lane: apply. Follow the apply section of docs/BACKLOG-RUN-PROMPT.md (Gmail check first, Tier A
letter recipe, fill but never submit). Browser budget: ONE Ego Lite TaskSpace per dossier, at
most 2 spaces open at once and at most 2 tabs per space. Close each space as soon as the dossier is
filled and handed off or parked. Never open a listing you are not about to fill.
In the handoff activity, list every field label with the exact value typed or picked, and every
field left blank with why; save free text answers via POST /api/jobs/<id>/answers.
""",
    "review": _COMMON + """
Lane: review. NO BROWSER. Quality over speed: these are the few Tier A jobs that matter most.
For each dossier, GET it fresh and read the full description, research_brief, cover_letter and
application_answers, plus content/resume_bank.yaml.
1. Check every claim in the letter and answers against the bank, line by line. Remove or fix
   anything the bank does not support. Known traps are listed in docs/BACKLOG-RUN-PROMPT.md step 3.
2. The letter must follow the Tier A recipe in docs/BACKLOG-RUN-PROMPT.md: one specific thing about
   the company with its source link in research_brief, the one bank fact closest to their problem
   with real detail the resume line does not show, a short casual close, under 150 words, no resume
   bullet copied word for word. If it is generic or weak, rewrite it.
3. Answers: short and casual, like a person typing, per docs/BACKLOG-RUN-PROMPT.md rule 7.
4. PUT the fixes (GET fresh, send every field) and log an activity titled "Reviewed by cursor_queue
   review" listing what you changed and anything Harsh must decide. Never change status.
""",
    "outreach": _COMMON + """
Lane: outreach. Follow the "Agent 2: outreach" section of docs/BACKLOG-RUN-PROMPT.md: draft only,
nothing is sent, every draft goes to the awaiting approval list. Up to 3 people per dossier.
Browser budget: ONE Ego Lite TaskSpace for the whole batch, at most 3 tabs, close each tab once that
person is done. Public pages only.
""",
}


def _env(tool: str) -> dict:
    env = dict(os.environ)
    if tool == "gemini":
        # Same setup as app/agent_runs.py: a separate home selects the API key login.
        env["GEMINI_CLI_HOME"] = str(Path.home() / ".job-machine-gemini")
        for line in (SERVICE / ".env").read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip().startswith("GEMINI") and value:
                env.setdefault(key.strip(), value.strip().strip('"'))
    return env


def _get(path: str):
    with urllib.request.urlopen(API + path, timeout=30) as resp:
        return json.load(resp)


def _send(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json", "X-Job-Machine": "dashboard"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def _right_role(role: str) -> bool:
    return bool(_ENG.search(role)) and not _SENIOR.search(role) and not _OFF_ROLE.search(role)


def _remote(job: dict) -> bool:
    """False only when the dossier says hybrid or on site; unknown goes to scoring."""
    text = f"{job.get('work_mode') or ''} {job.get('location') or ''}"
    if not (job.get("work_mode") or "").strip():
        return True
    return "remote" in text.lower() and not _NOT_REMOTE.search(text)


def _india(text: str | None) -> bool:
    return is_india(text)


# Exact tier token at the start of research_brief or next_action: "Tier A2" is not "Tier A".
_TIER = re.compile(r"\s*tier\s+(a2|a|b|e)(?![a-z0-9])", re.I)
# Apply lane order (BACKLOG-RUN-PROMPT.md "The queue"): Tier A, A2, B, then Tier E (Europe) last.
TIER_ORDER = {"A": 0, "A2": 1, "B": 2, "E": 3}
APPLY_MIN_FIT = {"A": 8, "A2": 7, "B": 7, "E": 7}


def _tier_token(text: str | None) -> str | None:
    match = _TIER.match(text or "")
    return match.group(1).upper() if match else None


def _tier(job: dict) -> str | None:
    """Tier is written at the start of research_brief. The jobs list leaves that field
    out, so a tier at the start of next_action counts, and a fit of 7 or more with no
    tier yet is checked on the full dossier."""
    for key in ("research_brief", "next_action"):
        token = _tier_token(job.get(key))
        if token:
            return token
    if (job.get("fit_score") or 0) < 7 or job.get("research_brief"):
        return None
    full = _get(f"/api/jobs/{job['id']}")
    job["research_brief"] = full.get("research_brief") or ""
    return _tier_token(job["research_brief"])


def _tier_a(job: dict) -> bool:
    return _tier(job) == "A"


def _tier_a2(job: dict) -> bool:
    return _tier(job) == "A2"


def build_plan() -> dict:
    jobs = _get("/api/jobs")
    research = _get("/api/research")
    research = research if isinstance(research, list) else research.get("items", [])
    open_jobs = [j for j in jobs if j["status"] in ("ready", "discovered", "researching", "applying")]
    plan = {"cleanup_jobs": [], "cleanup_research": [], "score": [], "apply": [], "outreach": [], "review": []}
    for job in open_jobs:
        # An `applying` dossier may already be submitted in real life, so cleanup never
        # touches it; the apply lane checks Gmail and decides.
        if job["status"] == "applying" and not (_remote(job) and _right_role(job.get("role", ""))):
            continue
        if not _remote(job) or _india(job.get("location")) or not _right_role(job.get("role", "")):
            reason = "not remote" if not _remote(job) else "based in India" if _india(job.get("location")) else "wrong role"
            plan["cleanup_jobs"].append({"id": job["id"], "company": job["company"], "role": job["role"], "reason": reason})
            continue
        fit = job.get("fit_score") or 0
        tier = _tier(job)
        if tier in APPLY_MIN_FIT and fit >= APPLY_MIN_FIT[tier]:
            plan["apply"].append(job["id"])
        else:
            plan["score"].append(job["id"])
    for item in research:
        if item.get("status") != "new":
            continue
        if not _right_role(item.get("role", "")) or _india(item.get("location")):
            plan["cleanup_research"].append({"id": item["id"], "company": item["company"], "role": item["role"]})
        else:
            plan["score"].append(f"research:{item['id']}")
    plan["outreach"] = [j["id"] for j in jobs
                        if j["status"] in ("applied", "ready") and _tier_a(j)
                        and not (j.get("people") or j.get("person_count"))]
    # Best first: higher fit.
    by_id = {j["id"]: j for j in jobs}
    # Tier A (open to Canada) first, then Tier A2 (US, UK, Australia, New Zealand or another
    # non India country), Tier B, Tier E (Europe) last; best fit first inside a tier.
    plan["apply"].sort(key=lambda i: (TIER_ORDER[_tier(by_id[i])], -(by_id[i].get("fit_score") or 0)))
    # Review is the careful pass for the jobs that matter most: Tier A and A2 only.
    plan["review"] = [i for i in plan["apply"] if _tier(by_id[i]) in ("A", "A2")]
    return plan


def _state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"done": {lane: [] for lane in LANES}}


def _save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


def _save_lane(lane: str, done: list) -> None:
    """Rewrite one lane only, so a parallel lane cannot lose its finished ids."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with STATE.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        raw = handle.read()
        state = json.loads(raw) if raw.strip() else {"done": {name: [] for name in LANES}}
        state.setdefault("done", {})
        state["done"][lane] = list(done)
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(state, indent=1))
        handle.flush()
        fcntl.flock(handle, fcntl.LOCK_UN)


def _provider_failed_without_results(output: str, batch: list[str]) -> bool:
    """Do not mark a batch done when a provider exhausts retries before its results."""
    failures = list(re.finditer(
        r"Attempt \d+ failed|quota exceeded|prepaid balance is used up|status 503|UNAVAILABLE",
        output, re.IGNORECASE,
    ))
    if not failures:
        return False
    tail = output[failures[-1].end():]
    ids = [item.split(":", 1)[1] if item.startswith("research:") else item for item in batch]
    return not all(item_id in tail for item_id in ids)


def _claimed_by_other(job_id: str, lane: str) -> bool:
    """A fresh claim blocks the item unless the title names this lane."""
    job = _get(f"/api/jobs/{job_id}")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    for act in job.get("activities", []):
        title = act.get("title") or ""
        when = act.get("created_at") or act.get("at") or ""
        try:
            fresh = datetime.fromisoformat(when.replace("Z", "+00:00")) > cutoff
        except ValueError:
            fresh = False
        low = title.lower()
        # The score lane has no browser and finishes before an item reaches apply or outreach,
        # so its claim never blocks them; apply and outreach still block each other.
        if title.startswith("Claimed by") and fresh and lane not in low and "cursor_queue score" not in low \
                and not (lane == "review" and "cursor_queue" in low):
            return True
    return False


def cmd_plan(_: argparse.Namespace) -> None:
    plan = build_plan()
    done = _state()["done"]
    print(f"cleanup: {len(plan['cleanup_jobs'])} dossiers to skip, {len(plan['cleanup_research'])} research to dismiss")
    reasons: dict[str, int] = {}
    for row in plan["cleanup_jobs"]:
        reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
    print("  by reason:", reasons)
    for lane in LANES:
        left = [i for i in plan[lane] if i not in done.get(lane, [])]
        batches = -(-len(left) // LANES[lane]["batch"])
        print(f"{lane:9} {len(left):4} items left, {batches} batches of {LANES[lane]['batch']}")


def cmd_cleanup(args: argparse.Namespace) -> None:
    plan = build_plan()
    print(f"{len(plan['cleanup_jobs'])} dossiers -> skipped, {len(plan['cleanup_research'])} research -> dismissed")
    if not args.apply:
        for row in plan["cleanup_jobs"][:15]:
            print(f"  skip {row['company']} | {row['role']} ({row['reason']})")
        print("dry run; add --apply to write")
        return
    keep_out = {"id", "activities", "revisions", "created_at", "updated_at"}
    for row in plan["cleanup_jobs"]:
        job = _get(f"/api/jobs/{row['id']}")
        _send("PUT", f"/api/jobs/{row['id']}", {**{k: v for k, v in job.items() if k not in keep_out}, "status": "skipped"})
        _send("POST", f"/api/jobs/{row['id']}/activity",
              {"kind": "note", "title": f"Skipped by cursor_queue cleanup: {row['reason']}",
               "detail": "Search policy 2026-11-25: remote only, engineering below senior, nothing based in India.",
               "session": "cursor_queue cleanup"})
    for row in plan["cleanup_research"]:
        _send("POST", f"/api/research/{row['id']}/dismiss")
    print("done")


def cmd_run(args: argparse.Namespace) -> None:
    lane = args.lane
    if lane in SUPERSEDED:
        print(f"NOTE: the {lane} lane is superseded by {SUPERSEDED[lane]}. It still runs for now.", file=sys.stderr)
    argv = TOOLS[args.tool]
    if args.model:
        # Same flag on both CLIs: cursor-agent --model, opencode run -m.
        flag = next(i for i, part in enumerate(argv) if part in ("-m", "--model"))
        argv = [*argv[:flag + 1], args.model, *argv[flag + 2:]]
    binary = shutil.which(argv[0])
    if binary is None:
        sys.exit(f"{argv[0]} is not on PATH")
    if args.batch < 1:
        sys.exit("--batch must be at least 1")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = LOG_DIR / f"{lane}.lock"
    try:
        lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        sys.exit(f"{lane} lane is already running ({lock}); delete the lock if it is stale")
    with os.fdopen(lock_fd, "w") as lock_file:
        lock_file.write(str(datetime.now(timezone.utc)))
    size = min(args.batch, LANES[lane]["batch"])
    try:
        for n in range(args.max_batches):
            state = _state()
            done = state["done"].setdefault(lane, [])
            batch = []
            for item in (i for i in build_plan()[lane] if i not in done):
                if not item.startswith("research:") and _claimed_by_other(item, lane):
                    continue
                batch.append(item)
                if len(batch) == size:
                    break
            if not batch:
                print(f"{lane}: queue empty")
                return
            listing = "\n".join(
                f"- research item {i.split(':', 1)[1]}" if i.startswith("research:") else f"- dossier {i}"
                for i in batch)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            log_path = LOG_DIR / f"{stamp}-{lane}.log"
            print(f"{lane} batch {n + 1}: {len(batch)} items -> {log_path.name}", flush=True)
            failed = False
            with open(log_path, "w") as log:
                try:
                    result = subprocess.run([binary, *argv[1:], _TASKS[lane] + "\nItems:\n" + listing],
                                            cwd=REPO, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=_env(args.tool),
                                            timeout=BATCH_TIMEOUT)
                    if result.returncode != 0:
                        log.write(f"\n[cursor_queue] cursor-agent exited {result.returncode}; batch not marked done\n")
                        failed = True
                except subprocess.TimeoutExpired:
                    log.write(f"\n[cursor_queue] batch stopped after {BATCH_TIMEOUT // 60} minutes\n")
            text = log_path.read_text(errors="ignore")
            if "ActionRequiredError" in text or "prepaid balance" in text:
                # Out of Cursor credits: every later batch would fail in seconds too.
                print(f"{lane}: Cursor credits are used up, stopping; items stay in the queue", flush=True)
                return
            if _provider_failed_without_results(text, batch):
                print(f"{lane} batch {n + 1} exhausted provider retries; items stay in the queue", flush=True)
                return
            if "rejected permission" in text:
                # OpenCode exits 0 after a refused tool call, so the batch stopped part way.
                failed = True
            if failed:
                print(f"{lane} batch {n + 1} failed; items stay in the queue, stopping this run", flush=True)
                return
            # A timeout still counts as attempted, so one stuck item never loops.
            done.extend(batch)
            _save_lane(lane, done)
    finally:
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    clean = sub.add_parser("cleanup")
    clean.add_argument("--apply", action="store_true")
    clean.set_defaults(fn=cmd_cleanup)
    run = sub.add_parser("run")
    run.add_argument("lane", choices=list(LANES))
    run.add_argument("--batch", type=int, default=99, help="go smaller than the lane default")
    run.add_argument("--max-batches", type=int, default=10)
    run.add_argument("--tool", choices=list(TOOLS), default="cursor")
    run.add_argument("--model", help="override the tool's default model")
    run.set_defaults(fn=cmd_run)
    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
