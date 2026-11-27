import threading

import pytest

from app import job_store
from app.models import JobWorkspaceInput
from app.pipeline import runner, store
from app.pipeline.runner import Pipeline, StepResult, StepSpec


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def _job(**extra):
    return job_store.add_job(
        JobWorkspaceInput(company="Acme", role="Backend Engineer", notes="keep", **extra)
    )


def _start(job, pipeline):
    return store.create_run(job.id, pipeline.name, pipeline.order)


def _ok(ctx):
    return StepResult()


def _boom(ctx):
    raise RuntimeError("boom")


def test_pipeline_rejects_bad_definitions():
    with pytest.raises(ValueError, match="listed before it"):
        Pipeline("p", (StepSpec("b", "code", deps=("a",), run=_ok), StepSpec("a", "code", run=_ok)))
    with pytest.raises(ValueError, match="duplicate"):
        Pipeline("p", (StepSpec("a", "code", run=_ok), StepSpec("a", "code", run=_ok)))
    with pytest.raises(ValueError, match="needs run"):
        StepSpec("a", "code")
    with pytest.raises(ValueError, match="schema, finish and capability"):
        StepSpec("a", "agent")


def test_three_step_dag_runs_writes_owned_fields_and_passes_outputs():
    job = _job()
    seen = {}

    def fetch(ctx):
        return StepResult(output={"text": "JD body"}, writes={"jd_text": "JD body"})

    def url(ctx):
        return StepResult(output={"url": "https://x/apply"}, writes={"apply_url": "https://x/apply"})

    def brief(ctx):
        seen.update(ctx.outputs)
        return StepResult(writes={"research_brief": f"{ctx.job.jd_text} at {ctx.job.apply_url}"})

    pipeline = Pipeline("packet", (
        StepSpec("fetch_jd", "code", owns=("jd_text",), run=fetch),
        StepSpec("resolve_apply_url", "code", owns=("apply_url",), run=url),
        StepSpec("brief", "code", deps=("fetch_jd", "resolve_apply_url"),
                 owns=("research_brief",), run=brief),
    ))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "packet_ready"
    assert all(s.status == "done" for s in result.steps.values())
    assert seen == {"fetch_jd": {"text": "JD body"}, "resolve_apply_url": {"url": "https://x/apply"}}
    saved = job_store.get_job(job.id)
    assert saved.research_brief == "JD body at https://x/apply"
    assert saved.notes == "keep"
    assert any(r.reason == f"Pipeline run {result.id} step brief" for r in saved.revisions)
    assert [a.outcome for a in store.list_attempts(result.id)] == ["ok", "ok", "ok"]
    assert store.get_run(result.id).lease_owner == ""  # released after the run


def test_independent_steps_run_in_parallel():
    job = _job()
    barrier = threading.Barrier(2, timeout=5)

    def wait(ctx):
        barrier.wait()  # raises BrokenBarrierError if the two run one after the other
        return StepResult()

    pipeline = Pipeline("p", (StepSpec("a", "code", run=wait), StepSpec("b", "code", run=wait)))

    assert runner.run(_start(job, pipeline).id, pipeline, owner="w1").status == "packet_ready"


def test_writing_an_unowned_field_is_a_policy_violation():
    job = _job()

    def sneaky(ctx):
        return StepResult(writes={"cover_letter": "overwritten"})

    pipeline = Pipeline("p", (StepSpec("a", "code", owns=("notes",), run=sneaky),))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "failed"
    assert "does not own: cover_letter" in result.terminal_reason
    assert job_store.get_job(job.id).revisions == job.revisions


def test_stop_ends_run_and_skips_the_rest():
    job = _job()
    later = []

    def fit(ctx):
        return StepResult(stop="retained_for_review", reason="fit 5")

    def kit(ctx):
        later.append(1)
        return StepResult()

    pipeline = Pipeline("p", (
        StepSpec("fit", "code", run=fit),
        StepSpec("kit", "code", deps=("fit",), run=kit),
    ))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "retained_for_review"
    assert result.terminal_reason == "fit 5"
    assert result.steps["kit"].status == "skipped"
    assert later == []


def test_stop_in_one_branch_is_not_overwritten_by_a_sibling_failure():
    job = _job()
    barrier = threading.Barrier(2, timeout=5)

    def stop(ctx):
        barrier.wait()
        return StepResult(stop="ineligible", reason="senior role")

    def fail(ctx):
        barrier.wait()
        raise RuntimeError("network down")

    pipeline = Pipeline("p", (StepSpec("a", "code", run=stop), StepSpec("b", "code", run=fail)))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "ineligible"
    assert result.steps["b"].status == "failed"


def test_failed_step_fails_the_run_after_independent_branches_finish():
    job = _job()
    pipeline = Pipeline("p", (
        StepSpec("a", "code", run=_boom),
        StepSpec("b", "code", run=lambda ctx: StepResult(output={"ok": True})),
        StepSpec("c", "code", deps=("a",), run=_ok),
    ))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "failed"
    assert result.terminal_reason == "a: RuntimeError: boom"
    assert result.steps["b"].status == "done"
    assert result.steps["c"].status == "skipped"
    assert [a.outcome for a in store.list_attempts(result.id) if a.step == "a"] == ["error"]


def test_when_false_skips_a_step_and_dependents_still_run():
    job = _job()
    pipeline = Pipeline("p", (
        StepSpec("people", "code", when=lambda ctx: False, run=_ok),
        StepSpec("brief", "code", deps=("people",), run=lambda ctx: StepResult(output={"done": 1})),
    ))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "packet_ready"
    assert result.steps["people"].status == "skipped"
    assert result.steps["brief"].status == "done"


class _Crash(BaseException):
    """Stands in for the process dying: not an Exception, so nothing catches it."""


def test_resume_after_crash_reruns_only_unfinished_steps():
    job = _job()
    calls = {"a": 0, "b": 0, "c": 0}
    crash = {"on": True}

    def step(name):
        def run(ctx):
            calls[name] += 1
            if name == "b" and crash["on"]:
                raise _Crash()
            return StepResult(output={name: True})
        return run

    pipeline = Pipeline("p", (
        StepSpec("a", "code", run=step("a")),
        StepSpec("b", "code", deps=("a",), run=step("b")),
        StepSpec("c", "code", deps=("b",), run=step("c")),
    ))
    run_id = _start(job, pipeline).id

    with pytest.raises(_Crash):
        runner.run(run_id, pipeline, owner="w1")
    assert store.get_run(run_id).steps["b"].status == "running"

    crash["on"] = False
    result = runner.run(run_id, pipeline, owner="w2")

    assert result.status == "packet_ready"
    assert calls == {"a": 1, "b": 2, "c": 1}


def test_second_worker_gets_lease_held():
    job = _job()
    pipeline = Pipeline("p", (StepSpec("a", "code", run=_ok),))
    run_id = _start(job, pipeline).id
    store.acquire_lease(run_id, "w1")

    with pytest.raises(runner.LeaseHeld):
        runner.run(run_id, pipeline, owner="w2")
    assert store.get_run(run_id).status == "queued"


def test_dossier_deleted_mid_run_fails_cleanly():
    job = _job()

    def delete_then_write(ctx):
        job_store.delete_job(ctx.job.id)
        return StepResult(writes={"notes": "x"})

    pipeline = Pipeline("p", (StepSpec("a", "code", owns=("notes",), run=delete_then_write),))

    result = runner.run(_start(job, pipeline).id, pipeline, owner="w1")

    assert result.status == "failed"
    assert "no longer exists" in result.terminal_reason


def test_run_refuses_a_pipeline_that_does_not_match_the_run():
    job = _job()
    pipeline = Pipeline("p", (StepSpec("a", "code", run=_ok),))
    other = Pipeline("p", (StepSpec("z", "code", run=_ok),))

    with pytest.raises(ValueError, match="does not match"):
        runner.run(_start(job, pipeline).id, other, owner="w1")
