from datetime import date

from fastapi.testclient import TestClient

from app import doc_store, job_store, system, telemetry
from app.main import app
from app.models import JobCaptureInput

client = TestClient(app)
_HEADER = {"X-Job-Machine": "dashboard"}


def _job(status: str, *, source: str = "LinkedIn", fit: int = 8, kinds: tuple[str, ...] = (),
         applied_on: str = "2026-11-10") -> dict:
    stamp = f"{applied_on}T00:00:00+00:00"
    return {
        "status": status, "source": source, "fit_score": fit, "updated_at": stamp,
        "activities": [{"kind": kind, "occurred_at": stamp, "created_at": stamp} for kind in kinds],
    }


def test_report_rows_carry_only_the_report_fields(tmp_path, monkeypatch):
    backend = doc_store.SqlBackend(f"sqlite:///{tmp_path / 'jobs.db'}")
    monkeypatch.setattr(job_store, "_BACKEND_OVERRIDE", backend)
    job_store.capture_job(JobCaptureInput(
        company="Acme", role="Engineer", job_url="https://acme.test/1", source="Ashby",
        status="applied", fit_score=8, jd_text="long description",
    ))

    rows = job_store.report_rows()

    assert len(rows) == 1
    assert set(rows[0]) == set(job_store.REPORT_FIELDS)
    assert rows[0]["status"] == "applied" and rows[0]["fit_score"] == 8
    assert system.funnel(rows)["totals"]["applied"] == 1


def test_funnel_counts_a_rejection_after_an_interview_as_a_response():
    jobs = [
        _job("applied", kinds=("applied",)),
        _job("rejected", kinds=("applied", "interview")),
        _job("interview", source="Ashby (clean-ats broad)", kinds=("applied",)),
        _job("discovered"),
        _job("skipped", fit=4),
    ]

    result = system.funnel(jobs, today=date(2026, 11, 14))

    assert result["totals"] == {
        "dossiers": 5, "applied": 3, "responded": 2, "rejected": 1, "waiting": 1,
        "response_rate": 0.667,
    }
    assert result["backlog"]["strong_unapplied"] == 1
    sources = {row["source"]: row for row in result["by_source"]}
    assert sources["LinkedIn"]["applied"] == 2
    assert sources["Ashby"]["responded"] == 1
    assert result["weekly"][-1] == {"week": "2026-11-09", "applied": 3}
    assert len(result["weekly"]) == 12


def test_connections_are_listed_and_checks_need_the_dashboard_header():
    listed = client.get("/api/system/connections").json()
    assert {item["id"] for item in listed} == set(system.CHECKS)

    assert client.post("/api/system/connections/database/check").status_code == 403
    assert client.post("/api/system/connections/nope/check", headers=_HEADER).status_code == 404


def test_a_check_that_raises_reports_fail_instead_of_a_server_error(monkeypatch):
    def boom():
        raise RuntimeError("no route to host")

    monkeypatch.setitem(system.CHECKS, "database", ("Dossier database", "", boom))

    body = client.post("/api/system/connections/database/check", headers=_HEADER).json()

    assert body["status"] == "fail"
    assert "no route to host" in body["detail"]


def test_requests_and_checks_show_up_in_the_telemetry_summary(monkeypatch):
    monkeypatch.setitem(system.CHECKS, "database", ("Dossier database", "", lambda: ("ok", "fine")))
    client.post("/api/system/connections/database/check", headers=_HEADER)

    summary = client.get("/api/system/telemetry").json()

    assert summary["enabled"] is True
    names = {row["name"]: row for row in summary["routes"]}
    assert names["POST /api/system/connections/{check_id}/check"]["kind"] == "request"
    assert names["connection.check"]["kind"] == "call"
    assert telemetry.exporter_endpoint() is None


def test_a_model_call_span_carries_usage_but_not_content_by_default(monkeypatch):
    monkeypatch.delenv("JOB_MACHINE_TRACE_CONTENT", raising=False)
    payload = {"usage": {"input_tokens": 120, "output_tokens": 30}, "total_cost_usd": 0.002}

    with telemetry.span("claude.cli") as current:
        telemetry.record_generation("the prompt", "the reply", payload, "claude-haiku-4-5")

    assert current.attributes["gen_ai.request.model"] == "claude-haiku-4-5"
    assert current.attributes["gen_ai.usage.input_tokens"] == 120
    assert current.attributes["gen_ai.usage.cost"] == 0.002
    assert "langfuse.observation.input" not in current.attributes

    monkeypatch.setenv("JOB_MACHINE_TRACE_CONTENT", "true")
    with telemetry.span("claude.cli") as current:
        telemetry.record_generation("the prompt", "the reply", payload, "claude-haiku-4-5")
    assert current.attributes["langfuse.observation.output"] == "the reply"
