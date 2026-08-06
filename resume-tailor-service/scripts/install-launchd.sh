#!/usr/bin/env bash
# ============================================================================
# Install (or verify) the launchd agent that keeps the dashboard running.
#
#   ./scripts/install-launchd.sh          # render + load the agent
#   ./scripts/install-launchd.sh --check  # render + diff only, touches nothing
#
# Why this exists: the agent used to live ONLY in ~/Library/LaunchAgents, so the
# actual deployment was unreproducible from a fresh clone. This is the source of
# truth for it now. Paths are derived from the repo location, never hardcoded,
# so it works from any checkout directory.
#
# macOS only — launchd is the supervisor. Docker mode (setup.sh --docker) uses
# compose's `restart: unless-stopped` instead and does not need this.
# ============================================================================
set -euo pipefail

SERVICE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$SERVICE_DIR/.." && pwd)"
LABEL="com.jobmachine.dashboard"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

MODE="install"
case "${1:-}" in
  --check) MODE="check" ;;
  "") MODE="install" ;;
  *) echo "Unknown option: $1  (use --check)"; exit 2 ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
  echo "launchd is macOS-only; nothing to do on $(uname -s)." >&2
  exit 0
fi

# ThrottleInterval guards against a crash-loop hammering the machine. The PATH
# here is only a bootstrap so /bin/bash can find uv; serve.sh re-exports a fuller
# PATH (including /Library/TeX/texbin for pdflatex) once it starts.
render() {
  cat <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${SERVICE_DIR}/scripts/serve.sh</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${SERVICE_DIR}</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>StandardOutPath</key>
    <string>${REPO_ROOT}/logs/dashboard.log</string>

    <key>StandardErrorPath</key>
    <string>${REPO_ROOT}/logs/dashboard.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST_EOF
}

if [ "$MODE" = "check" ]; then
  if [ ! -f "$PLIST" ]; then
    echo "NOT INSTALLED: $PLIST"
    exit 1
  fi
  if render | diff -u "$PLIST" - >/dev/null; then
    echo "in sync: $PLIST matches this script"
    exit 0
  fi
  echo "DRIFT: installed plist differs from this script (installed vs rendered)"
  render | diff -u "$PLIST" - || true
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO_ROOT/logs"
render > "$PLIST"
echo "wrote $PLIST"

# bootout first so a re-run picks up an edited plist. It fails when the agent
# was never loaded, which is fine on a first install, hence the `|| true`.
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "loaded ${LABEL}"

for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8420/health >/dev/null 2>&1; then
    echo "healthy after ${i}s → http://127.0.0.1:8420 (loopback only, no auth)"
    exit 0
  fi
  sleep 1
done

echo "agent loaded but /health did not answer in 20s; check ${REPO_ROOT}/logs/dashboard.log" >&2
exit 1
