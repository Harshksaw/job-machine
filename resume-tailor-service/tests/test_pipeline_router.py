import json
import random

import pytest

from app import job_store
from app.models import JobWorkspaceInput
from app.pipeline import router, runner, store
from app.pipeline.config import PipelineConfig
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult, Attempt
from app.pipeline.router import Health, Stats, resolve_chain, step_stats
from app.pipeline.runner import Pipeline, StepResult, StepSpec


class Step:
    def __init__(self, name="fit_score", capability="reason"):
        self.name = name
        self.capability = capability


def _cfg(adapters: dict, steps: dict | None = None) -> PipelineConfig:
    full = {
        name: {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"], **extra}
        for name, extra in adapters.items()
    }
    return PipelineConfig.model_validate({"adapters": full, "steps": steps or {}})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _names(chain):
    return [spec.name for spec in chain]


def _resolve(cfg, step=None, *, health=None, stats=None, rng=None, over_budget=None):
    return _names(resolve_chain(
        step or Step(), cfg, health=health or Health(blocked_families=lambda: set()),
        ledger_stats=stats or {}, rng=rng or random.Random(0),
        **({"over_budget": over_budget} if over_budget else {}),
    ))


def test_only_enabled_adapters_with_the_capability_ordered_by_cost_tier():
    cfg = _cfg({
        "pricey": {"cost_tier": 3},
        "cheap": {"cost_tier": 1},
        "off": {"cost_tier": 0, "enabled": False},
        "wrong": {"cost_tier": 0, "capabilities": ["web"]},
    })
    assert _resolve(cfg) == ["cheap", "pricey"]


def test_prefer_list_comes_first_in_its_own_order():
    cfg = _cfg({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}, "c": {"cost_tier": 3}},
               {"fit_score": {"prefer": ["c", "b"]}})
    assert _resolve(cfg) == ["c", "b", "a"]
    assert _resolve(cfg, Step("other")) == ["a", "b", "c"]


def test_same_tier_orders_by_pass_rate_then_median_duration():
    cfg = _cfg({"a": {}, "b": {}, "c": {}, "d": {}})
    stats = {
        "a": Stats(attempts=10, pass_rate=0.5, median_ms=100),
        "b": Stats(attempts=10, pass_rate=0.9, median_ms=900),
        "c": Stats(attempts=10, pass_rate=0.9, median_ms=200),
    }
    # d has no history: neutral 0.5 prior, unknown duration sorts after a known one.
    assert _resolve(cfg, stats=stats) == ["c", "b", "a", "d"]


def test_unavailable_cools_down_for_thirty_minutes():
    clock = Clock()
    health = Health(clock=clock, blocked_families=lambda: set())
    cfg = _cfg({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})

    health.mark_unavailable("a", "Out of credits")
    assert _resolve(cfg, health=health) == ["b"]
    assert health.status(cfg.adapters["a"])["reason"] == "Out of credits"

    clock.now += 29 * 60
    assert _resolve(cfg, health=health) == ["b"]
    clock.now += 2 * 60
    assert _resolve(cfg, health=health) == ["a", "b"]


def test_agent_health_blocks_a_whole_family():
    health = Health(blocked_families=lambda: {"codex"})
    cfg = _cfg({"a": {"family": "codex"}, "b": {"family": "cursor"}})
    assert _resolve(cfg, health=health) == ["b"]
    assert health.status(cfg.adapters["a"])["healthy"] is False


def test_over_budget_adapters_are_dropped():
    cfg = _cfg({"a": {"cost_tier": 1, "family": "claude"}, "b": {"cost_tier": 2, "family": "cursor"}})
    assert _resolve(cfg, over_budget=lambda family: family == "claude") == ["b"]
    # Spec 5.2: over budget means out of the chain, even when nothing is left.
    assert _resolve(cfg, over_budget=lambda family: True) == []


def test_canary_takes_the_front_for_its_share():
    cfg = _cfg({"a": {"cost_tier": 1}, "new": {"cost_tier": 3}},
               {"fit_score": {"canary": {"adapter": "new", "share": 0.25}}})

    class Fixed:
        def __init__(self, value):
            self.value = value

        def random(self):
            return self.value

    assert _resolve(cfg, rng=Fixed(0.1)) == ["new", "a"]
    assert _resolve(cfg, rng=Fixed(0.3)) == ["a", "new"]
    rng = random.Random(7)
    fronts = sum(_resolve(cfg, rng=rng)[0] == "new" for _ in range(2000))
    assert 400 < fronts < 600


def test_step_stats_uses_the_last_thirty_attempts_of_that_step():
    def attempt(i, adapter, outcome, ms, step="fit_score"):
        return Attempt(id=str(i), run_id="r", job_id="j", step=step, adapter=adapter,
                       started_at=f"2026-11-26T00:00:{i:02d}", duration_ms=ms, outcome=outcome)

    attempts = [attempt(i, "a", "timeout", 10) for i in range(10)]
    attempts += [attempt(10 + i, "a", "ok", 100) for i in range(30)]
    attempts += [attempt(50, "b", "ok", 300), attempt(51, "b", "invalid_output", 500)]
    attempts += [attempt(52, "a", "timeout", 1, step="other")]

    stats = step_stats("fit_score", attempts)

    assert stats["a"] == Stats(attempts=30, pass_rate=1.0, median_ms=100)
    assert stats["b"] == Stats(attempts=2, pass_rate=0.5, median_ms=400)


def test_over_budget_reads_meter_state_without_polling(monkeypatch, tmp_path):
    state = tmp_path / "ai-usage.json"
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"throttle_at": 0.8, "budgets": {"claude": {"day": 10}}, "routes": {}}))
    monkeypatch.setattr(router, "METER_STATE", state)
    monkeypatch.setattr(router, "METER_POLICY", policy)

    assert router.meter_over_budget("claude") is False  # no state yet: never blocks
    state.write_text(json.dumps({"providers": {"claude": {"day": 9}}, "health": {}}))
    assert router.meter_over_budget("claude") is True
    assert router.meter_over_budget("cursor") is False
    assert router.meter_over_budget("") is False
    # A stale state (the poller stopped) is ignored rather than trusted forever.
    import os
    os.utime(state, (0, 0))
    assert router.meter_over_budget("claude") is False


def test_make_chain_feeds_the_runner_and_cools_down_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    cfg = _cfg({"dead": {"cost_tier": 1}, "live": {"cost_tier": 2}})
    fakes = {
        "dead": FakeAdapter("dead", [AdapterResult(outcome="unavailable", error="Out of credits")]),
        "live": FakeAdapter("live", [AdapterResult(outcome="ok", output={"fit_score": 7})] * 2),
    }
    health = Health(blocked_families=lambda: set())
    chain = router.make_chain(lambda: cfg, health=health, rng=random.Random(0),
                              over_budget=lambda family: False, build=lambda spec: fakes[spec.name])

    from pydantic import BaseModel

    class Fit(BaseModel):
        fit_score: int

    pipeline = Pipeline("p", (StepSpec("fit_score", "agent", capability="reason", owns=("fit_score",), schema=Fit,
                                       finish=lambda parsed, ctx: StepResult(output=parsed.model_dump(),
                                                                             writes={"fit_score": parsed.fit_score})),))
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))
    run_id = store.create_run(job.id, "p", pipeline.order).id

    result = runner.run(run_id, pipeline, owner="w", resolve_chain=chain)

    assert result.status == "packet_ready"
    assert [a.adapter for a in store.list_attempts(run_id)] == ["dead", "live"]
    assert health.status(cfg.adapters["dead"])["healthy"] is False
    assert [a.name for a in chain(pipeline.steps[0])] == ["live"]


def test_agent_health_blocks_expire_since_pipeline_runs_never_refresh_them(monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    rows = [
        {"tool": "codex", "status": "blocked", "at": (now - timedelta(minutes=20)).isoformat()},
        {"tool": "cursor", "status": "blocked", "at": (now - timedelta(days=2)).isoformat()},
        {"tool": "gemini", "status": "ok", "at": now.isoformat()},
    ]
    monkeypatch.setattr(router.agent_health, "agent_health", lambda log_dir: rows)

    assert router._agent_health_blocked() == {"codex"}
