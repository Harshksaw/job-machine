"""Start Codex or OpenCode on a fixed job machine task from the dashboard.

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
_EXTRA_PATHS = [str(Path.home() / d) for d in (".opencode/bin", ".local/bin")] + ["/opt/homebrew/bin", "/usr/local/bin"]

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
# A run that outlives this is stuck (a free model down makes OpenCode retry forever).
MAX_RUNTIME = 45 * 60
OPENCODE_LOG = Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"
_OUTAGE_WINDOW = 15 * 60
_OUTAGE = re.compile(r"timestamp=(\S+Z) .*Model is unavailable")


def opencode_unavailable() -> bool:
    """True when OpenCode logged "Model is unavailable" in the last 15 minutes."""
    if not OPENCODE_LOG.exists():
        return False
    with open(OPENCODE_LOG, "rb") as fh:
        fh.seek(max(0, OPENCODE_LOG.stat().st_size - 200_000))
        tail = fh.read().decode("utf-8", "ignore")
    now = datetime.now(timezone.utc)
    for match in _OUTAGE.finditer(tail):
        try:
            when = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - when).total_seconds() < _OUTAGE_WINDOW:
            return True
    return False


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


TOOLS: dict[str, list[str]] = {
    "codex": ["codex", "exec", "--full-auto"],
    "opencode": ["opencode", "run", "-m", "opencode/deepseek-v4.1-flash-free"],
}


def start(tool: str, task: str) -> dict:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}; use one of: {', '.join(TOOLS)}")
    if task not in TASKS:
        raise ValueError(f"unknown task {task!r}; use one of: {', '.join(TASKS)}")
    # launchd starts the service with a minimal PATH, so look in the usual install dirs.
    binary = shutil.which(TOOLS[tool][0], path=os.pathsep.join([*_EXTRA_PATHS, os.environ.get("PATH", "")]))
    if binary is None:
        raise ValueError(f"{TOOLS[tool][0]} is not installed or not on PATH")
    if tool == "opencode" and opencode_unavailable():
        raise ValueError("OpenCode free models are unavailable right now (Model is unavailable "
                         "in its log within 15 minutes); use codex or try later")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOG_DIR / f"{stamp}-{tool}-{task}.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [binary, *TOOLS[tool][1:], TASKS[task]["prompt"]],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    _watchdog(proc, log_path)
    return {"pid": proc.pid, "tool": tool, "task": task, "log": log_path.name}


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
