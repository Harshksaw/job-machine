"""Agent steps of the packet pipeline: output schemas, finish functions and builders.

An agent step names a capability, not a tool. The runner hands it to an adapter chain,
the adapter renders `prompts/<step>.md` and returns a JSON object, the runner validates
it against the step schema (a failure gets one repair try with the error list), and the
finish function turns the parsed output into dossier writes. A finish writes only the
fields its step owns, except `people`, which adds people through the people store the
way `POST /api/jobs/{id}/people` does.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md sections 4 and 6.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import job_store, people_store
from app.house_style import strip_dashes
from app.models import FormField, JobActivityInput, Link, PersonInput, ReviewIssue
from app.pipeline import rules
from app.pipeline.runner import StepContext, StepResult, StepSpec

FIT_FLOOR = job_store.FIT_APPLY_FLOOR  # rule 2: below this the run ends "retained_for_review"
TIER_A2_FIT_FLOOR = 7  # AGENTS.md discovery sources: Tier A2 needs fit 7+
PEOPLE_FLOOR = 8  # rule 2: 8+ is people mining eligible
MAX_PEOPLE = 3


def _line(text: object) -> str:
    """One clean line: no em dashes (AGENTS.md working style), no newlines."""
    return " ".join(strip_dashes(str(text or "")).split())


def _not_blank(value: str) -> str:
    value = _line(value)
    if not value:
        raise ValueError("must not be blank")
    return value


def _url(value: str) -> str:
    value = (value or "").strip()
    if not value.startswith(("https://", "http://")) or " " in value:
        raise ValueError(f"must be an http or https URL, got {value!r}")
    return value


def _append_note(ctx: StepContext, line: str) -> job_store.Merge:
    """The line appended to the notes as they are at write time, not to this step's
    snapshot, so a note added while the step ran survives."""
    return job_store.append_note(line)


def _prefix(ctx: StepContext) -> str:
    return f"Pipeline {ctx.run.id}:"


# eligibility


class EligibilityOutput(BaseModel):
    eligible: bool
    reason: str
    # AGENTS.md (2026-11-27): remote limited to US, UK, Australian, New Zealand or another
    # non India country's residents is eligible as Tier A2, which needs fit 7 or higher.
    tier_a2: bool = False
    # Europe only, or a European company: eligible as Tier E, kept and worked last.
    tier_e: bool = False

    _reason = field_validator("reason")(_not_blank)


def _finish_eligibility(out: EligibilityOutput, ctx: StepContext) -> StepResult:
    verdict = "eligible" if out.eligible else "ineligible"
    if out.eligible and out.tier_a2:
        verdict = "eligible (Tier A2)"
    elif out.eligible and out.tier_e:
        verdict = "eligible (Tier E)"
    writes = {"notes": _append_note(ctx, f"{_prefix(ctx)} {verdict}, {out.reason}")}
    output = out.model_dump()
    if out.eligible:
        return StepResult(output=output, writes=writes)
    # Ends the run with a reason; the dossier is never archived or skipped.
    return StepResult(output=output, writes=writes, stop="ineligible", reason=out.reason[:300])


def eligibility_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("eligibility", "agent", deps=deps, owns=("notes",), capability="cheap",
                    schema=EligibilityOutput, finish=_finish_eligibility)


# fit_score


class FitScoreOutput(BaseModel):
    score: int = Field(ge=1, le=10)
    reason: str
    gaps: list[str] = Field(default_factory=list)

    _reason = field_validator("reason")(_not_blank)

    @field_validator("gaps")
    @classmethod
    def _clean_gaps(cls, gaps: list[str]) -> list[str]:
        return [_line(gap) for gap in gaps if _line(gap)]


def _finish_fit_score(out: FitScoreOutput, ctx: StepContext) -> StepResult:
    gaps = f" Gaps: {'; '.join(out.gaps)}." if out.gaps else ""
    writes: dict = {
        "fit_score": out.score,
        "notes": _append_note(ctx, f"{_prefix(ctx)} fit {out.score}/10, {out.reason}{gaps}"),
    }
    # job_store.patch_job moves a stored fit_analysis to this score in the same write.
    output = out.model_dump()
    tier_a2 = bool((ctx.outputs.get("eligibility") or {}).get("tier_a2"))
    floor = TIER_A2_FIT_FLOOR if tier_a2 else FIT_FLOOR
    if out.score < floor:
        # Rule 2: retain for review. The dossier stays active with its reason and gaps.
        label = f"Tier A2 needs fit {floor}+, " if tier_a2 else ""
        return StepResult(output=output, writes=writes, stop="retained_for_review",
                          reason=f"{label}fit {out.score}/10: {out.reason}"[:300])
    return StepResult(output=output, writes=writes)


def fit_score_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("fit_score", "agent", deps=deps, owns=("fit_score", "notes", "fit_analysis"),
                    capability="reason", schema=FitScoreOutput, finish=_finish_fit_score)


def fit_of(ctx: StepContext) -> int:
    """This run's fit score, else the one on the dossier, else 0."""
    score = (ctx.outputs.get("fit_score") or {}).get("score")
    if isinstance(score, int):
        return score
    return ctx.job.fit_score or 0


# company_context


_bank_ids: set[str] | None = None


def bank_source_ids() -> set[str]:
    """Source ids of the committed resume bank, loaded once."""
    global _bank_ids
    if _bank_ids is None:
        from app.application_kit import build_source_index
        from app.bank import load_bank
        from app.pipeline.prompts import BANK_PATH

        _bank_ids = set(build_source_index(load_bank(BANK_PATH)))
    return _bank_ids


class CompanyContextOutput(BaseModel):
    company_context: str
    why_this_role: str
    # Rule 1: why_this_role must trace to the resume bank.
    why_source_ids: list[str] = Field(min_length=1)
    sources: list[str] = Field(min_length=1)

    @field_validator("why_source_ids")
    @classmethod
    def _known_ids(cls, ids: list[str]) -> list[str]:
        known = bank_source_ids()
        unknown = [source_id for source_id in ids if source_id not in known]
        if unknown:
            raise ValueError(f"unknown resume bank source ids: {unknown}")
        return ids

    @field_validator("company_context", "why_this_role")
    @classmethod
    def _text(cls, value: str) -> str:
        value = strip_dashes(value or "").strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("sources")
    @classmethod
    def _sources(cls, sources: list[str]) -> list[str]:
        return [_url(source) for source in sources]


def _finish_company_context(out: CompanyContextOutput, ctx: StepContext) -> StepResult:
    sources = "\n".join(f"- {url}" for url in out.sources)
    return StepResult(
        output=out.model_dump(),
        writes={
            "company_context": f"{out.company_context}\n\nSources:\n{sources}",
            "why_this_role": f"{out.why_this_role} (bank: {', '.join(out.why_source_ids)})",
        },
    )


def company_context_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("company_context", "agent", deps=deps, owns=("company_context", "why_this_role"),
                    capability="web", schema=CompanyContextOutput, finish=_finish_company_context)


# form_fields


class FormFieldsOutput(BaseModel):
    url: str = ""
    fields: list[FormField] = Field(default_factory=list)
    note: str = ""


def _finish_form_fields(out: FormFieldsOutput, ctx: StepContext) -> StepResult:
    return StepResult(
        output={"url": out.url, "count": len(out.fields), "note": _line(out.note)},
        writes={"form_fields": [field.model_dump() for field in out.fields]},
    )


def form_fields_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("form_fields", "agent", deps=deps, owns=("form_fields",),
                    capability="browser_read", schema=FormFieldsOutput, finish=_finish_form_fields)


# people


class FoundPerson(BaseModel):
    name: str
    title: str = ""
    url: str
    why: str = ""

    _name = field_validator("name")(_not_blank)
    _url = field_validator("url")(_url)

    @field_validator("title", "why")
    @classmethod
    def _clean(cls, value: str) -> str:
        return _line(value)


class PeopleOutput(BaseModel):
    people: list[FoundPerson] = Field(default_factory=list, max_length=MAX_PEOPLE)


def _known(person: FoundPerson, existing) -> bool:
    for saved in existing:
        urls = {saved.linkedin_url, *(link.url for link in saved.links)} - {""}
        if saved.name.strip().lower() == person.name.lower() or person.url in urls:
            return True
    return False


def _finish_people(out: PeopleOutput, ctx: StepContext) -> StepResult:
    """Pin each person to the dossier, as POST /api/jobs/{id}/people does. Never
    contacts anyone: a person starts at "to-reach". Someone already saved for this
    job (same name or URL) is left alone, so a resumed run adds no duplicates."""
    job = ctx.job
    session = f"pipeline {ctx.run.id}"
    added = 0
    for person in out.people:
        if _known(person, people_store.people_for_job(job.id, job.company, job.role)):
            continue
        saved = people_store.add_person(PersonInput(
            name=person.name,
            title=person.title,
            company=job.company,
            role=job.role,
            job_id=job.id,
            linkedin_url=person.url if "linkedin.com/" in person.url else "",
            links=[Link(label="profile", url=person.url)],
            notes=person.why,
        ))
        job_store.add_activity(job.id, JobActivityInput(
            kind="research",
            title=f"Added {saved.name} to reach",
            detail=f"{saved.name}" + (f", {saved.title}" if saved.title else "")
            + f" saved on this listing by {session}. Status {saved.status}.",
            session=session,
        ))
        added += 1
    return StepResult(output={"people": [p.model_dump() for p in out.people], "added": added})


def people_step(deps: tuple[str, ...] = ()) -> StepSpec:
    return StepSpec("people", "agent", deps=deps, capability="web", schema=PeopleOutput,
                    finish=_finish_people, when=lambda ctx: fit_of(ctx) >= PEOPLE_FLOOR)


# review


class ReviewOutput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    passed: bool = Field(alias="pass")
    issues: list[ReviewIssue] = Field(default_factory=list)


def _finish_review(out: ReviewOutput, ctx: StepContext) -> StepResult:
    issues = [issue.model_dump() for issue in out.issues]
    for issue in rules.packet_issues(ctx.job):
        if issue not in issues:
            issues.append(issue)
    passed = out.passed and not issues
    return StepResult(
        output={"pass": passed, "issues": issues},
        writes={"review": {"passed": passed, "issues": issues}},
    )


def review_step(deps: tuple[str, ...] = ()) -> StepSpec:
    # Spec 6.4: never reviewed by the adapter that wrote the kit or the answers.
    return StepSpec("review", "agent", deps=deps, owns=("review",), capability="cheap",
                    schema=ReviewOutput, finish=_finish_review, independent_of=("kit", "answers"))
