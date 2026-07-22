import re
from app.bank import (
    ResumeBank, all_job_ids, all_project_ids, all_achievement_ids,
    all_job_bullet_ids, all_project_bullet_ids, bank_text_blob,
)
from app.models import Manifest

_NUMERIC_RE = re.compile(r"\d[\d,.]*\+?%?[KkMmBb]?\+?")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")


def extract_facts(text: str) -> set[str]:
    return set(_NUMERIC_RE.findall(text)) | set(_ACRONYM_RE.findall(text))


def validate_manifest(manifest: Manifest, bank: ResumeBank) -> list[str]:
    errors: list[str] = []

    job_ids = all_job_ids(bank)
    project_ids = all_project_ids(bank)
    achievement_ids = all_achievement_ids(bank)
    job_bullet_ids = all_job_bullet_ids(bank)
    project_bullet_ids = all_project_bullet_ids(bank)

    for js in manifest.job_selections:
        if js.job_id not in job_ids:
            errors.append(f"unknown job_id: {js.job_id}")
            continue
        valid_bullets = job_bullet_ids[js.job_id]
        for bid in js.bullet_ids:
            if bid not in valid_bullets:
                errors.append(f"unknown bullet_id {bid!r} for job {js.job_id!r}")

    for ps in manifest.project_selections:
        if ps.project_id not in project_ids:
            errors.append(f"unknown project_id: {ps.project_id}")
            continue
        valid_bullets = project_bullet_ids[ps.project_id]
        for bid in ps.bullet_ids:
            if bid not in valid_bullets:
                errors.append(f"unknown bullet_id {bid!r} for project {ps.project_id!r}")

    for aid in manifest.achievement_ids:
        if aid not in achievement_ids:
            errors.append(f"unknown achievement_id: {aid}")

    if set(manifest.job_trim_priority) != job_ids:
        errors.append(
            f"job_trim_priority must be exactly {sorted(job_ids)}, got {manifest.job_trim_priority}"
        )

    blob = bank_text_blob(bank)
    for fact in extract_facts(manifest.summary):
        if fact not in blob:
            errors.append(f"untraceable fact in summary: {fact!r}")

    return errors
