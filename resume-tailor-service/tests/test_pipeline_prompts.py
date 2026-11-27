"""Prompt templates for agent steps: rendering, versions, and agent neutral wording."""
import hashlib
import re

import pytest

from app.models import ApplicationAnswer, FormField, JobWorkspace
from app.pipeline import prompts
from app.pipeline.models import Run, StepState
from app.pipeline.runner import StepContext

_REAL_LEDGER = prompts._ledger
AGENT_STEPS = ("eligibility", "fit_score", "company_context", "form_fields", "people", "review")
# No agent tool or model vendor in a template: any adapter must be able to run it.
VENDORS = ("claude", "codex", "cursor", "gemini", "opencode", "antigravity", "agy",
           "openai", "anthropic", "gpt", "openrouter", "ollama", "haiku", "sonnet", "opus")


def _ctx(**job_fields):
    job_fields.setdefault("company", "Acme")
    job_fields.setdefault("role", "Backend Engineer")
    job = JobWorkspace(id="j1", created_at="t", updated_at="t", **job_fields)
    run = Run(id="r1", job_id="j1", pipeline="packet", order=["claim"],
              steps={"claim": StepState()}, created_at="t", updated_at="t")
    return StepContext(run=run, job=job, outputs={"fit_score": {"score": 8}})


@pytest.fixture(autouse=True)
def tiny_bank(monkeypatch):
    monkeypatch.setattr(prompts, "_ledger", lambda: "- acme.bullet.1: Built a widget pipeline.")


@pytest.mark.parametrize("step", AGENT_STEPS)
def test_every_agent_step_has_a_template_that_renders(step):
    text, version = prompts.render(step, _ctx(jd_text="Build APIs in Python."), {})
    assert "{{" not in text and "}}" not in text
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    assert "Acme" in text


@pytest.mark.parametrize("step", AGENT_STEPS)
def test_templates_name_no_agent_tool_or_vendor(step):
    source = prompts.template_source(step).lower()
    found = [v for v in VENDORS if re.search(rf"\b{v}\b", source)]
    assert found == []


@pytest.mark.parametrize("step", AGENT_STEPS)
def test_templates_follow_house_style(step):
    source = prompts.template_source(step)
    assert "—" not in source


def test_version_is_the_hash_of_the_template_source_not_the_job():
    a = prompts.render("eligibility", _ctx(company="Acme"), {})[1]
    b = prompts.render("eligibility", _ctx(company="Other Co"), {})[1]
    expected = hashlib.sha256(prompts.template_source("eligibility").encode()).hexdigest()[:12]
    assert a == b == expected


def test_render_fills_job_fields_outputs_and_extra():
    ctx = _ctx(jd_text="Ship Python services.", notes="older note")
    text, _ = prompts.render("fit_score", ctx, {})
    assert "Ship Python services." in text
    assert "acme.bullet.1" in text
    text, _ = prompts.render("eligibility", ctx, {"jd_text": "Overridden JD"})
    assert "Overridden JD" in text and "Ship Python services." not in text


def test_form_fields_prompt_carries_the_read_only_browser_rules():
    text, _ = prompts.render("form_fields", _ctx(apply_url="https://jobs.example.com/x"), {})
    assert "pipeline r1 form" in text
    assert "https://jobs.example.com/x" in text
    lowered = text.lower()
    for rule in ("never type", "sign in", "submit", "captcha", "close"):
        assert rule in lowered


def test_review_prompt_lists_the_packet():
    answer = ApplicationAnswer(id="a1", question="Why us?", answer="Short reply.",
                               created_at="t", updated_at="t")
    ctx = _ctx(cover_letter="Dear Acme team", application_answers=[answer],
               form_fields=[FormField(label="Why us?", kind="textarea", required=True)])
    text, _ = prompts.render("review", ctx, {})
    assert "Dear Acme team" in text and "Why us?" in text and "Short reply." in text


def test_unknown_placeholder_fails_loudly(monkeypatch):
    monkeypatch.setattr(prompts, "template_source", lambda step: "Hello {{nope}}")
    with pytest.raises(KeyError, match="nope"):
        prompts.render("eligibility", _ctx(), {})


def test_unknown_step_has_no_template():
    with pytest.raises(FileNotFoundError):
        prompts.render("no_such_step", _ctx(), {})


def test_the_default_ledger_is_the_committed_resume_bank():
    ledger = _REAL_LEDGER()
    assert ledger.startswith("- ") and "profile.name" in ledger
