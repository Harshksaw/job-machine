import os
import time

from app import agent_health


def _log(tmp_path, name, text, age_seconds=0):
    path = tmp_path / name
    path.write_text(text)
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))
    return path


def _by_tool(rows):
    return {row["tool"]: row for row in rows}


def test_out_of_credits_is_blocked(tmp_path):
    _log(tmp_path, "20261121T012702Z-cursor-triage-research.log",
         "ActionRequiredError: Your team's prepaid balance is used up Ask a team admin")
    row = _by_tool(agent_health.agent_health(tmp_path))["cursor"]
    assert row["status"] == "blocked"
    assert row["label"] == "Out of credits"


def test_usage_limit_keeps_the_reset_time(tmp_path):
    _log(tmp_path, "codex-liveness-20261118-2158.log",
         "ERROR: You've hit your usage limit. Upgrade to Pro, or try again at 11:27 PM.")
    row = _by_tool(agent_health.agent_health(tmp_path))["codex"]
    assert row["status"] == "blocked"
    assert row["label"] == "Usage limit hit"
    assert "11:27 PM" in row["detail"]


def test_invalid_key_is_blocked_for_opencode(tmp_path):
    _log(tmp_path, "opencode-research-job-abc.log", "Error: Invalid credential")
    row = _by_tool(agent_health.agent_health(tmp_path))["opencode"]
    assert row["status"] == "blocked"
    assert row["label"] == "Bad key"


def test_clean_latest_run_is_ok_even_after_an_older_failure(tmp_path):
    _log(tmp_path, "20261121T012702Z-codex-triage-research.log", "usage limit", age_seconds=3600)
    _log(tmp_path, "20261121T050730Z-codex-triage-research.log", "Done. 12 rows triaged.")
    row = _by_tool(agent_health.agent_health(tmp_path))["codex"]
    assert row["status"] == "ok"


def test_tool_with_no_logs_is_idle(tmp_path):
    _log(tmp_path, "20261121T012702Z-cursor-score-new.log", "all good")
    rows = _by_tool(agent_health.agent_health(tmp_path))
    assert rows["codex"]["status"] == "idle"
    assert rows["opencode"]["status"] == "idle"


def test_empty_log_is_skipped_in_favor_of_the_previous_run(tmp_path):
    _log(tmp_path, "20261121T010000Z-cursor-score-new.log", "Your team's prepaid balance is used up", age_seconds=60)
    _log(tmp_path, "20261121T020000Z-cursor-score-new.log", "")
    row = _by_tool(agent_health.agent_health(tmp_path))["cursor"]
    assert row["status"] == "blocked"


def test_missing_directory_is_all_idle(tmp_path):
    rows = agent_health.agent_health(tmp_path / "nope")
    assert {row["status"] for row in rows} == {"idle"}
