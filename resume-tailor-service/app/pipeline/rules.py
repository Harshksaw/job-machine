"""Shared rule checks for sendable text (spec section 6.2).

Cover letters and form answers go out under Harsh's name, so AGENTS.md working style is
checked in code, not only asked for in a prompt: no em dashes, no hyphenated compound
words, no banned or AI sounding phrases, word limits, and a cover letter names the
company. Each check returns a list of plain error strings (empty when the text passes),
which the kit and answers steps feed back for a repair and the review step lists as
issues. Fact traceability stays in `application_kit.validate_kit`.
"""
from __future__ import annotations

import re

from app.application_kit import _BANNED_COVER_PHRASES
from app.house_style import AI_TELLS
from app.models import JobWorkspace

EM_DASH = "\u2014"
ANSWER_MAX_WORDS = 120
COVER_MIN_WORDS, COVER_MAX_WORDS = 120, 360
# Same shape as house_style: letters joined by hyphens, skipping identifier chunks
# (anything with a digit, a slash, an @ or a domain dot: H-1B, GPT-4, a/b-c).
_COMPOUND = re.compile(r"\b[A-Za-z]+(?:-[A-Za-z]+)+\b")
_IDENTIFIER = re.compile(r"\d|/|@|\.[A-Za-z]")
_BANNED = tuple(dict.fromkeys((*_BANNED_COVER_PHRASES, *AI_TELLS)))
_LEGAL_SUFFIX = re.compile(r"\s+(inc|llc|ltd|corp|co|gmbh|plc)\.?$", re.IGNORECASE)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w+.#/-]+\b", text or ""))


def em_dash_errors(text: str, label: str) -> list[str]:
    if EM_DASH in (text or ""):
        return [f"{label} contains an em dash; use a comma, period or colon"]
    return []


def hyphen_compound_errors(text: str, label: str) -> list[str]:
    found: list[str] = []
    for chunk in (text or "").split():
        if _IDENTIFIER.search(chunk):
            continue
        for match in _COMPOUND.findall(chunk):
            if match not in found:
                found.append(match)
    return [f"{label} uses hyphenated compound {word!r}; write it without the hyphen"
            for word in found]


def banned_phrase_errors(text: str, label: str) -> list[str]:
    lowered = (text or "").lower()
    return [f"{label} contains banned phrase {phrase!r}; say it plainly"
            for phrase in _BANNED if phrase in lowered]


def word_limit_errors(text: str, label: str, *, min_words: int = 0, max_words: int | None = None) -> list[str]:
    count = _word_count(text)
    if count < min_words:
        return [f"{label} must be at least {min_words} words, got {count}"]
    if max_words is not None and count > max_words:
        return [f"{label} must be at most {max_words} words, got {count}"]
    return []


def company_heads(company: str) -> set[str]:
    """The distinctive first word of each name a dossier carries for the employer
    ("Acme Cloud, Inc." -> acme; "OneClick / IXL Learning" -> oneclick, ixl)."""
    core = _LEGAL_SUFFIX.sub("", (company or "").split(",")[0].strip()).strip()
    return {
        segment.split()[0].lower()
        for segment in re.split(r"\s*[/|]\s*", core)
        if segment.split()
    }


def company_named_errors(text: str, company: str) -> list[str]:
    heads = company_heads(company)
    lowered = (text or "").lower()
    if heads and not any(head in lowered for head in heads):
        return ["cover letter must name the company"]
    return []


def sendable_errors(text: str, label: str) -> list[str]:
    return [
        *em_dash_errors(text, label),
        *hyphen_compound_errors(text, label),
        *banned_phrase_errors(text, label),
    ]


def cover_letter_errors(text: str, company: str) -> list[str]:
    return [
        *sendable_errors(text, "cover letter"),
        *word_limit_errors(text, "cover letter", min_words=COVER_MIN_WORDS, max_words=COVER_MAX_WORDS),
        *company_named_errors(text, company),
    ]


def answer_errors(text: str, *, max_words: int = ANSWER_MAX_WORDS) -> list[str]:
    return [*sendable_errors(text, "answer"), *word_limit_errors(text, "answer", max_words=max_words)]


def _issue(field: str, error: str) -> dict:
    return {"field": field, "problem": error, "fix": "rewrite to follow the AGENTS.md working style"}


def packet_issues(job: JobWorkspace) -> list[dict]:
    """Rule issues across the packet, shaped like review issues. Answers waiting on
    Harsh have no text yet and are skipped."""
    issues: list[dict] = []
    if (job.cover_letter or "").strip():
        issues += [_issue("cover_letter", e) for e in cover_letter_errors(job.cover_letter, job.company)]
    for answer in job.application_answers:
        if answer.needs_user_input or not answer.answer.strip():
            continue
        issues += [_issue(answer.question, e) for e in answer_errors(answer.answer)]
    return issues
