#!/usr/bin/env bash
# Probe CDP on port 9222. Print export line when up; startup instructions when down.
#
# Usage (from repo root):
#   ./scripts/ensure-regular-chrome-cdp.sh
#
# Overrides:
#   JOB_MACHINE_CDP_PORT  default: 9222
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDP_PORT="${JOB_MACHINE_CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"

if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
  echo "CDP ready on ${CDP_URL}"
  curl -fsS "${CDP_URL}/json/version" 2>/dev/null | sed -n '1p' || true
  echo "export BU_CDP_URL=${CDP_URL}"
  exit 0
fi

echo "CDP not responding on ${CDP_URL}." >&2
echo "" >&2
echo "Default (regular Chrome, LinkedIn already signed in):" >&2
echo "  1. Cmd+Q to quit Chrome completely" >&2
echo "  2. ${REPO_ROOT}/scripts/start-chrome-debug.sh" >&2
echo "  3. export BU_CDP_URL=${CDP_URL}" >&2
echo "" >&2
echo "Isolated job profile (only when Harsh explicitly asks):" >&2
echo "  ${REPO_ROOT}/scripts/start-job-chrome.sh" >&2
echo "  export BU_CDP_URL=${CDP_URL}" >&2
exit 1
