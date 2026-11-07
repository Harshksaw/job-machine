"""Dashboard Search tab: Fantastic Jobs presets and agent launches."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app import agent_runs, fantastic

router = APIRouter()

# Browsers cannot attach a custom header to a cross site request without a CORS
# preflight, and this service grants none, so requiring it blocks drive by POSTs.
_DASHBOARD_HEADER = "dashboard"


def _require_dashboard(value: str | None) -> None:
    if value != _DASHBOARD_HEADER:
        raise HTTPException(status_code=403, detail="missing X-Job-Machine header")


class SearchRequest(BaseModel):
    preset: str
    limit: int = Field(default=25, ge=1, le=fantastic.MAX_LIMIT)
    time_frame: str = "7d"


class AgentRequest(BaseModel):
    tool: str
    task: str


@router.get("/api/search/presets")
def presets() -> dict:
    return {
        "presets": [{"id": key, "label": p["label"]} for key, p in fantastic.PRESETS.items()],
        "tasks": [{"id": key, "label": t["label"]} for key, t in agent_runs.TASKS.items()],
        "tools": list(agent_runs.TOOLS),
    }


@router.get("/api/search/usage")
def usage() -> dict:
    return fantastic.usage_summary()


@router.post("/api/search/run")
def run(data: SearchRequest, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    try:
        return fantastic.run_search(data.preset, data.limit, data.time_frame)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/api/agents/run")
def run_agent(data: AgentRequest, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    try:
        return agent_runs.start(data.tool, data.task)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/agents/runs")
def runs() -> list[dict]:
    return agent_runs.recent()
