"""AI usage meter and router: which tool should take the next task?

    python3 tools/ai-meter/meter.py poll            # refresh logs/ai-usage.json (launchd, every 5 min)
    python3 tools/ai-meter/meter.py status          # spend per tool vs budget
    python3 tools/ai-meter/meter.py route <kind>    # direction | heavy | bulk

Spend comes from CodeBurn (`codeburn status --format menubar-json`), which already reads
the local logs of Claude Code, Codex, Cursor Agent and OpenCode. Budgets, the routing
order per kind of work and the command for each tool live in policy.json, so every agent
(Claude, Cursor, Codex, OpenCode) routes from the same file and the same state.

A tool without a budget (Cursor on its plan, OpenCode free models) is never throttled.
A budgeted tool is skipped once today's or this week's spend reaches `throttle_at` of its
budget. If every tool on a route is over budget, the last one is used anyway and the
reason says so: the router never blocks work, it only steers it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY_PATH = HERE / "policy.json"
STATE_PATH = HERE.parent.parent / "logs" / "ai-usage.json"
STALE_AFTER = 300  # seconds; matches the launchd poll interval
OPENCODE_LOG = Path.home() / ".local" / "share" / "opencode" / "log" / "opencode.log"


def _opencode_health() -> str | None:
    """"Model is unavailable" in OpenCode's log within 15 minutes means its free models are down."""
    if not OPENCODE_LOG.exists():
        return None
    with open(OPENCODE_LOG, "rb") as fh:
        fh.seek(max(0, OPENCODE_LOG.stat().st_size - 200_000))
        tail = fh.read().decode("utf-8", "ignore")
    now = datetime.now(timezone.utc)
    for stamp in re.findall(r"timestamp=(\S+Z) .*Model is unavailable", tail):
        try:
            if (now - datetime.fromisoformat(stamp.replace("Z", "+00:00"))).total_seconds() < 900:
                return "Model is unavailable"
        except ValueError:
            continue
    return None

# CodeBurn ids mapped to router names: "cursor" in policy.json is the CLI, so
# CodeBurn's "cursor" (the editor) is renamed out of its way.
_ALIASES = {"cursor-agent": "cursor", "cursor agent": "cursor", "cursor": "cursor-ide"}


def summarize(today: dict, week: dict) -> dict:
    providers: dict[str, dict] = {}
    for period, report in (("day", today), ("week", week)):
        for detail in report.get("current", {}).get("providerDetails", []):
            name = _ALIASES.get(detail["id"], detail["id"])
            entry = providers.setdefault(name, {"day": 0.0, "week": 0.0, "calls_day": 0})
            entry[period] = round(entry[period] + float(detail.get("cost") or 0), 4)
            if period == "day":
                entry["calls_day"] += int(detail.get("calls") or 0)
    return providers


def _over(name: str, state: dict, policy: dict) -> str | None:
    down = state.get("health", {}).get(name)
    if down:
        return f"{name} is down ({down})"
    budget = policy.get("budgets", {}).get(name)
    if not budget:
        return None
    spent = state.get("providers", {}).get(name, {})
    limit = policy.get("throttle_at", 0.8)
    for period in ("day", "week"):
        cap = budget.get(period)
        if cap and spent.get(period, 0) >= cap * limit:
            return (f"{name} spent {spent.get(period, 0):.2f} of its {cap} "
                    f"{policy.get('currency', '')} {period} budget")
    return None


def pick(kind: str, state: dict, policy: dict) -> dict:
    routes = policy["routes"]
    if kind not in routes:
        raise ValueError(f"unknown kind {kind!r}; use one of: {', '.join(routes)}")
    skipped = []
    for name in routes[kind]:
        reason = _over(name, state, policy)
        if reason is None:
            why = f"{name} is first on the {kind} route with budget left"
            if skipped:
                why = "; ".join(skipped) + f", so {name}"
            return {"tool": name, "reason": why}
        skipped.append(reason)
    last = routes[kind][-1]
    return {"tool": last, "reason": "every tool on the route is over budget ("
            + "; ".join(skipped) + f"), using {last} anyway"}


def _codeburn(period: str) -> dict:
    out = subprocess.run(
        ["codeburn", "status", "--format", "menubar-json", "--period", period],
        capture_output=True, text=True, timeout=240, check=True,
    )
    return json.loads(out.stdout)


def poll() -> dict:
    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "providers": summarize(_codeburn("today"), _codeburn("week")),
        "health": {name: down for name, down in (("opencode", _opencode_health()),) if down},
    }
    policy = load_policy()
    state["routes"] = {kind: pick(kind, state, policy) for kind in policy["routes"]}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(STATE_PATH)
    return state


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


def load_state() -> dict:
    if not STATE_PATH.exists() or time.time() - STATE_PATH.stat().st_mtime > STALE_AFTER * 2:
        return poll()
    return json.loads(STATE_PATH.read_text())


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    if command == "poll":
        state = poll()
        print(json.dumps(state["routes"]))
        return 0
    policy, state = load_policy(), load_state()
    if command == "status":
        print(f"as of {state['generated_at']} ({policy['currency']})")
        for name, spent in sorted(state["providers"].items(), key=lambda kv: -kv[1]["week"]):
            if not spent["week"] and name not in policy["tools"]:
                continue
            budget = policy["budgets"].get(name, {})
            cap = f" / {budget.get('day')} day, {budget.get('week')} week" if budget else " (no budget)"
            print(f"  {name:10} today {spent['day']:8.2f}   week {spent['week']:8.2f}{cap}")
        for kind, choice in state["routes"].items():
            print(f"  {kind:10} -> {choice['tool']}: {choice['reason']}")
        return 0
    if command == "route" and len(argv) > 2:
        choice = pick(argv[2], state, policy)
        tool = policy["tools"][choice["tool"]]
        print(json.dumps({**choice, "command": tool["command"], "note": tool.get("note", "")}, indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
