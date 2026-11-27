"""Code steps of the packet pipeline, each run through runner.run on temp JSON stores.
Every network call is injected; the payloads below are synthetic."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


# fetch_jd

FIXTURES = Path(__file__).parent / "fixtures" / "ats"
ASHBY_ID = "11111111-2222-3333-4444-555555555555"
LEVER_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    """Replays canned responses by (method, url); anything else is a 404."""

    def __init__(self, routes=None, *, default=None):
        self.routes = dict(routes or {})
        self.default = default
        self.calls = []

    def __call__(self, method, url):
        self.calls.append((method, url))
        if (method, url) in self.routes:
            return self.routes[(method, url)]
        if url in self.routes:
            return self.routes[url]
        if self.default is not None:
            return self.default
        return 404, url, ""


def _ok(url, body):
    return {url: (200, url, body)}


def test_fetch_jd_keeps_existing_long_text_without_fetching():
    job = _job(jd_text="x" * 800, job_url=f"https://jobs.ashbyhq.com/acme/{ASHBY_ID}")
    http = FakeHttp()
    result = _run(job, steps_code.fetch_jd_step(http=http))
    assert result.status == "packet_ready"
    assert result.steps["fetch_jd"].output == {"source": "existing"}
    assert http.calls == []
    assert len(job_store.get_job(job.id).revisions) == 1  # creation only


def test_fetch_jd_reads_the_ashby_board_and_picks_the_posting():
    job = _job(job_url=f"https://jobs.ashbyhq.com/acme/{ASHBY_ID}/application")
    http = FakeHttp(_ok("https://api.ashbyhq.com/posting-api/job-board/acme", _fixture("ashby_board.json")))
    result = _run(job, steps_code.fetch_jd_step(http=http))
    out = result.steps["fetch_jd"].output
    assert out["source"] == "ashby" and out["chars"] >= 800 and "needs_agent" not in out
    text = job_store.get_job(job.id).jd_text
    assert text.startswith("Acme builds tools") and "Design things" not in text


def test_fetch_jd_strips_greenhouse_html_from_either_host():
    job = _job(job_url="https://boards.greenhouse.io/acme/jobs/4012345?gh_src=x")
    http = FakeHttp(_ok("https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345",
                        _fixture("greenhouse_job.json")))
    result = _run(job, steps_code.fetch_jd_step(http=http))
    assert result.steps["fetch_jd"].output["source"] == "greenhouse"
    text = job_store.get_job(job.id).jd_text
    assert "<" not in text and "&lt;" not in text and "&amp;" not in text
    assert "Requirements: two or more years" in text and len(text) >= 800


def test_fetch_jd_joins_lever_description_lists_and_additional():
    job = _job(apply_url=f"https://jobs.lever.co/acme/{LEVER_ID}/apply", job_url="https://remotive.com/x/1")
    http = FakeHttp(_ok(f"https://api.lever.co/v0/postings/acme/{LEVER_ID}", _fixture("lever_posting.json")))
    result = _run(job, steps_code.fetch_jd_step(http=http))
    assert result.steps["fetch_jd"].output["source"] == "lever"
    text = job_store.get_job(job.id).jd_text
    assert "Requirements" in text and "remote within Canada" in text and "<li>" not in text


def test_fetch_jd_uses_the_linkedin_guest_endpoint():
    job = _job(job_url="https://www.linkedin.com/jobs/view/backend-engineer-at-acme-4123456789/?trk=x")
    http = FakeHttp(_ok("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4123456789",
                        _fixture("linkedin_posting.html")))
    result = _run(job, steps_code.fetch_jd_step(http=http))
    assert result.steps["fetch_jd"].output["source"] == "linkedin"
    text = job_store.get_job(job.id).jd_text
    assert text.startswith("Acme builds tools")
    assert "Show more" not in text and "var x" not in text and "Seniority level" not in text


def test_fetch_jd_flags_needs_agent_without_failing_and_keeps_longer_text():
    job = _job(jd_text="A" * 300, job_url="https://acme.example/careers/backend")
    http = FakeHttp()
    result = _run(job, steps_code.fetch_jd_step(http=http))
    assert result.status == "packet_ready"
    assert result.steps["fetch_jd"].output["needs_agent"] is True
    assert job_store.get_job(job.id).jd_text == "A" * 300


def test_fetch_jd_survives_network_errors():
    job = _job(job_url="https://boards.greenhouse.io/acme/jobs/4012345")

    def broken(method, url):
        raise OSError("offline")

    result = _run(job, steps_code.fetch_jd_step(http=broken))
    assert result.status == "packet_ready"
    assert result.steps["fetch_jd"].output["needs_agent"] is True
