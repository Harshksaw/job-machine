"""`/api/pipeline/*` routes for the agent and model settings (spec 13.5): read and save
the config, its version history and rollback, the adapter list with key and health
state, and a one call test per adapter.

Mounted in app/main.py so the dashboard's "Agents and models" settings can use it. No
worker starts from here; the worker pool is wired in M6. Mutating routes
require the `X-Job-Machine: dashboard` header, like the other dashboard writes. Keys
are never returned: only whether the named env var is set.
"""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Header, HTTPException

from app.pipeline import config, store
from app.pipeline.adapters import build_adapter
from app.pipeline.config import PipelineConfig
from app.pipeline.models import Attempt, now_iso
from app.pipeline import router as router_module
from app.pipeline.router import TrackedAdapter
from app.search import _require_dashboard

router = APIRouter(prefix="/api/pipeline")

# The process wide health view, shared with llm.complete and the worker pool (M6).
HEALTH = router_module.HEALTH

# The capability each step needs (spec section 4), used to check step preferences
# until the step registry (steps.py, M3 and M4) owns this.
STEP_CAPABILITIES = {
    "fetch_jd": "web",
    "eligibility": "cheap",
    "fit_score": "reason",
    "resolve_apply_url": "web",
    "company_context": "web",
    "kit": "reason",
    "form_fields": "browser_read",
    "people": "web",
    "answers": "reason",
    "review": "cheap",
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
