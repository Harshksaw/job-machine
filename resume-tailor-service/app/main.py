import re
import uuid
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException

from app import tailor, render
from app.auth import verify_token
from app.bank import load_bank
from app.models import TailorRequest, TailorResponse
from app.errors import TailorValidationError, PdfCompileError, CannotFitOnePageError, ClaudeCliError

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
TEMPLATE_DIR = BASE_DIR / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"
OUTPUT_DIR = BASE_DIR / "output"

app = FastAPI(title="resume-tailor-service")


def _safe_slug(company: str, role: str) -> str:
    raw = f"{company}-{role}".lower().replace(" ", "-")
    cleaned = re.sub(r"[^a-z0-9._-]", "", raw).lstrip(".-")
    return cleaned or "job"


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/tailor", response_model=TailorResponse)
def tailor_resume(req: TailorRequest, _auth: None = Depends(verify_token)):
    bank = load_bank(BANK_PATH)

    try:
        manifest = tailor.get_manifest(req.jd_text, req.company, req.role, bank)
    except TailorValidationError as e:
        raise HTTPException(status_code=502, detail=f"model produced an invalid manifest: {e}")
    except ClaudeCliError as e:
        raise HTTPException(status_code=502, detail=f"claude CLI invocation failed: {e}")

    slug = _safe_slug(req.company, req.role)
    work_dir = OUTPUT_DIR / f"{slug}-{uuid.uuid4().hex[:8]}"

    try:
        pdf_path, final_manifest, pages = render.render_and_fit(
            manifest, bank, TEMPLATE_DIR, CLS_PATH, work_dir
        )
    except PdfCompileError as e:
        raise HTTPException(status_code=500, detail=f"LaTeX compile failed: {e}")
    except CannotFitOnePageError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return TailorResponse(pdf_path=str(pdf_path), manifest=final_manifest, pages=pages)
