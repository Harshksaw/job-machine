#!/usr/bin/env bash
# Render and install the nightly liveness LaunchAgent. Use --check to compare
# the installed file without writing or loading anything.
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_DIR/.." && pwd)"
LABEL="com.jobmachine.liveness"
TEMPLATE="$SERVICE_DIR/scripts/${LABEL}.plist.template"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PYTHON="$(command -v python3)"
REPORT="$REPO_ROOT/logs/liveness-report.json"
LOG="$REPO_ROOT/logs/liveness.log"

case "${1:-}" in
  --check) MODE="check" ;;
  "") MODE="install" ;;
  *) echo "Unknown option: $1  (use --check)" >&2; exit 2 ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
  echo "launchd is macOS-only; nothing to do on $(uname -s)." >&2
  exit 0
fi

render() {
  SERVICE_DIR="$SERVICE_DIR" REPO_ROOT="$REPO_ROOT" PYTHON="$PYTHON" \
    REPORT="$REPORT" LOG="$LOG" TEMPLATE="$TEMPLATE" python3 - <<'PY'
import os
from pathlib import Path

text = Path(os.environ["TEMPLATE"]).read_text(encoding="utf-8")
values = {
    "@PYTHON@": os.environ["PYTHON"],
    "@SCRIPT@": f'{os.environ["SERVICE_DIR"]}/scripts/check_liveness.py',
    "@REPORT@": os.environ["REPORT"],
    "@LOG@": os.environ["LOG"],
    "@SERVICE_DIR@": os.environ["SERVICE_DIR"],
}
for placeholder, value in values.items():
    text = text.replace(placeholder, value)
print(text, end="")
PY
}

if [ "$MODE" = "check" ]; then
  if [ ! -f "$PLIST" ]; then
    echo "NOT INSTALLED: $PLIST"
    exit 1
  fi
  if render | diff -u "$PLIST" - >/dev/null; then
    echo "in sync: $PLIST matches $TEMPLATE"
    exit 0
  fi
  echo "DRIFT: installed plist differs from $TEMPLATE"
  render | diff -u "$PLIST" - || true
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO_ROOT/logs"
render > "$PLIST"
echo "wrote $PLIST"
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "loaded ${LABEL}, scheduled daily at 02:15 local time"
