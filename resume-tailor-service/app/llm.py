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
_clock = time.monotonic
_CONFIG_BUDGET = object()  # "use the config's direct_call_budget for a direct call"


class LlmUnavailableError(ClaudeCliError):
    """Every adapter in the chain failed. A ClaudeCliError, so the routes that answer
    502 for a failed model call keep doing so."""


class NoAdapterError(LlmUnavailableError):
    """No adapter is left to try (none enabled, healthy or not excluded)."""


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


def _specs(target: _Target, exclude, cfg=None) -> list:
    from app.pipeline import config, router, store

    return router.resolve_chain(
        target, cfg or config.load_config(), health=router.HEALTH,
        ledger_stats=router.step_stats(target.name, store.list_attempts()),
        rng=_RNG, over_budget=router.meter_over_budget, exclude=tuple(exclude),
    )


def chain_names(capability: str, step: str = "", exclude=()) -> list[str]:
    """The adapters `complete` would try now, in order."""
    return [spec.name for spec in _specs(_Target(step or capability, capability), exclude)]


def deadline_for(run_id: str, budget=_CONFIG_BUDGET, cfg=None) -> tuple[float, int] | None:
    """(clock time to stop at, budget seconds) for a call, or None for no budget. A
    direct call (run id `llm`) gets the config's direct_call_budget by default; a
    pipeline step gets none, its adapters keep their per step timeouts."""
    if budget is _CONFIG_BUDGET:
        if run_id != LLM_RUN_ID:
            return None
        from app.pipeline import config

        budget = (cfg or config.load_config()).direct_call_budget
    if not budget:
        return None
    return _clock() + budget, int(budget)


def _left(deadline: tuple[float, int] | None, failed: list[str]) -> float | None:
    if deadline is None:
        return None
    left = deadline[0] - _clock()
    if left <= 0:
        tried = f"; tried: {'; '.join(failed)}" if failed else ""
        raise LlmUnavailableError(f"time budget of {deadline[1]}s used up before an adapter answered{tried}")
    return left


def complete(capability: str, prompt: str, schema, *, step: str = "", exclude_adapters=(),
             run_id: str = LLM_RUN_ID, job_id: str = "", budget=_CONFIG_BUDGET,
             deadline: tuple[float, int] | None = None) -> tuple[Any, dict]:
    """One structured model call through the router. Returns the parsed value (a model
    instance for a Pydantic class, else a dict) and meta: the adapter and model that
    answered, tokens, cost, and what failed before it. Raises LlmUnavailableError when
    the whole chain fails (NoAdapterError when there was nothing to try) or the time
    budget runs out (see deadline_for; `deadline` carries one across several calls)."""
    from app.pipeline import config, router, store
    from app.pipeline.models import AdapterResult, Attempt, now_iso

    cfg = config.load_config()
    if deadline is None:
        deadline = deadline_for(run_id, budget, cfg)
    _left(deadline, [])
    target = _Target(step or capability, capability)
    specs = _specs(target, exclude_adapters, cfg)
    if not specs:
        skipped = f" (excluding {', '.join(exclude_adapters)})" if exclude_adapters else ""
        raise NoAdapterError(f"no healthy enabled adapter offers capability {capability!r}{skipped}")
    json_schema = _json_schema(schema)
    failed: list[str] = []
    for spec in specs:
        adapter = router.TrackedAdapter(_build(spec), router.HEALTH)
        errors: list[str] = []
        for _ in range(2):
            left = _left(deadline, failed)
            timeout = spec.timeout_for(capability)
            if left is not None:
                timeout = min(timeout, left)
            started, t0 = now_iso(), time.monotonic()
            try:
                result = adapter.call(_repair(prompt, errors), run_id=run_id, step=target.name,
                                      schema=json_schema, timeout=timeout)
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


class Session:
    """The `complete(prompt) -> JSON text` callable the generators take, routed through
    `complete`.

    The generators run their own validation (facts traced to the bank, word limits,
    voice) and call again with the errors when a draft fails. A session turns that into
    the spec 5.3 fallback: an adapter whose answer was sent back twice is skipped on the
    next call, so the third try goes to the next adapter (or stays on the same one when
    it is the only one). Generators call `fresh()` once per draft, so one question's
    repairs never count against the next; a pipeline step keeps one root session and
    learns every author from it (`authors`), and `drop_last()` excludes the adapter that
    just failed a whole draft so the step can try another."""

    def __init__(self, capability: str, schema, *, step: str = "", on_meta: Callable[[dict], None] | None = None,
                 parent: Session | None = None, record: bool = True, **options):
        self.capability, self.schema, self.step = capability, schema, step
        self.on_meta, self.options, self.record = on_meta, options, record
        self.parent = parent
        self.authors: list[str] = []
        self.excluded: set[str] = set()
        self.last = ""
        self._answers: dict[str, int] = {}
        self._deadline: tuple[float, int] | None = None
        self._started = False

    @property
    def _root(self) -> Session:
        return self.parent._root if self.parent is not None else self

    def fresh(self) -> Session:
        return Session(self.capability, self.schema, step=self.step, on_meta=self.on_meta,
                       parent=self, record=self.record, **self.options)

    def _seen(self, meta: dict) -> None:
        root = self._root
        if not root.record:
            return
        adapter = meta.get("adapter") or ""
        root.last = adapter
        if adapter and adapter not in root.authors:
            root.authors.append(adapter)

    def _options(self) -> dict:
        """The call options, with one time budget for this whole draft."""
        options = dict(self.options)
        if not self._started:
            self._started = True
            self._deadline = deadline_for(options.get("run_id", LLM_RUN_ID), options.get("budget", _CONFIG_BUDGET))
        options.pop("budget", None)
        return {**options, "deadline": self._deadline, "budget": None}

    def __call__(self, prompt: str) -> str:
        hard = set(self._root.excluded)
        sent_back = {name for name, count in self._answers.items() if count >= 2}
        try:
            parsed, meta = complete(self.capability, prompt, self.schema, step=self.step,
                                    exclude_adapters=tuple(sorted(hard | sent_back)), **self._options())
        except NoAdapterError:
            if not sent_back - hard:
                raise
            parsed, meta = complete(self.capability, prompt, self.schema, step=self.step,
                                    exclude_adapters=tuple(sorted(hard)), **self._options())
        adapter = meta.get("adapter") or ""
        self._answers[adapter] = self._answers.get(adapter, 0) + 1
        self._seen(meta)
        if self.on_meta is not None:
            self.on_meta(meta)
        if isinstance(parsed, BaseModel):
            parsed = parsed.model_dump(mode="json", by_alias=True)
        return json.dumps(parsed)

    def drop_last(self) -> bool:
        """Exclude the adapter that answered last, if another one is left to try."""
        root = self._root
        if not root.last or root.last in root.excluded:
            return False
        remaining = chain_names(self.capability, self.step, tuple(root.excluded | {root.last}))
        if not remaining:
            return False
        root.excluded.add(root.last)
        return True


def completer(capability: str, schema, *, step: str = "", on_meta: Callable[[dict], None] | None = None,
              **options) -> Session:
    """A shareable template session (a generator's default `complete`). It records no
    authors itself; every generator call works on its own `fresh()` copy."""
    return Session(capability, schema, step=step, on_meta=on_meta, record=False, **options)


def fresh(complete_fn):
    """A generator's per draft callable: a fresh session for a routed one, else as is."""
    return complete_fn.fresh() if isinstance(complete_fn, Session) else complete_fn
