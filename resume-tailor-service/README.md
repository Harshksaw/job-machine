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

## Call it

```bash
curl -s -X POST http://localhost:8420/tailor \
  -H "Content-Type: application/json" \
  -d '{"jd_text": "...", "company": "Acme", "role": "Backend Engineer"}'
```

Returns `{"pdf_path": "...", "manifest": {...}, "pages": 1}`.

## Dashboard UI

A dashboard (applications board/table, tailored-resume inspector, and a
People/outreach view) is served at **http://localhost:8420/** — the same
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

## People / Outreach hub

The dashboard's third view (alongside the applications board and table) is
a central list of people to reach out to: name/title/company, a LinkedIn
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
