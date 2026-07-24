# People / Outreach Hub + Local-Only Simplification — Design

Date: 2026-07-23
Status: Approved by user.

## Background

The Command Center dashboard (over `resume-tailor-service`) reads the
Google-Sheet application log and shows, per job, a read-only "Mined Contacts"
panel that prints the sheet's free-text `people` / `hooks` / `outreach` columns
verbatim (e.g. `people = "CTO, Eng Lead"`). There is no structured record of a
person, no clickable profile link (a name like "CTO" is not reachable), and no
single place listing everyone worth contacting across all companies. The
original dashboard plan deferred this as the "Outreach approval station".

Separately, the service currently gates `/tailor` and every `/api/*` route
behind a shared-secret bearer token (`RESUME_TAILOR_TOKEN`). The user runs this
tool **only locally** and wants that friction gone.

## Scope — three workstreams in one plan

1. **Remove auth** — the service is local-only; drop the bearer token entirely
   and rely on a loopback (`127.0.0.1`) bind as the security boundary.
2. **One start script** — a single command that boots everything (mock sheet +
   API) and tears it down cleanly, so it is easy to run and maintain.
3. **People / Outreach Hub** — the feature: a central, editable list of people
   to reach out to, surfaced per-job.

## Goal

A **People / Outreach Hub** in the dashboard: a single, editable, central list
of people to reach out to — each with a LinkedIn link plus any number of extra
profile links, an outreach status, a saved hook/message, and an optional tie to
a specific company+role listing — and each company's people surfaced inside that
job's inspector. The dashboard becomes writable for people records (create /
edit / delete). All of this runs with no auth on a localhost-bound service,
started by one script.

## Non-goals (YAGNI)

- No reminders, scheduling, or notifications.
- No email/DM sending from the dashboard (drafting/approval stays with the user
  per CLAUDE.md; the hub only *stores* the message text).
- No auto-parsing of existing free-text `people` cells into structured records —
  that text is unreliable to split; the raw string stays visible as a fallback.
- No analytics/funnel beyond the StatsHeader the user already built, no external
  DB, no multi-user.
- Application (job) rows stay sheet-backed and read-only — only *people* are
  writable.

---

## Workstream 1 — Remove auth (local-only)

Drop the bearer token from the whole service. The **only** protection becomes
the loopback bind (`--host 127.0.0.1`), which the start script sets explicitly.

**Security note (documented in README):** this is safe for local use only. Re-add
the token dependency before any VPS / port-forwarded / networked deployment —
the Docker/compose files stay in the repo but are flagged as insecure-without-auth.

Changes:
- **`app/auth.py`** — delete `verify_token` (or reduce the module to nothing).
- **`app/main.py`** — `POST /tailor` drops `_auth: None = Depends(verify_token)`
  and the import.
- **`app/dashboard.py`** — `APIRouter(dependencies=[Depends(verify_token)])`
  becomes a plain `APIRouter()`; drop the import.
- **`app/people.py`** (new, workstream 3) — no auth dependency from the start.
- **`.env` / `.env.example`** — `RESUME_TAILOR_TOKEN` is no longer required
  (leave `APPS_SCRIPT_URL` / `APPS_SCRIPT_READ_SECRET` — the sheet read still
  uses them). Remove the token line and its comments.
- **`scripts/smoke_test.py`** — drop the `Authorization` header / token env read.
- **`README.md`** — remove the "fill in RESUME_TAILOR_TOKEN" setup step; add the
  local-only / re-add-auth-for-VPS caveat.
- **Frontend** — remove the token gate entirely (see workstream 3 frontend):
  delete `TokenScreen.tsx`; strip token/`Authorization` handling from `api.ts`
  (`getToken`/`setToken`/`clearToken`/`UNAUTHORIZED_EVENT`) so requests are plain
  `fetch`; remove token state + sign-out/401 handling from `App.tsx`. The app
  loads straight to the board.
- **Simplification unlocked:** the Inspector can render the PDF directly with
  `<iframe src="/api/tailored/{id}/pdf">` (no bearer means no blob-URL dance) —
  optional cleanup, do it since it removes code.
- **Tests** — remove/adjust every auth-gate assertion (401-without-token cases in
  `test_dashboard.py` and elsewhere); the remaining tests call routes with no
  auth. New people tests are authless from the start.

## Workstream 2 — One start script

Promote the local mock sheet server into the repo and add a single entrypoint.

- **`scripts/mock_sheet.py`** — move the stand-in Apps Script read server (GET
  `/exec?action=read` → `{ok:true, rows:[…]}`) into the repo (it currently lives
  in a scratchpad). Serves representative rows for local dashboard rendering.
- **`scripts/start.sh`** — the one command:
  1. `uv sync` (idempotent).
  2. If `APPS_SCRIPT_URL` points at `localhost`/`127.0.0.1`, start
     `mock_sheet.py` on that URL's port in the background.
  3. Start `uv run uvicorn app.main:app --host 127.0.0.1 --port 8420`.
  4. `trap` on INT/TERM to kill the mock when the API stops (clean teardown of
     both from one Ctrl-C).
  - Optional `--build` flag runs `npm run build` in `dashboard/` first.
- **`README.md`** — document `./scripts/start.sh` as *the* way to run locally.

## Workstream 3 — People / Outreach Hub

### Data model — `Person` (added to `app/models.py`, Pydantic v2)

| field         | type                 | notes                                                    |
|---------------|----------------------|----------------------------------------------------------|
| `id`          | `str`                | server-generated, url-safe (`uuid4().hex`); client never sets it |
| `name`        | `str`                | required, non-empty                                      |
| `title`       | `str = ""`           | their role, e.g. "Engineering Manager"                   |
| `company`     | `str`                | required — the join key to applications                  |
| `role`        | `str \| None = None` | optional — ties the person to an exact company+role listing |
| `linkedin_url`| `str = ""`           | primary profile link                                     |
| `links`       | `list[Link] = []`    | extra profiles; `Link{label: str, url: str}`             |
| `status`      | `str`                | one of `to-reach \| queued \| sent \| replied \| skip` (default `to-reach`) |
| `hook`        | `str = ""`           | the angle for the outreach                               |
| `message`     | `str = ""`           | drafted / sent outreach text                             |
| `notes`       | `str = ""`           | free notes                                               |
| `created_at`  | `str`                | ISO-8601 UTC, set on create                              |
| `updated_at`  | `str`                | ISO-8601 UTC, set on every write                         |

Write payloads use a `PersonInput` model (all of the above **except** `id` /
`created_at` / `updated_at`, which the server owns). Status validated against the
fixed vocabulary → `422` on unknown; blank `name`/`company` → `422`.

### Backend — `app/people.py` (new `APIRouter`, no auth)

```
GET    /api/people                 → list[Person]   (optional ?company= exact-normalized filter)
POST   /api/people   PersonInput   → Person   201   (server assigns id + timestamps)
PUT    /api/people/{id} PersonInput→ Person   200   (404 if id unknown)
DELETE /api/people/{id}            → 204            (404 if id unknown)
```

- `id` path param validated with the same `[A-Za-z0-9._-]+`, no-`..` guard style
  in `dashboard.py::_resolve_dir` (defense in depth even without paths).
- Clean fixed error messages; no internals leaked.

### Storage — `app/people_store.py`

- Backed by `data/people.json` (new gitignored `data/` dir — personal runtime
  data, like `output/`). Missing file → empty list.
- `load_people()`, `add_person(input) -> Person`, `update_person(id, input)`,
  `delete_person(id) -> bool`, `get_person(id)`.
- **Atomic writes**: temp file in the same dir + `os.replace`, so an interrupted
  write can't corrupt the store. A module-level `threading.Lock` guards the
  read-modify-write cycle (sync endpoints run in a threadpool).
- Store path module-level so tests point it at a temp dir.

### Frontend — two surfaces, joined by company

Rebuilt Vite/React/TS/Tailwind SPA; output committed to `app/static/`. Written
against the **current** `App.tsx` (default view **Table**; a Table/Board toggle
group; a `StatsHeader` + `FilterBar` layer; richer `api.ts`).

- **New third view.** Extend `type View = "board" | "table" | "people"` and add a
  **People** button to the existing header toggle group. When `view === "people"`,
  render the People hub in place of the applications `StatsHeader`/`FilterBar`/
  table block (the hub has its own search + status filter).
- **People view** (`components/People.tsx`, `PersonForm.tsx`) — the "one place":
  searchable (name/company/title) + status filter; worklist sort (`to-reach`
  first); each row shows name, title, company, status badge, clickable **link
  chips** (LinkedIn + extras), hook/notes preview, **edit** / **delete**; **+ Add**
  opens `PersonForm` (name, title, company with a datalist of known
  companies/roles, optional role, linkedin_url, dynamic `{label,url}` list,
  status, hook, message, notes).
- **Inspector** — replace the free-text "Mined Contacts" with a **"People at
  {company}"** section: people filtered by normalized company (and `role` when
  set), each with clickable links + status, plus **+ Add** prefilled for this
  listing. Keep the sheet's `hooks`; keep the raw sheet `people` string as a
  muted fallback.
- **Board / Table** cards gain a small **"N people"** chip.
- **`api.ts`** — add plain (authless) `listPeople` / `createPerson` /
  `updatePerson` / `deletePerson` JSON helpers.

### Join semantics

Client-side join (People list + Inspector share one `/api/people` fetch):
match `safe_slug(person.company) == safe_slug(application.company)`; when
`person.role` is set, additionally require `safe_slug(company, role)` to match
for a precise tie, else fall back to company-level. Mirrors the tailored-resume
join key. (Backend `?company=` filter exists for direct queries.)

## Safety

- **No auth** — the security boundary is the `127.0.0.1` bind set by the start
  script. Documented as local-only; re-add the token before any networked deploy.
- User-entered URLs are rendered as links **only** when the scheme is `http`/
  `https` (blocks `javascript:`/`data:` hrefs); external links use
  `rel="noopener noreferrer" target="_blank"`.
- Atomic file writes + lock prevent people-store corruption / races.
- `id` format validated on every path-param route. `data/people.json` gitignored.

## Testing

- `tests/test_people_store.py`: add/update/delete/list round-trip on a temp file;
  atomic-write behavior; unknown id → `False`; missing file → empty list.
- `tests/test_people_api.py` (`TestClient`, no auth): full CRUD; `422` on blank
  name/company and bad status; bad `id` → `400`; unknown `id` on PUT/DELETE →
  `404`; `DELETE` → `204`. Store path monkeypatched to a temp dir.
- **Auth-removal test changes:** delete the 401-without-token assertions across
  the existing suite; keep every other behavioral test, now called without a
  token. `uv run pytest -v` stays green.
- Frontend: verified by `npm run build` + a browser-MCP screenshot walkthrough
  (app loads with no token gate → add a person → it appears in the People view
  and in the matching job's inspector with a clickable LinkedIn link).

## Reuse (don't rewrite)

- `app/slug.py::safe_slug` — company/role normalization for the join.
- `app/dashboard.py::_resolve_dir` id-validation pattern (`_ID_RE`, `..` guard).
- Frontend: existing `api.ts` fetch/error conventions (minus the token parts),
  `lib/status.ts` badge styling, `lucide-react` icons, Tailwind/dark-mode classes.
- The scratchpad `mock_sheet.py` already written this session (promote it).

## Build & integration

`./scripts/start.sh` is the single local entrypoint. `npm run build` in
`dashboard/` regenerates the committed `app/static/`; FastAPI serves it at `/`
with API routes taking precedence. No new runtime env vars; `RESUME_TAILOR_TOKEN`
is retired.
