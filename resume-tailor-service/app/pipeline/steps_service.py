"""Service steps of the packet pipeline: the kit and the form answers.

Both wrap the validated generators in `app.application_kit` and add the repair loop of
spec section 6.3: a draft that fails validation is retried once with the errors fed
back, then the step fails with those errors (before, generation failed silently). The
shared rules in `rules.py` run on top as a safety net and get the same single repair.

The model call goes through `llm.complete` (the agent router, spec 13.1) with this
run's id, and the adapters that wrote the output are kept in `output["meta"]["authors"]`
so the review step can run on a different one (spec 6.4). Tests and callers can pass
their own `complete`.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md sections 4 and 6.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Callable

from app import llm
from app.application_kit import _answer_schema, _judgment_clarification, _kit_schema, generate_answer, generate_kit
from app.bank import load_bank
from app.errors import JobGenerationError
from app.models import ApplicationAnswer, FormField, GeneratedAnswer
from app.pipeline.models import now_iso
from app.pipeline import rules
from app.pipeline.runner import RunCancelled, StepContext, StepFailed, StepResult, StepSpec
from app.pipeline.steps_agent import FIT_FLOOR

BANK_PATH = Path(__file__).resolve().parents[2] / "content" / "resume_bank.yaml"
Complete = Callable[[str], str]

# One repair: the generator's first draft plus one retry with the errors.
_REPAIRS = 1


def _model(ctx: StepContext, complete: Complete | None, step: str, schema: dict) -> Complete:
    """The caller's `complete`, else one routed session for this step of this run."""
    if complete is not None:
        return complete
    return llm.Session("reason", schema, step=step, run_id=ctx.run.id, job_id=ctx.run.job_id, cancel=ctx.check)


def _next_adapter(model) -> bool:
    """After a draft failed on one adapter, move the step to the next one (spec 5.3)."""
    return isinstance(model, llm.Session) and model.drop_last()


def _meta(model) -> dict:
    return {"authors": list(getattr(model, "authors", []))}


def _bank(path: Path | None):
    return load_bank(path or BANK_PATH)


# kit


def _draft_kit(ctx: StepContext, bank, complete: Complete, issues: list[str] | None = None):
    """generate_kit with one validation repair, then the shared rules with one more,
    on each adapter in turn. Raises StepFailed with the errors when the draft still
    fails on the last one."""
    while True:
        try:
            generated = generate_kit(ctx.job, bank, max_retries=_REPAIRS, previous_errors=issues,
                                     complete=complete)
            errors = rules.cover_letter_errors(generated.cover_letter, ctx.job.company)
            if errors:
                generated = generate_kit(ctx.job, bank, max_retries=0, previous_errors=errors,
                                         complete=complete)
                errors = rules.cover_letter_errors(generated.cover_letter, ctx.job.company)
        except JobGenerationError as exc:
            if _next_adapter(complete):
                continue
            raise StepFailed(str(exc)) from exc
        if errors and _next_adapter(complete):
            continue
        break
    if errors:
        raise StepFailed(f"cover letter failed the shared rules after one repair: {errors}")
    return generated


def _pinned(analysis, ctx: StepContext):
    """fit_score is the gate (rule 2). Writing fit_analysis also sets fit_score from its
    score, so the kit's own score must not move it."""
    fit = (ctx.outputs.get("fit_score") or {}).get("score")
    if isinstance(fit, int) and fit != analysis.score:
        return analysis.model_copy(update={
            "score": fit, "recommendation": "apply" if fit >= FIT_FLOOR else "review",
        })
    return analysis


def kit_step(complete: Complete | None = None, *, bank_path: Path | None = None,
             deps: tuple[str, ...] = ()) -> StepSpec:
    def kit(ctx: StepContext) -> StepResult:
        model = _model(ctx, complete, "kit", _kit_schema())
        generated = _draft_kit(ctx, _bank(bank_path), model)
        analysis = _pinned(generated.analysis, ctx)
        writes: dict = {"fit_analysis": analysis.model_dump()}
        # Owner ruling: a letter already on the dossier may be hand edited, so it
        # survives; only the analysis is refreshed.
        keep = bool((ctx.job.cover_letter or "").strip())
        if not keep:
            writes["cover_letter"] = generated.cover_letter
        return StepResult(
            output={"kit_score": generated.analysis.score, "score": analysis.score,
                    "cover_letter": "kept existing cover letter" if keep else "generated",
                    "wrote_letter": not keep,
                    "words": len((ctx.job.cover_letter if keep else generated.cover_letter).split()),
                    "meta": _meta(model)},
            writes=writes,
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


def _answer(ctx: StepContext, bank, question: str, complete: Complete,
            issues: list[str] | None = None):
    """Like _draft_kit: one repair per adapter, then the next adapter. An adapter that
    failed a whole answer sits out the rest of this step."""
    while True:
        try:
            draft = generate_answer(ctx.job, bank, question, ANSWER_CONSTRAINTS,
                                    max_retries=_REPAIRS, previous_errors=issues, complete=complete)
            errors = [] if draft.needs_user_input else rules.answer_errors(draft.answer)
            if errors:
                draft = generate_answer(ctx.job, bank, question, ANSWER_CONSTRAINTS,
                                        max_retries=0, previous_errors=errors, complete=complete)
                errors = [] if draft.needs_user_input else rules.answer_errors(draft.answer)
        except JobGenerationError as exc:
            if _next_adapter(complete):
                continue
            raise StepFailed(f"answer for {question!r}: {exc}") from exc
        if errors and _next_adapter(complete):
            continue
        break
    if errors:
        raise StepFailed(f"answer for {question!r} failed the shared rules after one repair: {errors}")
    return draft


def answers_step(complete: Complete | None = None, *, bank_path: Path | None = None,
                 deps: tuple[str, ...] = ()) -> StepSpec:
    def answers(ctx: StepContext) -> StepResult:
        existing = {_key(a.question) for a in ctx.job.application_answers}
        new: list[ApplicationAnswer] = []
        skipped: list[dict] = []
        needs: list[str] = []
        bank = None
        model = _model(ctx, complete, "answers", _answer_schema())
        for field in ctx.job.form_fields:
            ctx.check()  # a cancel, shutdown or lost lease stops before the next field
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
                draft = _answer(ctx, bank, field.label, model)
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
        output = {"answered": len(new) - len(needs), "needs_user_input": needs, "skipped": skipped,
                  "meta": _meta(model)}
        if not new:
            return StepResult(output=output)
        answers_out = [a.model_dump() for a in (*ctx.job.application_answers, *new)]
        return StepResult(output=output, writes={"application_answers": answers_out})

    return StepSpec("answers", "service", deps=deps, owns=("application_answers",),
                    capability="reason", run=answers)


# repair (spec 6.4)


def _issue_text(issue: dict) -> str:
    text = f"Review: {issue.get('problem', '')}".strip()
    return text + (f" Fix: {issue['fix']}" if issue.get("fix") else "")


def repair_step(complete_kit: Complete | None = None, complete_answer: Complete | None = None, *,
                bank_path: Path | None = None, deps: tuple[str, ...] = ()) -> StepSpec:
    """One repair round on what a failing review flagged: the cover letter, or a drafted
    answer by its question, regenerated once with the review issues fed back. There is
    no second review, so the review stays failed and its issues stay under NEEDS HARSH;
    a repair that still fails validation keeps the old text and the run goes on."""

    def repair(ctx: StepContext) -> StepResult:
        review = ctx.outputs.get("review") or {}
        repaired: list[str] = []
        unrepaired: list[str] = []
        if review.get("pass") is not False:
            return StepResult(output={"repaired": repaired, "unrepaired": unrepaired})
        by_field: dict[str, list[str]] = {}
        for issue in review.get("issues") or []:
            if isinstance(issue, dict) and str(issue.get("field") or "").strip():
                by_field.setdefault(str(issue["field"]).strip(), []).append(_issue_text(issue))
        bank = _bank(bank_path)
        writes: dict = {}
        answers = list(ctx.job.application_answers)
        kit_model = _model(ctx, complete_kit, "repair", _kit_schema())
        answer_model = _model(ctx, complete_answer, "repair", _answer_schema())
        for field, issues in by_field.items():
            ctx.check()
            try:
                if field == "cover_letter":
                    # Only a letter the kit step wrote in this run; never a letter that
                    # was already on the dossier (it may be hand edited).
                    if not (ctx.outputs.get("kit") or {}).get("wrote_letter"):
                        unrepaired.append(field)
                        continue
                    generated = _draft_kit(ctx, bank, kit_model, issues)
                    writes["fit_analysis"] = _pinned(generated.analysis, ctx).model_dump()
                    writes["cover_letter"] = generated.cover_letter
                    repaired.append(field)
                    continue
                index = next((i for i, a in enumerate(answers)
                              if _key(a.question) == _key(field) and not a.needs_user_input), None)
                if index is None:
                    unrepaired.append(field)
                    continue
                draft = _answer(ctx, bank, answers[index].question, answer_model, issues)
                answers[index] = answers[index].model_copy(update={
                    "answer": draft.answer, "source_ids": draft.source_ids,
                    "needs_user_input": draft.needs_user_input,
                    "clarification": draft.clarification, "updated_at": now_iso(),
                })
                writes["application_answers"] = [a.model_dump() for a in answers]
                repaired.append(field)
            except RunCancelled:
                raise
            except StepFailed:
                unrepaired.append(field)
        return StepResult(output={"repaired": repaired, "unrepaired": unrepaired}, writes=writes)

    return StepSpec("repair", "service", deps=deps,
                    owns=("fit_analysis", "cover_letter", "application_answers"),
                    capability="reason", run=repair)
