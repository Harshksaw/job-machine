"""M2b router gaps: review runs on a different adapter than the one that wrote the kit
and answers (spec 6.4), step capabilities come from PACKET_PIPELINE, adapters whose key
is unset are skipped and shown as such, and a config PUT changes the next chain."""
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app import job_store, llm
from app.models import JobWorkspaceInput
from app.pipeline import adapters, api, config, pipelines, router, runner, steps_agent, steps_service, store
from app.pipeline.config import PipelineConfig
from app.pipeline.fake import FakeAdapter
from app.pipeline.models import AdapterResult
from app.pipeline.router import Health, resolve_chain
from app.pipeline.runner import Pipeline, StepResult, StepSpec
from tests.test_application_kit import _valid_kit_payload

HEADERS = {"X-Job-Machine": "dashboard"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(adapters, "LOG_DIR", tmp_path / "logs")
    health = Health(blocked_families=lambda: set())
    monkeypatch.setattr(router, "HEALTH", health)
    monkeypatch.setattr(api, "HEALTH", health)
    monkeypatch.setattr(router, "meter_over_budget", lambda family: False)


class Out(BaseModel):
    ok: bool


def _job():
    return job_store.add_job(JobWorkspaceInput(
        company="Acme Cloud", role="Backend Engineer",
        jd_text="Acme Cloud needs a Backend Engineer with FastAPI, AWS, and RAG experience. Build reliable services."))


def _author(names):
    return StepSpec("kit", "code", run=lambda ctx: StepResult(output={"meta": {"authors": names}}))


def _review(**extra):
    return StepSpec("review", "agent", deps=("kit",), capability="cheap", schema=Out, independent_of=("kit",),
                    finish=lambda parsed, ctx: StepResult(output=parsed.model_dump()), **extra)


def _run(pipeline, chain):
    created = store.create_run(_job().id, pipeline.name, pipeline.order)
    return runner.run(created.id, pipeline, owner="w", resolve_chain=chain)


# (a) review on a different adapter


def test_review_skips_the_adapter_that_wrote_the_kit():
    a = FakeAdapter("a", [AdapterResult(outcome="ok", output={"ok": True})])
    b = FakeAdapter("b", [AdapterResult(outcome="ok", output={"ok": True})])
    result = _run(Pipeline("p", (_author(["a"]), _review())), lambda step: [a, b])

    assert result.status == "packet_ready", result.terminal_reason
    assert a.calls == [] and len(b.calls) == 1
    assert [x.adapter for x in store.list_attempts(result.id) if x.step == "review"] == ["b"]


def test_review_fails_clearly_when_only_the_author_could_review():
    a = FakeAdapter("a", [AdapterResult(outcome="ok", output={"ok": True})])
    result = _run(Pipeline("p", (_author(["a"]), _review())), lambda step: [a])

    assert result.status == "failed"
    assert "other than a" in result.steps["review"].error
    assert a.calls == []


def test_packet_review_is_independent_of_kit_and_answers():
    review = next(step for step in pipelines.PACKET_PIPELINE.steps if step.name == "review")
    assert review.independent_of == ("kit", "answers")
    assert steps_agent.review_step().independent_of == ("kit", "answers")


def test_kit_step_routes_through_llm_and_records_its_author(monkeypatch):
    calls = []

    def complete(capability, prompt, schema, **options):
        calls.append((capability, options))
        return _valid_kit_payload(), {"adapter": "openrouter_haiku", "model": "m"}

    monkeypatch.setattr(llm, "complete", complete)
    fit = StepSpec("fit_score", "code", run=lambda ctx: StepResult(output={"score": 8}))
    pipeline = Pipeline("p", (fit, steps_service.kit_step(deps=("fit_score",))))
    result = _run(pipeline, lambda step: [])

    assert result.status == "packet_ready", result.terminal_reason
    assert result.steps["kit"].output["meta"] == {"authors": ["openrouter_haiku"]}
    capability, options = calls[0]
    assert capability == "reason"
    assert (options["step"], options["run_id"]) == ("kit", result.id)


def test_answers_step_records_every_author(monkeypatch):
    answer = {"answer": "I built a RAG platform on FastAPI and Qdrant, and it handles ingestion for many tenants.",
              "source_ids": ["project.docintel.bullet.1"], "needs_user_input": False, "clarification": ""}
    authors = iter(["x", "y"])
    monkeypatch.setattr(llm, "complete", lambda *a, **k: (answer, {"adapter": next(authors)}))
    job = _job()
    job_store.patch_job(job.id, {"form_fields": [{"label": "Why Acme Cloud?", "kind": "textarea"},
                                                 {"label": "Tell us about a project", "kind": "textarea"}]},
                        reason="t", session="t")
    pipeline = Pipeline("p", (steps_service.answers_step(),))
    created = store.create_run(job.id, pipeline.name, pipeline.order)
    result = runner.run(created.id, pipeline, owner="w")

    assert result.status == "packet_ready", result.terminal_reason
    assert result.steps["answers"].output["meta"] == {"authors": ["x", "y"]}


# (b) step capabilities from PACKET_PIPELINE


def _client():
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_step_capabilities_come_from_the_packet_pipeline():
    derived = {step.name: step.capability for step in pipelines.PACKET_PIPELINE.steps if step.capability}
    assert api.STEP_CAPABILITIES == {**derived, **llm.DIRECT_STEPS}
    rows = _client().get("/api/pipeline/steps").json()
    assert {"step": "kit", "capability": "reason"} in rows
    assert {"step": "review", "capability": "cheap"} in rows
    assert all(set(row) == {"step", "capability"} for row in rows)


# (c) unset key_env skipped and shown


def _sdk_cfg(**extra) -> PipelineConfig:
    return PipelineConfig.model_validate({"adapters": {
        "or": {"type": "sdk", "model": "openrouter:x", "key_env": "TEST_UNSET_KEY", "capabilities": ["reason"],
               "cost_tier": 1},
        "cli": {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"], "cost_tier": 2},
    }})


class _Step:
    name = "fit_score"
    capability = "reason"


def test_an_adapter_without_its_key_is_skipped_and_says_why(monkeypatch):
    monkeypatch.delenv("TEST_UNSET_KEY", raising=False)
    cfg = _sdk_cfg()
    health = Health(blocked_families=lambda: set())

    chain = resolve_chain(_Step(), cfg, health=health, ledger_stats={}, rng=random.Random(0))
    assert [spec.name for spec in chain] == ["cli"]
    assert health.status(cfg.adapters["or"]) == {"healthy": False, "reason": "TEST_UNSET_KEY is not set",
                                                  "until": None}

    monkeypatch.setenv("TEST_UNSET_KEY", "sk-or-v1-0123456789abcdef")
    chain = resolve_chain(_Step(), cfg, health=health, ledger_stats={}, rng=random.Random(0))
    assert [spec.name for spec in chain] == ["or", "cli"]


def test_openrouter_is_enabled_by_default_but_skipped_without_its_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    defaults = config.load_defaults()
    assert defaults.adapters["openrouter_haiku"].enabled is True
    health = Health(blocked_families=lambda: set())

    names = [s.name for s in resolve_chain(_Step(), defaults, health=health, ledger_stats={}, rng=random.Random(0))]
    assert "openrouter_haiku" not in names

    rows = {row["name"]: row for row in _client().get("/api/pipeline/adapters").json()}
    assert rows["openrouter_haiku"]["key_set"] is False
    assert rows["openrouter_haiku"]["health"]["reason"] == "OPENROUTER_API_KEY is not set"


# 4. hot reload: the stored config is read per call


def test_a_config_put_changes_the_next_chain(monkeypatch):
    built = []

    class Echo:
        def __init__(self, spec):
            self.name = spec.name

        def call(self, prompt, **kw):
            built.append(self.name)
            return AdapterResult(outcome="ok", output={"ok": True})

    monkeypatch.setattr(llm, "_build", Echo)
    client = _client()
    body = client.get("/api/pipeline/config").json()
    body["adapters"] = {
        "first": {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"], "cost_tier": 1},
        "second": {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"], "cost_tier": 2},
    }
    body["steps"] = {}
    assert client.put("/api/pipeline/config", json=body, headers=HEADERS).status_code == 200
    assert llm.complete("reason", "p", Out, step="kit")[1]["adapter"] == "first"

    body["steps"] = {"kit": {"prefer": ["second"]}}
    assert client.put("/api/pipeline/config", json=body, headers=HEADERS).status_code == 200
    assert llm.complete("reason", "p", Out, step="kit")[1]["adapter"] == "second"

    body["adapters"]["second"]["enabled"] = False
    body["steps"] = {}
    assert client.put("/api/pipeline/config", json=body, headers=HEADERS).status_code == 200
    assert llm.complete("reason", "p", Out, step="kit")[1]["adapter"] == "first"
    assert built == ["first", "second", "first"]


def test_kit_step_moves_to_the_next_adapter_after_its_repair_fails(monkeypatch):
    bad = _valid_kit_payload()
    bad["analysis"]["evidence"][0]["source_ids"] = ["invented.source"]
    script = {"a": [bad, bad, bad], "b": [_valid_kit_payload()]}
    used = []

    def complete(capability, prompt, schema, *, exclude_adapters=(), **options):
        name = next(n for n in ("a", "b") if n not in exclude_adapters)
        used.append(name)
        return script[name].pop(0), {"adapter": name}

    monkeypatch.setattr(llm, "complete", complete)
    monkeypatch.setattr(llm, "chain_names", lambda capability, step="", exclude=(): [
        n for n in ("a", "b") if n not in exclude])
    fit = StepSpec("fit_score", "code", run=lambda ctx: StepResult(output={"score": 8}))
    result = _run(Pipeline("p", (fit, steps_service.kit_step(deps=("fit_score",)))), lambda step: [])

    assert result.status == "packet_ready", result.terminal_reason
    assert used == ["a", "a", "b"]
    assert result.steps["kit"].output["meta"] == {"authors": ["a", "b"]}
