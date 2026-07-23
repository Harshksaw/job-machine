# Job Machine — Command Center Dashboard (over resume-tailor-service)

Add a single-user, same-origin web dashboard to `resume-tailor-service` that
joins the Google-Sheet application log with the locally-generated tailored
resumes, so I can see the pipeline and inspect each tailored PDF beside its
JD + the exact bank content that was selected.

## Architecture

```
FastAPI process (one origin, no CORS):
  ├─ app/sheets.py     ──httpx──► Google Apps Script ?action=read → rows JSON
  ├─ app/dashboard.py  joins rows ⇄ output/<dir>/meta.json by (company, role)
  ├─ output/<slug>-<hex>/  meta.json (NEW: jd_text, manifest, pages, created_at) + resume.pdf
  └─ app/bank.py       resume_bank.yaml → bullet-id → text resolution
```

- Same-origin (UI + API from one FastAPI process) → no CORS.
- Apps Script URL/secret stay server-side in `.env`; the browser never sees them.
- Join key: normalized `(company, role)` — identical to how the output slug is
  derived (`_safe_slug`). `jobUrl` recorded as a stronger key when present.

## Global Constraints (bind every task)

- **Auth:** all `/api/*` routes sit behind the existing `verify_token`
  (`Authorization: Bearer <RESUME_TAILOR_TOKEN>`). Browser-loaded binary
  resources (the PDF) are fetched by the frontend via authenticated `fetch()`
  and rendered from a blob URL — the token is NEVER placed in a URL/query string.
- **Secrets server-side only:** `APPS_SCRIPT_URL` and `APPS_SCRIPT_READ_SECRET`
  live in `.env`, are read only in `app/sheets.py`, and are never serialized to
  any API response or the browser.
- **Read-only MVP:** no status write-back, no drag-to-change-status, no funnel
  analytics, no outreach write endpoint. Display only.
- **Fidelity:** the UI resolves manifest bullet IDs → text strictly from
  `resume_bank.yaml` via `app/bank.py`. It renders real bank text verbatim and
  never invents content.
- **Join semantics:** normalize `(company, role)` with the SAME slug function
  used to build the output dir. Tolerate output dirs that have no `meta.json`
  (skip them). On multiple matches for one `(company, role)`, the most recent
  `created_at` wins.
- **Reuse, don't rewrite:** `app/bank.py::load_bank`, `app/auth.py::verify_token`,
  and the slug function. Extract the slug function to `app/slug.py` so both
  `main.py` and `dashboard.py` import it (avoids a circular import).
- **Stack:** backend FastAPI + `httpx` (sync client, matches the sync
  endpoints). Frontend Vite + React + TypeScript + Tailwind + `lucide-react`,
  building to `app/static/`.
- **Dev proxy:** Vite dev server proxies `/api` and `/health` → `http://localhost:8420`.
- All work happens on branch `worktree-resume-tailor-service` at
  `resume-tailor-service/`. No merge to main until the whole feature is done and
  reviewed (finishing-a-development-branch handles that at the end).

## Interfaces this feature integrates with (current code)

- `app/models.py`: `TailorRequest{jd_text,company,role}`,
  `Manifest{summary, job_selections:[{job_id,bullet_ids}],
  project_selections:[{project_id,bullet_ids}], achievement_ids,
  job_trim_priority}`, `TailorResponse{pdf_path,manifest,pages}`.
- `app/main.py`: `POST /tailor` (sync) already renders and returns
  `render.render_and_fit(...) -> (pdf_path, final_manifest, pages)`;
  `work_dir = OUTPUT_DIR / f"{slug}-{uuid4().hex[:8]}"`, `pdf_path` is
  `work_dir/resume.pdf`. `_safe_slug(company, role)` currently lives here.
- `app/bank.py`: `load_bank(path) -> ResumeBank` with `.jobs[].bullets[]`,
  `.projects[].bullets[]`, `.achievements[]` (each `Bullet{id,text}`), `.skills[]`.
- `app/auth.py`: `verify_token(authorization: Header) -> None`.
- Tests use FastAPI `TestClient` (`httpx`) + `pytest`.

## Task 1 — Apps Script read-mode (user redeploys)

Create `resume-tailor-service/scripts/apps_script.gs`: a replacement `doGet(e)`
that keeps the existing append/log behavior unchanged, and adds
`?action=read&secret=…` → reads the sheet (header-aware column mapping) and
returns `{ok:true, rows:[{company, role, source, jobUrl, status, fit, people,
hooks, outreach, notes, timestamp}, …]}`. Guard reads with a shared secret
param (constant-time compare where possible; reject on mismatch with
`{ok:false}`). The append path must remain byte-for-byte compatible with the
current webhook contract (the CLAUDE.md logging URL). Provide copy-paste +
redeploy instructions as a top-of-file comment or a sibling `.md`: edit the
EXISTING deployment as a NEW version so the `/exec` URL is preserved.

**Flag for the user:** verify the sheet's column headers match the field names
the read mapping expects; the instructions must tell the user how to check.

No pytest (this is Google Apps Script the user deploys). Reviewer checks the
`.gs` logic by reading: both actions handled, secret guard correct, append
unchanged, header-aware mapping, instructions present.

## Task 2 — Persist manifest + metadata on every /tailor

Add `TailoredResumeMeta` to `app/models.py`:
`{company, role, jd_text, pdf_path, manifest: Manifest, pages: int,
created_at: str (ISO-8601 UTC), job_url: str | None = None}`.

In the `POST /tailor` handler (`app/main.py`), after a successful
`render_and_fit`, write `output/<dir>/meta.json` containing that model
(`model_dump`, UTF-8, indented). The filesystem is the tailored-resume index —
no DB. `created_at` is generated at write time. Writing meta.json must not
change the `/tailor` HTTP response shape.

**TDD:** extend the `/tailor` test so that after a successful call,
`meta.json` exists in the new work dir and round-trips into `TailoredResumeMeta`
with the request's company/role/jd_text and the returned manifest/pages.

## Task 3 — Backend dashboard API

First extract `_safe_slug` from `app/main.py` into `app/slug.py`
(`def safe_slug(company: str, role: str) -> str`), update `main.py` to import it.
Behavior must be identical (keep a test).

- `app/sheets.py` (new): a sync `httpx` client that GETs the Apps Script read
  endpoint (`APPS_SCRIPT_URL`, `APPS_SCRIPT_READ_SECRET` from env), validates
  `ok:true`, and normalizes rows into an `Application` Pydantic model
  (`app/models.py`). On network error / `ok:false`, raise a typed error the
  router turns into a clean 502 (never leak the secret/URL in the message).
- `app/models.py`: add `Application{company, role, source, job_url, status,
  fit, people, hooks, outreach, notes, timestamp, tailored_resume_id: str|None}`.
- `app/dashboard.py` (new, `APIRouter`, all routes `Depends(verify_token)`):
  - `GET /api/applications` → sheet rows joined to `output/*/meta.json` by
    normalized `(company, role)` (tolerate dirs without meta.json; most recent
    `created_at` wins). `tailored_resume_id` = the matching output dir name.
  - `GET /api/tailored/{id}` → that dir's `meta.json` (manifest, jd_text, pages).
    Reject ids containing path separators / `..` (no traversal).
  - `GET /api/tailored/{id}/pdf` → `FileResponse` streaming `resume.pdf`
    (media type `application/pdf`). Same id validation.
  - `GET /api/resume-bank` → bank jobs/projects/bullets/achievements text
    (reuse `load_bank`) so the UI resolves manifest IDs → text.
- Move `httpx` from the dev group to runtime `dependencies` in `pyproject.toml`.
- Add `APPS_SCRIPT_URL` + `APPS_SCRIPT_READ_SECRET` to `.env.example`.

**TDD:** `tests/test_sheets.py` (mock the Apps Script HTTP call → normalized
rows; error path → typed error) and `tests/test_dashboard.py` (join logic incl.
no-meta and collision cases; `/api/tailored/{id}` reads meta.json; PDF streams
with correct content-type; id-traversal rejected; auth gate returns 401 without
token). Use `TestClient` + monkeypatched sheets fetch.

## Task 4 — Frontend (Vite + React + TS + Tailwind + lucide-react)

New Vite app at `resume-tailor-service/dashboard/`, building to
`resume-tailor-service/app/static/`. Token entered once, stored in
`localStorage`, sent as `Authorization: Bearer` on every `/api` fetch.

- **Applications Board:** fetch `/api/applications`; Kanban columns by `status`
  with a table toggle. Card = company, role, fit badge, `jobUrl` link, and a
  "PDF ✓" indicator when a tailored resume is joined. Click → open Inspector.
  Read-only (no drag-to-change-status in MVP).
- **Resume Inspector (side-by-side):** left = parsed JD text + "Manifest Bullets
  Selected" (resolve manifest bullet IDs → text via `/api/resume-bank`) + the
  summary line + a page-count badge; right = the tailored PDF. Fetch the PDF via
  authenticated `fetch()` → blob URL → `<iframe>` (NOT `src="/api/.../pdf"`
  directly — the iframe can't send the bearer header). Below: mined contacts for
  that row (from the Sheet `people`/`hooks` columns), read-only.
- **Vite dev proxy:** `/api` and `/health` → `http://localhost:8420`.
- Handle the un-authed / bad-token state (prompt for token; 401 → re-prompt).

Design: clean, legible, dark-mode-friendly command-center feel; no charts in MVP.

## Task 5 — Serve UI from FastAPI

In `app/main.py`, include the `dashboard.py` router, and mount `StaticFiles`
to serve the built `app/static/` at `/` with an SPA fallback to `index.html`,
keeping `/api/*`, `/health`, and `/tailor` intact and taking precedence over
the static catch-all. Decide and document whether built `app/static/` assets
are committed (so Docker/VPS serves the UI without a node build stage) or
gitignored; default to committing the built assets for this single-user tool
and gitignoring `dashboard/node_modules` and Vite caches.

## Task 6 — Test audit + gap-fill

Tasks 2 and 3 write their tests via TDD. This task audits total coverage and
fills any gap: confirm `test_sheets.py` (mock fetch → normalized rows, error
path), `test_dashboard.py` (join incl. no-meta + collision, meta.json read, PDF
stream + content-type, id-traversal rejection, auth gate), and the extended
`/tailor` meta.json assertion all exist and assert real behavior. Add whatever
is missing. Run `uv run pytest -v` — all existing + new tests pass, output
pristine.

## Verification (end-to-end, at the end)

1. `uv run pytest -v` — all existing + new tests pass.
2. Start service; generate 1–2 tailored resumes (smoke_test / real POST) →
   confirm `output/<dir>/meta.json` now exists.
3. User redeploys the updated Apps Script; `curl "<APPS_SCRIPT_URL>?action=read&secret=…"`
   returns rows JSON.
4. `npm run build` in `dashboard/`; reload `http://localhost:8420/` → board lists
   Sheet rows with fit/status; a card with a generated PDF shows "PDF ✓".
5. Open that card → Inspector shows JD text, resolved manifest bullets, the
   summary, and the embedded one-page PDF. Screenshot via browser MCP.

## Deferred (post-MVP)

Outreach approval station (needs a write-back `/api/log` endpoint hitting the
webhook append), funnel analytics, and drag-to-change-status on the board.
