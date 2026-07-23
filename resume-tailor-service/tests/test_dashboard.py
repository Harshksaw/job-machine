import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import dashboard, sheets
from app.dashboard import index_tailored
from app.errors import SheetsError
from app.models import (
    Application,
    JobSelection,
    Manifest,
    ProjectSelection,
    TailoredResumeMeta,
)

AUTH = {"Authorization": "Bearer test-token"}


def _meta(company, role, created_at, job_url=None):
    return TailoredResumeMeta(
        company=company,
        role=role,
        jd_text="jd text",
        pdf_path="/some/output/resume.pdf",
        manifest=Manifest(
            summary="summary",
            job_selections=[JobSelection(job_id="ommuse", bullet_ids=["ommuse.bullet.1"])],
            project_selections=[ProjectSelection(project_id="docintel", bullet_ids=["project.docintel.bullet.1"])],
            achievement_ids=["achievement.lms"],
            job_trim_priority=["ommuse"],
        ),
        pages=1,
        created_at=created_at,
        job_url=job_url,
    )


def _write_meta(output_dir, dir_name, meta):
    d = output_dir / dir_name
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta.model_dump()), encoding="utf-8")
    return d


# --------------------------------------------------------------------------- #
# index_tailored: pure-function tests over a temp output dir
# --------------------------------------------------------------------------- #

def test_index_tailored_matches_dir(tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    index = index_tailored(tmp_path)
    assert index == {"flowline-backend-engineer": "flowline-backend-engineer-abc123"}


def test_index_tailored_skips_dir_without_meta(tmp_path):
    (tmp_path / "no-meta-here").mkdir()
    assert index_tailored(tmp_path) == {}


def test_index_tailored_skips_corrupt_meta(tmp_path):
    d = tmp_path / "corrupt"
    d.mkdir()
    (d / "meta.json").write_text("{ this is not valid json", encoding="utf-8")
    # must not raise
    assert index_tailored(tmp_path) == {}


def test_index_tailored_most_recent_created_at_wins(tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-old",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    _write_meta(tmp_path, "flowline-backend-engineer-new",
                _meta("Flowline", "Backend Engineer", "2026-06-01T00:00:00+00:00"))
    index = index_tailored(tmp_path)
    assert index["flowline-backend-engineer"] == "flowline-backend-engineer-new"


def test_index_tailored_missing_output_dir(tmp_path):
    assert index_tailored(tmp_path / "does-not-exist") == {}


# --------------------------------------------------------------------------- #
# _resolve_dir: id validation (direct, deterministic)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("bad", ["../secret", "foo/bar", "..", "a/../b", "..%2f..", "with space"])
def test_resolve_dir_rejects_bad_ids(monkeypatch, tmp_path, bad):
    monkeypatch.setattr(dashboard, "OUTPUT_DIR", tmp_path)
    with pytest.raises(HTTPException) as ei:
        dashboard._resolve_dir(bad)
    assert ei.value.status_code == 400


def test_resolve_dir_accepts_valid_id(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "OUTPUT_DIR", tmp_path)
    resolved = dashboard._resolve_dir("flowline-backend-engineer-abc123")
    assert resolved == tmp_path / "flowline-backend-engineer-abc123"


# --------------------------------------------------------------------------- #
# Route tests via a standalone app
# --------------------------------------------------------------------------- #

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "test-token")
    monkeypatch.setattr(dashboard, "OUTPUT_DIR", tmp_path)
    app = FastAPI()
    app.include_router(dashboard.router)
    return TestClient(app)


def test_applications_join_sets_tailored_resume_id(client, monkeypatch, tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))

    def fake_fetch():
        return [
            Application(company="Flowline", role="Backend Engineer", job_url="u1"),
            Application(company="Nowhere", role="Ghost", job_url="u2"),
        ]

    monkeypatch.setattr(sheets, "fetch_applications", fake_fetch)
    resp = client.get("/api/applications", headers=AUTH)
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["tailored_resume_id"] == "flowline-backend-engineer-abc123"
    assert rows[1]["tailored_resume_id"] is None


def test_applications_returns_502_on_sheets_error(client, monkeypatch):
    def boom():
        raise SheetsError("upstream unavailable")

    monkeypatch.setattr(sheets, "fetch_applications", boom)
    resp = client.get("/api/applications", headers=AUTH)
    assert resp.status_code == 502


def test_applications_requires_auth(client, monkeypatch):
    monkeypatch.setattr(sheets, "fetch_applications", lambda: [])
    resp = client.get("/api/applications")  # no auth header
    assert resp.status_code == 401


def test_get_tailored_reads_meta(client, tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00", job_url="https://j"))
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["company"] == "Flowline"
    assert body["role"] == "Backend Engineer"
    assert body["job_url"] == "https://j"
    assert body["jd_text"] == "jd text"
    assert body["manifest"]["job_selections"][0]["job_id"] == "ommuse"


def test_get_tailored_404_when_missing(client):
    resp = client.get("/api/tailored/nonexistent-dir", headers=AUTH)
    assert resp.status_code == 404


def test_get_tailored_requires_auth(client):
    resp = client.get("/api/tailored/whatever")
    assert resp.status_code == 401


def test_get_tailored_pdf_streams(client, tmp_path):
    d = _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                    _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    (d / "resume.pdf").write_bytes(b"%PDF-1.4 fake pdf")
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123/pdf", headers=AUTH)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 fake pdf"


def test_get_tailored_pdf_404_when_missing(client, tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    # dir + meta exist, but resume.pdf does not
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123/pdf", headers=AUTH)
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_id", ["..", "%2e%2e", "..%2f.."])
def test_get_tailored_rejects_traversal_via_route(client, bad_id):
    resp = client.get(f"/api/tailored/{bad_id}", headers=AUTH)
    assert resp.status_code in (400, 404)  # never serves outside OUTPUT_DIR


def test_resume_bank_exposes_text_not_contact(client):
    resp = client.get("/api/resume-bank", headers=AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"jobs", "projects", "achievements"}
    assert "contact" not in body
    assert "education" not in body
    assert body["jobs"], "expected at least one job from the real bank"
    for job in body["jobs"]:
        assert set(job.keys()) == {"id", "company", "title", "bullets"}
        for b in job["bullets"]:
            assert set(b.keys()) == {"id", "text"}
    for proj in body["projects"]:
        assert set(proj.keys()) == {"id", "name", "bullets"}
    for ach in body["achievements"]:
        assert set(ach.keys()) == {"id", "text"}


def test_resume_bank_requires_auth(client):
    resp = client.get("/api/resume-bank")
    assert resp.status_code == 401
