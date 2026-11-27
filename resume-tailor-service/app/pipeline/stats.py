"""Ledger summaries for GET /api/pipeline/stats (spec section 7): per step and adapter,
and per model, the attempts, pass rate, p50 and p90 duration, total cost and the last
error. Pure functions over Attempt records."""
from __future__ import annotations

import math
from datetime import datetime

from app.pipeline.models import Attempt


def percentile(values: list[int], pct: float) -> int | None:
    """Nearest rank percentile; None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(pct / 100 * len(ordered)) - 1)]


def _summary(attempts: list[Attempt]) -> dict:
    attempts = sorted(attempts, key=lambda a: a.started_at)
    durations = [a.duration_ms for a in attempts]
    costs = [a.cost for a in attempts if a.cost is not None]
    ok = sum(a.outcome == "ok" for a in attempts)
    failures = [a for a in attempts if a.outcome != "ok"]
    last_failure = failures[-1] if failures else None
    return {
        "attempts": len(attempts),
        "ok": ok,
        "pass_rate": ok / len(attempts) if attempts else 0.0,
        "p50_ms": percentile(durations, 50),
        "p90_ms": percentile(durations, 90),
        "cost": round(sum(costs), 6) if costs else None,
        "last_error": (last_failure.error or last_failure.outcome) if last_failure else "",
        "last_error_at": last_failure.started_at if last_failure else "",
        "last_at": attempts[-1].started_at if attempts else "",
    }


def _after(attempt: Attempt, since: datetime | None) -> bool:
    if since is None:
        return True
    try:
        return datetime.fromisoformat(attempt.started_at) >= since
    except ValueError:
        return False


def compute(attempts: list[Attempt], since: str = "") -> dict:
    cutoff = datetime.fromisoformat(since) if since else None
    kept = [a for a in attempts if _after(a, cutoff)]
    by_step: dict[tuple[str, str], list[Attempt]] = {}
    by_model: dict[str, list[Attempt]] = {}
    for attempt in kept:
        by_step.setdefault((attempt.step, attempt.adapter), []).append(attempt)
        if attempt.model:
            by_model.setdefault(attempt.model, []).append(attempt)
    return {
        "since": since,
        "steps": [{"step": step, "adapter": adapter, **_summary(group)}
                  for (step, adapter), group in sorted(by_step.items())],
        "models": [{"model": model, **_summary(group)} for model, group in sorted(by_model.items())],
    }
