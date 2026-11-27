"""An adapter that replays scripted results, so the runner, router and fallback logic
can be tested with no network, no CLI and no model."""
from __future__ import annotations

from app.pipeline.models import AdapterResult


class FakeAdapter:
    def __init__(self, name: str, results: list[AdapterResult]):
        self.name = name
        self._results = list(results)
        # The `errors` list the runner passed on each call, to check repair prompts.
        self.calls: list[list[str]] = []

    def invoke(self, step, ctx, errors: list[str]) -> AdapterResult:
        self.calls.append(list(errors))
        if not self._results:
            return AdapterResult(outcome="unavailable", error="script exhausted")
        return self._results.pop(0)
