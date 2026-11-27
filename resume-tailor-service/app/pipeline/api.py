"""`/api/pipeline/*` routes for the agent and model settings (spec 13.5): read and save
the config, its version history and rollback, the adapter list with key and health
state, and a one call test per adapter.

Also (M8): enqueue and read pipeline runs, and the stored mail sync results, which the
MCP server and the dashboard read. Runs only queue here; the worker pool
(app/pipeline/worker.py, on when PIPELINE_WORKERS > 0) or `scripts/run_task.py`
executes them. M6 adds retry, cancel and the ledger stats.

Mounted in app/main.py. No worker starts from here. Mutating routes
require the `X-Job-Machine: dashboard` header, like the other dashboard writes. Keys
are never returned: only whether the named env var is set.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app import job_store
from app.llm import DIRECT_STEPS
from app.mail import store as mail_store
from app.pipeline import adapters as adapters_module
from app.pipeline import config, stats, store, tasks, worker
from app.pipeline.pipelines import PACKET_PIPELINE
from app.pipeline.adapters import build_adapter
from app.pipeline.config import PipelineConfig
from app.pipeline.models import Attempt, now_iso
from app.pipeline import router as router_module
from app.pipeline.router import TrackedAdapter
from app.search import _require_dashboard

router = APIRouter(prefix="/api/pipeline")

# The process wide health view, shared with llm.complete and the worker pool (M6).
HEALTH = router_module.HEALTH

# The capability each step needs, from the step registry (PACKET_PIPELINE) plus the
# service's direct model calls (llm.DIRECT_STEPS), used to check step preferences.
STEP_CAPABILITIES = {
    **{step.name: step.capability for step in PACKET_PIPELINE.steps if step.capability},
    **DIRECT_STEPS,
}
TEST_RUN_ID = "adapter-test"
_TEST_PROMPT = 'This is a connection test. Answer with {"ok": true}.'
_TEST_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
_TEST_TIMEOUT = 120


@router.get("/config")
def get_config() -> dict:
    return config.load_config().model_dump(mode="json")


@router.put("/config")
def put_config(data: PipelineConfig, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    errors = config.check_step_prefs(data, STEP_CAPABILITIES)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return config.save_config(data).model_dump(mode="json")


@router.get("/config/versions")
def get_versions() -> list[dict]:
    config.load_config()  # seeds version 1 on first use
    return config.list_versions()


@router.post("/config/rollback/{version}")
def post_rollback(version: int, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    try:
        return config.rollback(version).model_dump(mode="json")
    except config.VersionNotFound:
        raise HTTPException(status_code=404, detail=f"no config version {version}")


@router.post("/config/reset")
def post_reset(x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    return config.reset_to_defaults().model_dump(mode="json")


def _last_tests() -> dict[str, dict]:
    """The newest connection test per adapter, from the ledger."""
    last: dict[str, dict] = {}
    for attempt in store.list_attempts(TEST_RUN_ID):  # oldest first, so newest wins
        last[attempt.adapter] = {"outcome": attempt.outcome, "error": attempt.error, "model": attempt.model,
                                 "at": attempt.started_at, "duration_ms": attempt.duration_ms}
    return last


@router.get("/steps")
def get_steps() -> list[dict]:
    """Each step and the capability its preferred and canary adapters must have."""
    return [{"step": step, "capability": capability} for step, capability in STEP_CAPABILITIES.items()]


@router.get("/adapters")
def get_adapters() -> list[dict]:
    blocked = HEALTH.blocked_families()
    tests = _last_tests()
    return [
        {**spec.model_dump(mode="json"), "key_set": config.key_set(spec), "health": HEALTH.status(spec, blocked),
         "last_test": tests.get(spec.name)}
        for spec in config.load_config().adapters.values()
    ]


@router.post("/adapters/{name}/test")
def post_adapter_test(name: str, x_job_machine: str | None = Header(default=None)) -> dict:
    """One tiny call through the adapter, recorded in the ledger under run
    `adapter-test`. Works on a disabled adapter, so it can be checked before enabling."""
    _require_dashboard(x_job_machine)
    spec = config.load_config().adapters.get(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"no adapter {name!r}")
    adapter = TrackedAdapter(build_adapter(spec), HEALTH)
    started, t0 = now_iso(), time.monotonic()
    result = adapter.call(_TEST_PROMPT, run_id=TEST_RUN_ID, step="adapter_test", schema=_TEST_SCHEMA,
                          timeout=min(spec.timeout_for("cheap"), _TEST_TIMEOUT))
    attempt = Attempt(
        id=uuid.uuid4().hex, run_id=TEST_RUN_ID, job_id="", step="adapter_test", adapter=name,
        model=result.model, started_at=started, duration_ms=int((time.monotonic() - t0) * 1000),
        outcome=result.outcome, error=result.error, tokens_in=result.tokens_in,
        tokens_out=result.tokens_out, cost=result.cost, output_ref=result.output_ref,
    )
    store.add_attempt(attempt)
    return {"adapter": name, "outcome": result.outcome, "error": result.error, "model": result.model,
            "duration_ms": attempt.duration_ms, "attempt_id": attempt.id}


# --- runs (M8) -------------------------------------------------------------------------

MAX_ENQUEUE = 50


class RunRequest(BaseModel):
    pipeline: str
    job_ids: list[str] = Field(default_factory=list, max_length=MAX_ENQUEUE)


def _packet_order() -> list[str]:
    from app.pipeline.pipelines import PACKET_PIPELINE

    return PACKET_PIPELINE.order


@router.post("/runs", status_code=201)
def post_runs(data: RunRequest, x_job_machine: str | None = Header(default=None)) -> dict:
    """Queue runs. A task pipeline (mail_sync, liveness_sweep, remote_boards,
    ats_watchlist) gets one run and refuses a second while one is queued or running;
    `packet` gets one run per dossier id, skipping a dossier that already has one."""
    _require_dashboard(x_job_machine)
    if data.pipeline in tasks.TASK_BUILDERS:
        queued, active = tasks.enqueue_if_idle(data.pipeline)
        if active is not None:
            raise HTTPException(status_code=409, detail=f"{data.pipeline} already has run {active.id} ({active.status})")
        return {"queued": [queued.model_dump(mode="json")], "skipped": []}
    if data.pipeline != "packet":
        names = ", ".join(["packet", *tasks.TASK_BUILDERS])
        raise HTTPException(status_code=422, detail=f"unknown pipeline {data.pipeline!r}; one of {names}")
    if not data.job_ids:
        raise HTTPException(status_code=422, detail="packet runs need job_ids")
    missing = [job_id for job_id in data.job_ids if job_store.get_job(job_id) is None]
    if missing:
        raise HTTPException(status_code=404, detail=f"no dossier {', '.join(missing)}")
    queued, skipped = [], []
    for job_id in dict.fromkeys(data.job_ids):
        if any(run.pipeline == "packet" and run.status in ("queued", "running") for run in store.list_runs(job_id)):
            skipped.append(job_id)
            continue
        queued.append(store.create_run(job_id, "packet", _packet_order()).model_dump(mode="json"))
    return {"queued": queued, "skipped": skipped}


@router.get("/runs")
def get_runs(job_id: str | None = None, pipeline: str | None = None, status: str | None = None,
             limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    runs = store.list_runs(job_id)
    if pipeline:
        runs = [run for run in runs if run.pipeline == pipeline]
    if status:
        runs = [run for run in runs if run.status == status]
    return [
        {"id": run.id, "job_id": run.job_id, "pipeline": run.pipeline, "status": run.status,
         "terminal_reason": run.terminal_reason, "created_at": run.created_at, "updated_at": run.updated_at,
         "steps": {name: run.steps[name].status for name in run.order}}
        for run in runs[:limit]
    ]


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    attempts = [attempt.model_dump(mode="json") for attempt in store.list_attempts(run_id)]
    return {**run.model_dump(mode="json"), "attempts": attempts}


# --- mail sync results (M8) ------------------------------------------------------------


@router.get("/mail/status")
def get_mail_status() -> dict:
    """The window state and the newest mail sync runs. Never touches Gmail."""
    runs = [run for run in store.list_runs(tasks.task_job_id(tasks.MAIL_SYNC))][:5]
    return {
        "state": mail_store.get_state(),
        "runs": [{"id": run.id, "status": run.status, "terminal_reason": run.terminal_reason,
                  "created_at": run.created_at, "report": run.steps.get("mail_report").output
                  if run.steps.get("mail_report") else None} for run in runs],
    }


@router.get("/mail/events")
def get_mail_events(company: str = "", outcome: str = "", status: str = "", since: str = "", q: str = "",
                    limit: int = Query(default=50, ge=1, le=500)) -> list[dict]:
    """Stored mail sync events, newest first. Reads the store, never Gmail."""
    return mail_store.list_events(company=company, outcome=outcome, status=status, since=since, q=q, limit=limit)


# --- retry, cancel, stats (M6) ---------------------------------------------------------


class RetryRequest(BaseModel):
    step: str | None = None


def _downstream(pipeline, start: str) -> set[str]:
    """`start` and every step that depends on it, directly or not."""
    reset = {start}
    for spec in pipeline.steps:  # listed in dependency order
        if any(dep in reset for dep in spec.deps):
            reset.add(spec.name)
    return reset


def _other_active(run) -> str:
    if run.pipeline in tasks.TASK_BUILDERS:
        active = tasks.active_run(run.pipeline)
        return active.id if active is not None and active.id != run.id else ""
    for other in store.list_runs(run.job_id):
        if other.id != run.id and other.pipeline == run.pipeline and other.status in ("queued", "running"):
            return other.id
    return ""


@router.post("/runs/{run_id}/retry")
def post_retry(run_id: str, data: RetryRequest | None = None, x_job_machine: str | None = Header(default=None)) -> dict:
    """Queue a finished run again, resuming at its first failed step, or at `step` and
    everything after it. Steps before keep their output, so nothing done is redone."""
    _require_dashboard(x_job_machine)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    if run.status in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"run {run_id} is still {run.status}")
    pipeline = worker.pipeline_for(run.pipeline)
    if pipeline is None or pipeline.order != run.order:
        raise HTTPException(status_code=422, detail=f"run {run_id} no longer matches a known pipeline")
    step = (data.step if data else None) or ""
    if step and step not in run.steps:
        raise HTTPException(status_code=422, detail=f"run {run_id} has no step {step!r}")
    if not step:
        failed = [name for name in run.order if run.steps[name].status == "failed"]
        if not failed:
            raise HTTPException(status_code=409, detail="no failed step to resume from; name a step to rerun")
        step = failed[0]
    other = _other_active(run)
    if other:
        raise HTTPException(status_code=409, detail=f"run {other} is already queued or running for this work")
    reset = _downstream(pipeline, step) | {
        name for name, state in run.steps.items() if state.status in ("failed", "skipped", "running")
    }
    try:
        again = store.reset_for_retry(run_id, reset)
    except store.RunActive as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"run": again.model_dump(mode="json"), "reset": [name for name in run.order if name in reset]}


@router.post("/runs/{run_id}/cancel")
def post_cancel(run_id: str, x_job_machine: str | None = Header(default=None)) -> dict:
    """End a queued or running run: mark it cancelled, free its lease and kill its
    running CLI processes. Its worker stops at the next adapter boundary with no write."""
    _require_dashboard(x_job_machine)
    try:
        run = store.cancel_run(run_id, "cancelled from the dashboard or API")
    except store.RunNotFound:
        raise HTTPException(status_code=404, detail=f"no run {run_id}")
    except store.RunFinished as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    killed = adapters_module.kill_run(run_id)
    return {"run": run.model_dump(mode="json"), "killed": killed}


@router.get("/stats")
def get_stats(since: str = "") -> dict:
    """The attempt ledger summarised per step and adapter, and per model."""
    try:
        summary = stats.compute(store.list_attempts(), since=since)
    except ValueError:
        raise HTTPException(status_code=422, detail="since must be an ISO 8601 time")
    counts: dict[str, int] = {}
    for run in store.list_runs():
        counts[run.status] = counts.get(run.status, 0) + 1
    return {**summary, "runs": counts}
