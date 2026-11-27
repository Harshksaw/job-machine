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
