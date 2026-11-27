# Agent orchestrator M8: mail sync and update checks in code, plus the MCP server

Spec: `docs/superpowers/specs/2026-11-26-agent-orchestrator-design.md` sections 13.3 and
13.5. Builds on M1 (`runner.py`, `store.py`), M2 (adapters, router, config) and M3/M4
(`steps_code.py`, `steps_agent.py`). Replaces the Gmail connector dependency of
`prompts/mail-sync.md`; the matching and writing rules stay those of
`scripts/mail_outcomes.py`.

Files the parallel M2b work changes (`application_kit.py`, `tailor.py`, `llm.py`,
`pipeline/adapters.py`, `pipeline/router.py`) are not touched here.

## Files

- `app/mail/gmail.py`: read only Gmail client. Scope `gmail.readonly` only. Paths from
  `GMAIL_CLIENT_SECRET_FILE` and `GMAIL_TOKEN_FILE`, defaulting under
  `resume-tailor-service/data/` (gitignored). Every request goes through an injectable
  `Transport(path, params) -> dict`; tests use synthetic "Acme" messages.
- `scripts/gmail_auth.py`: one time installed app flow, run locally by Harsh; writes the
  token with mode 0600.
- `app/mail/store.py`: `mail_events` (one document per Gmail message id: the event, what
  happened to it, the dossier) and `mail_sync_state` (newest message date, last run).
  Same Postgres or JSON fallback pattern as `pipeline/store.py`.
- `app/pipeline/tasks.py`: task pipelines that are not per dossier: `mail_sync`,
  `liveness_sweep`, `remote_boards`, `ats_watchlist`, plus `run_task(name)`.
- `app/pipeline/prompts/mail_classify.md`: the classify prompt, agent neutral.
- `app/pipeline/api.py`: `POST/GET /api/pipeline/runs`, `GET /api/pipeline/runs/{id}`,
  `GET /api/pipeline/mail/status`, `GET /api/pipeline/mail/events`.
- `app/mcp_server.py`: FastMCP stdio server over the service HTTP API.
- `scripts/run_task.py`: run a task pipeline now, or drain queued task runs (for
  launchd until the M6 worker exists).
- `scripts/mail_outcomes.py`: matching and the per event decision split into
  `plan(event, jobs, by_id)`, used by both the CLI and the pipeline. CLI behaviour is
  unchanged.
- `scripts/remote_boards.py`: `main()` body split into `harvest(days)`, unchanged CLI.

## Decisions

- **Gmail over plain HTTPS** with `httpx` (already a dependency) plus `google-auth` for
  token load and refresh, and `google-auth-oauthlib` only for the one time consent flow.
  `google-api-python-client` was rejected: it adds the discovery client, `httplib2` and
  `uritemplate` for two GET endpoints (`messages.list`, `messages.get`).
- **Task runs, not a second runner.** `Pipeline` gets `scope="task"`; such a run uses a
  sentinel `job_id` of `task:<pipeline>`, its steps see `ctx.job = None`, and the runner
  refuses any `writes` from it (task pipelines may not declare owned fields). Store,
  leases, resume, ledger and the adapter chain are reused as they are. A separate task
  runner would duplicate retry, fallback and ledger logic; the change to `runner.py` is a
  few lines. A new terminal status `completed` ends a task run.
- **Classification is an agent step** (`mail_classify`, capability `cheap`) through the
  normal chain, so it works on any adapter. Until adapters render
  `prompts/<step>.md`, the fetch step puts the rendered instructions in its own output,
  which the generic prompt already shows the agent. `prompts.render` tolerates a task
  run (no dossier) so the template works once that wiring lands.
- **The agent cannot invent**: events whose id was not fetched are dropped, the date
  comes from the message itself, and messages it leaves out are stored as `ignored`.
- **Apply** uses `mail_outcomes.plan` on the in process dossier list, writes the
  activity with `external_id gmail:<id>` (already idempotent in `job_store`) and sets
  the status only when that activity was new. `confident: false` is held, unmatched and
  ambiguous are reported; no dossier is ever created.
- **Window**: two days before the newest message date of the last completed run, from
  `mail_sync_state`; 14 days on the first run. Messages already in `mail_events` are not
  classified again. The state moves only in the last step, so a failed run reruns the
  same window. At most 100 messages per run, oldest first; the next run continues.
- **Update checks**: no LLM. Liveness reports closed postings of `discovered`,
  `researching` and `ready` dossiers created over 30 days ago and never deletes.
  Remote boards writes `data/remote_candidates.json` and reports counts. The ATS
  watchlist calls `ats_watchlist.poll` with an in process stand in for the two service
  routes it uses, so it stages research rows exactly as the script does.
- **MCP server** talks HTTP to `JOB_MACHINE_API` (default `http://127.0.0.1:8420`), so it
  works against whichever service runs. `patch_dossier` refuses `status: applied` and
  read only fields; mail search reads stored results, never Gmail.
- **No worker yet** (M6): `POST /api/pipeline/runs` queues; `scripts/run_task.py`
  runs task pipelines now or drains the queued ones.
- Sheet logging of interviews and rejections stays with the interactive agent; the
  report lists them.

## Order of work (test first, one commit per part)

1. `feat(mail)`: gmail client, auth script, mail store, `mail_outcomes.plan`.
2. `feat(pipeline)`: task scope in the runner, `mail_sync` pipeline, update check
   pipelines, runs and mail routes, `run_task.py`.
3. `feat(mcp)`: server, tests against a TestClient, README section and config examples.
4. Codex review, fixes test first.
