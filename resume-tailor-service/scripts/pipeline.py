"""Agent orchestrator command line (spec 6.5).

    uv run python scripts/pipeline.py eval [--set content/eval_set.yaml]
        [--step fit_score ...] [--adapter openrouter_haiku ...] [--prompt-dir DIR] [--json]
    uv run python scripts/pipeline.py enqueue <dossier id>
    uv run python scripts/pipeline.py status <run id>

`eval` reruns agent steps on the eval set's dossiers against each chosen adapter (or a
prompt directory holding new templates) and prints pass rate, review pass rate, median
time and cost per adapter, model, step and prompt version. It only reads: no dossier,
person or ledger is written. Adapters run for real, so a model call costs what it costs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    ev = commands.add_parser("eval", help="rerun agent steps on the eval set and compare adapters")
    ev.add_argument("--set", type=Path, default=None, help="eval set yaml (default content/eval_set.yaml)")
    ev.add_argument("--step", action="append", default=[], help="agent step (repeatable; default from the set)")
    ev.add_argument("--adapter", action="append", default=[], help="adapter name (repeatable; default from the set)")
    ev.add_argument("--prompt-dir", type=Path, default=None, help="directory of alternative <step>.md templates")
    ev.add_argument("--json", action="store_true", help="print every row as JSON instead of the table")
    en = commands.add_parser("enqueue", help="queue a packet run for a dossier")
    en.add_argument("job_id")
    st = commands.add_parser("status", help="show a run and its steps")
    st.add_argument("run_id")
    args = parser.parse_args(argv)

    from app.pipeline import evaluate

    if args.command == "enqueue":
        print(evaluate.enqueue(args.job_id).id)
        return 0
    if args.command == "status":
        print(evaluate.status(args.run_id))
        return 0
    data = evaluate.load_eval_set(args.set or evaluate.EVAL_SET_PATH)
    steps = args.step or data["steps"]
    adapters = args.adapter or data["adapters"]
    if not adapters:
        parser.error("name at least one adapter (--adapter, or adapters: in the eval set)")
    rows = evaluate.run_eval(data["dossiers"], steps, adapters, prompt_dir=args.prompt_dir)
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(evaluate.report(evaluate.summarize(rows)))
        missing = sorted({row["job_id"] for row in rows if row["outcome"] == "missing"})
        if missing:
            print(f"\nNo dossier for: {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
