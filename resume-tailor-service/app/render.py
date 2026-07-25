import shutil
import subprocess
from pathlib import Path
import pypdf
from app.bank import ResumeBank
from app.models import Manifest
from app.render_tex import render_tex
from app.errors import PdfCompileError, CannotFitOnePageError


def compile_pdf(tex_source: str, work_dir: Path, cls_path: Path) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(cls_path, work_dir / "resume.cls")
    tex_file = work_dir / "resume.tex"
    tex_file.write_text(tex_source)

    pdf_path = work_dir / "resume.pdf"
    log_path = work_dir / "resume.log"
    # Remove any stale output from a previous compile attempt in this work_dir so that
    # pdf_path.exists() below is genuine evidence of *this* run's success, not a leftover
    # from an earlier trim iteration that pdflatex failed to overwrite.
    pdf_path.unlink(missing_ok=True)
    log_path.unlink(missing_ok=True)

    timeout = 30
    result = None
    for _ in range(2):  # twice so hyperref cross-references settle
        try:
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_file.name],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise PdfCompileError(f"pdflatex timed out after {timeout}s") from exc
        except OSError as exc:
            raise PdfCompileError(f"failed to run pdflatex: {exc}") from exc

    if not pdf_path.exists():
        tail = log_path.read_text()[-2000:] if log_path.exists() else (result.stdout[-2000:] if result else "")
        raise PdfCompileError(tail)
    return pdf_path


def count_pages(pdf_path: Path) -> int:
    reader = pypdf.PdfReader(str(pdf_path))
    return len(reader.pages)


def trim_one_item(manifest: Manifest) -> Manifest | None:
    m = manifest.model_copy(deep=True)

    if m.project_selections:
        m.project_selections.pop()
        return m

    if m.achievement_ids:
        m.achievement_ids.pop()
        return m

    if len(m.skill_ids) > 3:
        m.skill_ids.pop()
        return m

    for job_id in m.job_trim_priority:
        for js in m.job_selections:
            if js.job_id == job_id and len(js.bullet_ids) > 1:
                js.bullet_ids.pop()
                return m

    return None


def render_and_fit(
    manifest: Manifest,
    bank: ResumeBank,
    template_dir: Path,
    cls_path: Path,
    work_dir: Path,
    max_trim_attempts: int = 6,
) -> tuple[Path, Manifest, int]:
    current = manifest
    for _ in range(max_trim_attempts + 1):
        tex_source = render_tex(current, bank, template_dir)
        pdf_path = compile_pdf(tex_source, work_dir, cls_path)
        pages = count_pages(pdf_path)
        if pages <= 1:
            return pdf_path, current, pages
        trimmed = trim_one_item(current)
        if trimmed is None:
            break
        current = trimmed
    raise CannotFitOnePageError(
        f"could not fit resume to one page after {max_trim_attempts} trim attempts"
    )
