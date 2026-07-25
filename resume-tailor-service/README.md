# resume-tailor-service

Local/VPS service that tailors `resume.pdf` per job description by
selecting and reordering real content from `content/resume_bank.yaml` —
never fabricating — and compiling a guaranteed one-page PDF with your real
`resume.cls`.

## Setup

Prerequisite: the [Claude Code CLI](https://docs.claude.com/en/docs/claude-code/overview)
(`claude`) must be installed and logged in — run `claude` once and complete
login with your Claude subscription (or configured API key). The service
shells out to this CLI for its one LLM call, so no separate Anthropic API
key is needed.

```bash
cd resume-tailor-service
cp .env.example .env   # fill APPS_SCRIPT_URL / APPS_SCRIPT_READ_SECRET, or point
                        # APPS_SCRIPT_URL at http://127.0.0.1:8799/exec for the mock
```

## Run locally

```bash
./scripts/start.sh
```

This installs dependencies (`uv sync`), starts the mock Google Sheet server
on port 8799 when `APPS_SCRIPT_URL` points at localhost, and starts the API
on `http://127.0.0.1:8420`. Ctrl-C tears both down.

*Local-only — the service has no auth and binds to 127.0.0.1. Re-add a
token dependency before exposing it on a network.*

## Run via Docker

```bash
docker compose up -d
```

> **⚠️ No auth — do NOT expose this on a public network.** The service has no
> authentication. `docker-compose.yml` publishes the port on `127.0.0.1` only,
> so a stock `docker compose up` stays local to the host. Before running it on
> a VPS or forwarding the port, re-add an auth gate — a `Depends(...)` token
> check on the `/tailor`, `/api/*`, and `/api/people` routes, as the
> pre-`feat/people-outreach-hub` `app/auth.py` did — otherwise `/tailor`, the
> people-store CRUD, and PDF serving are open to anyone who can reach the port.

The Compose setup mounts both `./output` and `./data`, so generated PDFs,
dossiers, revisions, answers, and People records survive container recreation.

## Call it

```bash
curl -s -X POST http://localhost:8420/tailor \
  -H "Content-Type: application/json" \
  -d '{"jd_text": "...", "company": "Acme", "role": "Backend Engineer"}'
```

Returns `{"pdf_path": "...", "manifest": {...}, "pages": 1}`.

## Dashboard UI

A dashboard (job dossiers, applications board/table, tailored-resume inspector,
and a People/outreach view) is served at **http://localhost:8420/** — the same
FastAPI app and port as the API above (`GET /health`, `POST /tailor`,
`GET /api/*` all still work side by side; the UI is mounted last so it
never shadows them). The dashboard loads directly with no login or token
gate — the service is local-only, has no auth, and binds to 127.0.0.1.

The built assets live in `app/static/` and are committed to the repo, so a
fresh checkout serves the dashboard with no Node/npm build step — just
`uv run uvicorn app.main:app --port 8420` as above. If the built assets are
ever missing, the API still boots fine (`/` just won't resolve); `/health`,
`/tailor`, and `/api/*` are unaffected.

To rebuild the UI after changing anything under `dashboard/src`:

```bash
cd dashboard && npm install && npm run build
```

This regenerates `app/static/` (`index.html` + hashed `assets/*`), which you
then commit alongside your source change.

## Job dossiers

The default dashboard view is the canonical per-listing workspace. Each dossier
stores the complete JD, company research, fit score, evidence and gaps, exact
source IDs, positioning, next action, deadline, cover letter, unusual form
answers, tailored-resume ID, session activity, and complete restorable
revisions.

Dossiers live in `data/jobs.json`, which is local and gitignored. Google Sheets
is still supported as a compact pipeline log; **Import** merges its rows into
dossiers and deduplicates imported events. The same listing can also be
captured from an agent/browser session with:

```bash
curl -s -X POST http://127.0.0.1:8420/api/jobs/capture \
  -H "Content-Type: application/json" \
  -d '{"company":"Acme","role":"Backend Engineer","job_url":"https://example.com/job","source":"LinkedIn","fit_score":8,"jd_text":"...","session":"LinkedIn 2026-07-23"}'
```

Important routes:

```text
GET/POST       /api/jobs
GET/PUT/DELETE /api/jobs/{id}
POST           /api/jobs/capture
POST           /api/jobs/import-sheet
POST           /api/jobs/{id}/activity
POST           /api/jobs/{id}/generate-kit
POST           /api/jobs/{id}/answers/generate
POST           /api/jobs/{id}/restore/{revision_id}
```

`generate-kit` produces a structured fit decision plus a cover letter. Every
candidate evidence row cites IDs from `resume_bank.yaml`; IDs and traceable
facts are validated before storage. The answer endpoint follows the same
source-ledger rule and deterministically refuses to guess salary,
authorization/sponsorship, start-date, demographic, and similar personal
answers. Generated drafts remain editable and are revisioned on save.

Pass `job_id`, `job_url`, and `session` to `POST /tailor` to attach the PDF to
the dossier and add the resume event automatically.

## People / Outreach hub

The dashboard's People view is a central list of people to reach out to:
name/title/company, a LinkedIn
URL plus any extra links, an outreach status (`to-reach`, `queued`, `sent`,
`replied`, `skip`), a saved outreach message/hook, notes, and an optional
tie back to a job/application. A person tied to a company also shows up
under that company's card in the job inspector.

People are stored in `data/people.json` — gitignored and local-only, never
committed. The list is managed entirely through `GET/POST/PUT/DELETE
/api/people` (see `app/people.py` and `app/people_store.py`); like the rest
of the API, these routes have no auth and are only reachable on
127.0.0.1.

## How it works

The one LLM call — selecting which bank IDs to use for a given job
description — runs through the `claude` CLI in headless/print mode
(`claude -p ... --output-format json --model claude-sonnet-5`), authenticated
with whatever the CLI already resolves (Claude subscription login or a
configured key). This means the service needs no `ANTHROPIC_API_KEY` of its
own. The service itself has no auth — it's local-only, bound to 127.0.0.1.
See `app/claude_cli.py` for the wrapper and `app/tailor.py` for how its output
is parsed, validated, and retried.

## Fidelity guarantee

All structured resume content — every experience bullet, project, achievement,
and skill line — is selected by ID directly from `content/resume_bank.yaml`
and rendered verbatim. It can never be fabricated: the model only ever picks
from a fixed set of existing IDs, and every ID is checked against the bank
before rendering.

The one free-text field is the tailored summary line. It is prompt-constrained
to facts already in the bank, and additionally validated after generation:
numbers, acronyms, and named/technology tokens (e.g. "Rust", "Kubernetes")
must trace back to the bank's actual content before the summary is accepted.
The one documented residual is that a lowercase, number-free qualitative
phrase (e.g. "a strong communicator") is not machine-checked — it relies on
the prompt constraint rather than the validator. If validation fails
persistently, `/tailor` returns an error, and the job-search run prompts fall
back to the static `resume.pdf` rather than upload anything unverified.
