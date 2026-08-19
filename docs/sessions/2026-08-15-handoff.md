# Session handoff — 2026-08-15

State after a long prep session. Nothing was applied to and nothing was sent.
Nothing is committed; all changes are in the working tree.

## The headline fix

`generate-kit` and `/tailor` had been silently 502ing for months. Root cause:
`~/.claude/settings.json` sets `"defaultMode": "plan"` globally, so every
headless `claude -p` subprocess the service spawned inherited plan mode and
replied *"I'm in plan mode, so I can only read files and create a plan"*
instead of JSON. All 155 dossiers had zero cover letters, zero fit analyses,
zero prepared answers.

Fixed in `app/claude_cli.py` via `_ISOLATION_FLAGS` (`--permission-mode default
--strict-mcp-config --mcp-config '{"mcpServers":{}}' --disable-slash-commands
--allowedTools ""`) plus `--json-schema` for structured output. Do **not** use
`--bare`: it also drops auth and fails with "Not logged in".

See memory note `plan-mode-breaks-headless-claude`.

## Everything changed (uncommitted)

| File | What |
|---|---|
| `app/claude_cli.py` | isolation flags, `json_schema` param, empty-response guard, `schema_completer()` |
| `app/tailor.py` | default completer -> `schema_completer(Manifest)` |
| `app/application_kit.py` | 8 validator fixes (below) |
| `app/static/launch.html` | NEW — the one-click launch queue |
| `scripts/repin_canonical.py` | NEW — rebuilds resume.pdf + regenerates the baseline; `--check` gates drift |
| `content/resume_bank.yaml` | `skill.ai_genai` -> category "AI & ML" + PyTorch/HF/PEFT/LoRA/QLoRA/Unsloth/vLLM/embeddings/reranking |
| `content/canonical_baseline.json` | regenerated for the new resume |
| `harshsaw.tex`, `resume.pdf` | new resume (user-supplied 2026-08-15) |
| `tests/test_claude_cli.py` | NEW — 7 tests |
| `tests/test_application_kit.py` | +16 tests |
| `tests/test_integration_real_bank.py` | fixture gained the `okanagan` job; `&`-escaping guard re-anchored |

**Tests: 157 -> 180, all passing.**

### The 8 validator fixes in `application_kit.py`

1. `_GENERIC_TECH_TERMS` — UI/IoT/OSS/GPU etc. are not credential claims
2. `_MONTH_ALIASES` — bank writes "Dec", letters write "December"
3. `_TECH_ALIASES` — bank writes "PostgreSQL", letters write "Postgres"
4. `_fact_is_traceable` splits on `.` (was asymmetric with `_allowed_tokens`, so `Express.js` never decomposed)
5. `_drop_unquoted_keywords()` — paraphrased keywords filtered, not fatal
6. `_kit_schema()` / `_answer_schema()` — Pydantic omits defaulted fields from `required`, so decoding skipped `cover_letter` entirely
7. **gaps no longer fact-checked** — a gap names what he LACKS, so demanding bank traceability was backwards. This was the single largest failure cause (success went 2-in-9 -> 7-in-10)
8. `evidence.requirement` checked against the full corpus, not JD-only; company matched on first token

Anti-fabrication is intact: SQL/HTML/CSS/JWT/SSO/RBAC stay traceable, and three
tests prove fabrication still fails (Elasticsearch, Fortran, Cassandra).

## Where the work stands

- **48+ of 173 dossiers have a cover letter** (was 0). Batch still running.
- Launch queue: **http://127.0.0.1:8420/launch.html** — filter, fit-sorted,
  Open posting / Copy cover letter / Resume PDF / prepared answers, plus a
  "Needs my input" bucket.
- 18 new dossiers captured from a multi-tab Playwright scrape (LinkedIn +
  Wellfound, persistent profile at `./browser-profile`, both sessions valid).

### Background jobs (scratchpad, session-specific)

`prep_batch.py` generates kits for every eligible dossier, sequentially
(~2-5 min each). `REGEN=1` rebuilds dossiers that already have a letter —
needed because kits built before the bank sync cannot cite the Okanagan role
or the ML stack. Progress in `kit_log.jsonl`.

## Open decisions

1. **Tailoring format mismatch (blocking any resume tailoring).** `/tailor`
   renders through a Jinja template with `templates/resume.cls` (6425 bytes),
   NOT the canonical root `resume.cls` (3711 bytes). Tailored PDFs therefore do
   not preserve Harsh's real format. This is exactly what the canonical
   verifier spec was written to close, and it is still unbuilt — only step 1 of
   8 (baseline pinned + 7 regression tests) exists. No `app/canonical.py`,
   `app/patch.py` or `app/verify.py`.
2. **RDS discovery lane is down.** TCP timeout to the jobs database, and Docker
   is not running for the local mirror on :5433. Infrastructure, not code. This
   is the lane that targets Canada-eligible and sponsoring roles properly.
3. **Full bank now overflows one page.** With 5 jobs, `render_and_fit` trims
   BOTH projects to fit.
4. `/api/applications` returns 502 (Apps Script sheet unreachable), so the
   Pipeline and Board dashboard views are broken. Dossiers and People work.

## Watch out for

- Restarting the service SIGTERMs any in-flight `generate-kit` (exit 143). The
  batch logs it and the retry passes pick it up, but avoid gratuitous restarts.
- `pgrep -f prep_batch.py` matches a watcher whose own command line contains
  that string. Watch by PID (`kill -0 <pid>`), or you will spawn a duplicate.
