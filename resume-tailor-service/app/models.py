from pydantic import BaseModel


class TailorRequest(BaseModel):
    jd_text: str
    company: str
    role: str


class JobSelection(BaseModel):
    job_id: str
    bullet_ids: list[str]


class ProjectSelection(BaseModel):
    project_id: str
    bullet_ids: list[str]


class Manifest(BaseModel):
    summary: str
    job_selections: list[JobSelection]
    project_selections: list[ProjectSelection]
    achievement_ids: list[str]
    job_trim_priority: list[str]


class TailorResponse(BaseModel):
    pdf_path: str
    manifest: Manifest
    pages: int
