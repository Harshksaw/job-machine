import shutil
from pathlib import Path
import pytest
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.render_tex import render_tex
from app.render import compile_pdf, count_pages, trim_one_item, render_and_fit
from app.errors import PdfCompileError, CannotFitOnePageError

pytestmark = pytest.mark.skipif(shutil.which("pdflatex") is None, reason="pdflatex not on PATH")

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
CLS_PATH = TEMPLATE_DIR / "resume.cls"


def _manifest():
    return Manifest(
        summary="Backend engineer, 500 widgets/hour.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_compile_pdf_produces_a_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    pdf_path = compile_pdf(tex, tmp_path, CLS_PATH)
    assert pdf_path.exists()
    assert pdf_path.suffix == ".pdf"


def test_compile_pdf_raises_on_broken_tex(tmp_path):
    with pytest.raises(PdfCompileError):
        compile_pdf(r"\documentclass{resume}\begin{document}\badcommand\end{document}", tmp_path, CLS_PATH)


def test_count_pages_on_real_compiled_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    pdf_path = compile_pdf(tex, tmp_path, CLS_PATH)
    assert count_pages(pdf_path) == 1


def test_trim_one_item_drops_last_project_first():
    m = _manifest()
    m.project_selections.append(
        ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
    )
    trimmed = trim_one_item(m)
    assert len(trimmed.project_selections) == 1


def test_trim_one_item_then_drops_achievement():
    m = _manifest()
    m.project_selections = []
    trimmed = trim_one_item(m)
    assert trimmed.achievement_ids == []


def test_trim_one_item_then_drops_lowest_priority_job_bullet():
    m = _manifest()
    m.project_selections = []
    m.achievement_ids = []
    m.job_selections = [JobSelection(job_id="acme", bullet_ids=["acme.bullet.1", "acme.bullet.2"])]
    trimmed = trim_one_item(m)
    assert trimmed.job_selections[0].bullet_ids == ["acme.bullet.1"]


def test_trim_one_item_drops_bullet_from_lowest_priority_job_when_multiple_jobs_have_extra_bullets():
    # trim_one_item is pure Manifest manipulation and never consults the resume bank,
    # so the two job ids here don't need to exist in tests/fixtures/sample_bank.yaml.
    m = _manifest()
    m.project_selections = []
    m.achievement_ids = []
    m.job_selections = [
        JobSelection(job_id="job_a", bullet_ids=["job_a.bullet.1", "job_a.bullet.2"]),
        JobSelection(job_id="job_b", bullet_ids=["job_b.bullet.1", "job_b.bullet.2"]),
    ]
    m.job_trim_priority = ["job_b", "job_a"]
    trimmed = trim_one_item(m)
    by_job = {js.job_id: js.bullet_ids for js in trimmed.job_selections}
    assert by_job["job_b"] == ["job_b.bullet.1"]
    assert by_job["job_a"] == ["job_a.bullet.1", "job_a.bullet.2"]


def test_trim_one_item_drops_lowest_priority_skill_above_minimum():
    manifest = _manifest()
    manifest.project_selections = []
    manifest.achievement_ids = []
    manifest.skill_ids = ["skill.1", "skill.2", "skill.3", "skill.4"]
    trimmed = trim_one_item(manifest)
    assert trimmed is not None
    assert trimmed.skill_ids == ["skill.1", "skill.2", "skill.3"]


def test_trim_one_item_returns_none_when_nothing_left():
    m = _manifest()
    m.project_selections = []
    m.achievement_ids = []
    m.job_selections = [JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])]
    assert trim_one_item(m) is None


def test_render_and_fit_returns_one_page_pdf(tmp_path):
    bank = load_bank(FIXTURE)
    pdf_path, final_manifest, pages = render_and_fit(_manifest(), bank, TEMPLATE_DIR, CLS_PATH, tmp_path)
    assert pages == 1
    assert pdf_path.exists()


def test_render_and_fit_raises_when_it_cannot_fit(tmp_path, monkeypatch):
    bank = load_bank(FIXTURE)
    monkeypatch.setattr("app.render.count_pages", lambda _pdf_path: 2)
    with pytest.raises(CannotFitOnePageError):
        render_and_fit(_manifest(), bank, TEMPLATE_DIR, CLS_PATH, tmp_path, max_trim_attempts=1)
