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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app import doc_store
from app.pipeline.models import TERMINAL_STATUSES, Attempt, Run, StepState, now_iso

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RUNS = "pipeline_runs"
ATTEMPTS = "pipeline_attempts"
# A worker renews its lease well inside this window (M6); after a crash the run is
# free again once it lapses.
LEASE_SECONDS = 120

_LOCK = threading.RLock()
_JSON_BACKENDS: dict[Path, doc_store.JsonFileBackend] = {}
# Tests set this to a SqlBackend to run the same logic against SQL.
_BACKEND_OVERRIDE = None


class RunNotFound(KeyError):
    pass


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


def update_step(run_id: str, step: str, **changes) -> Run:
    def change(run: Run) -> None:
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


def finish_run(run_id: str, status: str, reason: str = "") -> Run:
    """End a run. The first terminal status wins; steps that never started are skipped."""
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"{status!r} is not a terminal run status")

    return _mutate(run_id, lambda run: _finish(run, status, reason))


def complete_step(run_id: str, step: str, *, output: dict, stop: str = "", reason: str = "") -> Run:
    """Mark a step done and, when it stops the run, end the run in the same write, so a
    crash between the two cannot keep the step and lose the stop."""
    if stop and stop not in TERMINAL_STATUSES:
        raise ValueError(f"{stop!r} is not a terminal run status")

    def change(run: Run) -> None:
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
