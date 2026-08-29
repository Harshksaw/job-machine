# Job Chrome — isolated browser profile

Job-machine automation (LinkedIn search, Wellfound applies, outreach) runs in a
**dedicated Chrome profile** so it never touches your daily browsing, bookmarks,
or work tabs.

Profile data lives in `./browser-profile/` at the repo root. That folder is
**gitignored** — cookies and login state stay on your machine only.

---

## Quick start

### 1. Start job Chrome

From the repo root:

```bash
./scripts/start-job-chrome.sh
```

This opens a **separate** Google Chrome instance (even if your normal Chrome is
already open) with:

| Setting | Value |
|---|---|
| Profile dir | `./browser-profile/` |
| CDP port | `9222` |
| Agent env | `BU_CDP_URL=http://127.0.0.1:9222` |

If CDP is already up, the script prints the connection URL and exits.

### 2. Sign in once (manual)

In the **job Chrome window** (not your regular Chrome):

1. Open [linkedin.com](https://www.linkedin.com) and log in.
2. Open [wellfound.com](https://wellfound.com) and log in.

Sessions persist in `./browser-profile/`. You should not need to repeat this
unless you clear the profile or cookies expire.

**Do not copy your entire default Chrome profile** into `browser-profile/`. That
would pull over unrelated cookies, extensions, saved passwords, and other
secrets. Prefer this fresh dedicated profile + one-time sign-in.

If you already used Playwright MCP with `--user-data-dir=./browser-profile`,
those sessions are the same profile — no need to sign in again.

### 3. Tell the agent to use it

**Cursor (browser-use / CDP):**

```bash
export BU_CDP_URL=http://127.0.0.1:9222
```

Then ask the agent to run LinkedIn / Wellfound / outreach work. Verify with:

```bash
browser-use --doctor
```

**Claude Code (Playwright MCP):**

Playwright MCP is configured (via `setup.sh` / README) with
`--user-data-dir=./browser-profile`. It launches its own Chromium with the
**same profile folder**.

> **Important:** Only one browser should use `browser-profile/` at a time.
> Quit job Chrome before starting a Claude Code Playwright session, or vice
> versa. Two processes locking the same profile can corrupt session data.


---

## Use your regular Chrome (already signed in)

When LinkedIn (or Wellfound) is already signed in on your **daily Chrome**, you
can attach automation to that profile instead of the isolated job profile.

### Tradeoffs

| | Job Chrome (`start-job-chrome.sh`) | Regular Chrome (`start-chrome-debug.sh`) |
|---|---|---|
| Profile | `./browser-profile/` (isolated) | Default macOS Chrome profile |
| Sign-in | One-time in job window | Already signed in |
| Risk | None to daily browsing | Automation shares work tabs/cookies |
| Coexistence | Runs alongside daily Chrome | **Must quit Chrome first**, then relaunch |

### Steps

1. **Fully quit Chrome** — `Cmd+Q` (not just close windows). Chrome must not be
   running, or the default profile is locked and remote debugging cannot attach.
2. Start Chrome with debugging:

```bash
./scripts/start-chrome-debug.sh
export BU_CDP_URL=http://127.0.0.1:9222
```

3. Chrome reopens your normal tabs and sessions. Automation should use
   **background tabs** (`new_tab(url)` in browser-use) and avoid
   `activate_tab()` unless you need the window in front (CAPTCHA/MFA).

**Do not copy** your default profile into `browser-profile/` — that would pull
over unrelated cookies, extensions, and saved passwords.

If you need daily Chrome back without CDP, quit again (`Cmd+Q`) and reopen Chrome
normally (without the script).

---

## Background tab safety (browser-use)

When job Chrome is connected via CDP, automation can drive tabs in the
background without stealing focus from your work Chrome:

- Prefer `new_tab(url)` for navigation — job Chrome is a separate app instance.
- Avoid `activate_tab()` unless you explicitly need the window in front (e.g.
  CAPTCHA or MFA).
- Job Chrome and daily Chrome are different processes — automation in job Chrome
  never affects your personal profile.

---

## Overrides

| Variable | Default | Purpose |
|---|---|---|
| `JOB_MACHINE_CHROME_PROFILE` | `<repo>/browser-profile` | Profile directory |
| `JOB_MACHINE_CDP_PORT` | `9222` | Remote debugging port |
| `BU_CDP_URL` | (unset → browser-use default) | Point Cursor agent at job Chrome |

Example — alternate port:

```bash
JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh
export BU_CDP_URL=http://127.0.0.1:9223
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Allow remote debugging?" popup | Click **Allow**, or run `browser-use mac-approve` |
| CDP not responding | Re-run the launcher you used; check no other app uses port 9222 |
| "Chrome is running but CDP is not available" | Quit Chrome fully (`Cmd+Q`), then `./scripts/start-chrome-debug.sh` |
| Want isolated profile again | Quit Chrome, use `./scripts/start-job-chrome.sh` instead |
| LinkedIn logged out | Sign in again in job Chrome; check you didn't delete `browser-profile/` |
| Profile corruption / weird state | Quit all browsers using the profile, remove `browser-profile/`, start fresh, sign in again |
| Playwright + job Chrome conflict | Quit one before starting the other (same profile dir) |

---

## What this does *not* do

- Does not modify launchd or the dashboard service (`resume-tailor-service`).
- Does not commit cookies or profile data (folder stays gitignored).
- Does not replace Claude Code Playwright MCP — it complements Cursor CDP
  automation with the same on-disk profile.
