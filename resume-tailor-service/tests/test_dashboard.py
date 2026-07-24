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
    resp = client.get("/api/applications")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows[0]["tailored_resume_id"] == "flowline-backend-engineer-abc123"
    assert rows[1]["tailored_resume_id"] is None


def test_applications_returns_502_on_sheets_error(client, monkeypatch):
    def boom():
        raise SheetsError("upstream unavailable")

    monkeypatch.setattr(sheets, "fetch_applications", boom)
    resp = client.get("/api/applications")
    assert resp.status_code == 502


def test_get_tailored_reads_meta(client, tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00", job_url="https://j"))
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company"] == "Flowline"
    assert body["role"] == "Backend Engineer"
    assert body["job_url"] == "https://j"
    assert body["jd_text"] == "jd text"
    assert body["manifest"]["job_selections"][0]["job_id"] == "ommuse"
    # server-absolute pdf_path is excluded from this response (internal path)
    assert "pdf_path" not in body


def test_get_tailored_404_when_missing(client):
    resp = client.get("/api/tailored/nonexistent-dir")
    assert resp.status_code == 404


def test_get_tailored_pdf_streams(client, tmp_path):
    d = _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                    _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    (d / "resume.pdf").write_bytes(b"%PDF-1.4 fake pdf")
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123/pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4 fake pdf"


def test_get_tailored_pdf_404_when_missing(client, tmp_path):
    _write_meta(tmp_path, "flowline-backend-engineer-abc123",
                _meta("Flowline", "Backend Engineer", "2026-01-01T00:00:00+00:00"))
    # dir + meta exist, but resume.pdf does not
    resp = client.get("/api/tailored/flowline-backend-engineer-abc123/pdf")
    assert resp.status_code == 404


@pytest.mark.parametrize("bad_id", ["..", "%2e%2e", "..%2f.."])
def test_get_tailored_rejects_traversal_via_route(client, bad_id):
    resp = client.get(f"/api/tailored/{bad_id}")
    assert resp.status_code in (400, 404)  # never serves outside OUTPUT_DIR


def test_get_tailored_pdf_cannot_escape_output_dir(client, tmp_path):
    """Stage a real secret file OUTSIDE OUTPUT_DIR (a sibling of tmp_path) and
    confirm crafted traversal ids can neither reach it nor leak its content.

    Two layers are in play, and this test distinguishes them (verified
    empirically — see task-6-report.md "traversal test fix" section):

    1. Routing layer: a literal ".." path segment is collapsed/rejected by
       Starlette/httpx URL handling BEFORE the view function ever runs, so
       it never reaches `_resolve_dir` — a 404, not proof the guard works.
    2. The guard itself (`app.dashboard._resolve_dir`): ids that are
       URL-encoded so they arrive as a single `{resume_id}` path segment
       (e.g. "%2e%2e") reach the view and are rejected there with a real
       400 ("invalid tailored resume id"). These are the cases that
       actually exercise the guard.

    Percent-encoded ids containing an encoded slash (e.g. "..%2f<name>")
    were tried and do NOT reach the guard either in this stack — the
    decoded "/" splits the URL into extra segments that don't match the
    single-segment route, so those also 404 at the routing layer. They are
    therefore excluded from the "proves the guard" set below.
    """
    outside_dir = tmp_path.parent / f"outside-secret-{tmp_path.name}"
    outside_dir.mkdir(exist_ok=True)
    secret_bytes = b"%PDF-1.4 SECRET-OUTSIDE-OUTPUT-DIR"
    (outside_dir / "resume.pdf").write_bytes(secret_bytes)
    try:
        # Guard-reaching cases: single path segment, decode to a string
        # containing ".." -> `_resolve_dir` itself rejects with 400.
        guard_reaching_ids = ("%2e%2e", f"%2e%2e{outside_dir.name}")
        for bad_id in guard_reaching_ids:
            resp = client.get(f"/api/tailored/{bad_id}/pdf")
            assert resp.status_code == 400
            assert resp.json()["detail"] == "invalid tailored resume id"
            assert resp.content != secret_bytes

        # Defense-in-depth (routing layer, NOT the guard): a literal ".."
        # segment is blocked before `_resolve_dir` runs at all.
        resp = client.get("/api/tailored/../pdf")
        assert resp.status_code == 404
        assert resp.content != secret_bytes
    finally:
        (outside_dir / "resume.pdf").unlink(missing_ok=True)
        outside_dir.rmdir()


def test_resume_bank_exposes_text_not_contact(client):
    resp = client.get("/api/resume-bank")
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


def test_get_applications_with_filters(client, monkeypatch):
    test_apps = [
        Application(
            company="Acme Corp",
            role="Backend Engineer",
            source="LinkedIn",
            job_url="https://acme.com",
            status="applied",
            fit="9",
            people="",
            hooks="",
            outreach="",
            notes="Great fit for Go and Python",
            timestamp="2026-07-20",
        ),
        Application(
            company="Beta AI",
            role="Full Stack Engineer",
            source="Wellfound",
            job_url="https://beta.ai",
            status="interview",
            fit="7",
            people="",
            hooks="",
            outreach="",
            notes="React and Node.js position",
            timestamp="2026-07-21",
        ),
    ]
    monkeypatch.setattr(sheets, "fetch_applications", lambda: test_apps)

    # Search filter 'Acme'
    resp = client.get("/api/applications?q=Acme")
    assert resp.status_code == 200
    res = resp.json()
    assert len(res) == 1
    assert res[0]["company"] == "Acme Corp"

    # Status filter 'interview'
    resp = client.get("/api/applications?status=interview")
    assert resp.status_code == 200
    res = resp.json()
    assert len(res) == 1
    assert res[0]["company"] == "Beta AI"

    # Min fit filter 8.0
    resp = client.get("/api/applications?min_fit=8.0")
    assert resp.status_code == 200
    res = resp.json()
    assert len(res) == 1
    assert res[0]["company"] == "Acme Corp"

