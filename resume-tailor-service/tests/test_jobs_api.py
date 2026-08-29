import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import (
    application_kit,
    job_store,
    jobs,
    people_store,
    session_store,
    sheets,
)
from app.models import (
    Application,
    FitAnalysis,
    GeneratedApplicationKit,
    JobWorkspaceInput,
    JobSelection,
    Manifest,
    PersonInput,
    ProjectSelection,
    TailoredResumeMeta,
)


def _client(
    monkeypatch,
    tmp_path,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(jobs, "OUTPUT_DIR", tmp_path / "output")
    app = FastAPI()
    app.include_router(jobs.router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


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
    assert listed[0]["has_cover_letter"] is False
    assert listed[0]["needs_user_input"] is False
    assert listed[0]["work_mode"] == ""
    assert "notes" in listed[0]

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


def test_job_people_are_pinned_counted_and_logged(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    job_id = job["id"]

    listed = client.get("/api/jobs").json()
    assert listed[0]["person_count"] == 0

    added = client.post(
        f"/api/jobs/{job_id}/people",
        json={"name": "Alex Recruiter", "company": "Acme", "title": "Recruiter"},
    )
    assert added.status_code == 201
    body = added.json()
    assert body["job_id"] == job_id
    assert body["company"] == "Acme"
    assert body["role"] == "Backend Engineer"

    people = client.get(f"/api/jobs/{job_id}/people").json()
    assert len(people) == 1 and people[0]["name"] == "Alex Recruiter"

    listed = client.get("/api/jobs").json()
    assert listed[0]["person_count"] == 1

    detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["activities"][-1]["title"] == "Added Alex Recruiter to reach"
    session_events = session_store.list_events(job_id=job_id)
    assert len(session_events) == 1
    assert session_events[0].title == "Added Alex Recruiter to reach"
    assert session_events[0].session == "Inbox"


def test_inbox_approve_preserves_unrelated_dossier_fields(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    payload = {key: job[key] for key in JobWorkspaceInput.model_fields}
    payload.update(
        {
            "fit_score": 8,
            "notes": "New agent research that must survive the decision.",
            "cover_letter": "Dear team,",
        }
    )
    saved = client.put(f"/api/jobs/{job['id']}", json=payload)
    assert saved.status_code == 200

    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": "approve", "session": "Inbox 2026-08-27"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["next_action"] == "Apply; reach out to people at the company"
    assert body["notes"] == "New agent research that must survive the decision."
    assert body["cover_letter"] == "Dear team,"
    assert body["activities"][-1]["title"] == "Approved to apply"
    assert body["activities"][-1]["session"] == "Inbox 2026-08-27"
    assert body["revisions"][-1]["changed_fields"] == ["status", "next_action"]
    events = session_store.list_events(job_id=job["id"])
    assert len(events) == 1
    assert events[0].title == "Approved to apply"


@pytest.mark.parametrize(
    ("initial_status", "decision", "expected_status", "expected_next_action"),
    [
        ("discovered", "hold", "researching", "Review later"),
        ("researching", "approve", "ready", "Apply"),
        ("researching", "hold", "researching", "Review later"),
        ("ready", "applied", "applied", "Await response"),
        ("applying", "applied", "applied", "Await response"),
    ],
)
def test_inbox_decision_maps_remaining_actions(
    monkeypatch,
    tmp_path,
    initial_status,
    decision,
    expected_status,
    expected_next_action,
):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    if initial_status != job["status"]:
        payload = {key: job[key] for key in JobWorkspaceInput.model_fields}
        payload["status"] = initial_status
        saved = client.put(f"/api/jobs/{job['id']}", json=payload)
        assert saved.status_code == 200

    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": decision, "session": "Inbox"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == expected_status
    assert response.json()["next_action"] == expected_next_action


def test_inbox_decision_rejects_unknown_action_without_mutation(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)

    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": "delete", "session": "Inbox"},
    )

    assert response.status_code == 422
    unchanged = client.get(f"/api/jobs/{job['id']}").json()
    assert unchanged["status"] == "discovered"
    assert unchanged["next_action"] == ""


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        ("interview", "approve"),
        ("interview", "hold"),
        ("discovered", "applied"),
    ],
)
def test_inbox_decision_rejects_invalid_transition_without_mutation(
    monkeypatch,
    tmp_path,
    status,
    decision,
):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    payload = {key: job[key] for key in JobWorkspaceInput.model_fields}
    payload.update({"status": status, "next_action": "Keep current action"})
    saved = client.put(f"/api/jobs/{job['id']}", json=payload)
    assert saved.status_code == 200
    before = client.get(f"/api/jobs/{job['id']}").json()

    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": decision, "session": "Inbox"},
    )

    assert response.status_code == 409
    assert client.get(f"/api/jobs/{job['id']}").json() == before


def test_job_people_summary_count_matches_nested_association(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    backend = _create(client)
    frontend_response = client.post(
        "/api/jobs",
        json={
            "company": "Acme",
            "role": "Frontend Engineer",
            "jd_text": "B" * 120,
        },
    )
    assert frontend_response.status_code == 201
    frontend = frontend_response.json()

    people_store.add_person(
        PersonInput(name="Backend Recruiter", company="Acme", role="Backend Engineer")
    )
    people_store.add_person(PersonInput(name="Company Recruiter", company="Acme"))
    people_store.add_person(
        PersonInput(
            name="Pinned Frontend Recruiter",
            company="Acme",
            role="Backend Engineer",
            job_id=frontend["id"],
        )
    )

    summaries = {row["id"]: row for row in client.get("/api/jobs").json()}
    backend_people = client.get(f"/api/jobs/{backend['id']}/people").json()
    frontend_people = client.get(f"/api/jobs/{frontend['id']}/people").json()

    assert summaries[backend["id"]]["person_count"] == len(backend_people) == 2
    assert summaries[frontend["id"]]["person_count"] == len(frontend_people) == 2


def test_blank_legacy_person_role_matches_company_job(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    people_store.add_person(
        PersonInput(name="Company Recruiter", company="Acme", role="   ")
    )

    summary = client.get("/api/jobs").json()[0]
    nested = client.get(f"/api/jobs/{job['id']}/people").json()

    assert summary["person_count"] == 1
    assert [person["name"] for person in nested] == ["Company Recruiter"]


def test_decision_stays_successful_when_session_mirror_is_unavailable(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path, raise_server_exceptions=False)
    job = _create(client)

    def fail_to_append(_):
        raise OSError("session store unavailable")

    monkeypatch.setattr(session_store, "append_event", fail_to_append)
    response = client.post(
        f"/api/jobs/{job['id']}/decision",
        json={"decision": "approve", "session": "Inbox"},
    )

    assert response.status_code == 200
    persisted = client.get(f"/api/jobs/{job['id']}").json()
    assert persisted["status"] == "ready"
    assert [
        event["title"]
        for event in persisted["activities"]
        if event["kind"] == "decision"
    ] == ["Approved to apply"]


def test_person_creation_stays_successful_when_activity_log_is_unavailable(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path, raise_server_exceptions=False)
    job = _create(client)

    def fail_to_log(*_args, **_kwargs):
        raise OSError("job activity store unavailable")

    monkeypatch.setattr(job_store, "add_activity", fail_to_log)
    response = client.post(
        f"/api/jobs/{job['id']}/people",
        json={"name": "Alex Recruiter", "company": "Acme"},
    )

    assert response.status_code == 201
    assert response.json()["job_id"] == job["id"]
    assert [person.name for person in people_store.load_people()] == [
        "Alex Recruiter"
    ]


def test_person_creation_rolls_back_when_job_disappears(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    monkeypatch.setattr(job_store, "add_activity", lambda *_args, **_kwargs: None)

    response = client.post(
        f"/api/jobs/{job['id']}/people",
        json={"name": "Alex Recruiter", "company": "Acme"},
    )

    assert response.status_code == 404
    assert people_store.load_people() == []


def test_person_creation_reports_failed_rollback_when_job_disappears(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    monkeypatch.setattr(job_store, "add_activity", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(people_store, "delete_person", lambda _person_id: False)

    response = client.post(
        f"/api/jobs/{job['id']}/people",
        json={"name": "Alex Recruiter", "company": "Acme"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "job disappeared after person creation and contact rollback failed"
    )


def test_person_creation_reports_unreadable_store_during_rollback(
    monkeypatch,
    tmp_path,
):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)
    unreadable = False
    original_read_text = Path.read_text

    def disappear_after_person_creation(*_args, **_kwargs):
        nonlocal unreadable
        unreadable = True
        return None

    def fail_people_read(path, *args, **kwargs):
        if unreadable and path == people_store.STORE_PATH:
            raise PermissionError("people store unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(job_store, "add_activity", disappear_after_person_creation)
    monkeypatch.setattr(Path, "read_text", fail_people_read)
    response = client.post(
        f"/api/jobs/{job['id']}/people",
        json={"name": "Alex Recruiter", "company": "Acme"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "job disappeared after person creation and contact rollback failed"
    )
    unreadable = False
    assert [person.name for person in people_store.load_people()] == [
        "Alex Recruiter"
    ]
