# Agent Orchestrator: design

Status: draft for review, 2026-11-26. Brainstormed with Harsh in a Claude Code session.
Written so that **any agent** (Claude Code, Cursor, Codex, Antigravity, Gemini, OpenCode)
can implement it milestone by milestone. Read `AGENTS.md` first; nothing here overrides a
hard rule there.

---

## 1. Why

Today the AI work runs three disconnected ways: one `claude -p` call per kit, answer or
tailor inside the service; dashboard "agent runs" (`app/agent_runs.py`) that hand one giant
prompt to one CLI for up to 4 hours; and interactive sessions coordinated by claim notes.

Evidence from the 80 `research-job` logs in `logs/agents/` (counted 2026-11-26): about 29
finished, 5 blocked, about 32 died (watchdog, ping timeouts, out of credit, retry loops),
14 unclear. Root causes:

| Problem | Cause |
|---|---|
| One failure loses everything | 8 steps in one prompt, no per step state, no resume |
| No fallback | Tool picked by hand; a dead tool kills the run |
| Kit failures ignored | Validation errors (for example "cover letter must name the company") are not repaired |
| LLM does deterministic work | JD fetch, apply URL lookup, full dossier PUT that can blank fields |
| Routing is advisory | `tools/ai-meter` prints a route; nothing enforces it |
| No measurement | Nothing records which tool or prompt succeeds, how long, at what cost |

## 2. Goals and non goals

Goals, in priority order:

1. **Reliability:** runs finish without babysitting; a failed step retries or falls back
   to another agent; restarts resume where they stopped.
2. **Quality:** every output is schema checked, rule checked and reviewed before it is
   written to a dossier.
3. **Throughput at low cost:** many dossiers in parallel; cheap models for cheap steps.
4. **Visibility:** per step, per agent stats (pass rate, time, cost) to tune prompts and
   routing.
5. **Agent independence:** no step, prompt or code path names a specific tool. Tools are
   pluggable adapters in config. Removing or adding a tool is a config change.

Non goals:

- **No submitting, sending or signing in.** The pipeline ends at an **apply packet**.
  Applying in Ego Lite and outreach stay interactive, gated by `AGENTS.md` rules 3 and 5.
- No cloud deployment. Everything runs on the Mac (decided 2026-11-26).
- No new infrastructure: reuse the FastAPI service, the `documents` table, launchd.

## 3. Architecture

```
                 +-------------------- resume-tailor-service (FastAPI, :8420) -------------------+
 Dashboard  ---> |  /api/pipeline/*  --->  Queue (pipeline_runs docs, leases)                    |
 CLI script ---> |                              |                                                |
 Any agent  ---> |                        Worker pool (threads, started in app lifespan)         |
 (HTTP)          |                              |                                                |
                 |                        Runner: walks the step DAG for one run                 |
                 |                     /        |             \                                  |
                 |              code step   service step    agent step                           |
                 |              (python)    (generate_kit,   |                                   |
                 |                           answers)        v                                   |
                 |                                     Router -> Adapter (cli | api)             |
                 |                                        ^         |                            |
                 |                     health + budget ---+         v                            |
                 |                                       Validator -> Reviewer -> PATCH dossier  |
                 |                        Ledger (pipeline_attempts docs) <- every attempt       |
                 +-------------------------------------------------------------------------------+
```

New package `resume-tailor-service/app/pipeline/`:

| File | One job |
|---|---|
| `models.py` | Pydantic: `Run`, `StepState`, `Attempt`, `StepSpec`, `AdapterSpec` |
| `store.py` | Runs and attempts in the existing `documents` table (collections `pipeline_runs`, `pipeline_attempts`), lease acquire, renew, release |
| `steps.py` | The step registry: one `StepSpec` per step (kind, deps, capability, owned fields, schema, timeout, prompt file) |
| `steps_code.py` | Code step implementations |
| `adapters.py` | `CliAdapter` and `ApiAdapter`, built from `content/agents.yaml` |
| `router.py` | Picks the adapter chain for a step |
| `validate.py` | Generic output checks plus per step rule hooks |
| `runner.py` | Executes one run: DAG order, parallel branches, retries, fallback |
| `worker.py` | Thread pool, lease loop, concurrency caps |
| `api.py` | FastAPI router `/api/pipeline/*` |
| `prompts/<step>.md` | Agent neutral step prompts, versioned by content hash |

Config: `resume-tailor-service/content/agents.yaml` (committed, no secrets).
Operator CLI: `resume-tailor-service/scripts/pipeline.py` (enqueue, status, retry, eval).

## 4. Steps and flow

A **run** belongs to one dossier and ends at the apply packet. Independent steps run in
parallel.

```
claim -> fetch_jd -> liveness -> eligibility -> fit_score --+--> (fit < 6: stop, "retained for review")
                                                            |
                                                    resolve_apply_url
                              +---------------+-------------+---------------+
                              v               v             v               v
                       company_context       kit       form_fields     people (fit 8+ only)
                              +---------------+------+------+---------------+
                                                     v
                                                  answers
                                                     v
                                                  review
                                                     v
                                           brief -> status "packet_ready"
```

| Step | Kind | Capability | Writes (only these fields) | Notes |
|---|---|---|---|---|
| `claim` | code | | activity note | Takes the run lease on the dossier; writes "Claimed by pipeline <run>" so interactive agents see it. Fails fast if another claim is under 2 hours old or an `applied` event exists |
| `fetch_jd` | code, fallback agent | `web` | `jd_text` | ATS public APIs and LinkedIn guest API from the playbook "JD fetch" section. Agent fallback only when text is still under 800 characters |
| `liveness` | code | | `notes` (append) | Reuses `scripts/check_liveness.check`. `closed` ends the run with status `closed_posting`; `unknown` continues |
| `eligibility` | agent | `cheap` | `notes` (append) | Same policy as today's `triage-filter`. Ineligible ends the run with a reason; never archives |
| `fit_score` | agent | `reason` | `fit_score`, `notes` | Score 1 to 10 against `resume_bank.yaml`. Below 6: run ends `retained_for_review` (rule 2) |
| `resolve_apply_url` | code, fallback agent | `web` | `apply_url` | Code detects ATS hosts and known board redirects; agent fallback for board listings. Empty plus reason when unconfirmed |
| `company_context` | agent | `web` | `company_context`, `why_this_role` | 3 to 6 sentences with source links; why_this_role cites bank source ids |
| `kit` | service | `reason` | `fit_analysis`, `cover_letter` | Calls `application_kit.generate_kit` with the repair loop (section 6) |
| `form_fields` | agent | `browser_read` | `form_fields` (new field) | Ego Lite read only: one TaskSpace named `pipeline <run_id> form`, never type, sign in or submit, close the space |
| `people` | agent | `web` | job people via `/api/jobs/{id}/people` | Only when `fit_score >= 8`. Up to 3. Never contacts anyone |
| `answers` | service | `reason` | `application_answers` | `generate_answer` per free text field from `form_fields`. Personal values only from `docs/PERSONAL-ANSWERS.md`; a missing value means `needs_user_input` |
| `review` | agent | `cheap` | `review` (new field) | Section 6 |
| `brief` | code | | `research_brief`, `status` | Template assembles SUMMARY, APPLY AT, GAPS, WHAT TO PUT IN, NEEDS HARSH, PEOPLE from step outputs. No LLM. Sets `packet_ready` |

Terminal run statuses: `packet_ready`, `retained_for_review`, `ineligible`,
`closed_posting`, `failed` (a step exhausted its chain), `cancelled`.

**Writes go through a new `PATCH /api/jobs/{id}`** that accepts only the fields a step
owns, records `run_id` and `step` in the revision, and never touches other fields. Agents
never call the dossier write API themselves.

## 5. Adapters and router

### 5.1 Adapter contract (the agent independence boundary)

Every agent step is executed the same way regardless of tool:

1. The runner renders `prompts/<step>.md` with the step input (dossier fields, prior step
   outputs) and appends a generic footer: *write a single JSON object matching this schema
   to `{output_path}` and nothing else.*
2. The adapter runs the tool, enforcing the step timeout by killing the process group.
3. The runner reads `{output_path}` (or the response body for API adapters), parses JSON,
   validates.

Two adapter types, both configured, never hard coded:

```yaml
# content/agents.yaml
workers: 4
adapters:
  gemini_lite:
    type: api                      # HTTP call, no CLI needed
    provider: gemini
    model: gemini-3.5-flash-lite
    key_env: GEMINI_API_KEY
    capabilities: [cheap]
    cost_tier: 1
    max_parallel: 4
  claude_haiku:
    type: cli
    command: [claude, -p, "{prompt}", --output-format, json, --model, haiku]
    isolation: claude_hermetic     # reuses claude_cli._subprocess_env flags
    capabilities: [cheap, reason]
    cost_tier: 2
    max_parallel: 2
  codex:
    type: cli
    command: [codex, exec, -s, workspace-write, -c, sandbox_workspace_write.network_access=true, "{prompt}"]
    capabilities: [reason, web, browser_read]
    cost_tier: 3
    max_parallel: 2
  cursor:
    type: cli
    command: [cursor-agent, -p, --force, --trust, --model, grok-4.7-medium, --output-format, text, "{prompt}"]
    capabilities: [reason, web, browser_read]
    cost_tier: 3
    max_parallel: 2
  opencode_free:
    type: cli
    command: [opencode, run, -m, opencode/big-pickle, "{prompt}"]
    capabilities: [web]
    cost_tier: 1
    max_parallel: 1
  antigravity:
    type: cli
    command: [agy, --dangerously-skip-permissions, -p, "{prompt}"]
    capabilities: [reason, web, browser_read]
    cost_tier: 3
    max_parallel: 1
capability_caps:
  browser_read: 2                  # total Ego Lite TaskSpaces open at once
```

Capabilities: `cheap` (classification, review), `reason` (scoring, judgment, writing),
`web` (needs shell plus network to fetch pages), `browser_read` (needs shell plus
`ego-browser`). Adding a tool means adding an entry; no code changes. Tool specific env
(for example Gemini CLI's `GEMINI_CLI_HOME`) moves from `agent_runs._tool_env` into an
`env` block on the adapter entry.

### 5.2 Router

For a step with capability `C`, the chain is every enabled adapter with `C`, filtered and
ordered:

1. Drop adapters marked unhealthy by `app/agent_health.py` (out of credits, usage limit,
   signed out, bad key) or over budget per `tools/ai-meter` policy.
2. Order by `cost_tier`, then by pass rate for this step over the last 30 attempts from
   the ledger (ties: lower median duration).
3. Optional per step override in `agents.yaml` (`steps: {fit_score: {prefer: [codex]}}`).

### 5.3 Failure classes and what happens

| Class | Detected by | Action |
|---|---|---|
| `unavailable` | Health patterns from `agent_health._BLOCKS`, missing binary, connection errors | Mark adapter unhealthy for 30 minutes, next adapter immediately |
| `timeout` | Step timeout (defaults: code 60s, cheap 3m, reason 8m, web 10m, browser_read 10m) | Next adapter |
| `invalid_output` | No file, bad JSON, schema or rule errors | Same adapter once more with the error list, then next adapter |
| `policy_violation` | Output asks to submit, contact or sign in; writes outside owned fields | No retry; step fails, run fails, flagged for Harsh |

A step fails only when its whole chain is exhausted. A failed run keeps every completed
step; `retry` resumes from the failed step.

## 6. Quality loop

1. **Schema:** every step output is a Pydantic model; parse failure is `invalid_output`.
2. **Rules (code):** shared checks on any text meant for a form or letter: no em dashes,
   no hyphenated compounds in sendable text, `_BANNED_COVER_PHRASES`, word limits, the
   company named in a cover letter, and `validate_kit` fact traceability against the bank.
3. **Repair:** the `kit` and `answers` steps feed validation errors back for one repair
   attempt, then fall back to the next adapter (today they fail silently).
4. **Review:** the `review` step runs on a different adapter than the one that wrote the
   kit and answers. Rubric: does it read like a person (`AGENTS.md` working style), is
   every claim from the bank, does it answer what the form asks, is anything only Harsh
   can answer. Output `{pass: bool, issues: [{field, problem, fix}]}`. A failing review
   triggers one repair round on the affected step; if it still fails, the packet is
   marked `packet_ready` with `review.pass=false` and the issues listed under NEEDS HARSH.
5. **Eval set:** `scripts/pipeline.py eval` reruns chosen steps on a fixed list of
   dossier ids (`content/eval_set.yaml`) against a prompt version or adapter and prints
   pass rate, review score, duration and cost side by side. Prompt changes are compared
   here before they ship.

## 7. Ledger and visibility

One `pipeline_attempts` document per attempt: `run_id`, `job_id`, `step`, `adapter`,
`model`, `prompt_version` (first 12 hex of sha256 of the rendered template), `started_at`
(ISO 8601 UTC), `duration_ms`, `outcome` (`ok` or a failure class), `error` (short),
`tokens_in`, `tokens_out`, `cost` (when the tool reports it, else null), `output_ref`.

Raw agent output is stored on disk at `logs/pipeline/<run_id>/<step>-<attempt>.json`
(gitignored), not in the database.

API (all under `/api/pipeline`; mutating routes require the existing `X-Job-Machine`
header):

| Route | Purpose |
|---|---|
| `POST /runs` | Enqueue `{job_ids}` or `{filter: {status, min_fit, limit}}`, optional `{steps}` subset |
| `GET /runs`, `GET /runs/{id}` | List and detail with per step state |
| `POST /runs/{id}/retry` | Resume from the first failed step, optional `{step}` |
| `POST /runs/{id}/cancel` | Kill running processes, release lease |
| `GET /stats` | Per step and adapter: attempts, pass rate, p50 and p90 duration, cost, last error |
| `GET /adapters` | Configured adapters with health and budget state |

Dashboard: a **Pipeline** tab (runs list, per dossier step timeline, stats table, adapter
health), and the Overview "Research this job" button enqueues a run instead of starting
one CLI.

Interactive agents (any tool) use the same API or `scripts/pipeline.py`; none needs its
own copy of the research prompt.

## 8. Concurrency and durability

- Worker pool size from `agents.yaml` (`workers`), started in the FastAPI lifespan,
  disabled in tests and when `PIPELINE_WORKERS=0`.
- A run lease (`lease_owner`, `lease_until`, renewed every 30s) on the run document;
  claims use the existing collection advisory lock, so a second service copy cannot
  double run. After a restart, leases expire and runs resume.
- Per adapter `max_parallel` and per capability caps (`browser_read: 2`) are enforced by
  semaphores in the worker.
- The dossier claim from section 4 keeps interactive agents and pipeline runs apart.

## 9. What gets retired

After milestone M6 ships and has run cleanly for a week:

- `research-job`, `score-new` and `triage-filter` prompts in `app/agent_runs.py` become
  pipeline step prompts; `agent_runs.start` stays only for `liveness` and ad hoc tasks.
- The `score` lane in `scripts/cursor_queue.py`. Its `apply` and `outreach` lanes stay.
- `tools/ai-meter` routing advice for pipeline work (the router reads the meter's budget
  state instead).

## 10. Testing

- A `FakeAdapter` (returns fixture JSON, or simulates timeout, unavailable, invalid
  output) drives runner, router and fallback tests with no network or CLI.
- Contract tests: each step's schema against fixture outputs; each code step against
  recorded HTTP fixtures.
- Rule tests for the shared text checks.
- Store tests on both backends (JSON fallback and Postgres), including lease expiry.
- CI keeps the rule that the suite runs with no `.env` and no agent CLIs installed.

## 11. Build order

Each milestone is independently shippable, has its own tests, and can be handed to a
different agent. An agent claims a milestone by noting it in the newest
`SESSION-HANDOFF-*.md` before starting.

| # | Milestone | Done when |
|---|---|---|
| M1 (done) | Core: `models.py`, `store.py`, `runner.py` with `FakeAdapter`, `PATCH /api/jobs/{id}` | A fake 3 step DAG runs, resumes after a simulated crash, and writes only owned fields |
| M2 | `adapters.py`, `agents.yaml`, `router.py`, health and budget filters | Router picks and falls back correctly in tests; one real smoke call per installed tool |
| M3 | Code steps: `claim`, `fetch_jd`, `liveness`, `resolve_apply_url`, `brief` | Recorded fixture tests pass; a live run on 3 dossiers fills JD and apply URL with no agent |
| M4 | Agent and service steps plus prompts: `eligibility`, `fit_score`, `company_context`, `kit` repair, `form_fields`, `people`, `answers` | 10 real dossiers reach `packet_ready` or a correct terminal status |
| M5 | `review` step, shared rule checks, `eval` command, `eval_set.yaml` | Eval prints a comparison for two adapters on the set |
| M6 | `api.py`, worker pool, Pipeline tab, Overview button switch | A 20 dossier batch runs unattended; stats visible in the dashboard |
| M7 | Retirements from section 9; `AGENTS.md` and playbook pointers updated | Old prompts removed; docs point at the pipeline |

## 12. Open questions

1. `form_fields` adds a new dossier field; should the dashboard show it on the Answers
   tab?
2. Cost data: Claude and Gemini report tokens; Codex, Cursor, OpenCode and agy may not.
   The ledger records null rather than estimating. Acceptable?

## 13. Vendor independence (added 2026-11-26)

Harsh's direction: Claude's login or terms may change, and that must not break the
software. Third party services are fine. Models must be configurable and changeable over
time without code changes.

### 13.1 In process agents on API keys (`type: sdk`)

A third adapter type runs the agent loop inside the service with **Pydantic AI**: tool
calling, typed output against the step schema, and an MCP client built in. LangGraph
was considered and rejected: its graph state and checkpoints duplicate the M1 runner.
Claude Agent SDK was rejected because it is still tied to Anthropic auth.

```yaml
adapters:
  router_reason:
    type: sdk
    model: "openrouter:anthropic/claude-haiku-4.5"   # any provider:model string
    key_env: OPENROUTER_API_KEY
    tools: [web_fetch, dossier_read]
    mcp: [fetch]
    capabilities: [reason, web]
    cost_tier: 2
```

- **OpenRouter** is the default third party gateway: one key, many vendors, so losing
  one vendor is a model string change. Direct keys (Gemini, Anthropic, OpenAI) and local
  Ollama work through the same adapter type.
- `claude -p` stays as one optional adapter. If its auth breaks, the router marks it
  unhealthy (5.2) and the chain moves on; nothing else changes.
- The service's own LLM calls (`generate_kit`, `/tailor`, `generate_answer`) move behind
  one function, `llm.complete(capability, prompt, schema)`, which uses the same router
  instead of calling `claude_cli.run_claude` directly.

### 13.2 Models configurable over time

- `agents.yaml` is reloaded when its file changes; no restart.
- Per step model choice: `steps: {kit: {prefer: [router_reason]}}`, plus an optional
  `canary: {adapter: new_model, share: 0.2}` that sends a share of runs to a new model.
- The ledger records `adapter` and `model` per attempt, and `GET /api/pipeline/stats`
  compares pass rate, review pass rate, time and cost per model, so a model is promoted
  or dropped on evidence. `scripts/pipeline.py eval` (6.5) checks a new model on the
  eval set before it gets live traffic.

### 13.3 Mail and update checks in code, plus MCP

- **Gmail in code:** the Gmail API with Harsh's own OAuth client (read only scope, token
  stored locally, gitignored). A scheduled code pipeline fetches new mail from ATS
  senders; only classification (rejection, interview, assessment, other) is an agent
  step with capability `cheap`. Replaces the Claude Gmail connector dependency in
  `prompts/mail-sync.md`.
- **Update checks in code:** liveness, board polling and the ATS watchlist become
  scheduled code pipelines in the same worker, with no LLM.
- **`job-machine` MCP server:** exposes `get_dossier`, `patch_dossier`, `enqueue_run`,
  `run_status`, `search_mail` over the service API, so Claude Code, Cursor, Codex,
  Antigravity and the sdk agents all use the same tools instead of curl instructions.

### 13.4 Build order additions

| # | Milestone | Done when |
|---|---|---|
| M2b | `sdk` adapter (Pydantic AI), OpenRouter and Gemini entries, `llm.complete` replacing direct `claude -p` calls, `agents.yaml` hot reload | Kit, tailor and answers pass their suites with `claude` absent from PATH |
| M8 | Gmail API mail pipeline, scheduled update pipelines, `job-machine` MCP server, canary routing | Mail sync runs on a schedule with no Claude session; an agent other than Claude uses the MCP tools |

Needs from Harsh: an OpenRouter key (or other provider keys) in `.env`, and a Google
Cloud OAuth client for read only Gmail.
