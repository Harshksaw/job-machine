"""Service steps kit and answers, run through runner.run on temp JSON stores. The model
call is replaced with a scripted `complete`, the way tests/test_application_kit.py does."""
import json

import pytest

from app import job_store
from app.models import ApplicationAnswer, FormField, JobWorkspaceInput
from app.pipeline import rules, runner, steps_service, store
from app.pipeline.runner import Pipeline, StepResult, StepSpec
from tests.test_application_kit import _job as _kit_job, _valid_kit_payload

GOOD_ANSWER = {
    "answer": "I built a RAG platform on FastAPI and Qdrant, and it handles ingestion for many tenants.",
    "source_ids": ["project.docintel.bullet.1"],
    "needs_user_input": False,
    "clarification": "",
}


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


class Script:
    """A fake model: replays payloads in order and keeps every prompt it was sent."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        payload = self.payloads.pop(0) if len(self.payloads) > 1 else self.payloads[0]
        return payload if isinstance(payload, str) else json.dumps(payload)


def _job(**extra):
    base = _kit_job()
    extra.setdefault("company", base.company)
    extra.setdefault("role", base.role)
    extra.setdefault("jd_text", base.jd_text)
    return job_store.add_job(JobWorkspaceInput(**extra))


def _run(job, *steps):
    pipeline = Pipeline("t", tuple(steps))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    return runner.run(created.id, pipeline, owner="w1")


def _fit(score):
    return StepSpec("fit_score", "code", run=lambda ctx: StepResult(output={"score": score}))


# kit


def test_kit_spec():
    step = steps_service.kit_step()
    assert (step.kind, step.capability) == ("service", "reason")
    assert set(step.owns) == {"fit_analysis", "cover_letter"}


def test_kit_writes_analysis_and_letter():
    job = _job()
    model = Script(_valid_kit_payload())
    result = _run(job, _fit(8), steps_service.kit_step(complete=model, deps=("fit_score",)))
    assert result.status == "packet_ready", result.terminal_reason
    saved = job_store.get_job(job.id)
    assert "Acme Cloud" in saved.cover_letter
    assert saved.fit_analysis.score == 8 and saved.fit_score == 8
    assert len(model.prompts) == 1
    assert result.steps["kit"].output["kit_score"] == 8


def test_kit_score_is_pinned_to_the_fit_score_step():
    """fit_score is the gate; a kit that scores differently must not move fit_score,
    which update_job copies from fit_analysis.score."""
    job = _job()
    result = _run(job, _fit(6), steps_service.kit_step(complete=Script(_valid_kit_payload()),
                                                       deps=("fit_score",)))
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert saved.fit_score == 6 and saved.fit_analysis.score == 6
    assert saved.fit_analysis.recommendation == "apply"
    output = result.steps["kit"].output
    assert (output["kit_score"], output["score"]) == (8, 6)


def test_kit_repairs_once_with_the_validation_errors():
    job = _job()
    bad = _valid_kit_payload()
    bad["cover_letter"] = bad["cover_letter"].replace("connect reliable", "I am passionate about connecting reliable")
    model = Script(bad, _valid_kit_payload())
    result = _run(job, steps_service.kit_step(complete=model))
    assert result.status == "packet_ready", result.terminal_reason
    assert len(model.prompts) == 2
    assert "passionate" in model.prompts[1] and "failed validation" in model.prompts[1]


def test_kit_fails_with_the_errors_after_one_repair():
    job = _job()
    bad = _valid_kit_payload()
    bad["cover_letter"] = "Too short for Acme Cloud."
    model = Script(bad)
    result = _run(job, steps_service.kit_step(complete=model))
    assert result.status == "failed"
    assert len(model.prompts) == 2
    assert "120-360 words" in result.terminal_reason
    saved = job_store.get_job(job.id)
    assert saved.cover_letter == "" and saved.fit_analysis is None


def test_kit_feeds_shared_rule_errors_back_for_one_repair(monkeypatch):
    calls = []

    def fake_rules(text, company):
        calls.append(text)
        return ["cover letter uses hyphenated compound 'x-y'"] if len(calls) == 1 else []

    monkeypatch.setattr(rules, "cover_letter_errors", fake_rules)
    job = _job()
    model = Script(_valid_kit_payload())
    result = _run(job, steps_service.kit_step(complete=model))
    assert result.status == "packet_ready", result.terminal_reason
    assert len(model.prompts) == 2 and "'x-y'" in model.prompts[1]


def test_kit_fails_when_shared_rules_still_fail_after_the_repair(monkeypatch):
    monkeypatch.setattr(rules, "cover_letter_errors", lambda text, company: ["cover letter contains an em dash"])
    job = _job()
    result = _run(job, steps_service.kit_step(complete=Script(_valid_kit_payload())))
    assert result.status == "failed"
    assert "em dash" in result.terminal_reason
    assert job_store.get_job(job.id).cover_letter == ""


# answers


FIELDS = [
    FormField(label="First name", kind="text", required=True),
    FormField(label="Email", kind="email", required=True),
    FormField(label="Resume", kind="file", required=True),
    FormField(label="Tell us about a project you built (GitHub link optional)", kind="textarea"),
    FormField(label="What is your expected salary?", kind="text"),
    FormField(label="Do you require visa sponsorship?", kind="select", options=["Yes", "No"]),
    FormField(label="How did you hear about us?", kind="select", options=["LinkedIn", "Other"]),
]


def test_answers_spec():
    step = steps_service.answers_step()
    assert (step.kind, step.capability, step.owns) == ("service", "reason", ("application_answers",))


def test_answers_drafts_free_text_and_flags_judgment_fields_for_harsh():
    job = _job(form_fields=FIELDS)
    model = Script(GOOD_ANSWER)
    result = _run(job, steps_service.answers_step(complete=model))
    assert result.status == "packet_ready", result.terminal_reason
    answers = {a.question: a for a in job_store.get_job(job.id).application_answers}
    assert set(answers) == {
        "Tell us about a project you built (GitHub link optional)",
        "What is your expected salary?",
        "Do you require visa sponsorship?",
        "How did you hear about us?",
    }
    project = answers["Tell us about a project you built (GitHub link optional)"]
    assert project.answer.startswith("I built a RAG platform") and not project.needs_user_input
    assert project.source_ids == ["project.docintel.bullet.1"]
    assert answers["What is your expected salary?"].needs_user_input
    assert answers["Do you require visa sponsorship?"].needs_user_input
    # Only the free text field reached the model; judgment questions never do.
    assert len(model.prompts) == 1
    assert "Under 120 words" in model.prompts[0]
    output = result.steps["answers"].output
    assert output["answered"] == 1
    assert sorted(output["needs_user_input"]) == [
        "Do you require visa sponsorship?", "How did you hear about us?", "What is your expected salary?"]
    # A choice field is never skipped silently (rule 5): it waits for Harsh with its options.
    heard = answers["How did you hear about us?"]
    assert heard.needs_user_input and heard.answer == "" and "LinkedIn, Other" in heard.clarification
    skipped = {item["label"] for item in output["skipped"]}
    assert {"First name", "Email", "Resume"} == skipped


def test_answers_stop_before_the_next_field_once_the_run_is_cancelled():
    job = _job(form_fields=[FormField(label="Why Acme Cloud?", kind="textarea"),
                            FormField(label="Tell us about a project you built", kind="textarea")])
    calls = []

    def model(prompt):
        calls.append(prompt)
        store.cancel_run(next(iter(store.list_runs(job.id))).id, "stop")
        return json.dumps(GOOD_ANSWER)

    result = _run(job, steps_service.answers_step(complete=model))

    assert result.status == "cancelled"
    assert len(calls) == 1
    assert job_store.get_job(job.id).application_answers == []


def test_routed_sessions_carry_the_step_cancel_check():
    job = _job()
    seen = {}

    def kit(ctx):
        seen["model"] = steps_service._model(ctx, None, "kit", {})
        seen["check"] = ctx.check
        return StepResult()

    _run(job, StepSpec("kit", "service", run=kit))
    assert seen["model"].options["cancel"] is seen["check"]


def test_answers_keeps_an_existing_answer_for_the_same_question():
    existing = ApplicationAnswer(id="a1", question="Why Acme Cloud?", answer="Harsh wrote this.",
                                 status="approved", created_at="t", updated_at="t")
    job = _job(form_fields=[FormField(label="why acme cloud?", kind="textarea")],
               application_answers=[existing])
    model = Script(GOOD_ANSWER)
    result = _run(job, steps_service.answers_step(complete=model))
    assert result.status == "packet_ready"
    answers = job_store.get_job(job.id).application_answers
    assert [a.answer for a in answers] == ["Harsh wrote this."]
    assert model.prompts == []


def test_answers_with_no_form_fields_writes_nothing():
    job = _job()
    result = _run(job, steps_service.answers_step(complete=Script(GOOD_ANSWER)))
    assert result.status == "packet_ready"
    assert result.steps["answers"].output["answered"] == 0
    assert job_store.get_job(job.id).application_answers == []


def test_answers_repairs_once_then_fails_with_the_errors():
    job = _job(form_fields=[FormField(label="Why Acme Cloud?", kind="textarea")])
    bad = dict(GOOD_ANSWER, answer="I am passionate about RAG on FastAPI.")
    model = Script(bad)
    result = _run(job, steps_service.answers_step(complete=model))
    assert result.status == "failed"
    assert len(model.prompts) == 2 and "passionate" in model.prompts[1]
    assert "Why Acme Cloud?" in result.terminal_reason and "passionate" in result.terminal_reason
    assert job_store.get_job(job.id).application_answers == []


def test_answers_feeds_shared_rule_errors_back(monkeypatch):
    seen = []

    def fake_rules(text, **_):
        seen.append(text)
        return ["answer must be at most 120 words, got 130"] if len(seen) == 1 else []

    monkeypatch.setattr(rules, "answer_errors", fake_rules)
    job = _job(form_fields=[FormField(label="Why Acme Cloud?", kind="textarea")])
    model = Script(GOOD_ANSWER)
    result = _run(job, steps_service.answers_step(complete=model))
    assert result.status == "packet_ready", result.terminal_reason
    assert len(model.prompts) == 2 and "got 130" in model.prompts[1]


def test_a_required_choice_question_is_flagged_for_harsh_not_skipped():
    job = _job(form_fields=[FormField(label="Can you commit to an on call rotation?", kind="radio",
                                      required=True, options=["Yes", "No"])])
    model = Script(GOOD_ANSWER)
    result = _run(job, steps_service.answers_step(complete=model))
    assert result.status == "packet_ready"
    [answer] = job_store.get_job(job.id).application_answers
    assert answer.needs_user_input and "Yes, No" in answer.clarification
    assert model.prompts == []


# repair (spec 6.4): one repair round on what a failing review flagged


def _review(passed, issues):
    return StepSpec("review", "code", run=lambda ctx: StepResult(output={"pass": passed, "issues": issues}))


def _kit_wrote():
    """Stands in for a kit step that wrote the dossier's letter in this run."""
    return StepSpec("kit", "code", run=lambda ctx: StepResult(output={"wrote_letter": True}))


LETTER_ISSUE = {"field": "cover_letter", "problem": "Opens with a vague line.", "fix": "Start with the product."}


def test_repair_spec():
    step = steps_service.repair_step()
    assert (step.kind, step.capability) == ("service", "reason")
    assert set(step.owns) == {"fit_analysis", "cover_letter", "application_answers"}


def test_repair_does_nothing_after_a_passing_review():
    job = _job(cover_letter="Old letter for Acme Cloud.")
    model = Script(_valid_kit_payload())
    result = _run(job, _review(True, []), steps_service.repair_step(complete_kit=model, deps=("review",)))
    assert result.status == "packet_ready"
    assert result.steps["repair"].output == {"repaired": [], "unrepaired": []}
    assert model.prompts == [] and job_store.get_job(job.id).cover_letter == "Old letter for Acme Cloud."


def test_repair_regenerates_the_letter_with_the_review_issues():
    job = _job(cover_letter="Old letter for Acme Cloud.")
    model = Script(_valid_kit_payload())
    result = _run(job, _fit(7), _kit_wrote(), _review(False, [LETTER_ISSUE]),
                  steps_service.repair_step(complete_kit=model, deps=("fit_score", "kit", "review")))
    assert result.status == "packet_ready", result.terminal_reason
    assert "Opens with a vague line." in model.prompts[0] and "Start with the product." in model.prompts[0]
    saved = job_store.get_job(job.id)
    assert saved.cover_letter.startswith("Acme Cloud needs") and saved.fit_score == 7
    assert result.steps["repair"].output == {"repaired": ["cover_letter"], "unrepaired": []}


def test_repair_regenerates_a_flagged_answer_in_place():
    old = ApplicationAnswer(id="a1", question="Why Acme Cloud?", answer="Old stiff reply.",
                            created_at="t", updated_at="t")
    harsh = ApplicationAnswer(id="a2", question="Salary?", needs_user_input=True, clarification="ask",
                              created_at="t", updated_at="t")
    job = _job(application_answers=[old, harsh])
    issue = {"field": "Why Acme Cloud?", "problem": "Reads stiff.", "fix": "Say one real thing."}
    model = Script(GOOD_ANSWER)
    result = _run(job, _review(False, [issue, {"field": "Salary?", "problem": "Empty.", "fix": ""}]),
                  steps_service.repair_step(complete_answer=model, deps=("review",)))
    assert result.status == "packet_ready", result.terminal_reason
    answers = job_store.get_job(job.id).application_answers
    assert [a.id for a in answers] == ["a1", "a2"]
    assert answers[0].answer.startswith("I built a RAG platform") and answers[1].needs_user_input
    assert "Reads stiff." in model.prompts[0] and len(model.prompts) == 1
    assert result.steps["repair"].output == {"repaired": ["Why Acme Cloud?"], "unrepaired": ["Salary?"]}


def test_a_repair_that_still_fails_keeps_the_old_text_and_the_run_goes_on():
    job = _job(cover_letter="Old letter for Acme Cloud.")
    bad = _valid_kit_payload()
    bad["cover_letter"] = "Too short for Acme Cloud."
    result = _run(job, _kit_wrote(), _review(False, [LETTER_ISSUE]),
                  steps_service.repair_step(complete_kit=Script(bad), deps=("kit", "review")))
    assert result.status == "packet_ready"
    assert job_store.get_job(job.id).cover_letter == "Old letter for Acme Cloud."
    assert result.steps["repair"].output == {"repaired": [], "unrepaired": ["cover_letter"]}


# Owner ruling: hand edited cover letters survive the pipeline.


def test_kit_keeps_an_existing_cover_letter_but_writes_the_analysis():
    job = _job(cover_letter="Harsh's own letter to Acme Cloud.")
    result = _run(job, _fit(7), steps_service.kit_step(complete=Script(_valid_kit_payload()),
                                                       deps=("fit_score",)))
    assert result.status == "packet_ready", result.terminal_reason
    saved = job_store.get_job(job.id)
    assert saved.cover_letter == "Harsh's own letter to Acme Cloud."
    assert saved.fit_analysis.score == 7 and saved.fit_score == 7
    output = result.steps["kit"].output
    assert output["cover_letter"] == "kept existing cover letter" and output["wrote_letter"] is False


def test_kit_generates_a_letter_when_none_exists():
    job = _job()
    result = _run(job, steps_service.kit_step(complete=Script(_valid_kit_payload())))
    assert result.steps["kit"].output["wrote_letter"] is True
    assert result.steps["kit"].output["cover_letter"] == "generated"
    assert job_store.get_job(job.id).cover_letter.startswith("Acme Cloud needs")


def test_repair_does_not_touch_a_letter_the_kit_did_not_write_this_run():
    job = _job(cover_letter="Harsh's own letter to Acme Cloud.")
    kit_model = Script(_valid_kit_payload())
    result = _run(job, steps_service.kit_step(complete=kit_model), _review(False, [LETTER_ISSUE]),
                  steps_service.repair_step(complete_kit=kit_model, deps=("kit", "review")))
    assert result.status == "packet_ready", result.terminal_reason
    assert job_store.get_job(job.id).cover_letter == "Harsh's own letter to Acme Cloud."
    assert len(kit_model.prompts) == 1  # the kit's own draft; repair never called the model
    assert result.steps["repair"].output == {"repaired": [], "unrepaired": ["cover_letter"]}


def test_repair_rewrites_a_letter_the_kit_wrote_this_run():
    job = _job()
    kit_model = Script(_valid_kit_payload())
    result = _run(job, steps_service.kit_step(complete=kit_model), _review(False, [LETTER_ISSUE]),
                  steps_service.repair_step(complete_kit=kit_model, deps=("kit", "review")))
    assert result.steps["repair"].output == {"repaired": ["cover_letter"], "unrepaired": []}
    assert len(kit_model.prompts) == 2
