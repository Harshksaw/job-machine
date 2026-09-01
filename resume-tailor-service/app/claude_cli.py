import json
import subprocess
from collections.abc import Callable

from app.errors import ClaudeCliError

# "claude-haiku-4-5" is a valid, current model id/alias for the `claude` CLI
# (verified live: `claude -p "Reply with only: ok" --model claude-haiku-4-5
# --output-format json` succeeds, echoes back `"model":"claude-haiku-4-5"` in
# the system-init event and resolves to `"claude-haiku-4-5-20251001"` in the
# assistant-message events). Switched from Sonnet to Haiku because Sonnet was
# too slow for this workload and was timing out at 120s.
MODEL_NAME = "claude-haiku-4-5"

# This service needs a plain text completion, not an interactive coding
# session. Left to its defaults the subprocess inherits the *user's* global
# Claude Code config, which is not ours to control: `~/.claude/settings.json`
# carries `"defaultMode": "plan"`, so the model answered every kit request with
# "I'm in plan mode, so I can only read files and create a plan" instead of the
# JSON, and `/tailor` + `/generate-kit` returned 502 for months (0 of 155 live
# dossiers ever got a kit). It also loaded every MCP server and plugin on the
# machine, which added ~70 startup events and minutes of latency per call.
# These flags pin the subprocess to a hermetic, tool-free completion.
# Do not drop them without re-testing against a plan-mode default.
_ISOLATION_FLAGS = [
    "--permission-mode", "default",   # ignore the user's plan-mode default
    "--strict-mcp-config",            # ...and their MCP servers
    "--mcp-config", '{"mcpServers":{}}',
    "--disable-slash-commands",       # ...and their skills
    "--allowedTools", "",             # no tools: this is a completion, not an agent
]


def run_claude(
    prompt: str,
    # 600s, not 300s. Under a parallel batch the CLI queues behind other
    # in-flight calls, and the 2026-08-16 run lost five otherwise-fine
    # dossiers to "timed out after 300s" rather than to any real failure.
    timeout: int = 600,
    model: str = MODEL_NAME,
    json_schema: dict | None = None,
) -> str:
    """Run a headless Claude Code query via the `claude` CLI (print mode),
    using the user's Claude Code auth (subscription or configured key) — no
    separate ANTHROPIC_API_KEY required. Returns the assistant's raw text
    response (expected to be the manifest JSON).

    Note on `--output-format json`: `claude -p --help` documents this as
    emitting "a single result" object, but live testing showed the CLI can
    instead emit a JSON array covering the whole turn (system-init,
    assistant-message, rate_limit_event, ..., result), with the final
    element being the `{"type": "result", ...}` object. Both shapes are
    handled below.

    `json_schema` forces structured output. Without it the model reliably
    reasons *about* the task in prose before (or instead of) emitting the
    object, which then fails `json.loads`; with it the CLI guarantees the
    result field parses against the schema.
    """
    command = ["claude", "-p", prompt, "--output-format", "json", "--model", model]
    command += _ISOLATION_FLAGS
    if json_schema is not None:
        command += ["--json-schema", json.dumps(json_schema)]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ClaudeCliError(
            "`claude` CLI not found on PATH — install Claude Code and run `claude` once to log in"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCliError(f"claude CLI timed out after {timeout}s") from exc
    if result.returncode != 0:
        # The CLI reports usage limits, auth problems and rate limits on stdout,
        # not stderr, so a stderr-only message loses the reason entirely and the
        # failure reads as a bare "exit 1".
        detail = (result.stderr or "").strip()[-500:] or (result.stdout or "").strip()[-500:]
        raise ClaudeCliError(
            f"claude CLI failed (exit {result.returncode}): {detail or '<no output on stderr or stdout>'}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ClaudeCliError(f"claude CLI returned non-JSON output: {result.stdout[:500]}") from exc

    # Observed shape: a JSON array of transcript events; find the terminal
    # `type: "result"` event. Documented shape: a single result object.
    if isinstance(payload, list):
        result_events = [e for e in payload if isinstance(e, dict) and e.get("type") == "result"]
        if not result_events:
            types = [e.get("type") for e in payload if isinstance(e, dict)]
            raise ClaudeCliError(f"claude CLI JSON array had no 'result' event; event types={types}")
        payload = result_events[-1]

    if not isinstance(payload, dict):
        raise ClaudeCliError(f"claude CLI returned unexpected JSON shape: {type(payload).__name__}")

    if payload.get("is_error"):
        raise ClaudeCliError(f"claude CLI reported an error: {payload.get('result') or payload.get('subtype')}")

    text = payload.get("result")
    if not isinstance(text, str):
        raise ClaudeCliError(f"claude CLI JSON had no usable text field; keys={list(payload)}")
    if not text.strip():
        # Surfaces as a bare "Expecting value: line 1 column 1 (char 0)" two
        # frames up otherwise, which reads like a prompt bug rather than an
        # empty turn.
        raise ClaudeCliError("claude CLI returned an empty response")
    return text


def schema_completer(model_or_schema) -> Callable[[str], str]:
    """A one-arg `complete` callable pinned to a JSON schema.

    Accepts a Pydantic model class or an already-built schema dict — callers
    that need a field the model marks optional (Pydantic omits any field with
    a default from `required`, and structured decoding will then skip it) pass
    a tightened dict.

    Call sites take `complete: Callable[[str], str]` so tests can inject a
    stub; this keeps that shape while still forcing structured output.
    """
    schema = (
        model_or_schema.model_json_schema()
        if hasattr(model_or_schema, "model_json_schema")
        else model_or_schema
    )

    def complete(prompt: str) -> str:
        return run_claude(prompt, json_schema=schema)

    return complete
