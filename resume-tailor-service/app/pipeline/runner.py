"""Runs one pipeline run for one dossier.

Steps run in dependency order, and every step whose dependencies are met runs at the
same time in its own thread. Each step state is saved the moment it changes, so after
a crash or restart `run()` resumes at the first step that did not finish. A step may
write only the dossier fields it owns, and only through `job_store.patch_job`. Agent
steps go through an adapter chain (see `_run_agent`).

A pipeline with `scope="task"` (mail sync, update checks) belongs to no dossier: its
run carries the sentinel job id `task:<pipeline>`, its steps see `ctx.job = None`, and it
may own no dossier fields, so any `writes` it returns fail the run as a policy breach.
Everything else (store, leases, resume, ledger, adapter chain) is the same.

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Protocol

from pydantic import BaseModel, ValidationError

from app import job_store
from app.models import JobWorkspace
from app.pipeline import store
from app.pipeline.models import TERMINAL_STATUSES, AdapterResult, Attempt, Run, now_iso

STEP_KINDS = ("code", "service", "agent")
SCOPES = ("dossier", "task")
TASK_PREFIX = "task:"


def task_job_id(pipeline: str) -> str:
    """The sentinel job id of a task run."""
    return f"{TASK_PREFIX}{pipeline}"


@dataclass
class StepContext:
    run: Run
    # None in a task run, which belongs to no dossier.
    job: JobWorkspace | None
    outputs: dict[str, dict]


@dataclass
class StepResult:
    output: dict = field(default_factory=dict)
    writes: dict = field(default_factory=dict)
    # A terminal run status that ends the run early, such as "retained_for_review".
    stop: str = ""
    reason: str = ""


@dataclass(frozen=True)
class StepSpec:
    name: str
    kind: str
    deps: tuple[str, ...] = ()
    owns: tuple[str, ...] = ()
    capability: str = ""
    run: Callable[[StepContext], StepResult] | None = None
    schema: type[BaseModel] | None = None
    finish: Callable[[BaseModel, StepContext], StepResult] | None = None
    when: Callable[[StepContext], bool] | None = None
    # Steps whose authors (output meta.authors, the adapters that wrote them) must not
    # run this one, such as review checking the kit and answers (spec 6.4).
    independent_of: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"step {self.name}: kind must be one of {STEP_KINDS}")
        if self.kind == "agent":
            if self.schema is None or self.finish is None or not self.capability:
                raise ValueError(f"agent step {self.name} needs schema, finish and capability")
        elif self.run is None:
            raise ValueError(f"{self.kind} step {self.name} needs run")


class Adapter(Protocol):
    name: str

    def invoke(self, step: StepSpec, ctx: StepContext, errors: list[str]) -> AdapterResult: ...


@dataclass(frozen=True)
class Pipeline:
    name: str
    steps: tuple[StepSpec, ...]
    done_status: str = "packet_ready"
    scope: str = "dossier"

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"pipeline {self.name}: scope must be one of {SCOPES}")
        if self.scope == "task":
            owning = [step.name for step in self.steps if step.owns]
            if owning:
                raise ValueError(f"task pipeline {self.name} may not own dossier fields ({', '.join(owning)})")
        names = [step.name for step in self.steps]
        if len(set(names)) != len(names):
            raise ValueError(f"pipeline {self.name} has duplicate step names")
        # Requiring dependencies to be listed first makes the listing a valid order
        # and rules out cycles without a graph search.
        listed: set[str] = set()
        for step in self.steps:
            missing = [dep for dep in step.deps if dep not in listed]
            if missing:
                raise ValueError(
                    f"step {step.name} depends on {', '.join(missing)}, which must be listed before it"
                )
            listed.add(step.name)
        if self.done_status not in TERMINAL_STATUSES:
            raise ValueError(f"done_status {self.done_status!r} is not a terminal run status")

    @property
    def order(self) -> list[str]:
        return [step.name for step in self.steps]


class LeaseHeld(RuntimeError):
    pass


class RunAbandoned(BaseException):
    """The worker is shutting down. Like a crash, it leaves the run `running` with its
    current step half done, so the next claim resumes it; never caught by step code."""


class StepFailed(Exception):
    def __init__(self, message: str, *, policy: bool = False):
        super().__init__(message)
        self.policy = policy


Chain = Callable[[StepSpec], list[Adapter]]


def _no_adapters(step: StepSpec) -> list[Adapter]:
    return []


def run(run_id: str, pipeline: Pipeline, *, owner: str, resolve_chain: Chain = _no_adapters,
        stop: threading.Event | None = None, renew_every: float = store.RENEW_SECONDS,
        lease_seconds: int = store.LEASE_SECONDS) -> Run:
    """Run until the run ends. The lease is renewed every `renew_every` seconds while it
    runs, so the reaper or a second worker can never take over an in flight step. A set
    `stop` event abandons the run (RunAbandoned) at the next step or adapter boundary."""
    if not store.acquire_lease(run_id, owner, seconds=lease_seconds):
        raise LeaseHeld(f"run {run_id} is leased by another worker")
    stop = stop or threading.Event()
    done_renewing = threading.Event()

    def renew() -> None:
        while not done_renewing.wait(renew_every):
            try:
                store.renew_lease(run_id, owner, seconds=lease_seconds)
            except Exception:
                pass  # a database blip; the next tick tries again, well inside the lease

    renewer = threading.Thread(target=renew, name=f"lease-{run_id[:8]}", daemon=True)
    renewer.start()
    try:
        current = store.get_run(run_id)
        if current.pipeline != pipeline.name or current.order != pipeline.order:
            raise ValueError(f"run {run_id} does not match pipeline {pipeline.name}")
        task = pipeline.scope == "task"
        if task != current.job_id.startswith(TASK_PREFIX):
            raise ValueError(f"run {run_id} job id {current.job_id!r} does not fit a {pipeline.scope} pipeline")
        current = store.start_run(run_id)
        specs = {step.name: step for step in pipeline.steps}
        while current.status not in TERMINAL_STATUSES:
            ready = [
                specs[name]
                for name in current.order
                if current.steps[name].status == "pending"
                and all(current.steps[dep].status in ("done", "skipped") for dep in specs[name].deps)
            ]
            if stop.is_set():
                raise RunAbandoned(run_id)
            if not ready:
                failed = [name for name in current.order if current.steps[name].status == "failed"]
                if failed:
                    first = failed[0]
                    current = store.finish_run(run_id, "failed", f"{first}: {current.steps[first].error}")
                else:
                    current = store.finish_run(run_id, pipeline.done_status)
                break
            with ThreadPoolExecutor(max_workers=len(ready)) as pool:
                # list() re-raises anything a step thread raised, including a crash.
                list(pool.map(lambda step: _execute(run_id, step, resolve_chain, stop), ready))
            current = store.get_run(run_id)
        return current
    finally:
        done_renewing.set()
        renewer.join(timeout=5)
        store.release_lease(run_id, owner)


def _check_interrupt(run_id: str, stop: threading.Event) -> None:
    """Between adapter tries and before a write: stop for a shutdown or a cancel."""
    if stop.is_set():
        raise RunAbandoned(run_id)
    current = store.get_run(run_id)
    if current is not None and current.status == "cancelled":
        raise StepFailed("run cancelled")


def _execute(run_id: str, step: StepSpec, resolve_chain: Chain, stop: threading.Event) -> None:
    try:
        ctx = _context(run_id)
        if step.when is not None and not step.when(ctx):
            store.update_step(run_id, step.name, status="skipped", finished_at=now_iso())
            return
        store.update_step(run_id, step.name, status="running", started_at=now_iso(), error="")
        if step.kind == "agent":
            result = _run_agent(step, ctx, resolve_chain, stop)
        else:
            result = _run_local(step, ctx)
        _check_interrupt(run_id, stop)
        _apply(step, ctx, result)
    except Exception as exc:
        # Anything a step, adapter or store raises fails this step; only a crash
        # (BaseException) escapes, and resume handles that.
        failure = exc if isinstance(exc, StepFailed) else StepFailed(_short(exc))
        store.update_step(run_id, step.name, status="failed", error=str(failure), finished_at=now_iso())
        if failure.policy:
            store.finish_run(run_id, "failed", f"{step.name}: {failure}")
        return
    store.complete_step(run_id, step.name, output=result.output, stop=result.stop, reason=result.reason)


def _context(run_id: str) -> StepContext:
    current = store.get_run(run_id)
    # run() has already checked that the job id fits the pipeline scope.
    task = current.job_id.startswith(TASK_PREFIX)
    job = None if task else job_store.get_job(current.job_id)
    if job is None and not task:
        raise StepFailed(f"dossier {current.job_id} no longer exists")
    outputs = {
        name: state.output or {}
        for name, state in current.steps.items()
        if state.status == "done"
    }
    return StepContext(run=current, job=job, outputs=outputs)


def _short(exc: BaseException) -> str:
    if isinstance(exc, StepFailed):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"[:300]


def _record(ctx: StepContext, step: StepSpec, adapter: str, started: str, t0: float,
            result: AdapterResult) -> None:
    store.add_attempt(
        Attempt(
            id=uuid.uuid4().hex,
            run_id=ctx.run.id,
            job_id=ctx.run.job_id,
            step=step.name,
            adapter=adapter,
            model=result.model,
            prompt_version=result.prompt_version,
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
            outcome=result.outcome,
            error=result.error,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=result.cost,
            output_ref=result.output_ref,
        )
    )


def _run_local(step: StepSpec, ctx: StepContext) -> StepResult:
    started, t0 = now_iso(), time.monotonic()
    try:
        result = step.run(ctx)
    except Exception as exc:
        _record(ctx, step, step.kind, started, t0, AdapterResult(outcome="error", error=_short(exc)))
        raise StepFailed(_short(exc)) from exc
    _record(ctx, step, step.kind, started, t0, AdapterResult(outcome="ok"))
    return result


def _run_agent(step: StepSpec, ctx: StepContext, resolve_chain: Chain,
               stop: threading.Event | None = None) -> StepResult:
    """Try each adapter in the chain. Invalid output gets one more try on the same
    adapter with the error list; unavailable, timeout and error move on at once; a
    policy violation fails the step, which fails the run."""
    chain = resolve_chain(step)
    if not chain:
        raise StepFailed(f"no adapter offers capability {step.capability!r}")
    authors = authors_of(ctx, step.independent_of)
    if authors:
        chain = [adapter for adapter in chain if adapter.name not in authors]
        if not chain:
            raise StepFailed(f"no adapter other than {', '.join(sorted(authors))} offers capability "
                             f"{step.capability!r}; enable another one so the work is not checked by its author")
    last = ""
    for adapter in chain:
        errors: list[str] = []
        for _ in range(2):
            _check_interrupt(ctx.run.id, stop or threading.Event())
            started, t0 = now_iso(), time.monotonic()
            try:
                result = adapter.invoke(step, ctx, errors)
            except Exception as exc:
                result = AdapterResult(outcome="error", error=_short(exc))
            # A cancel kills the adapter's process; its broken output must not count
            # as a try or start a second one.
            _check_interrupt(ctx.run.id, stop or threading.Event())
            parsed = None
            if result.outcome == "ok":
                try:
                    parsed = step.schema.model_validate(result.output or {})
                except ValidationError as exc:
                    errors = [
                        f"{'.'.join(str(part) for part in error['loc']) or 'output'}: {error['msg']}"
                        for error in exc.errors()
                    ]
                    result = result.model_copy(
                        update={"outcome": "invalid_output", "error": "; ".join(errors)[:300]}
                    )
            elif result.outcome == "invalid_output":
                errors = [result.error or "output was not a JSON object"]
            _record(ctx, step, adapter.name, started, t0, result)
            if parsed is not None:
                try:
                    return step.finish(parsed, ctx)
                except Exception as exc:
                    raise StepFailed(_short(exc)) from exc
            last = f"{adapter.name}: {result.outcome} {result.error}".strip()
            if result.outcome == "policy_violation":
                raise StepFailed(last, policy=True)
            if result.outcome != "invalid_output":
                break
    raise StepFailed(f"every adapter failed; last: {last}")


def authors_of(ctx: StepContext, steps: tuple[str, ...]) -> set[str]:
    """The adapters that wrote the outputs of `steps` in this run."""
    authors: set[str] = set()
    for name in steps:
        meta = (ctx.outputs.get(name) or {}).get("meta") or {}
        authors.update(str(author) for author in meta.get("authors") or [] if author)
    return authors


def _apply(step: StepSpec, ctx: StepContext, result: StepResult) -> None:
    if result.stop and result.stop not in TERMINAL_STATUSES:
        raise StepFailed(f"unknown stop status {result.stop!r}")
    stray = sorted(set(result.writes) - set(step.owns))
    if stray:
        raise StepFailed(f"wrote fields it does not own: {', '.join(stray)}", policy=True)
    if not result.writes:
        return
    try:
        updated = job_store.patch_job(
            ctx.run.job_id,
            result.writes,
            reason=f"Pipeline run {ctx.run.id} step {step.name}",
            session=f"pipeline {ctx.run.id}",
        )
    except ValueError as exc:
        raise StepFailed(f"dossier rejected the write: {_short(exc)}") from exc
    if updated is None:
        raise StepFailed(f"dossier {ctx.run.job_id} no longer exists")
