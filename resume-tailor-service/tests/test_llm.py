"""`app.llm.complete`: the service's own model calls go through the router chain with
fallback (spec 13.1), so kit, tailor and answers work with `claude` absent from PATH.
No network and no real model: adapters are scripted or Pydantic AI FunctionModels."""
import json
import os

import pytest
from pydantic import BaseModel
from pydantic_ai import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import application_kit, llm, tailor
from app.bank import load_bank
from app.errors import ClaudeCliError
from app.pipeline import adapters, config, router, sdk, store
from app.pipeline.config import PipelineConfig
from app.pipeline.models import AdapterResult
from app.pipeline.router import Health

from tests.test_application_kit import BASE_DIR, _job, _valid_kit_payload
from tests.test_tailor import FIXTURE, VALID_MANIFEST_DICT


class Out(BaseModel):
    answer: str


class Scripted:
    def __init__(self, name, results):
        self.name = name
        self.results = list(results)
        self.prompts = []

    def call(self, prompt, *, run_id, step, schema, timeout):
        self.prompts.append(prompt)
        return self.results.pop(0) if self.results else AdapterResult(outcome="unavailable", error="exhausted")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(adapters, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(router, "HEALTH", Health(blocked_families=lambda: set()))
    monkeypatch.setattr(router, "meter_over_budget", lambda family: False)


def _save(adapters_: dict, steps: dict | None = None) -> PipelineConfig:
    full = {
        name: {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"], **extra}
        for name, extra in adapters_.items()
    }
    return config.save_config(PipelineConfig.model_validate({"adapters": full, "steps": steps or {}}))


def _script(monkeypatch, scripts: dict):
    monkeypatch.setattr(llm, "_build", lambda spec: scripts[spec.name])


def test_first_good_answer_wins_and_meta_names_the_adapter(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})
    a = Scripted("a", [AdapterResult(outcome="ok", output={"answer": "yes"}, model="m-a", tokens_in=5,
                                     tokens_out=2, cost=0.01)])
    _script(monkeypatch, {"a": a, "b": Scripted("b", [])})

    parsed, meta = llm.complete("reason", "Say yes", Out, step="kit")

    assert parsed == Out(answer="yes")
    assert (meta["adapter"], meta["model"], meta["tokens_in"], meta["cost"]) == ("a", "m-a", 5, 0.01)
    [attempt] = store.list_attempts(llm.LLM_RUN_ID)
    assert (attempt.step, attempt.adapter, attempt.outcome) == ("kit", "a", "ok")


def test_invalid_output_gets_one_retry_with_errors_then_the_next_adapter(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})
    bad = AdapterResult(outcome="ok", output={"nope": 1})
    a = Scripted("a", [bad, bad])
    b = Scripted("b", [AdapterResult(outcome="ok", output={"answer": "fine"})])
    _script(monkeypatch, {"a": a, "b": b})

    parsed, meta = llm.complete("reason", "Say", Out)

    assert parsed.answer == "fine" and meta["adapter"] == "b"
    assert len(a.prompts) == 2
    assert "answer" in a.prompts[1] and "rejected" in a.prompts[1]
    assert [x.outcome for x in store.list_attempts(llm.LLM_RUN_ID)] == ["invalid_output", "invalid_output", "ok"]


def test_unavailable_and_timeout_move_on_and_cool_down(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}, "c": {"cost_tier": 3}})
    a = Scripted("a", [AdapterResult(outcome="unavailable", error="Out of credits")])
    b = Scripted("b", [AdapterResult(outcome="timeout", error="killed")])
    c = Scripted("c", [AdapterResult(outcome="ok", output={"answer": "c"})])
    _script(monkeypatch, {"a": a, "b": b, "c": c})

    _, meta = llm.complete("reason", "Say", Out)

    assert meta["adapter"] == "c"
    assert len(a.prompts) == len(b.prompts) == 1
    assert router.HEALTH.status(config.load_config().adapters["a"])["healthy"] is False


def test_a_dict_schema_checks_required_keys_and_returns_a_dict(monkeypatch):
    _save({"a": {}})
    schema = {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}
    _script(monkeypatch, {"a": Scripted("a", [AdapterResult(outcome="ok", output={"y": 1}),
                                             AdapterResult(outcome="ok", output={"x": "1"})])})

    parsed, _ = llm.complete("reason", "p", schema)

    assert parsed == {"x": "1"}


def test_exhausted_chain_raises_a_claude_cli_error_subclass(monkeypatch):
    _save({"a": {}})
    _script(monkeypatch, {"a": Scripted("a", [AdapterResult(outcome="error", error="HTTP 400")])})

    with pytest.raises(llm.LlmUnavailableError, match="HTTP 400") as caught:
        llm.complete("reason", "p", Out)
    assert isinstance(caught.value, ClaudeCliError)


def test_no_adapter_for_the_capability_raises(monkeypatch):
    _save({"a": {"capabilities": ["cheap"]}})
    with pytest.raises(llm.LlmUnavailableError, match="reason"):
        llm.complete("reason", "p", Out)


def test_policy_violation_stops_the_chain(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})
    b = Scripted("b", [AdapterResult(outcome="ok", output={"answer": "b"})])
    _script(monkeypatch, {"a": Scripted("a", [AdapterResult(outcome="policy_violation", error="asked to submit")]),
                          "b": b})
    with pytest.raises(llm.LlmUnavailableError, match="policy"):
        llm.complete("reason", "p", Out)
    assert b.prompts == []


def test_exclude_adapters_and_step_prefs(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}, "c": {"cost_tier": 3}}, steps={"kit": {"prefer": ["c"]}})
    _script(monkeypatch, {name: Scripted(name, [AdapterResult(outcome="ok", output={"answer": name})])
                          for name in "abc"})

    assert llm.complete("reason", "p", Out, step="kit")[1]["adapter"] == "c"
    assert llm.complete("reason", "p", Out, step="kit", exclude_adapters=("c",))[1]["adapter"] == "a"
    assert llm.complete("reason", "p", Out, exclude_adapters=("a", "c"))[1]["adapter"] == "b"


def test_completer_is_the_text_seam_and_reports_meta(monkeypatch):
    _save({"a": {}})
    _script(monkeypatch, {"a": Scripted("a", [AdapterResult(outcome="ok", output={"answer": "x"})])})
    seen = []

    text = llm.completer("reason", Out, step="answers", on_meta=seen.append)("p")

    assert json.loads(text) == {"answer": "x"}
    assert seen[0]["adapter"] == "a"


# M2b done when: kit, tailor and answers work with `claude` absent from PATH (spec 13.4).


@pytest.fixture
def no_claude(monkeypatch, tmp_path):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("TEST_OR_KEY", "sk-or-v1-test-0123456789")
    defaults = config.load_defaults()
    adapters_ = {"claude_haiku": defaults.adapters["claude_haiku"].model_dump(exclude={"name"}),
                 "openrouter_test": {"type": "sdk", "model": "openrouter:anthropic/claude-haiku-4.5",
                                     "key_env": "TEST_OR_KEY", "capabilities": ["cheap", "reason"],
                                     "cost_tier": 2}}
    config.save_config(PipelineConfig.model_validate({"adapters": adapters_}))


def _model_answers(monkeypatch, payload: dict):
    def respond(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])

    monkeypatch.setattr(sdk, "build_model", lambda spec: FunctionModel(respond, model_name="or-test"))


def _adapters_tried(step):
    return [(a.adapter, a.outcome) for a in store.list_attempts(llm.LLM_RUN_ID) if a.step == step]


def test_kit_works_without_claude_on_path(monkeypatch, no_claude):
    assert not any(os.path.exists(os.path.join(p, "claude")) for p in os.environ["PATH"].split(os.pathsep))
    _model_answers(monkeypatch, _valid_kit_payload())
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    kit = application_kit.generate_kit(_job(), bank, max_retries=0)

    assert kit.analysis.score == 8 and "Acme Cloud" in kit.cover_letter
    assert _adapters_tried("kit") == [("claude_haiku", "unavailable"), ("openrouter_test", "ok")]


def test_answers_work_without_claude_on_path(monkeypatch, no_claude):
    _model_answers(monkeypatch, {"answer": "Yes. I am open to relocation.", "source_ids": ["profile.relocation"],
                                 "needs_user_input": False, "clarification": ""})
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    answer = application_kit.generate_answer(_job(), bank, "Are you willing to relocate?", max_retries=0)

    assert answer.source_ids == ["profile.relocation"]
    assert _adapters_tried("answers") == [("claude_haiku", "unavailable"), ("openrouter_test", "ok")]


def test_tailor_works_without_claude_on_path(monkeypatch, no_claude):
    _model_answers(monkeypatch, VALID_MANIFEST_DICT)

    manifest = tailor.get_manifest("jd text", "Acme", "SWE", load_bank(FIXTURE), max_retries=0)

    assert manifest.job_selections[0].job_id == "acme"
    assert _adapters_tried("tailor") == [("claude_haiku", "unavailable"), ("openrouter_test", "ok")]


def test_generators_default_to_llm_not_claude_cli():
    import inspect

    for fn in (application_kit.generate_kit, application_kit.generate_answer, tailor.get_manifest):
        default = inspect.signature(fn).parameters["complete"].default
        assert getattr(default, "__module__", "") == "app.llm", fn.__name__


# Codex review: a draft the generator's own validation rejects twice moves to the next
# adapter (spec 5.3 and 6.3), not back to the same cheapest one.


def _untraceable_kit():
    payload = _valid_kit_payload()
    payload["analysis"]["evidence"][0]["source_ids"] = ["invented.source"]
    return payload


def test_kit_rejected_twice_by_validation_falls_back_to_the_next_adapter(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})
    a = Scripted("a", [AdapterResult(outcome="ok", output=_untraceable_kit())] * 3)
    b = Scripted("b", [AdapterResult(outcome="ok", output=_valid_kit_payload())])
    _script(monkeypatch, {"a": a, "b": b})
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    kit = application_kit.generate_kit(_job(), bank, max_retries=2)

    assert kit.analysis.score == 8
    assert (len(a.prompts), len(b.prompts)) == (2, 1)


def test_with_one_adapter_validation_retries_stay_on_it(monkeypatch):
    _save({"a": {}})
    a = Scripted("a", [AdapterResult(outcome="ok", output=_untraceable_kit())] * 2
                 + [AdapterResult(outcome="ok", output=_valid_kit_payload())])
    _script(monkeypatch, {"a": a})
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    assert application_kit.generate_kit(_job(), bank, max_retries=2).analysis.score == 8
    assert len(a.prompts) == 3


def test_each_generator_call_starts_a_fresh_session(monkeypatch):
    _save({"a": {"cost_tier": 1}, "b": {"cost_tier": 2}})
    answer = {"answer": "Yes. I am open to relocation.", "source_ids": ["profile.relocation"],
              "needs_user_input": False, "clarification": ""}
    a = Scripted("a", [AdapterResult(outcome="ok", output=answer)] * 3)
    _script(monkeypatch, {"a": a, "b": Scripted("b", [])})
    bank = load_bank(BASE_DIR / "content" / "resume_bank.yaml")

    for _ in range(3):
        application_kit.generate_answer(_job(), bank, "Are you willing to relocate?", max_retries=0)
    assert len(a.prompts) == 3
