"""Runs and mail sync result routes (M8)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import job_store
from app.mail import store as mail_store
from app.models import JobWorkspaceInput
from app.pipeline import api, store

HEADERS = {"X-Job-Machine": "dashboard"}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(mail_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mail_store, "_JSON_BACKENDS", {})
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_enqueue_needs_the_header_and_a_known_pipeline(client):
    assert client.post("/api/pipeline/runs", json={"pipeline": "mail_sync"}).status_code == 403
    assert client.post("/api/pipeline/runs", json={"pipeline": "nope"}, headers=HEADERS).status_code == 422


def test_task_run_is_queued_once(client):
    first = client.post("/api/pipeline/runs", json={"pipeline": "mail_sync"}, headers=HEADERS)
    assert first.status_code == 201
    run = first.json()["queued"][0]
    assert run["job_id"] == "task:mail_sync" and run["status"] == "queued"
    assert client.post("/api/pipeline/runs", json={"pipeline": "mail_sync"}, headers=HEADERS).status_code == 409
    listed = client.get("/api/pipeline/runs", params={"pipeline": "mail_sync"}).json()
    assert [r["id"] for r in listed] == [run["id"]] and listed[0]["steps"]["mail_fetch"] == "pending"
    detail = client.get(f"/api/pipeline/runs/{run['id']}").json()
    assert detail["order"][0] == "mail_fetch" and detail["attempts"] == []
    assert client.get("/api/pipeline/runs/missing").status_code == 404


def test_packet_runs_need_existing_dossiers_and_skip_active_ones(client):
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))
    assert client.post("/api/pipeline/runs", json={"pipeline": "packet"}, headers=HEADERS).status_code == 422
    assert client.post("/api/pipeline/runs", json={"pipeline": "packet", "job_ids": ["nope"]},
                       headers=HEADERS).status_code == 404
    body = client.post("/api/pipeline/runs", json={"pipeline": "packet", "job_ids": [job.id, job.id]},
                       headers=HEADERS).json()
    assert len(body["queued"]) == 1 and body["queued"][0]["order"][0] == "claim"
    again = client.post("/api/pipeline/runs", json={"pipeline": "packet", "job_ids": [job.id]}, headers=HEADERS).json()
    assert again == {"queued": [], "skipped": [job.id]}
    assert [r["job_id"] for r in client.get("/api/pipeline/runs", params={"job_id": job.id}).json()] == [job.id]


def test_mail_status_and_events_read_the_store(client):
    mail_store.save_events([
        {"id": "m1", "company": "Acme", "role": "", "date": "2026-02-01", "outcome": "rejected",
         "confident": True, "note": "", "status": "written"},
        {"id": "m2", "company": "Globex", "role": "", "date": "2026-02-02", "outcome": "interview",
         "confident": True, "note": "call", "status": "unmatched"},
    ])
    mail_store.save_state(newest_date="2026-02-02")
    assert client.get("/api/pipeline/mail/status").json()["state"]["newest_date"] == "2026-02-02"
    assert [e["id"] for e in client.get("/api/pipeline/mail/events").json()] == ["m2", "m1"]
    assert [e["id"] for e in client.get("/api/pipeline/mail/events", params={"outcome": "rejected"}).json()] == ["m1"]
    assert [e["id"] for e in client.get("/api/pipeline/mail/events", params={"company": "glob"}).json()] == ["m2"]


# --- retry, cancel, stats (M6) ---------------------------------------------------------

import uuid

from app.pipeline import adapters
from app.pipeline.models import Attempt


def _packet_run(job_id):
    from app.pipeline.pipelines import PACKET_PIPELINE

    return store.create_run(job_id, "packet", PACKET_PIPELINE.order)


def _failed_at(run, step):
    order = run.order
    for name in order[: order.index(step)]:
        store.complete_step(run.id, name, output={"name": name})
    store.update_step(run.id, step, status="failed", error="boom")
    return store.finish_run(run.id, "failed", f"{step}: boom")


def test_retry_resumes_from_the_first_failed_step(client):
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))
    run = _failed_at(_packet_run(job.id), "eligibility")
    assert client.post(f"/api/pipeline/runs/{run.id}/retry").status_code == 403
    assert client.post("/api/pipeline/runs/missing/retry", headers=HEADERS).status_code == 404

    body = client.post(f"/api/pipeline/runs/{run.id}/retry", headers=HEADERS)

    assert body.status_code == 200
    again = store.get_run(run.id)
    assert again.status == "queued" and again.terminal_reason == ""
    assert again.steps["liveness"].status == "done" and again.steps["liveness"].output == {"name": "liveness"}
    assert all(again.steps[name].status == "pending" for name in again.order[again.order.index("eligibility"):])
    assert body.json()["reset"][0] == "eligibility"
    # A queued run cannot be retried again.
    assert client.post(f"/api/pipeline/runs/{run.id}/retry", headers=HEADERS).status_code == 409


def test_retry_from_a_named_step_resets_it_and_what_depends_on_it(client):
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))
    run = _packet_run(job.id)
    for name in run.order:
        store.complete_step(run.id, name, output={})
    store.finish_run(run.id, "packet_ready")
    assert client.post(f"/api/pipeline/runs/{run.id}/retry", headers=HEADERS).status_code == 409  # nothing failed
    assert client.post(f"/api/pipeline/runs/{run.id}/retry", json={"step": "nope"},
                       headers=HEADERS).status_code == 422

    body = client.post(f"/api/pipeline/runs/{run.id}/retry", json={"step": "review"}, headers=HEADERS).json()

    assert body["reset"] == ["review", "repair", "brief"]
    again = store.get_run(run.id)
    assert again.steps["answers"].status == "done" and again.steps["review"].status == "pending"


def test_retry_refuses_while_another_run_of_the_dossier_is_active(client):
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))
    old = _failed_at(_packet_run(job.id), "claim")
    _packet_run(job.id)  # a newer queued run
    assert client.post(f"/api/pipeline/runs/{old.id}/retry", headers=HEADERS).status_code == 409


def test_cancel_ends_an_active_run_and_kills_its_processes(client, monkeypatch):
    killed = []
    monkeypatch.setattr(adapters, "kill_run", lambda run_id: killed.append(run_id) or 2)
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))
    run = _packet_run(job.id)
    store.acquire_lease(run.id, "worker-1")
    assert client.post(f"/api/pipeline/runs/{run.id}/cancel").status_code == 403
    assert client.post("/api/pipeline/runs/missing/cancel", headers=HEADERS).status_code == 404

    body = client.post(f"/api/pipeline/runs/{run.id}/cancel", headers=HEADERS)

    assert body.status_code == 200 and body.json()["killed"] == 2
    assert killed == [run.id]
    done = store.get_run(run.id)
    assert done.status == "cancelled" and done.lease_owner == ""
    assert client.post(f"/api/pipeline/runs/{run.id}/cancel", headers=HEADERS).status_code == 409
    # A cancelled run can be retried from where it stopped.
    assert client.post(f"/api/pipeline/runs/{run.id}/retry", json={"step": "claim"}, headers=HEADERS).status_code == 200


def _attempt(step, adapter, outcome, ms, cost=None, model="", error="", at="2026-11-26T10:00:00+00:00"):
    store.add_attempt(Attempt(id=uuid.uuid4().hex, run_id="r1", job_id="j1", step=step, adapter=adapter,
                              model=model, started_at=at, duration_ms=ms, outcome=outcome, error=error,
                              cost=cost))


def test_stats_per_step_adapter_and_model(client):
    for ms in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000):
        _attempt("fit_score", "haiku", "ok", ms, cost=0.01, model="m-haiku", at=f"2026-11-26T10:00:{ms // 100:02d}+00:00")
    _attempt("fit_score", "haiku", "timeout", 5000, model="m-haiku", error="killed after 480s",
             at="2026-11-26T11:00:00+00:00")
    _attempt("claim", "code", "ok", 5)

    stats = client.get("/api/pipeline/stats").json()

    rows = {(row["step"], row["adapter"]): row for row in stats["steps"]}
    haiku = rows[("fit_score", "haiku")]
    assert haiku["attempts"] == 11 and haiku["ok"] == 10
    assert haiku["pass_rate"] == pytest.approx(10 / 11)
    assert haiku["p50_ms"] == 600 and haiku["p90_ms"] == 1000
    assert haiku["cost"] == pytest.approx(0.10)
    assert haiku["last_error"] == "killed after 480s" and haiku["last_at"] == "2026-11-26T11:00:00+00:00"
    assert rows[("claim", "code")]["cost"] is None
    models = {row["model"]: row for row in stats["models"]}
    assert list(models) == ["m-haiku"] and models["m-haiku"]["attempts"] == 11
    assert client.get("/api/pipeline/stats", params={"since": "2026-11-26T10:30:00+00:00"}).json()["steps"][0]["attempts"] == 1


def test_worker_route_reports_whether_the_pool_runs(client, monkeypatch):
    from app.pipeline import worker

    monkeypatch.setattr(worker, "ACTIVE_POOL", None)
    assert client.get("/api/pipeline/worker").json() == {"running": False, "workers": 0, "max_workers": 0}

    class Pool:
        size = 3
        active_workers = 2

    monkeypatch.setattr(worker, "ACTIVE_POOL", Pool())
    assert client.get("/api/pipeline/worker").json() == {"running": True, "workers": 2, "max_workers": 3}
