import json
import subprocess
from app.errors import ClaudeCliError

# "claude-haiku-4-5" is a valid, current model id/alias for the `claude` CLI
# (verified live: `claude -p "Reply with only: ok" --model claude-haiku-4-5
# --output-format json` succeeds, echoes back `"model":"claude-haiku-4-5"` in
# the system-init event and resolves to `"claude-haiku-4-5-20251001"` in the
# assistant-message events). Switched from Sonnet to Haiku because Sonnet was
# too slow for this workload and was timing out at 120s.
MODEL_NAME = "claude-haiku-4-5"


def run_claude(prompt: str, timeout: int = 300, model: str = MODEL_NAME) -> str:
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
    """
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json", "--model", model],
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
        raise ClaudeCliError(f"claude CLI failed (exit {result.returncode}): {result.stderr[-500:]}")
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
    return text
