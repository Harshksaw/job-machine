#!/usr/bin/env bash
# Non-interactive, supervised entrypoint used by launchd (com.jobmachine.dashboard).
# Unlike start.sh, this never runs the mock sheet and never blocks on a TTY:
# launchd owns the lifecycle (auto-restart via KeepAlive) and captures stdout/stderr
# to the centralized log file. For manual/interactive runs, keep using start.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

# launchd hands us a minimal PATH; make uv + homebrew + TeX (pdflatex) visible.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/Library/TeX/texbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

# Load .env (APPS_SCRIPT_URL / secrets) if present.
if [ -f .env ]; then set -a; . ./.env; set +a; fi

# Timestamp each boot so restarts are visible in the log.
echo "[serve] $(date '+%Y-%m-%dT%H:%M:%S%z') starting uvicorn on 127.0.0.1:8420 (pid $$)"

# exec so launchd supervises the real process and KeepAlive restarts work cleanly.
exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8420
