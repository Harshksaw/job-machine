# Job Machine — Full Setup

One-time setup ~20 min. After that: open terminal, run `claude`, say "run the wellfound prompt".

---

## 0. Prerequisites
- Node.js 18+ (`node --version` to check)
- Chrome installed
- Your resume PDF saved into this folder as `resume.pdf`

## 1. Install Claude Code (skip if installed)
```bash
npm install -g @anthropic-ai/claude-code
claude          # first run → log in with your Claude subscription account
```
Docs: https://docs.claude.com/en/docs/claude-code/overview

## 2. Add Playwright MCP with a PERSISTENT browser profile
Run this **inside this folder** (config is per-directory):
```bash
cd job-machine
claude mcp add playwright -- npx -y @playwright/mcp@latest --user-data-dir=./browser-profile
npx playwright install chromium
```
Why `--user-data-dir`: the browser keeps its own profile folder, so you
log in to LinkedIn + Wellfound ONCE and stay logged in for every future run.

Verify: run `claude`, then type `/mcp` — playwright should show ✔ Connected.
(First check may fail while npx downloads; wait a few seconds, retry.)

## 3. Set up resume-tailor-service (one-time)
Tailors `resume.pdf` per job description before every upload in the run
prompts, guaranteeing a real, one-page PDF (no fabrication — content comes
from `resume-tailor-service/content/resume_bank.yaml`).
```bash
cd resume-tailor-service
uv sync
cp .env.example .env   # fill in ANTHROPIC_API_KEY and RESUME_TAILOR_TOKEN
uv run uvicorn app.main:app --port 8420
```
See `resume-tailor-service/README.md` for full setup, the Docker/VPS option,
and the API shape.

`RESUME_TAILOR_TOKEN` must be exported in the shell running `claude` (or
sourced from `resume-tailor-service/.env`) — the run prompts' `curl` calls
to `/tailor` use it to authenticate. If the service isn't running, the run
prompts fall back to `./resume.pdf` automatically.

## 4. One-time login run
Inside `claude`:
```
Use playwright mcp to open a browser to linkedin.com — I'll log in manually,
tell me when you see my feed. Then open wellfound.com, same thing.
```
Log in by hand in the window that opens. Done — sessions persist in ./browser-profile.

## 5. Test the webhook
```
Open this URL with playwright and tell me the response:
https://script.google.com/macros/s/AKfycbz4hpb7VnQIsHEiOyN6wa-7R254QOdo3n0QK-pNw7gJ52a3BbKltIx0pY1PqYkfD2SJLA/exec?company=CCTest&role=SWE&status=test
```
Expect {"ok":true} + a row in the sheet. If you get a Google login page instead,
redeploy the Apps Script with access = "Anyone" (Deploy → Manage deployments → edit).

## 6. Daily usage
```bash
cd job-machine && claude
```
Then one of:
- `Read prompts/wellfound-run.md and execute it`
- `Read prompts/linkedin-run.md and execute it`
- `Read prompts/outreach-run.md and execute it`

CLAUDE.md in this folder is loaded automatically every session — it holds your
profile, rules, and webhook so the run prompts stay short.

## 7. Volume lane — ApplyPilot (add later, optional)
```bash
git clone https://github.com/Pickle-Pixel/ApplyPilot   # verified 2026-07-19 — 1.3k★, built on Claude Code CLI
```
Follow its README; it runs on Claude Code. Point its resume facts at resume.pdf,
set fit threshold 7+, add a post-apply curl to the webhook with source=ApplyPilot.
Keep it OFF LinkedIn.

## 8. Form-hell lane — Skyvern (only if Workday/Greenhouse queue builds up)
https://github.com/Skyvern-AI/skyvern — self-host per README.

---

## Safety rails (already baked into prompts)
- LinkedIn: human pace, max ~12 connection requests/session, no bulk anything
- Never fabricate experience in any answer or form
- Every action logs to the sheet — statuses: applied / people-mined /
  outreach-sent / outreach-queued / replied / interview / rejected
