#!/usr/bin/env bash
# Probe CDP on port 9222. Print export line when up; startup instructions when down.
#
# Regular Chrome (default profile) cannot serve working CDP on Chrome 136+: it binds
# the port then 404s every /json/* endpoint. Confirmed again on Chrome 152, 2026-09-02.
# So the fallback here is job Chrome (isolated profile), not start-chrome-debug.sh.
# See docs/AGENT-PLAYBOOK.md "Before any browser session" for the full story and the
# port-9222-collision gotcha (a stale broken regular-Chrome CDP listener can squat on
# the IPv4 side of the port for days; job Chrome then only binds IPv6 and this probe,
# which checks 127.0.0.1, reports failure even though job Chrome is fine).
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
echo "Start job Chrome (isolated profile, this is the default lane):" >&2
echo "  ${REPO_ROOT}/scripts/start-job-chrome.sh" >&2
echo "  export BU_CDP_URL=${CDP_URL}" >&2
echo "" >&2
echo "If that also reports CDP not responding, check for a stale process already on" >&2
echo "this port before assuming it failed:" >&2
echo "  lsof -nP -iTCP:${CDP_PORT} -sTCP:LISTEN" >&2
echo "  curl -fsS http://[::1]:${CDP_PORT}/json/version   # job Chrome may have only" >&2
echo "                                                      # won the IPv6 side" >&2
echo "If a stale listener is squatting on the port, do not kill it blindly, confirm" >&2
echo "it isn't Harsh's actual daily Chrome, then retry job Chrome on another port:" >&2
echo "  JOB_MACHINE_CDP_PORT=9223 ${REPO_ROOT}/scripts/start-job-chrome.sh" >&2
exit 1
