# Agent orchestrator M2b: vendor independent LLM calls

Spec: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` sections 5, 6 and
13 (13.1, 13.2, 13.4, 13.5). Builds on M1 (runner), M2 (adapters, router, stored config),
M3, M4 (steps) and the Settings UI.

Why: Claude login or terms may change; that must not break the software. Done when kit,
tailor and answers pass their suites with `claude` absent from PATH (13.4).

## Files

- `pyproject.toml`, `uv.lock`: `pydantic-ai-slim[anthropic,google,mcp,openai]==2.76.0`
  (pinned). Checked to install and import on Python 3.12 (the Dockerfile base).
- `app/pipeline/sdk.py` (new): model construction from `provider:name`, the built in tools
  (`web_fetch`, `dossier_read`), MCP toolsets from config, the agent run with a timeout,
  and the exception to outcome mapping.
- `app/pipeline/adapters.py`: `SdkAdapter` runs through `sdk.py` instead of reporting
  unavailable.
- `app/pipeline/config.py`: `AdapterSpec.tools`, `AdapterSpec.mcp`,
  `PipelineConfig.mcp_servers`; sdk model strings checked (`provider:name`, known
  provider, `key_env` required except for `ollama`).
- `app/llm.py` (new): `complete(capability, prompt, schema, *, step, exclude_adapters,
  run_id, job_id) -> (parsed, meta)` plus `completer(...)`, the `Callable[[str], str]`
  seam the generators already take.
- `app/application_kit.py`, `app/tailor.py`: default `complete` becomes
  `llm.completer(...)` instead of `claude_cli.schema_completer(...)`. Prompts, schemas,
  validation and retries are untouched; every test that injects `complete` is unchanged.
- `app/pipeline/router.py`: `resolve_chain(..., exclude=())`; adapters whose `key_env`
  is unset are unhealthy ("X is not set"), so the router skips them and the Settings UI
  shows the reason; one process wide `HEALTH`.
- `app/pipeline/runner.py`: `StepSpec.independent_of`; the runner drops the adapters that
  authored those steps (from their output `meta.authors`) from the chain.
- `app/pipeline/steps_service.py`: kit, answers and repair call `llm.complete` with the
  run id and record `meta.authors` in their output.
- `app/pipeline/steps_agent.py`: review is `independent_of=("kit", "answers")`.
- `app/pipeline/api.py`: `STEP_CAPABILITIES` derived from `PACKET_PIPELINE` steps plus
  the direct `llm` callers (`tailor`); `/api/pipeline/steps` keeps its shape.
- `content/agents.yaml`: `openrouter_haiku` (sdk, enabled, key `OPENROUTER_API_KEY`),
  `gemini_flash` (sdk, disabled), commented MCP example.

## Order of work (test first, one commit per part)

1. sdk adapter on Pydantic AI, config fields, dependency.
2. `app/llm.py` and the generator switch, with a test that kit, tailor and answers work
   with `claude` absent from PATH through a non Claude adapter.
3. Router gaps: review on a different adapter than the kit and answers author; step
   capabilities from `PACKET_PIPELINE`; adapters with an unset key skipped and shown.
   Enable `openrouter_haiku` here, once the key skip exists.
4. Hot reload: a config PUT changes the next `llm.complete` chain.

Then the full backend suite, a Codex review of `6ee33fe..HEAD`, fixes test first.

## Rulings where the spec is silent

- `llm.complete` mirrors the runner: invalid output gets one more try on the same adapter
  with the error list, unavailable, timeout and error move to the next adapter, a policy
  violation stops. A dict schema is checked for its `required` top level keys; a Pydantic
  class is validated and returned as an instance. The generators keep their own
  validation loops on top, unchanged.
- Exhausting the chain raises `LlmUnavailableError`, a subclass of `ClaudeCliError`, so
  the existing 502 handlers in `jobs.py` and `main.py` keep working unchanged.
- Every `llm.complete` try is an attempt in the ledger (run id `llm` for direct HTTP
  calls, the pipeline run id inside a run), so stats compare models for kit and answers.
- `google-gla:` model strings are accepted as an alias of Pydantic AI v2's `google:`.
- Pydantic AI's output validation (with the step schema as the output type) gives the
  model one in-run retry; whatever is still invalid is `invalid_output` for the runner.
- `web_fetch` is http(s) GET only, refuses hosts that resolve to non public addresses
  (so an agent cannot reach the dashboard on localhost), follows at most 5 redirects
  with the same check, 15 s timeout, 1 MB cap, HTML reduced to text and cut at 20,000
  characters. `dossier_read` returns a fixed list of dossier fields, read only.
- Review independence is by adapter name. If excluding the authors leaves no adapter,
  the review step fails with a clear message instead of reviewing its own work.
- `/api/pipeline/steps` lists only steps that use an adapter (agent and service steps),
  so `fetch_jd` and `resolve_apply_url` (code steps today) drop out and `repair` and
  `tailor` appear.
