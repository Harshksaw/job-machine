# Resume Tailor Service — Design

Date: 2026-07-21
Status: Approved by user. `.cls` file received and in place.

## Background

While setting up the job-machine workflow, the user asked to install a LobeHub
MCP plugin (`nishtobehonest-latex-resume-tailor-mcp`) to tailor a LaTeX resume
per job description. On inspection, the plugin's page was written to instruct
an AI agent to blindly run `npx -y nishtobehonest-latex-resume-tailor-mcp` —
an unreviewed package (2 installs, no ratings) that also wanted an
`ANTHROPIC_API_KEY` in `.env`. That combination (agent-directed instructions +
"don't verify, just run this" + a package that wants an API key + a personal
resume) is the shape of a supply-chain / credential-exfiltration risk, so it
was rejected. This spec replaces it with a small, fully-reviewed, locally-run
service built and owned by the user.

## Goal

A local HTTP service that takes a job description and returns a tailored
version of the user's real resume as a compiled PDF, guaranteed to be exactly
one page, using only facts that already exist in `CLAUDE.md` / the resume
content bank — never fabricated content.

## Non-goals

- No rewording of bullet text (facts/numbers/phrasing stay verbatim from the
  content bank — only *selection and ordering* changes per job description).
- Not a replacement for the user's manual judgment on borderline applications
  (fit-scoring rules in CLAUDE.md still apply upstream of this tool).
- Not a multi-tenant product — single user, single resume bank.

## Deployment targets

Two supported modes, same codebase:

1. **Local** — bound to `127.0.0.1`, run manually per session (original
   design). Auth token still required (see below) so behavior is identical
   between modes and nothing has to change when moving to mode 2.
2. **VPS** — same app, containerized with Docker so `pdflatex`/`xelatex` and
   Python deps travel together, reachable over the network. Because a VPS
   deployment is network-reachable by definition, **every request must
   include a shared-secret bearer token** (`RESUME_TAILOR_TOKEN` in `.env`,
   checked in FastAPI middleware, constant-time compare). No token → `401`,
   regardless of deployment mode. The Anthropic API key never leaves the
   server — the token only gates access to this service, not to Anthropic.

## Architecture

A new, separate folder in the repo: `resume-tailor-service/`. Python +
FastAPI, dependency-managed with `uv` (isolated venv + lockfile, nothing
global touched). The service binds to `127.0.0.1` only and is started
manually once per job-search session (same pattern as the existing Playwright
MCP setup in `README.md`).

### Endpoint

```
POST /tailor
Body: {"jd_text": "...", "company": "...", "role": "..."}
Response: {"pdf_path": "...", "manifest": {...}, "pages": 1}
```

```
GET /health
```

## Components

1. **`content/resume_bank.yaml`** — the single source of truth for real
   content. Every experience bullet, project, achievement, and skill-line
   from CLAUDE.md, each with a stable ID (e.g. `ommuse.bullet.1`,
   `project.docintel.bullet.2`). Nothing outside this file may appear on a
   generated resume.

2. **`templates/resume.cls`** — the user's real LaTeX class file (provided
   directly by the user, not reconstructed).

3. **`templates/resume_template.tex.jinja`** — a Jinja2 template matching the
   user's real resume layout, referencing `resume.cls`, with placeholders for
   the summary line and the selected/ordered content blocks.

4. **`app/main.py`** — FastAPI app exposing `/tailor` and `/health`.

5. **`app/tailor.py`** — makes one Anthropic API call (key loaded from a
   local, gitignored `.env`) with the JD text and the full content bank. The
   model returns a **manifest**: which bullet IDs to include per job (subset
   + order, most-relevant first), which project(s) to include (subset +
   order), which achievement bullets to include (subset + order), which
   verified skill-category IDs to include and order, a short (1–2 sentence)
   summary line, and a `job_trim_priority` list ranking jobs
   from least- to most-relevant to this JD (used only for trimming — jobs
   themselves always display in chronological order, never reordered). The
   model is instructed to return IDs and reused facts only — never freeform
   bullet text — so there is no path for it to introduce new content.

6. **`app/render.py`**:
   - **Validate**: every ID in the manifest must exist in `resume_bank.yaml`.
     Every noun/number in the generated summary line must be traceable to the
     content bank. If the manifest references an unknown ID or the summary
     introduces an untraceable fact, reject and retry once with a corrective
     instruction; if it still fails, return an error — never fall back to
     unvalidated content.
   - **Render**: fill the Jinja2 template with the validated, selected
     content.
   - **Compile**: run local `pdflatex` (already installed at
     `/Library/TeX/texbin/pdflatex`) in a temp working directory.
   - **Page-count guarantee**: count pages of the compiled PDF with `pypdf`.
     The manifest's list ordering *is* the priority ranking (the model puts
     each list in most-relevant-first order), so trimming never requires a
     new judgment call — it only ever drops from the tail of an existing
     list.
     - 1 page → done, return the PDF.
     - >1 page → drop the lowest-priority optional item, in this fixed order:
       (a) last project in the projects list, (b) last achievement bullet,
       (c) the lowest-priority skill category while at least three remain,
       (d) last bullet of the lowest-priority job — then recompile. Repeat,
       one item at a time, up to a fixed small number of attempts.
     - Still >1 page after exhausting droppable content → hard error. The
       service never silently returns a resume longer than one page.

7. **`.env`** (gitignored) — `ANTHROPIC_API_KEY=...`, provided by the user.

8. **`pyproject.toml`** (uv-managed) — deps: `fastapi`, `uvicorn`, `jinja2`,
   `pypdf`, `anthropic`, `pydantic`, `python-dotenv`.

9. **`Dockerfile`** — installs a minimal TeX Live (or reuses a `texlive`
   base image) + the `uv`-managed Python deps, so the same image runs
   locally or on a VPS. **`docker-compose.yml`** for one-command local run.

10. **`app/auth.py`** — FastAPI dependency that checks the
    `Authorization: Bearer <token>` header against `RESUME_TAILOR_TOKEN`
    from `.env` using a constant-time comparison; applied to `/tailor`.
    `/health` stays unauthenticated (no secrets in its response).

## Data flow

```
JD text
  → Anthropic call → manifest (IDs + summary line only)
  → validate manifest against resume_bank.yaml
  → render .tex from template + validated content
  → pdflatex compile
  → pypdf page count
  → (trim + recompile loop if >1 page)
  → PDF path + manifest returned
```

## Error handling

- Invalid manifest (unknown ID, untraceable fact) → one corrective retry,
  then explicit error.
- `pdflatex` compile failure → error response includes the tail of the LaTeX
  log for debugging.
- Cannot fit to one page after full trim → explicit error, no silent
  degradation.
- Service binds to `127.0.0.1` only; API key is never logged or included in
  any response body.

## Testing

- A smoke-test script posts 2–3 representative sample JDs (backend-heavy,
  AI/RAG-heavy, mobile-heavy) and asserts: a PDF is produced, it is exactly 1
  page, and every bullet ID in the returned manifest traces back to
  `resume_bank.yaml`.
- Manual check: open at least one generated PDF and visually confirm it
  matches the user's real resume styling.

## Integration with the job-machine workflow

`prompts/wellfound-run.md` and `prompts/linkedin-run.md` gain one new step
before the resume upload: call `POST /tailor` with the listing's JD text,
company, and role, and use the returned PDF path in place of the static
`resume.pdf`. Starting the service (`uv run uvicorn app.main:app --port
8420`, run from `resume-tailor-service/`) becomes a one-time per-session setup
step, documented in `README.md` alongside the existing Playwright MCP setup.

## Confirmed input

The user's real `resume.cls` is in place at
`resume-tailor-service/templates/resume.cls` — the "Medium Length
Professional CV" class (Trey Hunner / LaTeXTemplates.com, freely licensed for
copying/distribution with the copyright notice preserved). It defines
`\name`, `\address`, `rSection`, and `rSubsection` — `resume_template.tex.jinja`
will be built directly against these commands/environments.
