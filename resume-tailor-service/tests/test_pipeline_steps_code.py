"""Code steps of the packet pipeline, each run through runner.run on temp JSON stores.
Every network call is injected; the payloads below are synthetic."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import job_store
from app.models import ApplicationAnswerInput, JobActivityInput, JobWorkspaceInput
from app.pipeline import runner, store, steps_code
from app.pipeline.runner import Pipeline


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


def _job(**extra):
    extra.setdefault("notes", "keep")
    extra.setdefault("company", "Acme")
    extra.setdefault("role", "Backend Engineer")
    return job_store.add_job(JobWorkspaceInput(**extra))


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



def test_claim_checks_the_live_dossier_not_the_step_snapshot(monkeypatch):
    """Two runs racing for one dossier: a claim that lands after the step context was
    loaded must still be seen, so the check and the write happen in one transaction."""
    job = _job()
    original = runner._context

    def stale_context(run_id):
        ctx = original(run_id)
        _activity(job, "Claimed by pipeline other-run", session="pipeline other-run",
                  occurred_at=_ago(minutes=1))
        return ctx

    monkeypatch.setattr(runner, "_context", stale_context)
    result = _run(job, steps_code.claim_step())
    assert result.status == "failed"
    titles = [a.title for a in job_store.get_job(job.id).activities]
    assert titles.count("Claimed by pipeline other-run") == 1
    assert f"Claimed by pipeline {result.id}" not in titles


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


# liveness


def test_liveness_closed_stops_the_run_and_appends_one_note_line():
    job = _job(apply_url="https://boards.greenhouse.io/acme/jobs/1", job_url="https://remotive.com/x/1")
    seen = []

    def check(url):
        seen.append(url)
        return "closed", "greenhouse 404"

    result = _run(job, steps_code.liveness_step(check=check))
    assert seen == ["https://boards.greenhouse.io/acme/jobs/1"]
    assert result.status == "closed_posting"
    assert "greenhouse 404" in result.terminal_reason
    assert result.steps["liveness"].output == {"state": "closed", "evidence": "greenhouse 404"}
    notes = job_store.get_job(job.id).notes
    assert notes.startswith("keep\n") and notes.count("\n") == 1
    assert "closed" in notes.splitlines()[1] and "greenhouse 404" in notes


@pytest.mark.parametrize("state", ["live", "unknown"])
def test_liveness_live_or_unknown_continues_without_writing(state):
    job = _job(job_url="https://jobs.lever.co/acme/x")
    result = _run(job, steps_code.liveness_step(check=lambda url: (state, "evidence")))
    assert result.status == "packet_ready"
    assert result.steps["liveness"].output["state"] == state
    saved = job_store.get_job(job.id)
    assert saved.notes == "keep" and len(saved.revisions) == 1


def test_liveness_default_checker_is_the_liveness_script():
    from app.pipeline.steps_code import _default_check

    check = _default_check()
    assert check.__module__ == "check_liveness" and check.__name__ == "check"


# resolve_apply_url

GH_POSTING = "https://job-boards.greenhouse.io/acme/jobs/4012345"


def test_resolve_keeps_an_existing_apply_url():
    job = _job(apply_url="https://acme.example/apply", job_url="https://himalayas.app/companies/acme/jobs/x")
    http = FakeHttp()
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    assert result.steps["resolve_apply_url"].output == {
        "apply_url": "https://acme.example/apply", "source": "existing"}
    assert http.calls == [] and len(job_store.get_job(job.id).revisions) == 1


@pytest.mark.parametrize("url", [
    f"https://jobs.ashbyhq.com/acme/{ASHBY_ID}",
    GH_POSTING,
    f"https://jobs.lever.co/acme/{LEVER_ID}",
    "https://apply.workable.com/acme/j/ABC123DEF/",
])
def test_resolve_takes_an_ats_job_url_as_the_apply_url(url):
    job = _job(job_url=url)
    http = FakeHttp()
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    assert result.steps["resolve_apply_url"].output == {"apply_url": url, "source": "job_url"}
    assert job_store.get_job(job.id).apply_url == url
    assert http.calls == []


def test_resolve_follows_a_board_redirect_to_an_ats_posting():
    board = "https://remotive.com/remote-jobs/software-dev/backend-engineer-123"
    job = _job(job_url=board)
    http = FakeHttp({("HEAD", board): (200, GH_POSTING, "")})
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    assert result.steps["resolve_apply_url"].output == {"apply_url": GH_POSTING, "source": "redirect"}
    assert job_store.get_job(job.id).apply_url == GH_POSTING


def test_resolve_falls_back_to_get_and_accepts_a_careers_page():
    board = "https://jobicy.com/jobs/123-backend-engineer"
    careers = "https://www.acme.example/careers/backend-engineer"
    job = _job(job_url=board)
    http = FakeHttp({("HEAD", board): (405, board, ""), ("GET", board): (200, careers, "<html></html>")})
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    assert result.steps["resolve_apply_url"].output["apply_url"] == careers
    assert [method for method, _ in http.calls] == ["HEAD", "GET"]


@pytest.mark.parametrize("final", [
    "https://himalayas.app/companies/acme/jobs/backend-engineer",  # stayed on the board
    "https://www.linkedin.com/jobs/view/4123456789",  # another aggregator
    "https://boards.greenhouse.io/acme",  # Greenhouse board index: the expired job trap
    "https://ats.rippling.com/acme/jobs?rr_message=job_not_found",  # Rippling dead link
    "https://www.acme.example/",  # employer home page, not a careers page
])
def test_resolve_rejects_unconfirmed_redirects(final):
    board = "https://himalayas.app/companies/acme/jobs/backend-engineer"
    job = _job(job_url=board)
    http = FakeHttp(default=(200, final, ""))
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    out = result.steps["resolve_apply_url"].output
    assert result.status == "packet_ready"
    assert out["needs_agent"] is True and out["reason"]
    assert job_store.get_job(job.id).apply_url == ""


def test_resolve_rejects_a_redirect_that_errors():
    board = "https://remoteok.com/remote-jobs/123"
    job = _job(job_url=board)
    http = FakeHttp(default=(404, GH_POSTING, ""))
    result = _run(job, steps_code.resolve_apply_url_step(http=http))
    assert result.steps["resolve_apply_url"].output["needs_agent"] is True


def test_resolve_leaves_linkedin_and_unknown_hosts_to_the_agent_without_fetching():
    for url in ("https://www.linkedin.com/jobs/view/4123456789", "https://acme.example/careers/x", ""):
        job = _job(job_url=url, role=f"Role {url}")
        http = FakeHttp()
        result = _run(job, steps_code.resolve_apply_url_step(http=http))
        assert result.steps["resolve_apply_url"].output["needs_agent"] is True
        assert http.calls == []


# brief

HEADINGS = ["SUMMARY", "APPLY AT", "GAPS", "WHAT TO PUT IN", "NEEDS HARSH", "PEOPLE"]


def _sections(text):
    out, current = {}, None
    for line in text.splitlines():
        if line in HEADINGS:
            current = line
            out[current] = []
        elif current and line.strip():
            out[current].append(line)
    return {name: "\n".join(lines) for name, lines in out.items()}


def _stub(name, output, deps=()):
    from app.pipeline.runner import StepResult, StepSpec

    return StepSpec(name, "code", deps=deps, run=lambda ctx: StepResult(output=output))


def test_brief_assembles_every_section_and_marks_the_dossier_ready():
    job = _job(
        status="researching", apply_url=GH_POSTING, location="Remote, Canada",
        fit_analysis={"score": 7, "recommendation": "apply", "verdict": "Strong backend match \u2014 light on Go",
                      "gaps": ["No production Go"]},
        cover_letter="Dear Acme team, ...",
    )
    job_store.add_answer(job.id, ApplicationAnswerInput(question="Why Acme?", answer="I like the product."))
    job_store.add_answer(job.id, ApplicationAnswerInput(
        question="Expected salary?", needs_user_input=True, clarification="Posted band is missing"))
    people = {"people": [{"name": "Pat Example", "title": "Engineering Manager", "url": "https://example.com/pat"}]}
    result = _run(
        job,
        _stub("liveness", {"state": "live", "evidence": "greenhouse 200"}),
        _stub("people", people),
        steps_code.brief_step(deps=("liveness", "people")),
    )
    assert result.status == "packet_ready"
    saved = job_store.get_job(job.id)
    assert saved.status == "ready"
    text = saved.research_brief
    assert [line for line in text.splitlines() if line in HEADINGS] == HEADINGS
    assert "\u2014" not in text and "not available yet" not in text
    s = _sections(text)
    assert "Backend Engineer at Acme" in s["SUMMARY"] and "7/10" in s["SUMMARY"]
    assert "live" in s["SUMMARY"]
    assert GH_POSTING in s["APPLY AT"]
    assert "No production Go" in s["GAPS"]
    assert "Why Acme?" in s["WHAT TO PUT IN"] and "I like the product." in s["WHAT TO PUT IN"]
    assert "Cover letter" in s["WHAT TO PUT IN"] and "Expected salary?" not in s["WHAT TO PUT IN"]
    assert "Expected salary?" in s["NEEDS HARSH"] and "Posted band is missing" in s["NEEDS HARSH"]
    assert "Pat Example" in s["PEOPLE"] and "Engineering Manager" in s["PEOPLE"]
    assert result.steps["brief"].output["status"] == "ready"


def test_brief_renders_missing_pieces_as_not_available_yet():
    job = _job()
    result = _run(job, steps_code.brief_step())
    saved = job_store.get_job(job.id)
    assert saved.status == "ready"
    s = _sections(saved.research_brief)
    for name in ("APPLY AT", "GAPS", "WHAT TO PUT IN", "NEEDS HARSH", "PEOPLE"):
        assert s[name] == "not available yet", name
    assert "Backend Engineer at Acme" in s["SUMMARY"]
    assert result.status == "packet_ready"


def test_brief_explains_an_unresolved_apply_url_and_lists_review_issues():
    job = _job(job_url="https://himalayas.app/companies/acme/jobs/x")
    review = {"pass": False, "issues": [{"field": "cover_letter", "problem": "reads stiff", "fix": "shorten"}]}
    result = _run(
        job,
        _stub("resolve_apply_url", {"needs_agent": True, "reason": "board listing did not lead to the employer"}),
        _stub("review", review),
        steps_code.brief_step(deps=("resolve_apply_url", "review")),
    )
    s = _sections(job_store.get_job(job.id).research_brief)
    assert "not available yet" in s["APPLY AT"] and "did not lead to the employer" in s["APPLY AT"]
    assert "https://himalayas.app/companies/acme/jobs/x" in s["APPLY AT"]
    assert "cover_letter" in s["NEEDS HARSH"] and "reads stiff" in s["NEEDS HARSH"]
    assert result.status == "packet_ready"


@pytest.mark.parametrize("status", ["applying", "ready", "skipped"])
def test_brief_leaves_other_statuses_alone(status):
    job = _job(status=status)
    result = _run(job, steps_code.brief_step())
    saved = job_store.get_job(job.id)
    assert saved.status == status and saved.research_brief.startswith("SUMMARY")
    assert result.steps["brief"].output["status"] == status


def test_brief_says_nothing_flagged_once_answers_exist_and_none_need_harsh():
    job = _job()
    job_store.add_answer(job.id, ApplicationAnswerInput(question="Why Acme?", answer="I like the product."))
    _run(job, steps_code.brief_step())
    s = _sections(job_store.get_job(job.id).research_brief)
    assert s["NEEDS HARSH"] == "nothing flagged"


# the code pipeline end to end


def test_packet_code_pipeline_wires_the_steps_in_order():
    pipeline = steps_code.PACKET_CODE_PIPELINE
    # Owner ruling (M4): resolve_apply_url runs first so a board listing gets its JD
    # and its liveness check from the employer ATS.
    assert pipeline.order == ["claim", "resolve_apply_url", "fetch_jd", "liveness", "brief"]
    deps = {step.name: step.deps for step in pipeline.steps}
    assert deps == {"claim": (), "resolve_apply_url": ("claim",), "fetch_jd": ("resolve_apply_url",),
                    "liveness": ("fetch_jd",), "brief": ("liveness",)}
    assert all(step.kind == "code" for step in pipeline.steps)
    assert [s.name for s in steps_code.code_steps()] == pipeline.order


def test_code_steps_run_end_to_end_offline():
    board = "https://remotive.com/remote-jobs/software-dev/backend-engineer-123"
    job = _job(job_url=board)
    http = FakeHttp({
        ("HEAD", board): (200, GH_POSTING, ""),
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs/4012345": (200, "x", _fixture("greenhouse_job.json")),
    })
    checked = []
    pipeline = Pipeline("packet_code", steps_code.code_steps(
        http=http, check=lambda url: checked.append(url) or ("live", "stub")))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    result = runner.run(created.id, pipeline, owner="w1")
    assert result.status == "packet_ready", result.terminal_reason
    saved = job_store.get_job(job.id)
    # resolve runs first, so fetch_jd reads the JD from the employer's Greenhouse posting
    # and liveness checks the apply URL, not the board listing.
    assert saved.apply_url == GH_POSTING
    assert result.steps["fetch_jd"].output["source"] == "greenhouse"
    assert len(saved.jd_text) >= steps_code.JD_MIN_CHARS
    assert checked == [GH_POSTING]
    # Eligibility and fit have not run, so the code only pipeline never promotes status.
    assert saved.status == "discovered" and GH_POSTING in saved.research_brief
    assert result.steps["brief"].output["status"] == "discovered"
    assert any(a.title == f"Claimed by pipeline {result.id}" for a in saved.activities)


def test_code_steps_can_promote_status_once_the_full_pipeline_wires_them():
    job = _job(job_url=GH_POSTING)
    pipeline = Pipeline("packet_code", steps_code.code_steps(
        http=FakeHttp(), check=lambda url: ("live", "stub"), mark_ready=True))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    runner.run(created.id, pipeline, owner="w1")
    assert job_store.get_job(job.id).status == "ready"


def test_packet_code_pipeline_does_not_promote_status():
    brief = steps_code.PACKET_CODE_PIPELINE.steps[-1]
    assert brief.owns == ("research_brief",)
