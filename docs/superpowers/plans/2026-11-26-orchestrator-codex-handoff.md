# Agent orchestrator: handoff to Codex

Written 2026-11-26 when the Claude builders hit their usage limit. Everything below was
checked with git and pytest at hand off time. Read this whole file before touching code.

## Hard rules for this work

1. **Never touch the live system.** `/Users/harshsaw/job-machine` (branch
   `chore/antigravity-handoff`) serves the live dashboard on `http://127.0.0.1:8420`
   under launchd. Do not edit files there, switch its branch, commit there, call :8420,
   or restart it. Its uncommitted edits belong to another agent.
2. Work only in the worktrees named below. Never push. Never merge into `main`.
3. Read `AGENTS.md` first (hard rules 1 to 5; no em dashes; the `origin` repo is PUBLIC,
   so no personal data in code, tests, fixtures or docs).
4. Strict TDD: failing test first, see it fail, minimal code, full suite green, commit.
   Commit messages end with a `Co-Authored-By:` line naming the agent that wrote them.
5. No real network, CLIs, models or mail in tests. Manual smoke runs use port 8421 with
   `PIPELINE_WORKERS=0` and `DATABASE_URL`/`DATABASE_URL_UNPOOLED` unset.

Design authority: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md`
(sections 1 to 13). Per milestone plans are in `docs/superpowers/plans/2026-11-26-agent-orchestrator-*.md`.

## State at hand off

| Worktree | Branch | State |
|---|---|---|
| `/Users/harshsaw/job-machine-orchestrator` | `feat/agent-orchestrator` | M1, M2, M3, M4, Settings UI merged and reviewed. M2b parts 1 and 2 committed (`abbeb7f` sdk adapter on Pydantic AI, `5eeba97` `llm.complete` routing kit, answers, tailor). Clean tree. **730 passed.** Dashboard: 17 passed. |
| `/Users/harshsaw/job-machine-orchestrator-m8` | `feat/orchestrator-m8` (from `6ee33fe`) | M8 in progress. One commit `476655d` (read only Gmail client, mail event store). **Uncommitted WIP:** `app/pipeline/tasks.py`, `scripts/run_task.py`, `app/pipeline/prompts/mail_classify.md`, `tests/test_pipeline_tasks.py`, edits to `app/mail/gmail.py`, `app/pipeline/{api,models,prompts,runner}.py`, `scripts/remote_boards.py`, `tests/test_mail_gmail.py`. **1 failing test:** `tests/test_pipeline_steps_code.py::test_claim_checks_the_live_dossier_not_the_step_snapshot` (713 passed), likely caused by the WIP runner edit. |
| `job-machine-orchestrator-m3`, `-m4` | merged | Already merged into `feat/agent-orchestrator`; leave alone. |

## Remaining work, in order

### 1. Finish M2b (worktree `job-machine-orchestrator`)
Plan: `docs/superpowers/plans/2026-11-26-agent-orchestrator-m2b-vendor-independence.md`.
Parts 1 and 2 are done. Still to do:
- (a) the `review` step must run on a different adapter than the one that wrote the
  kit and answers in the same run (record the author adapter in the step output meta;
  the router excludes it for `review`);
- (b) `STEP_CAPABILITIES` in `app/pipeline/api.py` must be derived from the
  `PACKET_PIPELINE` StepSpecs in `app/pipeline/pipelines.py`, and `GET /api/pipeline/steps`
  must keep returning the same shape;
- (c) adapters whose `key_env` is unset are skipped by the router and shown as such in
  `GET /api/pipeline/adapters`;
- (d) a test proving that a `PUT /api/pipeline/config` changes the very next chain (hot reload);
- (e) a test proving kit, tailor and answers work with `claude` absent from PATH and a non
  Claude adapter configured (spec M2b "done when").
Then run the review below and fix Critical and Important findings test first.

### 2. Finish M8 (worktree `job-machine-orchestrator-m8`)
Plan: `docs/superpowers/plans/2026-11-26-agent-orchestrator-m8-mail-mcp.md` if present
(read it; it records choices already made). First fix the failing claim test without
weakening it, then finish and commit the WIP in small commits:
- task runs (`app/pipeline/tasks.py`): a run path for work that is not per dossier;
- `mail_sync`: fetch (code) -> classify (agent step, capability `cheap`, schema matches
  the event json in `prompts/mail-sync.md`, including `confident`) -> apply (code, reuse
  `scripts/mail_outcomes.py` matching, idempotent on Gmail message id, never create
  dossiers, unmatched and not confident go to the report) -> report; window starts two
  days before the newest message of the last run;
- update check tasks with no LLM: liveness sweep (report only, never delete) and remote
  boards / ATS watchlist refresh reusing the existing script functions;
- `job-machine` MCP server (official `mcp` SDK, FastMCP, stdio) with tools `get_dossier`,
  `list_dossiers`, `patch_dossier` (never sets status applied), `enqueue_run`,
  `run_status`, `search_mail_events`; base URL from `JOB_MACHINE_API`
  (default `http://127.0.0.1:8420`); docs with example MCP config for Claude Code,
  Cursor and Codex; do NOT edit the repo's `.mcp.json` or `.cursor/mcp.json`;
- `scripts/gmail_auth.py`: one time local OAuth (scope `gmail.readonly`), token in
  `resume-tailor-service/data/` (gitignored).
Avoid editing `app/application_kit.py`, `app/tailor.py`, `app/llm.py`,
`app/pipeline/adapters.py`, `app/pipeline/router.py` in this worktree (M2b owns them).
When green and reviewed, merge `feat/orchestrator-m8` into `feat/agent-orchestrator` from
the `job-machine-orchestrator` worktree and rerun every suite.

### 3. M5 quality loop extras (spec section 6.5)
`scripts/pipeline.py eval` plus `content/eval_set.yaml` (dossier ids supplied at run time,
never committed with real ids): reruns chosen steps against a prompt version or adapter
and prints pass rate, review pass rate, duration, cost side by side. Tests on fakes.

### 4. M6 worker and API (spec sections 7, 8)
`app/pipeline/worker.py`: thread pool started in the FastAPI lifespan only when
`PIPELINE_WORKERS` > 0 (default 0, so merging does not start anything), lease renewal
every 30s covering the longest step, `max_parallel` and capability caps as semaphores, a
reaper for runs stuck in `running` with an expired lease. Routes `POST /api/pipeline/runs`
(job ids or filter), `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/retry`,
`POST /runs/{id}/cancel`, `GET /stats`. Dashboard: a Pipeline tab (runs, per dossier step
timeline, stats, adapter health); Overview "Research this job" enqueues a run behind a
setting, keeping the old behavior as default until Harsh switches it. Rebuild
`app/static` with `npm run build` and commit the assets.

### 5. M7 docs
Add a pointer in `AGENTS.md` and `docs/AGENT-PLAYBOOK.md` to the pipeline and MCP server,
and mark old prompts (`research-job`, `score-new`, `triage-filter` in `app/agent_runs.py`,
`score` lane in `scripts/cursor_queue.py`) as superseded. Do NOT delete them until Harsh
has run the pipeline for a week. Do these doc edits on the feature branch only.

## Review after each item

From the worktree root, after the item's suite is green:

```bash
codex exec -s read-only "Review the diff from <base commit> to HEAD on branch <branch> against docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md and AGENTS.md. List Critical/Important/Minor with file:line and a concrete failing scenario. Do not modify files." < /dev/null
```

(`< /dev/null` matters: without it the review hangs on stdin.) Fix every Critical and
Important finding with a failing test first. Record declined findings with the reason in
the item's plan file.

## Known decisions already made (do not reopen)

- Pipeline stops at the apply packet; it never submits, sends, signs in or contacts.
- Fit below 6 retains the dossier for review; Tier A2 (US, UK or Australia only remote)
  needs 7; people mining only at 8 and above.
- Kit keeps an existing cover letter; repair only rewrites a letter written in the same run.
- Config lives in the `pipeline_config` store, editable from Settings; `content/agents.yaml`
  is only the seed; secrets stay in `.env` (only `key_env` names in config).
- Pydantic AI for in process agents; OpenRouter is the default gateway; `claude -p` is one
  optional adapter.
- `PUT /api/pipeline/config` can set CLI commands, so the API must stay loopback only.

## What Harsh must provide (not Codex)

- `OPENROUTER_API_KEY` (and any other provider keys) in `resume-tailor-service/.env`.
- A Google Cloud OAuth client (Desktop app, Gmail API enabled, scope `gmail.readonly`),
  its JSON saved where `GMAIL_CLIENT_SECRET_FILE` points, then run `scripts/gmail_auth.py`
  once.
- The decision to merge `feat/agent-orchestrator` into `main` and restart the dashboard.

## Finish line

All suites green in `job-machine-orchestrator` on `feat/agent-orchestrator` with M2b, M8,
M5, M6 and M7 merged, each reviewed, and a short summary appended to this file listing
commits, test counts, review findings fixed or declined, and anything left for Harsh.

## Final summary (2026-11-27)

All work is on `feat/agent-orchestrator` in `/Users/harshsaw/job-machine-orchestrator`.
Nothing was pushed or merged into `main`, and the live service on :8420 was not touched.

| Item | State | Commits |
|---|---|---|
| 1. M2b vendor independence | done | `abbeb7f`, `5eeba97`, `9474c60`, `23361a3`, `2b86b0b` |
| 2. M8 task runs, mail sync, MCP | done, merged | `476655d`, `dc58695`, `64d3bb8`, `86cd27a`, `1864f4e`, merge `57e8bcf` |
| 3. M5 eval | done | `2349534`, `5fe3a68`, `2c4d9bf` |
| 4. M6 worker, routes, Pipeline tab | done | `a61172f`, `b587d14`, `4b4a68a`, `f8ab0cd`, `d60a1ac`, `0192ceb`, `c744586`, `23583dd`, `afbe1b7` |
| 5. M7 docs and superseded markers | done (nothing deleted) | `a7252fe`, `cb28ff8` |

Tests at `afbe1b7`: backend **881 passed** (811 at `57e8bcf`), dashboard **22 passed**,
typecheck clean, `app/static` rebuilt and committed.

M6 rulings:
- `PIPELINE_WORKERS` (default 0) is the switch and the thread ceiling. The stored
  config's `workers` (Settings) is how many threads claim runs, read every tick, so 0
  pauses the pool. Schedules and "Use the pipeline for research" are off by default.
- The runner renews the lease every 30s. A worker that loses its lease (cancel, retry,
  reaper) stops without another write. On shutdown, CLI process groups are killed and
  the abandoned runs go back to `queued`.
- Service steps (kit, answers) make their own model calls through `llm.complete`, so
  the worker semaphores do not gate them.

Codex review of `57e8bcf..HEAD` (read only):
- Fixed: a stale write after cancel then retry (`c744586`); `workers` from Settings
  (`23583dd`); POST /runs `filter` (`afbe1b7`).
- Declined: the `steps` subset on POST /runs. A partial run has no defined terminal
  status (brief marks the dossier ready), and `retry` with `{step}` covers rerunning
  from a step.
- Declined: a claim at enqueue time. The claim step already refuses a dossier that
  another session has freshly claimed, and a claim written at enqueue would block a
  dossier for hours while workers are off. AGENTS.md now tells agents to check for a
  queued run.
- Declined (minor): a resized semaphore can exceed the new limit until the calls
  holding the old one finish.

Smoke on 127.0.0.1:8421 (`PIPELINE_WORKERS=1`, minimal env without DATABASE_URL or
keys, every adapter disabled): a throwaway dossier with no URL ran through claim,
resolve_apply_url, fetch_jd and liveness with no network, then failed at eligibility
("no adapter offers capability 'cheap'"). Retry requeued it and it failed the same way.
Cancelling a fresh queued run gave `cancelled` with 0 attempts. A cancel of a finished
run gave 409, and a cancel without the header gave 403. A liveness_sweep task run
reached `completed`, and stats and the index page answered. Shutdown was clean. The
smoke data files were moved to the session scratchpad and the worktree config was
restored.

Left for Harsh:
- `OPENROUTER_API_KEY` (and any other provider keys) in `resume-tailor-service/.env`.
- The Gmail OAuth client (Desktop app, `gmail.readonly`) at `GMAIL_CLIENT_SECRET_FILE`,
  then run `scripts/gmail_auth.py` once.
- Decide when to set `PIPELINE_WORKERS` (above 0) on the service, and the schedules in
  Settings.
- The decision to merge `feat/agent-orchestrator` into `main` and restart the
  dashboard. Remove the superseded prompts once the pipeline has run cleanly for a week.
