"""Can each agent tool still run? Read from the newest run log, since a tool that is out of
credits, over its limit or signed out fails in its first second and says why.

The usage meter knows what a tool spent, not whether it can start. The status is only as
fresh as the last run, so it clears on the next clean run.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

TOOLS = ("cursor", "codex", "opencode", "antigravity")
# An agent log echoes its prompt and the repo docs near the top, so only the end counts.
_TAIL = 1500
# First match wins.
_BLOCKS = [
    ("prepaid balance is used up", "Out of credits"),
    ("Insufficient balance", "Out of credits"),
    ("hit your usage limit", "Usage limit hit"),
    ("Not logged in", "Signed out"),
    ("Authentication required", "Signed out"),
    ("Invalid credential", "Bad key"),
    ("Connection stalled repeatedly", "Connection stalled"),
]
_HINTS = {
    "Out of credits": "Add credits, then run again",
    "Usage limit hit": "Wait for the limit to reset",
    "Signed out": "Log in again",
    "Bad key": "Log in again to replace the key",
    "Connection stalled": "The service stopped responding, retry",
}
_RESET = re.compile(r"try again at ([^.\n]{1,30})")


def _tool_of(name: str) -> str | None:
    # Dashboard runs are <stamp>-<tool>-<task>.log, hand started ones <tool>-<task>-<stamp>.log.
    for part in name.removesuffix(".log").split("-")[:2]:
        if part in TOOLS:
            return part
    return None


def _row(tool: str, newest: tuple[float, Path] | None) -> dict:
    if newest is None:
        return {"tool": tool, "status": "idle", "label": "No runs yet", "detail": "", "at": None}
    mtime, path = newest
    at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    tail = path.read_text(errors="ignore")[-_TAIL:]
    for needle, label in _BLOCKS:
        if needle in tail:
            detail = _HINTS[label]
            reset = _RESET.search(tail) if label == "Usage limit hit" else None
            if reset:
                detail = f"Resets {reset.group(1).strip()}"
            return {"tool": tool, "status": "blocked", "label": label, "detail": detail, "at": at}
    return {"tool": tool, "status": "ok", "label": "Last run fine", "detail": path.name, "at": at}


def agent_health(log_dir: Path) -> list[dict]:
    newest: dict[str, tuple[float, Path]] = {}
    if log_dir.is_dir():
        for path in log_dir.glob("*.log"):
            tool = _tool_of(path.name)
            if tool is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size == 0:
                continue  # still starting, the run before it is the better signal
            if tool not in newest or stat.st_mtime > newest[tool][0]:
                newest[tool] = (stat.st_mtime, path)
    return [_row(tool, newest.get(tool)) for tool in TOOLS]
