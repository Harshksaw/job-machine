import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cursor_queue.py"
spec = importlib.util.spec_from_file_location("cursor_queue", SCRIPT)
cursor_queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cursor_queue)


def _job(id, fit, brief=None, next_action="", status="discovered", location="Remote", role="Software Engineer"):
    job = {"id": id, "company": f"Co{id}", "role": role, "status": status, "fit_score": fit,
           "work_mode": "remote", "location": location, "next_action": next_action}
    if brief is not None:
        job["research_brief"] = brief
    return job


@pytest.fixture
def api(monkeypatch):
    """A fake dashboard API: the list leaves research_brief out, the full dossier has it."""
    state = {"jobs": [], "full": {}, "calls": []}

    def get(path):
        state["calls"].append(path)
        if path == "/api/jobs":
            return state["jobs"]
        if path == "/api/research":
            return []
        if path.startswith("/api/jobs/"):
            return state["full"][path.rsplit("/", 1)[1]]
        raise AssertionError(path)
    monkeypatch.setattr(cursor_queue, "_get", get)
    return state


@pytest.mark.parametrize("text, token", [
    ("Tier A, 40 people, seed", "A"),
    ("Tier A2: US residents only", "A2"),
    ("  tier a2 uk only", "A2"),
    ("Tier E, Berlin startup", "E"),
    ("Tier B", "B"),
    ("Tier A\nmore", "A"),
    ("Tierra Labs", None),
    ("Tier AB", None),
    ("", None),
])
def test_tier_token_is_exact(text, token):
    assert cursor_queue._tier_token(text) == token


def test_tier_a2_is_not_tier_a(api):
    job = _job("1", 9, brief="Tier A2 US only")
    assert not cursor_queue._tier_a(job)
    assert cursor_queue._tier_a2(job)


def test_tier_a2_reads_the_full_dossier_when_the_list_leaves_the_brief_out(api):
    api["full"]["7"] = {"research_brief": "Tier A2, UK residents only"}
    job = _job("7", 7)  # list row: no research_brief, no tier in next_action
    assert cursor_queue._tier_a2(job)
    assert "/api/jobs/7" in api["calls"]


def test_plan_orders_tier_a_then_a2_then_e_and_outreach_is_tier_a_only(api):
    api["jobs"] = [
        _job("e", 9, brief="Tier E, Europe only"),
        _job("a2", 9, brief="Tier A2 US only"),
        _job("a", 8, brief="Tier A open to Canada"),
        _job("a_hi", 9, next_action="Tier A, apply"),
        _job("b", 9, brief="Tier B"),
        _job("ready_a2", 8, brief="Tier A2 UK", status="ready"),
        _job("ready_a", 8, brief="Tier A", status="ready"),
    ]
    api["full"] = {j["id"]: j for j in api["jobs"]}
    plan = cursor_queue.build_plan()
    # Backlog order: Tier A, Tier A2, Tier B, then Tier E (Europe) last.
    assert plan["apply"] == ["a_hi", "a", "ready_a", "a2", "ready_a2", "b", "e"]
    assert "b" not in plan["score"]
    assert plan["review"] == ["a_hi", "a", "ready_a", "a2", "ready_a2"]
    assert plan["outreach"] == ["ready_a"]


def test_low_fit_tiers_stay_in_score(api):
    api["jobs"] = [_job("b6", 6, brief="Tier B"), _job("e6", 6, brief="Tier E"),
                   _job("a7", 7, brief="Tier A"), _job("none", 5)]
    plan = cursor_queue.build_plan()
    assert plan["apply"] == []
    assert plan["score"] == ["b6", "e6", "a7", "none"]


def test_indiana_is_not_india(api):
    api["jobs"] = [_job("in", 8, brief="Tier A", location="Indianapolis, Indiana"),
                   _job("bl", 8, brief="Tier A", location="Bengaluru, India")]
    plan = cursor_queue.build_plan()
    assert [row["id"] for row in plan["cleanup_jobs"]] == ["bl"]
    assert plan["apply"] == ["in"]
