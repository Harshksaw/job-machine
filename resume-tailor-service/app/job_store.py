"""Atomic local store for the canonical per-listing job workspace."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models import (
    Application,
    ApplicationAnswer,
    ApplicationAnswerInput,
    GeneratedApplicationKit,
    JobActivity,
    JobActivityInput,
    JobCaptureInput,
    JobRevision,
    JobSummary,
    JobWorkspace,
    JobWorkspaceInput,
)
from app.errors import JobDecisionConflictError, JobStoreError
from app.slug import safe_slug

BASE_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = BASE_DIR / "data" / "jobs.json"
_LOCK = threading.RLock()

_SHEET_STATUS_MAP = {
    "applied": "applied",
    "people-mined": "outreach",
    "outreach-sent": "outreach",
    "outreach-queued": "applying",
    "replied": "outreach",
    "interview": "interview",
    "offer": "offer",
    "rejected": "rejected",
    "skip": "skipped",
    "skipped": "skipped",
}

_DECISION_PATCH = {
    "approve": ("ready", "Apply", "decision", "Approved to apply"),
    "hold": ("researching", "Review later", "decision", "Held for later review"),
    "applied": ("applied", "Await response", "applied", "Marked applied from inbox"),
}

_DECISION_ALLOWED_STATUSES = {
    "approve": {"discovered", "researching"},
    "hold": {"discovered", "researching"},
    "applied": {"ready", "applying"},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_unlocked() -> list[dict]:
    try:
        raw = STORE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except UnicodeError as exc:
        raise JobStoreError(
            "job dossier store is not valid UTF-8; refusing to overwrite it"
        ) from exc
    except OSError as exc:
        raise JobStoreError("could not read the job dossier store") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise JobStoreError(
            "job dossier store is malformed; refusing to overwrite it"
        ) from exc
    if not isinstance(data, list):
        raise JobStoreError(
            "job dossier store must contain a JSON list; refusing to overwrite it"
        )
    return [row for row in data if isinstance(row, dict)]


def _write_unlocked(items: list[dict]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_name(f"{STORE_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(items, indent=2, ensure_ascii=True), encoding="utf-8")
        os.replace(tmp, STORE_PATH)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _load_valid_unlocked() -> list[JobWorkspace]:
    jobs: list[JobWorkspace] = []
    for raw in _read_unlocked():
        try:
            jobs.append(JobWorkspace.model_validate(raw))
        except ValueError:
            continue
    return jobs


def _input_from_job(job: JobWorkspace) -> JobWorkspaceInput:
    keys = JobWorkspaceInput.model_fields
    return JobWorkspaceInput.model_validate(
        {key: getattr(job, key) for key in keys}
    )


def _normalized_input(data: JobWorkspaceInput) -> JobWorkspaceInput:
    payload = data.model_dump()
    if data.fit_analysis is not None:
        payload["fit_score"] = data.fit_analysis.score
    return JobWorkspaceInput.model_validate(payload)


def _activity(
    data: JobActivityInput,
    *,
    created_at: str | None = None,
) -> JobActivity:
    now = created_at or _now()
    return JobActivity(
        **data.model_dump(),
        id=uuid.uuid4().hex,
        created_at=now,
    )


def _revision(
    data: JobWorkspaceInput,
    *,
    reason: str,
    changed_fields: list[str],
    created_at: str,
) -> JobRevision:
    return JobRevision(
        id=uuid.uuid4().hex,
        reason=reason,
        changed_fields=changed_fields,
        snapshot=data.model_dump(mode="json"),
        created_at=created_at,
    )


def load_jobs() -> list[JobWorkspace]:
    with _LOCK:
        jobs = _load_valid_unlocked()
    return sorted(jobs, key=lambda job: job.updated_at, reverse=True)


def get_job(job_id: str) -> JobWorkspace | None:
    with _LOCK:
        return next((job for job in _load_valid_unlocked() if job.id == job_id), None)


def list_summaries() -> list[JobSummary]:
    return [
        JobSummary(
            id=job.id,
            company=job.company,
            role=job.role,
            job_url=job.job_url,
            source=job.source,
            location=job.location,
            work_mode=job.work_mode,
            status=job.status,
            priority=job.priority,
            fit_score=job.fit_score,
            recommendation=(
                job.fit_analysis.recommendation if job.fit_analysis else None
            ),
            next_action=job.next_action,
            deadline=job.deadline,
            notes=job.notes,
            tailored_resume_id=job.tailored_resume_id,
            has_cover_letter=bool(job.cover_letter.strip()),
            needs_user_input=any(
                answer.needs_user_input for answer in job.application_answers
            ),
            answer_count=len(job.application_answers),
            activity_count=len(job.activities),
            revision_count=len(job.revisions),
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        for job in load_jobs()
    ]


def add_job(data: JobWorkspaceInput, *, session: str = "") -> JobWorkspace:
    normalized = _normalized_input(data)
    with _LOCK:
        items = _read_unlocked()
        now = _now()
        activity = _activity(
            JobActivityInput(
                kind="created",
                title="Job dossier created",
                detail=f"{normalized.company} - {normalized.role}",
                session=session,
            ),
            created_at=now,
        )
        revision = _revision(
            normalized,
            reason="Initial dossier",
            changed_fields=list(JobWorkspaceInput.model_fields),
            created_at=now,
        )
        job = JobWorkspace(
            **normalized.model_dump(),
            id=uuid.uuid4().hex,
            activities=[activity],
            revisions=[revision],
            created_at=now,
            updated_at=now,
        )
        items.append(job.model_dump(mode="json"))
        _write_unlocked(items)
        return job


def update_job(
    job_id: str,
    data: JobWorkspaceInput,
    *,
    reason: str = "Dossier updated",
    activity_kind: str = "updated",
    session: str = "",
) -> JobWorkspace | None:
    normalized = _normalized_input(data)
    with _LOCK:
        items = _read_unlocked()
        for index, raw in enumerate(items):
            try:
                current = JobWorkspace.model_validate(raw)
            except ValueError:
                continue
            if current.id != job_id:
                continue

            before = _input_from_job(current)
            changed_fields = [
                key
                for key in JobWorkspaceInput.model_fields
                if getattr(before, key) != getattr(normalized, key)
            ]
            if not changed_fields:
                return current

            now = _now()
            changed_label = ", ".join(field.replace("_", " ") for field in changed_fields)
            activity = _activity(
                JobActivityInput(
                    kind=activity_kind,
                    title=reason,
                    detail=f"Changed: {changed_label}",
                    session=session,
                ),
                created_at=now,
            )
            revision = _revision(
                normalized,
                reason=reason,
                changed_fields=changed_fields,
                created_at=now,
            )
            updated = JobWorkspace(
                **normalized.model_dump(),
                id=current.id,
                activities=[*current.activities, activity],
                revisions=[*current.revisions, revision],
                created_at=current.created_at,
                updated_at=now,
            )
            items[index] = updated.model_dump(mode="json")
            _write_unlocked(items)
            return updated
        return None


def apply_decision(
    job_id: str,
    decision: str,
    *,
    session: str = "Inbox",
) -> JobWorkspace | None:
    with _LOCK:
        items = _read_unlocked()
        for index, raw in enumerate(items):
            try:
                current = JobWorkspace.model_validate(raw)
            except ValueError:
                continue
            if current.id != job_id:
                continue

            allowed_statuses = _DECISION_ALLOWED_STATUSES[decision]
            if current.status not in allowed_statuses:
                allowed_label = ", ".join(sorted(allowed_statuses))
                raise JobDecisionConflictError(
                    f"cannot {decision} a job in status {current.status}; "
                    f"expected one of: {allowed_label}"
                )

            status, next_action, kind, title = _DECISION_PATCH[decision]
            if (current.fit_score or 0) >= 8:
                if decision == "approve":
                    next_action = "Apply; reach out to people at the company"
                elif decision == "applied":
                    next_action = "Reach out to people at the company"

            before = _input_from_job(current)
            after = before.model_copy(
                update={"status": status, "next_action": next_action}
            )
            changed_fields = [
                key
                for key in ("status", "next_action")
                if getattr(before, key) != getattr(after, key)
            ]
            now = _now()
            activity = _activity(
                JobActivityInput(
                    kind=kind,
                    title=title,
                    detail=(
                        f"{current.company} — {current.role}. "
                        f"Status set to {status}."
                    ),
                    session=session,
                ),
                created_at=now,
            )
            revisions = current.revisions
            if changed_fields:
                revisions = [
                    *revisions,
                    _revision(
                        after,
                        reason=title,
                        changed_fields=changed_fields,
                        created_at=now,
                    ),
                ]
            updated = JobWorkspace(
                **after.model_dump(),
                id=current.id,
                activities=[*current.activities, activity],
                revisions=revisions,
                created_at=current.created_at,
                updated_at=now,
            )
            items[index] = updated.model_dump(mode="json")
            _write_unlocked(items)
            return updated
        return None


def delete_job(job_id: str) -> bool:
    with _LOCK:
        items = _read_unlocked()
        kept = [raw for raw in items if raw.get("id") != job_id]
        if len(kept) == len(items):
            return False
        _write_unlocked(kept)
        return True


def add_activity(job_id: str, data: JobActivityInput) -> JobWorkspace | None:
    with _LOCK:
        items = _read_unlocked()
        for index, raw in enumerate(items):
            try:
                current = JobWorkspace.model_validate(raw)
            except ValueError:
                continue
            if current.id != job_id:
                continue
            if data.external_id and any(
                event.external_id == data.external_id for event in current.activities
            ):
                return current

            now = _now()
            updated = current.model_copy(
                update={
                    "activities": [*current.activities, _activity(data)],
                    "updated_at": now,
                }
            )
            items[index] = updated.model_dump(mode="json")
            _write_unlocked(items)
            return updated
        return None


def restore_revision(
    job_id: str,
    revision_id: str,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    revision = next((item for item in current.revisions if item.id == revision_id), None)
    if revision is None:
        return None
    restored = JobWorkspaceInput.model_validate(revision.snapshot)
    return update_job(
        job_id,
        restored,
        reason=f"Restored revision: {revision.reason}",
        activity_kind="restored",
        session=session,
    )


def apply_generated_kit(
    job_id: str,
    kit: GeneratedApplicationKit,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    data = _input_from_job(current)
    updated = data.model_copy(
        update={
            "fit_score": kit.analysis.score,
            "fit_analysis": kit.analysis,
            "cover_letter": kit.cover_letter,
            "status": (
                "ready"
                if kit.analysis.recommendation == "apply"
                and current.status in {"discovered", "researching"}
                else current.status
            ),
        }
    )
    return update_job(
        job_id,
        updated,
        reason="Application kit generated",
        activity_kind="generated",
        session=session,
    )


def attach_resume(
    job_id: str,
    resume_id: str,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    updated = _input_from_job(current).model_copy(
        update={"tailored_resume_id": resume_id}
    )
    return update_job(
        job_id,
        updated,
        reason="Tailored resume attached",
        activity_kind="resume",
        session=session,
    )


def sync_tailor_context(
    job_id: str,
    jd_text: str,
    job_url: str | None,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    patch: dict = {"jd_text": jd_text}
    if job_url and job_url.strip():
        patch["job_url"] = job_url
    updated = _input_from_job(current).model_copy(update=patch)
    return update_job(
        job_id,
        updated,
        reason="Tailoring context saved",
        activity_kind="resume",
        session=session,
    )


def add_answer(
    job_id: str,
    data: ApplicationAnswerInput,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    now = _now()
    answer = ApplicationAnswer(
        **data.model_dump(),
        id=uuid.uuid4().hex,
        created_at=now,
        updated_at=now,
    )
    updated = _input_from_job(current).model_copy(
        update={"application_answers": [*current.application_answers, answer]}
    )
    return update_job(
        job_id,
        updated,
        reason="Application answer added",
        activity_kind="answer",
        session=session,
    )


def replace_answer(
    job_id: str,
    answer_id: str,
    data: ApplicationAnswerInput,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    existing = next(
        (answer for answer in current.application_answers if answer.id == answer_id),
        None,
    )
    if existing is None:
        return None
    replacement = ApplicationAnswer(
        **data.model_dump(),
        id=existing.id,
        created_at=existing.created_at,
        updated_at=_now(),
    )
    answers = [
        replacement if answer.id == answer_id else answer
        for answer in current.application_answers
    ]
    updated = _input_from_job(current).model_copy(
        update={"application_answers": answers}
    )
    return update_job(
        job_id,
        updated,
        reason="Application answer updated",
        activity_kind="answer",
        session=session,
    )


def delete_answer(
    job_id: str,
    answer_id: str,
    *,
    session: str = "",
) -> JobWorkspace | None:
    current = get_job(job_id)
    if current is None:
        return None
    answers = [
        answer for answer in current.application_answers if answer.id != answer_id
    ]
    if len(answers) == len(current.application_answers):
        return None
    updated = _input_from_job(current).model_copy(
        update={"application_answers": answers}
    )
    return update_job(
        job_id,
        updated,
        reason="Application answer removed",
        activity_kind="answer",
        session=session,
    )


def _job_key(company: str, role: str) -> str:
    return safe_slug(company, role)


def find_matching_job(
    company: str,
    role: str,
    job_url: str = "",
) -> JobWorkspace | None:
    jobs = load_jobs()
    clean_url = job_url.strip()
    if clean_url:
        exact = next((job for job in jobs if job.job_url.strip() == clean_url), None)
        if exact is not None:
            return exact
    key = _job_key(company, role)
    candidates = [job for job in jobs if _job_key(job.company, job.role) == key]
    if not candidates:
        return None
    if clean_url:
        blank_url = next((job for job in candidates if not job.job_url.strip()), None)
        if blank_url is not None:
            return blank_url
        return None
    return candidates[0]


def capture_job(data: JobCaptureInput) -> tuple[JobWorkspace, bool]:
    """Create or enrich a dossier from an agent/browser search session."""
    current = find_matching_job(data.company, data.role, data.job_url)
    if current is None:
        return (
            add_job(
                JobWorkspaceInput(
                    company=data.company,
                    role=data.role,
                    job_url=data.job_url,
                    source=data.source,
                    location=data.location,
                    work_mode=data.work_mode,
                    status=data.status or "discovered",
                    fit_score=data.fit_score,
                    jd_text=data.jd_text,
                    company_context=data.company_context,
                    why_this_role=data.why_this_role,
                    notes=data.notes,
                    next_action=data.next_action,
                    deadline=data.deadline,
                ),
                session=data.session,
            ),
            True,
        )

    current_input = _input_from_job(current)
    patch: dict = {
        "company": data.company,
        "role": data.role,
    }
    for field in (
        "job_url",
        "source",
        "location",
        "work_mode",
        "jd_text",
        "company_context",
        "why_this_role",
        "notes",
        "next_action",
        "deadline",
    ):
        value = getattr(data, field)
        if value.strip():
            patch[field] = value
    if data.status is not None:
        patch["status"] = data.status
    if data.fit_score is not None:
        patch["fit_score"] = data.fit_score

    updated = update_job(
        current.id,
        current_input.model_copy(update=patch),
        reason="Session capture synchronized",
        activity_kind="captured",
        session=data.session,
    )
    if updated is not None and updated.updated_at != current.updated_at:
        return updated, False
    revisited = add_activity(
        current.id,
        JobActivityInput(
            kind="captured",
            title="Listing revisited",
            session=data.session,
        ),
    )
    return revisited or current, False


def _sheet_fingerprint(application: Application) -> str:
    payload = "|".join(
        (
            application.company,
            application.role,
            application.job_url,
            application.status,
            application.timestamp,
            application.notes,
            application.people,
            application.outreach,
        )
    )
    return "sheet:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_application(
    application: Application,
    *,
    session: str = "Sheet import",
) -> tuple[JobWorkspace, bool]:
    current = find_matching_job(
        application.company,
        application.role,
        application.job_url,
    )
    mapped_status = _SHEET_STATUS_MAP.get(
        application.status.strip().lower(),
        "discovered",
    )
    try:
        fit_score = int(float(application.fit)) if application.fit.strip() else None
    except ValueError:
        fit_score = None
    if fit_score is not None and not 1 <= fit_score <= 10:
        fit_score = None

    created = current is None
    if current is None:
        current = add_job(
            JobWorkspaceInput(
                company=application.company or "Unknown company",
                role=application.role or "Unknown role",
                job_url=application.job_url,
                source=application.source,
                status=mapped_status,
                fit_score=fit_score,
                company_context=application.hooks,
                notes=application.notes,
                tailored_resume_id=application.tailored_resume_id,
            ),
            session=session,
        )
    else:
        data = _input_from_job(current)
        patch: dict = {}
        for field, incoming in (
            ("job_url", application.job_url),
            ("source", application.source),
            ("company_context", application.hooks),
            ("notes", application.notes),
        ):
            if incoming.strip() and not getattr(data, field).strip():
                patch[field] = incoming
        if application.tailored_resume_id and not data.tailored_resume_id:
            patch["tailored_resume_id"] = application.tailored_resume_id
        if fit_score is not None and data.fit_score is None:
            patch["fit_score"] = fit_score
        latest_sheet_time = max(
            (
                event.occurred_at or ""
                for event in current.activities
                if event.kind == "sheet"
            ),
            default="",
        )
        status_is_current = (
            not latest_sheet_time
            or (
                bool(application.timestamp)
                and application.timestamp >= latest_sheet_time
            )
        )
        if (
            status_is_current
            and mapped_status != "discovered"
            and data.status not in {"offer", "archived"}
        ):
            patch["status"] = mapped_status
        if patch:
            current = update_job(
                current.id,
                data.model_copy(update=patch),
                reason="Sheet fields synchronized",
                activity_kind="import",
                session=session,
            ) or current

    detail_parts = [
        value
        for value in (
            application.notes,
            f"People: {application.people}" if application.people else "",
            f"Hooks: {application.hooks}" if application.hooks else "",
            f"Outreach: {application.outreach}" if application.outreach else "",
        )
        if value
    ]
    current = add_activity(
        current.id,
        JobActivityInput(
            kind="sheet",
            title=f"Sheet event: {application.status or 'logged'}",
            detail="\n".join(detail_parts),
            session=session,
            occurred_at=application.timestamp or None,
            external_id=_sheet_fingerprint(application),
        ),
    ) or current
    return current, created
