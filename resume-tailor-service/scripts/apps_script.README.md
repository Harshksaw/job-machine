# Job Machine — Apps Script read-mode redeploy guide

`apps_script.gs` in this folder is a drop-in replacement for the `doGet(e)`
function in your job-application-log Google Sheet's bound Apps Script
project. It keeps the existing append/log webhook working exactly as-is, and
adds a new, secret-guarded read action for the dashboard to consume.

## What it does

**Append (unchanged, no secret required)**

```
GET /exec?company=&role=&source=&jobUrl=&status=&fit=&people=&hooks=&outreach=&notes=
```

Appends one row to the sheet, returns `{"ok":true}`. This is the exact
contract from CLAUDE.md's logging instructions — params, order, and return
shape are untouched.

**Read (new, secret-guarded)**

```
GET /exec?action=read&secret=YOUR_SECRET
```

Reads every data row in the sheet, maps columns by **header name** (not
fixed column position), and returns:

```json
{
  "ok": true,
  "rows": [
    {
      "company": "...", "role": "...", "source": "...", "jobUrl": "...",
      "status": "...", "fit": "...", "people": "...", "hooks": "...",
      "outreach": "...", "notes": "...", "timestamp": "..."
    }
  ]
}
```

If `secret` is missing, wrong, or no `READ_SECRET` has been configured yet,
it returns `{"ok":false}` and never reads the sheet.

## Redeploy steps

1. **Back up first.** Open the existing Apps Script project from the Sheet
   (`Extensions > Apps Script`) and copy the current code somewhere safe
   before overwriting it.

2. **Verify your sheet's headers.** Open row 1 of the log sheet and confirm
   there's a header cell for each of: `company`, `role`, `source`, `jobUrl`,
   `status`, `fit`, `people`, `hooks`, `outreach`, `notes`, `timestamp`.
   - Matching is case-insensitive and ignores spaces/underscores/hyphens, so
     `Job URL`, `job_url`, and `jobUrl` are all treated the same.
   - A handful of common alternate spellings are already handled via the
     `HEADER_ALIASES` object at the top of `apps_script.gs` (e.g.
     `Position`/`Title` → `role`, `URL`/`Link` → `jobUrl`, `Date` →
     `timestamp`).
   - If a header in your sheet doesn't match anything, that field comes
     back as `""` for every row. Fix this by either renaming the header
     cell to match, or by adding your header's normalized text (lowercase,
     spaces/underscores/hyphens stripped) as a new key in `HEADER_ALIASES`.

3. **Verify append column order.** The append path writes columns in this
   order: `company, role, source, jobUrl, status, fit, people, hooks,
   outreach, notes`, then a timestamp as the last column — matching the
   query-param order in the webhook URL. If your sheet's actual column
   order differs, either reorder the sheet's columns to match, or edit the
   array passed to `appendRow(...)` inside `handleAppend_()`.

4. **Paste `apps_script.gs`'s contents** over the existing script, replacing
   the current `doGet` (and everything else in the file).

5. **Set the read secret** — pick one:
   - **Preferred:** in the Apps Script editor, gear icon → **Project
     Settings** → **Script Properties** → **Add script property** → key
     `READ_SECRET`, value = a long random string.
   - **Alternative:** temporarily set the `secret` variable inside the
     `setReadSecret()` function near the bottom of the file, select
     `setReadSecret` from the function dropdown, click **Run** once
     (authorize if prompted), then blank out the value you typed so it
     isn't left sitting in source.

   Never commit the real secret value into this file or into version
   control. Never log it — the script does not log request params, keep it
   that way.

6. **Redeploy as a NEW VERSION of the existing deployment** so the `/exec`
   URL is preserved (other tooling already points at it):
   `Deploy` → `Manage deployments` → pencil (edit) icon on the existing Web
   App deployment → Version: **New version** → **Deploy**.
   Do **not** use "New deployment" — that creates a different `/exec` URL.

7. **Smoke test:**

   ```bash
   # Append still works (existing behavior)
   curl "https://script.google.com/macros/s/AKfycbz.../exec?company=Test&role=SWE&source=test&jobUrl=&status=applied&fit=8&people=&hooks=&outreach=&notes="
   # -> {"ok":true}, new row appended

   # Read without a secret
   curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read"
   # -> {"ok":false}

   # Read with the wrong secret
   curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read&secret=wrong"
   # -> {"ok":false}

   # Read with the correct secret
   curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read&secret=YOUR_SECRET"
   # -> {"ok":true,"rows":[...]}
   ```

## Notes / assumptions

- The original `doGet` source wasn't available in this repo, so the append
  path was reconstructed from the documented webhook contract (query params
  and `{"ok":true}` return) in the project's `CLAUDE.md`. Column order and
  "append to the active sheet" are best-effort assumptions — verify them
  against your actual sheet before relying on it in production.
- Both `handleAppend_` and `handleRead_` operate on
  `SpreadsheetApp.getActiveSpreadsheet().getActiveSheet()` — i.e. whichever
  tab was last active in the UI, not necessarily a fixed tab name. If your
  spreadsheet has multiple tabs, replace `getActiveSheet()` with
  `getSheetByName('YourTabName')` in both functions so appends and reads
  consistently target the same tab regardless of which tab a human last had
  open.
