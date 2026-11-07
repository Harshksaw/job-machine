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

## Ego Lite is the apply browser (since 2026-11-07)

Harsh's standing instruction: **use Ego Lite for all job applications.** Job Chrome (CDP
9223) is no longer the apply lane. Run `ego-browser skill` first and follow the guide it
prints (it matches the installed version). Use one named TaskSpace per run and print its
`spaceId`; a space handed to Harsh with `handOff()` becomes his, so start a new name rather
than reusing it.

Why it replaced job Chrome, from the first day on both:

- Ashby reCAPTCHA Enterprise silently held 2 of 4 job Chrome submits (Socure, LangChain):
  no confirmation, no errors, button still there. Ego Lite submits reached Ashby's own
  validation every time and 3 of 3 confirmed (Pylon, Notion AI, plus a validation pass on
  Applied Intuition). Ego pages report `navigator.webdriver === false`.
- Ego Lite carries Harsh's Google session, so the Sheet webhook works from it.
- Wait about 20 seconds on a filled form before clicking Submit; the instant submits were
  the ones that got held.
- Ashby adds required fields only at submit time (Notion pronouns, Applied Intuition
  Education History and immigration case). Read the "needs corrections" list after the
  first submit, fill those, and submit again on the same page.
- `page.fill()` refuses a textarea outside the viewport. Click it first (clicks scroll the
  target into view), then `keyboard.insertText()`.
- Harsh's Ego Lite profile has the **Jobright extension**, which docks a sidebar on job
  pages. With it open, `page.fill()` on Greenhouse fails at random with "element is not
  visible in the viewport" even after `scrollIntoView`. Click the field, then
  `keyboard.insertText()`, which works every time. Leave the extension alone.
- **Greenhouse react-select dropdowns:** the "Country" field next to Phone is the phone
  country code (options read "Canada +1"). Focus the input, `ArrowDown`, type, then
  `Enter`; clicking options fails because the list closes between script rounds. Check
  the result in `[class*=single-value]`. Success lands on `.../jobs/<id>/confirmation`.

## Before any browser session

**Standing rule (corrected 2026-09-02):** `./scripts/start-chrome-debug.sh` (regular
Chrome, default profile) **cannot work** on Chrome 136+. Confirmed again on Chrome 152:
Chrome refuses DevTools Protocol on the default user-data directory for security, it
binds the port and then serves `404` on every `/json/*` endpoint. This was already
found once (see commit `2b31b66`, "regular Chrome cannot work"); a later doc edit
reverted the standing rule back to regular Chrome without re-testing, which broke CDP
again on 2026-09-02. **Default is `./scripts/start-job-chrome.sh`** (isolated profile,
`./browser-profile/`, gitignored). Regular-Chrome attach is not an option until Chrome
changes this policy, not a preference.

**Port collision gotcha:** a stale regular-Chrome process from a previous
`start-chrome-debug.sh` attempt can sit for days still bound to `127.0.0.1:9222`
(IPv4) while serving 404 on everything. If `start-job-chrome.sh` reports CDP not
responding, check `lsof -nP -iTCP:9222 -sTCP:LISTEN` before assuming the new Chrome
failed to start, since your job Chrome may have only won the IPv6 side of that port
(`curl http://[::1]:9222/json/version` to check) and is otherwise fine. Fix by running
job Chrome on a different port rather than touching the stale process:
`JOB_MACHINE_CDP_PORT=9223 ./scripts/start-job-chrome.sh`. Do not kill the process
squatting on 9222 without checking it is not Harsh's actual daily Chrome window first,
`ps -p <pid> -o lstart=` tells you how long it has been running.

**Startup sequence (every session):**

1. `curl -fsS http://127.0.0.1:9222/json/version` (or your last-used port).
2. **If it 200s with real CDP fields (`webSocketDebuggerUrl`, etc.):** attach.
   `export BU_CDP_URL=http://127.0.0.1:9222`.
3. **If it 404s, refuses, or is silent:** run `./scripts/start-job-chrome.sh`. First
   run: sign in to LinkedIn/Wellfound once in that window, it persists in
   `./browser-profile/`. If it reports "CDP not responding," check the port-collision
   gotcha above before retrying blindly.
4. Never run `Cmd+Q`, `osascript` quit, or `killall` against Harsh's actual regular
   Chrome (the one with his tab groups). Job Chrome is a separate process/profile, you
   may start, stop, and restart it freely, it holds no work of his.
5. Cursor: `browser-use --doctor` · Claude Code: `/mcp` → playwright connected.

### Job Chrome: still don't make a mess

It is an isolated profile, but it is not disposable mid-run, other automation may be
sharing it in the same session.

**Silent browser work (standing preference).** Never drag Harsh to the job
Chrome window or tab. Do not call `activate_tab()`, do not bring CDP 9223 to
the foreground, and do not steal focus from whatever he is doing. Keep tabs in
the background: CDP input and screenshots work without activating, and the
launcher starts job Chrome hidden with background throttling off (see
`docs/BROWSER_PROFILE.md`). If a hidden tab still will not respond, stop and
report it rather than activating. CAPTCHA/MFA is the only case for showing it.

**Close only what you opened.** Keep a session list of automation tab target ids
(or the exact `linkedin.com/in/` URLs you opened). After each outreach send, close
**only** that tab. Never close tabs by guessing index or run "close all except."

**Automation tab budget:** max **5 automation tabs** open at once. For outreach, open
one profile tab, send, close it, then open the next. Do not leave `/in/` profile tabs
open after a send.

**Never from automation:**

- `Cmd+Q`, `osascript` quit Chrome, `killall "Google Chrome"` against Harsh's regular
  Chrome (the long-running one with his tab groups, not job Chrome)
- Bulk tab close, "close other tabs", or closing tabs not on your session list
- `activate_tab()` during normal outreach (background is the default)

## Which browser tool (routing)

| Task | Agent | Tool | Preconditions |
|---|---|---|---|
| LinkedIn search, Easy Apply, outreach | Cursor | **browser-use** (`BU_CDP_URL`) | Job Chrome up via `start-job-chrome.sh` |
| Same tasks in Claude Code | Claude Code | **Playwright MCP** (attach via `--cdp-endpoint`) | Job Chrome CDP up |
| LinkedIn iframe / shadow DOM | Claude Code | Playwright MCP | Same CDP attach |
| Sheet webhook confirm | Either | browser-use or Playwright | Google session signed in inside job Chrome |
| Public ATS JD fetch | Either | `curl` (no browser) | None |
| ZipRecruiter apply | Claude Code | Playwright MCP | Job Chrome |

Do **not** use claude-in-chrome or ecc chrome-devtools MCP for job-machine work
unless Harsh explicitly switches stacks. Default lane: job Chrome + browser-use
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
- The invite dialog renders late. Poll up to 10 s for "Add a note", then again for the
  textarea, before treating it as a failure. A one-shot check failed 2 of 3 sends on
  2026-10-12; polling sent 3 of 3 on 2026-10-13.
- Profiles often show a short first name ("Mike" for a stored "Michael"). An identity check
  on the exact first name will stop a correct send; match on surname plus company.

**Never use `main button:has-text("Connect")`.** It also matches "People you may know"
sidebar buttons. On 2026-08-27 that selector sent five unintended note-less invitations
before it was caught, and they had to be withdrawn. Scope any Connect selector strictly to
the profile top card, and after every send verify the target profile shows "Pending" and
that the sent-invitations list shows the right person with the right note. Never batch-send
without per-send verification.

**Layout changes seen 2026-10-24** (7 of 7 sent over raw CDP on the job Chrome):

- The profile has no `h1`. The first line of `main.innerText` is the displayed name, and
  the menu now renders in the light DOM, not `#interop-outlet`.
- 2nd degree: Connect is an `<a>` (not a `button`) on the top card, with
  `aria-label="Invite <Name> to connect"`. The People Also Viewed sidebar uses the same
  label pattern, so match the label **exactly** against the top-card name, never by
  prefix or by `button` text.
- 3rd degree: Connect is a `[role=menuitem]` under the top-card More menu, next to
  "Save to PDF". Poll for the menu to render (up to 8 s); a fixed 2 s wait missed it once.
- LinkedIn may shorten a surname ("Yilun C."). Confirm identity with first name plus the
  company on the top card instead.
- Do not verify by looking for "Pending" on the profile. It no longer shows reliably on
  the top card. Verify on `/mynetwork/invitation-manager/sent/`: the person is at the top
  with the exact note text, and the "People (N)" count rose by one.

Invite cap is 12 per session (`AGENTS.md` rule 3) and every message needs Harsh's approval
before it goes out.

### Outreach send workflow (job Chrome, non-disruptive)

After Harsh approves a batch (`prompts/outreach-run.md` step 4), send at human pace
without touching his other tabs:

1. Confirm CDP on job Chrome (`start-job-chrome.sh`), LinkedIn signed in.
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

Company and people pages (`/company/<slug>`, `/company/<slug>/people`) return a Cloudflare
403 to curl (2026-10-13). Take founders from the JD, YC pages, or web search instead.

---

## YC / Work at a Startup

Discovery is fully public, verified 2026-10-13 with about 500 requests at a 1 to 3 s pace
and no blocks:

- **Company list:** the `/companies` page HTML exposes a public Algolia app id and search
  key, index `YCCompany_production`. Filters such as `isHiring:true AND batch:"Summer 2026"`
  work without login. Batch names are spelled out ("Spring 2026"); short forms are P26, X25.
- **Jobs per company:** `ycombinator.com/companies/<slug>/jobs` embeds every posting as JSON
  in a `data-page` attribute, including visa, experience floor, role type, salary, equity.
- **Job page:** `/companies/<slug>/jobs/<shortId>-<slug>` adds the full JD as markdown and
  any custom application questions.
- **Visa field** has only three values: "US citizen/visa only" (skip for US roles), "Will
  sponsor", "US citizenship/visa not required". It is US-only, so read the JD for Canada.
- **Founders:** the company page has clean founder data plus Launch YC posts. The jobs page
  embeds founders as a Python-style string, sometimes a list, not JSON.

Applying needs a YC account. Apply buttons go to `account.ycombinator.com/authenticate`,
then `workatastartup.com/application?signup_job_id=<numeric id>`. Agents do not create
accounts, so a live, signed-in session from Harsh is required. Some listings apply outside
YC (email with video, Google Form, a coding challenge); the dossier `next_action` says so.

Signed-in flow, verified 2026-10-13 on 15 roles in the job profile:

- Open `workatastartup.com/jobs/<signup_job_id>` directly. The page has one `Apply` or
  `Applied` button; read it first, and never send when it says `Applied`.
- `Apply` opens a `[role=dialog]` titled "Reach out to <founder> at <company>" with one
  textarea (50 character minimum) and a `Send` button. Custom questions add more textareas
  in the same dialog. No resume upload: the YC profile is the application.
- Hidden tab: enable focus emulation, click `Apply` at its rect, focus and select the
  textarea, then `Input.insertText` the note and compare the value before sending.
- Success: the dialog closes and the button flips to `Applied`. A note that "your
  qualifications might not match" is advisory and does not block.
- Failure seen once: an alert "Could not apply to this company. Please contact support if
  this persists." with the button still `Apply`. Treat as ambiguous and do not retry.

Raw CDP run 2026-10-24 (6 of 6 applied, job Chrome): the dialog title reads as an empty
zero-width string, so do not key on it. One textarea means no custom questions. The flip to
`Applied` survived a fresh reload on all six.

**Check the button before trusting the dossier.** aSim already showed `Applied` while its
dossier was still at `discovered` with no applied event, because the earlier submission was
never logged. The button state is the real dedupe gate.

**Dedupe key:** the ycombinator.com job URL. Older dossiers use
`workatastartup.com/jobs/<numeric id>`, the same number as `signup_job_id`, so match both,
and cross-check company plus role because the same role arrives from LinkedIn or Ashby
under a different title.

---

## Remote job boards

`cd resume-tailor-service && uv run python scripts/remote_boards.py --out <file>` pulls all
five boards, filters, dedupes, and writes candidates with full JD text. It never writes to
the dossier store: score each candidate, then capture it. First run 2026-11-06: 764
listings, 203 kept, 49 scored and captured (14 at fit 7 or higher).

Per board, verified 2026-11-06:

| Board | Endpoint | Notes |
|---|---|---|
| Himalayas | `himalayas.app/jobs/api/search?q=&country=Canada&seniority=Entry-level&page=N` | Best source by far (490 of 764). 20 per page. `locationRestrictions` lists the countries a hire may live in; empty means worldwide. |
| Jobicy | `jobicy.com/api/v2/remote-jobs?count=50&geo=canada&industry=engineering` | `jobLevel` is often "Any". |
| Remotive | `remotive.com/api/remote-jobs?category=software-dev` | Small feed, mostly worldwide contract roles. |
| Working Nomads | `workingnomads.com/api/exposed_jobs/` | About 30 recent jobs total; filter on `category_name`. |
| Remote OK | `remoteok.com/api` | Row 0 is the API terms notice; the terms ask that Remote OK be credited as the source. |

- **Remotive and Remote OK return 403 to the bare Python-urllib client.** The script sends
  an honest `job-machine-remote-boards/1.0` user agent, which they accept. Do not
  impersonate a browser.
- **Dedupe on a normalized role.** Board titles drift from the ATS title ("Junior Software
  Engineer" vs "Junior Software Engineer (Remote)"), so the script compares company and
  role with parentheticals and "remote" removed, and reports `company_history` when he
  already applied elsewhere at that company.
- **Noise to expect:** staffing shops posting dozens of generic "developer" roles
  worldwide, per-task AI training gigs, and LATAM-only contractors. The years and flags
  pass (US residency, French, LATAM, contract) is what makes the list scoreable.
- **Himalayas is a discovery source, not an apply route** (2026-11-07). Its "Apply now"
  goes to a Himalayas talent signup, and the API's `applicationLink` points back at
  Himalayas. Find the role on the employer's own board instead: query
  `boards-api.greenhouse.io/v1/boards/<slug>/jobs`, `api.lever.co/v0/postings/<slug>` and
  `api.ashbyhq.com/posting-api/job-board/<slug>` for the company slug, then a web search.
  Of 14 fit 7+ Himalayas roles, 4 resolved this way (Mercury x2, Valtech, Xsolla). The rest
  were stale aggregator copies, recruiter reposts, a senior iCIMS role, or not findable.
  Point the dossier's `job_url` at the employer posting once found.

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

## Background-tab forms (job Chrome stays hidden)

- **Custom dropdowns close instantly** in a hidden tab because the page never has focus
  (seen on BambooHR "Fabric" selects, 2026-10-03). Send
  `Emulation.setFocusEmulationEnabled {enabled: true}` on the tab, then click the toggle
  and the option with real `Input.dispatchMouseEvent` press/release at their rects. JS
  `.click()` does not open them.
- **Type, do not set.** React forms (Ashby, BambooHR, Manatal) can ignore native value
  setters, so Ashby rejected an email set that way. Focus plus `select()`, then
  `Input.insertText`, registers reliably.
- **`scrollIntoView({behavior:'smooth'})` and full-page screenshots can hang** a hidden
  tab. Click without scrolling and capture the viewport only.
- **BambooHR submits can end on a reCAPTCHA** ("Almost there! Please confirm you're not a
  robot"). That needs Harsh. Leave the filled tab open and do not mark it applied.

## Ashby boards

The board SPA resists ref-clicks. Get a role UUID with `javascript_tool`
(`document.querySelectorAll('a')` filtered by title) and navigate directly to
`/<org>/<uuid>/application`. Fields then fill with `form_input` plus `file_upload`.
Comboboxes need click, type, then click the option.

Verified over CDP on 2026-10-07:

- **Upload the resume first** on a fresh page (`DOM.setFileInputFiles` on
  `#_systemfield_resume`) and wait for `ApiSetFormValueToFile`. Uploading after typing
  sometimes leaves a "resume.pdf failed to upload" toast and the submit is rejected.
- **Radios can show checked without being saved.** Ashby only records a radio on a
  change event, so a restored or pre-checked option reads `checked` but fails as
  "Missing entry". Click a different option, then the target. Click the `<input>` itself,
  not its label.
- **Boolean questions** are two buttons with `data-option="yes|no"`, and `aria-pressed`
  confirms the choice.
- **Education History** has a school combobox, plus degree and major inputs and native
  month/year selects. Setting the selects with the native value setter plus `change`
  works. Start date can be left blank.
- **Forms add required questions** that the GraphQL form snapshot did not show, for
  example Superhuman's "willing to relocate". Always read the error list after submit.
- **A cookie banner covers the Submit button.** Click "Necessary Only" first.
- **No confirmation text and no errors is ambiguous.** Do not resubmit. Log it and have
  Harsh check his email.
- **reCAPTCHA Enterprise can hold a background submit silently** (Socure, 2026-11-05). A
  trusted CDP click landed on "Submit Application" (checked with `elementFromPoint`), the
  form stayed put with zero errors, and no confirmation email came. The page carried a
  `recaptcha/enterprise/anchor` iframe. Check for that iframe before submitting: if it is
  there, fill the form and hand the submit to Harsh rather than clicking it and leaving an
  ambiguous state.

---

## Stale postings sweep

`resume-tailor-service/scripts/check_liveness.py <[{id,url}].json> <out.json>` checks
postings on their own site with no browser and no LLM: LinkedIn jobs-guest ("No longer
accepting applications" or 404), Greenhouse and Lever posting APIs (404), the Ashby org
board (id missing), YC job pages (404 or redirect). Wellfound, Indeed and company sites
come back `unknown`. Delete only on `closed`, never on `unknown`, and never delete an
applied dossier: the rule 8 resend gate reads them.

First sweep, 2026-11-07, on 401 unapplied dossiers older than 30 days: 121 closed and
deleted, 81 live, 199 unknown (mostly Wellfound). The LinkedIn guest endpoint answered a
429 at first and then served 1.5 s spaced requests fine. A full backup was taken first in
`session-artifacts/cleanup-2026-11-07/`.

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

**Updating the base resume.** The canonical trio is `harshsaw.tex`, `resume.cls`, and
`resume.pdf` at the repo root. `resume-tailor-service/templates/resume.cls` must be a
byte-identical copy of the root class (a test enforces it), and
`templates/resume_template.tex.jinja` must mirror `harshsaw.tex` section by section. When
Harsh supplies a new resume:

1. Put his source in `harshsaw.tex` with `\documentclass{resume}`, even if he named his
   class differently (the 2026-10 `resume_2.cls` declares itself as `resume`). Remove any
   em dashes (`---`) before compiling.
2. Copy his class over both `resume.cls` copies.
3. Update `resume_bank.yaml` so every bullet, title, and skill on the new resume is in the
   bank. Keep existing IDs, since tests pin them.
4. Mirror any layout change into the Jinja template.
5. From `resume-tailor-service/`, run `uv run python scripts/repin_canonical.py`. It
   rebuilds `resume.pdf` and regenerates `content/canonical_baseline.json`. `--check`
   reports drift without writing. Then run `uv run pytest -q`.
6. Archive the previous PDF under `session-artifacts/resume-archive/`, which is gitignored.

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

**Second trap: a sandboxed agent restarted the service.** On 2026-10-24 every
`generate-kit` call 502'd with `API Error: Couldn't connect through your proxy
(ERR_PROXY_TUNNEL)`. Cursor's agent had restarted uvicorn from its sandbox shell, so the
service and every `claude -p` child inherited `HTTPS_PROXY=http://127.0.0.1:<port>` owned
by `cursorsandbox`, which refuses api.anthropic.com. Check with
`ps eww -p $(lsof -ti tcp:8420 -sTCP:LISTEN) | tr ' ' '\n' | grep -i proxy`. Fix: restart
uvicorn with the `*_proxy` variables unset. Never start the service from inside an agent
sandbox. The launchd plist described below was also missing that day, so nothing was
supervising it.

It recurred on 2026-11-05: uvicorn was again a cursorsandbox child with the proxy set and
no plist. Fix that worked: kill the listener on 8420, then run
`resume-tailor-service/scripts/install-launchd.sh` with the `*_proxy` variables unset, and
confirm the new pid's environment has no proxy entries. Run `install-launchd.sh --check` at
session start.

---

## Dossier database (Neon Postgres, since 2026-11-06)

Dossiers, people and session events live in Neon project `odd-voice-74887748`
(`job-machine-oregon`, aws-us-west-2, branch `main`), one row per document in a
`documents` table (`app/doc_store.py`). `resume-tailor-service/.env` holds
`DATABASE_URL` and `DATABASE_URL_UNPOOLED` (written by `neon deploy`, gitignored); the
service prefers the unpooled URL. Without either variable it falls back to JSON files in
`data/`, which would start empty: the pre-migration JSON store was archived and removed on
2026-11-07 (`session-artifacts/cleanup-2026-11-07/`). If the dashboard ever shows zero
dossiers, check that `.env` still has the database URLs before anything else.

- **Always go through the API.** Never write to the database directly.
- **Region matters.** The first project was created in Sydney (341 ms round trip from
  Kelowna): the Inbox took 2.5 s and each save about 1 s. Oregon is 0.5 s and 0.2 s.
  Neon cannot move a project, so a wrong region means a new project plus
  `scripts/migrate_to_db.py` (idempotent, verifies counts).
- **Tests never touch Neon.** `tests/conftest.py` strips the database variables that
  `load_dotenv()` would load; the SQL path is tested on SQLite.
- **Login:** `neon login` times out after 60 s. If an agent starts it, hand the link to
  Harsh immediately, or have him run `! neon login` himself.

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

Chrome's built-in JSON viewer can wrap the response so the `<pre>` is not found. Read
`document.body.innerText` instead. Never reload the URL to re-check: the webhook appends a
row on every load, so a reload creates a duplicate.
