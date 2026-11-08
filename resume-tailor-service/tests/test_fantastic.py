import pytest
from fastapi.testclient import TestClient

from app import agent_runs, fantastic, job_store
from app.main import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(fantastic, "USAGE_PATH", tmp_path / "usage.json")


def _job(n, org="Acme", title="Software Engineer"):
    return {
        "id": n, "title": title, "organization": org,
        "url": f"https://boards.greenhouse.io/acme/jobs/{n}", "source": "greenhouse",
        "locations_derived": ["Vancouver, British Columbia, Canada"],
        "ai_work_arrangement": "Remote OK", "description_text": "Build things.",
        "date_posted": "2026-11-06T00:00:00", "ai_experience_level": "0-2",
    }


def test_run_captures_new_and_skips_known_listings():
    first = fantastic.run_search("canada", 2, fetch=lambda _: [_job(1), _job(2, "Beta")])
    assert len(first["new"]) == 2
    again = fantastic.run_search("canada", 2, fetch=lambda _: [_job(1), _job(3, "Gamma")])
    assert [n["company"] for n in again["new"]] == ["Gamma"]
    assert again["duplicates"] == ["Acme | Software Engineer"]
    captured = job_store.load_jobs()
    assert {j.status for j in captured} == {"discovered"}
    assert all(j.source == "Fantastic Jobs (greenhouse)" for j in captured)


def test_usage_counts_jobs_returned_and_requests():
    fantastic.run_search("remote-na", 5, fetch=lambda _: [_job(1), _job(2, "B")])
    usage = fantastic.usage_summary()
    assert usage["jobs_used"] == 2 and usage["requests_used"] == 1
    assert usage["jobs_left"] == 498


def test_budget_refuses_a_run_that_could_cross_the_trial(monkeypatch):
    monkeypatch.setattr(fantastic, "TRIAL", {"jobs": 10, "requests": 100})
    fantastic.run_search("canada", 8, fetch=lambda _: [_job(n, f"O{n}") for n in range(8)])
    with pytest.raises(ValueError, match="trial jobs left"):
        fantastic.run_search("canada", 5, fetch=lambda _: [])


def test_preset_params_respect_eligibility():
    params = fantastic.PRESETS["canada"]["params"]
    assert params["organization_agency"] == "exclude"
    assert "senior" in params["title_advanced"]
    assert params["ai_experience_level"] == "0-2,2-5"


def test_search_and_agent_posts_need_the_dashboard_header():
    client = TestClient(app)
    assert client.post("/api/search/run", json={"preset": "canada"}).status_code == 403
    assert client.post("/api/agents/run", json={"tool": "codex", "task": "score-new"}).status_code == 403


def test_agent_tasks_are_fixed():
    client = TestClient(app)
    response = client.post(
        "/api/agents/run", json={"tool": "codex", "task": "rm -rf"},
        headers={"X-Job-Machine": "dashboard"},
    )
    assert response.status_code == 400


def test_agent_start_runs_the_named_task(monkeypatch, tmp_path):
    started = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        started["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(agent_runs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(agent_runs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(agent_runs.shutil, "which", lambda name, path=None: "/bin/" + name)
    result = agent_runs.start("opencode", "score-new")
    assert result["pid"] == 4242
    assert started["cmd"][:2] == ["/bin/opencode", "run"]
    assert "Do not submit applications" in started["cmd"][-1]
