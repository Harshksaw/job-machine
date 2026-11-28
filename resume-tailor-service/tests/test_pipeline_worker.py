"""The M6 worker pool: claims, concurrency caps, the reaper, schedules, shutdown, and the
lifespan switch (spec section 8). Fake pipelines and adapters only."""
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import BaseModel

from app import job_store
from app.models import JobWorkspaceInput
from app.pipeline import config, store, tasks, worker
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline, StepResult, StepSpec


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})


def _job():
    return job_store.add_job(JobWorkspaceInput(company="Acme", role="Engineer"))


def _wait(predicate, timeout=5.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _ended(run_id):
    return lambda: store.get_run(run_id).status not in ("queued", "running")


class Out(BaseModel):
    answer: str


def _agent_step(name, capability="reason", deps=()):
    return StepSpec(name, "agent", capability=capability, schema=Out, deps=deps,
                    finish=lambda parsed, ctx: StepResult(output=parsed.model_dump()))


def _pool(pipelines, chain=lambda step: [], **extra):
    defaults = {"poll": 0.02, "tick": 0.05, "shutdown_timeout": 5}
    return worker.WorkerPool(extra.pop("size", 1), pipeline_for=pipelines.get, chain=chain,
                             **{**defaults, **extra})


def test_pool_runs_a_queued_run_to_its_end_and_stops_cleanly():
    job = _job()
    pipeline = Pipeline("p", (StepSpec("a", "code", run=lambda ctx: StepResult(output={"n": 1})),))
    run = store.create_run(job.id, "p", pipeline.order)
    pool = _pool({"p": pipeline})
    pool.start()
    try:
        assert _wait(_ended(run.id))
    finally:
        pool.stop()
    done = store.get_run(run.id)
    assert done.status == "packet_ready" and done.steps["a"].output == {"n": 1}
    assert done.lease_owner == ""
    assert not any(thread.is_alive() for thread in pool.threads)


def test_unknown_pipeline_fails_the_run_instead_of_looping():
    run = store.create_run("j1", "nope", ["a"])
    pool = _pool({})
    pool.start()
    try:
        assert _wait(_ended(run.id))
    finally:
        pool.stop()
    assert store.get_run(run.id).status == "failed"
    assert "nope" in store.get_run(run.id).terminal_reason


def test_reaper_resumes_a_run_whose_worker_died():
    job = _job()
    pipeline = Pipeline("p", (StepSpec("a", "code", run=lambda ctx: StepResult(output={"n": 2})),))
    run = store.create_run(job.id, "p", pipeline.order)

    def dead(r):
        r.status = "running"
        r.lease_owner = "dead-worker"
        r.lease_until = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        r.steps["a"] = r.steps["a"].model_copy(update={"status": "running"})

    store._mutate(run.id, dead)
    pool = _pool({"p": pipeline})
    pool.start()
    try:
        assert _wait(_ended(run.id))
    finally:
        pool.stop()
    assert store.get_run(run.id).status == "packet_ready"


def test_adapter_max_parallel_is_enforced_across_runs(monkeypatch):
    live, peak, lock = [0], [0], threading.Lock()

    class Slow(FakeAdapter):
        def invoke(self, step, ctx, errors):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.15)
            with lock:
                live[0] -= 1
            return AdapterResult(outcome="ok", output={"answer": "x"})

    cfg = config.PipelineConfig.model_validate({"adapters": {"solo": {
        "type": "cli", "command": ["x", "{prompt}"], "capabilities": ["reason"], "max_parallel": 1}}})
    pipeline = Pipeline("p", (_agent_step("s"),))
    runs = [store.create_run(_job().id, "p", pipeline.order) for _ in range(3)]
    pool = _pool({"p": pipeline}, chain=lambda step: [Slow("solo", [])], size=3, load_config=lambda: cfg)
    pool.start()
    try:
        assert all(_wait(_ended(r.id)) for r in runs)
    finally:
        pool.stop()
    assert peak[0] == 1
    assert {store.get_run(r.id).status for r in runs} == {"packet_ready"}


def test_capability_cap_limits_concurrent_steps_over_every_adapter():
    live, peak, lock = [0], [0], threading.Lock()

    class Slow(FakeAdapter):
        def invoke(self, step, ctx, errors):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.15)
            with lock:
                live[0] -= 1
            return AdapterResult(outcome="ok", output={"answer": "x"})

    cfg = config.PipelineConfig.model_validate({
        "adapters": {name: {"type": "cli", "command": ["x", "{prompt}"], "capabilities": ["browser_read"],
                            "max_parallel": 4} for name in ("a1", "a2")},
        "capability_caps": {"browser_read": 2}})
    pipeline = Pipeline("p", (_agent_step("s", capability="browser_read"),))
    runs = [store.create_run(_job().id, "p", pipeline.order) for _ in range(4)]
    names = iter(["a1", "a2"] * 4)
    pool = _pool({"p": pipeline}, chain=lambda step: [Slow(next(names), [])], size=4, load_config=lambda: cfg)
    pool.start()
    try:
        assert all(_wait(_ended(r.id)) for r in runs)
    finally:
        pool.stop()
    assert peak[0] == 2


def test_stop_abandons_an_in_flight_run_and_puts_it_back_in_the_queue():
    job = _job()
    entered, leave = threading.Event(), threading.Event()

    class Blocks(FakeAdapter):
        def invoke(self, step, ctx, errors):
            entered.set()
            leave.wait(5)
            return AdapterResult(outcome="ok", output={"answer": "x"})

    pipeline = Pipeline("p", (_agent_step("s"),))
    run = store.create_run(job.id, "p", pipeline.order)
    pool = _pool({"p": pipeline}, chain=lambda step: [Blocks("a", [])])
    pool.start()
    assert entered.wait(5)
    stopper = threading.Thread(target=pool.stop)
    stopper.start()
    time.sleep(0.1)
    leave.set()  # the adapter call returns; the runner sees the stop and abandons
    stopper.join(10)
    left = store.get_run(run.id)
    assert left.status == "queued" and left.lease_owner == ""
    assert store.list_attempts(run.id) == []


def test_stop_kills_the_cli_processes_of_active_runs(monkeypatch):
    job = _job()
    entered, leave = threading.Event(), threading.Event()
    killed = []
    monkeypatch.setattr(worker.adapters, "kill_run", lambda run_id: killed.append(run_id) or leave.set() or 1)

    class Blocks(FakeAdapter):
        def invoke(self, step, ctx, errors):
            entered.set()
            leave.wait(5)
            return AdapterResult(outcome="invalid_output", error="killed")

    pipeline = Pipeline("p", (_agent_step("s"),))
    run = store.create_run(job.id, "p", pipeline.order)
    pool = _pool({"p": pipeline}, chain=lambda step: [Blocks("a", [])])
    pool.start()
    assert entered.wait(5)
    pool.stop()
    assert killed == [run.id]
    assert store.get_run(run.id).status == "queued"


# --- schedules ---------------------------------------------------------------------------


def test_schedulable_tasks_match_the_task_registry():
    assert set(config.SCHEDULABLE_TASKS) == set(tasks.TASK_BUILDERS)


def test_schedules_validate_task_names_and_intervals():
    ok = config.PipelineConfig.model_validate({"schedules": {"mail_sync": {"every_minutes": 60}}})
    assert ok.schedules["mail_sync"].every_minutes == 60 and ok.schedules["mail_sync"].enabled
    with pytest.raises(ValueError, match="unknown task"):
        config.PipelineConfig.model_validate({"schedules": {"packet": {"every_minutes": 60}}})
    with pytest.raises(ValueError):
        config.PipelineConfig.model_validate({"schedules": {"mail_sync": {"every_minutes": 1}}})
    assert config.load_defaults().schedules == {}  # off by default


def test_enqueue_due_respects_interval_and_the_one_active_rule(monkeypatch):
    cfg = config.PipelineConfig.model_validate({"schedules": {
        "mail_sync": {"every_minutes": 60},
        "liveness_sweep": {"every_minutes": 60, "enabled": False},
        "remote_boards": {"every_minutes": 60},
    }})
    now = datetime.now(timezone.utc)

    first = worker.enqueue_due(cfg, now)
    assert sorted(run.pipeline for run in first) == ["mail_sync", "remote_boards"]
    assert worker.enqueue_due(cfg, now) == []  # both still queued

    for run in first:
        store.finish_run(run.id, "completed")
    assert worker.enqueue_due(cfg, now + timedelta(minutes=30)) == []  # not due yet
    later = worker.enqueue_due(cfg, now + timedelta(minutes=61))
    assert sorted(run.pipeline for run in later) == ["mail_sync", "remote_boards"]
    assert tasks.active_run("liveness_sweep") is None


def test_pool_maintenance_enqueues_due_schedules():
    cfg = config.PipelineConfig.model_validate({"schedules": {"liveness_sweep": {"every_minutes": 60}}})
    started = threading.Event()
    sweep = Pipeline("liveness_sweep", (StepSpec("liveness_sweep", "code",
                                                 run=lambda ctx: started.set() or StepResult()),),
                     done_status="completed", scope="task")
    pool = _pool({"liveness_sweep": sweep}, load_config=lambda: cfg)
    pool.start()
    try:
        assert started.wait(5)
        assert _wait(lambda: tasks.active_run("liveness_sweep") is None)
    finally:
        pool.stop()
    runs = store.list_runs(tasks.task_job_id("liveness_sweep"))
    assert [run.status for run in runs] == ["completed"]


# --- lifespan switch ---------------------------------------------------------------------


class _FakePool:
    instances = []

    def __init__(self, size, **kwargs):
        self.size, self.started, self.stopped = size, False, False
        _FakePool.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.mark.parametrize("value, size", [(None, None), ("0", None), ("", None), ("junk", None), ("2", 2)])
def test_start_from_env_starts_nothing_unless_pipeline_workers_is_positive(monkeypatch, value, size):
    _FakePool.instances = []
    monkeypatch.setattr(worker, "WorkerPool", _FakePool)
    if value is None:
        monkeypatch.delenv("PIPELINE_WORKERS", raising=False)
    else:
        monkeypatch.setenv("PIPELINE_WORKERS", value)
    pool = worker.start_from_env()
    if size is None:
        assert pool is None and _FakePool.instances == []
    else:
        assert pool.size == size and pool.started


def test_app_lifespan_starts_and_stops_the_pool_only_when_enabled(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    _FakePool.instances = []
    monkeypatch.setattr(worker, "WorkerPool", _FakePool)
    monkeypatch.delenv("PIPELINE_WORKERS", raising=False)
    with TestClient(main.app):
        pass
    assert _FakePool.instances == []

    monkeypatch.setenv("PIPELINE_WORKERS", "1")
    with TestClient(main.app):
        assert _FakePool.instances[0].started and not _FakePool.instances[0].stopped
    assert _FakePool.instances[0].stopped


def test_research_via_pipeline_is_off_by_default():
    assert config.load_defaults().research_via_pipeline is False
    assert config.PipelineConfig.model_validate({"research_via_pipeline": True}).research_via_pipeline


def test_start_from_env_records_the_active_pool(monkeypatch):
    monkeypatch.setattr(worker, "WorkerPool", _FakePool)
    monkeypatch.setattr(worker, "ACTIVE_POOL", None)
    monkeypatch.setenv("PIPELINE_WORKERS", "1")
    pool = worker.start_from_env()
    assert worker.ACTIVE_POOL is pool
    worker.stop_pool(pool)
    assert pool.stopped and worker.ACTIVE_POOL is None


def test_stop_waits_one_deadline_for_the_whole_pool():
    entered, leave = threading.Event(), threading.Event()

    class Stuck(FakeAdapter):
        def invoke(self, step, ctx, errors):
            entered.set()
            leave.wait(5)  # an in process call that ignores the kill
            return AdapterResult(outcome="ok", output={"answer": "x"})

    pipeline = Pipeline("p", (_agent_step("s"),))
    runs = [store.create_run(_job().id, "p", pipeline.order) for _ in range(4)]
    cfg = config.PipelineConfig.model_validate({"adapters": {"a": {
        "type": "cli", "command": ["x", "{prompt}"], "capabilities": ["reason"], "max_parallel": 4}}})
    pool = _pool({"p": pipeline}, chain=lambda step: [Stuck("a", [])], size=4, shutdown_timeout=0.3,
                 load_config=lambda: cfg)
    pool.start()
    assert _wait(lambda: all(store.get_run(r.id).status == "running" for r in runs))
    t0 = time.monotonic()
    pool.stop()
    took = time.monotonic() - t0
    leave.set()
    for thread in pool.threads:  # let them finish inside this test's stores
        thread.join(5)
    assert took < 0.7
    assert {store.get_run(r.id).status for r in runs} == {"queued"}


def test_settings_workers_sets_how_many_threads_claim_and_zero_pauses():
    job = _job()
    pipeline = Pipeline("p", (StepSpec("a", "code", run=lambda ctx: StepResult()),))
    run = store.create_run(job.id, "p", pipeline.order)
    current = {"cfg": config.PipelineConfig.model_validate({"workers": 0})}
    pool = _pool({"p": pipeline}, size=2, load_config=lambda: current["cfg"])
    pool.start()
    try:
        time.sleep(0.3)
        assert store.get_run(run.id).status == "queued"  # paused from Settings
        assert pool.active_workers == 0
        current["cfg"] = config.PipelineConfig.model_validate({"workers": 4})
        assert _wait(_ended(run.id))
        assert pool.active_workers == 2  # capped by PIPELINE_WORKERS
    finally:
        pool.stop()


def test_a_capability_cap_of_zero_pauses_that_capability_instead_of_lifting_the_limit():
    calls = []

    class Records(FakeAdapter):
        def invoke(self, step, ctx, errors):
            calls.append(step.name)
            return AdapterResult(outcome="ok", output={"answer": "x"})

    cfg = config.PipelineConfig.model_validate({
        "adapters": {"a1": {"type": "cli", "command": ["x", "{prompt}"], "capabilities": ["browser_read"]}},
        "capability_caps": {"browser_read": 0}})
    pipeline = Pipeline("p", (_agent_step("s", capability="browser_read"),))
    run = store.create_run(_job().id, "p", pipeline.order)
    pool = _pool({"p": pipeline}, chain=lambda step: [Records("a1", [])], load_config=lambda: cfg)
    pool.start()
    try:
        assert not _wait(_ended(run.id), timeout=0.5)
    finally:
        pool.stop()
    assert calls == []
    assert store.get_run(run.id).status == "queued"
