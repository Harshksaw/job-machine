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
