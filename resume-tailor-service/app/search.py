"""Dashboard Search tab: Fantastic Jobs presets and agent launches."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app import agent_runs, fantastic, job_store, research_store
from app.models import JobCaptureInput

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
        "presets": [
            {"id": key, "label": p["label"], "stage": p.get("stage", "dossier"),
             "default_limit": p.get("default_limit", 20)}
            for key, p in fantastic.PRESETS.items()
        ],
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


class ResearchItem(BaseModel):
    """What a portal sweep (Cursor, OpenCode, Claude) stages for review."""

    company: str
    role: str
    url: str
    source: str
    location: str = ""
    remote_scope: str = ""
    open_to_canada: bool | None = None
    visa: str | None = None
    salary: str = ""
    posted: str = ""
    jd_text: str = ""
    notes: str = ""
    preset: str = "portal-sweep"


@router.get("/api/research")
def research(preset: str | None = None, status: str | None = None) -> list[dict]:
    items = research_store.list_items(preset, status)
    return [{k: v for k, v in item.items() if k != "jd_text"} for item in items]


@router.post("/api/research", status_code=201)
def add_research(data: ResearchItem, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    item = data.model_dump()
    tracked = job_store.find_matching_job(data.company, data.role, data.url)
    item["tracked_dossier"] = tracked.id if tracked else None
    doc, created = research_store.add(item)
    return {"created": created, "item": {k: v for k, v in doc.items() if k != "jd_text"}}


@router.post("/api/research/{item_id}/promote")
def promote(item_id: str, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    item = research_store.get(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="research item not found")
    job, created = job_store.capture_job(JobCaptureInput(
        company=item["company"], role=item["role"], job_url=item.get("url", ""),
        source=item.get("source", "Research"), location=item.get("location", ""),
        work_mode="remote" if "remote" in item.get("preset", "") else "",
        status="discovered", jd_text=item.get("jd_text", ""),
        notes=f"Promoted from research ({item.get('preset')}). Remote scope: {item.get('remote_scope') or 'unspecified'}. "
              f"Open to Canada: {item.get('open_to_canada')}. Needs a fit score.",
        next_action="Score fit (AGENTS.md rule 2)",
        session=f"Research {item.get('preset')}",
    ))
    research_store.set_status(item_id, "promoted", dossier_id=job.id)
    return {"dossier_id": job.id, "created": created}


@router.post("/api/research/{item_id}/dismiss")
def dismiss(item_id: str, x_job_machine: str | None = Header(default=None)) -> dict:
    _require_dashboard(x_job_machine)
    if research_store.set_status(item_id, "dismissed") is None:
        raise HTTPException(status_code=404, detail="research item not found")
    return {"ok": True}
