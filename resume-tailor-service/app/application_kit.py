"""Validated generation for fit analysis, cover letters, and form answers."""

from __future__ import annotations

import json
import re
from typing import Callable

from pydantic import ValidationError

from app.bank import ResumeBank
from app.claude_cli import run_claude
from app.errors import JobGenerationError
from app.models import (
    GeneratedAnswer,
    GeneratedApplicationKit,
    JobWorkspace,
)
from app.validate import extract_facts

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*")
_FACT_STOPWORDS = {"i"}
_BANNED_COVER_PHRASES = (
    "i am writing to apply",
    "i believe i would be a great fit",
    "passionate about",
    "esteemed company",
    "dynamic team",
    "perfect fit",
    "dream job",
)
_JUDGMENT_QUESTION_PATTERNS = (
    "salary",
    "compensation",
    "desired pay",
    "expected pay",
    "pay expectation",
    "pay range",
    "expected rate",
    "hourly rate",
    "sponsorship",
    "sponsor",
    "visa",
    "authorized to work",
    "work authorization",
    "employment authorization",
    "legally eligible",
    "right to work",
    "work permit",
    "immigration",
    "citizenship",
    "ethnicity",
    "race",
    "gender",
    "disability",
    "veteran",
    "criminal",
    "background check",
    "security clearance",
    "start date",
    "earliest start",
    "date available",
    "notice period",
    "age",
    "18 years",
    "driver's license",
    "driver licence",
    "willing to travel",
)


def _source_slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", ".", text.lower()).strip(".")
    return value or "entry"


def build_source_index(bank: ResumeBank) -> dict[str, str]:
    sources = {
        "profile.name": bank.contact.name,
        "profile.education": (
            f"{bank.education.degree}, {bank.education.school}, {bank.education.date}"
        ),
        "profile.location": bank.contact.location,
    }
    for job in bank.jobs:
        for bullet in job.bullets:
            sources[bullet.id] = (
                f"{job.company}, {job.title}, {job.dates}: {bullet.text}"
            )
    for project in bank.projects:
        for bullet in project.bullets:
            sources[bullet.id] = (
                f"{project.name}; {project.tech}: {bullet.text}"
            )
    for achievement in bank.achievements:
        sources[achievement.id] = achievement.text
    for skill in bank.skills:
        source_id = skill.id or f"skill.{_source_slug(skill.category)}"
        sources[source_id] = (
            f"{skill.category}: {skill.items}"
        )
    for fact in bank.profile_facts:
        sources[fact.id] = fact.text
    return sources


def _describe_sources(sources: dict[str, str]) -> str:
    return "\n".join(f"- {source_id}: {text}" for source_id, text in sources.items())


def _parse_json(raw_text: str) -> dict:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("response must be a JSON object")
    return parsed


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w+.#/-]+\b", text))


def _allowed_tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _fact_errors(text: str, allowed_text: str, label: str) -> list[str]:
    errors: list[str] = []
    allowed_tokens = _allowed_tokens(allowed_text)
    allowed_lower = allowed_text.lower()
    for fact in extract_facts(text):
        if fact.lower() in _FACT_STOPWORDS:
            continue
        wordlike = any(char.isalpha() for char in fact) and not any(
            char.isdigit() or char == "%" for char in fact
        )
        if wordlike:
            if fact.lower() not in allowed_tokens:
                errors.append(f"{label} contains untraceable fact {fact!r}")
        elif fact.lower() not in allowed_lower:
            errors.append(f"{label} contains untraceable fact {fact!r}")
    return errors


def validate_kit(
    kit: GeneratedApplicationKit,
    job: JobWorkspace,
    sources: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    analysis = kit.analysis
    expected_recommendation = "apply" if analysis.score >= 6 else "review"
    if analysis.recommendation != expected_recommendation:
        errors.append(
            "score 6+ must recommend apply; score below 6 must recommend review"
        )
    if len(analysis.evidence) < 3:
        errors.append("analysis must include at least three requirement rows")

    jd_lower = job.jd_text.lower()
    for keyword in analysis.keywords:
        if keyword.strip() and keyword.strip().lower() not in jd_lower:
            errors.append(f"keyword is not present in the job description: {keyword!r}")

    for index, evidence in enumerate(analysis.evidence):
        unknown = [source_id for source_id in evidence.source_ids if source_id not in sources]
        if unknown:
            errors.append(f"evidence {index} has unknown source ids: {unknown}")
        if evidence.strength != "gap" and not evidence.source_ids:
            errors.append(f"evidence {index} needs at least one source id")
        errors.extend(
            _fact_errors(
                evidence.requirement,
                job.jd_text,
                f"evidence requirement {index}",
            )
        )
        selected_text = " ".join(
            sources[source_id]
            for source_id in evidence.source_ids
            if source_id in sources
        )
        if evidence.proof:
            errors.extend(
                _fact_errors(
                    evidence.proof,
                    selected_text,
                    f"evidence {index}",
                )
            )

    allowed = " ".join(
        [
            *sources.values(),
            job.company,
            job.role,
            job.jd_text,
            job.company_context,
            job.why_this_role,
        ]
    )
    errors.extend(_fact_errors(analysis.verdict, allowed, "verdict"))
    errors.extend(_fact_errors(analysis.role_thesis, allowed, "role thesis"))
    for index, gap in enumerate(analysis.gaps):
        errors.extend(_fact_errors(gap, allowed, f"gap {index}"))
    for index, item in enumerate(analysis.positioning):
        errors.extend(_fact_errors(item, allowed, f"positioning {index}"))

    cover = kit.cover_letter.strip()
    if analysis.recommendation in {"apply", "review"}:
        count = _word_count(cover)
        if count < 120 or count > 360:
            errors.append(f"cover letter must be 120-360 words, got {count}")
        if job.company.lower() not in cover.lower():
            errors.append("cover letter must name the company")
    if cover:
        lowered = cover.lower()
        for phrase in _BANNED_COVER_PHRASES:
            if phrase in lowered:
                errors.append(f"cover letter contains banned phrase {phrase!r}")
        if "[" in cover or "]" in cover:
            errors.append("cover letter contains an unresolved placeholder")
        errors.extend(_fact_errors(cover, allowed, "cover letter"))
    return errors


def _kit_prompt(
    job: JobWorkspace,
    sources: dict[str, str],
    previous_errors: list[str] | None = None,
) -> str:
    correction = ""
    if previous_errors:
        correction = (
            "\nThe previous draft failed validation:\n"
            + "\n".join(f"- {error}" for error in previous_errors)
            + "\nReturn a corrected JSON object.\n"
        )
    return f"""Build a rigorous application kit for one real candidate and one job.

Company: {job.company}
Role: {job.role}
Company research/context:
{job.company_context or "(none saved)"}
Candidate's genuine reason for this role:
{job.why_this_role or "(not yet saved)"}
Job description:
{job.jd_text}

Candidate source ledger (the ONLY allowed candidate facts):
{_describe_sources(sources)}

Rules:
1. Never invent experience, skills, dates, numbers, education, authorization,
   preferences, or company facts. Candidate proof must cite source_ids above.
2. Score fit from 1-10. Below 6 => "review"; 6 or above => "apply".
   "review" means keep the opportunity active so the user can improve or
   reconsider it later. Never recommend "skip" automatically.
3. Evidence rows map important JD requirements to concise proof. Use strength
   "strong", "partial", or "gap". A gap has no source_ids.
4. keywords must be exact phrases found in the JD.
5. positioning is a short action list for this specific application.
6. For both "apply" and "review", write a 120-360 word cover letter in 3-5 short
   paragraphs. Start with a specific company/product/role observation, connect
   2-3 cited real accomplishments, acknowledge a material gap when useful, and
   close directly. Sound like one engineer writing to another. No generic
   enthusiasm, flattery, placeholders, "passionate", or "I am writing to apply".
7. A low score must not delete, archive, or skip the dossier.
{correction}
Return ONLY JSON in this exact shape:
{{
  "analysis": {{
    "score": 8,
    "recommendation": "apply",
    "verdict": "one direct sentence",
    "role_thesis": "the candidate's strongest honest positioning",
    "keywords": ["exact JD phrase"],
    "evidence": [
      {{
        "requirement": "important JD requirement",
        "strength": "strong",
        "proof": "concise candidate proof",
        "source_ids": ["exact.source.id"]
      }}
    ],
    "gaps": ["material gap stated plainly"],
    "positioning": ["specific application tactic"]
  }},
  "cover_letter": "plain text paragraphs separated by newlines"
}}"""


def generate_kit(
    job: JobWorkspace,
    bank: ResumeBank,
    *,
    complete: Callable[[str], str] = run_claude,
    max_retries: int = 1,
) -> GeneratedApplicationKit:
    if len(job.jd_text.strip()) < 80:
        raise JobGenerationError(
            "save a complete job description (at least 80 characters) first"
        )
    sources = build_source_index(bank)
    previous_errors: list[str] | None = None
    attempts = max_retries + 1
    for _ in range(attempts):
        raw_text = complete(_kit_prompt(job, sources, previous_errors))
        try:
            kit = GeneratedApplicationKit.model_validate(_parse_json(raw_text))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            previous_errors = [f"response did not match the required JSON schema: {exc}"]
            continue
        errors = validate_kit(kit, job, sources)
        if not errors:
            return kit
        previous_errors = errors
    raise JobGenerationError(
        f"application kit invalid after {attempts} attempt(s): {previous_errors}"
    )


def _judgment_clarification(question: str) -> str | None:
    lowered = question.lower()
    matched = next(
        (pattern for pattern in _JUDGMENT_QUESTION_PATTERNS if pattern in lowered),
        None,
    )
    if matched is None:
        return None
    return (
        f"This asks about {matched}, which is not established in the verified "
        "candidate facts. Confirm the exact response before submitting."
    )


def _answer_prompt(
    job: JobWorkspace,
    question: str,
    constraints: str,
    sources: dict[str, str],
    previous_errors: list[str] | None = None,
) -> str:
    correction = ""
    if previous_errors:
        correction = (
            "\nThe previous answer failed validation:\n"
            + "\n".join(f"- {error}" for error in previous_errors)
            + "\nCorrect it.\n"
        )
    return f"""Draft one truthful application-form answer.

Company: {job.company}
Role: {job.role}
Job description:
{job.jd_text}
Question:
{question}
Constraints from the form/user:
{constraints or "(none)"}

Verified candidate sources:
{_describe_sources(sources)}

Use only verified candidate facts and relevant company/JD context. Answer the
question immediately, then support it with the smallest useful amount of
specific evidence. Do not add a greeting or sign-off. Do not invent. Cite every
candidate claim through source_ids. If a truthful answer requires an unknown
personal preference or decision, set needs_user_input=true, leave answer empty,
and state exactly what must be confirmed.
{correction}
Return ONLY JSON:
{{
  "answer": "direct answer or empty when user input is required",
  "source_ids": ["exact.source.id"],
  "needs_user_input": false,
  "clarification": ""
}}"""


def validate_answer(
    answer: GeneratedAnswer,
    job: JobWorkspace,
    sources: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    unknown = [source_id for source_id in answer.source_ids if source_id not in sources]
    if unknown:
        errors.append(f"answer has unknown source ids: {unknown}")
    if answer.needs_user_input:
        if answer.answer.strip():
            errors.append("answer must be empty when user input is required")
        if not answer.clarification.strip():
            errors.append("clarification is required when user input is required")
        return errors
    if not answer.answer.strip():
        errors.append("answer must not be empty")
    if not answer.source_ids:
        errors.append("answer must cite at least one candidate source")
    if "[" in answer.answer or "]" in answer.answer:
        errors.append("answer contains an unresolved placeholder")
    allowed = " ".join(
        [
            *(sources[source_id] for source_id in answer.source_ids if source_id in sources),
            job.company,
            job.role,
            job.jd_text,
            job.company_context,
        ]
    )
    errors.extend(_fact_errors(answer.answer, allowed, "answer"))
    return errors


def generate_answer(
    job: JobWorkspace,
    bank: ResumeBank,
    question: str,
    constraints: str = "",
    *,
    complete: Callable[[str], str] = run_claude,
    max_retries: int = 1,
) -> GeneratedAnswer:
    clarification = _judgment_clarification(question)
    if clarification is not None:
        return GeneratedAnswer(
            needs_user_input=True,
            clarification=clarification,
        )

    sources = build_source_index(bank)
    previous_errors: list[str] | None = None
    attempts = max_retries + 1
    for _ in range(attempts):
        raw_text = complete(
            _answer_prompt(job, question, constraints, sources, previous_errors)
        )
        try:
            answer = GeneratedAnswer.model_validate(_parse_json(raw_text))
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            previous_errors = [f"response did not match the required JSON schema: {exc}"]
            continue
        errors = validate_answer(answer, job, sources)
        if not errors:
            return answer
        previous_errors = errors
    raise JobGenerationError(
        f"application answer invalid after {attempts} attempt(s): {previous_errors}"
    )
