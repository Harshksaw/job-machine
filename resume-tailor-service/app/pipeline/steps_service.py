"""Service steps of the packet pipeline: the kit and the form answers.

Both wrap the validated generators in `app.application_kit` and add the repair loop of
spec section 6.3: a draft that fails validation is retried once with the errors fed
back, then the step fails with those errors (before, generation failed silently). The
shared rules in `rules.py` run on top as a safety net and get the same single repair.

The model call is still `claude_cli` through the generators' default `complete`
(M2b moves it behind the router); tests and callers can pass their own `complete`.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md sections 4 and 6.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Callable

from app.application_kit import _judgment_clarification, generate_answer, generate_kit
from app.bank import load_bank
from app.errors import JobGenerationError
from app.models import ApplicationAnswer, FormField, GeneratedAnswer
from app.pipeline.models import now_iso
from app.pipeline import rules
from app.pipeline.runner import StepContext, StepFailed, StepResult, StepSpec
from app.pipeline.steps_agent import FIT_FLOOR

BANK_PATH = Path(__file__).resolve().parents[2] / "content" / "resume_bank.yaml"
Complete = Callable[[str], str]

# One repair: the generator's first draft plus one retry with the errors.
_REPAIRS = 1


def _kw(complete: Complete | None) -> dict:
    return {"complete": complete} if complete is not None else {}


def _bank(path: Path | None):
    return load_bank(path or BANK_PATH)


# kit


def kit_step(complete: Complete | None = None, *, bank_path: Path | None = None,
             deps: tuple[str, ...] = ()) -> StepSpec:
    def kit(ctx: StepContext) -> StepResult:
        bank = _bank(bank_path)
        try:
            generated = generate_kit(ctx.job, bank, max_retries=_REPAIRS, **_kw(complete))
            errors = rules.cover_letter_errors(generated.cover_letter, ctx.job.company)
            if errors:
                generated = generate_kit(ctx.job, bank, max_retries=0, previous_errors=errors,
                                         **_kw(complete))
                errors = rules.cover_letter_errors(generated.cover_letter, ctx.job.company)
        except JobGenerationError as exc:
            raise StepFailed(str(exc)) from exc
        if errors:
            raise StepFailed(f"cover letter failed the shared rules after one repair: {errors}")
        analysis = generated.analysis
        kit_score = analysis.score
        fit = (ctx.outputs.get("fit_score") or {}).get("score")
        if isinstance(fit, int) and fit != analysis.score:
            # fit_score is the gate (rule 2). Writing fit_analysis also sets fit_score
            # from its score, so the kit's own score must not move it.
            analysis = analysis.model_copy(update={
                "score": fit, "recommendation": "apply" if fit >= FIT_FLOOR else "review",
            })
        return StepResult(
            output={"kit_score": kit_score, "score": analysis.score,
                    "words": len(generated.cover_letter.split())},
            writes={"fit_analysis": analysis.model_dump(), "cover_letter": generated.cover_letter},
        )

    return StepSpec("kit", "service", deps=deps, owns=("fit_analysis", "cover_letter"),
                    capability="reason", run=kit)


# answers

# Harsh's casual voice for form answers (AGENTS.md working style, 2026-11-24).
ANSWER_CONSTRAINTS = (
    f"Under {rules.ANSWER_MAX_WORDS} words. First person, plain, casual and short, like a "
    "person typing a quick reply. Pick one or two real facts, not a tour of the resume. "
    "No em dashes, no hyphenated compound words, no buzzwords, no tidy three part lists, "
    "no opener like I am excited to."
)
_FREE_TEXT = frozenset({"text", "textarea"})
# Fields filled from docs/PERSONAL-ANSWERS.md or the resume, never drafted.
_PERSONAL_KINDS = frozenset({"email", "phone", "url", "file"})
_PERSONAL_LABEL = re.compile(
    r"\b(name|e-?mail|phone|mobile|address|street|city|province|state|zip|postal|country|"
    r"location|located|linkedin|github|website|portfolio|resume|cv|cover letter|pronouns?)\b",
    re.IGNORECASE,
)
# A label longer than this is a question, not a personal value ("Tell us about a
# project you built (GitHub link optional)").
_PERSONAL_MAX_WORDS = 6


def _personal(field: FormField) -> bool:
    if field.kind in _PERSONAL_KINDS:
        return True
    return len(field.label.split()) <= _PERSONAL_MAX_WORDS and bool(_PERSONAL_LABEL.search(field.label))


def _choice_note(field: FormField) -> str:
    options = f" Options: {', '.join(field.options)}." if field.options else ""
    required = " Required." if field.required else ""
    return f"Pick the {field.kind} value yourself from PERSONAL-ANSWERS.md or your own call.{options}{required}"


def _key(question: str) -> str:
    return " ".join(question.lower().split())


def _answer(ctx: StepContext, bank, field: FormField, complete: Complete | None):
    try:
        draft = generate_answer(ctx.job, bank, field.label, ANSWER_CONSTRAINTS,
                                max_retries=_REPAIRS, **_kw(complete))
        errors = [] if draft.needs_user_input else rules.answer_errors(draft.answer)
        if errors:
            draft = generate_answer(ctx.job, bank, field.label, ANSWER_CONSTRAINTS,
                                    max_retries=0, previous_errors=errors, **_kw(complete))
            errors = [] if draft.needs_user_input else rules.answer_errors(draft.answer)
    except JobGenerationError as exc:
        raise StepFailed(f"answer for {field.label!r}: {exc}") from exc
    if errors:
        raise StepFailed(f"answer for {field.label!r} failed the shared rules after one repair: {errors}")
    return draft


def answers_step(complete: Complete | None = None, *, bank_path: Path | None = None,
                 deps: tuple[str, ...] = ()) -> StepSpec:
    def answers(ctx: StepContext) -> StepResult:
        existing = {_key(a.question) for a in ctx.job.application_answers}
        new: list[ApplicationAnswer] = []
        skipped: list[dict] = []
        needs: list[str] = []
        bank = None
        for field in ctx.job.form_fields:
            if _key(field.label) in existing:
                skipped.append({"label": field.label, "why": "already answered"})
                continue
            judgment = _judgment_clarification(field.label) is not None
            if not judgment and _personal(field):
                skipped.append({"label": field.label, "why": "personal value, from PERSONAL-ANSWERS.md"})
                continue
            if not judgment and field.kind not in _FREE_TEXT:
                # A choice, date or number field is a decision, not something to draft.
                # Never skip it silently (rule 5): it waits for Harsh with its options.
                draft = GeneratedAnswer(needs_user_input=True, clarification=_choice_note(field))
            else:
                bank = bank or _bank(bank_path)
                draft = _answer(ctx, bank, field, complete)
            if draft.needs_user_input:
                needs.append(field.label)
            stamp = now_iso()
            new.append(ApplicationAnswer(
                id=uuid.uuid4().hex, created_at=stamp, updated_at=stamp,
                question=field.label, answer=draft.answer, constraints=ANSWER_CONSTRAINTS,
                source_ids=draft.source_ids, needs_user_input=draft.needs_user_input,
                clarification=draft.clarification,
            ))
            existing.add(_key(field.label))
        output = {"answered": len(new) - len(needs), "needs_user_input": needs, "skipped": skipped}
        if not new:
            return StepResult(output=output)
        answers_out = [a.model_dump() for a in (*ctx.job.application_answers, *new)]
        return StepResult(output=output, writes={"application_answers": answers_out})

    return StepSpec("answers", "service", deps=deps, owns=("application_answers",),
                    capability="reason", run=answers)
