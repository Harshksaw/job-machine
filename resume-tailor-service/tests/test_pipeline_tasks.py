"""Task pipelines (M8): task scope in the runner, mail sync on a fake Gmail transport and
fake adapters, and the code only update checks. No network, no model, no real mail."""
import json
from datetime import date

import pytest

from app import job_store, research_store, session_store
from app.mail import gmail
from app.mail import store as mail_store
from app.models import JobWorkspaceInput
from app.pipeline import prompts, runner, store, tasks
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.runner import Pipeline, StepResult, StepSpec, task_job_id
from tests.mail_fixtures import FakeTransport, raw_message


@pytest.fixture(autouse=True)
def stores(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(session_store, "STORE_PATH", tmp_path / "sessions.jsonl")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(mail_store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mail_store, "_JSON_BACKENDS", {})


def _job(company, role, status="applied", **extra):
    return job_store.add_job(JobWorkspaceInput(company=company, role=role, status=status,
                                               job_url=f"https://example.com/{company}/{role}".replace(" ", "-"),
                                               **extra))


# --- runner task scope ----------------------------------------------------------------


def test_task_pipeline_may_not_own_fields_and_runs_without_a_dossier():
    with pytest.raises(ValueError, match="may not own"):
        Pipeline("t", (StepSpec("a", "code", owns=("notes",), run=lambda ctx: StepResult()),), scope="task")
    seen = {}

    def step(ctx):
        seen["job"] = ctx.job
        return StepResult(output={"ok": True})

    pipeline = Pipeline("t", (StepSpec("a", "code", run=step),), done_status="completed", scope="task")
    created = store.create_run(task_job_id("t"), "t", pipeline.order)
    result = runner.run(created.id, pipeline, owner="w")
    assert result.status == "completed" and seen["job"] is None
    assert [a.outcome for a in store.list_attempts(created.id)] == ["ok"]


def test_task_run_writes_fail_the_run_and_scopes_must_match():
    pipeline = Pipeline("t", (StepSpec("a", "code", run=lambda ctx: StepResult(writes={"notes": "x"})),),
                        done_status="completed", scope="task")
    result = runner.run(store.create_run(task_job_id("t"), "t", pipeline.order).id, pipeline, owner="w")
    assert result.status == "failed" and "does not own" in result.terminal_reason

    job = _job("Acme", "Engineer")
    wrong = store.create_run(job.id, "t", pipeline.order)
    with pytest.raises(ValueError, match="does not fit"):
        runner.run(wrong.id, pipeline, owner="w")
    dossier = Pipeline("d", (StepSpec("a", "code", run=lambda ctx: StepResult()),))
    with pytest.raises(ValueError, match="does not fit"):
        runner.run(store.create_run(task_job_id("d"), "d", dossier.order).id, dossier, owner="w")


def test_prompt_renders_for_a_task_run():
    run = store.create_run(task_job_id("mail_sync"), "mail_sync", ["mail_fetch", "mail_classify"])
    ctx = runner.StepContext(run=run, job=None, outputs={"mail_fetch": {"messages": [{"id": "m1"}]}})
    text, version = prompts.render("mail_classify", ctx)
    assert '"id": "m1"' in text and "Never make up an id" in text and len(version) == 12


# --- mail sync --------------------------------------------------------------------------


def _inbox():
    return {
        "m1": raw_message("m1", subject="Your application to Acme", day="2026-02-02",
                          body="Unfortunately we decided not to move forward."),
        "m2": raw_message("m2", subject="Globex interview", day="2026-02-03", body="Pick a time to talk."),
        "m3": raw_message("m3", subject="Initech update", day="2026-02-04", body="We wanted to let you"),
        "m4": raw_message("m4", subject="Weekly job alert", day="2026-02-05", body="New jobs for you"),
        "m5": raw_message("m5", subject="Hooli next step", day="2026-02-01", body="Take home test due Friday"),
        "m6": raw_message("m6", subject="Thank you for applying to Acme", day="2026-02-05", body="Received"),
    }


def _classified(*extra):
    events = [
        {"id": "m1", "company": "Acme", "role": "Backend Engineer", "date": "2099-01-01", "outcome": "rejected",
         "confident": True, "note": "Rejected — role filled"},
        {"id": "m2", "company": "Globex", "role": "", "date": "2026-02-03", "outcome": "interview",
         "confident": True, "note": "Wants to schedule a call"},
        {"id": "m3", "company": "Initech", "role": "Engineer", "date": "2026-02-04", "outcome": "rejected",
         "confident": False, "note": "Cut off"},
        {"id": "m5", "company": "Hooli", "role": "Engineer", "date": "2026-02-01", "outcome": "assessment",
         "confident": True, "note": "Take home due Friday"},
        {"id": "zz", "company": "Acme", "role": "", "date": "2026-02-01", "outcome": "interview",
         "confident": True, "note": "made up"},
        *extra,
    ]
    return AdapterResult(outcome="ok", output={"events": events})


def _mail_pipeline(transport, today=date(2026, 2, 10)):
    return tasks.mail_sync_pipeline(lambda: gmail.GmailClient(transport), today=lambda: today)


def _chain(*results):
    adapter = FakeAdapter("fake_cheap", list(results))
    return adapter, (lambda step: [adapter])


def test_mail_sync_end_to_end_writes_holds_reports_and_moves_the_window():
    acme = _job("Acme Inc", "Backend Engineer")
    _job("Globex", "Data Engineer")
    _job("Globex", "ML Engineer")
    initech = _job("Initech", "Engineer")
    transport = FakeTransport(_inbox())
    adapter, chain = _chain(_classified())

    run = tasks.run_task("mail_sync", pipeline=_mail_pipeline(transport), resolve_chain=chain)

    assert run.status == "completed", run.terminal_reason
    # First run looks back 14 days from "today".
    searches = [params["q"] for path, params in transport.calls if path == "messages"]
    assert searches and all("after:2026/01/27 -in:sent" in q for q in searches)
    # The receipt never reaches the agent.
    fetched = [m["id"] for m in run.steps["mail_fetch"].output["messages"]]
    assert fetched == ["m5", "m1", "m2", "m3", "m4"]
    assert "Never make up an id" in run.steps["mail_fetch"].output["instructions"]

    saved = job_store.get_job(acme.id)
    assert saved.status == "rejected"
    act = [a for a in saved.activities if a.external_id == "gmail:m1"]
    assert len(act) == 1 and act[0].kind == "reply" and "—" not in act[0].detail
    assert act[0].occurred_at.startswith("2026-02-02")  # the message date, not the agent's
    assert job_store.get_job(initech.id).status == "applied"  # uncertain: held

    events = {e["id"]: e for e in mail_store.list_events()}
    assert events["m1"]["status"] == "written" and events["m1"]["status_change"] == "rejected"
    assert events["m2"]["status"] == "unmatched" and events["m2"]["reason"].startswith("ambiguous")
    assert events["m3"]["status"] == "held"
    assert events["m4"]["status"] == "ignored"
    assert events["m5"]["status"] == "unmatched" and events["m5"]["reason"] == "no dossier"
    assert "zz" not in events
    assert job_store.list_summaries().__len__() == 4  # no dossier invented

    report = run.steps["mail_report"].output
    assert [r["id"] for r in report["waiting_on_harsh"]] == ["m5"]
    assert [r["id"] for r in report["interviews"]] == ["m2"]
    assert report["rejections_written"] == 1
    assert [r["id"] for r in report["sheet_log"]] == ["m1"]
    assert report["newest_date"] == "2026-02-05"
    assert run.steps["mail_classify"].output["dropped"] == ["zz"]
    assert mail_store.get_state()["newest_date"] == "2026-02-05"
    assert session_store.list_events(job_id=acme.id)  # mirrored like the activity route


def test_mail_sync_rerun_skips_known_mail_and_never_writes_twice():
    acme = _job("Acme", "Backend Engineer")
    transport = FakeTransport(_inbox())
    _, chain = _chain(_classified())
    tasks.run_task("mail_sync", pipeline=_mail_pipeline(transport), resolve_chain=chain)

    transport.calls.clear()
    adapter, chain = _chain()
    rerun = tasks.run_task("mail_sync", pipeline=_mail_pipeline(transport), resolve_chain=chain)
    assert rerun.status == "completed"
    assert all("after:2026/02/03" in p["q"] for path, p in transport.calls if path == "messages")
    assert rerun.steps["mail_classify"].status == "skipped" and adapter.calls == []
    assert [p for p, _ in transport.calls if p.startswith("messages/")] == []

    # Even when the store forgets the mail, the dossier event is keyed on the message id.
    job_store.patch_job(acme.id, {"status": "interview"})
    mail_store._JSON_BACKENDS.clear()
    (mail_store.DATA_DIR / "mail_events.json").unlink()
    _, chain = _chain(_classified())
    third = tasks.run_task("mail_sync", pipeline=_mail_pipeline(transport), resolve_chain=chain)
    saved = job_store.get_job(acme.id)
    assert [a.external_id for a in saved.activities].count("gmail:m1") == 1
    assert saved.status == "interview"  # not set back to rejected by a replayed email
    assert {e["id"]: e["status"] for e in mail_store.list_events()}["m1"] == "duplicate"
    assert third.status == "completed"


def test_failed_classification_fails_the_run_and_keeps_the_window():
    _job("Acme", "Backend Engineer")
    _, chain = _chain(AdapterResult(outcome="invalid_output", error="junk"),
                      AdapterResult(outcome="ok", output={"events": [{"id": "m1"}]}))
    run = tasks.run_task("mail_sync", pipeline=_mail_pipeline(FakeTransport(_inbox())), resolve_chain=chain)
    assert run.status == "failed" and run.terminal_reason.startswith("mail_classify")
    assert mail_store.get_state() == {"id": "mail_sync"}
    assert mail_store.list_events() == []


def test_unconfigured_gmail_fails_with_the_fix(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAIL_TOKEN_FILE", str(tmp_path / "none.json"))
    run = tasks.run_task("mail_sync", pipeline=tasks.mail_sync_pipeline(), resolve_chain=lambda step: [])
    assert run.status == "failed" and "gmail_auth.py" in run.terminal_reason


def test_mail_window_uses_two_day_overlap():
    assert tasks.mail_window({"newest_date": "2026-02-05"}) == date(2026, 2, 3)
    assert tasks.mail_window({}, date(2026, 2, 15)) == date(2026, 2, 1)
    assert tasks.mail_window({"newest_date": "junk"}, date(2026, 2, 15)) == date(2026, 2, 1)


# --- update checks ----------------------------------------------------------------------


def test_liveness_sweep_reports_old_unapplied_closed_postings_and_deletes_nothing(monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(job_store, "_now", lambda: "2025-01-01T00:00:00+00:00")
        old_closed = _job("Acme", "Engineer", status="discovered")
        old_live = _job("Globex", "Engineer", status="ready")
        old_applied = _job("Initech", "Engineer", status="applied")
    new = _job("Hooli", "Engineer", status="discovered")
    checked = []

    def check(url):
        checked.append(url)
        return ("closed", "404") if "Acme" in url else ("live", "200")

    run = tasks.run_task("liveness_sweep", pipeline=tasks.liveness_sweep_pipeline(check))
    out = run.steps["liveness_sweep"].output
    assert run.status == "completed"
    assert checked == [old_closed.job_url, old_live.job_url]
    assert [c["id"] for c in out["closed"]] == [old_closed.id]
    assert out["counts"] == {"closed": 1, "live": 1}
    assert job_store.get_job(old_closed.id) is not None and job_store.get_job(old_closed.id).status == "discovered"
    assert job_store.get_job(old_applied.id) and job_store.get_job(new.id)


def test_liveness_sweep_treats_a_crashing_check_as_unknown(monkeypatch):
    monkeypatch.setattr(job_store, "_now", lambda: "2025-01-01T00:00:00+00:00")
    _job("Acme", "Engineer", status="discovered")

    def boom(url):
        raise TimeoutError("slow")

    out = tasks.run_task("liveness_sweep", pipeline=tasks.liveness_sweep_pipeline(boom)).steps["liveness_sweep"].output
    assert out["counts"] == {"unknown": 1} and out["closed"] == []


def _board_row(company, role, url):
    return {"company": company, "role": role, "job_url": url, "source": "Fake", "location": "Canada",
            "seniority": "", "posted": "", "jd_text": "x" * 400}


def test_remote_boards_reuses_the_script_harvest(tmp_path):
    _job("Acme", "Software Engineer")
    boards = [("Fake", lambda: [_board_row("Acme", "Software Engineer", "https://example.com/a"),
                               _board_row("Globex", "Backend Engineer", "https://example.com/g"),
                               _board_row("Globex", "Sales Lead", "https://example.com/s")]),
              ("Dead", lambda: (_ for _ in ()).throw(OSError("down")))]
    out_path = tmp_path / "candidates.json"
    run = tasks.run_task("remote_boards", pipeline=tasks.remote_boards_pipeline(boards, out_path=out_path))
    out = run.steps["remote_boards_harvest"].output
    assert run.status == "completed"
    assert [row["company"] for row in out["listings"]] == ["Globex"]
    assert out["dropped"] == {"already in dossiers": 1, "title": 1}
    assert out["boards"]["Dead"].startswith("failed")
    assert json.loads(out_path.read_text())[0]["role"] == "Backend Engineer"
    assert len(job_store.list_summaries()) == 1  # harvest only


def test_ats_watchlist_stages_new_listings_through_the_research_route(tmp_path):
    _job("Acme", "Backend Engineer")
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("boards:\n  - company: Acme\n    provider: greenhouse\n    token: acme\n")
    calls = []

    def get_json(url):
        calls.append(url)
        return {"jobs": [
            {"title": "Backend Engineer", "absolute_url": "https://example.com/1", "content": "x"},
            {"title": "Platform Engineer", "absolute_url": "https://example.com/2", "content": "y"},
        ]}

    run = tasks.run_task("ats_watchlist", pipeline=tasks.ats_watchlist_pipeline(get_json, watchlist=watchlist))
    out = run.steps["ats_watchlist_poll"].output
    assert run.status == "completed", run.terminal_reason
    assert out["fetched"] == 2 and out["new"] == 1 and out["staged"] == 1
    assert calls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"]
    assert [item["role"] for item in research_store.list_items()] == ["Platform Engineer"]
    assert len(job_store.list_summaries()) == 1  # discovery only, no dossier


def test_registry_and_active_run():
    assert set(tasks.TASK_BUILDERS) == {"mail_sync", "liveness_sweep", "remote_boards", "ats_watchlist"}
    with pytest.raises(KeyError):
        tasks.task_pipeline("nope")
    assert tasks.active_run("liveness_sweep") is None
    queued = tasks.enqueue("liveness_sweep")
    assert queued.job_id == "task:liveness_sweep" and tasks.active_run("liveness_sweep").id == queued.id


def test_a_crash_between_activity_and_status_writes_neither(monkeypatch):
    """Codex review: the activity and the status move are one transaction, so a crash
    cannot leave the email logged and the status unmoved forever."""
    acme = _job("Acme", "Backend Engineer")
    real_patch = job_store.patch_job

    def crash(*args, **kwargs):
        raise RuntimeError("power cut")

    monkeypatch.setattr(job_store, "patch_job", crash)
    _, chain = _chain(_classified())
    first = tasks.run_task("mail_sync", pipeline=_mail_pipeline(FakeTransport(_inbox())), resolve_chain=chain)
    assert first.status == "failed"
    saved = job_store.get_job(acme.id)
    assert "gmail:m1" not in [a.external_id for a in saved.activities] and saved.status == "applied"

    monkeypatch.setattr(job_store, "patch_job", real_patch)
    _, chain = _chain(_classified())
    second = tasks.run_task("mail_sync", pipeline=_mail_pipeline(FakeTransport(_inbox())), resolve_chain=chain)
    assert second.status == "completed"
    saved = job_store.get_job(acme.id)
    assert saved.status == "rejected" and [a.external_id for a in saved.activities].count("gmail:m1") == 1


def test_crash_rolls_back_on_the_sql_backend_too(monkeypatch, tmp_path):
    from app import doc_store

    monkeypatch.setattr(job_store, "_BACKEND_OVERRIDE", doc_store.SqlBackend(f"sqlite:///{tmp_path / 'jobs.db'}"))
    test_a_crash_between_activity_and_status_writes_neither(monkeypatch)
