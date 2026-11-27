"""Picks which adapters may run a step, and in what order (spec 5.2).

The chain is every enabled adapter with the step's capability, minus the ones that
cannot run now (unhealthy) and the ones over their spend budget, ordered by:

1. the step's `prefer` list from the config, in its order;
2. `cost_tier`, cheapest first;
3. pass rate for this step over its last 30 attempts in the ledger (no history counts
   as a neutral 0.5, so a new adapter is tried before a proven bad one but after a
   proven good one; the canary is how a new model gets real traffic);
4. lower median duration.

A step canary sends its `share` of calls to one adapter first, so a new model earns a
pass rate before it is promoted. `resolve_chain` is pure: health, budget, ledger stats
and the random source are all passed in. Per adapter `max_parallel` and capability caps
are enforced by the worker pool (M6), not here.
"""
from __future__ import annotations

import importlib.util
import json
import random
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app import agent_health, agent_runs
from app.pipeline import adapters as adapters_module
from app.pipeline import config as config_module
from app.pipeline import store
from app.pipeline.config import AdapterSpec, PipelineConfig
from app.pipeline.models import AdapterResult, Attempt

COOLDOWN_SECONDS = 30 * 60
STATS_WINDOW = 30
NO_HISTORY_PASS_RATE = 0.5
AGENT_HEALTH_MAX_AGE = 6 * 3600
METER_DIR = Path(__file__).resolve().parents[3] / "tools" / "ai-meter"
METER_POLICY = METER_DIR / "policy.json"
METER_STATE = METER_DIR.parent.parent / "logs" / "ai-usage.json"
# The meter polls every 5 minutes; state older than this means the poller stopped.
METER_STALE_SECONDS = 3600


@dataclass(frozen=True)
class Stats:
    attempts: int
    pass_rate: float
    median_ms: float


def step_stats(step: str, attempts: list[Attempt], window: int = STATS_WINDOW) -> dict[str, Stats]:
    """Pass rate and median duration per adapter over its last `window` tries of a step."""
    by_adapter: dict[str, list[Attempt]] = {}
    for attempt in sorted(attempts, key=lambda a: a.started_at):
        if attempt.step == step:
            by_adapter.setdefault(attempt.adapter, []).append(attempt)
    stats = {}
    for name, tries in by_adapter.items():
        recent = tries[-window:]
        stats[name] = Stats(
            attempts=len(recent),
            pass_rate=sum(a.outcome == "ok" for a in recent) / len(recent),
            median_ms=statistics.median(a.duration_ms for a in recent),
        )
    return stats


def _agent_health_blocked() -> set[str]:
    """Tool families whose newest dashboard run log shows a block. Pipeline runs do not
    write those logs, so a block would never clear on its own; one older than
    AGENT_HEALTH_MAX_AGE is ignored and the in process cooldown takes over."""
    try:
        rows = agent_health.agent_health(agent_runs.LOG_DIR)
    except OSError:
        return set()
    cutoff = datetime.now(timezone.utc).timestamp() - AGENT_HEALTH_MAX_AGE
    blocked = set()
    for row in rows:
        if row["status"] != "blocked" or not row.get("at"):
            continue
        try:
            at = datetime.fromisoformat(row["at"]).timestamp()
        except ValueError:
            continue
        if at >= cutoff:
            blocked.add(row["tool"])
    return blocked


class Health:
    """Which adapters can run now. An `unavailable` outcome cools an adapter down for
    30 minutes in this process; `agent_health` (the newest dashboard run log per tool)
    blocks a whole tool family, such as every codex adapter when codex is out of
    credits."""

    def __init__(self, *, cooldown: int = COOLDOWN_SECONDS, clock: Callable[[], float] = time.time,
                 blocked_families: Callable[[], set[str]] = _agent_health_blocked):
        self._cooldown = cooldown
        self._clock = clock
        self._blocked_families = blocked_families
        self._until: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    def mark_unavailable(self, name: str, reason: str = "") -> None:
        with self._lock:
            self._until[name] = (self._clock() + self._cooldown, reason or "unavailable")

    def status(self, spec: AdapterSpec, blocked: set[str] | None = None) -> dict:
        with self._lock:
            until, reason = self._until.get(spec.name, (0.0, ""))
        if until > self._clock():
            return {"healthy": False, "reason": reason,
                    "until": datetime.fromtimestamp(until, tz=timezone.utc).isoformat()}
        if blocked is None:
            blocked = self._blocked_families()
        if spec.family and spec.family in blocked:
            return {"healthy": False, "reason": f"{spec.family} is blocked (see agent health)", "until": None}
        return {"healthy": True, "reason": "", "until": None}

    def blocked_families(self) -> set[str]:
        return self._blocked_families()


def meter_over_budget(family: str) -> bool:
    """Whether tools/ai-meter says this tool family is over budget or down. Reads the
    meter's last saved state with the meter's own rule and never polls (a poll runs
    CodeBurn for minutes). No family, no fresh state or no meter means not over budget: the
    budget only steers work, it never blocks it."""
    if not family or not METER_STATE.exists() or not METER_POLICY.exists():
        return False
    try:
        if time.time() - METER_STATE.stat().st_mtime > METER_STALE_SECONDS:
            return False
        meter = _load_meter()
        state = json.loads(METER_STATE.read_text())
        policy = json.loads(METER_POLICY.read_text())
        return meter._over(family, state, policy) is not None
    except Exception:
        return False


_METER = None


def _load_meter():
    global _METER
    if _METER is None:
        # tools/ai-meter is not a package (the hyphen), so load the file directly.
        spec = importlib.util.spec_from_file_location("ai_meter", METER_DIR / "meter.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _METER = module
    return _METER


def _never_over_budget(family: str) -> bool:
    return False


def resolve_chain(step, config: PipelineConfig, *, health: Health, ledger_stats: dict[str, Stats],
                  rng, over_budget: Callable[[str], bool] = _never_over_budget) -> list[AdapterSpec]:
    blocked = health.blocked_families()
    capable = [
        spec for spec in config.adapters.values()
        if spec.enabled and step.capability in spec.capabilities
        and health.status(spec, blocked)["healthy"]
    ]
    prefs = config.steps.get(step.name)
    prefer = prefs.prefer if prefs else []

    def rank(spec: AdapterSpec):
        stats = ledger_stats.get(spec.name)
        return (
            prefer.index(spec.name) if spec.name in prefer else len(prefer),
            spec.cost_tier,
            -(stats.pass_rate if stats else NO_HISTORY_PASS_RATE),
            stats.median_ms if stats else float("inf"),
            spec.name,
        )

    in_budget = [spec for spec in capable if not over_budget(spec.family)]
    # Over budget adapters stay as a last resort, like the meter's own routes.
    chain = sorted(in_budget or capable, key=rank)
    if prefs and prefs.canary and rng.random() < prefs.canary.share:
        canary = [spec for spec in chain if spec.name == prefs.canary.adapter]
        chain = canary + [spec for spec in chain if spec.name != prefs.canary.adapter]
    return chain


class TrackedAdapter:
    """Wraps an adapter so an `unavailable` outcome cools it down for later steps."""

    def __init__(self, adapter, health: Health):
        self._adapter = adapter
        self._health = health
        self.name = adapter.name

    def invoke(self, step, ctx, errors: list[str]) -> AdapterResult:
        return self._watch(self._adapter.invoke(step, ctx, errors))

    def call(self, *args, **kwargs) -> AdapterResult:
        return self._watch(self._adapter.call(*args, **kwargs))

    def _watch(self, result: AdapterResult) -> AdapterResult:
        if result.outcome == "unavailable":
            self._health.mark_unavailable(self.name, result.error)
        return result


def make_chain(load_config: Callable[[], PipelineConfig] = config_module.load_config, *,
               health: Health, rng=None, over_budget: Callable[[str], bool] = meter_over_budget,
               load_attempts: Callable[[], list[Attempt]] = store.list_attempts,
               build: Callable = adapters_module.build_adapter):
    """The runner's `resolve_chain` callable. Reads the stored config on every step, so
    a change from the dashboard applies to the next step without a restart."""
    rng = rng or random.Random()

    def chain(step) -> list[TrackedAdapter]:
        specs = resolve_chain(step, load_config(), health=health,
                              ledger_stats=step_stats(step.name, load_attempts()),
                              rng=rng, over_budget=over_budget)
        return [TrackedAdapter(build(spec), health) for spec in specs]

    return chain
