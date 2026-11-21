"""Dashboard Settings tab: funnel stats, connection checks and the telemetry summary."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Header, HTTPException

from app import (
    agent_health,
    agent_runs,
    doc_store,
    fantastic,
    job_store,
    people_store,
    research_store,
    sheets,
    telemetry,
)
from app.errors import SheetsError
from app.search import _require_dashboard

router = APIRouter()

REPO = Path(__file__).resolve().parents[2]
_AI_USAGE = REPO / "logs" / "ai-usage.json"
_AI_POLICY = REPO / "tools" / "ai-meter" / "policy.json"
_STARTED_AT = datetime.now(timezone.utc)

_POST_APPLY = {"applied", "outreach", "interview", "offer", "rejected"}
_PRE_APPLY = {"discovered", "researching", "ready", "applying"}
# Dossier sources are free text ("Ashby (clean-ats broad)", "Company ATS (Lever)").
_SOURCE_GROUPS = (
    ("linkedin", "LinkedIn"), ("wellfound", "Wellfound"), ("combinator", "YC"),
    ("startup", "YC"), ("yc", "YC"), ("ashby", "Ashby"), ("greenhouse", "Greenhouse"),
    ("lever", "Lever"), ("himalayas", "Remote boards"), ("remot", "Remote boards"),
    ("jobicy", "Remote boards"), ("nomads", "Remote boards"), ("hacker", "Hacker News"),
    ("a16z", "a16z"), ("indeed", "Indeed"),
)
_WEEKS = 12
# Even the narrow read is a round trip to Neon per page load, so keep it for a minute.
_STATS_TTL = 60
_stats_cache: dict = {"at": 0.0, "value": None}


def _source_group(source: str) -> str:
    lowered = source.lower()
    for needle, label in _SOURCE_GROUPS:
        if needle in lowered:
            return label
    return "Other"


def _applied_at(job: dict) -> str:
    for activity in job.get("activities") or []:
        if activity.get("kind") == "applied":
            return activity.get("occurred_at") or activity.get("created_at") or ""
    return job.get("updated_at") or ""


def funnel(jobs: list[dict], today: date | None = None) -> dict:
    """Counts for the Settings tab from `job_store.report_rows()`. "Heard back" means an
    interview or assessment was logged at any point, so a role that was later rejected
    still counts as a response."""
    today = today or datetime.now(timezone.utc).date()
    first_week = today - timedelta(days=today.weekday(), weeks=_WEEKS - 1)
    weekly = {first_week + timedelta(weeks=n): 0 for n in range(_WEEKS)}
    by_source: dict[str, Counter] = {}
    by_fit: dict[int, Counter] = {}
    totals: Counter = Counter()

    for job in jobs:
        status = job.get("status") or ""
        kinds = {activity.get("kind") for activity in job.get("activities") or []}
        applied = status in _POST_APPLY or "applied" in kinds
        responded = applied and (status in ("interview", "offer") or "interview" in kinds)
        row = Counter(
            tracked=1, applied=applied, responded=responded,
            rejected=applied and status == "rejected",
            waiting=applied and not responded and status in ("applied", "outreach"),
            strong_unapplied=(job.get("fit_score") or 0) >= 8 and status in _PRE_APPLY,
        )
        totals += row
        if job.get("fit_score"):
            by_fit.setdefault(job["fit_score"], Counter()).update(row)
        if applied:
            by_source.setdefault(_source_group(job.get("source") or ""), Counter()).update(row)
            try:
                day = datetime.fromisoformat(_applied_at(job)).date()
            except ValueError:
                continue
            week = day - timedelta(days=day.weekday())
            if week in weekly:
                weekly[week] += 1

    def rate(row: Counter) -> float | None:
        return round(row["responded"] / row["applied"], 3) if row["applied"] else None

    return {
        "totals": {
            "dossiers": len(jobs),
            "applied": totals["applied"],
            "responded": totals["responded"],
            "rejected": totals["rejected"],
            "waiting": totals["waiting"],
            "response_rate": rate(totals),
        },
        "by_status": dict(Counter(job.get("status") for job in jobs)),
        "by_source": sorted(
            (
                {"source": source, "applied": row["applied"], "responded": row["responded"],
                 "rejected": row["rejected"], "response_rate": rate(row)}
                for source, row in by_source.items()
            ),
            key=lambda item: -item["applied"],
        ),
        "by_fit": [
            {"fit": fit, "tracked": row["tracked"], "applied": row["applied"],
             "responded": row["responded"], "response_rate": rate(row)}
            for fit, row in sorted(by_fit.items(), reverse=True)
        ],
        "weekly": [{"week": week.isoformat(), "applied": count} for week, count in weekly.items()],
        "backlog": {"strong_unapplied": totals["strong_unapplied"]},
    }


def _ai_usage() -> dict | None:
    try:
        usage = json.loads(_AI_USAGE.read_text(encoding="utf-8"))
        budgets = json.loads(_AI_POLICY.read_text(encoding="utf-8")).get("budgets", {})
    except (OSError, ValueError):
        return None
    providers = [
        {"provider": name, "day": spend.get("day", 0), "week": spend.get("week", 0),
         "calls_day": spend.get("calls_day", 0),
         "day_budget": budgets.get(name, {}).get("day"),
         "week_budget": budgets.get(name, {}).get("week")}
        for name, spend in usage.get("providers", {}).items()
        if spend.get("week") or name in budgets
    ]
    return {
        "generated_at": usage.get("generated_at"),
        "providers": providers,
        "agents": agent_health.agent_health(agent_runs.LOG_DIR),
    }


def _stats() -> dict:
    value = funnel(job_store.report_rows())
    value["backlog"]["research_new"] = len(research_store.list_items(None, "new"))
    value["people"] = dict(Counter(person.status for person in people_store.load_people()))
    value["ai_usage"] = _ai_usage()
    value["service"] = {
        "started_at": _STARTED_AT.isoformat(timespec="seconds"),
        "database": "Postgres" if doc_store.sql_backend_from_env() else "local JSON files",
    }
    value["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return value


@router.get("/api/system/stats")
def stats(refresh: bool = False) -> dict:
    if refresh or _stats_cache["value"] is None or time.monotonic() - _stats_cache["at"] > _STATS_TTL:
        _stats_cache.update(at=time.monotonic(), value=_stats())
    return _stats_cache["value"]


@router.get("/api/system/telemetry")
def telemetry_summary() -> dict:
    return telemetry.summary()


# --- connection checks -------------------------------------------------------------
# Each check returns (status, detail) with status ok, warn or fail. None of them spends
# a model call or a search credit, and none writes anything.

# launchd starts the service with a minimal PATH, so look in the usual install dirs.
_PATH = os.pathsep.join([*agent_runs._EXTRA_PATHS, "/Library/TeX/texbin", os.environ.get("PATH", "")])


def _cli(command: list[str], timeout: int = 20) -> tuple[int | None, str]:
    """Run a CLI and return (exit code, first line of output); code is None if missing."""
    binary = shutil.which(command[0], path=_PATH)
    if binary is None:
        return None, f"{command[0]} is not installed or not on PATH"
    proc = subprocess.run(
        [binary, *command[1:]], capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    lines = [line.strip() for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()]
    return proc.returncode, lines[0][:200] if lines else ""


def _cli_check(command: list[str], logged_out: str = "") -> tuple[str, str]:
    code, line = _cli(command)
    if code is None:
        return "fail", line
    if code != 0 or (logged_out and logged_out in line.lower()):
        return "fail", line or f"exit {code}"
    return "ok", line


def _check_database() -> tuple[str, str]:
    count = len(job_store.list_summaries())
    if doc_store.sql_backend_from_env() is None:
        return "warn", f"{count} dossiers in local JSON files; DATABASE_URL is not set"
    return "ok", f"Postgres answered, {count} dossiers"


def _check_sheet() -> tuple[str, str]:
    try:
        return "ok", f"Sheet answered with {len(sheets.fetch_applications())} rows"
    except SheetsError as error:
        return "fail", str(error)


def _check_fantastic() -> tuple[str, str]:
    usage = fantastic.usage_summary()
    if not usage.get("configured"):
        return "warn", "FANTASTIC_JOBS_API_KEY is not set"
    return "ok", f"{usage.get('jobs_left')} trial jobs and {usage.get('requests_left')} requests left"


def _age(moment: datetime) -> str:
    minutes = int((datetime.now(timezone.utc) - moment).total_seconds() // 60)
    if minutes < 120:
        return f"{minutes} minutes ago"
    return f"{minutes // 60} hours ago" if minutes < 48 * 60 else f"{minutes // 1440} days ago"


def _check_ai_meter() -> tuple[str, str]:
    try:
        generated = datetime.fromisoformat(json.loads(_AI_USAGE.read_text())["generated_at"])
    except (OSError, ValueError, KeyError):
        return "fail", "logs/ai-usage.json is missing or unreadable"
    stale = datetime.now(timezone.utc) - generated > timedelta(minutes=15)
    return ("warn" if stale else "ok"), f"Usage refreshed {_age(generated)}" + (
        "; the meter should refresh every 5 minutes" if stale else ""
    )


def _check_mail_sync() -> tuple[str, str]:
    runs = sorted((REPO / "session-artifacts").glob("mail-sync-*/events.json"))
    if not runs:
        return "warn", "No mail sync has run; see prompts/mail-sync.md"
    ran = datetime.fromtimestamp(runs[-1].stat().st_mtime, tz=timezone.utc)
    stale = datetime.now(timezone.utc) - ran > timedelta(days=3)
    return ("warn" if stale else "ok"), f"Last mail sync {_age(ran)}" + (
        "; outcomes in the inbox may be missing from the dossiers" if stale else ""
    )


def _check_telemetry() -> tuple[str, str]:
    state = telemetry.summary()
    if not state["enabled"]:
        return "warn", "Tracing is off (OTEL_SDK_DISABLED)"
    endpoint = state["exporter"]
    if not endpoint:
        return "ok", (
            f"Tracing on, {state['buffered']} spans kept in memory. "
            "Set OTEL_EXPORTER_OTLP_ENDPOINT to also export them."
        )
    target = urlsplit(endpoint)
    port = target.port or (443 if target.scheme == "https" else 80)
    try:
        socket.create_connection((target.hostname, port), timeout=5).close()
    except OSError as error:
        return "fail", f"Collector at {target.hostname}:{port} did not accept a connection: {error}"
    return "ok", f"Exporting to {target.hostname}:{port}"


CHECKS: dict[str, tuple[str, str, Callable[[], tuple[str, str]]]] = {
    "database": ("Dossier database", "Reads the dossier index from Neon Postgres.", _check_database),
    "claude": ("Claude CLI", "Kit and resume generation run through it. Checks it is installed.",
               lambda: _cli_check(["claude", "--version"])),
    "cursor": ("Cursor CLI", "Runs the research and triage agents. Checks the login.",
               lambda: _cli_check(["cursor-agent", "status"], logged_out="not logged in")),
    "codex": ("Codex CLI", "Fallback agent. Checks the login.",
              lambda: _cli_check(["codex", "login", "status"], logged_out="not logged in")),
    "pdflatex": ("pdflatex", "Compiles tailored resumes.", lambda: _cli_check(["pdflatex", "--version"])),
    "sheet": ("Google Sheet log", "Reads the application log through the Apps Script.", _check_sheet),
    "fantastic": ("Fantastic Jobs", "Search presets. Reads the saved trial budget.", _check_fantastic),
    "ai-meter": ("AI usage meter", "logs/ai-usage.json, which routes work between tools.", _check_ai_meter),
    "mail-sync": ("Mail sync", "When email outcomes were last written to dossiers.", _check_mail_sync),
    "telemetry": ("OpenTelemetry", "Tracing state and the collector, when one is set.", _check_telemetry),
}


@router.get("/api/system/connections")
def connections() -> list[dict]:
    return [{"id": key, "label": label, "what": what} for key, (label, what, _) in CHECKS.items()]


@router.post("/api/system/connections/{check_id}/check")
def check_connection(check_id: str, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    if check_id not in CHECKS:
        raise HTTPException(status_code=404, detail="unknown connection check")
    started = time.monotonic()
    with telemetry.span("connection.check", check=check_id) as current:
        try:
            status, detail = CHECKS[check_id][2]()
        except subprocess.TimeoutExpired:
            status, detail = "fail", "Timed out"
        except Exception as error:  # a failing check is the result, not a server error
            status, detail = "fail", f"{type(error).__name__}: {error}"[:300]
        current.set_attribute("check.status", status)
    return {"id": check_id, "status": status, "detail": detail,
            "ms": round((time.monotonic() - started) * 1000)}
