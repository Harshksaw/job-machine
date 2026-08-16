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
            "company": latex_escape(job.company),
            "location": latex_escape(job.location),
            "title": latex_escape(job.title),
            "dates": latex_escape(job.dates),
            # Raw, like contact.email and the profile urls: it goes inside
            # \href{} where escaping would corrupt the target.
            "url": job.url,
            "bullets": [latex_escape(bullet_text[bid]) for bid in sel.bullet_ids],
        })

    project_by_id = {p.id: p for p in bank.projects}
    projects_ctx = []
    for ps in manifest.project_selections:
        proj = project_by_id[ps.project_id]
        bullet_text = {b.id: b.text for b in proj.bullets}
        projects_ctx.append({
            "name": latex_escape(proj.name),
            "tech": latex_escape(proj.tech),
            "demo_url": proj.demo_url,
            "repo_url": proj.repo_url,
            "bullets": [latex_escape(bullet_text[bid]) for bid in ps.bullet_ids],
        })

    achievement_text = {b.id: b.text for b in bank.achievements}
    achievements_ctx = [latex_escape(achievement_text[aid]) for aid in manifest.achievement_ids]

    contact = bank.contact
    contact_ctx = {
        "name": latex_escape(contact.name),
        "phone": latex_escape(contact.phone),
        "location": latex_escape(contact.location),
        # URL and email fields stay raw: they go inside \href{...} verbatim.
        "email": contact.email,
        "linkedin_url": contact.linkedin_url,
        "github_url": contact.github_url,
        "website_url": contact.website_url,
        "website_display": latex_escape(contact.website_display),
    }

    education_ctx = {
        "degree": latex_escape(bank.education.degree),
        "school": latex_escape(bank.education.school),
        "date": latex_escape(bank.education.date),
    }

    skills_by_id = {skill.id: skill for skill in bank.skills if skill.id}
    selected_skills = (
        [skills_by_id[skill_id] for skill_id in manifest.skill_ids]
        if manifest.skill_ids
        else bank.skills
    )

    return {
        "contact": contact_ctx,
        "education": education_ctx,
        "summary": latex_escape(manifest.summary),
        "jobs": jobs_ctx,
        "projects": projects_ctx,
        "achievements": achievements_ctx,
        # Named "entries" (not "items") so Jinja's `.` lookup can't resolve
        # to the dict's built-in `.items()` method instead of this key.
        "skills": [
            {"category": latex_escape(s.category), "entries": latex_escape(s.items)}
            for s in selected_skills
        ],
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
