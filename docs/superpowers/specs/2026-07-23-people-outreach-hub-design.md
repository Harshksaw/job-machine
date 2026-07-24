# People / Outreach Hub — Design

Date: 2026-07-23
Status: Approved by user.

## Background

The Command Center dashboard (over `resume-tailor-service`) currently reads the
Google-Sheet application log and shows, per job, a read-only "Mined Contacts"
panel that prints the sheet's free-text `people` / `hooks` / `outreach` columns
verbatim (e.g. `people = "CTO, Eng Lead"`). There is no structured record of a
person, no clickable profile link (a name like "CTO" is not reachable), and no
single place that lists everyone worth contacting across all companies. The
original dashboard plan explicitly deferred this as the "Outreach approval
station (post-MVP)".

The user's people-mining workflow (CLAUDE.md: fit 8+ → people-mining eligible,
every outreach shown for approval before sending) needs a real home for the
people it surfaces: one central list, with links, tied back to the jobs.

## Goal

Add a **People / Outreach Hub** to the dashboard: a single, editable, central
list of people the user can reach out to — each with a LinkedIn link plus any
number of extra profile links, an outreach status, a saved hook/message, and an
optional tie to a specific company+role listing — and surface each company's
people inside that job's inspector. The dashboard becomes writable for people
records (create / edit / delete) behind the existing bearer token.

## Non-goals (YAGNI)

- No reminders, scheduling, or notifications.
- No email/DM sending from the dashboard (drafting/approval stays in the user's
  hands per CLAUDE.md; the hub only *stores* the message text).
- No auto-parsing of the existing free-text `people` cells into structured
  records — that text is unstructured and unreliable to split; the raw string
  stays visible as a fallback, and structured people are added going forward.
- No analytics/funnel, no multi-user, no external DB.
- Application (job) rows remain sheet-backed and read-only — only *people* are
  writable.

## Architecture

Same single FastAPI origin as today (no CORS). People are stored server-side in
a local JSON file — consistent with this project's stated design (*"the
filesystem is the tailored-resume index — no DB"*). The browser reads and
mutates people through new authenticated `/api/people*` routes; it joins people
to the (sheet-sourced) applications client-side by normalized company.

```
FastAPI process (one origin):
  ├─ app/people_store.py  ── load/add/update/delete over data/people.json (atomic write + lock)
  ├─ app/people.py        ── APIRouter: GET/POST/PUT/DELETE /api/people, Depends(verify_token)
  ├─ app/dashboard.py     ── unchanged (applications join, tailored resume routes)
  ├─ app/sheets.py        ── unchanged (application log read)
  └─ app/static/          ── rebuilt dashboard SPA (Board | Table | People + inspector section)
```

## Data model — `Person`

Added to `app/models.py` (Pydantic v2).

| field         | type                       | notes                                                    |
|---------------|----------------------------|----------------------------------------------------------|
| `id`          | `str`                      | server-generated, url-safe (`uuid4().hex`); client never sets it |
| `name`        | `str`                      | required, non-empty                                      |
| `title`       | `str = ""`                 | their role, e.g. "Engineering Manager"                   |
| `company`     | `str`                      | required — the join key to applications                  |
| `role`        | `str \| None = None`       | optional — ties the person to an exact company+role listing |
| `linkedin_url`| `str = ""`                 | primary profile link                                     |
| `links`       | `list[Link] = []`          | extra profiles; `Link{label: str, url: str}`             |
| `status`      | `str`                      | one of `to-reach \| queued \| sent \| replied \| skip` (default `to-reach`) |
| `hook`        | `str = ""`                 | the angle for the outreach                               |
| `message`     | `str = ""`                 | drafted / sent outreach text                             |
| `notes`       | `str = ""`                 | free notes                                               |
| `created_at`  | `str`                      | ISO-8601 UTC, set on create                              |
| `updated_at`  | `str`                      | ISO-8601 UTC, set on every write                         |

Write payloads use a separate `PersonInput` model (all of the above **except**
`id` / `created_at` / `updated_at`, which the server owns). Status is validated
against the fixed vocabulary; unknown status → `422`. `name` and `company`
blank → `422`.

## API contract — `app/people.py` (all `Depends(verify_token)`)

```
GET    /api/people                 → list[Person]   (optional ?company= exact-normalized filter)
POST   /api/people   PersonInput   → Person   201   (server assigns id + timestamps)
PUT    /api/people/{id} PersonInput→ Person   200   (404 if id unknown)
DELETE /api/people/{id}            → 204            (404 if id unknown)
```

- `id` path param validated with the same `[A-Za-z0-9._-]+`, no-`..` guard style
  already in `dashboard.py::_resolve_dir` (defense in depth even though the id is
  a JSON key, not a path).
- Auth: no token → `401` (reuses `app/auth.py::verify_token`), identical to the
  other `/api/*` routes.
- Errors are clean, fixed messages; no server internals leaked.

## Storage — `app/people_store.py`

- Backed by `data/people.json` (a new gitignored `data/` dir — personal runtime
  data, like `output/`). Missing file → treated as empty list.
- Functions: `load_people()`, `add_person(input) -> Person`,
  `update_person(id, input) -> Person`, `delete_person(id) -> bool`,
  `get_person(id)`.
- **Atomic writes**: serialize to a temp file in the same dir, `os.replace` into
  place, so an interrupted write can never corrupt the store.
- A module-level `threading.Lock` guards the read-modify-write cycle (FastAPI
  runs sync endpoints in a threadpool, so concurrent mutations are possible).
- Store path is module-level so tests can point it at a temp dir.

## Frontend — two surfaces, joined by company

Rebuilt Vite/React/TS/Tailwind SPA in `dashboard/`, output committed to
`app/static/`. `data/` mutations go through `fetch` with the bearer header; a
`401` re-prompts for the token (existing pattern).

**Header nav gains a third view:** `[ Board ] [ Table ] [ People ]`.

**People view** (`components/People.tsx`, `PersonForm.tsx`) — the "one place":
- Search (name/company/title) + filter by status; sensible sort (worklist feel:
  `to-reach` first).
- Each row: name, title, company, status badge, clickable **link chips**
  (LinkedIn + each extra link), hook/notes preview, **edit** / **delete**.
- **+ Add** opens `PersonForm`: name, title, company (with a datalist of the
  companies/roles already present in the applications list), optional role,
  linkedin_url, a dynamic list of `{label, url}` extra links, status select,
  hook, message textarea, notes.

**Inspector** (per application) — a company's people replace the old free-text
"Mined Contacts":
- New **"People at {company}"** section: the loaded people filtered by
  normalized company (and `role` when the person set one), each with clickable
  links + status, and a **+ Add** button prefilled with this listing's
  company+role.
- The sheet's `hooks` string stays (still useful). The sheet's raw free-text
  `people` string is kept as a muted "raw sheet note" so nothing is lost.

**Board / Table** cards gain a small **"N people"** chip (count of matched
people for that company).

## Join semantics

Client-side join (the People list and the Inspector share one `/api/people`
fetch): match `safe_slug(person.company) == safe_slug(application.company)`;
when `person.role` is set, additionally require the role to match
`safe_slug(application.company, application.role)` for a precise tie, otherwise
fall back to the company-level match. This mirrors the existing tailored-resume
join key. (Backend `?company=` filter exists for direct queries but the UI
joins in the browser.)

## Safety

- All writes behind `verify_token`; same token as the rest of the dashboard.
- User-entered URLs are rendered as links **only** when the scheme is `http`/
  `https` (blocks `javascript:`/`data:` hrefs); all external links use
  `rel="noopener noreferrer" target="_blank"`.
- Atomic file writes + lock prevent store corruption / races.
- `id` format validated on every path-param route.
- No secrets involved; `data/people.json` is gitignored.

## Testing

- `tests/test_people_store.py`: add/update/delete/list round-trip against a temp
  file; atomic-write behavior; unknown id → no-op/`False`; missing file →
  empty list.
- `tests/test_people_api.py` (FastAPI `TestClient`): full CRUD; **401 without
  token**; `422` on blank name/company and bad status; bad `id` → `400`; unknown
  `id` on PUT/DELETE → `404`; `DELETE` → `204`. Store path monkeypatched to a
  temp dir.
- Frontend: verified by `npm run build` + a browser-MCP screenshot walkthrough
  (add a person → appears in People view and in the matching job's inspector
  with a clickable LinkedIn link), matching how the dashboard was verified
  before. (No JS test harness exists in `dashboard/` today; not adding one.)

## Reuse (don't rewrite)

- `app/auth.py::verify_token` — auth on every `/api/people*` route.
- `app/slug.py::safe_slug` — company/role normalization for the join.
- `app/dashboard.py::_resolve_dir` id-validation pattern (`_ID_RE`, `..` guard).
- Frontend: `api.ts` bearer/401 handling, `lib/status.ts` badge styling
  conventions, `lucide-react` icons, existing Tailwind/dark-mode classes.

## Build & integration

`npm run build` in `dashboard/` regenerates the committed `app/static/`
(`index.html` + hashed assets); the FastAPI app already serves it at `/` with
the API routes taking precedence. No new infrastructure, no new runtime env
vars. The service still starts with
`uv run uvicorn app.main:app --port 8420`.
