"""The full packet pipeline end to end: FakeAdapters scripted per capability, the kit and
answer model calls replaced with scripted `complete`s, and the code steps' HTTP served
from the synthetic fixtures. No network, no CLI, no model."""
import pytest

from app import job_store, people_store
from app.models import JobWorkspaceInput
from app.pipeline import pipelines, runner, store
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline
from tests.test_pipeline_steps_code import GH_POSTING, FakeHttp, _fixture, _sections
from tests.test_pipeline_steps_service import GOOD_ANSWER, Script, _valid_kit_payload

BOARD = "https://remotive.com/remote-jobs/software-dev/backend-engineer-123"
GH_API = "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345"


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def ok(output):
    return AdapterResult(outcome="ok", output=output)


FORM = {"url": GH_POSTING, "fields": [
    {"label": "First name", "kind": "text", "required": True},
    {"label": "Why Acme Cloud?", "kind": "textarea", "required": True},
    {"label": "Do you require visa sponsorship?", "kind": "select", "options": ["Yes", "No"]},
]}
CONTEXT = {
    "company_context": "Acme builds scheduling tools for small teams.",
    "why_this_role": "Backend services in Python, which matches his FastAPI work.",
    "sources": ["https://acme.example/about"],
}
PEOPLE = {"people": [{"name": "Dana Lee", "title": "Engineering Manager",
                      "url": "https://acme.example/team/dana", "why": "Leads the backend team."}]}


def _adapters(fit, *, eligible=True, review=None):
    """One FakeAdapter per capability. The two web steps run at the same time, so each
    gets its own scripted adapter to keep the replay order deterministic."""
    return {
        "cheap": FakeAdapter("fake_cheap", [
            ok({"eligible": eligible, "reason": "Two years asked, remote in Canada."}),
            ok(review or {"pass": True, "issues": []}),
        ]),
        "reason": FakeAdapter("fake_reason", [ok({"score": fit, "reason": "Python services match.",
                                                  "gaps": ["No Go in production"]})]),
        "browser_read": FakeAdapter("fake_browser", [ok(FORM)]),
        "web": {
            "company_context": FakeAdapter("fake_web_context", [ok(CONTEXT)]),
            "people": FakeAdapter("fake_web_people", [ok(PEOPLE)]),
        },
    }


def _chain(adapters):
    def resolve(step):
        entry = adapters.get(step.capability)
        if isinstance(entry, dict):
            entry = entry.get(step.name)
        return [entry] if entry else []
    return resolve


def _pipeline(kit_model, answer_model, checked=None):
    http = FakeHttp({("HEAD", BOARD): (200, GH_POSTING, ""),
                     GH_API: (200, GH_API, _fixture("greenhouse_job.json"))})
    check = (lambda url: (checked.append(url) if checked is not None else None) or ("live", "stub"))
    return Pipeline("packet", pipelines.packet_steps(
        http=http, check=check, complete_kit=kit_model, complete_answer=answer_model))


def _go(job, adapters, kit_model=None, answer_model=None, checked=None):
    kit_model = kit_model or Script(_valid_kit_payload())
    answer_model = answer_model or Script(GOOD_ANSWER)
    pipeline = _pipeline(kit_model, answer_model, checked)
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    return runner.run(created.id, pipeline, owner="w1", resolve_chain=_chain(adapters))


def _job(**extra):
    extra.setdefault("company", "Acme Cloud")
    extra.setdefault("role", "Backend Engineer")
    extra.setdefault("job_url", BOARD)
    return job_store.add_job(JobWorkspaceInput(**extra))


def test_packet_pipeline_order_and_dependencies():
    pipeline = pipelines.PACKET_PIPELINE
    assert pipeline.name == "packet" and pipeline.done_status == "packet_ready"
    assert pipeline.order == [
        "claim", "resolve_apply_url", "fetch_jd", "liveness", "eligibility", "fit_score",
        "company_context", "kit", "form_fields", "people", "answers", "review", "brief",
    ]
    deps = {step.name: step.deps for step in pipeline.steps}
    for name in ("company_context", "kit", "form_fields", "people"):
        assert deps[name] == ("fit_score",)
    assert set(deps["answers"]) == {"company_context", "kit", "form_fields", "people"}
    assert deps["review"] == ("answers",) and deps["brief"] == ("review",)
    brief = pipeline.steps[-1]
    assert brief.owns == ("research_brief", "status")
    kinds = {step.name: step.kind for step in pipeline.steps}
    assert kinds["kit"] == kinds["answers"] == "service"
    assert all(kinds[n] == "agent" for n in
               ("eligibility", "fit_score", "company_context", "form_fields", "people", "review"))


def test_packet_pipeline_end_to_end_reaches_packet_ready_with_a_brief():
    job = _job()
    adapters = _adapters(8)
    checked = []
    result = _go(job, adapters, checked=checked)
    assert result.status == "packet_ready", result.terminal_reason
    assert all(state.status == "done" for state in result.steps.values())
    saved = job_store.get_job(job.id)
    # Code steps: the employer ATS, its JD, its liveness.
    assert saved.apply_url == GH_POSTING
    assert "scheduling product" in saved.jd_text
    assert checked == [GH_POSTING]
    # Agent and service steps.
    assert saved.fit_score == 8 and saved.fit_analysis.score == 8
    assert "Acme Cloud" in saved.cover_letter
    assert "https://acme.example/about" in saved.company_context
    assert [f.label for f in saved.form_fields] == [f["label"] for f in FORM["fields"]]
    questions = {a.question: a for a in saved.application_answers}
    assert set(questions) == {"Why Acme Cloud?", "Do you require visa sponsorship?"}
    assert questions["Do you require visa sponsorship?"].needs_user_input
    assert saved.review.passed is True
    assert [p.name for p in people_store.people_for_job(job.id, job.company, job.role)] == ["Dana Lee"]
    # The brief and the status.
    assert saved.status == "ready"
    brief = _sections(saved.research_brief)
    assert GH_POSTING in brief["APPLY AT"]
    assert "Fit: 8/10" in brief["SUMMARY"]
    assert "No Go in production" in saved.notes
    assert "Why Acme Cloud?" in brief["WHAT TO PUT IN"]
    assert "Do you require visa sponsorship?" in brief["NEEDS HARSH"]
    assert "Dana Lee" in brief["PEOPLE"]
    assert "\u2014" not in saved.research_brief
    # Nothing was sent anywhere: people start at to-reach.
    assert all(p.status == "to-reach" for p in people_store.load_people())


def test_fit_seven_skips_people_and_still_reaches_packet_ready():
    job = _job()
    adapters = _adapters(7)
    result = _go(job, adapters)
    assert result.status == "packet_ready", result.terminal_reason
    assert result.steps["people"].status == "skipped"
    assert adapters["web"]["people"].calls == []
    assert people_store.load_people() == []
    assert "PEOPLE\nnot available yet" in job_store.get_job(job.id).research_brief


def test_fit_five_is_retained_for_review_before_any_writing():
    job = _job()
    kit_model = Script(_valid_kit_payload())
    result = _go(job, _adapters(5), kit_model=kit_model)
    assert result.status == "retained_for_review"
    assert kit_model.prompts == []
    saved = job_store.get_job(job.id)
    assert saved.fit_score == 5 and saved.status == "discovered"
    assert saved.cover_letter == "" and saved.research_brief == ""
    for name in ("kit", "people", "answers", "review", "brief"):
        assert result.steps[name].status == "skipped"


def test_ineligible_ends_the_run_before_fit_score():
    job = _job()
    adapters = _adapters(9, eligible=False)
    result = _go(job, adapters)
    assert result.status == "ineligible"
    assert adapters["reason"].calls == []
    saved = job_store.get_job(job.id)
    assert saved.fit_score is None and saved.status == "discovered"


def test_failing_review_still_ready_with_issues_under_needs_harsh():
    job = _job()
    issue = {"field": "Why Acme Cloud?", "problem": "Reads stiff.", "fix": "Say it plainly."}
    result = _go(job, _adapters(8, review={"pass": False, "issues": [issue]}))
    assert result.status == "packet_ready", result.terminal_reason
    saved = job_store.get_job(job.id)
    assert saved.review.passed is False
    assert "Reads stiff." in _sections(saved.research_brief)["NEEDS HARSH"]


def test_a_kit_that_never_validates_fails_the_run_and_keeps_completed_steps():
    job = _job()
    bad = _valid_kit_payload()
    bad["cover_letter"] = "Too short for Acme Cloud."
    result = _go(job, _adapters(8), kit_model=Script(bad))
    assert result.status == "failed"
    assert result.terminal_reason.startswith("kit:")
    assert result.steps["fit_score"].status == "done"
    assert result.steps["kit"].status == "failed"
    assert result.steps["answers"].status != "done"
    assert job_store.get_job(job.id).status == "discovered"
