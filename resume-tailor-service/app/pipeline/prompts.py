"""Prompt templates for agent steps.

Each agent step has `prompts/<step>.md`, written for any agent: no tool or vendor names.
Placeholders are `{{name}}`, filled from the dossier, the run, prior step outputs and the
resume bank ledger, then from `extra`, which wins. Adapters render the prompt and append
their own output footer (spec section 5.1).

The version is the first 12 hex characters of sha256 over the template source, so the
attempt ledger can compare prompt versions across jobs.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.bank import load_bank
from app.pipeline.runner import StepContext

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
BANK_PATH = Path(__file__).resolve().parents[2] / "content" / "resume_bank.yaml"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


def template_source(step_name: str) -> str:
    if not re.fullmatch(r"[a-z_]+", step_name):
        raise FileNotFoundError(f"no prompt template for step {step_name!r}")
    path = PROMPT_DIR / f"{step_name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"no prompt template for step {step_name!r}")
    return path.read_text(encoding="utf-8")


def version(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]


def _ledger() -> str:
    from app.application_kit import build_source_index

    sources = build_source_index(load_bank(BANK_PATH))
    return "\n".join(f"- {source_id}: {text}" for source_id, text in sources.items())


def _or_none(text: object) -> str:
    value = str(text or "").strip()
    return value or "(none)"


def _values(ctx: StepContext) -> dict[str, object]:
    job = ctx.job
    if job is None:
        # A task run (mail sync) has no dossier: only the run and step outputs.
        return {
            "run_id": ctx.run.id,
            "outputs": json.dumps(ctx.outputs, indent=2, sort_keys=True, default=str),
        }
    fields = [
        f"- {field.label} [{field.kind}{', required' if field.required else ''}]"
        + (f" options: {', '.join(field.options)}" if field.options else "")
        for field in job.form_fields
    ]
    answers = [
        f"- Q: {answer.question}\n  A: "
        + ("(needs the candidate)" if answer.needs_user_input else _or_none(answer.answer))
        for answer in job.application_answers
    ]
    return {
        "run_id": ctx.run.id,
        "company": job.company,
        "role": job.role,
        "location": _or_none(job.location),
        "work_mode": _or_none(job.work_mode),
        "compensation": _or_none(job.compensation),
        "job_url": _or_none(job.job_url),
        "apply_url": _or_none(job.apply_url),
        "jd_text": _or_none(job.jd_text),
        "notes": _or_none(job.notes),
        "fit_score": _or_none(job.fit_score),
        "company_context": _or_none(job.company_context),
        "why_this_role": _or_none(job.why_this_role),
        "cover_letter": _or_none(job.cover_letter),
        "form_fields": "\n".join(fields) or "(none read)",
        "answers": "\n".join(answers) or "(none)",
        "outputs": json.dumps(ctx.outputs, indent=2, sort_keys=True, default=str),
    }


def render(step_name: str, ctx: StepContext, extra: dict | None = None) -> tuple[str, str]:
    source = template_source(step_name)
    values = {**_values(ctx), **(extra or {})}
    names = set(_PLACEHOLDER.findall(source))
    if "ledger" in names and "ledger" not in values:
        values["ledger"] = _ledger()
    missing = sorted(names - set(values))
    if missing:
        raise KeyError(f"prompt {step_name} has unknown placeholders: {', '.join(missing)}")
    text = _PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), source)
    return text, version(source)
