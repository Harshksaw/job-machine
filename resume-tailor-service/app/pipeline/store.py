"""Pipeline runs and attempts, stored beside the dossiers: Postgres when DATABASE_URL
is set, one JSON file per collection otherwise (tests and CI).

Every change to a run is one read, modify, write transaction on that run, so worker
threads can save step states at the same time. Never call this module from inside a
job_store transaction or the reverse: the SQL backend reuses one transaction per thread
for any collection, so a nested call would write into the wrong collection.
"""
from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy import select

from app import doc_store
from app.pipeline.models import TERMINAL_STATUSES, Attempt, Run, StepState, now_iso

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RUNS = "pipeline_runs"
ATTEMPTS = "pipeline_attempts"
# A worker renews its lease every RENEW_SECONDS, well inside this window (M6); after a
# crash the run is free again once it lapses.
LEASE_SECONDS = 120
RENEW_SECONDS = 30

_LOCK = threading.RLock()
_JSON_BACKENDS: dict[Path, doc_store.JsonFileBackend] = {}
# Tests set this to a SqlBackend to run the same logic against SQL.
_BACKEND_OVERRIDE = None


class RunNotFound(KeyError):
    pass


class RunFinished(ValueError):
    """The run already has a terminal status."""


class RunActive(ValueError):
    """The run is still queued or running."""


class NotLeaseHolder(RuntimeError):
    """A worker tried to write a run (or its dossier) it no longer holds the lease of:
    the run was cancelled, retried or reaped since it last checked."""


def _require_owner(run: Run | None, owner: str | None) -> None:
    if owner is None:
        return
    if run is None or not owner or run.lease_owner != owner:
        held = run.lease_owner if run is not None else "nobody"
        raise NotLeaseHolder(f"run {run.id if run else '?'} is held by {held or 'nobody'}, not {owner}")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
    tmp.replace(path)


def _store(collection: str):
    backend = _BACKEND_OVERRIDE or doc_store.sql_backend_from_env()
    if backend is not None:
        return backend
    path = DATA_DIR / f"{collection}.json"
    with _LOCK:
        if path not in _JSON_BACKENDS:
            _JSON_BACKENDS[path] = doc_store.JsonFileBackend(
                lambda: _read(path), lambda items: _write(path, items), threading.RLock()
            )
        return _JSON_BACKENDS[path]


def _put_run(tx, run: Run) -> None:
    tx.put(
        run.model_dump(mode="json"),
        {"status": run.status, "match_key": run.job_id, "sort_key": run.created_at},
    )


def create_run(job_id: str, pipeline: str, order: list[str]) -> Run:
    now = now_iso()
    run = Run(
        id=uuid.uuid4().hex,
        job_id=job_id,
        pipeline=pipeline,
        order=list(order),
        steps={name: StepState() for name in order},
        created_at=now,
        updated_at=now,
    )
    with _store(RUNS).transaction(RUNS) as tx:
        _put_run(tx, run)
    return run


def get_run(run_id: str) -> Run | None:
    raw = _store(RUNS).get(RUNS, run_id)
    return Run.model_validate(raw) if raw is not None else None


def list_runs(job_id: str | None = None) -> list[Run]:
    runs = [Run.model_validate(raw) for raw in _store(RUNS).all(RUNS)]
    if job_id is not None:
        runs = [run for run in runs if run.job_id == job_id]
    return sorted(runs, key=lambda run: run.created_at, reverse=True)


def _mutate(run_id: str, change: Callable[[Run], None]) -> Run:
    with _store(RUNS).transaction(RUNS) as tx:
        raw = tx.get(run_id)
        if raw is None:
            raise RunNotFound(run_id)
        run = Run.model_validate(raw)
        change(run)
        run.updated_at = now_iso()
        _put_run(tx, run)
        return run


def update_step(run_id: str, step: str, *, owner: str | None = None, **changes) -> Run:
    """Change one step state. With `owner`, only while that worker holds the lease,
    checked in the same write (NotLeaseHolder otherwise)."""
    def change(run: Run) -> None:
        _require_owner(run, owner)
        run.steps[step] = run.steps[step].model_copy(update=changes)

    return _mutate(run_id, change)


def start_run(run_id: str) -> Run:
    """Mark a run running and put back any step that a crash left half done."""

    def change(run: Run) -> None:
        if run.status in TERMINAL_STATUSES:
            return
        run.status = "running"
        for name, state in run.steps.items():
            if state.status == "running":
                run.steps[name] = StepState()

    return _mutate(run_id, change)


def finish_run(run_id: str, status: str, reason: str = "", *, owner: str | None = None) -> Run:
    """End a run. The first terminal status wins; steps that never started are skipped.
    With `owner`, only while that worker holds the lease."""
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"{status!r} is not a terminal run status")

    def change(run: Run) -> None:
        _require_owner(run, owner)
        _finish(run, status, reason)

    return _mutate(run_id, change)


def complete_step(run_id: str, step: str, *, output: dict, stop: str = "", reason: str = "",
                  owner: str | None = None) -> Run:
    """Mark a step done and, when it stops the run, end the run in the same write, so a
    crash between the two cannot keep the step and lose the stop."""
    if stop and stop not in TERMINAL_STATUSES:
        raise ValueError(f"{stop!r} is not a terminal run status")

    def change(run: Run) -> None:
        _require_owner(run, owner)
        run.steps[step] = run.steps[step].model_copy(
            update={"status": "done", "output": output, "finished_at": now_iso()}
        )
        if stop:
            _finish(run, stop, reason)

    return _mutate(run_id, change)


def _finish(run: Run, status: str, reason: str) -> None:
    if run.status in TERMINAL_STATUSES:
        return
    run.status = status
    run.terminal_reason = reason
    for name, state in run.steps.items():
        if state.status == "pending":
            run.steps[name] = state.model_copy(update={"status": "skipped"})


@contextmanager
def lease_guard(run_id: str, owner: str | None) -> Iterator[None]:
    """Hold the run row while a dossier write happens, after checking `owner` still
    holds the lease (NotLeaseHolder otherwise), so a cancel or retry cannot land
    between the check and the write. Enter it inside the job_store transaction: on SQL
    the run row is read FOR UPDATE on that transaction's connection (a nested store
    transaction would reuse it under the wrong collection); on SQLite the backend's
    writer lock already serialises; with JSON files the runs file stays locked."""
    if owner is None:
        yield
        return
    backend = _store(RUNS)
    if isinstance(backend, doc_store.SqlBackend):
        active = getattr(backend._local, "tx", None)
        if active is None:
            with backend.transaction(RUNS) as tx:
                raw = tx.get(run_id)
                _require_owner(Run.model_validate(raw) if raw is not None else None, owner)
                yield
            return
        query = select(doc_store.documents.c.doc).where(
            (doc_store.documents.c.collection == RUNS) & (doc_store.documents.c.id == run_id))
        if active.conn.dialect.name == "postgresql":
            query = query.with_for_update()
        raw = active.conn.execute(query).scalar_one_or_none()
        _require_owner(Run.model_validate(raw) if raw is not None else None, owner)
        yield
        return
    with backend.transaction(RUNS) as tx:
        raw = tx.get(run_id)
        _require_owner(Run.model_validate(raw) if raw is not None else None, owner)
        yield


def acquire_lease(run_id: str, owner: str, seconds: int = LEASE_SECONDS) -> bool:
    now = datetime.now(timezone.utc)
    acquired = False

    def change(run: Run) -> None:
        nonlocal acquired
        held = (
            run.lease_owner
            and run.lease_owner != owner
            and run.lease_until
            and datetime.fromisoformat(run.lease_until) > now
        )
        if held:
            return
        run.lease_owner = owner
        run.lease_until = (now + timedelta(seconds=seconds)).isoformat()
        acquired = True

    _mutate(run_id, change)
    return acquired


def _lease_live(run: Run, now: datetime) -> bool:
    return bool(run.lease_owner and run.lease_until and datetime.fromisoformat(run.lease_until) > now)


def renew_lease(run_id: str, owner: str, seconds: int = LEASE_SECONDS) -> bool:
    """Extend the lease, only while `owner` still holds it."""
    now = datetime.now(timezone.utc)
    renewed = False

    def change(run: Run) -> None:
        nonlocal renewed
        if run.lease_owner == owner and owner:
            run.lease_until = (now + timedelta(seconds=seconds)).isoformat()
            renewed = True

    _mutate(run_id, change)
    return renewed


def claim(run_id: str, owner: str, seconds: int = LEASE_SECONDS) -> bool:
    """Take a queued run whose lease is free, in one write (the worker's claim)."""
    now = datetime.now(timezone.utc)
    taken = False

    def change(run: Run) -> None:
        nonlocal taken
        if run.status != "queued" or (_lease_live(run, now) and run.lease_owner != owner):
            return
        run.lease_owner = owner
        run.lease_until = (now + timedelta(seconds=seconds)).isoformat()
        taken = True

    _mutate(run_id, change)
    return taken


def reap_expired() -> list[str]:
    """Put back in the queue every run left `running` with no live lease: its worker
    crashed, stopped or lost the database. The next claim resumes it (start_run puts
    half done steps back), so a run that renews its lease is never touched."""
    reaped = []
    for candidate in list_runs():
        if candidate.status != "running" or _lease_live(candidate, datetime.now(timezone.utc)):
            continue

        def change(run: Run) -> None:
            if run.status == "running" and not _lease_live(run, datetime.now(timezone.utc)):
                run.status = "queued"
                run.lease_owner = ""
                run.lease_until = ""
                reaped.append(run.id)

        try:
            _mutate(candidate.id, change)
        except RunNotFound:
            continue
    return reaped


def cancel_run(run_id: str, reason: str) -> Run:
    """End a queued or running run as cancelled and free its lease whoever holds it. A
    step still running is marked failed; its worker sees the status and stops."""

    def change(run: Run) -> None:
        if run.status in TERMINAL_STATUSES:
            raise RunFinished(f"run {run_id} already ended {run.status}")
        for name, state in run.steps.items():
            if state.status == "running":
                run.steps[name] = state.model_copy(update={"status": "failed", "error": "cancelled",
                                                           "finished_at": now_iso()})
        _finish(run, "cancelled", reason)
        run.lease_owner = ""
        run.lease_until = ""

    return _mutate(run_id, change)


def reset_for_retry(run_id: str, steps: set[str]) -> Run:
    """Queue a finished run again with `steps` back to pending; other steps keep their
    state and output, so the run resumes where it stopped."""

    def change(run: Run) -> None:
        if run.status not in TERMINAL_STATUSES:
            raise RunActive(f"run {run_id} is still {run.status}")
        unknown = sorted(set(steps) - set(run.steps))
        if unknown:
            raise KeyError(f"run {run_id} has no step {', '.join(unknown)}")
        for name in steps:
            run.steps[name] = StepState()
        run.status = "queued"
        run.terminal_reason = ""
        run.lease_owner = ""
        run.lease_until = ""

    return _mutate(run_id, change)


def requeue(run_id: str) -> Run:
    """Put a run its worker abandoned (shutdown) back in the queue, if it is still running."""

    def change(run: Run) -> None:
        if run.status == "running":
            run.status = "queued"

    return _mutate(run_id, change)


def release_lease(run_id: str, owner: str) -> None:
    def change(run: Run) -> None:
        if run.lease_owner == owner:
            run.lease_owner = ""
            run.lease_until = ""

    _mutate(run_id, change)


def add_attempt(attempt: Attempt) -> None:
    with _store(ATTEMPTS).transaction(ATTEMPTS) as tx:
        tx.put(
            attempt.model_dump(mode="json"),
            {"status": attempt.outcome, "match_key": attempt.run_id, "sort_key": attempt.started_at},
        )


def list_attempts(run_id: str | None = None) -> list[Attempt]:
    attempts = [Attempt.model_validate(raw) for raw in _store(ATTEMPTS).all(ATTEMPTS)]
    if run_id is not None:
        attempts = [attempt for attempt in attempts if attempt.run_id == run_id]
    return sorted(attempts, key=lambda attempt: attempt.started_at)
