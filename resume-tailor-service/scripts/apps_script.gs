/**
 * Job Machine — job-application log Web App (Google Apps Script)
 * =================================================================
 *
 * This script is bound to the job-application-log Google Sheet and is
 * published as a Web App. It handles TWO actions via doGet(e):
 *
 *   1. APPEND (default / unchanged) — the existing webhook contract used by
 *      CLAUDE.md's logging instructions:
 *        GET /exec?company=&role=&source=&jobUrl=&status=&fit=&people=&hooks=&outreach=&notes=
 *      Appends one row to the sheet and returns {"ok":true}. No secret
 *      required — do not change this path's params or return shape, other
 *      tooling depends on it exactly as-is.
 *
 *   2. READ (new, secret-guarded) —
 *        GET /exec?action=read&secret=YOUR_SECRET
 *      Reads the whole sheet, maps columns by HEADER NAME (not fixed
 *      column position), and returns:
 *        {"ok":true,"rows":[{"company":...,"role":...,"source":...,
 *          "jobUrl":...,"status":...,"fit":...,"people":...,"hooks":...,
 *          "outreach":...,"notes":...,"timestamp":...}, ...]}
 *      If the secret is missing, wrong, or not yet configured, it returns
 *      {"ok":false} and never touches the sheet.
 *
 * -----------------------------------------------------------------
 * REDEPLOY INSTRUCTIONS (read before pasting this in)
 * -----------------------------------------------------------------
 * 1. BACK UP first. Open your existing Apps Script project (from the Sheet:
 *    Extensions > Apps Script) and copy/save the current doGet code
 *    somewhere before you overwrite it, in case you need to roll back.
 *
 * 2. VERIFY YOUR SHEET'S HEADERS before relying on the read path. Open row 1
 *    of the log sheet and check it has header cells for: company, role,
 *    source, jobUrl, status, fit, people, hooks, outreach, notes, timestamp.
 *      - Matching is case-insensitive and ignores spaces/underscores/hyphens,
 *        so "Job URL", "job_url", and "jobUrl" all match the jobUrl field.
 *      - A few common alternate spellings are already mapped for you in the
 *        HEADER_ALIASES object below (e.g. "Position"/"Title" -> role,
 *        "URL"/"Link" -> jobUrl, "Date" -> timestamp).
 *      - If one of your headers doesn't match anything, that column will
 *        come back as "" (empty string) for every row in the read output.
 *        Fix it by either renaming the header cell in row 1 to match, or by
 *        adding your header's normalized text as a new key in
 *        HEADER_ALIASES below (see comments on that object).
 *
 * 3. VERIFY APPEND COLUMN ORDER. This script appends columns in the order
 *    company, role, source, jobUrl, status, fit, people, hooks, outreach,
 *    notes, then a timestamp as the last column — matching the query-param
 *    order in the CLAUDE.md webhook URL. If your sheet's actual columns are
 *    in a different order, either reorder the sheet's columns to match, or
 *    edit the array inside appendRow(...) in handleAppend_() to match your
 *    sheet.
 *
 * 4. PASTE this entire file over your existing script's contents (replace
 *    everything in the Code.gs / doGet file).
 *
 * 5. SET THE READ SECRET (pick ONE way — never commit the real secret value
 *    into this file or into version control):
 *      a. Preferred: in the Apps Script editor, click the gear icon
 *         "Project Settings" > scroll to "Script Properties" > "Add script
 *         property" > key = READ_SECRET, value = a long random string.
 *      b. Alternative: temporarily edit the `secret` variable inside the
 *         setReadSecret() function near the bottom of this file, select
 *         setReadSecret from the function dropdown at the top of the
 *         editor, click Run once (authorize if prompted), then delete/blank
 *         out the value you typed so it isn't left sitting in the source.
 *    The dashboard (or curl) must send this same value as ?secret=... .
 *    Never log this value — this script does not log request params
 *    anywhere; keep it that way.
 *
 * 6. REDEPLOY AS A NEW VERSION OF THE EXISTING DEPLOYMENT so the /exec URL
 *    does not change (any other tooling/webhook already points at it):
 *      Deploy > Manage deployments > click the pencil (edit) icon on the
 *      existing Web App deployment > Version: "New version" > Deploy.
 *      Do NOT use "New deployment" — that mints a different /exec URL.
 *
 * 7. SMOKE TEST after redeploying:
 *      - Append still works (existing behavior):
 *        curl "https://script.google.com/macros/s/AKfycbz.../exec?company=Test&role=SWE&source=test&jobUrl=&status=applied&fit=8&people=&hooks=&outreach=&notes="
 *        -> expect {"ok":true} and a new row in the sheet.
 *      - Read without a secret:
 *        curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read"
 *        -> expect {"ok":false}
 *      - Read with the wrong secret:
 *        curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read&secret=wrong"
 *        -> expect {"ok":false}
 *      - Read with the correct secret:
 *        curl "https://script.google.com/macros/s/AKfycbz.../exec?action=read&secret=YOUR_SECRET"
 *        -> expect {"ok":true,"rows":[...]}
 *
 * See also: resume-tailor-service/scripts/apps_script.README.md for the same
 * instructions in a more readable format.
 * -----------------------------------------------------------------
 */

// Canonical fields returned by the read action, in output order.
var READ_FIELDS = [
  'company', 'role', 'source', 'jobUrl', 'status',
  'fit', 'people', 'hooks', 'outreach', 'notes', 'timestamp'
];

// Maps a NORMALIZED header cell (lowercased, spaces/underscores/hyphens
// stripped) to the canonical field name it represents. Add more entries
// here if your sheet's header row uses different wording — the key is what
// your header becomes after normalization, the value must be one of the
// canonical field names in READ_FIELDS above.
var HEADER_ALIASES = {
  'company': 'company',
  'role': 'role',
  'position': 'role',
  'title': 'role',
  'jobtitle': 'role',
  'source': 'source',
  'joburl': 'jobUrl',
  'url': 'jobUrl',
  'link': 'jobUrl',
  'jobposting': 'jobUrl',
  'status': 'status',
  'fit': 'fit',
  'fitscore': 'fit',
  'people': 'people',
  'hooks': 'hooks',
  'outreach': 'outreach',
  'notes': 'notes',
  'timestamp': 'timestamp',
  'date': 'timestamp',
  'loggedat': 'timestamp',
  'createdat': 'timestamp'
};

function doGet(e) {
  var params = (e && e.parameter) || {};

  if (params.action === 'read') {
    return handleRead_(params);
  }

  return handleAppend_(params);
}

/**
 * Existing append/log behavior — UNCHANGED contract.
 * Expects: company, role, source, jobUrl, status, fit, people, hooks,
 * outreach, notes as query params. No secret required. Returns {"ok":true}.
 */
function handleAppend_(params) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();

  sheet.appendRow([
    params.company || '',
    params.role || '',
    params.source || '',
    params.jobUrl || '',
    params.status || '',
    params.fit || '',
    params.people || '',
    params.hooks || '',
    params.outreach || '',
    params.notes || '',
    new Date()
  ]);

  return jsonOutput_({ ok: true });
}

/**
 * New read action, guarded by a shared secret. Returns {"ok":false} and
 * never reads the sheet if the secret is missing, wrong, or unconfigured.
 */
function handleRead_(params) {
  var providedSecret = params.secret || '';
  var expectedSecret = PropertiesService.getScriptProperties().getProperty('READ_SECRET') || '';

  if (expectedSecret === '' || !secretsMatch_(providedSecret, expectedSecret)) {
    return jsonOutput_({ ok: false });
  }

  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var values = sheet.getDataRange().getValues();

  if (values.length === 0) {
    return jsonOutput_({ ok: true, rows: [] });
  }

  var headerRow = values[0];
  var colIndexByField = {}; // canonical field name -> column index
  for (var c = 0; c < headerRow.length; c++) {
    var normalized = normalizeHeader_(headerRow[c]);
    var field = HEADER_ALIASES[normalized];
    if (field && !(field in colIndexByField)) {
      colIndexByField[field] = c;
    }
  }

  var rows = [];
  for (var r = 1; r < values.length; r++) {
    var raw = values[r];
    if (isBlankRow_(raw)) continue;

    var row = {};
    for (var i = 0; i < READ_FIELDS.length; i++) {
      var fieldName = READ_FIELDS[i];
      var idx = colIndexByField[fieldName];
      row[fieldName] = (idx === undefined) ? '' : formatCell_(raw[idx]);
    }
    rows.push(row);
  }

  return jsonOutput_({ ok: true, rows: rows });
}

// Normalizes a header cell for comparison: lowercase, strip spaces,
// underscores and hyphens. "Job URL", "job_url", "jobUrl" all become
// "joburl".
function normalizeHeader_(headerCell) {
  return String(headerCell || '')
    .toLowerCase()
    .replace(/[\s_\-]+/g, '');
}

function isBlankRow_(raw) {
  for (var i = 0; i < raw.length; i++) {
    if (String(raw[i]).trim() !== '') return false;
  }
  return true;
}

function formatCell_(cell) {
  if (Object.prototype.toString.call(cell) === '[object Date]') {
    return cell.toISOString();
  }
  return cell;
}

/**
 * Defensive string equality: always walks the full length of both strings
 * (no early return on first mismatch) so comparison time does not vary with
 * how many leading characters match. Apps Script/V8 has no crypto-grade
 * constant-time compare primitive, so this is a best-effort mitigation, not
 * a cryptographic guarantee.
 */
function secretsMatch_(a, b) {
  var maxLen = Math.max(a.length, b.length);
  var diff = (a.length === b.length) ? 0 : 1;
  for (var i = 0; i < maxLen; i++) {
    var charA = i < a.length ? a.charCodeAt(i) : 0;
    var charB = i < b.length ? b.charCodeAt(i) : 0;
    diff |= (charA ^ charB);
  }
  return diff === 0;
}

function jsonOutput_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * One-time setup helper (alternative to setting the Script Property by
 * hand): select this function in the editor's function dropdown, click
 * Run, authorize if prompted, then blank out the value below so the real
 * secret isn't left in the source. Prefer setting the READ_SECRET Script
 * Property directly via Project Settings instead (see instructions above).
 */
function setReadSecret() {
  var secret = 'REPLACE_WITH_A_LONG_RANDOM_SECRET';
  PropertiesService.getScriptProperties().setProperty('READ_SECRET', secret);
}
