"""Lease renewal, claims, the reaper, cancel and shutdown on the store and runner (M6,
spec section 8)."""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

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


def _job():
    return job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))


def _past(seconds=60):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _set(run_id, **fields):
    def change(run):
        for key, value in fields.items():
            setattr(run, key, value)
    store._mutate(run_id, change)


def test_renew_lease_only_extends_the_owners_lease():
    run = store.create_run("j1", "p", ["a"])
    assert store.acquire_lease(run.id, "w1", seconds=5)
    before = store.get_run(run.id).lease_until
    time.sleep(0.01)
    assert store.renew_lease(run.id, "w1", seconds=100)
    assert store.get_run(run.id).lease_until > before
    assert not store.renew_lease(run.id, "w2", seconds=100)
    assert store.get_run(run.id).lease_owner == "w1"
    store.release_lease(run.id, "w1")
    assert not store.renew_lease(run.id, "w1")


def test_claim_takes_only_a_queued_run_with_a_free_lease():
    run = store.create_run("j1", "p", ["a"])
    assert store.claim(run.id, "w1")
    assert not store.claim(run.id, "w2")  # held
    store.release_lease(run.id, "w1")
    store.finish_run(run.id, "failed", "x")
    assert not store.claim(run.id, "w2")  # no longer queued
    assert store.get_run(run.id).lease_owner == ""


def test_reaper_requeues_only_running_runs_whose_lease_lapsed():
    lapsed = store.create_run("j1", "p", ["a"])
    _set(lapsed.id, status="running", lease_owner="dead", lease_until=_past())
    orphan = store.create_run("j2", "p", ["a"])
    _set(orphan.id, status="running")  # released without finishing
    live = store.create_run("j3", "p", ["a"])
    store.acquire_lease(live.id, "alive")
    _set(live.id, status="running")
    queued = store.create_run("j4", "p", ["a"])

    assert sorted(store.reap_expired()) == sorted([lapsed.id, orphan.id])
    assert store.get_run(lapsed.id).status == "queued" and store.get_run(lapsed.id).lease_owner == ""
    assert store.get_run(orphan.id).status == "queued"
    assert store.get_run(live.id).status == "running" and store.get_run(live.id).lease_owner == "alive"
    assert store.get_run(queued.id).status == "queued"


def test_runner_renews_the_lease_so_a_takeover_cannot_reset_an_in_flight_step():
    job = _job()
    seen = {}
    release = threading.Event()

    def slow(ctx):
        first = store.get_run(ctx.run.id).lease_until
        time.sleep(0.3)
        seen["renewed"] = store.get_run(ctx.run.id).lease_until > first
        # Another worker (or service copy) tries to take the run over mid step.
        seen["reaped"] = store.reap_expired()
        try:
            runner.run(ctx.run.id, pipeline, owner="w2")
            seen["takeover"] = True
        except runner.LeaseHeld:
            seen["takeover"] = False
        release.set()
        return StepResult(output={"ok": True})

    pipeline = Pipeline("p", (StepSpec("a", "code", run=slow),))
    run = store.create_run(job.id, "p", pipeline.order)
    done = runner.run(run.id, pipeline, owner="w1", renew_every=0.05, lease_seconds=1)

    assert seen == {"renewed": True, "reaped": [], "takeover": False}
    assert done.status == "packet_ready" and done.steps["a"].output == {"ok": True}
    assert store.get_run(run.id).lease_owner == ""


class Out(BaseModel):
    answer: str


def test_cancel_stops_the_step_without_writes_or_a_retry():
    job = _job()

    class CancelsMidCall(FakeAdapter):
        def invoke(self, step, ctx, errors):
            store.cancel_run(ctx.run.id, "cancelled by test")
            return super().invoke(step, ctx, errors)

    adapter = CancelsMidCall("a1", [AdapterResult(outcome="invalid_output", error="killed"),
                                    AdapterResult(outcome="ok", output={"answer": "x"})])
    step = StepSpec("score", "agent", capability="reason", schema=Out, owns=("notes",),
                    finish=lambda parsed, ctx: StepResult(writes={"notes": parsed.answer}))
    pipeline = Pipeline("p", (step,))
    run = store.create_run(job.id, "p", pipeline.order)

    done = runner.run(run.id, pipeline, owner="w1", resolve_chain=lambda s: [adapter])

    assert done.status == "cancelled" and done.terminal_reason == "cancelled by test"
    assert len(adapter.calls) == 1  # no second try after the cancel
    assert done.steps["score"].status == "failed" and "cancelled" in done.steps["score"].error
    assert job_store.get_job(job.id).notes == ""
    assert done.lease_owner == ""


def test_cancel_run_refuses_a_finished_run_and_clears_any_lease():
    run = store.create_run("j1", "p", ["a", "b"])
    store.acquire_lease(run.id, "w1")
    store.update_step(run.id, "a", status="running")
    cancelled = store.cancel_run(run.id, "stop")
    assert cancelled.status == "cancelled" and cancelled.lease_owner == ""
    assert cancelled.steps["b"].status == "skipped"
    with pytest.raises(store.RunFinished):
        store.cancel_run(run.id, "again")


def test_a_stop_signal_abandons_the_run_for_a_later_resume():
    job = _job()
    stop = threading.Event()

    class StopsMidCall(FakeAdapter):
        def invoke(self, step, ctx, errors):
            stop.set()
            return super().invoke(step, ctx, errors)

    adapter = StopsMidCall("a1", [AdapterResult(outcome="ok", output={"answer": "x"})])
    step = StepSpec("score", "agent", capability="reason", schema=Out, owns=("notes",),
                    finish=lambda parsed, ctx: StepResult(writes={"notes": parsed.answer}))
    pipeline = Pipeline("p", (step,))
    run = store.create_run(job.id, "p", pipeline.order)

    with pytest.raises(runner.RunAbandoned):
        runner.run(run.id, pipeline, owner="w1", resolve_chain=lambda s: [adapter], stop=stop)

    left = store.get_run(run.id)
    assert left.status == "running" and left.steps["score"].status == "running"
    assert left.lease_owner == ""
    assert job_store.get_job(job.id).notes == ""
    # The reaper puts it back, and the next run resumes the step from scratch.
    assert store.reap_expired() == [run.id]
    again = FakeAdapter("a1", [AdapterResult(outcome="ok", output={"answer": "y"})])
    done = runner.run(run.id, pipeline, owner="w2", resolve_chain=lambda s: [again])
    assert done.status == "packet_ready" and job_store.get_job(job.id).notes == "y"


def test_reset_for_retry_requeues_chosen_steps_of_a_finished_run():
    run = store.create_run("j1", "p", ["a", "b", "c"])
    store.complete_step(run.id, "a", output={"x": 1})
    store.update_step(run.id, "b", status="failed", error="boom")
    store.finish_run(run.id, "failed", "b: boom")

    reset = store.reset_for_retry(run.id, {"b", "c"})

    assert reset.status == "queued" and reset.terminal_reason == ""
    assert reset.steps["a"].status == "done" and reset.steps["a"].output == {"x": 1}
    assert reset.steps["b"].status == "pending" and reset.steps["b"].error == ""
    assert reset.steps["c"].status == "pending"
    with pytest.raises(store.RunActive):
        store.reset_for_retry(run.id, {"b"})


def test_a_worker_that_lost_its_lease_writes_nothing_after_cancel_and_retry():
    job = _job()
    seen = {}

    def slow(ctx):
        # While this step runs, the run is cancelled and at once retried from this step,
        # so it is queued again for another worker.
        store.cancel_run(ctx.run.id, "stop")
        store.reset_for_retry(ctx.run.id, {"a", "b"})
        return StepResult(output={"stale": True}, writes={"notes": "stale"})

    def later(ctx):
        seen["b ran"] = True
        return StepResult()

    pipeline = Pipeline("p", (StepSpec("a", "code", owns=("notes",), run=slow),
                              StepSpec("b", "code", deps=("a",), run=later)))
    run = store.create_run(job.id, "p", pipeline.order)

    returned = runner.run(run.id, pipeline, owner="old")

    assert job_store.get_job(job.id).notes == ""
    left = store.get_run(run.id)
    assert returned.status == "queued" and left.status == "queued"
    assert left.steps["a"].status == "pending" and left.steps["a"].output is None
    assert seen == {}
    # The retry then runs normally on a new worker.
    def fresh(ctx):
        return StepResult(writes={"notes": "fresh"})

    again = Pipeline("p", (StepSpec("a", "code", owns=("notes",), run=fresh),
                           StepSpec("b", "code", deps=("a",), run=later)))
    assert runner.run(run.id, again, owner="new").status == "packet_ready"
    assert job_store.get_job(job.id).notes == "fresh"
