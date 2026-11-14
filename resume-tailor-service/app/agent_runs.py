"""Start Cursor or Codex on a fixed job machine task from the dashboard.

Only named tasks run, never a free text prompt from the request, and the endpoint that
calls this requires a custom header the browser will not send cross site. Each run is a
detached subprocess in the repo root with its output in logs/agents/.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG_DIR = REPO / "logs" / "agents"
_EXTRA_PATHS = [str(Path.home() / ".local/bin")] + ["/opt/homebrew/bin", "/usr/local/bin"]

_PREAMBLE = (
    "You are working in the job machine repo. Read AGENTS.md and docs/AGENT-PLAYBOOK.md "
    "first and follow every hard rule. The dossier API is http://127.0.0.1:8420. "
    "Do not submit applications, send outreach, or drive any browser in this task. "
)
TASKS: dict[str, dict] = {
    "score-new": {
        "label": "Score new discoveries",
        "prompt": _PREAMBLE + (
            "GET /api/jobs and take every dossier with status discovered and no fit_score. "
            "For each, read its jd_text with GET /api/jobs/<id>, score fit 1 to 10 against "
            "resume-tailor-service/content/resume_bank.yaml and the eligibility policy in "
            "AGENTS.md, then PUT the dossier back with fit_score set, status ready for 7+, "
            "researching for 6, and a one line reason in notes. Never archive or skip. "
            "End with a table: company | role | score | reason."
        ),
    },
    "triage-research": {
        "label": "Triage research finds",
        "prompt": _PREAMBLE + (
            "GET /api/research?status=new and skip items with tracked_dossier set. For each, "
            "judge fit 1 to 10 against resume-tailor-service/content/resume_bank.yaml (early "
            "career, about 2 years, backend, full stack, applied AI) and the AGENTS.md "
            "eligibility policy, using its url, role, remote_scope and notes (GET the posting "
            "url for the description if needed). POST /api/research/<id>/promote with header "
            "X-Job-Machine: dashboard when fit is 7 or more and he is eligible. POST "
            "/api/research/<id>/dismiss with the same header only when clearly ineligible "
            "(senior, US residents only, on site outside the US and Canada, not engineering). "
            "Leave everything else as new for Harsh. End with a table: company | role | fit | "
            "action | reason."
        ),
    },
    "liveness": {
        "label": "Check stale postings",
        "prompt": _PREAMBLE + (
            "Find dossiers with status discovered, researching or ready created more than "
            "30 days ago. Write them as [{id,url}] to logs/agents/liveness-input.json and run "
            "`cd resume-tailor-service && python3 scripts/check_liveness.py "
            "../logs/agents/liveness-input.json ../logs/agents/liveness-result.json`. "
            "Report the counts. Do not delete anything; Harsh decides."
        ),
    },
}
# Tasks that run on one dossier. The id is validated, never free text, and these stay out
# of TASKS so the Search tab does not offer them without a job.
_JOB_ID = re.compile(r"[0-9a-f]{32}")
JOB_TASKS: dict[str, dict] = {
    "research-job": {
        "label": "Research this job",
        "prompt": (
            "You are working in the job machine repo. Read AGENTS.md and docs/AGENT-PLAYBOOK.md "
            "first and follow every hard rule, above all: never fabricate; every claim traces to "
            "resume-tailor-service/content/resume_bank.yaml. Do not submit applications, send "
            "outreach, or drive any browser. Research exactly one dossier: "
            "http://127.0.0.1:8420/api/jobs/{job_id}. Before anything else POST "
            "/api/jobs/{job_id}/activity {{\"kind\":\"note\",\"title\":\"Claimed by Cursor "
            "research-job\"}}; stop if another agent claimed it in the last 2 hours. Then:\n"
            "1. Full JD: if jd_text is under 800 characters, fetch the full posting (playbook JD "
            "fetch section; ATS public APIs first).\n"
            "2. apply_url: the employer's own application page (Ashby, Greenhouse, Lever, Workday, "
            "company careers). For a board listing (Himalayas, Remotive, Jobicy, Remote OK, "
            "Wellfound) follow it with plain HTTP or a web search for the company careers page. "
            "If you cannot confirm it, leave apply_url empty and say so in the brief.\n"
            "3. company_context: 3 to 6 plain sentences from public sources (what they build, "
            "stage and size, funding or customers, anything recent), with source links.\n"
            "4. why_this_role: 2 to 4 sentences tying the role to his real bank evidence.\n"
            "5. Fit vs resume: POST /api/jobs/{job_id}/generate-kit (allow up to 5 minutes). It "
            "writes fit_analysis and the cover letter; if it fails, record the error, do not "
            "write a letter yourself.\n"
            "6. People: find up to 3 real people (hiring manager, engineering lead, recruiter) "
            "from public pages and POST them to /api/jobs/{job_id}/people with their profile "
            "url and why they matter. Never contact anyone.\n"
            "7. Form answers: list the questions this application form is likely to ask (read "
            "the real form over HTTP when the ATS exposes it). For each free text question POST "
            "/api/jobs/{job_id}/answers/generate with constraints \"Under 120 words. First "
            "person, plain. No em dashes.\". Personal values come from docs/PERSONAL-ANSWERS.md "
            "only; when a value is missing there, mark it for Harsh, never guess.\n"
            "8. research_brief: a PUT replaces the whole dossier, so any field you leave out "
            "is saved blank. GET the dossier fresh, drop only id, activities, revisions, "
            "created_at and updated_at, send EVERY other field back exactly as you read it "
            "(cover_letter, fit_score, fit_analysis, application_answers, status, notes, "
            "tailored_resume_id and the rest), and change only jd_text, apply_url, "
            "company_context, why_this_role and research_brief. Add "
            "?session=Cursor%20research-job. Then GET again and confirm cover_letter, "
            "fit_score and status are unchanged. "
            "research_brief is plain text with these headings: SUMMARY (3 lines: what the role "
            "is, fit score and verdict, apply or not and why), APPLY AT (apply_url or why it is "
            "missing), GAPS (from fit_analysis), WHAT TO PUT IN (one line per form field: field "
            "-> value, from PERSONAL-ANSWERS.md, the bank or a generated answer; resume = "
            "resume.pdf as is), NEEDS HARSH (every field only he can answer), PEOPLE (name, "
            "title, url). No em dashes.\n"
            "End with one line: done or blocked, and why."
        ),
    },
}
# A run that outlives this is stuck (a free model down makes OpenCode retry forever).
MAX_RUNTIME = 45 * 60
def _watchdog(proc: subprocess.Popen, log_path: Path) -> None:
    def stop() -> None:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
            with open(log_path, "a") as log:
                log.write(f"\n[job-machine] stopped after {MAX_RUNTIME / 60:g} minutes without finishing\n")

    timer = threading.Timer(MAX_RUNTIME, stop)
    timer.daemon = True
    timer.start()


# OpenCode was dropped on 2026-11-09: every free model failed (401, "Model is unavailable",
# or an empty reply) and it never finished a task.
TOOLS: dict[str, list[str]] = {
    "cursor": ["cursor-agent", "-p", "--force", "--trust", "--output-format", "text"],
    "codex": ["codex", "exec", "--full-auto"],
}


def start(tool: str, task: str, job_id: str | None = None) -> dict:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; use one of: {', '.join(TOOLS)}")
    if task in JOB_TASKS:
        if not job_id or not _JOB_ID.fullmatch(job_id):
            raise ValueError(f"task {task!r} needs a dossier id (32 lowercase hex characters)")
        prompt = JOB_TASKS[task]["prompt"].format(job_id=job_id)
    elif task in TASKS:
        prompt = TASKS[task]["prompt"]
        job_id = None
    else:
        raise ValueError(f"unknown task {task!r}; use one of: {', '.join([*TASKS, *JOB_TASKS])}")
    # launchd starts the service with a minimal PATH, so look in the usual install dirs.
    binary = shutil.which(TOOLS[tool][0], path=os.pathsep.join([*_EXTRA_PATHS, os.environ.get("PATH", "")]))
    if binary is None:
        raise ValueError(f"{TOOLS[tool][0]} is not installed or not on PATH")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"{stamp}-{tool}-{task}{'-' + job_id if job_id else ''}.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [binary, *TOOLS[tool][1:], prompt],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _watchdog(proc, log_path)
    return {"pid": proc.pid, "tool": tool, "task": task, "job_id": job_id, "log": log_path.name}


def recent(limit: int = 10) -> list[dict]:
    if not LOG_DIR.exists():
        return []
    logs = sorted(LOG_DIR.glob("*-*-*.log"), reverse=True)[:limit]
    runs = []
    for path in logs:
        text = path.read_text(errors="ignore")
        stamp, tool, task = path.stem.split("-", 2)
        runs.append({
            "log": path.name, "started": stamp, "tool": tool, "task": task,
            "tail": text[-1500:],
        })
    return runs
