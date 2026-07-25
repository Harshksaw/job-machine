"""Real-bank end-to-end integration test.

This is the test that should have caught all three tailoring bugs the unit
suite missed:
  - BUG 1: skills rendered as `<built-in method items of dict object ...>`
    instead of the actual skill values (dict `.items` attribute collision).
  - BUG 2: hand-escaped LaTeX in the bank (`\\&`, `\\%`) was error-prone and
    two bullets (`Q&A`, `70%`) were missed, breaking `pdflatex`.
  - BUG 3: the `claude` CLI model was too slow and timed out.

It builds a full manifest by hand (no `claude` CLI call) referencing every
real id in `content/resume_bank.yaml`, validates it, renders + compiles it
with the real template/class, and inspects both the raw `.tex` and the
compiled PDF text to prove the skills table and LaTeX-special-character
bullets (`&`, `%`) survive a real `pdflatex` compile.
"""
import shutil
from pathlib import Path

import pytest
import pypdf

from app.bank import load_bank
from app.models import JobSelection, Manifest, ProjectSelection
from app.render import render_and_fit
from app.render_tex import render_tex
from app.validate import validate_manifest

pytestmark = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")

BASE_DIR = Path(__file__).parent.parent
BANK_PATH = BASE_DIR / "content" / "resume_bank.yaml"
TEMPLATE_DIR = BASE_DIR / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"


def _full_manifest() -> Manifest:
    return Manifest(
        summary=(
            "Backend engineer building RAG pipelines with AWS and Kafka, "
            "serving 12K+ users and cutting bandwidth by 70%."
        ),
        job_selections=[
            JobSelection(
                job_id="ommuse",
                bullet_ids=[
                    "ommuse.bullet.1",
                    "ommuse.bullet.2",
                    "ommuse.bullet.3",
                    "ommuse.bullet.4",
                ],
            ),
            JobSelection(
                job_id="morethinks",
                bullet_ids=["morethinks.bullet.1", "morethinks.bullet.2"],
            ),
            JobSelection(
                job_id="bwisher",
                bullet_ids=["bwisher.bullet.1", "bwisher.bullet.2", "bwisher.bullet.3"],
            ),
            JobSelection(
                job_id="jythu",
                bullet_ids=["jythu.bullet.1", "jythu.bullet.2"],
            ),
        ],
        project_selections=[
            ProjectSelection(
                project_id="docintel",
                bullet_ids=[
                    "project.docintel.bullet.1",
                    "project.docintel.bullet.2",
                    "project.docintel.bullet.3",
                ],
            ),
            ProjectSelection(
                project_id="codexpo",
                bullet_ids=[
                    "project.codexpo.bullet.1",
                    "project.codexpo.bullet.2",
                    "project.codexpo.bullet.3",
                ],
            ),
        ],
        achievement_ids=[
            "achievement.lms",
            "achievement.stock",
            "achievement.freelancer",
            "achievement.hackathon",
        ],
        skill_ids=[
            "skill.languages",
            "skill.frontend_mobile",
            "skill.backend_messaging",
            "skill.databases",
            "skill.cloud_devops",
            "skill.ai_genai",
        ],
        job_trim_priority=["ommuse", "morethinks", "bwisher", "jythu"],
    )


def test_full_real_bank_manifest_has_no_validation_errors():
    bank = load_bank(BANK_PATH)
    errors = validate_manifest(_full_manifest(), bank)
    assert errors == []


def test_full_real_bank_manifest_renders_and_fits_one_page(tmp_path):
    bank = load_bank(BANK_PATH)
    manifest = _full_manifest()
    assert validate_manifest(manifest, bank) == []

    pdf_path, final_manifest, pages = render_and_fit(
        manifest, bank, TEMPLATE_DIR, CLS_PATH, tmp_path
    )
    assert pages == 1

    # BUG 1 regression: the skills table must render actual values, never a
    # leaked dict method repr.
    tex = render_tex(final_manifest, bank, TEMPLATE_DIR)
    assert "built-in method" not in tex
    assert "PostgreSQL" in tex
    assert "Kubernetes" in tex

    # BUG 2 regression: extract text from the compiled PDF and confirm real
    # skill values and LaTeX-special-character bullets survived a genuine
    # pdflatex compile (this only works if `&`/`%` were escaped correctly).
    reader = pypdf.PdfReader(str(pdf_path))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert "PostgreSQL" in pdf_text
    assert "LangChain" in pdf_text
    assert "sync.Map" in pdf_text  # known bullet fragment (ommuse.bullet.2)
    assert "Q&A" in pdf_text  # docintel project bullet -- proves & escaping compiled
    assert "70%" in pdf_text  # jythu bullet -- proves % escaping compiled
