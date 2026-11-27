"""Run a task pipeline (spec 13.3) now, or drain the queued task runs.

    cd resume-tailor-service
    uv run python scripts/run_task.py mail_sync          # or liveness_sweep, remote_boards, ats_watchlist
    uv run python scripts/run_task.py --queued           # run task runs queued through the API or MCP

Runs in this process against the same store as the service (it reads `.env` the same
way), so it can be scheduled with launchd until the M6 worker runs these on its own.
Prints the run status and the last step's output as JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _summary(run) -> dict:
    last = run.order[-1]
    return {"run_id": run.id, "pipeline": run.pipeline, "status": run.status,
            "terminal_reason": run.terminal_reason, "output": run.steps[last].output}


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from app.pipeline import runner, store, tasks

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", nargs="?", choices=sorted(tasks.TASK_BUILDERS))
    parser.add_argument("--queued", action="store_true", help="run every queued task run")
    args = parser.parse_args(argv)
    if bool(args.name) == args.queued:
        parser.error("give a task name or --queued")

    owner = f"run_task-{os.getpid()}"
    if args.name:
        if tasks.active_run(args.name) is not None:
            print(f"{args.name} already has a queued or running run", file=sys.stderr)
            return 1
        run = tasks.run_task(args.name, owner=owner)
        print(json.dumps(_summary(run), indent=1, default=str))
        return 0 if run.status == "completed" else 1

    code = 0
    for queued in reversed(store.list_runs()):  # oldest first
        if queued.status != "queued" or queued.pipeline not in tasks.TASK_BUILDERS:
            continue
        try:
            run = tasks.run_task(queued.pipeline, owner=owner, run_id=queued.id)
        except runner.LeaseHeld:
            continue
        print(json.dumps(_summary(run), indent=1, default=str))
        code = code or (0 if run.status == "completed" else 1)
    return code


if __name__ == "__main__":
    sys.exit(main())
