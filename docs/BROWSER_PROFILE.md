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

## Quick start (default: job Chrome, isolated profile)

### 1. Probe or start CDP

From the repo root:

```bash
./scripts/ensure-regular-chrome-cdp.sh   # probes only; tells you to run start-job-chrome.sh if down
```

If CDP is down, start the isolated profile directly:

```bash
./scripts/start-job-chrome.sh
export BU_CDP_URL=http://127.0.0.1:9222
```

First run: sign in once in **that** window (linkedin.com, wellfound.com). It persists
in `browser-profile/` for every future run. Your regular, everyday Chrome is never
touched, launched, or quit by this.

| Setting | Value |
|---|---|
| Profile dir | `<repo>/browser-profile` (absolute path, gitignored) |
| CDP port | `9222` (override with `JOB_MACHINE_CDP_PORT`) |
| Agent env | `BU_CDP_URL=http://127.0.0.1:9222` |
| Coexistence | Runs alongside daily Chrome (`open -na`), separate process |

> **Only one process may use `browser-profile/` at a time.** Quit job Chrome
> before another writer touches that folder.

> **Port collision:** if a stale regular-Chrome CDP attempt from an earlier session
> is still bound to `127.0.0.1:9222` (it happens, see the warning above), job Chrome
> may only win the IPv6 side of that port. If `start-job-chrome.sh` reports "CDP not
> responding," check `curl http://[::1]:9222/json/version` before assuming it failed,
> then retry on a clean port: `JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh`.

### 2. Attach automation

**Cursor (browser-use):**

```bash
export BU_CDP_URL=http://127.0.0.1:9222
browser-use --doctor
```

**Claude Code (Playwright MCP):**

Playwright MCP attaches via `--cdp-endpoint`, defined in the committed `.mcp.json` at
the repo root. It does **not** launch its own Chromium. Start job Chrome first, then
verify with `/mcp` → playwright connected.

**The config is committed, not per-machine.** `.mcp.json` (Claude Code) and
`.cursor/mcp.json` (Cursor) carry the identical definition, so every agent attaches to the
same browser without anyone exporting anything. Neither file sets `--user-data-dir`: the
launcher owns the profile, the port is the only contract. Do not re-add a profile path
here, and do not register a second copy of this server in `~/.claude.json`, or sessions
start diverging again.

**`claude-in-chrome` is the exception and does not apply here.** It reaches Chrome
through the extension in your regular, everyday Chrome, not CDP, and does not follow
you into the isolated job profile. Do not use it for job-machine work; use Playwright
MCP or browser-use against job Chrome instead.

### 3. Background tab safety

Even in the isolated profile, other automation may be sharing it in the same session:

- `start-job-chrome.sh` launches job Chrome hidden and without focus, with renderer
  and timer throttling disabled so hidden tabs still click, scroll, and screenshot.
  Use `JOB_MACHINE_CHROME_VISIBLE=1` only for first sign-in, CAPTCHA, or MFA.
- Prefer `new_tab(url)`, it works in background without stealing focus.
- Never call `activate_tab()` or Playwright `bringToFront()`. It unhides the window
  over Harsh's work. If a hidden tab truly will not respond, stop and report it.
- Close **only** tabs automation opened. Never bulk-close.

Full rules: `docs/AGENT-PLAYBOOK.md` ("Job Chrome: still don't make a mess").

---

## Deprecated: regular Chrome over CDP (does not work)

This was the original design (share your daily Chrome, already signed into
LinkedIn) and is kept here only so nobody re-discovers it the hard way.
`./scripts/start-chrome-debug.sh` still exists for pre-136 Chrome but is dead on
anything current:

```bash
./scripts/start-chrome-debug.sh   # quits nothing itself; refuses if Chrome is
                                   # already running, since macOS cannot attach
                                   # --remote-debugging-port to a live process
```

Even a clean launch with this flag on the default profile binds the port and then
404s every `/json/*` endpoint, per the restriction at the top of this doc. Quitting
and relaunching regular Chrome will not help. Do not ask Harsh to `Cmd+Q` his browser
to chase this further, use job Chrome instead.

---

## Overrides

| Variable | Default | Purpose |
|---|---|---|
| `JOB_MACHINE_CHROME_PROFILE` | `<repo>/browser-profile` | Isolated profile directory |
| `JOB_MACHINE_CDP_PORT` | `9222` | Remote debugging port |
| `BU_CDP_URL` | (unset) | Point browser-use at Chrome CDP |

Example, alternate port (also the fix for the port-9222-collision case above):

```bash
JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh
export BU_CDP_URL=http://127.0.0.1:9223
```

Persist `BU_CDP_URL` across terminals by adding the export line to `~/.zshrc`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Allow remote debugging?" popup | Click **Allow**, or run `browser-use mac-approve` |
| `/json/version` returns **404** | Default-profile restriction on Chrome 136+. Use `./scripts/start-job-chrome.sh`. Quitting and relaunching regular Chrome will not help |
| `/json/version` refused on `127.0.0.1` but `[::1]` works | Port collision with a stale listener. Retry on another port: `JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh` |
| `/json/version` refused entirely | Nothing is running. Start the job profile |
| Playwright launches its own browser | Its args lost `--cdp-endpoint`. Restore `.mcp.json` at the repo root, then restart the session. A relative `--user-data-dir` is the usual culprit: it resolves against the server's working directory, so it silently makes an empty profile |
| Agents landing in different browsers | Check for a duplicate `playwright` entry in `~/.claude.json`. A stale one registered under an old repo path is inert, but a live one overrides the committed config |
| LinkedIn logged out | Sign in again in job Chrome |
| Profile corruption | Quit all browsers using the profile, remove `browser-profile/`, start fresh |

---

## What this does *not* do

- Does not modify launchd or the dashboard service (`resume-tailor-service`).
- Does not commit cookies or profile data (folder stays gitignored).
- Does not replace the browser-tool routing table in `docs/AGENT-PLAYBOOK.md`.
