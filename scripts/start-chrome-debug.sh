#!/usr/bin/env bash
# DEPRECATED on Chrome 136+. Chrome refuses remote debugging on the DEFAULT user data
# directory: it binds the port, then serves 404 on every /json/* endpoint. Verified
# 2026-08-31 on Chrome 152. Use ./scripts/start-job-chrome.sh instead. Kept for older
# Chrome only.
#
# Launch Google Chrome with your **default macOS profile** and remote debugging
# on port 9222. No --user-data-dir — uses the same cookies/sessions as daily Chrome
# (LinkedIn, Wellfound, etc. already signed in).
#
# IMPORTANT: Fully quit Chrome first (Cmd+Q). If Chrome is already running without
# --remote-debugging-port, the profile is locked and this script will refuse to start.
#
# Usage (from repo root):
#   ./scripts/start-chrome-debug.sh
#
# Overrides:
#   JOB_MACHINE_CDP_PORT  default: 9222
set -euo pipefail

CDP_PORT="${JOB_MACHINE_CDP_PORT:-9222}"
CDP_URL="http://127.0.0.1:${CDP_PORT}"
CHROME_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS launcher — on other OS, quit Chrome fully, then start with:" >&2
  echo "  google-chrome --remote-debugging-port=${CDP_PORT}" >&2
  exit 1
fi

if [[ ! -x "$CHROME_APP" ]]; then
  echo "Google Chrome not found at ${CHROME_APP}" >&2
  exit 1
fi

if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
  echo "Chrome already running with CDP on port ${CDP_PORT} (default profile)."
  echo "  BU_CDP_URL=${CDP_URL}"
  curl -fsS "${CDP_URL}/json/version" 2>/dev/null | sed -n '1p' || true
  exit 0
fi

# Chrome running without remote debugging locks the default profile.
if pgrep -xq "Google Chrome" 2>/dev/null || pgrep -f "${CHROME_APP}" >/dev/null 2>&1; then
  echo "Chrome is running but CDP is not available on ${CDP_URL}." >&2
  echo "" >&2
  echo "Quit Chrome completely (Cmd+Q), then re-run:" >&2
  echo "  ./scripts/start-chrome-debug.sh" >&2
  echo "" >&2
  echo "macOS cannot attach --remote-debugging-port to an already-running instance." >&2
  echo "Your tabs and logins are preserved — Chrome will reopen them after relaunch." >&2
  exit 1
fi

"$CHROME_APP" \
  --remote-debugging-port="${CDP_PORT}" \
  --no-first-run \
  --no-default-browser-check \
  >/dev/null 2>&1 &

for _ in $(seq 1 30); do
  if curl -fsS "${CDP_URL}/json/version" >/dev/null 2>&1; then
    echo "Chrome started (default profile) with remote debugging."
    echo "  CDP:   ${CDP_URL}"
    echo "  Agent: export BU_CDP_URL=${CDP_URL}"
    echo ""
    echo "Automation shares your regular Chrome profile — use background tabs."
    echo "Quit Chrome (Cmd+Q) when done if you need a clean relaunch later."
    exit 0
  fi
  sleep 0.5
done

echo "Chrome opened but CDP is not responding on ${CDP_URL} yet." >&2
echo "If macOS asks to allow remote debugging, click Allow (or: browser-use mac-approve)." >&2
echo "Then re-run: ./scripts/start-chrome-debug.sh" >&2
exit 1
