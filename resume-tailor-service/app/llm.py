"""The service's own model calls (kit, answers, tailor), behind the agent router.

`complete(capability, prompt, schema)` reads the stored agent config on every call, asks
the router for the chain of adapters with that capability and falls back the way the
pipeline runner does (spec 5.3): invalid output gets one more try on the same adapter
with the error list, unavailable, timeout and error move to the next adapter, a policy
violation stops. So losing the `claude` login, or any one vendor, is a config change
and never breaks kit, tailor or answers (spec 13.1).

Every try is an attempt in the ledger, so pass rate, time and cost per model show up
next to the pipeline's. `completer(...)` keeps the `Callable[[str], str]` shape the
generators take, so their prompts, validation and retries are untouched.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.errors import ClaudeCliError

# Ledger run id for calls made outside a pipeline run (the dashboard's kit, answer and
# tailor routes).
LLM_RUN_ID = "llm"
# Callers that are not pipeline steps, with the capability they need, so the Settings
# step preferences can name them too.
DIRECT_STEPS = {"tailor": "reason"}

_RNG = random.Random()


class LlmUnavailableError(ClaudeCliError):
    """Every adapter in the chain failed. A ClaudeCliError, so the routes that answer
    502 for a failed model call keep doing so."""


@dataclass(frozen=True)
class _Target:
    name: str
    capability: str


def _build(spec):
    from app.pipeline.adapters import build_adapter

    return build_adapter(spec)


def _json_schema(schema) -> dict:
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.model_json_schema()
    return schema


def _check(schema, output: dict) -> tuple[Any, list[str]]:
    """The parsed value and the errors, from a Pydantic class or a JSON schema dict (its
    required top level keys)."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            return schema.model_validate(output), []
        except ValidationError as exc:
            return None, [
                f"{'.'.join(str(part) for part in error['loc']) or 'output'}: {error['msg']}"
                for error in exc.errors()
            ]
    missing = [key for key in schema.get("required", []) if key not in output]
    if missing:
        return None, [f"{key}: Field required" for key in missing]
    return output, []


def _repair(prompt: str, errors: list[str]) -> str:
    if not errors:
        return prompt
    return prompt + "\n\nYour last answer was rejected. Fix these problems:\n" + "\n".join(f"- {e}" for e in errors)


def complete(capability: str, prompt: str, schema, *, step: str = "", exclude_adapters=(),
             run_id: str = LLM_RUN_ID, job_id: str = "") -> tuple[Any, dict]:
    """One structured model call through the router. Returns the parsed value (a model
    instance for a Pydantic class, else a dict) and meta: the adapter and model that
    answered, tokens, cost, and what failed before it. Raises LlmUnavailableError when
    the whole chain fails."""
    from app.pipeline import config, router, store
    from app.pipeline.models import AdapterResult, Attempt, now_iso

    target = _Target(step or capability, capability)
    specs = router.resolve_chain(
        target, config.load_config(), health=router.HEALTH,
        ledger_stats=router.step_stats(target.name, store.list_attempts()),
        rng=_RNG, over_budget=router.meter_over_budget, exclude=tuple(exclude_adapters),
    )
    if not specs:
        skipped = f" (excluding {', '.join(exclude_adapters)})" if exclude_adapters else ""
        raise LlmUnavailableError(f"no healthy enabled adapter offers capability {capability!r}{skipped}")
    json_schema = _json_schema(schema)
    failed: list[str] = []
    for spec in specs:
        adapter = router.TrackedAdapter(_build(spec), router.HEALTH)
        errors: list[str] = []
        for _ in range(2):
            started, t0 = now_iso(), time.monotonic()
            try:
                result = adapter.call(_repair(prompt, errors), run_id=run_id, step=target.name,
                                      schema=json_schema, timeout=spec.timeout_for(capability))
            except Exception as exc:
                result = AdapterResult(outcome="error", error=f"{type(exc).__name__}: {exc}"[:300])
            parsed = None
            if result.outcome == "ok":
                parsed, errors = _check(schema, result.output or {})
                if errors:
                    result = result.model_copy(update={"outcome": "invalid_output", "error": "; ".join(errors)[:300]})
            elif result.outcome == "invalid_output":
                errors = [result.error or "output was not a JSON object"]
            store.add_attempt(Attempt(
                id=uuid.uuid4().hex, run_id=run_id, job_id=job_id, step=target.name, adapter=spec.name,
                model=result.model, started_at=started, duration_ms=int((time.monotonic() - t0) * 1000),
                outcome=result.outcome, error=result.error, tokens_in=result.tokens_in,
                tokens_out=result.tokens_out, cost=result.cost, output_ref=result.output_ref,
            ))
            if result.outcome == "ok":
                return parsed, {"adapter": spec.name, "model": result.model, "tokens_in": result.tokens_in,
                                "tokens_out": result.tokens_out, "cost": result.cost, "failed": failed}
            failed.append(f"{spec.name}: {result.outcome} {result.error}".strip())
            if result.outcome == "policy_violation":
                raise LlmUnavailableError(f"policy violation, chain stopped: {failed[-1]}")
            if result.outcome != "invalid_output":
                break
    raise LlmUnavailableError(f"every adapter failed; last: {failed[-1]}")


def completer(capability: str, schema, *, step: str = "", on_meta: Callable[[dict], None] | None = None,
              **options) -> Callable[[str], str]:
    """A one argument `complete(prompt) -> JSON text` for the generators, routed through
    `complete`. `on_meta` sees which adapter answered each call."""

    def complete_text(prompt: str) -> str:
        parsed, meta = complete(capability, prompt, schema, step=step, **options)
        if on_meta is not None:
            on_meta(meta)
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump(mode="json", by_alias=True)
        return json.dumps(parsed)

    return complete_text
