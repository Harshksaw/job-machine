# resume-tailor-service

Local/VPS service that tailors `resume.pdf` per job description by
selecting and reordering real content from `content/resume_bank.yaml` —
never fabricating — and compiling a guaranteed one-page PDF with your real
`resume.cls`.

## Setup

```bash
cd resume-tailor-service
uv sync
cp .env.example .env   # then fill in ANTHROPIC_API_KEY and RESUME_TAILOR_TOKEN
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
