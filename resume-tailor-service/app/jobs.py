"""Canonical job-dossier API for the single-user local workspace."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app import application_kit, job_store, sheets
from app.bank import load_bank
from app.dashboard import index_tailored
from app.errors import ClaudeCliError, JobGenerationError, SheetsError
from app.models import (
    Application,
    ApplicationAnswerInput,
    GenerateAnswerRequest,
    JobActivityInput,
    JobCaptureInput,
    JobSummary,
    TailoredResumeMeta,
    JobWorkspace,
    JobWorkspaceInput,
    SheetImportResult,
)
from app.slug import safe_slug

BASE_DIR = Path(__file__).resolve().parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
OUTPUT_DIR = BASE_DIR / "output"

_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

router = APIRouter()


def _validate_id(value: str, label: str = "job") -> None:
    if ".." in value or not _ID_RE.match(value):
        raise HTTPException(status_code=400, detail=f"invalid {label} id")


def _get_job_or_404(job_id: str) -> JobWorkspace:
    _validate_id(job_id)
    job = job_store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return job


def _enrich_from_tailored_meta(
    job: JobWorkspace,
    application: Application,
    session: str,
) -> JobWorkspace:
    resume_id = application.tailored_resume_id
    if not resume_id or job.jd_text.strip():
        return job
    meta_path = OUTPUT_DIR / resume_id / "meta.json"
    try:
        meta = TailoredResumeMeta.model_validate_json(
            meta_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return job
    enriched, _ = job_store.capture_job(
        JobCaptureInput(
            company=job.company,
            role=job.role,
            job_url=job.job_url or meta.job_url or "",
            jd_text=meta.jd_text,
            session=session,
        )
    )
    return enriched


@router.get("/api/jobs", response_model=list[JobSummary])
def list_jobs(
    q: str | None = None,
    status: str | None = None,
) -> list[JobSummary]:
    jobs = job_store.list_summaries()
    if q and q.strip():
        query = q.strip().lower()
        jobs = [
            job
            for job in jobs
            if query in job.company.lower()
            or query in job.role.lower()
            or query in job.source.lower()
            or query in job.location.lower()
            or query in job.next_action.lower()
        ]
    if status and status.strip():
        jobs = [job for job in jobs if job.status == status.strip().lower()]
    return jobs


@router.post("/api/jobs", response_model=JobWorkspace, status_code=201)
def create_job(
    data: JobWorkspaceInput,
    session: str = Query(default=""),
) -> JobWorkspace:
    return job_store.add_job(data, session=session)


@router.post(
    "/api/jobs/from-application",
    response_model=JobWorkspace,
)
def create_from_application(
    application: Application,
    session: str = Query(default="Pipeline"),
) -> JobWorkspace:
    job, _ = job_store.upsert_application(application, session=session)
    return _enrich_from_tailored_meta(job, application, session)


@router.post("/api/jobs/capture", response_model=JobWorkspace)
def capture_job(data: JobCaptureInput) -> JobWorkspace:
    job, _ = job_store.capture_job(data)
    return job


@router.post("/api/jobs/import-sheet", response_model=SheetImportResult)
def import_sheet(
    session: str = Query(default="Sheet import"),
) -> SheetImportResult:
    try:
        applications = sheets.fetch_applications()
    except SheetsError:
        raise HTTPException(
            status_code=502,
            detail="failed to load applications from the sheet",
        )

    resume_index = index_tailored(OUTPUT_DIR)
    created_ids: set[str] = set()
    updated_ids: set[str] = set()
    all_ids: list[str] = []
    for application in sorted(applications, key=lambda row: row.timestamp):
        application.tailored_resume_id = resume_index.get(
            safe_slug(application.company, application.role)
        )
        before = job_store.find_matching_job(
            application.company,
            application.role,
            application.job_url,
        )
        job, created = job_store.upsert_application(application, session=session)
        job = _enrich_from_tailored_meta(job, application, session)
        all_ids.append(job.id)
        if created:
            created_ids.add(job.id)
        elif (
            job.id not in created_ids
            and before is not None
            and before.updated_at != job.updated_at
        ):
            updated_ids.add(job.id)
    return SheetImportResult(
        imported_rows=len(applications),
        created_jobs=len(created_ids),
        updated_jobs=len(updated_ids),
        job_ids=list(dict.fromkeys(all_ids)),
    )


@router.get("/api/jobs/{job_id}", response_model=JobWorkspace)
def get_job(job_id: str) -> JobWorkspace:
    return _get_job_or_404(job_id)


@router.put("/api/jobs/{job_id}", response_model=JobWorkspace)
def replace_job(
    job_id: str,
    data: JobWorkspaceInput,
    session: str = Query(default=""),
) -> JobWorkspace:
    _get_job_or_404(job_id)
    updated = job_store.update_job(job_id, data, session=session)
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated


@router.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    _validate_id(job_id)
    if not job_store.delete_job(job_id):
        raise HTTPException(status_code=404, detail="job dossier not found")


@router.post("/api/jobs/{job_id}/activity", response_model=JobWorkspace)
def add_activity(job_id: str, data: JobActivityInput) -> JobWorkspace:
    _get_job_or_404(job_id)
    updated = job_store.add_activity(job_id, data)
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated


@router.post(
    "/api/jobs/{job_id}/restore/{revision_id}",
    response_model=JobWorkspace,
)
def restore_revision(
    job_id: str,
    revision_id: str,
    session: str = Query(default=""),
) -> JobWorkspace:
    job = _get_job_or_404(job_id)
    _validate_id(revision_id, "revision")
    if not any(revision.id == revision_id for revision in job.revisions):
        raise HTTPException(status_code=404, detail="job revision not found")
    restored = job_store.restore_revision(job_id, revision_id, session=session)
    if restored is None:
        raise HTTPException(status_code=404, detail="job revision not found")
    return restored


@router.post("/api/jobs/{job_id}/generate-kit", response_model=JobWorkspace)
def generate_kit(
    job_id: str,
    session: str = Query(default=""),
) -> JobWorkspace:
    job = _get_job_or_404(job_id)
    bank = load_bank(BANK_PATH)
    try:
        kit = application_kit.generate_kit(job, bank)
    except JobGenerationError as exc:
        status_code = 422 if "job description" in str(exc).lower() else 502
        raise HTTPException(status_code=status_code, detail=str(exc))
    except ClaudeCliError as exc:
        raise HTTPException(status_code=502, detail=f"generation service failed: {exc}")
    updated = job_store.apply_generated_kit(job_id, kit, session=session)
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated


@router.post("/api/jobs/{job_id}/answers", response_model=JobWorkspace)
def add_answer(
    job_id: str,
    data: ApplicationAnswerInput,
    session: str = Query(default=""),
) -> JobWorkspace:
    _get_job_or_404(job_id)
    updated = job_store.add_answer(job_id, data, session=session)
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated


@router.post(
    "/api/jobs/{job_id}/answers/generate",
    response_model=JobWorkspace,
)
def generate_answer(
    job_id: str,
    request: GenerateAnswerRequest,
) -> JobWorkspace:
    job = _get_job_or_404(job_id)
    bank = load_bank(BANK_PATH)
    try:
        generated = application_kit.generate_answer(
            job,
            bank,
            request.question,
            request.constraints,
        )
    except JobGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except ClaudeCliError as exc:
        raise HTTPException(status_code=502, detail=f"generation service failed: {exc}")
    updated = job_store.add_answer(
        job_id,
        ApplicationAnswerInput(
            question=request.question,
            answer=generated.answer,
            constraints=request.constraints,
            source_ids=generated.source_ids,
            needs_user_input=generated.needs_user_input,
            clarification=generated.clarification,
        ),
        session=request.session,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated


@router.put(
    "/api/jobs/{job_id}/answers/{answer_id}",
    response_model=JobWorkspace,
)
def replace_answer(
    job_id: str,
    answer_id: str,
    data: ApplicationAnswerInput,
    session: str = Query(default=""),
) -> JobWorkspace:
    _get_job_or_404(job_id)
    _validate_id(answer_id, "answer")
    updated = job_store.replace_answer(job_id, answer_id, data, session=session)
    if updated is None:
        raise HTTPException(status_code=404, detail="application answer not found")
    return updated


@router.delete(
    "/api/jobs/{job_id}/answers/{answer_id}",
    status_code=204,
)
def delete_answer(
    job_id: str,
    answer_id: str,
    session: str = Query(default=""),
) -> None:
    _get_job_or_404(job_id)
    _validate_id(answer_id, "answer")
    if job_store.delete_answer(job_id, answer_id, session=session) is None:
        raise HTTPException(status_code=404, detail="application answer not found")
