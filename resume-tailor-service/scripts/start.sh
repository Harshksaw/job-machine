#!/usr/bin/env bash
# One command to run everything locally: mock sheet (if APPS_SCRIPT_URL is local)
# + the FastAPI service bound to loopback. Ctrl-C tears both down.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env so we can see APPS_SCRIPT_URL / secret.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

uv sync

MOCK_PID=""
cleanup() { [ -n "$MOCK_PID" ] && kill "$MOCK_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

# Start the mock only when the configured sheet URL is local.
if printf '%s' "${APPS_SCRIPT_URL:-}" | grep -qE '127\.0\.0\.1|localhost'; then
  PORT="$(printf '%s' "$APPS_SCRIPT_URL" | sed -E 's#.*:([0-9]+).*#\1#')"
  echo "Starting mock sheet on port ${PORT}…"
  APPS_SCRIPT_READ_SECRET="${APPS_SCRIPT_READ_SECRET:-}" \
    python3 scripts/mock_sheet.py "$PORT" &
  MOCK_PID=$!
fi

echo "Starting API on http://127.0.0.1:8420 …"
uv run uvicorn app.main:app --host 127.0.0.1 --port 8420
