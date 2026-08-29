#!/usr/bin/env bash
# ============================================================================
# Job Machine — one-shot setup for a fresh clone (e.g. your work laptop).
#
#   git clone https://github.com/Harshksaw/job-machine.git
#   cd job-machine
#   bash setup.sh            # host mode: runs the tailor service via uv + TeX Live
#   bash setup.sh --docker   # docker mode: runs the tailor service in a container
#
# Idempotent: safe to re-run. Does all one-time setup, then prints how to run.
# No secrets required — the resume-tailor service on this branch is local-only
# with NO auth (binds to 127.0.0.1).
#
# What is (and isn't) containerizable:
#   • The tailor service CAN run in Docker (Dockerfile bakes in TeX Live + Node +
#     the claude CLI; compose mounts your host ~/.claude for its LLM login).
#   • The application run itself CANNOT — the `claude` CLI drives Chrome via
#     Playwright MCP against your persistent LinkedIn profile, on the host.
#
#   --docker vs host trade-off:
#     host   → needs uv + TeX Live installed (userspace; no admin). Two windows.
#     docker → needs Docker + a host `claude` login (for the ~/.claude mount).
#              Service runs DETACHED → you only need ONE window (for `claude`).
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")"

MODE="host"
case "${1:-}" in
  --docker) MODE="docker" ;;
  --host|"") MODE="host" ;;
  *) echo "Unknown option: $1  (use --docker or --host)"; exit 2 ;;
esac

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

[ -f CLAUDE.md ] && [ -d resume-tailor-service ] || die "Run this from the job-machine repo root."
bold "Job Machine setup — mode: ${MODE}"

# ---- Host-side prerequisites (needed for the application run in BOTH modes) --
bold "1/6  Host prerequisites (needed to drive the browser, either mode)"
have node || die "Node.js 18+ required — install from https://nodejs.org then re-run."
ok "node $(node --version)"
have npm  || die "npm required (ships with Node.js)."
if ! have claude; then
  warn "Claude Code CLI not found — installing globally…"
  npm install -g @anthropic-ai/claude-code || die "Failed to install @anthropic-ai/claude-code."
fi
ok "claude $(claude --version 2>/dev/null || echo installed)"
warn "If never logged in on this machine: run 'claude' once and sign in (both the run AND"
warn "the tailor service's LLM call reuse this login — no ANTHROPIC_API_KEY needed)."

bold "2/6  resume.pdf"
if [ -f resume.pdf ]; then ok "resume.pdf present"; else
  warn "resume.pdf MISSING — copy your resume PDF into $(pwd)/resume.pdf (upload fallback)."
fi

bold "3/6  Playwright MCP (persistent browser profile → log in to LinkedIn once)"
if claude mcp list 2>/dev/null | grep -q '^playwright'; then
  ok "playwright MCP already configured for this folder"
else
  claude mcp add playwright -- npx -y @playwright/mcp@latest --user-data-dir=./browser-profile \
    && ok "playwright MCP added (profile: ./browser-profile — gitignored)" \
    || warn "Could not add playwright MCP automatically — see README.md step 2."
fi
bold "4/6  Chromium for Playwright"
npx -y playwright install chromium >/dev/null 2>&1 && ok "chromium installed" \
  || warn "chromium install skipped/failed — run 'npx playwright install chromium' manually."

# ---- resume-tailor-service (mode-specific) ---------------------------------
bold "5/6  resume-tailor-service .env (no secrets needed)"
if [ -f resume-tailor-service/.env ]; then
  ok ".env already exists — leaving it untouched"
elif [ "$MODE" = "docker" ]; then
  # In a container, 127.0.0.1 is the container itself, so the host mock sheet is
  # unreachable. /tailor (all the run needs) works regardless; the dashboard's
  # sheet-reads stay disabled unless you point APPS_SCRIPT_URL at a real /exec.
  cp resume-tailor-service/.env.example resume-tailor-service/.env
  ok "created resume-tailor-service/.env (APPS_SCRIPT_URL left blank; /tailor works, dashboard reads disabled)"
else
  cp resume-tailor-service/.env.example resume-tailor-service/.env
  grep -q '127.0.0.1:8799' resume-tailor-service/.env || printf \
    '\n# Auto-set by setup.sh: point the dashboard read-source at the bundled mock.\nAPPS_SCRIPT_URL=http://127.0.0.1:8799/exec\nAPPS_SCRIPT_READ_SECRET=local-dev\n' \
    >> resume-tailor-service/.env
  ok "created resume-tailor-service/.env (points at the bundled mock sheet on :8799)"
fi

if [ "$MODE" = "docker" ]; then
  bold "6/6  Build + start the tailor service in Docker (detached)"
  have docker || die "Docker not found — install Docker Desktop, or re-run without --docker."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running — start Docker Desktop, then re-run."
  [ -d "${HOME}/.claude" ] || warn "~/.claude not found — run 'claude' once so the container can mount your login."
  ( cd resume-tailor-service && docker compose up -d --build ) \
    && ok "container up → http://127.0.0.1:8420 (loopback only, no auth)" \
    || die "docker compose up failed."
  # brief health check
  for i in 1 2 3 4 5 6 7 8; do
    if curl -fsS http://127.0.0.1:8420/health >/dev/null 2>&1; then ok "service healthy (/health ok)"; break; fi
    [ "$i" = 8 ] && warn "service not answering /health yet — check 'docker compose logs -f' in resume-tailor-service/"
    sleep 2
  done
else
  bold "6/6  Python deps for the tailor service (host mode)"
  if ! have uv; then
    warn "uv not found — installing (userspace, no admin)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    have uv || die "uv installed but not on PATH — open a new shell and re-run."
  fi
  ok "uv $(uv --version 2>/dev/null || echo installed)"
  warn "Host mode compiles PDFs with LaTeX — TeX Live must be installed (texlive-latex-base/-extra/-fonts-recommended). Docker mode bundles it for you."
  ( cd resume-tailor-service && uv sync ) && ok "uv sync complete (.venv ready)" || die "uv sync failed."

  # launchd supervises the dashboard on macOS (starts at login, restarts on
  # crash) — the host-mode equivalent of compose's `restart: unless-stopped`.
  if [ "$(uname -s)" = "Darwin" ]; then
    ( cd resume-tailor-service && ./scripts/install-launchd.sh ) \
      && ok "launchd agent installed — dashboard supervised on http://127.0.0.1:8420" \
      || warn "launchd install failed — run resume-tailor-service/scripts/install-launchd.sh by hand, or use ./scripts/start.sh per session."
  fi
fi

# ---- Next steps ------------------------------------------------------------
echo
if [ "$MODE" = "docker" ]; then
  bold "✅ Docker setup complete. The service is already running (detached). ONE window to run:"
  cat <<'EOF'

      claude
      # then say:  run the linkedin prompt      (prompts/linkedin-run.md)
      #      or:   run the outreach / wellfound prompt

  Service controls (from resume-tailor-service/):
      docker compose logs -f      # watch it        docker compose down   # stop it
EOF
else
  bold "✅ Host setup complete (all local-only). To run the machine:"
  cat <<'EOF'

  On macOS the tailor service is ALREADY running under launchd — it starts at
  login and restarts on crash, so you only need ONE window:

      claude
      # then say:  run the linkedin prompt      (prompts/linkedin-run.md)

  Service controls (from resume-tailor-service/):
      curl -s 127.0.0.1:8420/health          # is it up?
      ./scripts/install-launchd.sh --check   # does the agent match the repo?
      tail -f ../logs/dashboard.log          # watch it
      ./scripts/start.sh                     # foreground run instead (adds mock sheet :8799)
EOF
fi
cat <<'EOF'

  First run only: in the claude window, /mcp should show playwright ✔ Connected,
  then open linkedin.com once and log in — ./browser-profile keeps you signed in.

  Cursor agents: ./scripts/start-job-chrome.sh  (see docs/BROWSER_PROFILE.md)

  Where the last run left off:  docs/sessions/2026-07-24-linkedin-run.md
EOF
