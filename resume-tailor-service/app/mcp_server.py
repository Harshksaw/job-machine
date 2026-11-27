"""The `job-machine` MCP server (spec 13.3): dossier and pipeline tools for any agent.

    cd resume-tailor-service
    uv run python -m app.mcp_server            # stdio transport

Claude Code, Cursor, Codex, Antigravity and in process agents all get the same tools
instead of curl instructions. It talks HTTP to the service at `JOB_MACHINE_API`
(default http://127.0.0.1:8420), so it works against whichever copy of the service is
running and holds no data of its own.

Tools: get_dossier, list_dossiers, patch_dossier, enqueue_run, run_status,
search_mail_events. `patch_dossier` changes only the fields the caller names and never
sets status `applied` (that is an `applied` activity after a real submission, AGENTS.md
rule 8). `search_mail_events` reads stored mail sync results, never Gmail.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_API = "http://127.0.0.1:8420"
# The service's guard header for writes (app/search.py _require_dashboard).
_WRITE_HEADERS = {"X-Job-Machine": "dashboard"}
# Fields a patch may never touch: identity, history, and the application record.
_READ_ONLY = frozenset({"id", "activities", "revisions", "created_at", "updated_at"})
_LIST_FIELDS = ("id", "company", "role", "status", "fit_score", "priority", "location", "work_mode",
                "job_url", "next_action", "deadline", "updated_at")
MAX_LIST = 200


class Api:
    """Thin client over the service routes the tools use."""

    def __init__(self, client: httpx.Client | None = None, base_url: str | None = None):
        base = (base_url or os.environ.get("JOB_MACHINE_API") or DEFAULT_API).rstrip("/")
        self._client = client or httpx.Client(base_url=base, timeout=30)

    def request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ToolError(f"job machine service unreachable: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise ToolError(f"HTTP {response.status_code}: {str(detail)[:300]}")
        return response.json() if response.content else None


def _safe_id(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value or not all(ch.isalnum() or ch in "-_" for ch in value):
        raise ToolError(f"invalid {label} {value!r}")
    return value


def build_server(api: Api | None = None) -> MCPServer:
    api = api or Api()
    server = MCPServer(
        "job-machine",
        instructions=(
            "Dossiers and pipeline runs of Harsh's job search service. Read AGENTS.md before "
            "acting on a dossier. These tools never submit applications or send messages."
        ),
    )

    @server.tool()
    def get_dossier(job_id: str, include_revisions: bool = False) -> dict:
        """One dossier by id: fields, answers and activities (revisions only when asked)."""
        job = api.request("GET", f"/api/jobs/{_safe_id(job_id, 'job id')}")
        if not include_revisions:
            job.pop("revisions", None)
        return job

    @server.tool()
    def list_dossiers(status: str = "", q: str = "", min_fit: int | None = None, limit: int = 50) -> list[dict]:
        """Dossier summaries, optionally by status, a text match on company, role, source,
        location or next action, and a minimum fit score. Newest first, at most 200."""
        params = {key: value for key, value in (("status", status), ("q", q)) if value}
        jobs = api.request("GET", "/api/jobs", params=params)
        if min_fit is not None:
            jobs = [job for job in jobs if (job.get("fit_score") or 0) >= min_fit]
        jobs.sort(key=lambda job: job.get("updated_at") or "", reverse=True)
        return [{key: job.get(key) for key in _LIST_FIELDS} for job in jobs[:max(0, min(limit, MAX_LIST))]]

    @server.tool()
    def patch_dossier(job_id: str, fields: dict[str, Any], session: str = "mcp") -> dict:
        """Change only the named dossier fields (PATCH): fields left out are untouched.
        The caller owns what it sends. Never sets status `applied`; log a real submission
        as an `applied` activity instead (AGENTS.md rule 8)."""
        if not fields:
            raise ToolError("no fields to change")
        blocked = sorted(set(fields) & _READ_ONLY)
        if blocked:
            raise ToolError(f"read only fields: {', '.join(blocked)}")
        if str(fields.get("status", "")).strip().lower() == "applied":
            raise ToolError("patch_dossier never sets status applied")
        job = api.request("PATCH", f"/api/jobs/{_safe_id(job_id, 'job id')}", json=fields,
                          params={"session": session or "mcp"})
        job.pop("revisions", None)
        return job

    @server.tool()
    def enqueue_run(pipeline: str, job_ids: list[str] | None = None) -> dict:
        """Queue a pipeline run: `packet` with dossier ids, or a task pipeline
        (mail_sync, liveness_sweep, remote_boards, ats_watchlist) with none."""
        ids = [_safe_id(job_id, "job id") for job_id in job_ids or []]
        return api.request("POST", "/api/pipeline/runs", json={"pipeline": pipeline, "job_ids": ids},
                           headers=_WRITE_HEADERS)

    @server.tool()
    def run_status(run_id: str = "", job_id: str = "", pipeline: str = "", limit: int = 20) -> dict:
        """One run with its steps and attempts by id, or `{"runs": [...]}`, the newest
        runs filtered by dossier id or pipeline name."""
        if run_id:
            return api.request("GET", f"/api/pipeline/runs/{_safe_id(run_id, 'run id')}")
        params: dict = {"limit": max(1, min(limit, 500))}
        if job_id:
            params["job_id"] = job_id
        if pipeline:
            params["pipeline"] = pipeline
        return {"runs": api.request("GET", "/api/pipeline/runs", params=params)}

    @server.tool()
    def search_mail_events(company: str = "", outcome: str = "", status: str = "", since: str = "",
                           q: str = "", limit: int = 50) -> list[dict]:
        """Stored mail sync results, newest first. `outcome` is rejected, interview,
        assessment or reply; `status` is written, duplicate, held, unmatched or ignored;
        `since` is YYYY-MM-DD. Reads what mail sync stored, never the inbox."""
        params = {key: value for key, value in (("company", company), ("outcome", outcome), ("status", status),
                                                 ("since", since), ("q", q)) if value}
        params["limit"] = max(1, min(limit, 500))
        return api.request("GET", "/api/pipeline/mail/events", params=params)

    return server


def main() -> None:
    build_server().run("stdio")


if __name__ == "__main__":
    main()
