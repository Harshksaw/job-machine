# Agent orchestrator M2: config, adapters, router, config API

Spec: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` sections 5, 7, 8,
10, 11 and 13.5. Backend only. Nothing is wired into `app/main.py` yet (that is M6);
the new router is mounted only in its tests.

Rules carried over from M1: Pydantic models, JSON fallback plus `SqlBackend` through
`_BACKEND_OVERRIDE`, never nest a pipeline store transaction inside a job_store one. The
suite runs with no `.env`, no network and no agent CLIs. TDD per task: failing test
first, then code, then the full suite. One commit per task.

## Task 1: `app/pipeline/config.py` and `content/agents.yaml`

- `AdapterSpec`: `name`, `type` (`cli` | `api` | `sdk`), `command` (list, must contain
  `{prompt}` for cli; `{schema}` optional), `output` (`file` | `stdout`), `isolation`
  (`""` | `claude_hermetic`), `provider`, `model`, `key_env`, `env`, `capabilities`
  (subset of `cheap`, `reason`, `web`, `browser_read`), `cost_tier`, `max_parallel`,
  `enabled`, `timeouts` (capability -> seconds), `family` (the tool name that
  `agent_health` and `tools/ai-meter` use). api and sdk need `model`; api needs a
  supported `provider`.
- `StepPrefs`: `prefer: list[str]`, `canary: Canary | None` (`adapter`, `share` 0..1).
- `PipelineConfig`: `workers`, `adapters: dict[str, AdapterSpec]`, `capability_caps`,
  `steps: dict[str, StepPrefs]`, `version`, `updated_at`. Rejects a step preference or
  canary naming an unknown adapter.
- `check_step_prefs(config, step_capabilities) -> list[str]`: errors for a preferred or
  canary adapter that lacks the step's capability, or an unknown step.
- `key_set(spec) -> bool` from `os.environ`; secrets are never stored.
- Store (collection `pipeline_config`, one document per version): `load_config()` seeds
  version 1 from `content/agents.yaml` when empty, `save_config(config)` writes version
  max+1, `list_versions()`, `rollback(version)` copies an old version forward as a new
  version, `reset_to_defaults()`.

## Task 2: `app/pipeline/adapters.py`

- `render_prompt(step, ctx, errors)`: generic M2 prompt (step name, dossier fields,
  prior outputs, repair errors). M4 swaps in `prompts/<step>.md`.
- `CliAdapter(spec)`: `call(prompt, *, run_id, step, schema, timeout)` runs the command
  in its own process group with `claude_cli._subprocess_env()` as the base env, plus the
  spec env; `claude_hermetic` appends `claude_cli._ISOLATION_FLAGS`. Output file
  `logs/pipeline/<run_id>/<step>-<n>.json`; stdout mode parses stdout (claude envelope
  aware). Outcomes: missing binary or a `_BLOCKS` pattern in the output tail ->
  `unavailable`; timeout kills the group -> `timeout`; nonzero exit, no file or bad JSON
  -> `invalid_output`.
- `ApiAdapter(spec)`: Gemini `generateContent` with JSON response mode through
  `_post_json` (httpx). Missing key, network errors, 401/403/429/5xx -> `unavailable`.
- `SdkAdapter`: always `unavailable`, "sdk adapters arrive in M2b".
- `build_adapter(spec)`. Runner change: `AdapterResult.output_ref` flows into the
  attempt ledger.

## Task 3: `app/pipeline/router.py`

- `Health`: in process cooldown (30 min after `unavailable`) plus an optional blocked
  family source (`agent_health` over `logs/agents`).
- `over_budget(family)`: reads `logs/ai-usage.json` and `tools/ai-meter/policy.json`
  with the meter's own `_over`, never polls. Missing files -> False.
- `step_stats(step, attempts)`: pass rate and median duration per adapter over the last
  30 attempts of that step.
- `resolve_chain(step, config, *, health, ledger_stats, rng, over_budget)`: enabled
  adapters with the capability, minus unhealthy, minus over budget (kept as a last resort
  only when nothing else is left), ordered by prefer list, cost tier, pass rate, median
  duration; canary first with probability `share`.
- `make_chain(...)` returns the runner's `Chain` callable, building adapters and marking
  unavailable outcomes on the shared `Health`.

## Task 4: `app/pipeline/api.py`

FastAPI `APIRouter`: `GET/PUT /api/pipeline/config`, `GET /api/pipeline/config/versions`,
`POST /api/pipeline/config/rollback/{version}`, `POST /api/pipeline/config/reset`,
`GET /api/pipeline/adapters` (spec, `key_set`, health), `POST
/api/pipeline/adapters/{name}/test` (one tiny prompt, attempt recorded with run id
`adapter-test`). Mutating routes reuse `search._require_dashboard`.

## Task 5: review

`codex exec -s read-only` review of `53a081f..HEAD`; fix Critical and Important findings
test first.
