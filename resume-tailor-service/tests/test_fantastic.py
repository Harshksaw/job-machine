import pytest
from fastapi.testclient import TestClient

from app import agent_runs, fantastic, job_store, research_store
from app.main import app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(fantastic, "USAGE_PATH", tmp_path / "usage.json")
    monkeypatch.setattr(research_store, "STORE_PATH", tmp_path / "research.json")


def _job(n, org="Acme", title="Software Engineer"):
    return {
        "id": n, "title": title, "organization": org,
        "url": f"https://boards.greenhouse.io/acme/jobs/{n}", "source": "greenhouse",
        "locations_derived": ["Vancouver, British Columbia, Canada"],
        "ai_work_arrangement": "Remote OK", "description_text": "Build things.",
        "date_posted": "2026-11-06T00:00:00", "ai_experience_level": "0-2",
    }


def test_run_captures_new_and_skips_known_listings():
    first = fantastic.run_search("remote-ca", 2, fetch=lambda _: [_job(1), _job(2, "Beta")])
    assert len(first["new"]) == 2
    again = fantastic.run_search("remote-ca", 2, fetch=lambda _: [_job(1), _job(3, "Gamma")])
    assert [n["company"] for n in again["new"]] == ["Gamma"]
    assert again["duplicates"] == ["Acme | Software Engineer"]
    captured = job_store.load_jobs()
    assert {j.status for j in captured} == {"discovered"}
    assert all(j.source == "Fantastic Jobs (greenhouse)" for j in captured)


def test_usage_counts_jobs_returned_and_requests():
    fantastic.run_search("remote-ca", 5, fetch=lambda _: [_job(1), _job(2, "B")])
    usage = fantastic.usage_summary()
    assert usage["jobs_used"] == 2 and usage["requests_used"] == 1
    assert usage["jobs_left"] == 498


def test_budget_refuses_a_run_that_could_cross_the_trial(monkeypatch):
    monkeypatch.setattr(fantastic, "TRIAL", {"jobs": 10, "requests": 100})
    fantastic.run_search("remote-ca", 8, fetch=lambda _: [_job(n, f"O{n}") for n in range(8)])
    with pytest.raises(ValueError, match="trial jobs left"):
        fantastic.run_search("remote-ca", 5, fetch=lambda _: [])


def test_preset_params_respect_eligibility():
    params = fantastic.PRESETS["remote-ca"]["params"]
    assert params["organization_agency"] == "exclude"
    assert "senior" in params["title_advanced"]
    assert "ai_experience_level" not in params
    assert params["ai_work_arrangement"] == "Remote Solely"


def test_search_and_agent_posts_need_the_dashboard_header():
    client = TestClient(app)
    assert client.post("/api/search/run", json={"preset": "remote-ca"}).status_code == 403
    assert client.post("/api/agents/run", json={"tool": "codex", "task": "score-new"}).status_code == 403


def test_agent_tasks_are_fixed():
    client = TestClient(app)
    response = client.post(
        "/api/agents/run", json={"tool": "codex", "task": "rm -rf"},
        headers={"X-Job-Machine": "dashboard"},
    )
    assert response.status_code == 400


def _fake_start(monkeypatch, tmp_path):
    started = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, **kwargs):
        started["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(agent_runs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(agent_runs.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(agent_runs.shutil, "which", lambda name, path=None: "/bin/" + name)
    return started


def test_agent_start_runs_the_named_task(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    result = agent_runs.start("cursor", "score-new")
    assert result["pid"] == 4242
    assert started["cmd"][:2] == ["/bin/cursor-agent", "-p"]
    assert "Do not submit applications" in started["cmd"][-1]


def test_cursor_always_runs_grok_4_7_medium(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    agent_runs.start("cursor", "score-new")
    assert started["cmd"][started["cmd"].index("--model") + 1] == "grok-4.7-medium"


def test_opencode_runs_the_free_model_unless_the_tier_is_flipped(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    monkeypatch.delenv("OPENCODE_TIER", raising=False)
    agent_runs.start("opencode", "score-new")
    assert started["cmd"][started["cmd"].index("-m") + 1] == "opencode/big-pickle"
    monkeypatch.setenv("OPENCODE_TIER", "go")
    agent_runs.start("opencode", "score-new")
    assert started["cmd"][started["cmd"].index("-m") + 1].startswith("opencode-go/")
    monkeypatch.setenv("OPENCODE_TIER", "paid")
    with pytest.raises(ValueError):
        agent_runs.start("opencode", "score-new")


def test_job_research_runs_on_one_named_dossier(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    job_id = "93bd70fa0de747a398ed4af6cd6c45dc"
    result = agent_runs.start("cursor", "research-job", job_id)
    assert result["job_id"] == job_id
    prompt = started["cmd"][-1]
    assert f"/api/jobs/{job_id}" in prompt
    assert "research_brief" in prompt and "apply_url" in prompt
    assert job_id in result["log"]


@pytest.mark.parametrize("job_id", [None, "", "../etc", "93bd70fa; rm -rf ~", "X" * 32])
def test_job_research_needs_a_real_job_id(job_id):
    with pytest.raises(ValueError):
        agent_runs.start("cursor", "research-job", job_id)


def test_job_tasks_are_not_listed_as_bulk_tasks():
    assert "research-job" not in agent_runs.TASKS


def test_runs_are_killed_after_the_time_limit(monkeypatch, tmp_path):
    killed = []

    class FakeProc:
        pid = 777

        def poll(self):
            return None

    monkeypatch.setattr(agent_runs, "LOG_DIR", tmp_path)
    monkeypatch.setattr(agent_runs.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    monkeypatch.setattr(agent_runs.shutil, "which", lambda name, path=None: "/bin/" + name)
    monkeypatch.setattr(agent_runs.os, "killpg", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(agent_runs, "MAX_RUNTIME", 0.05)
    result = agent_runs.start("codex", "score-new")
    agent_runs.time.sleep(0.3)
    assert killed == [777]
    assert "stopped after" in (tmp_path / result["log"]).read_text()


def test_advanced_params_never_hold_a_bare_multi_word_name():
    # Fantastic Jobs parses *_advanced as a tsquery, so "United States" is a 400. A multi word
    # name needs the phrase operator: "United <-> States".
    import re

    for name, preset in fantastic.PRESETS.items():
        for key, value in preset["params"].items():
            if not key.endswith("_advanced"):
                continue
            for piece in re.split(r"\s*(?:<->|[|&()!])\s*", value):
                assert not re.search(r"\s", piece.strip()), f"{name}.{key}: {piece!r}"


def test_agent_prompts_protect_the_root_resume():
    prompts = [t["prompt"] for t in (*agent_runs.TASKS.values(), *agent_runs.JOB_TASKS.values())]
    assert all("resume.pdf" in p and "Never write to" in p for p in prompts)


def test_antigravity_runs_headless_through_agy(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    result = agent_runs.start("antigravity", "score-new")
    assert started["cmd"][:3] == ["/bin/agy", "--dangerously-skip-permissions", "-p"]
    assert "Do not submit applications" in started["cmd"][-1]
    assert "-antigravity-" in result["log"]


def test_gemini_runs_on_the_api_key_home_and_cheap_model(monkeypatch, tmp_path):
    started = _fake_start(monkeypatch, tmp_path)
    seen = {}
    real = agent_runs.subprocess.Popen
    monkeypatch.setattr(agent_runs.subprocess, "Popen", lambda cmd, **kw: (seen.update(kw), real(cmd, **kw))[1])
    agent_runs.start("gemini", "triage-filter")
    cmd = started["cmd"]
    assert cmd[cmd.index("-m") + 1] == "gemini-3.5-flash-lite"
    assert seen["env"]["GEMINI_CLI_HOME"].endswith(".job-machine-gemini")
    assert "Never promote" in cmd[-1]


def test_other_tools_keep_the_normal_environment(monkeypatch, tmp_path):
    assert "GEMINI_CLI_HOME" not in agent_runs._tool_env("cursor")


def test_big_companies_are_kept_aside_not_captured():
    big = {**_job(9, "Google"), "organization": "Google"}
    mid = {**_job(10, "Mid"), "linkedin_org_employees": 5000}
    result = fantastic.run_search("remote-ca", 3, fetch=lambda _: [big, mid, _job(11, "Tiny")])
    assert [n["company"] for n in result["new"]] == ["Tiny"]
    assert len(result["aside"]) == 2


def test_india_based_roles_are_dropped():
    india = {**_job(12, "Desi"), "locations_derived": ["Bengaluru, Karnataka, India"]}
    result = fantastic.run_search("remote-ca", 2, fetch=lambda _: [india, _job(13, "Kept")])
    assert [n["company"] for n in result["new"]] == ["Kept"]


def _fantastic_job(n, org, office, scope=None):
    job = {"id": n, "title": "Software Engineer", "organization": org,
           "url": f"https://jobs.ashbyhq.com/x/{n}", "source": "ashby",
           "locations_derived": [office], "ai_work_arrangement": "Remote Solely",
           "description_text": "Build things.", "date_posted": "2026-11-06T00:00:00"}
    if scope:
        job["ai_remote_location_derived"] = [scope]
    return job


def test_fantastic_research_items_carry_tier_and_drop_india():
    jobs = [_fantastic_job(1, "Usa", "Austin, Texas, United States", "United States"),
            _fantastic_job(2, "Ger", "Berlin, Germany", "Germany"),
            # A European company hiring anywhere is still Tier E (European company, last).
            _fantastic_job(3, "Eurw", "Amsterdam, Netherlands", "Worldwide"),
            _fantastic_job(4, "Ind", "Austin, Texas, United States", "United States; India")]
    result = fantastic.run_search("remote-us", 4, fetch=lambda _: jobs)
    staged = {i["company"]: i for i in research_store.list_items()}
    assert {c: (i["tier"], i["region"]) for c, i in staged.items()} == {
        "Usa": ("A2", "us"), "Ger": ("E", "europe"), "Eurw": ("E", "europe")}
    assert staged["Eurw"]["open_to_canada"] is True  # the scope itself is open to Canada
    assert result["dropped"] == {"india": 1}


def test_fantastic_dossier_capture_notes_the_tier():
    fantastic.run_search("remote-ca", 1, fetch=lambda _: [
        _fantastic_job(1, "Can", "Vancouver, British Columbia, Canada")])
    [job] = job_store.load_jobs()
    assert "Tier A (canada)" in job.notes


@pytest.mark.parametrize("task", ["triage-research", "triage-filter"])
def test_triage_prompts_keep_tier_a2_and_e_finds(task):
    prompt = agent_runs.TASKS[task]["prompt"]
    assert "US residents only" not in prompt
    assert "residents of countries other than Canada" not in prompt
    assert "Tier A2" in prompt and "Tier E" in prompt and "India" in prompt


def test_fantastic_european_office_alongside_others_is_not_a_european_company():
    job = {**_fantastic_job(5, "SfCo", "San Francisco, California", "Worldwide"),
           "locations_derived": ["San Francisco, California", "Berlin, Germany"]}
    fantastic.run_search("remote-us", 1, fetch=lambda _: [job])
    [item] = research_store.list_items()
    assert (item["tier"], item["region"]) == ("A", "worldwide")


def test_fantastic_open_to_canada_falls_back_to_the_office_when_scope_is_missing():
    fantastic.run_search("remote-us", 1, fetch=lambda _: [_fantastic_job(6, "Van", "Vancouver, British Columbia, Canada")])
    [item] = research_store.list_items()
    assert item["tier"] == "A" and item["open_to_canada"] is True
