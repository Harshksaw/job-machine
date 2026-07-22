from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app.main as main_module
from app.models import Manifest, JobSelection, ProjectSelection
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError


def _fake_manifest():
    return Manifest(
        summary="Backend engineer.",
        job_selections=[JobSelection(job_id="ommuse", bullet_ids=["ommuse.bullet.1"])],
        project_selections=[ProjectSelection(project_id="docintel", bullet_ids=["project.docintel.bullet.1"])],
        achievement_ids=["achievement.lms"],
        job_trim_priority=["ommuse", "morethinks", "bwisher", "jythu"],
    )


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setenv("RESUME_TAILOR_TOKEN", "test-token")


def test_health_requires_no_auth():
    client = TestClient(main_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tailor_rejects_missing_token():
    client = TestClient(main_module.app)
    resp = client.post("/tailor", json={"jd_text": "x", "company": "Acme", "role": "SWE"})
    assert resp.status_code == 401


def test_tailor_success_returns_pdf_path_and_manifest(monkeypatch, tmp_path):
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())
    monkeypatch.setattr(main_module.render, "render_and_fit", lambda *a, **k: (fake_pdf, _fake_manifest(), 1))

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "We need a backend engineer.", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pages"] == 1
    assert body["pdf_path"] == str(fake_pdf)
    assert body["manifest"]["job_selections"][0]["job_id"] == "ommuse"


def test_tailor_returns_502_on_validation_failure(monkeypatch):
    def _raise(*a, **k):
        raise TailorValidationError("bad manifest")
    monkeypatch.setattr(main_module.tailor, "get_manifest", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 502


def test_tailor_returns_422_when_cannot_fit_one_page(monkeypatch):
    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())

    def _raise(*a, **k):
        raise CannotFitOnePageError("nope")
    monkeypatch.setattr(main_module.render, "render_and_fit", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 422


def test_tailor_returns_500_on_compile_failure(monkeypatch):
    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())

    def _raise(*a, **k):
        raise PdfCompileError("log tail")
    monkeypatch.setattr(main_module.render, "render_and_fit", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 500
