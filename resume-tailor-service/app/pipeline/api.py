"""`/api/pipeline/*` routes for the agent and model settings (spec 13.5): read and save
the config, its version history and rollback, the adapter list with key and health
state, and a one call test per adapter.

Also (M8): enqueue and read pipeline runs, and the stored mail sync results, which the
MCP server and later the dashboard read. Runs only queue here; the M6 worker or
`scripts/run_task.py` executes them.

Mounted in app/main.py so the dashboard's "Agents and models" settings can use it. No
worker starts from here; the worker pool is wired in M6. Mutating routes
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
from app.pipeline import config, store, tasks
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
        active = tasks.active_run(data.pipeline)
        if active is not None:
            raise HTTPException(status_code=409, detail=f"{data.pipeline} already has run {active.id} ({active.status})")
        return {"queued": [tasks.enqueue(data.pipeline).model_dump(mode="json")], "skipped": []}
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
