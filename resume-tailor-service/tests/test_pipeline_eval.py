"""The eval set (spec 6.5): rerun agent steps on fixed dossiers against a chosen adapter
or prompt version and compare pass rate, review pass rate, time and cost, without ever
writing to a dossier. Adapters are fakes; nothing reaches a network or a model."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import job_store, people_store
from app.models import JobWorkspaceInput
from app.pipeline import adapters, config, evaluate, prompts, store
from app.pipeline.config import PipelineConfig
from app.pipeline.models import AdapterResult

SCRIPT = Path(__file__).parents[1] / "scripts" / "pipeline.py"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(people_store, "STORE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_JSON_BACKENDS", {})
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})
    monkeypatch.setattr(adapters, "LOG_DIR", tmp_path / "logs")
    config.save_config(PipelineConfig.model_validate({"adapters": {
        name: {"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["cheap", "reason", "web"]}
        for name in ("alpha", "beta")
    }}))


class Fake:
    def __init__(self, name, outputs, *, model="m", cost=0.01):
        self.name, self.outputs, self.model, self.cost = name, list(outputs), model, cost
        self.prompts = []

    def invoke(self, step, ctx, errors):
        self.prompts.append((step.name, ctx.job.id))
        output = self.outputs.pop(0)
        if isinstance(output, AdapterResult):
            return output
        return AdapterResult(outcome="ok", output=output, model=self.model, cost=self.cost,
                             prompt_version="v1")


def _jobs(n=2):
    return [job_store.add_job(JobWorkspaceInput(company=f"Acme {i}", role="Backend Engineer",
                                                jd_text="Build APIs in Python.")).id for i in range(n)]


def _no_writes(monkeypatch):
    monkeypatch.setattr(job_store, "patch_job", lambda *a, **k: pytest.fail("eval wrote to a dossier"))
    monkeypatch.setattr(job_store, "update_job", lambda *a, **k: pytest.fail("eval wrote to a dossier"))
    monkeypatch.setattr(people_store, "add_person", lambda *a, **k: pytest.fail("eval added a person"))


def test_eval_scores_each_adapter_without_writing(monkeypatch):
    ids = _jobs()
    before = [job_store.get_job(i).model_dump() for i in ids]
    _no_writes(monkeypatch)
    fakes = {
        "alpha": Fake("alpha", [{"score": 8, "reason": "Python matches."}, {"score": 99, "reason": "x"}],
                      model="a-1", cost=0.02),
        "beta": Fake("beta", [{"score": 7, "reason": "Good."}, {"score": 6, "reason": "Fine."}], model="b-1"),
    }

    rows = evaluate.run_eval(ids, ["fit_score"], ["alpha", "beta"], build=lambda spec: fakes[spec.name])
    summary = {(row["adapter"], row["model"]): row for row in evaluate.summarize(rows)}

    assert summary[("alpha", "a-1")]["tries"] == 2
    assert summary[("alpha", "a-1")]["pass_rate"] == 0.5  # score 99 fails the schema
    assert summary[("beta", "b-1")]["pass_rate"] == 1.0
    assert summary[("alpha", "a-1")]["cost"] == pytest.approx(0.04)
    assert summary[("alpha", "a-1")]["median_ms"] >= 0
    assert [job_store.get_job(i).model_dump() for i in ids] == before
    assert store.list_attempts() == []  # eval never feeds the live router stats


def test_review_pass_rate_and_rules(monkeypatch):
    ids = _jobs(2)
    _no_writes(monkeypatch)
    fake = Fake("alpha", [{"pass": True, "issues": []},
                          {"pass": False, "issues": [{"field": "cover_letter", "problem": "Too formal.",
                                                      "fix": "Shorter."}]}])

    rows = evaluate.run_eval(ids, ["review"], ["alpha"], build=lambda spec: fake)
    [row] = evaluate.summarize(rows)

    assert row["pass_rate"] == 1.0
    assert row["review_pass_rate"] == 0.5


def test_a_finish_rule_failure_counts_as_a_fail(monkeypatch):
    ids = _jobs(1)
    _no_writes(monkeypatch)
    fake = Fake("alpha", [{"company_context": "Acme builds tools.", "why_this_role": "APIs.",
                           "why_source_ids": ["no.such.source"], "sources": ["https://acme.example"]}])

    rows = evaluate.run_eval(ids, ["company_context"], ["alpha"], build=lambda spec: fake)

    assert rows[0]["ok"] is False
    assert "unknown resume bank source ids" in rows[0]["error"]


def test_people_is_checked_on_schema_only_and_adds_nobody(monkeypatch):
    ids = _jobs(1)
    _no_writes(monkeypatch)
    fake = Fake("alpha", [{"people": [{"name": "Dana Lee", "url": "https://acme.example/dana"}]}])

    rows = evaluate.run_eval(ids, ["people"], ["alpha"], build=lambda spec: fake)

    assert rows[0]["ok"] is True


def test_adapter_failures_and_missing_dossiers_are_reported(monkeypatch):
    ids = _jobs(1)
    fake = Fake("alpha", [AdapterResult(outcome="timeout", error="killed", model="m")])

    rows = evaluate.run_eval([*ids, "missing-id"], ["fit_score"], ["alpha"], build=lambda spec: fake)

    assert [(r["job_id"], r["outcome"]) for r in rows] == [(ids[0], "timeout"), ("missing-id", "missing")]
    [row] = [r for r in evaluate.summarize(rows) if r["adapter"] == "alpha"]
    assert row["pass_rate"] == 0.0


def test_only_agent_steps_and_known_adapters(monkeypatch):
    with pytest.raises(ValueError, match="agent step"):
        evaluate.run_eval(_jobs(1), ["kit"], ["alpha"])
    with pytest.raises(ValueError, match="adapter"):
        evaluate.run_eval(_jobs(1), ["fit_score"], ["ghost"])


def test_a_prompt_dir_swaps_the_templates_for_a_version_comparison(monkeypatch, tmp_path):
    ids = _jobs(1)
    alt = tmp_path / "prompts_v2"
    alt.mkdir()
    (alt / "fit_score.md").write_text("Rate {{company}} from 1 to 10. New wording.\n")
    seen = []

    class Rendering(Fake):
        def invoke(self, step, ctx, errors):
            text, version = prompts.render(step.name, ctx)
            seen.append((text, version))
            return AdapterResult(outcome="ok", output={"score": 7, "reason": "ok"}, prompt_version=version)

    rows = evaluate.run_eval(ids, ["fit_score"], ["alpha"], build=lambda spec: Rendering("alpha", []),
                             prompt_dir=alt)

    assert "New wording." in seen[0][0]
    assert rows[0]["prompt_version"] == prompts.version((alt / "fit_score.md").read_text())
    assert prompts.PROMPT_DIR != alt  # restored


def test_eval_set_file_and_report():
    data = evaluate.load_eval_set(Path(__file__).parents[1] / "content" / "eval_set.yaml")
    assert data["dossiers"] and data["steps"]
    rows = [{"adapter": "a", "model": "m", "step": "fit_score", "prompt_version": "v", "ok": True,
             "review_pass": None, "duration_ms": 1200, "cost": 0.01, "outcome": "ok", "error": "", "job_id": "j"}]
    text = evaluate.report(evaluate.summarize(rows))
    assert "pass" in text and "a" in text and "1.2s" in text


def test_the_script_runs_eval_and_status(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0
    for command in ("eval", "enqueue", "status"):
        assert command in result.stdout


def test_enqueue_and_status_helpers():
    [job_id] = _jobs(1)

    run = evaluate.enqueue(job_id)
    text = evaluate.status(run.id)

    assert run.pipeline == "packet" and run.status == "queued"
    assert run.id in text and "queued" in text and "fit_score" in text
    with pytest.raises(KeyError):
        evaluate.enqueue("no-such-job")


# Codex review fixes.


def test_an_adapter_without_the_step_capability_is_refused():
    cfg = config.load_config()
    cfg.adapters["beta"].capabilities = ["cheap"]
    config.save_config(cfg)
    with pytest.raises(ValueError, match="beta lacks capability reason"):
        evaluate.run_eval(_jobs(1), ["fit_score"], ["beta"], build=lambda spec: Fake("beta", []))


def test_a_disabled_adapter_can_be_evaluated_before_it_goes_live():
    cfg = config.load_config()
    cfg.adapters["beta"].enabled = False
    config.save_config(cfg)
    rows = evaluate.run_eval(_jobs(1), ["fit_score"], ["beta"],
                             build=lambda spec: Fake("beta", [{"score": 7, "reason": "ok"}]))
    assert rows[0]["ok"] is True


def test_sdk_adapters_run_without_their_mcp_servers_in_eval():
    cfg = PipelineConfig.model_validate({
        "adapters": {"or": {"type": "sdk", "model": "openrouter:x", "key_env": "K", "capabilities": ["reason"],
                            "mcp": ["jm"], "tools": ["dossier_read"]}},
        "mcp_servers": {"jm": {"url": "http://127.0.0.1:9000/mcp"}},
    })
    config.save_config(cfg)
    seen = []
    evaluate.run_eval(_jobs(1), ["fit_score"], ["or"],
                      build=lambda spec: seen.append(spec) or Fake("or", [{"score": 7, "reason": "ok"}]))
    assert seen[0].mcp == [] and seen[0].tools == ["dossier_read"]


def test_a_dossier_changed_during_a_try_fails_that_row():
    [job_id] = _jobs(1)

    class Writer(Fake):
        def invoke(self, step, ctx, errors):
            job_store.patch_job(job_id, {"notes": "agent wrote this"}, reason="t", session="t")
            return super().invoke(step, ctx, errors)

    rows = evaluate.run_eval([job_id], ["fit_score"], ["alpha"],
                             build=lambda spec: Writer("alpha", [{"score": 7, "reason": "ok"}]))

    assert rows[0]["ok"] is False
    assert "dossier changed during the eval" in rows[0]["error"]
