"""Read-only dashboard API.

Mounting this router (and StaticFiles) is a later task — `main.py` is left
untouched here. Tests build their own ``FastAPI()`` and ``include_router`` it.

The join key between a sheet row and a tailored resume is
``safe_slug(company, role)``; when several output dirs share a key the most
recent ``created_at`` wins. ``index_tailored`` is a pure function so it can be
unit-tested against a temp dir. ``OUTPUT_DIR`` and the ``sheets`` module are
referenced at module level so tests can monkeypatch them.
"""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app import sheets
from app.auth import verify_token
from app.bank import load_bank
from app.errors import SheetsError
from app.models import Application, TailoredResumeMeta
from app.slug import safe_slug

BASE_DIR = Path(__file__).resolve().parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
OUTPUT_DIR = BASE_DIR / "output"

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

router = APIRouter(dependencies=[Depends(verify_token)])


def index_tailored(output_dir: Path) -> dict[str, str]:
    """Map ``safe_slug(company, role)`` -> output dir name for every dir under
    ``output_dir`` holding a readable ``meta.json``. Most recent ``created_at``
    wins on collisions. Dirs without/with corrupt ``meta.json`` are skipped.
    """
    best: dict[str, tuple[str, str]] = {}  # key -> (dir_name, created_at)
    if not output_dir.is_dir():
        return {}

    for child in sorted(output_dir.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = TailoredResumeMeta.model_validate_json(
                meta_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            continue  # missing/corrupt/invalid meta.json -> skip, never crash

        key = safe_slug(meta.company, meta.role)
        current = best.get(key)
        if current is None or meta.created_at > current[1]:
            best[key] = (child.name, meta.created_at)

    return {key: dir_name for key, (dir_name, _) in best.items()}


def _resolve_dir(resume_id: str) -> Path:
    """Validate ``resume_id`` and return its dir inside OUTPUT_DIR (400 if not).

    Rejects anything that isn't a single ``[A-Za-z0-9._-]+`` segment or that
    contains ``..``, then confirms the resolved path stays directly under
    OUTPUT_DIR.
    """
    if ".." in resume_id or not _ID_RE.match(resume_id):
        raise HTTPException(status_code=400, detail="invalid tailored resume id")
    base = OUTPUT_DIR.resolve()
    candidate = (base / resume_id).resolve()
    if candidate.parent != base:
        raise HTTPException(status_code=400, detail="invalid tailored resume id")
    return candidate


@router.get("/api/applications", response_model=list[Application])
def get_applications() -> list[Application]:
    try:
        applications = sheets.fetch_applications()
    except SheetsError:
        # Clean, fixed message — never echo the SheetsError (defense in depth).
        raise HTTPException(status_code=502, detail="failed to load applications from the sheet")

    index = index_tailored(OUTPUT_DIR)
    for application in applications:
        key = safe_slug(application.company, application.role)
        application.tailored_resume_id = index.get(key)
    return applications


@router.get("/api/tailored/{resume_id}", response_model=TailoredResumeMeta)
def get_tailored(resume_id: str) -> TailoredResumeMeta:
    meta_path = _resolve_dir(resume_id) / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="tailored resume not found")
    try:
        return TailoredResumeMeta.model_validate_json(
            meta_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="tailored resume not found")


@router.get("/api/tailored/{resume_id}/pdf")
def get_tailored_pdf(resume_id: str) -> FileResponse:
    pdf_path = _resolve_dir(resume_id) / "resume.pdf"
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="tailored resume pdf not found")
    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/api/resume-bank")
def get_resume_bank() -> dict:
    """Bank jobs/projects/achievements as id+text so the UI can resolve manifest
    IDs. Deliberately excludes contact and education.
    """
    bank = load_bank(BANK_PATH)
    return {
        "jobs": [
            {
                "id": job.id,
                "company": job.company,
                "title": job.title,
                "bullets": [{"id": b.id, "text": b.text} for b in job.bullets],
            }
            for job in bank.jobs
        ],
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "bullets": [{"id": b.id, "text": b.text} for b in project.bullets],
            }
            for project in bank.projects
        ],
        "achievements": [{"id": b.id, "text": b.text} for b in bank.achievements],
    }
