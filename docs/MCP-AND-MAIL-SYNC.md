# job-machine MCP server and Gmail mail sync

Both pieces are in `resume-tailor-service` (spec section 13.3). Nothing here holds a
secret: the OAuth client and token live in `resume-tailor-service/data/`, which is
gitignored, and the MCP server only knows the service URL.

## The MCP server

`app/mcp_server.py`, stdio transport, built on the official `mcp` Python SDK (v2, where
FastMCP is named `MCPServer`). It calls the service HTTP API at `JOB_MACHINE_API`
(default `http://127.0.0.1:8420`), so it works against whichever service is running.
Point it at a test copy (for example port 8421) by changing that variable.

| Tool | What it does |
|---|---|
| `get_dossier(job_id, include_revisions=false)` | One dossier |
| `list_dossiers(status, q, min_fit, limit)` | Summaries, newest first |
| `patch_dossier(job_id, fields, session)` | PATCH only the named fields; refuses `status: applied` and read only fields |
| `enqueue_run(pipeline, job_ids)` | Queue `packet` runs for dossiers, or a task pipeline (`mail_sync`, `liveness_sweep`, `remote_boards`, `ats_watchlist`) |
| `run_status(run_id \| job_id \| pipeline)` | One run with steps and attempts, or `{runs: [...]}` |
| `search_mail_events(company, outcome, status, since, q, limit)` | Stored mail sync results; never reads the inbox |

Runs only queue until the M6 worker exists; `uv run python scripts/run_task.py --queued`
executes queued task runs.

Replace `/ABSOLUTE/PATH/TO/job-machine` below with the checkout path.

Claude Code (`claude mcp add`, user scope, so the repo's `.mcp.json` stays as it is):

```bash
claude mcp add --scope user job-machine \
  --env JOB_MACHINE_API=http://127.0.0.1:8420 \
  -- uv run --directory /ABSOLUTE/PATH/TO/job-machine/resume-tailor-service python -m app.mcp_server
```

Cursor (`~/.cursor/mcp.json`, the global file, not the repo's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "job-machine": {
      "command": "uv",
      "args": ["run", "--directory", "/ABSOLUTE/PATH/TO/job-machine/resume-tailor-service",
               "python", "-m", "app.mcp_server"],
      "env": {"JOB_MACHINE_API": "http://127.0.0.1:8420"}
    }
  }
}
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.job-machine]
command = "uv"
args = ["run", "--directory", "/ABSOLUTE/PATH/TO/job-machine/resume-tailor-service", "python", "-m", "app.mcp_server"]
env = { JOB_MACHINE_API = "http://127.0.0.1:8420" }
```

## Gmail mail sync

The `mail_sync` task pipeline replaces the Gmail connector step of
`prompts/mail-sync.md`:

`mail_fetch` (code: the two searches from that prompt, `after:` two days before the last
run's newest message, `-in:sent`, receipts dropped) -> `mail_classify` (agent step,
capability `cheap`, any adapter) -> `mail_apply` (code: `scripts/mail_outcomes.plan`,
one dossier activity per Gmail message id, uncertain events held, unmatched ones
reported, no dossier created) -> `mail_report`.

Read only: the client asks for `gmail.readonly` and only lists and reads messages.

One time setup, by Harsh:

1. Google Cloud console: create (or pick) a project, enable the **Gmail API**.
2. OAuth consent screen: user type External, publishing status Testing, add your own
   Gmail address as a test user, add the scope `.../auth/gmail.readonly` only.
   (Testing mode tokens expire after 7 days; publish the app, unverified, for longer
   lived tokens, or rerun step 4 weekly.)
3. Credentials: Create credentials, OAuth client ID, application type **Desktop app**.
   Download the JSON to `resume-tailor-service/data/gmail_client_secret.json` (or set
   `GMAIL_CLIENT_SECRET_FILE`).
4. Run the consent flow once, locally:
   `cd resume-tailor-service && uv run python scripts/gmail_auth.py`
   It writes `data/gmail_token.json` (mode 0600, or `GMAIL_TOKEN_FILE`).
5. Run a sync: `uv run python scripts/run_task.py mail_sync`, or queue one with the
   `enqueue_run` tool and drain with `scripts/run_task.py --queued`. Results:
   `GET /api/pipeline/mail/status`, `GET /api/pipeline/mail/events`, or the
   `search_mail_events` tool. The report lists assessments, interviews, held and
   unmatched mail, and the interviews and rejections to log to the Sheet.

The same runner hosts the code only update checks: `liveness_sweep` (report only, never
deletes), `remote_boards` (writes `data/remote_candidates.json`) and `ats_watchlist`
(stages new listings in the Research queue).
