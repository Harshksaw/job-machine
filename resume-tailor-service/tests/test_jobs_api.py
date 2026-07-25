import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import application_kit, job_store, jobs, sheets
from app.models import (
    Application,
    FitAnalysis,
    GeneratedApplicationKit,
    JobSelection,
    Manifest,
    ProjectSelection,
    TailoredResumeMeta,
)


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "output")
    app = FastAPI()
    app.include_router(jobs.router)
    return TestClient(app)


def _create(client: TestClient) -> dict:
    response = client.post(
        "/api/jobs",
        json={
            "company": "Acme",
            "role": "Backend Engineer",
            "jd_text": "A" * 120,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_job_crud_activity_and_restore(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = _create(client)
    job_id = created["id"]

    listed = client.get("/api/jobs").json()
    assert listed[0]["id"] == job_id
    assert "revisions" not in listed[0]

    original_revision = created["revisions"][0]["id"]
    update_payload = {
        key: value
        for key, value in created.items()
        if key not in {"id", "activities", "revisions", "created_at", "updated_at"}
    }
    update_payload["notes"] = "Follow the infrastructure angle."
    updated = client.put(
        f"/api/jobs/{job_id}?session=Manual",
        json=update_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["notes"].startswith("Follow")

    activity = client.post(
        f"/api/jobs/{job_id}/activity",
        json={
            "kind": "applied",
            "title": "Application submitted",
            "detail": "Confirmation received",
            "session": "LinkedIn 2026-07-23",
        },
    )
    assert activity.status_code == 200
    assert activity.json()["activities"][-1]["kind"] == "applied"

    restored = client.post(
        f"/api/jobs/{job_id}/restore/{original_revision}",
    )
    assert restored.status_code == 200
    assert restored.json()["notes"] == ""

    deleted = client.delete(f"/api/jobs/{job_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_generate_kit_updates_job(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = _create(client)
    fake_kit = GeneratedApplicationKit(
        analysis=FitAnalysis(
            score=9,
            recommendation="apply",
            verdict="Direct match.",
        ),
        cover_letter="Curated letter",
    )
    monkeypatch.setattr(application_kit, "generate_kit", lambda *_: fake_kit)

    response = client.post(f"/api/jobs/{created['id']}/generate-kit")
    assert response.status_code == 200
    body = response.json()
    assert body["fit_score"] == 9
    assert body["cover_letter"] == "Curated letter"
    assert body["status"] == "ready"


def test_capture_endpoint_is_automation_friendly(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/jobs/capture",
        json={
            "company": "Acme",
            "role": "SWE",
            "job_url": "https://example.com/job",
            "fit_score": 8,
            "jd_text": "Full listing text",
            "session": "LinkedIn 2026-07-23",
        },
    )
    assert response.status_code == 200
    assert response.json()["fit_score"] == 8
    assert response.json()["jd_text"] == "Full listing text"


def test_sensitive_answer_is_saved_as_needing_input(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    created = _create(client)
    response = client.post(
        f"/api/jobs/{created['id']}/answers/generate",
        json={"question": "What salary do you expect?", "session": "Application"},
    )
    assert response.status_code == 200
    answer = response.json()["application_answers"][0]
    assert answer["needs_user_input"] is True
    assert answer["answer"] == ""
    assert answer["clarification"]


def test_sheet_import_upserts_one_dossier_with_two_events(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sheets,
        "fetch_applications",
        lambda: [
            Application(
                company="Acme",
                role="SWE",
                status="applied",
                job_url="https://example.com/1",
                timestamp="2026-07-23T10:00:00Z",
            ),
            Application(
                company="Acme",
                role="SWE",
                status="interview",
                job_url="https://example.com/1",
                timestamp="2026-07-24T10:00:00Z",
            ),
        ],
    )
    response = client.post("/api/jobs/import-sheet")
    assert response.status_code == 200
    assert response.json()["created_jobs"] == 1
    assert len(response.json()["job_ids"]) == 1
    detail = client.get(f"/api/jobs/{response.json()['job_ids'][0]}").json()
    assert detail["status"] == "interview"
    assert len([event for event in detail["activities"] if event["kind"] == "sheet"]) == 2

    repeated = client.post("/api/jobs/import-sheet")
    assert repeated.status_code == 200
    assert repeated.json()["created_jobs"] == 0
    assert repeated.json()["updated_jobs"] == 0


def test_invalid_job_id_is_rejected(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    assert client.get("/api/jobs/%2e%2e").status_code in (400, 404)


def test_sheet_import_backfills_jd_from_tailored_metadata(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    output = tmp_path / "output" / "acme-swe-resume"
    output.mkdir(parents=True)
    meta = TailoredResumeMeta(
        company="Acme",
        role="SWE",
        jd_text="Complete job description recovered from the resume artifact.",
        pdf_path=str(output / "resume.pdf"),
        manifest=Manifest(
            summary="summary",
            job_selections=[
                JobSelection(job_id="ommuse", bullet_ids=["ommuse.bullet.1"])
            ],
            project_selections=[
                ProjectSelection(
                    project_id="docintel",
                    bullet_ids=["project.docintel.bullet.1"],
                )
            ],
            achievement_ids=[],
            job_trim_priority=["ommuse"],
        ),
        pages=1,
        created_at="2026-07-23T00:00:00+00:00",
    )
    (output / "meta.json").write_text(
        json.dumps(meta.model_dump()),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sheets,
        "fetch_applications",
        lambda: [Application(company="Acme", role="SWE", status="applied")],
    )
    imported = client.post("/api/jobs/import-sheet").json()
    detail = client.get(f"/api/jobs/{imported['job_ids'][0]}").json()
    assert detail["tailored_resume_id"] == "acme-swe-resume"
    assert detail["jd_text"].startswith("Complete job description")
