"""Code steps of the packet pipeline, each run through runner.run on temp JSON stores.
Every network call is injected; the payloads below are synthetic."""
from datetime import datetime, timedelta, timezone

import pytest

from app import job_store
from app.models import JobActivityInput, JobWorkspaceInput
from app.pipeline import runner, store, steps_code
from app.pipeline.runner import Pipeline


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def _job(**extra):
    extra.setdefault("notes", "keep")
    return job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer", **extra))


def _run(job, *steps):
    pipeline = Pipeline("t", tuple(steps))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    return runner.run(created.id, pipeline, owner="w1")


def _ago(**delta):
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _activity(job, title, *, kind="note", session="", occurred_at=None):
    job_store.add_activity(
        job.id, JobActivityInput(kind=kind, title=title, session=session, occurred_at=occurred_at)
    )


# claim


def test_claim_records_a_claim_activity():
    job = _job()
    result = _run(job, steps_code.claim_step())
    assert result.status == "packet_ready"
    assert result.steps["claim"].output == {"claimed": True}
    saved = job_store.get_job(job.id)
    claims = [a for a in saved.activities if a.title.startswith("Claimed by")]
    assert [a.title for a in claims] == [f"Claimed by pipeline {result.id}"]
    assert claims[0].session == f"pipeline {result.id}"
    assert saved.notes == "keep"


def test_claim_refuses_a_fresh_claim_from_another_session():
    job = _job()
    _activity(job, "Claimed by cursor s1", session="cursor s1", occurred_at=_ago(minutes=30))
    result = _run(job, steps_code.claim_step())
    assert result.status == "failed"
    assert "claimed" in result.terminal_reason
    titles = [a.title for a in job_store.get_job(job.id).activities]
    assert not any(t.startswith("Claimed by pipeline") for t in titles)


def test_claim_ignores_a_claim_older_than_two_hours():
    job = _job()
    _activity(job, "Claimed by cursor s1", session="cursor s1", occurred_at=_ago(hours=3))
    result = _run(job, steps_code.claim_step())
    assert result.status == "packet_ready"


def test_claim_cancels_an_applied_dossier():
    job = _job()
    _activity(job, "Applied via Ashby", kind="applied", occurred_at=_ago(days=10))
    result = _run(job, steps_code.claim_step())
    assert result.status == "cancelled"
    assert "already applied" in result.terminal_reason
    titles = [a.title for a in job_store.get_job(job.id).activities]
    assert not any(t.startswith("Claimed by pipeline") for t in titles)


def test_claim_cancels_a_dossier_past_submission_by_status():
    job = _job(status="interview")
    result = _run(job, steps_code.claim_step())
    assert result.status == "cancelled"
    assert "already applied" in result.terminal_reason


def test_claim_is_idempotent_for_its_own_run():
    job = _job()
    pipeline = Pipeline("t", (steps_code.claim_step(),))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    own = f"Claimed by pipeline {created.id}"
    _activity(job, own, session=f"pipeline {created.id}", occurred_at=_ago(minutes=5))
    result = runner.run(created.id, pipeline, owner="w1")
    assert result.status == "packet_ready"
    titles = [a.title for a in job_store.get_job(job.id).activities]
    assert titles.count(own) == 1
