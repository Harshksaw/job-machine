"""The eval set (spec 6.5): rerun chosen agent steps on a fixed list of dossiers against
chosen adapters or a prompt version, and compare pass rate, review pass rate, time and
cost side by side before a prompt or model change gets live traffic.

This path only reads. It never patches a dossier, never adds a person and never writes
to the attempt ledger (eval tries would skew the live router's pass rates). An sdk
adapter runs without its MCP servers (only the read only built in tools), and a try
during which the dossier changed fails with that reason. A CLI agent has its own shell,
so it is trusted the same way it is in a live run. A step's
finish function is run to apply its rules, except `people`, whose finish saves people,
so people is judged on its schema alone. Raw agent output still lands under
logs/pipeline/eval-<stamp>/ like any adapter call.

`enqueue` and `status` are small helpers over the run store; no worker starts here.
"""
from __future__ import annotations

import statistics
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError

from app import job_store
from app.pipeline import config, prompts, store
from app.pipeline.adapters import build_adapter
from app.pipeline.models import AdapterResult, Run, StepState
from app.pipeline.pipelines import PACKET_PIPELINE
from app.pipeline.runner import StepContext

EVAL_SET_PATH = Path(__file__).resolve().parents[2] / "content" / "eval_set.yaml"
# Finish functions with side effects outside the step's returned writes.
_SCHEMA_ONLY = frozenset({"people"})


def agent_steps() -> dict:
    return {step.name: step for step in PACKET_PIPELINE.steps if step.kind == "agent"}


def load_eval_set(path: Path = EVAL_SET_PATH) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {"dossiers": [str(i) for i in data.get("dossiers") or []],
            "steps": [str(s) for s in data.get("steps") or []],
            "adapters": [str(a) for a in data.get("adapters") or []]}


@contextmanager
def _prompt_dir(path: Path | None):
    if path is None:
        yield
        return
    saved = prompts.PROMPT_DIR
    prompts.PROMPT_DIR = Path(path)
    try:
        yield
    finally:
        prompts.PROMPT_DIR = saved


def _context(job, step_name: str, run_id: str) -> StepContext:
    run = Run(id=run_id, job_id=job.id, pipeline="eval", order=[step_name], steps={step_name: StepState()},
              created_at="", updated_at="")
    return StepContext(run=run, job=job, outputs={})


def _judge(step, result, ctx) -> tuple[bool, bool | None, str]:
    """(passed schema and rules, review pass or None, error)."""
    if result.outcome != "ok":
        return False, None, f"{result.outcome}: {result.error}".strip()
    try:
        parsed = step.schema.model_validate(result.output or {})
    except ValidationError as exc:
        return False, None, "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())[:300]
    if step.name in _SCHEMA_ONLY:
        return True, None, ""
    try:
        finished = step.finish(parsed, ctx)
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"[:300]
    stray = sorted(set(finished.writes) - set(step.owns))
    if stray:
        return False, None, f"wrote fields it does not own: {', '.join(stray)}"
    review = finished.output.get("pass") if step.name == "review" else None
    return True, review, ""


def run_eval(dossier_ids: list[str], steps: list[str], adapter_names: list[str], *,
             prompt_dir: Path | None = None, build: Callable = build_adapter) -> list[dict]:
    """One row per (dossier, step, adapter) try."""
    registry = agent_steps()
    unknown = [name for name in steps if name not in registry]
    if unknown:
        raise ValueError(f"not an agent step: {', '.join(unknown)}; choose from {', '.join(registry)}")
    cfg = config.load_config()
    missing = [name for name in adapter_names if name not in cfg.adapters]
    if missing:
        raise ValueError(f"unknown adapter: {', '.join(missing)}")
    # A disabled adapter may be evaluated (that is how a new model earns its place), but
    # never on a step the live router would not give it.
    lacking = [f"{name} lacks capability {registry[step].capability} for {step}"
               for step in steps for name in adapter_names
               if registry[step].capability not in cfg.adapters[name].capabilities]
    if lacking:
        raise ValueError("; ".join(lacking))
    specs = {name: cfg.adapters[name].model_copy(update={"mcp": []}) for name in adapter_names}
    run_id = "eval-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    rows: list[dict] = []
    with _prompt_dir(prompt_dir):
        for job_id in dossier_ids:
            job = job_store.get_job(job_id)
            for step_name in steps:
                step = registry[step_name]
                for name in adapter_names:
                    row = {"job_id": job_id, "step": step_name, "adapter": name, "model": cfg.adapters[name].model,
                           "prompt_version": "", "ok": False, "review_pass": None, "duration_ms": 0,
                           "cost": None, "outcome": "missing", "error": "no such dossier"}
                    if job is None:
                        rows.append(row)
                        continue
                    ctx = _context(job, step_name, run_id)
                    t0 = time.monotonic()
                    try:
                        result = build(specs[name]).invoke(step, ctx, [])
                    except Exception as exc:
                        result = AdapterResult(outcome="error", error=f"{type(exc).__name__}: {exc}"[:300])
                    ok, review, error = _judge(step, result, ctx)
                    after = job_store.get_job(job_id)
                    if after is None or after.updated_at != job.updated_at:
                        ok, error = False, "dossier changed during the eval; check what the agent wrote"
                        job = after or job
                    row.update(model=result.model or row["model"], prompt_version=result.prompt_version, ok=ok,
                               review_pass=review, duration_ms=int((time.monotonic() - t0) * 1000),
                               cost=result.cost, outcome=result.outcome, error=error)
                    rows.append(row)
    return rows


def summarize(rows: list[dict]) -> list[dict]:
    """Per adapter, model, step and prompt version: tries, pass rate, review pass rate
    (review only), median duration and total cost. Missing dossiers are left out."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if row["outcome"] != "missing":
            groups[(row["adapter"], row["model"], row["step"], row["prompt_version"])].append(row)
    out = []
    for (adapter, model, step, version), tries in sorted(groups.items()):
        reviews = [r["review_pass"] for r in tries if r["review_pass"] is not None]
        costs = [r["cost"] for r in tries if r["cost"] is not None]
        out.append({
            "adapter": adapter, "model": model, "step": step, "prompt_version": version, "tries": len(tries),
            "pass_rate": sum(r["ok"] for r in tries) / len(tries),
            "review_pass_rate": sum(reviews) / len(reviews) if reviews else None,
            "median_ms": statistics.median(r["duration_ms"] for r in tries),
            "cost": sum(costs) if costs else None,
        })
    return out


def report(summary: list[dict]) -> str:
    header = f"{'adapter':<18} {'model':<34} {'step':<16} {'prompt':<12} {'tries':>5} {'pass':>6} {'review':>7} {'median':>8} {'cost':>9}"
    lines = [header, "-" * len(header)]
    for row in summary:
        review = "-" if row["review_pass_rate"] is None else f"{row['review_pass_rate']:.0%}"
        cost = "-" if row["cost"] is None else f"${row['cost']:.4f}"
        lines.append(f"{row['adapter']:<18} {row['model'][:34]:<34} {row['step']:<16} {row['prompt_version'] or '-':<12} "
                     f"{row['tries']:>5} {row['pass_rate']:>6.0%} {review:>7} {row['median_ms'] / 1000:>7.1f}s {cost:>9}")
    return "\n".join(lines)


def enqueue(job_id: str) -> Run:
    """Queue a packet run for a dossier (a worker picks it up from M6)."""
    if job_store.get_job(job_id) is None:
        raise KeyError(f"no dossier {job_id}")
    return store.create_run(job_id, PACKET_PIPELINE.name, PACKET_PIPELINE.order)


def status(run_id: str) -> str:
    run = store.get_run(run_id)
    if run is None:
        raise KeyError(f"no run {run_id}")
    lines = [f"run {run.id}  dossier {run.job_id}  {run.status}"
             + (f"  ({run.terminal_reason})" if run.terminal_reason else "")]
    for name in run.order:
        state = run.steps[name]
        lines.append(f"  {name:<18} {state.status}" + (f"  {state.error}" if state.error else ""))
    return "\n".join(lines)
