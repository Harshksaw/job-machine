"""The worker pool that executes queued pipeline runs (M6, spec section 8).

Started from the FastAPI lifespan only when the `PIPELINE_WORKERS` env var is a
positive number; unset or 0 starts nothing, so merging this code changes nothing until
Harsh turns it on. `PIPELINE_WORKERS` is the switch and the most threads this process
starts; `workers` in the stored config (Settings, seeded from agents.yaml, spec section
8) is how many of them claim runs, read every tick, so 0 pauses the pool and a change
applies without a restart. Each claiming worker thread:

1. claims the oldest queued run whose lease is free (`store.claim`, one write, so two
   threads or two service copies never take the same run);
2. runs it with `runner.run` and the router chain; the runner renews the lease every
   30s while the run is active, so a takeover can never reset an in flight step;
3. on shutdown, abandons the run at the next step or adapter boundary and puts it back
   in the queue, after killing its CLI processes.

One maintenance thread, every `tick` seconds, reaps runs left `running` with a lapsed
lease (back to `queued`; the next claim resumes them) and enqueues task pipelines whose
schedule is due (`schedules` in the stored config, off by default; one active run per
task, the same rule as POST /api/pipeline/runs).

Per adapter `max_parallel` and per capability caps (`capability_caps`, such as
`browser_read: 2`) are semaphores around each adapter call, shared by every worker in
this process. Service steps (kit, answers) make their own model calls through
`llm.complete` and are not gated here.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Callable

from app.pipeline import adapters, runner, store, tasks
from app.pipeline import config as config_module
from app.pipeline.config import PipelineConfig
from app.pipeline.models import TERMINAL_STATUSES, Run
from app.pipeline.runner import Pipeline, RunAbandoned

log = logging.getLogger(__name__)

ENV = "PIPELINE_WORKERS"
MAX_WORKERS = 32
POLL_SECONDS = 2.0
TICK_SECONDS = 30.0
SHUTDOWN_SECONDS = 15.0
_GATE_WAIT = 0.25
# The pool the app lifespan started, for GET /api/pipeline/worker; None when off.
ACTIVE_POOL = None


def pipeline_for(name: str) -> Pipeline | None:
    """The pipeline a stored run names: `packet` or a task pipeline."""
    if name == "packet":
        from app.pipeline.pipelines import PACKET_PIPELINE

        return PACKET_PIPELINE
    if name in tasks.TASK_BUILDERS:
        return tasks.task_pipeline(name)
    return None


# --- concurrency caps -------------------------------------------------------------------


class Gates:
    """Named semaphores. A size change in the config makes a new semaphore; calls
    already holding the old one release it as they finish."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sems: dict[str, tuple[int, threading.Semaphore]] = {}

    def _sem(self, key: str, size: int) -> threading.Semaphore:
        with self._lock:
            held = self._sems.get(key)
            if held is None or held[0] != size:
                held = (size, threading.Semaphore(size))
                self._sems[key] = held
            return held[1]

    @contextmanager
    def hold(self, keys: list[tuple[str, int]], stop: threading.Event):
        # Always the same order (capability first, then adapter), so two calls never
        # wait on each other in a cycle.
        taken: list[threading.Semaphore] = []
        try:
            for key, size in keys:
                sem = self._sem(key, size)
                while not sem.acquire(timeout=_GATE_WAIT):
                    if stop.is_set():
                        raise RunAbandoned(key)
                taken.append(sem)
            yield
        finally:
            for sem in reversed(taken):
                sem.release()


class GatedAdapter:
    """An adapter whose calls wait for its own and its capability's semaphore."""

    def __init__(self, inner, gates: Gates, keys: list[tuple[str, int]], stop: threading.Event):
        self._inner = inner
        self._gates = gates
        self._keys = keys
        self._stop = stop
        self.name = inner.name

    def invoke(self, step, ctx, errors: list[str]):
        with self._gates.hold(self._keys, self._stop):
            return self._inner.invoke(step, ctx, errors)


def gated_chain(chain: runner.Chain, gates: Gates, load_config: Callable[[], PipelineConfig],
                stop: threading.Event) -> runner.Chain:
    def resolve(step) -> list:
        cfg = load_config()
        cap = cfg.capability_caps.get(step.capability)
        out = []
        for adapter in chain(step):
            keys = [(f"capability:{step.capability}", cap)] if cap else []
            spec = cfg.adapters.get(adapter.name)
            keys.append((f"adapter:{adapter.name}", spec.max_parallel if spec else 1))
            out.append(GatedAdapter(adapter, gates, keys, stop))
        return out

    return resolve


# --- schedules --------------------------------------------------------------------------


def _created(run: Run) -> datetime:
    moment = datetime.fromisoformat(run.created_at)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def enqueue_due(cfg: PipelineConfig, now: datetime | None = None) -> list[Run]:
    """Queue every scheduled task whose newest run started at least its interval ago
    and which has no queued or running run."""
    now = now or datetime.now(timezone.utc)
    queued = []
    for name, schedule in cfg.schedules.items():
        if not schedule.enabled or name not in tasks.TASK_BUILDERS:
            continue
        runs = store.list_runs(runner.task_job_id(name))  # newest first
        if runs and now - _created(runs[0]) < timedelta(minutes=schedule.every_minutes):
            continue
        run, _active = tasks.enqueue_if_idle(name)
        if run is not None:
            queued.append(run)
    return queued


# --- the pool ---------------------------------------------------------------------------


def _default_chain() -> runner.Chain:
    from app.pipeline import router

    # The process wide health view, shared with the settings API and llm.complete.
    return router.make_chain(health=router.HEALTH)


class WorkerPool:
    def __init__(self, size: int, *, pipeline_for: Callable[[str], Pipeline | None] = pipeline_for,
                 chain: runner.Chain | None = None,
                 load_config: Callable[[], PipelineConfig] = config_module.load_config,
                 poll: float = POLL_SECONDS, tick: float = TICK_SECONDS,
                 shutdown_timeout: float = SHUTDOWN_SECONDS, owner_prefix: str | None = None):
        self.size = max(1, min(int(size), MAX_WORKERS))
        self._pipeline_for = pipeline_for
        self._load_config = load_config
        self._poll = poll
        self._tick = tick
        self._shutdown_timeout = shutdown_timeout
        self._prefix = owner_prefix or f"worker-{socket.gethostname()}-{os.getpid()}"
        self._stop = threading.Event()
        self._gates = Gates()
        self._chain = gated_chain(chain or _default_chain(), self._gates, load_config, self._stop)
        self._active: dict[str, str] = {}  # owner -> run id
        # How many threads may claim now: Settings `workers`, capped by `size`.
        self.active_workers = 0
        self._active_lock = threading.Lock()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.threads:
            return
        self._refresh_target()
        for index in range(self.size):
            owner = f"{self._prefix}-{index}"
            self.threads.append(threading.Thread(target=self._loop, args=(owner, index), name=owner, daemon=True))
        self.threads.append(threading.Thread(target=self._maintain, name=f"{self._prefix}-maint", daemon=True))
        for thread in self.threads:
            thread.start()
        log.info("pipeline worker pool started with %s workers", self.size)

    def stop(self) -> None:
        """Stop claiming, abandon in flight runs at their next boundary (their CLI
        processes are killed so that comes quickly), and wait for the threads. A run
        still stuck in an in process model call keeps its lease until it lapses; the
        reaper of the next start puts it back."""
        self._stop.set()
        with self._active_lock:
            active = list(self._active.values())
        for run_id in active:
            try:
                adapters.kill_run(run_id)
            except Exception:
                log.exception("could not kill the processes of run %s", run_id)
        # One deadline for the whole pool, so shutdown never waits longer than that.
        deadline = time.monotonic() + self._shutdown_timeout
        for thread in self.threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        log.info("pipeline worker pool stopped")

    # -- threads --

    def _maintain(self) -> None:
        while not self._stop.is_set():
            self.maintain()
            self._stop.wait(self._tick)

    def _refresh_target(self) -> PipelineConfig | None:
        try:
            cfg = self._load_config()
        except Exception:
            log.exception("could not read the pipeline config; keeping %s workers", self.active_workers)
            return None
        self.active_workers = max(0, min(self.size, cfg.workers))
        return cfg

    def maintain(self) -> None:
        cfg = self._refresh_target()
        try:
            for run_id in store.reap_expired():
                log.info("requeued run %s after its lease lapsed", run_id)
        except Exception:
            log.exception("reaper failed")
        try:
            for run in enqueue_due(cfg) if cfg is not None else []:
                log.info("scheduled %s run %s", run.pipeline, run.id)
        except Exception:
            log.exception("schedules failed")

    def _loop(self, owner: str, index: int = 0) -> None:
        while not self._stop.is_set():
            if index >= self.active_workers:
                self._stop.wait(self._poll)
                continue
            try:
                run = self.claim_next(owner)
            except Exception:
                log.exception("claim failed")
                run = None
            if run is None:
                self._stop.wait(self._poll)
                continue
            self.execute(run, owner)

    def claim_next(self, owner: str) -> Run | None:
        queued = [run for run in store.list_runs() if run.status == "queued"]
        for run in sorted(queued, key=lambda r: r.created_at):  # oldest first
            if store.claim(run.id, owner):
                return run
        return None

    def execute(self, run: Run, owner: str) -> None:
        pipeline = self._pipeline_for(run.pipeline)
        if pipeline is None:
            store.release_lease(run.id, owner)
            self._fail(run.id, f"no pipeline named {run.pipeline!r}")
            return
        with self._active_lock:
            self._active[owner] = run.id
        try:
            runner.run(run.id, pipeline, owner=owner, resolve_chain=self._chain, stop=self._stop)
        except runner.LeaseHeld:
            pass
        except RunAbandoned:
            store.requeue(run.id)
        except Exception as exc:
            # A run that cannot start (pipeline changed, bad job id) would otherwise
            # loop through the reaper forever.
            log.exception("run %s failed outside its steps", run.id)
            self._fail(run.id, f"{type(exc).__name__}: {exc}"[:300])
        finally:
            with self._active_lock:
                self._active.pop(owner, None)
            store.release_lease(run.id, owner)

    def _fail(self, run_id: str, reason: str) -> None:
        current = store.get_run(run_id)
        if current is not None and current.status not in TERMINAL_STATUSES:
            store.finish_run(run_id, "failed", reason)


def workers_from_env() -> int:
    raw = os.environ.get(ENV, "").strip()
    try:
        return max(0, min(int(raw), MAX_WORKERS)) if raw else 0
    except ValueError:
        log.warning("%s=%r is not a number; no pipeline workers started", ENV, raw)
        return 0


def start_from_env() -> WorkerPool | None:
    """The lifespan hook: a started pool when PIPELINE_WORKERS > 0, else None."""
    global ACTIVE_POOL
    size = workers_from_env()
    if size <= 0:
        return None
    pool = WorkerPool(size)
    pool.start()
    ACTIVE_POOL = pool
    return pool


def stop_pool(pool) -> None:
    global ACTIVE_POOL
    if pool is None:
        return
    pool.stop()
    if ACTIVE_POOL is pool:
        ACTIVE_POOL = None
