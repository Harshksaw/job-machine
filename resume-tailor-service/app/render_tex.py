from pathlib import Path
import jinja2
from app.bank import ResumeBank
from app.models import Manifest

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_SPECIAL.get(ch, ch) for ch in text)


def _build_context(manifest: Manifest, bank: ResumeBank) -> dict:
    job_sel_by_id = {js.job_id: js for js in manifest.job_selections}
    jobs_ctx = []
    for job in bank.jobs:
        sel = job_sel_by_id.get(job.id)
        if sel is None:
            continue
        bullet_text = {b.id: b.text for b in job.bullets}
        jobs_ctx.append({
            "company": job.company,
            "location": job.location,
            "title": job.title,
            "dates": job.dates,
            "bullets": [bullet_text[bid] for bid in sel.bullet_ids],
        })

    project_by_id = {p.id: p for p in bank.projects}
    projects_ctx = []
    for ps in manifest.project_selections:
        proj = project_by_id[ps.project_id]
        bullet_text = {b.id: b.text for b in proj.bullets}
        projects_ctx.append({
            "name": proj.name,
            "tech": proj.tech,
            "bullets": [bullet_text[bid] for bid in ps.bullet_ids],
        })

    achievement_text = {b.id: b.text for b in bank.achievements}
    achievements_ctx = [achievement_text[aid] for aid in manifest.achievement_ids]

    return {
        "contact": bank.contact.model_dump(),
        "education": bank.education.model_dump(),
        "summary": latex_escape(manifest.summary),
        "jobs": jobs_ctx,
        "projects": projects_ctx,
        "achievements": achievements_ctx,
        "skills": [s.model_dump() for s in bank.skills],
    }


def render_tex(manifest: Manifest, bank: ResumeBank, template_dir: Path) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((#",
        comment_end_string="#))",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    template = env.get_template("resume_template.tex.jinja")
    return template.render(**_build_context(manifest, bank))
