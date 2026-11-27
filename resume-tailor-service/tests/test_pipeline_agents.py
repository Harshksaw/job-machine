import pytest
from pydantic import BaseModel, Field

from app import job_store
from app.models import JobWorkspaceInput
from app.pipeline import runner, store
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline, StepResult, StepSpec


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


class Context(BaseModel):
    company_context: str = Field(min_length=10)


def _finish(parsed: Context, ctx) -> StepResult:
    return StepResult(output=parsed.model_dump(), writes={"company_context": parsed.company_context})


PIPELINE = Pipeline("p", (
    StepSpec("company_context", "agent", capability="web", owns=("company_context",),
             schema=Context, finish=_finish),
))

GOOD = AdapterResult(outcome="ok", output={"company_context": "They build search for shops."},
                     model="m1", tokens_in=10, tokens_out=5, cost=0.01)


def _go(*adapters, pipeline=PIPELINE):
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))
    run_id = store.create_run(job.id, pipeline.name, pipeline.order).id
    result = runner.run(run_id, pipeline, owner="w1", resolve_chain=lambda step: list(adapters))
    return job, result


def test_first_adapter_success_writes_and_records_the_attempt():
    first = FakeAdapter("cheap", [GOOD])
    second = FakeAdapter("pricey", [GOOD])

    job, result = _go(first, second)

    assert result.status == "packet_ready"
    assert job_store.get_job(job.id).company_context == "They build search for shops."
    assert second.calls == []
    [attempt] = store.list_attempts(result.id)
    assert (attempt.adapter, attempt.outcome, attempt.model, attempt.cost) == ("cheap", "ok", "m1", 0.01)


def test_schema_failure_gets_one_repair_try_with_the_errors():
    short = AdapterResult(outcome="ok", output={"company_context": "short"})
    first = FakeAdapter("cheap", [short, GOOD])

    job, result = _go(first)

    assert result.status == "packet_ready"
    assert first.calls[0] == []
    assert "company_context" in first.calls[1][0]
    assert [a.outcome for a in store.list_attempts(result.id)] == ["invalid_output", "ok"]


def test_two_invalid_outputs_move_to_the_next_adapter():
    bad = AdapterResult(outcome="invalid_output", error="not JSON")
    first = FakeAdapter("cheap", [bad, bad])
    second = FakeAdapter("pricey", [GOOD])

    job, result = _go(first, second)

    assert result.status == "packet_ready"
    assert first.calls == [[], ["not JSON"]]
    assert [a.adapter for a in store.list_attempts(result.id)] == ["cheap", "cheap", "pricey"]


@pytest.mark.parametrize("outcome", ["unavailable", "timeout", "error"])
def test_unavailable_timeout_and_error_fall_back_without_retry(outcome):
    first = FakeAdapter("cheap", [AdapterResult(outcome=outcome, error="out of credits")])
    second = FakeAdapter("pricey", [GOOD])

    job, result = _go(first, second)

    assert result.status == "packet_ready"
    assert len(first.calls) == 1


def test_exhausted_chain_fails_the_run_with_the_last_error():
    first = FakeAdapter("cheap", [AdapterResult(outcome="timeout", error="10m")])
    second = FakeAdapter("pricey", [AdapterResult(outcome="unavailable", error="signed out")])

    job, result = _go(first, second)

    assert result.status == "failed"
    assert result.terminal_reason == (
        "company_context: every adapter failed; last: pricey: unavailable signed out"
    )
    assert job_store.get_job(job.id).company_context == ""


def test_policy_violation_stops_at_once():
    first = FakeAdapter("cheap", [AdapterResult(outcome="policy_violation", error="tried to submit")])
    second = FakeAdapter("pricey", [GOOD])

    job, result = _go(first, second)

    assert result.status == "failed"
    assert "tried to submit" in result.terminal_reason
    assert second.calls == []


def test_no_adapter_for_the_capability_fails_the_step():
    job, result = _go()

    assert result.status == "failed"
    assert "no adapter offers capability 'web'" in result.terminal_reason


def test_finish_raising_fails_the_step_instead_of_crashing():
    def broken(parsed, ctx):
        raise KeyError("missing")

    pipeline = Pipeline("p", (
        StepSpec("company_context", "agent", capability="web", owns=("company_context",),
                 schema=Context, finish=broken),
    ))

    job, result = _go(FakeAdapter("a", [GOOD]), pipeline=pipeline)

    assert result.status == "failed"
    assert "KeyError" in result.terminal_reason
