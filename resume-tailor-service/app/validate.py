import re
from app.bank import (
    ResumeBank, all_job_ids, all_project_ids, all_achievement_ids,
    all_skill_ids, all_job_bullet_ids, all_project_bullet_ids, bank_text_blob,
)
from app.models import Manifest

_NUMERIC_RE = re.compile(r"\d[\d,.]*\+?%?[KkMmBb]?\+?")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#\-]*")
_SENTENCE_END = (".", "!", "?")


def _bank_word_set(bank: ResumeBank) -> set[str]:
    return {w.lower() for w in _TOKEN_RE.findall(bank_text_blob(bank))}


def extract_facts(text: str) -> set[str]:
    """Tokens in a summary that MUST be traceable to the resume bank:
    numbers, all-caps acronyms, tech-looking tokens (internal caps or . + #),
    and proper-noun-style Capitalized words that appear mid-sentence.
    Note: lowercase, number-free qualitative claims are intentionally NOT
    checked here (documented residual — the prompt constrains those, and a
    persistent validation failure degrades safely to the static resume via
    the run-prompt fallback)."""
    facts: set[str] = set(_NUMERIC_RE.findall(text))
    matches = list(_TOKEN_RE.finditer(text))
    for i, m in enumerate(matches):
        # Strip a trailing sentence terminator (".", "!", "?") that the token
        # regex's continuation class greedily glues onto the last word of a
        # sentence (e.g. "pipeline." or "Go.") — that punctuation is not part
        # of the word/tech-token itself, unlike an internal "." in "Node.js".
        tok = m.group().rstrip(".!?")
        if not tok or not any(c.isalpha() for c in tok):
            continue  # pure number, already handled by _NUMERIC_RE
        preceding = text[: m.start()].rstrip()
        sentence_initial = (i == 0) or preceding.endswith(_SENTENCE_END)
        is_all_caps = tok.isupper() and len(tok) >= 2
        has_internal_cap = any(c.isupper() for c in tok[1:])
        has_tech_punct = any(c in ".+#" for c in tok)
        is_capitalized = tok[:1].isupper()
        if is_all_caps or has_internal_cap or has_tech_punct:
            facts.add(tok)
        elif is_capitalized and not sentence_initial:
            facts.add(tok)
    return facts


def validate_manifest(manifest: Manifest, bank: ResumeBank) -> list[str]:
    errors: list[str] = []

    job_ids = all_job_ids(bank)
    project_ids = all_project_ids(bank)
    achievement_ids = all_achievement_ids(bank)
    skill_ids = all_skill_ids(bank)
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

    for skill_id in manifest.skill_ids:
        if skill_id not in skill_ids:
            errors.append(f"unknown skill_id: {skill_id}")
    if len(manifest.skill_ids) != len(set(manifest.skill_ids)):
        errors.append("skill_ids must not contain duplicates")

    if set(manifest.job_trim_priority) != job_ids:
        errors.append(
            f"job_trim_priority must be exactly {sorted(job_ids)}, got {manifest.job_trim_priority}"
        )

    blob = bank_text_blob(bank)
    bank_words = _bank_word_set(bank)
    for fact in extract_facts(manifest.summary):
        is_wordlike = any(c.isalpha() for c in fact) and not any(
            c.isdigit() or c in "%" for c in fact
        )
        if is_wordlike:
            if fact.lower() not in bank_words:
                errors.append(f"untraceable fact in summary: {fact!r}")
        else:
            if fact not in blob:
                errors.append(f"untraceable fact in summary: {fact!r}")

    return errors
