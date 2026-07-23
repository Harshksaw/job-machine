import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app.main as main_module
from app.slug import safe_slug
from app.models import Manifest, JobSelection, ProjectSelection, TailoredResumeMeta
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError, ClaudeCliError


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

    meta_path = Path(body["pdf_path"]).parent / "meta.json"
    assert meta_path.exists()
    meta = TailoredResumeMeta.model_validate(json.loads(meta_path.read_text(encoding="utf-8")))
    assert meta.company == "Acme"
    assert meta.role == "SWE"
    assert meta.jd_text == "We need a backend engineer."
    assert meta.pdf_path == body["pdf_path"]
    assert meta.manifest.model_dump() == body["manifest"]
    assert meta.pages == body["pages"]
    assert meta.job_url is None
    assert meta.created_at


def test_tailor_returns_500_when_meta_write_fails(monkeypatch, tmp_path):
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())
    monkeypatch.setattr(main_module.render, "render_and_fit", lambda *a, **k: (fake_pdf, _fake_manifest(), 1))

    def _raise(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "We need a backend engineer.", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 500


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


def test_tailor_returns_502_on_claude_cli_error(monkeypatch):
    def _raise(*a, **k):
        raise ClaudeCliError("claude CLI not found on PATH")
    monkeypatch.setattr(main_module.tailor, "get_manifest", _raise)

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
        headers={"Authorization": "Bearer test-token"},
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 502


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


def test_dashboard_router_is_mounted_and_requires_auth():
    """GET /api/applications with no Authorization header must be 401, not 404.

    A 404 here would mean either the dashboard router isn't included on `app`,
    or the static SPA mount is shadowing /api/* routes.
    """
    client = TestClient(main_module.app)
    resp = client.get("/api/applications")
    assert resp.status_code == 401


def test_static_index_served_at_root():
    client = TestClient(main_module.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_safe_slug_strips_path_traversal():
    traversal_slug = safe_slug("../../etc", "x")
    assert "/" not in traversal_slug
    assert ".." not in traversal_slug
    assert traversal_slug

    assert safe_slug("Acme Corp", "Backend Engineer") == "acme-corp-backend-engineer"
    assert safe_slug("..", "..") == "job"
