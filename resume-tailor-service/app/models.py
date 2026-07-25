from typing import Any

from pydantic import BaseModel, Field, field_validator


class TailorRequest(BaseModel):
    jd_text: str
    company: str
    role: str
    job_url: str | None = None
    job_id: str | None = None
    session: str = ""


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
    skill_ids: list[str] = Field(default_factory=list)
    job_trim_priority: list[str]


class TailorResponse(BaseModel):
    pdf_path: str
    manifest: Manifest
    pages: int
    resume_id: str | None = None


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


JOB_STATUSES = (
    "discovered",
    "researching",
    "ready",
    "applying",
    "applied",
    "outreach",
    "interview",
    "offer",
    "rejected",
    "skipped",
    "archived",
)
JOB_PRIORITIES = ("low", "normal", "high", "dream")
# ``skip`` remains readable for dossiers created before low-fit review became
# the default. New generation accepts only ``apply`` or ``review``.
FIT_RECOMMENDATIONS = ("apply", "review", "skip")
EVIDENCE_STRENGTHS = ("strong", "partial", "gap")
ANSWER_STATUSES = ("draft", "approved", "submitted")


class FitEvidence(BaseModel):
    requirement: str
    strength: str
    proof: str = ""
    source_ids: list[str] = Field(default_factory=list)

    @field_validator("strength")
    @classmethod
    def _known_strength(cls, value: str) -> str:
        if value not in EVIDENCE_STRENGTHS:
            raise ValueError(f"strength must be one of {EVIDENCE_STRENGTHS}")
        return value


class FitAnalysis(BaseModel):
    score: int = Field(ge=1, le=10)
    recommendation: str
    verdict: str
    role_thesis: str = ""
    keywords: list[str] = Field(default_factory=list)
    evidence: list[FitEvidence] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    positioning: list[str] = Field(default_factory=list)

    @field_validator("recommendation")
    @classmethod
    def _known_recommendation(cls, value: str) -> str:
        if value not in FIT_RECOMMENDATIONS:
            raise ValueError(f"recommendation must be one of {FIT_RECOMMENDATIONS}")
        return value


class ApplicationAnswerInput(BaseModel):
    question: str
    answer: str = ""
    constraints: str = ""
    status: str = "draft"
    source_ids: list[str] = Field(default_factory=list)
    needs_user_input: bool = False
    clarification: str = ""

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()

    @field_validator("status")
    @classmethod
    def _known_answer_status(cls, value: str) -> str:
        if value not in ANSWER_STATUSES:
            raise ValueError(f"status must be one of {ANSWER_STATUSES}")
        return value


class ApplicationAnswer(ApplicationAnswerInput):
    id: str
    created_at: str
    updated_at: str


class JobActivityInput(BaseModel):
    kind: str = "note"
    title: str
    detail: str = ""
    session: str = ""
    occurred_at: str | None = None
    external_id: str | None = None

    @field_validator("kind", "title")
    @classmethod
    def _activity_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class JobActivity(JobActivityInput):
    id: str
    created_at: str


class JobWorkspaceInput(BaseModel):
    company: str
    role: str
    job_url: str = ""
    source: str = ""
    location: str = ""
    work_mode: str = ""
    compensation: str = ""
    status: str = "discovered"
    priority: str = "normal"
    fit_score: int | None = Field(default=None, ge=1, le=10)
    jd_text: str = ""
    company_context: str = ""
    why_this_role: str = ""
    notes: str = ""
    next_action: str = ""
    deadline: str = ""
    fit_analysis: FitAnalysis | None = None
    cover_letter: str = ""
    application_answers: list[ApplicationAnswer] = Field(default_factory=list)
    tailored_resume_id: str | None = None

    @field_validator("company", "role")
    @classmethod
    def _job_identity_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("status")
    @classmethod
    def _known_job_status(cls, value: str) -> str:
        if value not in JOB_STATUSES:
            raise ValueError(f"status must be one of {JOB_STATUSES}")
        return value

    @field_validator("priority")
    @classmethod
    def _known_priority(cls, value: str) -> str:
        if value not in JOB_PRIORITIES:
            raise ValueError(f"priority must be one of {JOB_PRIORITIES}")
        return value


class JobCaptureInput(BaseModel):
    """Small automation-friendly upsert payload for browser search sessions."""

    company: str
    role: str
    job_url: str = ""
    source: str = ""
    location: str = ""
    work_mode: str = ""
    status: str | None = None
    fit_score: int | None = Field(default=None, ge=1, le=10)
    jd_text: str = ""
    company_context: str = ""
    why_this_role: str = ""
    notes: str = ""
    next_action: str = ""
    deadline: str = ""
    session: str = ""

    @field_validator("company", "role")
    @classmethod
    def _capture_identity_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("status")
    @classmethod
    def _known_capture_status(cls, value: str | None) -> str | None:
        if value is not None and value not in JOB_STATUSES:
            raise ValueError(f"status must be one of {JOB_STATUSES}")
        return value


class JobRevision(BaseModel):
    id: str
    reason: str
    changed_fields: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any]
    created_at: str


class JobWorkspace(JobWorkspaceInput):
    id: str
    activities: list[JobActivity] = Field(default_factory=list)
    revisions: list[JobRevision] = Field(default_factory=list)
    created_at: str
    updated_at: str


class JobSummary(BaseModel):
    id: str
    company: str
    role: str
    job_url: str
    source: str
    location: str
    status: str
    priority: str
    fit_score: int | None
    recommendation: str | None
    next_action: str
    deadline: str
    tailored_resume_id: str | None
    answer_count: int
    activity_count: int
    revision_count: int
    created_at: str
    updated_at: str


class GeneratedApplicationKit(BaseModel):
    analysis: FitAnalysis
    cover_letter: str = ""


class GenerateAnswerRequest(BaseModel):
    question: str
    constraints: str = ""
    session: str = ""

    @field_validator("question")
    @classmethod
    def _generated_question_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


class GeneratedAnswer(BaseModel):
    answer: str = ""
    source_ids: list[str] = Field(default_factory=list)
    needs_user_input: bool = False
    clarification: str = ""


class SheetImportResult(BaseModel):
    imported_rows: int
    created_jobs: int
    updated_jobs: int
    job_ids: list[str] = Field(default_factory=list)
