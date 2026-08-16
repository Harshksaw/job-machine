import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import app.main as main_module
from app.slug import safe_slug
from app.models import (
    JobSelection,
    JobWorkspaceInput,
    Manifest,
    ProjectSelection,
    TailoredResumeMeta,
)
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError, ClaudeCliError


def _fake_manifest():
    return Manifest(
        summary="Backend engineer.",
        job_selections=[JobSelection(job_id="ommuse", bullet_ids=["ommuse.bullet.1"])],
        project_selections=[ProjectSelection(project_id="docintel", bullet_ids=["project.docintel.bullet.1"])],
        achievement_ids=["achievement.lms"],
        job_trim_priority=["okanagan", "ommuse", "bwisher", "jythu"],
    )


def test_health_requires_no_auth():
    client = TestClient(main_module.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tailor_success_returns_pdf_path_and_manifest(monkeypatch, tmp_path):
    fake_pdf = tmp_path / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    monkeypatch.setattr(main_module.tailor, "get_manifest", lambda *a, **k: _fake_manifest())
    monkeypatch.setattr(main_module.render, "render_and_fit", lambda *a, **k: (fake_pdf, _fake_manifest(), 1))

    client = TestClient(main_module.app)
    resp = client.post(
        "/tailor",
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


def test_tailor_links_context_and_artifact_to_dossier(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module.job_store, "STORE_PATH", tmp_path / "jobs.json")
    job = main_module.job_store.add_job(
        JobWorkspaceInput(company="Acme", role="SWE")
    )
    artifact_dir = tmp_path / "acme-swe-artifact"
    artifact_dir.mkdir()
    fake_pdf = artifact_dir / "resume.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(
        main_module.tailor,
        "get_manifest",
        lambda *args, **kwargs: _fake_manifest(),
    )
    monkeypatch.setattr(
        main_module.render,
        "render_and_fit",
        lambda *args, **kwargs: (fake_pdf, _fake_manifest(), 1),
    )

    response = TestClient(main_module.app).post(
        "/tailor",
        json={
            "jd_text": "Complete backend role description.",
            "company": "Acme",
            "role": "SWE",
            "job_url": "https://example.com/job",
            "job_id": job.id,
            "session": "LinkedIn 2026-07-23",
        },
    )
    assert response.status_code == 200
    assert response.json()["resume_id"] == "acme-swe-artifact"
    linked = main_module.job_store.get_job(job.id)
    assert linked is not None
    assert linked.jd_text == "Complete backend role description."
    assert linked.job_url == "https://example.com/job"
    assert linked.tailored_resume_id == "acme-swe-artifact"


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
        json={"jd_text": "x", "company": "Acme", "role": "SWE"},
    )
    assert resp.status_code == 500


def test_dashboard_router_is_mounted():
    """GET /api/applications must resolve to the router (not 404). With no
    sheet configured it fails as a 502, which still proves it is mounted."""
    from fastapi.testclient import TestClient
    from app.main import app
    resp = TestClient(app).get("/api/applications")
    assert resp.status_code != 404


def test_static_index_served_at_root():
    client = TestClient(main_module.app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_static_asset_served():
    """A real hashed build asset under app/static/assets/ is served as-is.

    This proves StaticFiles is actually serving files (not just falling back
    to index.html for every path) — the filename hash is discovered via glob
    at test time so it never goes stale when the frontend is rebuilt.
    """
    assets_dir = Path(__file__).resolve().parent.parent / "app" / "static" / "assets"
    if not assets_dir.is_dir():
        pytest.skip("app/static/assets not present (dashboard not built in this environment)")

    asset_files = [p for p in assets_dir.glob("*.js") if p.is_file()]
    if not asset_files:
        pytest.skip("no built .js assets found under app/static/assets")

    asset_path = asset_files[0]
    client = TestClient(main_module.app)
    resp = client.get(f"/assets/{asset_path.name}")
    assert resp.status_code == 200
    assert resp.content == asset_path.read_bytes()
    # A real asset response must not be the index.html SPA fallback.
    assert "text/html" not in resp.headers["content-type"]


def test_safe_slug_strips_path_traversal():
    traversal_slug = safe_slug("../../etc", "x")
    assert "/" not in traversal_slug
    assert ".." not in traversal_slug
    assert traversal_slug

    assert safe_slug("Acme Corp", "Backend Engineer") == "acme-corp-backend-engineer"
    assert safe_slug("..", "..") == "job"
