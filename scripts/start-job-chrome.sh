#!/usr/bin/env bash
# Launch an isolated Google Chrome for job-machine automation (LinkedIn, Wellfound,
# apply/outreach). Uses repo-local browser-profile/ (gitignored) and exposes CDP
# so Cursor browser-use / Playwright can attach without touching your daily Chrome.
#
# Usage (from repo root):
#   ./scripts/start-job-chrome.sh
#
# Overrides:
#   JOB_MACHINE_CHROME_PROFILE  default: <repo>/browser-profile
#   JOB_MACHINE_CDP_PORT        default: 9222
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE_DIR="${JOB_MACHINE_CHROME_PROFILE:-$REPO_ROOT/browser-profile}"
CDP_PORT="${JOB_MACHINE_CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS launcher — on other OS, start Chrome manually with:" >&2
  echo "  google-chrome --user-data-dir=${PROFILE_DIR} --remote-debugging-port=${CDP_PORT}" >&2
  exit 1
fi

if [[ ! -x "$CHROME_APP" ]]; then
  echo "Google Chrome not found at ${CHROME_APP}" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"

if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
  echo "Job Chrome already running (CDP on port ${CDP_PORT})."
  echo "  Profile: ${PROFILE_DIR}"
  echo "  BU_CDP_URL=${CDP_URL}"
  curl -fsS "${CDP_URL}/json/version" 2>/dev/null | sed -n '1p' || true
  exit 0
fi

# -na = new application instance — separate from your regular Chrome window/profile.
open -na "Google Chrome" --args \
  "--user-data-dir=${PROFILE_DIR}" \
  "--remote-debugging-port=${CDP_PORT}" \
  "--no-first-run" \
  "--no-default-browser-check"

for _ in $(seq 1 30); do
  if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
    echo "Job Chrome started."
    echo "  Profile: ${PROFILE_DIR}"
    echo "  CDP:     ${CDP_URL}"
    echo "  Agent:   export BU_CDP_URL=${CDP_URL}"
    echo ""
    echo "Sign in once in THIS window: linkedin.com and wellfound.com."
    echo "Quit this Chrome when done — your daily Chrome profile is untouched."
    exit 0
  fi
  sleep 0.5
done

echo "Chrome opened but CDP is not responding on ${CDP_URL} yet." >&2
echo "If macOS asks to allow remote debugging, click Allow (or: browser-use mac-approve)." >&2
echo "Then re-run: ./scripts/start-job-chrome.sh" >&2
exit 1
