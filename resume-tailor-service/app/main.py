import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from app import dashboard, job_store, jobs, people, render, sessions, tailor
from app.bank import load_bank
from app.models import TailorRequest, TailorResponse, TailoredResumeMeta
from app.slug import safe_slug
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError, ClaudeCliError

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
TEMPLATE_DIR = BASE_DIR / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "app" / "static"

app = FastAPI(title="resume-tailor-service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tailor", response_model=TailorResponse)
def tailor_resume(req: TailorRequest):
    if req.job_id and job_store.get_job(req.job_id) is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    if req.job_id:
        job_store.sync_tailor_context(
            req.job_id,
            req.jd_text,
            req.job_url,
            session=req.session,
        )
    bank = load_bank(BANK_PATH)

    try:
        manifest = tailor.get_manifest(req.jd_text, req.company, req.role, bank)
    except TailorValidationError as e:
        raise HTTPException(status_code=502, detail=f"model produced an invalid manifest: {e}")
    except ClaudeCliError as e:
        raise HTTPException(status_code=502, detail=f"claude CLI invocation failed: {e}")

    slug = safe_slug(req.company, req.role)
    work_dir = OUTPUT_DIR / f"{slug}-{uuid.uuid4().hex[:8]}"

    try:
        pdf_path, final_manifest, pages = render.render_and_fit(
            manifest, bank, TEMPLATE_DIR, CLS_PATH, work_dir
        )
    except PdfCompileError as e:
        raise HTTPException(status_code=500, detail=f"LaTeX compile failed: {e}")
    except CannotFitOnePageError as e:
        raise HTTPException(status_code=422, detail=str(e))

    meta = TailoredResumeMeta(
        company=req.company,
        role=req.role,
        jd_text=req.jd_text,
        pdf_path=str(pdf_path),
        manifest=final_manifest,
        pages=pages,
        created_at=datetime.now(timezone.utc).isoformat(),
        job_url=req.job_url,
    )
    meta_path = Path(pdf_path).parent / "meta.json"
    try:
        meta_path.write_text(json.dumps(meta.model_dump(), indent=2), encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"failed to write resume metadata: {e}")

    resume_id = Path(pdf_path).parent.name
    if req.job_id:
        job_store.attach_resume(req.job_id, resume_id, session=req.session)

    return TailorResponse(
        pdf_path=str(pdf_path),
        manifest=final_manifest,
        pages=pages,
        resume_id=resume_id,
    )


app.include_router(dashboard.router)
app.include_router(people.router)
app.include_router(jobs.router)
app.include_router(sessions.router)

# Serve the built dashboard SPA (see dashboard/README or resume-tailor-service/README
# for the rebuild step). Mounted last so it never shadows the API routes above —
# StaticFiles only handles requests that don't match an already-registered route.
# Guarded so the API still boots if the frontend hasn't been built.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="dashboard")
