"""The job-machine MCP server against the real routes on a TestClient: no network."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from app import job_store, jobs, people_store, session_store
from app.mail import store as mail_store
from app.mcp_server import Api, build_server
from app.models import JobWorkspaceInput
from app.pipeline import api, store


@pytest.fixture
def server(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(mail_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mail_store, "_JSON_BACKENDS", {})
    app = FastAPI()
    app.include_router(jobs.router)
    app.include_router(api.router)
    return build_server(Api(TestClient(app)))


def call(server, name, **args):
    result = asyncio.run(server.call_tool(name, args))
    assert not result.is_error, result.content
    data = result.structured_content
    if data is None:  # a plain dict return comes back as JSON text
        data = json.loads(result.content[0].text)
    return data["result"] if isinstance(data, dict) and set(data) == {"result"} else data


def call_error(server, name, **args):
    try:
        result = asyncio.run(server.call_tool(name, args))
    except ToolError as exc:
        return str(exc)
    assert result.is_error
    return " ".join(getattr(part, "text", "") for part in result.content)


def _job(**extra):
    return job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer", **extra))


def test_lists_the_six_tools(server):
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"get_dossier", "list_dossiers", "patch_dossier", "enqueue_run", "run_status",
                     "search_mail_events"}


def test_get_and_list_dossiers(server):
    a = _job(status="ready", fit_score=8)
    _job(status="discovered", fit_score=4)
    got = call(server, "get_dossier", job_id=a.id)
    assert got["company"] == "Acme" and "revisions" not in got
    assert "revisions" in call(server, "get_dossier", job_id=a.id, include_revisions=True)
    assert [j["id"] for j in call(server, "list_dossiers", status="ready")] == [a.id]
    assert [j["id"] for j in call(server, "list_dossiers", min_fit=6)] == [a.id]
    assert len(call(server, "list_dossiers", limit=1)) == 1
    assert "404" in call_error(server, "get_dossier", job_id="missing")
    assert "invalid" in call_error(server, "get_dossier", job_id="../x")


def test_patch_changes_only_named_fields_and_never_sets_applied(server):
    job = _job(notes="keep", status="ready")
    out = call(server, "patch_dossier", job_id=job.id, fields={"next_action": "Apply"})
    assert out["next_action"] == "Apply" and out["notes"] == "keep"
    assert job_store.get_job(job.id).next_action == "Apply"
    assert "never sets status applied" in call_error(server, "patch_dossier", job_id=job.id,
                                                     fields={"status": "Applied"})
    assert "read only" in call_error(server, "patch_dossier", job_id=job.id, fields={"activities": []})
    assert "422" in call_error(server, "patch_dossier", job_id=job.id, fields={"bogus": 1})
    assert job_store.get_job(job.id).status == "ready"


def test_enqueue_and_run_status(server):
    job = _job()
    queued = call(server, "enqueue_run", pipeline="packet", job_ids=[job.id])
    run_id = queued["queued"][0]["id"]
    assert call(server, "run_status", run_id=run_id)["job_id"] == job.id
    assert [r["id"] for r in call(server, "run_status", job_id=job.id)["runs"]] == [run_id]
    task = call(server, "enqueue_run", pipeline="mail_sync")
    assert task["queued"][0]["job_id"] == "task:mail_sync"
    assert "409" in call_error(server, "enqueue_run", pipeline="mail_sync")
    assert [r["pipeline"] for r in call(server, "run_status", pipeline="mail_sync")["runs"]] == ["mail_sync"]


def test_search_mail_events_reads_the_store(server):
    mail_store.save_events([{"id": "m1", "company": "Acme", "role": "", "date": "2026-02-01",
                             "outcome": "interview", "confident": True, "note": "call", "status": "written"}])
    assert [e["id"] for e in call(server, "search_mail_events", company="acme")] == ["m1"]
    assert call(server, "search_mail_events", outcome="rejected") == []


def test_unreachable_service_is_a_tool_error():
    def refuse(request):
        raise httpx.ConnectError("refused")

    server = build_server(Api(httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://x")))
    assert "unreachable" in call_error(server, "list_dossiers")


def test_base_url_from_env(monkeypatch):
    monkeypatch.setenv("JOB_MACHINE_API", "http://127.0.0.1:8421/")
    assert str(Api()._client.base_url) == "http://127.0.0.1:8421"
