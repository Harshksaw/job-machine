# Agent playbook

Operating techniques for this repo, learned the expensive way. Read `AGENTS.md` first for
the rules; this file is the how.

Most of this was discovered during live apply sessions between 2026-07 and 2026-08. Dates
are kept so you can judge staleness. Web UIs change: if a selector here does not match,
verify against the live page rather than assuming the page is broken.

**This file is committed to a PUBLIC repo.** Techniques only. Never add a confirmation
code, dossier id, third-party name, or anything from `docs/PERSONAL-ANSWERS.md`. Live queue
state belongs in the gitignored `SESSION-HANDOFF-*.md`.

---

## Before any browser session

**Standing rule:** Default browser is Harsh's **regular Chrome** via
`./scripts/start-chrome-debug.sh` (default profile, LinkedIn already signed in).
Port **9222** by default (override with `JOB_MACHINE_CDP_PORT`). Use job Chrome
(`./scripts/start-job-chrome.sh`, `./browser-profile/`) **only when Harsh explicitly
requests the isolated profile.** Verify with `./scripts/ensure-regular-chrome-cdp.sh`
or `curl -fsS http://127.0.0.1:<port>/json/version` before trusting CDP.

**Startup sequence (every session):**

1. `./scripts/ensure-regular-chrome-cdp.sh` (or manual curl probe on port 9222).
2. **If CDP responds:** attach immediately. `export BU_CDP_URL=http://127.0.0.1:9222`.
   Do **not** quit, restart, or relaunch Chrome from automation.
3. **If CDP is down:** stop and tell Harsh. He must `Cmd+Q` Chrome himself, then run
   `./scripts/start-chrome-debug.sh`. Agents never run `Cmd+Q`, `osascript` quit
   Chrome, `killall Chrome`, or any other command that closes his browser or tabs.
4. `export BU_CDP_URL=http://127.0.0.1:9222` (re-export in each new terminal;
   add to `~/.zshrc` if you want it persistent).
5. Cursor: `browser-use --doctor` · Claude Code: `/mcp` → playwright connected.

### Regular Chrome: do not disturb existing tabs

Harsh works in **tab groups** with real tabs open. Automation attaches to his
regular Chrome over CDP and must never disturb tabs or groups it did not open.

**Attach, never quit.** Probe CDP first. If port 9222 responds, connect and work.
Never quit Chrome, never bulk-close tabs, never switch the visible tab, and never
reorganize tab groups from automation. If CDP is unavailable, report the blocker
and wait for Harsh to enable remote debugging himself.

**Background tabs only.** In browser-use, `new_tab(url)` opens a tab without
changing which tab is visible in the window. CDP input (clicks, typing) works in
background tabs. Do **not** call `activate_tab()` unless Harsh explicitly asks or
CAPTCHA/MFA needs the window in front.

**Close only what you opened.** Keep a session list of automation tab target ids
(or the exact `linkedin.com/in/` URLs you opened). After each outreach send, close
**only** that tab. Never close tabs by guessing index, never run "close all except",
and never touch Harsh's pre-existing tabs, dashboard tabs he opened, or sheet
confirm tabs unless he opened them for this automation run.

**Automation tab budget:** max **5 automation tabs** open at once (not counting
Harsh's existing tabs). For outreach, open one profile tab, send, close it, then
open the next. Do not leave `/in/` profile tabs open after a send.

**Never from automation:**

- `Cmd+Q`, `osascript` quit Chrome, `killall "Google Chrome"`
- Bulk tab close, "close other tabs", or closing tabs not on your session list
- `activate_tab()` during normal outreach (background is the default)
- Starting job Chrome (`start-job-chrome.sh`) when regular Chrome CDP is up
- Any action that would steal focus from Harsh's current tab group

## Which browser tool (routing)

| Task | Agent | Tool | Preconditions |
|---|---|---|---|
| LinkedIn search, Easy Apply, outreach | Cursor | **browser-use** (`BU_CDP_URL`) | Regular Chrome up via `start-chrome-debug.sh` |
| Same tasks in Claude Code | Claude Code | **Playwright MCP** (attach via `--cdp-endpoint`) | Chrome CDP on 9222 |
| LinkedIn iframe / shadow DOM | Claude Code | Playwright MCP | Same CDP attach |
| Sheet webhook confirm | Either | browser-use or Playwright | Google session in regular Chrome |
| Public ATS JD fetch | Either | `curl` (no browser) | None |
| ZipRecruiter apply | Claude Code | Playwright MCP | Regular Chrome preferred |
| Isolated profile experiment | Either | `start-job-chrome.sh` first | **Only when Harsh asks** |

Do **not** use claude-in-chrome or ecc chrome-devtools MCP for job-machine work
unless Harsh explicitly switches stacks. Default lane: regular Chrome + browser-use
(Cursor) or Playwright MCP attach (Claude Code).

1. **Confirm you are the only driver when using `browser-profile/`.** Run
   `ps aux | grep [c]laude` and `ps aux | grep [p]laywright-mcp`. On 2026-08-27 a second
   `claude` process plus a `playwright-mcp` instance drove the same CDP browser and the
   same dossier store. It closed tabs mid-script, opened others, and contributed to five
   unintended LinkedIn invites. It also produced contradictory `applied` and `outreach`
   reconciliations on the same dossier, because two agents were overwriting each other.
2. **If a dossier event appears that you did not write, stop and tell Harsh.** Do not
   reconcile. Reconciling against a live second writer just flip-flops the record.
3. **Find the real CDP port.** The script defaults to 9222 but sessions have run on 9223.
   `curl -fsS http://127.0.0.1:<port>/json/version` before trusting either.
4. **Smoke-test the apply lane on one form before staging a queue.** See the next section
   for why.
5. **Tab budget applies to automation tabs only** (see "Regular Chrome: do not disturb
   existing tabs" above). Max 5 automation tabs open at once. After each LinkedIn outreach
   send, close the `/in/` profile tab you opened for that send. Do not count or close
   Harsh's pre-existing tabs.

## Known-broken lane: inert submit buttons (2026-08-28)

On 2026-08-28 nothing could be submitted from the job Chrome (Chrome-for-Testing,
`browser-profile/`, CDP 9223) across two unrelated stacks:

- **Wellfound:** `Apply` / `Apply now` present, enabled, in viewport. Trusted mouse clicks
  produced no modal, no navigation, no textarea.
- **Greenhouse:** form filled end to end including resume upload and e-signature,
  `checkValidity()` reported zero invalid fields, and trusted mouse down/up on "Submit
  application" produced no navigation, no confirmation, and no error.

Everything else in the same session worked: navigation, typing, file upload, comboboxes,
and LinkedIn invites. It was specifically the submit and apply handlers.

**Consequence for every session:** always verify a submission against the site's own
record (Wellfound `/jobs/applications`, LinkedIn sent-invitations list, an ATS
confirmation screen) before writing `status=applied`. Never infer success from a click.

Suspects still unruled-out: the Chrome-for-Testing profile itself, an extension inside
`browser-profile/`, or a second process on the same profile. Harsh's normal Chrome is the
control test.

---

## LinkedIn

### Easy Apply lives inside an iframe

The current flow (`?openSDUIApplyFlow=true`) renders the modal inside the **same-origin
`iframe[0]`**, a full-viewport `position:absolute; z-index:-1` iframe that hosts the app,
not in the top document. So `read_page` and top-level `document.querySelector` find
nothing and `[role="dialog"]` returns 0.

The modal is often taller than the viewport, so its sticky footer (the Next / Review /
Submit button) is clipped below the fold and screenshots cap around 840px no matter what
you pass to `resize_window`. Reach into the iframe instead:

```js
const d = document.querySelectorAll('iframe')[0].contentDocument;
const m = d.querySelector('.jobs-easy-apply-modal, .artdeco-modal');
const btn = [...m.querySelectorAll('button')]
  .find(b => /Submit application|^Next$|^Review$/i.test((b.getAttribute('aria-label')||b.innerText||'')));
btn.scrollIntoView({block:'center'}); btn.click();
```

Single-step Easy Apply (contact info plus resume, no screening questions) shows "Submit
application" directly. Confirmation text is "Your application was sent to <company>!".
Contact info and resume prefill from the profile; keep the most-recently-used resume
unless it is stale. Do **not** double-click the "Easy Apply" button: the second click can
trigger the "Save this application?" leave dialog, which you dismiss with its X.

### Profile menus live in an open shadow root

The profile action menu, the invite modal, and the sent-invitations controls render inside
an open shadow root (`#interop-outlet`). `document.querySelector` finds nothing there;
Playwright text locators pierce it.

Verified connect-with-note flow (2026-08-27):

- Top-card Connect is usually absent for 3rd-degree connections. Click the topmost visible
  `button[aria-label="More"]`.
- Anchor on the menu item **"Save to PDF"**, which is unique to that menu, walk up to its
  container, then click the sibling **"Connect"**.
- Click **"Add a note"** (last match), fill `textarea#custom-message`, click **"Send"**
  (exact match).
- On the sent page, "Withdraw" is a bare `<span>` with no button role, and its confirm
  lives in `dialog[open]`.
- The note cap is **300 characters**. Check length before filling.

**Never use `main button:has-text("Connect")`.** It also matches "People you may know"
sidebar buttons. On 2026-08-27 that selector sent five unintended note-less invitations
before it was caught, and they had to be withdrawn. Scope any Connect selector strictly to
the profile top card, and after every send verify the target profile shows "Pending" and
that the sent-invitations list shows the right person with the right note. Never batch-send
without per-send verification.

Invite cap is 12 per session (`AGENTS.md` rule 3) and every message needs Harsh's approval
before it goes out.

### Outreach send workflow (regular Chrome, non-disruptive)

After Harsh approves a batch (`prompts/outreach-run.md` step 4), send at human pace
without touching his other tabs:

1. Confirm CDP on regular Chrome (`ensure-regular-chrome-cdp.sh`), LinkedIn signed in.
2. For each approved Person: `new_tab("<linkedin_profile_url>")` in the background.
   Record the target id or URL in your session list.
3. Browse the profile briefly, run the connect-with-note flow in **that tab only**
   (selectors above). Do not navigate his visible tab or open LinkedIn feed in an
   existing tab.
4. Verify: profile shows **Pending**, sent-invitations list matches person and note.
5. Close **only** the tab you opened (session list). Wait 30-60s before the next send.
6. Update Person to `sent`, append dossier `outreach` activity, log the sheet row.

If CDP is down mid-batch, stop and tell Harsh. Do not quit Chrome or close unrelated
tabs to recover.

---

## Wellfound

### Harvest full JDs from `__NEXT_DATA__`, no login

Public role pages (`/role/<slug>`, `/role/r/<slug>` for remote, `?page=N` to paginate) ship
every search result inside `#__NEXT_DATA__` at `props.pageProps.apolloState.data`:

- `JobListingSearchResult:<id>` carries the **complete JD** in `description`, plus
  `jobType` (full-time / contract / internship / cofounder), `liveStartAt` (unix epoch,
  gives the real post date), `locationNames`, `acceptedRemoteLocationNames`,
  `compensation`, `yearsExperienceMin/Max`, and `atsSource`.
- `StartupResult:<id>` carries `name`, `slug`, `companySize`, `highConcept`, `badges`, and
  `highlightedJobListings` refs that join companies to jobs.
- Job URL is `wellfound.com/jobs/<id>-<slug>`. The team page is `/company/<slug>/people`,
  where founders and titles render in page text, not in apolloState.

A 2026-08-26 run of 8 role families times 3 pages returned 1,185 unique listings with full
JDs. **`atsSource` is the real unlock:** it routes you to the company's own ATS board,
which accepts applications without a Wellfound login and avoids the inert-submit problem
above.

Custom note field rules are in `AGENTS.md` rule 4.

---

## ZipRecruiter

A standing source, but **live browser search only**. Search URL is
`ziprecruiter.com/jobs-search?search=<terms>&location=Canada`. No bot wall on search
itself. Job cards load the JD in an SPA panel via the **"View <title>"** button; clicking
the article does not select it. Enumerate cards and extract JD text with `javascript_tool`,
because `get_page_text` grabs the company "About" sidebar rather than the JD.

- **"1-Click Apply" is not one click.** It opens a multi-step employer form: name, email,
  phone, address, plus per-employer screening (work-auth dropdown, commute yes/no,
  education, free text). Comboboxes are custom ARIA widgets, not `<select>`: open, then
  click the `[role=option]`.
- **Auth gotcha:** a session can be partially authenticated, able to browse and submit but
  with `/profile` redirecting to `/authn/login` (passwordless email-code). In that state
  the form-apply likely goes out **with no resume attached**. The resume attaches reliably
  only when fully logged in, and only Harsh can complete the email-code login.
- **Form type decides success** (2026-08-01):
  - **Radio-only forms work.** Select radios, Continue, confirm the button reads
    "Applied". This is the good case.
  - **Text and address forms are blocked two ways at once.** Clicking or typing into an
    address field can trigger a third-party autofill extension that hard-crashes MCP tools
    with `Cannot access a chrome-extension:// URL of different extension`, and nothing
    recovers until you `navigate` to reload the tab. Separately, setting values through
    `javascript_tool` native-setter plus events makes fields look filled while leaving the
    React form's internal validity false, so Continue stays `disabled`. Both input paths
    are dead. If the modal has free-text or address inputs, expect not to be able to
    submit. Try the company's own careers site instead.
- Postings can close mid-apply: a reload returns "the job you were trying to access has
  closed" and redirects to `/jobseeker/home?closed_job_redirect=1`. Not a bug on our side.

## Ashby boards

The board SPA resists ref-clicks. Get a role UUID with `javascript_tool`
(`document.querySelectorAll('a')` filtered by title) and navigate directly to
`/<org>/<uuid>/application`. Fields then fill with `form_input` plus `file_upload`.
Comboboxes need click, type, then click the option.

---

## Fetching full JD text without a browser

Verified 2026-08-16 across roughly 40 postings. A plain fetch of the public job URL usually
returns a JS shell, so use these instead:

| ATS | Endpoint |
|---|---|
| LinkedIn | `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<jobId>` returns the full public description where `/jobs/view/...` shows a login wall. `<jobId>` is the trailing digits of the normal URL. Highest-yield trick of the sweep. |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/<org>` returns all published postings with a `descriptionPlain` field. `<org>` is the path segment after `ashbyhq.com/`. |
| Lever | `https://api.lever.co/v0/postings/<org>/<posting-id>` |
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/<board-token>/jobs/<job-id>` |
| Wellfound | Public job detail pages fetch fine. A company `/company/<x>/jobs` index can 403, so go to the specific `/jobs/<id>-<slug>` page. |

**Redirect traps that return plausible but WRONG text.** Always confirm the returned role
matches the one you asked for:

- **Greenhouse** silently redirects an expired job URL to the company's board index, so a
  naive fetch returns some *other* live posting. One fetch returned an unrelated "Alliances
  Field Engineer" for a graduate-SWE URL. Confirm through the single-job API: a 404 there
  means the posting is gone.
- **LinkedIn** redirects expired postings to the generic job-search list rather than 404ing.
- **Rippling** redirects to `?rr_message=job_not_found`.

**Expect heavy staleness.** In that sweep 14 of about 40 saved postings were already dead.
Treat a dossier's saved `job_url` as perishable and re-verify before writing a kit against
it.

---

## Dedupe before capture

`AGENTS.md` rule 8 is the rule. This is the mechanism, and it exists because the rule was
broken twice.

On 2026-08-26 two duplicate applications shipped to companies that had been applied to
weeks earlier. The dedupe pass had been computed over one JSON list and capture then ran
from a *different* list, so the result was printed and never applied. One company was even
correctly flagged "already tracked" and the flag was ignored.

How to do it right:

- Dedupe the **same object list you iterate** for capture. Not a sibling list, not an
  earlier snapshot.
- Make the check **block the write**, not print a warning.
- Match on more than the raw URL. Greenhouse serves the same requisition from both
  `boards.greenhouse.io` and `job-boards.greenhouse.io`, so normalize the host and compare
  the numeric requisition id, and cross-check company plus role as well.
- `capture` upserts on `job_url`, so reusing the exact same URL is the intended way to
  update a dossier rather than fork it.
- Old session handoffs are also a dedupe source. Check the newest `SESSION-HANDOFF-*.md`
  for its "do not resend" list before applying to anything.

Since 2026-08-28 the store enforces the URL half of this itself.
`job_store.canonical_job_url()` folds the Greenhouse host aliases, drops a trailing
`/application` or `/apply` segment, strips `www.` and per-visit tracking parameters
(`refId`, `trackingId`, `trk`, `utm_*`, and friends), and `find_matching_job` compares that
canonical form instead of the raw string. Identity-bearing query parameters survive on
purpose: CookUnity's posting is `?gh_jid=7751648003`, so stripping the query would have
merged unrelated roles. You still owe the company plus role cross-check, because a URL that
points at a company listing index rather than one posting can canonicalize the same for two
different jobs.

### A logged submission is not an applied status

The re-send gate reads `status`. Writing a `kind: applied` activity does **not** by itself
make the dossier read as applied. Five listings from the 2026-08-28 overnight run sat at
`applying` with a perfectly good "Application submitted now" event underneath, which is
exactly the state a later session would treat as unapplied and submit again.

`add_activity` now advances `discovered`, `researching`, `ready`, or `applying` to
`applied` when an `applied` event lands, and never regresses a later status such as
`interview`. Keep setting the status explicitly anyway: the auto-advance is a safety net,
not the contract.

---

## Resume tailoring

**Default: do not tailor.** Upload the original `./resume.pdf` as-is for every application.
ATS parsers handle it fine. Harsh's instruction (2026-08-02): "don't use the tailoring
unless very much required, use original as it is."

If a role genuinely requires a tailored resume, **confirm with Harsh first**, treat it like
an outreach send. Preserve his exact LaTeX format from the `harshsaw.tex` template: never
restructure sections, fonts, or spacing. Visually compare the output against
`resume.pdf` before using it.

Two historical causes of layout distortion were fixed on 2026-08-16, so "it breaks my
formatting" is no longer the reason to decline, but the confirm-first rule still stands:

1. `/tailor` rendered through `templates/resume.cls` instead of the canonical root
   `resume.cls`, so margins and section rules were never his.
2. `harshsaw.tex` bolds roughly 49 phrases inside bullets (technologies and numbers) while
   the bank stored them as plain text, so every tailored PDF came out flat. The bank now
   carries emphasis as `**phrase**`, `app/render_tex.py` converts it to a bold command
   after LaTeX escaping, and `app/bank.py: strip_emphasis` keeps the markers out of cover
   letters, prepared answers, and the traceability corpus.

Also fixed: a job or project whose bullets were all trimmed emitted an empty LaTeX list and
killed the render with "perhaps a missing \item". The template now skips bulletless
entries.

## Headless Claude subprocesses

`generate-kit` and `/tailor` shell out to the `claude` CLI through
`resume-tailor-service/app/claude_cli.py` (300s timeout, 2 retries).

**The trap:** `~/.claude/settings.json` sets `defaultMode` globally. If it is `plan`, every
subprocess inherits it and returns prose ("I'm in plan mode, so I can only read files...")
instead of the requested output, which surfaces as a confusing JSON-parse error and a 502
at the call site. Nothing in the error mentions plan mode, so it gets debugged in the wrong
file. This silently broke both endpoints for months: 155 dossiers with zero cover letters,
zero fit analyses, zero answers.

Required flags for any headless call:

```
--permission-mode default --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
  --disable-slash-commands --allowedTools ""
```

Plus `--json-schema` when the caller expects JSON, or the model preambles in prose. Do
**not** use `--bare`: it drops auth and fails with "Not logged in". Note that Pydantic
omits any field with a default from a schema's `required` list, so structured decoding will
skip it. Tighten the schema before sending.

Without the isolation flags the subprocess also loads every MCP server and plugin on the
machine, adding roughly 70 startup events and minutes of latency per call.

Covered by `resume-tailor-service/tests/test_claude_cli.py`.

---

## Service operations

The dashboard, tailor, and jobs API are one FastAPI service on `http://127.0.0.1:8420/`,
running under a launchd LaunchAgent so it survives login and crashes:

- Plist: `~/Library/LaunchAgents/com.jobmachine.dashboard.plist`
- Entrypoint: `resume-tailor-service/scripts/serve.sh` (non-interactive). Use
  `scripts/start.sh` for manual runs with the mock sheet.
- `RunAtLoad` plus `KeepAlive`, verified by a `kill -9` respawn test.
- Logs persist to `logs/dashboard.log`, which is gitignored.

Manage it:

```
restart: launchctl kickstart -k gui/$(id -u)/com.jobmachine.dashboard
stop:    launchctl unload ~/Library/LaunchAgents/com.jobmachine.dashboard.plist
start:   launchctl load ~/Library/LaunchAgents/com.jobmachine.dashboard.plist
```

It runs uvicorn **without** `--reload`, so a code change needs the restart above to take
effect. This has cost real debugging time: edits appear to do nothing until you kickstart.

Data persistence is independent: `job_store.py` and `people_store.py` write atomically
(temp file plus `os.replace`) to `resume-tailor-service/data/` (`jobs.json`,
`people.json`), which is gitignored and survives restarts. Back up with
`resume-tailor-service/scripts/backup-job-data.sh`.

The repo lives at `~/job-machine`. It was moved out of `~/Downloads` on 2026-07-29 because
macOS TCC protects that directory and the launchd agent crash-looped there with `Operation
not permitted`. Do not move it back.

## Sheet webhook

The Apps Script `/exec` URL needs the **browser's Google session**. `curl` hits a sign-in
wall. Open the URL in a tab and read the `<pre>` for `{"ok":true}`. URL is in `AGENTS.md`.
