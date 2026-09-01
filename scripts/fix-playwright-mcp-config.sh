#!/usr/bin/env bash
# SUPERSEDED. The committed .mcp.json and .cursor/mcp.json already pin every agent to
# --cdp-endpoint http://127.0.0.1:9223, so no global config edit is needed. Running this
# writes a competing definition into ~/.claude.json that overrides the committed one.
# Kept only as a repair tool if the committed files are lost. Port corrected to 9223:
# 9222 with the default Chrome profile cannot serve CDP on Chrome 136+ (see AGENTS.md).
#
# One-time fix: Playwright MCP attach mode for job-machine in ~/.claude.json.
#
# Problems fixed:
#   - Stale project path /Users/harshsaw/Downloads/job-machine
#   - Relative --user-data-dir=./browser-profile (wrong cwd → wrong profile)
#   - No --cdp-endpoint (MCP launched its own Chromium)
#
# After running: restart Claude Code in this repo, run /mcp, start regular Chrome:
#   JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh
#
# Usage:
#   ./scripts/fix-playwright-mcp-config.sh
set -euo pipefail

CLAUDE_JSON="${HOME}/.claude.json"
REPO="/Users/harshsaw/job-machine"

if [[ ! -f "$CLAUDE_JSON" ]]; then
  echo "Not found: $CLAUDE_JSON" >&2
  exit 1
fi

export CLAUDE_JSON
python3 <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["CLAUDE_JSON"])
data = json.loads(path.read_text())

playwright_attach = {
    "type": "stdio",
    "command": "npx",
    "args": [
        "-y",
        "@playwright/mcp@latest",
        "--cdp-endpoint=http://127.0.0.1:9223",
    ],
    "env": {},
}

proj = data.setdefault("projects", {})
for key in ("/Users/harshsaw/job-machine", "/Users/harshsaw/Downloads/job-machine"):
    if key in proj:
        proj[key]["mcpServers"] = {"playwright": playwright_attach}

mapping = data.get("githubRepoPaths", {}).get("harshksaw/job-machine", [])
if "/Users/harshsaw/Downloads/job-machine" in mapping:
    data["githubRepoPaths"]["harshksaw/job-machine"] = [
        p for p in mapping if p != "/Users/harshsaw/Downloads/job-machine"
    ]

path.write_text(json.dumps(data, indent=2) + "\n")
print(f"Patched {path}")
print("Playwright MCP args:", playwright_attach["args"])
PY

echo ""
echo "Next:"
echo "  1. Cmd+Q Chrome (if CDP down), then JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh"
echo "  2. export BU_CDP_URL=http://127.0.0.1:9223"
echo "  3. Restart Claude Code in ${REPO}, verify /mcp → playwright connected"
