from __future__ import annotations
from pathlib import Path
import yaml
from pydantic import BaseModel


class Bullet(BaseModel):
    id: str
    text: str


class Job(BaseModel):
    id: str
    company: str
    location: str
    title: str
    dates: str
    bullets: list[Bullet]


class Project(BaseModel):
    id: str
    name: str
    tech: str
    bullets: list[Bullet]


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
    category: str
    items: str


class ResumeBank(BaseModel):
    contact: Contact
    education: Education
    jobs: list[Job]
    projects: list[Project]
    achievements: list[Bullet]
    skills: list[SkillLine]


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


def all_job_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {job.id: {b.id for b in job.bullets} for job in bank.jobs}


def all_project_bullet_ids(bank: ResumeBank) -> dict[str, set[str]]:
    return {proj.id: {b.id for b in proj.bullets} for proj in bank.projects}


def bank_text_blob(bank: ResumeBank) -> str:
    parts: list[str] = []
    for job in bank.jobs:
        parts.extend(b.text for b in job.bullets)
    for proj in bank.projects:
        parts.extend(b.text for b in proj.bullets)
    parts.extend(b.text for b in bank.achievements)
    parts.extend(s.items for s in bank.skills)
    return " ".join(parts)
