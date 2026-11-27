# Agent Orchestrator M1 (Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Agents without those skills (Cursor, Codex, Antigravity): do the tasks in order, run every command shown, and do not start a task until the previous one is committed.

**Goal:** Build the orchestrator core: a dossier PATCH that changes only named fields, durable pipeline runs with leases and an attempt ledger, and a runner that executes a step DAG with adapter fallback and resumes after a crash.

**Architecture:** A new package `resume-tailor-service/app/pipeline/` stores runs and attempts as documents in the existing `documents` table (JSON file fallback when no `DATABASE_URL`), exactly like `app/research_store.py`. The runner walks steps in dependency order, runs ready steps in parallel threads, saves each step state the moment it changes, and writes to the dossier only through `job_store.patch_job`, limited to the fields each step owns. Agent steps call adapters through a small protocol; M1 ships only a `FakeAdapter` for tests. Real adapters, the router and real steps come in M2 to M4.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy (SQLite in tests, Postgres in production), pytest, uv.

**Spec:** `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` (sections 3, 4, 5.1, 5.3, 7, 8, 10 and milestone M1 in section 11).

## Global Constraints

- Read `AGENTS.md` first. The `origin` remote is PUBLIC: no personal data in code, tests or fixtures.
- All commands run from `resume-tailor-service/` with `.venv/bin/python -m pytest`. The suite must pass with no `.env` and no agent CLIs installed (CI rule).
- Baseline before Task 1: `388 passed`. Every task ends with the full suite green.
- Timestamps are ISO 8601 UTC from `datetime.now(timezone.utc).isoformat()`.
- New collections: `pipeline_runs`, `pipeline_attempts` (the `collection` column is `String(32)`).
- **Never nest a pipeline store transaction inside a job store transaction or the reverse.** `SqlBackend.transaction` keeps one transaction per thread and reuses it for any collection, so a nested call would write pipeline documents into the `jobs` collection. The runner calls the two stores one after the other, never inside each other.
- Terminal run statuses (copied from the spec): `packet_ready`, `retained_for_review`, `ineligible`, `closed_posting`, `failed`, `cancelled`.
- Attempt outcomes (spec 5.3 plus `error` for a code step that raised): `ok`, `unavailable`, `timeout`, `invalid_output`, `policy_violation`, `error`.
- Match the house style: module docstring explaining why, short comments only where the reason is not obvious, no em dashes in text.

## Review Focus

1. A step returns a write for a field it does not own: the dossier must stay unchanged and the run must end `failed` as a policy violation (test in Task 3).
2. The dossier is deleted while a run is in flight: the step fails with a readable error, the runner does not crash (test in Task 3).
3. An adapter returns JSON that never satisfies the schema: one retry on the same adapter with the errors, then the next adapter; when all fail, the run ends `failed` with the last error in `terminal_reason` (test in Task 4).
4. Two workers start the same run: the second gets `LeaseHeld` and changes nothing (tests in Tasks 2 and 3).
5. One parallel step stops the run while a sibling later fails: the first terminal status wins and is not overwritten (tests in Tasks 2 and 3).

---

## File Structure

| File | Responsibility |
|---|---|
| `app/job_store.py` (modify) | Add `patch_job`: merge named fields into the current dossier, reject unknown names |
| `app/jobs.py` (modify) | Add `PATCH /api/jobs/{job_id}` |
| `app/pipeline/__init__.py` (create) | Package marker with a one line docstring |
| `app/pipeline/models.py` (create) | `Run`, `StepState`, `Attempt`, `AdapterResult`, status constants, `now_iso` |
| `app/pipeline/store.py` (create) | Run and attempt persistence, leases, step state changes |
| `app/pipeline/runner.py` (create) | `StepSpec`, `Pipeline`, `StepContext`, `StepResult`, `Adapter` protocol, `run()` |
| `app/pipeline/fake.py` (create) | `FakeAdapter` that replays scripted `AdapterResult`s |
| `tests/test_job_store.py`, `tests/test_jobs_api.py` (modify) | PATCH tests (auto rerun on SQL by `tests/test_job_store_sql.py`) |
| `tests/test_pipeline_store.py` (create) | Store tests on JSON and SQLite |
| `tests/test_pipeline_runner.py` (create) | Runner tests for code steps, writes, stops, resume, leases |
| `tests/test_pipeline_agents.py` (create) | Runner tests for agent steps through `FakeAdapter` |

---

### Task 1: `patch_job` and `PATCH /api/jobs/{job_id}`

**Files:**
- Modify: `app/job_store.py` (add after `update_job`, which ends near line 413)
- Modify: `app/jobs.py` (add after `replace_job`, near line 335; add `Body` to the fastapi import on line 9)
- Test: `tests/test_job_store.py`, `tests/test_jobs_api.py`

**Interfaces:**
- Consumes: `job_store.update_job(job_id, data: JobWorkspaceInput, *, reason, activity_kind, session) -> JobWorkspace | None`, `job_store._input_from_job`, `job_store.get_job`.
- Produces: `job_store.patch_job(job_id: str, fields: dict, *, reason: str = "Dossier patched", activity_kind: str = "updated", session: str = "") -> JobWorkspace | None`. Raises `ValueError` for unknown field names or an invalid merged dossier (Pydantic `ValidationError` is a `ValueError`). Returns `None` when the dossier does not exist. HTTP: `PATCH /api/jobs/{job_id}?session=...` with a JSON object body; `422` for unknown fields, invalid values or an empty body, `404` for a missing dossier.

Gotcha to keep: `update_job` normalizes `fit_score` from `fit_analysis.score` when `fit_analysis` is set. A patch of `fit_score` alone on a dossier with a `fit_analysis` is overridden by that score. That is existing behavior; the M4 `fit_score` step must write both or neither.

- [ ] **Step 1: Write the failing store tests**

Append to `tests/test_job_store.py`:

```python
def test_patch_changes_only_named_fields(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    created = job_store.add_job(
        JobWorkspaceInput(
            company="Acme",
            role="Backend Engineer",
            notes="keep me",
            cover_letter="Dear Acme",
        )
    )

    patched = job_store.patch_job(
        created.id,
        {"apply_url": "https://jobs.ashbyhq.com/acme/1"},
        reason="Pipeline run r1 step resolve_apply_url",
        session="pipeline r1",
    )

    assert patched.apply_url == "https://jobs.ashbyhq.com/acme/1"
    assert patched.notes == "keep me"
    assert patched.cover_letter == "Dear Acme"
    assert patched.revisions[-1].reason == "Pipeline run r1 step resolve_apply_url"
    assert patched.revisions[-1].changed_fields == ["apply_url"]


def test_patch_rejects_unknown_fields_and_bad_values(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    created = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))

    with pytest.raises(ValueError, match="unknown dossier fields: nope"):
        job_store.patch_job(created.id, {"nope": 1})
    with pytest.raises(ValueError):
        job_store.patch_job(created.id, {"status": "not-a-status"})
    with pytest.raises(ValueError):
        job_store.patch_job(created.id, {"company": "  "})

    assert job_store.get_job(created.id).revisions == created.revisions


def test_patch_missing_dossier_returns_none(monkeypatch, tmp_path):
    _use_temp_store(monkeypatch, tmp_path)
    assert job_store.patch_job("0" * 32, {"notes": "x"}) is None
```

- [ ] **Step 2: Write the failing API tests**

Append to `tests/test_jobs_api.py` (it already has `_client` and `_create`):

```python
def test_patch_job_changes_only_sent_fields(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)

    response = client.patch(
        f"/api/jobs/{job['id']}?session=pipeline%20r1",
        json={"company_context": "They build search."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company_context"] == "They build search."
    assert body["jd_text"] == job["jd_text"]
    assert body["activities"][-1]["session"] == "pipeline r1"


def test_patch_job_rejects_bad_bodies(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    job = _create(client)

    assert client.patch(f"/api/jobs/{job['id']}", json={"nope": 1}).status_code == 422
    assert client.patch(f"/api/jobs/{job['id']}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"/api/jobs/{job['id']}", json={}).status_code == 422
    assert client.patch(f"/api/jobs/{'0' * 32}", json={"notes": "x"}).status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_job_store.py tests/test_jobs_api.py -k patch -v`
Expected: FAIL with `AttributeError: module 'app.job_store' has no attribute 'patch_job'` and `405 Method Not Allowed` on the API tests.

- [ ] **Step 4: Implement `patch_job`**

Add to `app/job_store.py` directly after `update_job`:

```python
def patch_job(
    job_id: str,
    fields: dict,
    *,
    reason: str = "Dossier patched",
    activity_kind: str = "updated",
    session: str = "",
) -> JobWorkspace | None:
    """Change only the named fields. A full PUT saves a left out field as blank, which
    is how agents have wiped cover letters; a patch cannot. Unknown names raise."""
    unknown = sorted(set(fields) - set(JobWorkspaceInput.model_fields))
    if unknown:
        raise ValueError(f"unknown dossier fields: {', '.join(unknown)}")
    with _transaction():
        current = get_job(job_id)
        if current is None:
            return None
        merged = JobWorkspaceInput.model_validate(
            {**_input_from_job(current).model_dump(), **fields}
        )
        return update_job(
            job_id, merged, reason=reason, activity_kind=activity_kind, session=session
        )
```

- [ ] **Step 5: Implement the route**

In `app/jobs.py` change line 9 to `from fastapi import APIRouter, Body, HTTPException, Query`, then add after `replace_job`:

```python
@router.patch("/api/jobs/{job_id}", response_model=JobWorkspace)
def patch_job(
    job_id: str,
    fields: dict = Body(...),
    session: str = Query(default=""),
) -> JobWorkspace:
    _get_job_or_404(job_id)
    if not fields:
        raise HTTPException(status_code=422, detail="no fields to change")
    try:
        updated = job_store.patch_job(job_id, fields, session=session)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="job dossier not found")
    return updated
```

- [ ] **Step 6: Run the tests to verify they pass, on JSON and SQL**

Run: `.venv/bin/python -m pytest tests/test_job_store.py tests/test_jobs_api.py tests/test_job_store_sql.py -k patch -v`
Expected: PASS, including the `_on_sql` copies.

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass (baseline 388 plus the new tests and their SQL copies).

- [ ] **Step 8: Commit**

```bash
git add app/job_store.py app/jobs.py tests/test_job_store.py tests/test_jobs_api.py
git commit -m "feat(jobs): PATCH a dossier by named fields only"
```

---

### Task 2: Pipeline models and store

**Files:**
- Create: `app/pipeline/__init__.py`, `app/pipeline/models.py`, `app/pipeline/store.py`
- Test: `tests/test_pipeline_store.py`

**Interfaces:**
- Consumes: `doc_store.JsonFileBackend(read, write, lock)`, `doc_store.SqlBackend(url)`, `doc_store.sql_backend_from_env()`, transaction objects with `get(id)`, `put(doc, index)`, `all()`.
- Produces (used by Tasks 3 and 4 and by M2 to M6):
  - `models.RUN_STATUSES: tuple[str, ...]`, `models.TERMINAL_STATUSES: frozenset[str]`, `models.now_iso() -> str`
  - `models.StepState(status, output, error, started_at, finished_at)`, `models.Run(id, job_id, pipeline, status, order, steps, terminal_reason, lease_owner, lease_until, created_at, updated_at)`, `models.Attempt(...)`, `models.AdapterResult(outcome, output, error, model, tokens_in, tokens_out, cost)`
  - `store.create_run(job_id: str, pipeline: str, order: list[str]) -> Run`
  - `store.get_run(run_id: str) -> Run | None`, `store.list_runs(job_id: str | None = None) -> list[Run]`
  - `store.update_step(run_id: str, step: str, **changes) -> Run`
  - `store.start_run(run_id: str) -> Run`, `store.finish_run(run_id: str, status: str, reason: str = "") -> Run`
  - `store.acquire_lease(run_id: str, owner: str, seconds: int = LEASE_SECONDS) -> bool`, `store.release_lease(run_id: str, owner: str) -> None`
  - `store.add_attempt(attempt: Attempt) -> None`, `store.list_attempts(run_id: str | None = None) -> list[Attempt]`
  - `store.RunNotFound(KeyError)`; test hooks `store.DATA_DIR`, `store._JSON_BACKENDS`, `store._BACKEND_OVERRIDE`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_store.py`:

```python
import uuid

import pytest

from app import doc_store
from app.pipeline import store
from app.pipeline.models import Attempt, now_iso


@pytest.fixture(params=["json", "sql"], autouse=True)
def backend(request, monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    if request.param == "sql":
        monkeypatch.setattr(
            store, "_BACKEND_OVERRIDE", doc_store.SqlBackend(f"sqlite:///{tmp_path / 'p.db'}")
        )
    return request.param


def test_create_and_read_run_keeps_step_order():
    run = store.create_run("a" * 32, "packet", ["claim", "fetch_jd", "brief"])

    loaded = store.get_run(run.id)
    assert loaded.order == ["claim", "fetch_jd", "brief"]
    assert loaded.status == "queued"
    assert {name: s.status for name, s in loaded.steps.items()} == {
        "claim": "pending", "fetch_jd": "pending", "brief": "pending",
    }
    assert [r.id for r in store.list_runs(job_id="a" * 32)] == [run.id]
    assert store.list_runs(job_id="b" * 32) == []
    assert store.get_run("missing") is None


def test_update_step_and_start_run_resets_interrupted_steps():
    run = store.create_run("a" * 32, "packet", ["one", "two"])
    store.update_step(run.id, "one", status="done", output={"x": 1})
    store.update_step(run.id, "two", status="running", started_at=now_iso())

    started = store.start_run(run.id)

    assert started.status == "running"
    assert started.steps["one"].status == "done"
    assert started.steps["one"].output == {"x": 1}
    assert started.steps["two"].status == "pending"


def test_finish_run_first_terminal_status_wins_and_skips_pending():
    run = store.create_run("a" * 32, "packet", ["one", "two"])
    store.update_step(run.id, "one", status="done")

    store.finish_run(run.id, "retained_for_review", "fit 5")
    again = store.finish_run(run.id, "failed", "later failure")

    assert again.status == "retained_for_review"
    assert again.terminal_reason == "fit 5"
    assert again.steps["two"].status == "skipped"
    with pytest.raises(ValueError):
        store.finish_run(run.id, "running")


def test_leases_block_other_owners_until_expiry_or_release():
    run = store.create_run("a" * 32, "packet", ["one"])

    assert store.acquire_lease(run.id, "w1") is True
    assert store.acquire_lease(run.id, "w1") is True  # renewing your own lease
    assert store.acquire_lease(run.id, "w2") is False

    store.release_lease(run.id, "w2")  # not the owner: no effect
    assert store.acquire_lease(run.id, "w2") is False

    store.release_lease(run.id, "w1")
    assert store.acquire_lease(run.id, "w2", seconds=-1) is True  # already expired
    assert store.acquire_lease(run.id, "w3") is True


def test_unknown_run_raises():
    with pytest.raises(store.RunNotFound):
        store.update_step("missing", "one", status="done")


def test_attempts_are_listed_per_run_in_time_order():
    def attempt(run_id, started_at):
        return Attempt(
            id=uuid.uuid4().hex, run_id=run_id, job_id="a" * 32, step="fit_score",
            adapter="fake", started_at=started_at, duration_ms=5, outcome="ok",
        )

    store.add_attempt(attempt("r1", "2026-11-26T10:00:02+00:00"))
    store.add_attempt(attempt("r1", "2026-11-26T10:00:01+00:00"))
    store.add_attempt(attempt("r2", "2026-11-26T10:00:03+00:00"))

    listed = store.list_attempts("r1")
    assert [a.started_at for a in listed] == [
        "2026-11-26T10:00:01+00:00", "2026-11-26T10:00:02+00:00",
    ]
    assert len(store.list_attempts()) == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline'`.

- [ ] **Step 3: Create the package and models**

`app/pipeline/__init__.py`:

```python
"""Agent orchestrator. Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md"""
```

`app/pipeline/models.py`:

```python
"""Records of the agent orchestrator: one run per dossier, the state of each of its
steps, and one attempt per try of a step. The attempts are the ledger that the stats
view and the router read to learn which adapter does which step well."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

RUN_STATUSES = (
    "queued",
    "running",
    "packet_ready",
    "retained_for_review",
    "ineligible",
    "closed_posting",
    "failed",
    "cancelled",
)
TERMINAL_STATUSES = frozenset(RUN_STATUSES[2:])

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]
Outcome = Literal["ok", "unavailable", "timeout", "invalid_output", "policy_violation", "error"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StepState(BaseModel):
    status: StepStatus = "pending"
    output: dict | None = None
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


class Run(BaseModel):
    id: str
    job_id: str
    pipeline: str
    status: str = "queued"
    # Postgres JSONB does not keep key order, so the step order is stored separately.
    order: list[str]
    steps: dict[str, StepState]
    terminal_reason: str = ""
    lease_owner: str = ""
    lease_until: str = ""
    created_at: str
    updated_at: str


class Attempt(BaseModel):
    id: str
    run_id: str
    job_id: str
    step: str
    adapter: str
    model: str = ""
    prompt_version: str = ""
    started_at: str
    duration_ms: int
    outcome: Outcome
    error: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
    output_ref: str = ""


class AdapterResult(BaseModel):
    """What an adapter hands back for one try. `output` is the parsed JSON object the
    agent produced; the runner validates it against the step schema."""
    outcome: Outcome
    output: dict | None = None
    error: str = ""
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None
```

- [ ] **Step 4: Create the store**

`app/pipeline/store.py`:

```python
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

    def change(run: Run) -> None:
        if run.status in TERMINAL_STATUSES:
            return
        run.status = status
        run.terminal_reason = reason
        for name, state in run.steps.items():
            if state.status == "pending":
                run.steps[name] = state.model_copy(update={"status": "skipped"})

    return _mutate(run_id, change)


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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_store.py -v`
Expected: PASS, 12 tests (6 on JSON, 6 on SQL).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/__init__.py app/pipeline/models.py app/pipeline/store.py tests/test_pipeline_store.py
git commit -m "feat(pipeline): durable runs, leases and attempt ledger"
```

---

### Task 3: Runner for code steps (DAG, writes, stops, resume, leases)

**Files:**
- Create: `app/pipeline/runner.py`
- Test: `tests/test_pipeline_runner.py`

**Interfaces:**
- Consumes: everything `store` produces in Task 2; `job_store.patch_job` and `job_store.get_job` from Task 1.
- Produces (used by Task 4 and M2 to M6):
  - `StepContext(run: Run, job: JobWorkspace, outputs: dict[str, dict])`
  - `StepResult(output: dict = {}, writes: dict = {}, stop: str = "", reason: str = "")`
  - `StepSpec(name, kind, deps=(), owns=(), capability="", run=None, schema=None, finish=None, when=None)` where `kind` is `"code" | "service" | "agent"`; code and service steps need `run: Callable[[StepContext], StepResult]`; agent steps need `schema: type[BaseModel]`, `finish: Callable[[BaseModel, StepContext], StepResult]` and `capability`
  - `Pipeline(name: str, steps: tuple[StepSpec, ...], done_status: str = "packet_ready")` with property `order -> list[str]`
  - `Adapter` protocol: attribute `name: str`, method `invoke(step: StepSpec, ctx: StepContext, errors: list[str]) -> AdapterResult`
  - `run(run_id: str, pipeline: Pipeline, *, owner: str, resolve_chain: Callable[[StepSpec], list[Adapter]] = _no_adapters) -> Run`
  - Exceptions `LeaseHeld(RuntimeError)`, `StepFailed(Exception)` with attribute `policy: bool`

Task 4 fills in `_run_agent`; in this task it raises `StepFailed` so every code path is complete.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_runner.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'runner' from 'app.pipeline'`.

- [ ] **Step 3: Implement the runner**

Create `app/pipeline/runner.py`:

```python
"""Runs one pipeline run for one dossier.

Steps run in dependency order, and every step whose dependencies are met runs at the
same time in its own thread. Each step state is saved the moment it changes, so after
a crash or restart `run()` resumes at the first step that did not finish. A step may
write only the dossier fields it owns, and only through `job_store.patch_job`. Agent
steps go through an adapter chain (see `_run_agent`).

Design: docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md
"""
from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Protocol

from pydantic import BaseModel

from app import job_store
from app.models import JobWorkspace
from app.pipeline import store
from app.pipeline.models import TERMINAL_STATUSES, AdapterResult, Attempt, Run, now_iso

STEP_KINDS = ("code", "service", "agent")


@dataclass
class StepContext:
    run: Run
    job: JobWorkspace
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

    def __post_init__(self) -> None:
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


class StepFailed(Exception):
    def __init__(self, message: str, *, policy: bool = False):
        super().__init__(message)
        self.policy = policy


Chain = Callable[[StepSpec], list[Adapter]]


def _no_adapters(step: StepSpec) -> list[Adapter]:
    return []


def run(run_id: str, pipeline: Pipeline, *, owner: str, resolve_chain: Chain = _no_adapters) -> Run:
    if not store.acquire_lease(run_id, owner):
        raise LeaseHeld(f"run {run_id} is leased by another worker")
    try:
        current = store.start_run(run_id)
        if current.pipeline != pipeline.name or current.order != pipeline.order:
            raise ValueError(f"run {run_id} does not match pipeline {pipeline.name}")
        specs = {step.name: step for step in pipeline.steps}
        while current.status not in TERMINAL_STATUSES:
            ready = [
                specs[name]
                for name in current.order
                if current.steps[name].status == "pending"
                and all(current.steps[dep].status in ("done", "skipped") for dep in specs[name].deps)
            ]
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
                list(pool.map(lambda step: _execute(run_id, step, resolve_chain), ready))
            current = store.get_run(run_id)
        return current
    finally:
        store.release_lease(run_id, owner)


def _execute(run_id: str, step: StepSpec, resolve_chain: Chain) -> None:
    try:
        ctx = _context(run_id)
        if step.when is not None and not step.when(ctx):
            store.update_step(run_id, step.name, status="skipped", finished_at=now_iso())
            return
        store.update_step(run_id, step.name, status="running", started_at=now_iso(), error="")
        if step.kind == "agent":
            result = _run_agent(step, ctx, resolve_chain)
        else:
            result = _run_local(step, ctx)
        _apply(step, ctx, result)
    except StepFailed as exc:
        store.update_step(run_id, step.name, status="failed", error=str(exc), finished_at=now_iso())
        if exc.policy:
            store.finish_run(run_id, "failed", f"{step.name}: {exc}")
        return
    store.update_step(run_id, step.name, status="done", output=result.output, finished_at=now_iso())
    if result.stop:
        store.finish_run(run_id, result.stop, result.reason)


def _context(run_id: str) -> StepContext:
    current = store.get_run(run_id)
    job = job_store.get_job(current.job_id)
    if job is None:
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
            started_at=started,
            duration_ms=int((time.monotonic() - t0) * 1000),
            outcome=result.outcome,
            error=result.error,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=result.cost,
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


def _run_agent(step: StepSpec, ctx: StepContext, resolve_chain: Chain) -> StepResult:
    raise StepFailed(f"agent steps are not wired yet ({step.name})")


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_runner.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/runner.py tests/test_pipeline_runner.py
git commit -m "feat(pipeline): step DAG runner with owned writes, stops and resume"
```

---

### Task 4: Agent steps through adapters, with `FakeAdapter`

**Files:**
- Create: `app/pipeline/fake.py`
- Modify: `app/pipeline/runner.py` (replace the `_run_agent` stub; change the pydantic import to `from pydantic import BaseModel, ValidationError`)
- Test: `tests/test_pipeline_agents.py`

**Interfaces:**
- Consumes: `StepSpec`, `StepContext`, `StepResult`, `Adapter`, `run`, `StepFailed`, `_record`, `_short` from Task 3; `AdapterResult` from Task 2.
- Produces: `fake.FakeAdapter(name: str, results: list[AdapterResult])` with attribute `calls: list[list[str]]` (the `errors` passed on each call) and method `invoke(step, ctx, errors) -> AdapterResult`. When its scripted results run out it returns `AdapterResult(outcome="unavailable", error="script exhausted")`. M2 adds real adapters implementing the same protocol.

Behavior (spec 5.3): `ok` plus schema valid returns; `ok` but schema invalid becomes `invalid_output`; `invalid_output` gets one more try on the same adapter with the error list; `unavailable`, `timeout` and `error` move to the next adapter; `policy_violation` fails the step and the run at once; an empty or exhausted chain fails the step.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline_agents.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.pipeline.fake'`.

- [ ] **Step 3: Create `FakeAdapter`**

`app/pipeline/fake.py`:

```python
"""An adapter that replays scripted results, so the runner, router and fallback logic
can be tested with no network, no CLI and no model."""
from __future__ import annotations

from app.pipeline.models import AdapterResult


class FakeAdapter:
    def __init__(self, name: str, results: list[AdapterResult]):
        self.name = name
        self._results = list(results)
        # The `errors` list the runner passed on each call, to check repair prompts.
        self.calls: list[list[str]] = []

    def invoke(self, step, ctx, errors: list[str]) -> AdapterResult:
        self.calls.append(list(errors))
        if not self._results:
            return AdapterResult(outcome="unavailable", error="script exhausted")
        return self._results.pop(0)
```

- [ ] **Step 4: Replace the `_run_agent` stub**

In `app/pipeline/runner.py` change `from pydantic import BaseModel` to `from pydantic import BaseModel, ValidationError`, and replace `_run_agent` with:

```python
def _run_agent(step: StepSpec, ctx: StepContext, resolve_chain: Chain) -> StepResult:
    """Try each adapter in the chain. Invalid output gets one more try on the same
    adapter with the error list; unavailable, timeout and error move on at once; a
    policy violation fails the step, which fails the run."""
    chain = resolve_chain(step)
    if not chain:
        raise StepFailed(f"no adapter offers capability {step.capability!r}")
    last = ""
    for adapter in chain:
        errors: list[str] = []
        for _ in range(2):
            started, t0 = now_iso(), time.monotonic()
            result = adapter.invoke(step, ctx, errors)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_agents.py tests/test_pipeline_runner.py -v`
Expected: PASS (agents: 10 tests counting the 3 parametrized cases; runner: 12).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Mark M1 done in the spec and commit**

In `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md`, section 11, change the M1 row's first cell from `M1` to `M1 (done)`. Then from the repo root:

```bash
git add resume-tailor-service/app/pipeline/fake.py resume-tailor-service/app/pipeline/runner.py resume-tailor-service/tests/test_pipeline_agents.py docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md
git commit -m "feat(pipeline): agent steps with adapter fallback and repair retry"
```

---

## Done when (spec M1)

- A fake 3 step DAG runs to `packet_ready` (Task 3, `test_three_step_dag_runs_writes_owned_fields_and_passes_outputs`).
- It resumes after a simulated crash without redoing finished steps (Task 3, `test_resume_after_crash_reruns_only_unfinished_steps`).
- It writes only owned fields (Task 3, `test_writing_an_unowned_field_is_a_policy_violation`, plus the Task 1 patch tests).
- Full suite green with no `.env`.
