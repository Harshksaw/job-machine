"""Agent steps of the packet pipeline, run through runner.run with scripted FakeAdapters
on temp JSON stores. No network, no CLI, no model."""
import pytest

from app import job_store, people_store
from app.models import FitAnalysis, JobWorkspaceInput, PersonInput
from app.pipeline import runner, steps_agent, store
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline, StepResult, StepSpec

EM = "—"


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def _job(**extra):
    extra.setdefault("notes", "keep")
    extra.setdefault("company", "Acme")
    extra.setdefault("role", "Backend Engineer")
    return job_store.add_job(JobWorkspaceInput(**extra))


def ok(output):
    return AdapterResult(outcome="ok", output=output)


def _run(job, steps, script):
    """`script` maps step name -> list of AdapterResults for that step's FakeAdapter."""
    adapters = {name: FakeAdapter(f"fake_{name}", results) for name, results in script.items()}
    pipeline = Pipeline("t", tuple(steps))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    result = runner.run(created.id, pipeline, owner="w1",
                        resolve_chain=lambda step: [adapters[step.name]] if step.name in adapters else [])
    return result, adapters


def _stub(name, output, deps=()):
    return StepSpec(name, "code", deps=deps, run=lambda ctx: StepResult(output=output))


# eligibility


def test_eligibility_spec():
    step = steps_agent.eligibility_step()
    assert (step.kind, step.capability, step.owns) == ("agent", "cheap", ("notes",))


def test_eligible_appends_one_note_line_and_continues():
    job = _job()
    result, _ = _run(job, [steps_agent.eligibility_step()],
                     {"eligibility": [ok({"eligible": True, "reason": "Two years asked, remote Canada."})]})
    assert result.status == "packet_ready"
    assert result.steps["eligibility"].output["eligible"] is True
    notes = job_store.get_job(job.id).notes.splitlines()
    assert notes[0] == "keep" and len(notes) == 2
    assert notes[1].startswith(f"Pipeline {result.id}: eligible")


def test_ineligible_stops_the_run_with_the_reason_and_never_archives():
    job = _job()
    reason = f"Needs 7+ years {EM} senior role."
    result, _ = _run(job, [steps_agent.eligibility_step(), _stub("after", {}, deps=("eligibility",))],
                     {"eligibility": [ok({"eligible": False, "reason": reason})]})
    assert result.status == "ineligible"
    assert "senior role" in result.terminal_reason
    assert result.steps["after"].status == "skipped"
    saved = job_store.get_job(job.id)
    assert saved.status == "discovered"
    assert "ineligible" in saved.notes and EM not in saved.notes


def test_eligibility_repairs_invalid_output_once_on_the_same_adapter():
    job = _job()
    result, adapters = _run(job, [steps_agent.eligibility_step()], {"eligibility": [
        ok({"eligible": "maybe"}),
        ok({"eligible": True, "reason": "fine"}),
    ]})
    assert result.status == "packet_ready"
    calls = adapters["eligibility"].calls
    assert calls[0] == [] and any("eligible" in e for e in calls[1])


def test_eligibility_rejects_a_blank_reason():
    job = _job()
    result, _ = _run(job, [steps_agent.eligibility_step()], {"eligibility": [
        ok({"eligible": False, "reason": "  "}), ok({"eligible": False, "reason": " "}),
    ]})
    assert result.status == "failed"


# fit_score


def test_fit_score_spec():
    step = steps_agent.fit_score_step()
    assert (step.kind, step.capability) == ("agent", "reason")
    assert set(step.owns) == {"fit_score", "notes", "fit_analysis"}


def test_fit_score_eight_writes_score_and_note():
    job = _job()
    result, _ = _run(job, [steps_agent.fit_score_step()], {"fit_score": [
        ok({"score": 8, "reason": "Python APIs match.", "gaps": ["No Kafka"]})]})
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert saved.fit_score == 8 and saved.fit_analysis is None
    assert "fit 8/10" in saved.notes and "No Kafka" in saved.notes
    assert result.steps["fit_score"].output == {"score": 8, "reason": "Python APIs match.", "gaps": ["No Kafka"]}


def test_fit_score_five_is_retained_for_review_and_kept_active():
    job = _job(status="researching")
    result, _ = _run(job, [steps_agent.fit_score_step(), _stub("after", {}, deps=("fit_score",))],
                     {"fit_score": [ok({"score": 5, "reason": "Mostly frontend.", "gaps": ["React Native"]})]})
    assert result.status == "retained_for_review"
    assert "5" in result.terminal_reason and "Mostly frontend" in result.terminal_reason
    saved = job_store.get_job(job.id)
    assert saved.fit_score == 5 and saved.status == "researching"
    assert "React Native" in saved.notes


def test_fit_score_updates_an_existing_fit_analysis_so_the_score_sticks():
    """update_job copies fit_analysis.score into fit_score, so a step that wrote only
    fit_score would be silently overwritten by the old analysis."""
    analysis = FitAnalysis(score=9, recommendation="apply", verdict="old verdict")
    job = _job(fit_analysis=analysis)
    assert job.fit_score == 9
    result, _ = _run(job, [steps_agent.fit_score_step()], {"fit_score": [
        ok({"score": 5, "reason": "Rescored on the full JD.", "gaps": []})]})
    assert result.status == "retained_for_review"
    saved = job_store.get_job(job.id)
    assert saved.fit_score == 5
    assert saved.fit_analysis.score == 5 and saved.fit_analysis.recommendation == "review"
    assert saved.fit_analysis.verdict == "old verdict"


@pytest.mark.parametrize("bad", [{"score": 11, "reason": "x"}, {"score": 0, "reason": "x"},
                                 {"score": 7}, {"score": "high", "reason": "x"}])
def test_fit_score_out_of_range_or_missing_is_invalid(bad):
    job = _job()
    result, adapters = _run(job, [steps_agent.fit_score_step()], {"fit_score": [ok(bad), ok(bad)]})
    assert result.status == "failed"
    assert len(adapters["fit_score"].calls) == 2
    assert job_store.get_job(job.id).fit_score is None


# company_context


def test_company_context_writes_context_with_sources_and_why():
    job = _job()
    out = {
        "company_context": f"Acme builds payroll tools {EM} it raised a seed round.",
        "why_this_role": "The role is Python APIs, which he built at work.",
        "why_source_ids": ["exp.a.1"],
        "sources": ["https://acme.example/about", "https://news.example/acme"],
    }
    step = steps_agent.company_context_step()
    assert (step.capability, set(step.owns)) == ("web", {"company_context", "why_this_role"})
    result, _ = _run(job, [step], {"company_context": [ok(out)]})
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert "payroll tools" in saved.company_context and EM not in saved.company_context
    assert "https://acme.example/about" in saved.company_context
    assert saved.why_this_role == out["why_this_role"]
    assert result.steps["company_context"].output["sources"] == out["sources"]


@pytest.mark.parametrize("sources", [[], ["not a url"], ["ftp://x.example"]])
def test_company_context_needs_at_least_one_source_url(sources):
    job = _job()
    out = {"company_context": "Acme builds payroll tools.", "why_this_role": "Fits.", "sources": sources}
    result, adapters = _run(job, [steps_agent.company_context_step()],
                            {"company_context": [ok(out), ok(out)]})
    assert result.status == "failed"
    assert any("sources" in e for e in adapters["company_context"].calls[1])
    assert job_store.get_job(job.id).company_context == ""


# form_fields


def test_form_fields_writes_the_new_dossier_field():
    job = _job(apply_url="https://jobs.ashbyhq.com/acme/1")
    fields = [
        {"label": "First name", "kind": "text", "required": True},
        {"label": "Why Acme?", "kind": "textarea", "required": True},
        {"label": "Do you need sponsorship?", "kind": "select", "options": ["Yes", "No"]},
    ]
    step = steps_agent.form_fields_step()
    assert (step.capability, step.owns) == ("browser_read", ("form_fields",))
    result, _ = _run(job, [step], {"form_fields": [ok({"url": job.apply_url, "fields": fields})]})
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert [f.label for f in saved.form_fields] == ["First name", "Why Acme?", "Do you need sponsorship?"]
    assert saved.form_fields[2].options == ["Yes", "No"]
    assert result.steps["form_fields"].output["count"] == 3


def test_form_fields_rejects_an_unknown_kind():
    job = _job()
    bad = {"fields": [{"label": "Essay", "kind": "essay"}]}
    result, _ = _run(job, [steps_agent.form_fields_step()], {"form_fields": [ok(bad), ok(bad)]})
    assert result.status == "failed"


# people


def _people_pipeline(score):
    return [_stub("fit_score", {"score": score}), steps_agent.people_step(deps=("fit_score",))]


PEOPLE = {"people": [
    {"name": "Dana Lee", "title": "Engineering Manager", "url": "https://www.linkedin.com/in/dana-example",
     "why": "Runs the platform team this role joins."},
    {"name": "Sam Roe", "title": "Recruiter", "url": "https://acme.example/team", "why": "Owns the req."},
]}


def test_people_runs_at_fit_eight_and_pins_people_to_the_dossier():
    job = _job()
    result, _ = _run(job, _people_pipeline(8), {"people": [ok(PEOPLE)]})
    assert result.status == "packet_ready"
    assert result.steps["people"].status == "done"
    found = people_store.people_for_job(job.id, job.company, job.role)
    assert sorted(p.name for p in found) == ["Dana Lee", "Sam Roe"]
    dana = next(p for p in found if p.name == "Dana Lee")
    assert dana.job_id == job.id and dana.status == "to-reach"
    assert dana.linkedin_url == "https://www.linkedin.com/in/dana-example"
    assert dana.title == "Engineering Manager"
    titles = [a.title for a in job_store.get_job(job.id).activities]
    assert "Added Dana Lee to reach" in titles
    assert [p["name"] for p in result.steps["people"].output["people"]] == ["Dana Lee", "Sam Roe"]


def test_people_is_skipped_at_fit_seven():
    job = _job()
    result, adapters = _run(job, _people_pipeline(7), {"people": [ok(PEOPLE)]})
    assert result.status == "packet_ready"
    assert result.steps["people"].status == "skipped"
    assert adapters["people"].calls == []
    assert people_store.load_people() == []


def test_people_does_not_duplicate_someone_already_saved():
    job = _job()
    people_store.add_person(PersonInput(name="dana lee", company="Acme", job_id=job.id))
    result, _ = _run(job, _people_pipeline(9), {"people": [ok(PEOPLE)]})
    assert result.status == "packet_ready"
    names = sorted(p.name for p in people_store.load_people())
    assert names == ["Sam Roe", "dana lee"]


def test_people_allows_at_most_three():
    job = _job()
    many = {"people": [{"name": f"P{i}", "url": f"https://acme.example/p{i}"} for i in range(4)]}
    result, _ = _run(job, _people_pipeline(8), {"people": [ok(many), ok(many)]})
    assert result.status == "failed"
    assert people_store.load_people() == []


# review


def test_review_spec():
    step = steps_agent.review_step()
    assert (step.capability, step.owns) == ("cheap", ("review",))


def test_review_pass_writes_the_review_field():
    job = _job(cover_letter="Acme builds payments. " + " ".join(["plain"] * 150))
    result, _ = _run(job, [steps_agent.review_step()], {"review": [ok({"pass": True, "issues": []})]})
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert saved.review.passed is True and saved.review.issues == []
    assert result.steps["review"].output == {"pass": True, "issues": []}


def test_review_adds_rule_violations_and_fails_the_review():
    letter = f"Hello there {EM} I am a full-stack dev. " + " ".join(["plain"] * 150)
    job = _job(cover_letter=letter)
    result, _ = _run(job, [steps_agent.review_step()], {"review": [ok({"pass": True, "issues": []})]})
    assert result.status == "packet_ready"
    review = job_store.get_job(job.id).review
    assert review.passed is False
    problems = " ".join(issue.problem for issue in review.issues)
    assert "em dash" in problems and "full-stack" in problems and "name the company" in problems
    assert result.steps["review"].output["pass"] is False


def test_review_listing_issues_cannot_pass():
    job = _job()
    issue = {"field": "Why Acme?", "problem": "Reads like a brochure.", "fix": "Say one real thing."}
    result, _ = _run(job, [steps_agent.review_step()], {"review": [ok({"pass": True, "issues": [issue]})]})
    review = job_store.get_job(job.id).review
    assert review.passed is False and review.issues[0].field == "Why Acme?"
