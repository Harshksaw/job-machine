# Browser automation: CDP attach

Job-machine automation attaches to Chrome over CDP. **Default:** the isolated job
profile on port 9223.

> **Regular Chrome over CDP is dead on Chrome 136 and later.** Chrome refuses remote
> debugging on the default user data directory. It accepts the flag, binds the port, then
> returns **404 on every `/json/*` endpoint**. Confirmed 2026-08-31 on Chrome 152, with
> the isolated profile working on the same binary at the same moment. A 404 is this
> restriction; connection refused is a browser that is not running. Re-running
> `start-chrome-debug.sh` cannot fix a 404.

Profile data for the isolated lane lives in
`/Users/harshsaw/job-machine/browser-profile/` (gitignored).

---

## Quick start (default: regular Chrome)

### 1. Probe or start CDP

From the repo root:

```bash
./scripts/ensure-regular-chrome-cdp.sh
```

If CDP is down:

1. **Fully quit Chrome**, `Cmd+Q` (not just close windows).
2. Start with remote debugging:

```bash
./scripts/start-chrome-debug.sh
export BU_CDP_URL=http://127.0.0.1:9222
```

| Setting | Value |
|---|---|
| Profile | Default macOS Chrome (no `--user-data-dir`) |
| CDP port | `9222` (override with `JOB_MACHINE_CDP_PORT`) |
| Agent env | `BU_CDP_URL=http://127.0.0.1:9222` |

### 2. Attach automation

**Cursor (browser-use):**

```bash
export BU_CDP_URL=http://127.0.0.1:9222
browser-use --doctor
```

**Claude Code (Playwright MCP):**

Playwright MCP attaches via `--cdp-endpoint=http://127.0.0.1:9223`, defined in the
committed `.mcp.json` at the repo root. It does **not** launch its own Chromium. Start
regular Chrome first, then verify with `/mcp` → playwright connected.

**The config is committed, not per-machine.** `.mcp.json` (Claude Code) and
`.cursor/mcp.json` (Cursor) carry the identical definition, so every agent attaches to the
same browser without anyone exporting anything. Neither file sets `--user-data-dir`: the
launcher owns the profile, the port is the only contract. Do not re-add a profile path
here, and do not register a second copy of this server in `~/.claude.json`, or sessions
start diverging again.

**`claude-in-chrome` is the exception.** It reaches Chrome through the extension, not CDP,
so it always lands in the regular Chrome no matter which browser owns 9222. That agrees
with the default lane. It does **not** follow you into the isolated job profile, so when
`start-job-chrome.sh` is the active browser, use Playwright MCP only.

### 3. Background tab safety

Harsh works in tab groups with real tabs open. Automation must not disturb tabs
it did not open:

- Prefer `new_tab(url)`, it works in background without stealing focus.
- Avoid `activate_tab()` unless CAPTCHA/MFA needs the window in front.
- Close **only** tabs automation opened. Never bulk-close or touch existing tabs.

Full rules: `docs/AGENT-PLAYBOOK.md` ("Regular Chrome: do not disturb existing tabs").

---

## Optional: isolated job Chrome

Use **only when Harsh explicitly requests** the isolated profile (experiments,
Chrome-for-Testing debugging, or when regular Chrome submit handlers misbehave).

```bash
./scripts/start-job-chrome.sh
export BU_CDP_URL=http://127.0.0.1:9222
```

| Setting | Value |
|---|---|
| Profile dir | `/Users/harshsaw/job-machine/browser-profile` (absolute) |
| CDP port | `9222` |
| Coexistence | Runs alongside daily Chrome (`open -na`) |

Sign in once in **this** window: linkedin.com and wellfound.com. Do not copy your
default Chrome profile into `browser-profile/`.

> **Only one process may use `browser-profile/` at a time.** Quit job Chrome
> before another writer touches that folder.

Playwright MCP still attaches via the same CDP port; whichever Chrome owns port
9222 is the profile in use.

---

## Tradeoffs

| | Regular Chrome (default) | Job Chrome (on request) |
|---|---|---|
| Profile | Default macOS Chrome | `browser-profile/` (isolated) |
| Sign-in | Already signed in | One-time in job window |
| Risk | Shares work tabs/cookies | None to daily browsing |
| Coexistence | Must quit/relaunch for CDP | Runs alongside daily Chrome |

---

## Overrides

| Variable | Default | Purpose |
|---|---|---|
| `JOB_MACHINE_CHROME_PROFILE` | `<repo>/browser-profile` | Isolated profile directory |
| `JOB_MACHINE_CDP_PORT` | `9222` | Remote debugging port |
| `BU_CDP_URL` | (unset) | Point browser-use at Chrome CDP |

Example, alternate port:

```bash
JOB_MACHINE_CDP_PORT=9223 ./scripts/start-chrome-debug.sh
export BU_CDP_URL=http://127.0.0.1:9223
```

Persist `BU_CDP_URL` across terminals by adding the export line to `~/.zshrc`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Allow remote debugging?" popup | Click **Allow**, or run `browser-use mac-approve` |
| `/json/version` returns **404** | Default-profile restriction on Chrome 136+. Use `JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh`. Quitting and relaunching regular Chrome will not help |
| `/json/version` refused | Nothing is running. Start the job profile |
| "Chrome is running but CDP is not available" | Quit Chrome fully (`Cmd+Q`), then `./scripts/start-chrome-debug.sh` |
| Playwright launches its own browser | Its args lost `--cdp-endpoint`. Restore `.mcp.json` at the repo root, then restart the session. A relative `--user-data-dir` is the usual culprit: it resolves against the server's working directory, so it silently makes an empty profile |
| Agents landing in different browsers | Check for a duplicate `playwright` entry in `~/.claude.json`. A stale one registered under an old repo path is inert, but a live one overrides the committed config |
| Want isolated profile | `./scripts/start-job-chrome.sh` (only when needed) |
| LinkedIn logged out (job profile) | Sign in again in job Chrome |
| Profile corruption (job profile) | Quit all browsers using the profile, remove `browser-profile/`, start fresh |

---

## What this does *not* do

- Does not modify launchd or the dashboard service (`resume-tailor-service`).
- Does not commit cookies or profile data (folder stays gitignored).
- Does not replace the browser-tool routing table in `docs/AGENT-PLAYBOOK.md`.
