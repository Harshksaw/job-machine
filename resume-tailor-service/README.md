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
uv sync
cp .env.example .env   # then fill in RESUME_TAILOR_TOKEN
```

## Run locally

```bash
uv run uvicorn app.main:app --port 8420
```

## Run via Docker (for VPS deployment)

```bash
docker compose up -d
```

## Call it

```bash
curl -s -X POST http://localhost:8420/tailor \
  -H "Authorization: Bearer $RESUME_TAILOR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jd_text": "...", "company": "Acme", "role": "Backend Engineer"}'
```

Returns `{"pdf_path": "...", "manifest": {...}, "pages": 1}`.

## How it works

The one LLM call — selecting which bank IDs to use for a given job
description — runs through the `claude` CLI in headless/print mode
(`claude -p ... --output-format json --model claude-sonnet-5`), authenticated
with whatever the CLI already resolves (Claude subscription login or a
configured key). This means the service needs no `ANTHROPIC_API_KEY` of its
own — only `RESUME_TAILOR_TOKEN`, to authenticate callers of this API.
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
