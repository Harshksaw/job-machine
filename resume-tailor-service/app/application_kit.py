"""Validated generation for fit analysis, cover letters, and form answers."""

from __future__ import annotations

import json
import re
from typing import Callable

from pydantic import ValidationError

from app import traceability
from app.bank import ResumeBank
from app.claude_cli import schema_completer
from app.errors import JobGenerationError
from app.models import (
    GeneratedAnswer,
    GeneratedApplicationKit,
    JobWorkspace,
)
from app.validate import extract_facts

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#/-]*")
# Generic engineering vocabulary asserts nothing about *this* candidate, so it
# is not a "fact" that needs a source. `extract_facts` treats every all-caps
# token as a credential claim, so a single incidental "UI" in an otherwise
# perfect kit failed validation and 502'd the whole request (observed live on
# 2026-08-13). Deliberately excluded: nameable skills and products such as SQL,
# HTML, CSS, JWT, SSO and RBAC. Those ARE credential claims, and they stay
# traceable so a fabricated skill is still caught.
# The traceability vocabulary and the token/compound rules now live in
# app.traceability, shared with the tailored-resume validator in app.validate.
# They had been duplicated, and the tailoring copy silently missed every fix
# made here -- rejecting "Node" while the bank says "Node.js".
_GENERIC_TECH_TERMS = traceability.GENERIC_TECH_TERMS
_FACT_STOPWORDS = traceability.FACT_STOPWORDS
_MONTH_ALIASES = traceability.MONTH_ALIASES
_TECH_ALIASES = traceability.TECH_ALIASES
_allowed_tokens = traceability.allowed_tokens
_fact_is_traceable = traceability.fact_is_traceable
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
    # `.plain`, not `.text`: the ledger is quoted into cover letters and form
    # answers, which are prose. The bank's "**...**" spans are resume-render
    # emphasis and would be copied verbatim into a letter otherwise.
    for job in bank.jobs:
        for bullet in job.bullets:
            sources[bullet.id] = (
                f"{job.company}, {job.title}, {job.dates}: {bullet.plain}"
            )
    for project in bank.projects:
        for bullet in project.bullets:
            sources[bullet.id] = (
                f"{project.name}; {project.tech}: {bullet.plain}"
            )
    for achievement in bank.achievements:
        sources[achievement.id] = achievement.plain
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


def _fact_errors(text: str, allowed_text: str, label: str) -> list[str]:
    errors: list[str] = []
    allowed_tokens = _allowed_tokens(allowed_text)
    allowed_lower = allowed_text.lower()
    for fact in extract_facts(text):
        # A trailing comma/period rides along on numeric tokens ("in 2026,"),
        # so the literal lookup missed a year the ledger really does contain.
        fact = fact.strip().rstrip(",.;:!?")
        if not fact or fact.lower() in _FACT_STOPWORDS:
            continue
        wordlike = any(char.isalpha() for char in fact) and not any(
            char.isdigit() or char == "%" for char in fact
        )
        if wordlike:
            if not _fact_is_traceable(fact, allowed_tokens):
                errors.append(f"{label} contains untraceable fact {fact!r}")
        elif not traceability.literal_fact_is_traceable(fact, allowed_lower):
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

    for index, evidence in enumerate(analysis.evidence):
        unknown = [source_id for source_id in evidence.source_ids if source_id not in sources]
        if unknown:
            errors.append(f"evidence {index} has unknown source ids: {unknown}")
        if evidence.strength != "gap" and not evidence.source_ids:
            errors.append(f"evidence {index} needs at least one source id")
        # Validate the requirement against the whole verified corpus, for the
        # same reason as `proof` below. A requirement names the technology the
        # row is about, and the model writes the canonical spelling
        # ("TypeScript", "Node.js", "PostgreSQL") even when the posting
        # abbreviates or lower-cases it -- so checking against the JD alone
        # rejected rows whose terms are demonstrably real, sitting in the
        # resume bank. Requirements describe the job, not the candidate; the
        # credential claims live in `proof`, checked below, and in the source
        # ids checked above.
        errors.extend(
            _fact_errors(
                evidence.requirement,
                allowed,
                f"evidence requirement {index}",
            )
        )
        if evidence.proof:
            # Validate proof facts against the full verified corpus (all bank
            # sources + JD + company/role context) -- the same allowlist the
            # cover letter uses -- not only the specific cited sources. A proof
            # sentence legitimately restates the JD requirement it addresses
            # ("REST APIs", "SaaS") and may reference a real bank fact recorded
            # under a sibling source id; the old narrow check flagged those
            # honest tokens as "untraceable" and 502'd every kit. Fabrication is
            # still blocked -- every fact must appear somewhere in the verified
            # corpus -- and the cited source ids are validated for existence
            # above.
            errors.extend(
                _fact_errors(
                    evidence.proof,
                    allowed,
                    f"evidence {index}",
                )
            )

    errors.extend(_fact_errors(analysis.verdict, allowed, "verdict"))
    errors.extend(_fact_errors(analysis.role_thesis, allowed, "role thesis"))
    # Gaps are deliberately NOT fact-checked. A gap states what the candidate
    # is missing ("no Jest or Cypress experience", "no IoT background"), so by
    # construction it names things absent from the resume bank -- demanding
    # traceability there is backwards, and it was rejecting honest, useful
    # admissions. The anti-fabrication rule guards against *overstating*
    # experience; an invented gap can only understate it. Real credential
    # claims still run the full check via evidence proof, verdict, role
    # thesis, positioning and the cover letter.
    for index, item in enumerate(analysis.positioning):
        errors.extend(_fact_errors(item, allowed, f"positioning {index}"))

    cover = kit.cover_letter.strip()
    if analysis.recommendation in {"apply", "review"}:
        count = _word_count(cover)
        if count < 120 or count > 360:
            errors.append(f"cover letter must be 120-360 words, got {count}")
        # Match the company's core name, not its full legal form. Requiring the
        # exact "Remarcable, Inc." string rejected cover letters that naturally
        # say "Remarcable"; strip a trailing comma-suffix and common legal
        # suffix so the human-facing name is what must appear.
        company_core = re.split(r",", job.company)[0].strip()
        company_core = re.sub(
            r"\s+(inc|llc|ltd|corp|co|gmbh|plc)\.?$",
            "",
            company_core,
            flags=re.IGNORECASE,
        ).strip()
        # A letter naturally writes "Cerebras", not "Cerebras Systems", so
        # requiring the full registered name rejected correct letters. The
        # distinctive first token is what actually names the company.
        #
        # A dossier may also carry two names for one employer, either an
        # aggregator over the real one or a rebrand ("OneClick / IXL
        # Learning"). Naming EITHER side is naming the company, so accept any
        # segment's head token rather than only the very first -- otherwise a
        # letter correctly addressed to IXL Learning was rejected for not
        # saying "OneClick".
        heads = {
            segment.split()[0].lower()
            for segment in re.split(r"\s*[/|]\s*", company_core)
            if segment.split()
        }
        if heads and not any(head in cover.lower() for head in heads):
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
   Copy names, dates, month spellings, degree names, acronyms and FIGURES
   exactly as the source ledger writes them (keep "Dec 2026" as "Dec", keep
   "Computer Information Systems" spelled out, keep "2K+" as "2K+" and never
   restyle it as "2,000+") -- do not expand, abbreviate, round, total, or coin
   an acronym or figure the ledger does not contain.
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
8. NEVER use an em-dash. Not in the cover letter, the role thesis, positioning,
   evidence, or any other field. Use a comma, a period, a colon, or restructure
   the sentence. This is a hard style rule for every string you emit.
9. NEVER state availability, a start date, a notice period, or any date that is
   not already in the ledger. The candidate's earliest start is deliberately not
   recorded, so any month or year you supply is fabricated and the traceability
   guard will reject the whole kit. Do not write "available from", "starting in",
   or a graduation-adjacent date the ledger does not contain. Say nothing about
   when the candidate can begin.
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


def _drop_unquoted_keywords(kit: GeneratedApplicationKit, job: JobWorkspace) -> None:
    """Discard keywords that are not verbatim in the JD, in place.

    A keyword is a label lifted off the posting, not a claim about the
    candidate, so a paraphrase ("TypeScript" for a JD that wrote "Typescript",
    "iOS and Android" for "iOS/Android") is cosmetic. Failing the whole kit
    over one -- and throwing away a correct analysis and cover letter with it
    -- costs far more than dropping the label. Fabrication controls are
    untouched: every candidate fact still has to trace to the source ledger.
    """
    jd_lower = job.jd_text.lower()
    kit.analysis.keywords = [
        keyword for keyword in kit.analysis.keywords
        if keyword.strip() and keyword.strip().lower() in jd_lower
    ]


def _kit_schema() -> dict:
    """`GeneratedApplicationKit`'s schema with every field this module actually
    validates marked required.

    Pydantic omits any field carrying a default from `required`, so the CLI's
    structured decoder was free to skip `cover_letter` — and did, on every
    attempt, producing kits that then failed the 120-360 word check. The same
    holds for the analysis lists `validate_kit` depends on.
    """
    schema = GeneratedApplicationKit.model_json_schema()
    schema["required"] = ["analysis", "cover_letter"]
    analysis = schema["$defs"]["FitAnalysis"]
    analysis["required"] = [
        "score", "recommendation", "verdict", "role_thesis",
        "keywords", "evidence", "gaps", "positioning",
    ]
    analysis["properties"]["evidence"]["minItems"] = 3  # validate_kit's floor
    return schema


def generate_kit(
    job: JobWorkspace,
    bank: ResumeBank,
    *,
    complete: Callable[[str], str] = schema_completer(_kit_schema()),
    # Validation failures are one-off word choices, not systematic: the
    # correction loop feeds the exact errors back and the next draft almost
    # always clears them. Two attempts left honest kits failing on a single
    # stray token; a third costs ~90s only in the rare case it is needed.
    max_retries: int = 2,
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
        _drop_unquoted_keywords(kit, job)
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


def _answer_schema() -> dict:
    """`GeneratedAnswer` declares no required fields at all, so structured
    decoding could satisfy it with `{}`. Demand the two that carry meaning."""
    schema = GeneratedAnswer.model_json_schema()
    schema["required"] = ["answer", "source_ids"]
    return schema


def generate_answer(
    job: JobWorkspace,
    bank: ResumeBank,
    question: str,
    constraints: str = "",
    *,
    complete: Callable[[str], str] = schema_completer(_answer_schema()),
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
