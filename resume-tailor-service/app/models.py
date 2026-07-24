from pydantic import BaseModel, field_validator


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


class TailoredResumeMeta(BaseModel):
    company: str
    role: str
    jd_text: str
    pdf_path: str
    manifest: Manifest
    pages: int
    created_at: str
    job_url: str | None = None


class Application(BaseModel):
    """One row of the Google-Sheet application log.

    Every cell arrives as free-form spreadsheet text, so all sheet-sourced
    fields are plain strings defaulting to "" (missing/blank cells normalize to
    "" in ``sheets.fetch_applications``). ``tailored_resume_id`` is filled in by
    the dashboard join (output dir name) and is None when no tailored resume
    matches.
    """

    company: str = ""
    role: str = ""
    source: str = ""
    job_url: str = ""
    status: str = ""
    fit: str = ""
    people: str = ""
    hooks: str = ""
    outreach: str = ""
    notes: str = ""
    timestamp: str = ""
    tailored_resume_id: str | None = None


PERSON_STATUSES = ("to-reach", "queued", "sent", "replied", "skip")


class Link(BaseModel):
    label: str = ""
    url: str = ""


class PersonInput(BaseModel):
    name: str
    title: str = ""
    company: str
    role: str | None = None
    linkedin_url: str = ""
    links: list[Link] = []
    status: str = "to-reach"
    hook: str = ""
    message: str = ""
    notes: str = ""

    @field_validator("name", "company")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("status")
    @classmethod
    def _known_status(cls, v: str) -> str:
        if v not in PERSON_STATUSES:
            raise ValueError(f"status must be one of {PERSON_STATUSES}")
        return v


class Person(PersonInput):
    id: str
    created_at: str
    updated_at: str
