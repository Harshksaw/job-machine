from __future__ import annotations
from pathlib import Path
import re
import yaml
from pydantic import BaseModel, Field

# Bullets carry Harsh's keyword emphasis as "**phrase**", mirroring the
# \textbf{} spans in harshsaw.tex. Only app.render_tex turns the marker into
# bold; every other consumer wants the plain sentence, because a cover letter
# quoting "**Apache Kafka**" would be wrong and a traceability corpus should
# match on the word, not the punctuation around it.
_EMPHASIS_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def strip_emphasis(text: str) -> str:
    return _EMPHASIS_RE.sub(r"\1", text)


class Bullet(BaseModel):
    id: str
    text: str

    @property
    def plain(self) -> str:
        """The bullet as prose, with presentation markers removed."""
        return strip_emphasis(self.text)


class Job(BaseModel):
    id: str
    company: str
    location: str
    title: str
    dates: str
    bullets: list[Bullet]
    # The canonical resume links the company name (\job's 3rd argument).
    # Optional: an empty url renders the company as plain text.
    url: str = ""


class Project(BaseModel):
    id: str
    name: str
    tech: str
    bullets: list[Bullet]
    # The canonical resume puts "Live Demo | GitHub" beside each project
    # heading. Either may be empty; the template omits what is missing.
    demo_url: str = ""
    repo_url: str = ""


class Contact(BaseModel):
    name: str
    phone: str
    location: str
    email: str
    linkedin_url: str
    github_url: str
    website_url: str
    website_display: str


class Education(BaseModel):
    degree: str
    school: str
    date: str


class SkillLine(BaseModel):
    id: str = ""
    category: str
    items: str


class ResumeBank(BaseModel):
    contact: Contact
    education: Education
    jobs: list[Job]
    projects: list[Project]
    achievements: list[Bullet]
    skills: list[SkillLine]
    profile_facts: list[Bullet] = Field(default_factory=list)


def load_bank(path: Path) -> ResumeBank:
    if not path.exists():
        raise FileNotFoundError(f"resume bank not found: {path}")
    data = yaml.safe_load(path.read_text())
    return ResumeBank.model_validate(data)


def all_job_ids(bank: ResumeBank) -> set[str]:
    return {job.id for job in bank.jobs}


def all_project_ids(bank: ResumeBank) -> set[str]:
    return {project.id for project in bank.projects}


def all_achievement_ids(bank: ResumeBank) -> set[str]:
    return {bullet.id for bullet in bank.achievements}


def all_skill_ids(bank: ResumeBank) -> set[str]:
    return {skill.id for skill in bank.skills if skill.id}


def all_job_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {job.id: {b.id for b in job.bullets} for job in bank.jobs}


def all_project_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {proj.id: {b.id for b in proj.bullets} for proj in bank.projects}


def bank_text_blob(bank: ResumeBank) -> str:
    parts: list[str] = []
    for job in bank.jobs:
        parts.append(job.company)
        parts.append(job.title)
        parts.extend(b.plain for b in job.bullets)
    for proj in bank.projects:
        parts.append(proj.name)
        parts.extend(b.plain for b in proj.bullets)
    parts.extend(b.plain for b in bank.achievements)
    parts.extend(s.items for s in bank.skills)
    parts.extend(fact.text for fact in bank.profile_facts)
    return " ".join(parts)
