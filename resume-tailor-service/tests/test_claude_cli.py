import json
import subprocess

import pytest

from app import claude_cli
from app.errors import ClaudeCliError


class _Result:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _capture(monkeypatch, stdout):
    """Record the argv `run_claude` builds without spawning anything."""
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return _Result(stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return seen


def _result_payload(text):
    return json.dumps([{"type": "result", "is_error": False, "result": text}])


def test_run_claude_overrides_the_users_plan_mode_default(monkeypatch):
    """The subprocess must not inherit the user's global Claude Code config.

    `~/.claude/settings.json` carries `"defaultMode": "plan"`, which made the
    model answer "I'm in plan mode, so I can only read files and create a
    plan" instead of the manifest JSON -- every kit and tailor call 502'd.
    """
    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))

    claude_cli.run_claude("hello")

    command = seen["command"]
    assert "--permission-mode" in command
    assert command[command.index("--permission-mode") + 1] == "default"


def test_run_claude_isolates_mcp_servers_tools_and_skills(monkeypatch):
    """A completion, not an agent: no MCP servers, no tools, no skills."""
    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))

    claude_cli.run_claude("hello")

    command = seen["command"]
    assert "--strict-mcp-config" in command
    assert command[command.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert command[command.index("--allowedTools") + 1] == ""
    assert "--disable-slash-commands" in command


def test_run_claude_passes_a_json_schema_when_given_one(monkeypatch):
    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))
    schema = {"type": "object", "required": ["ok"]}

    claude_cli.run_claude("hello", json_schema=schema)

    command = seen["command"]
    assert json.loads(command[command.index("--json-schema") + 1]) == schema


def test_run_claude_omits_the_schema_flag_by_default(monkeypatch):
    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))

    claude_cli.run_claude("hello")

    assert "--json-schema" not in seen["command"]


def test_run_claude_rejects_an_empty_response(monkeypatch):
    """An empty turn otherwise surfaced two frames up as a bare
    "Expecting value: line 1 column 1 (char 0)", which reads like a prompt
    bug rather than an empty response."""
    _capture(monkeypatch, _result_payload("   "))

    with pytest.raises(ClaudeCliError, match="empty response"):
        claude_cli.run_claude("hello")


def test_schema_completer_accepts_a_plain_dict(monkeypatch):
    """Callers tightening a Pydantic schema pass a dict, not a model class."""
    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))
    schema = {"type": "object", "required": ["cover_letter"]}

    complete = claude_cli.schema_completer(schema)
    complete("hello")

    command = seen["command"]
    assert json.loads(command[command.index("--json-schema") + 1]) == schema


def test_schema_completer_accepts_a_model_class(monkeypatch):
    from app.models import GeneratedAnswer

    seen = _capture(monkeypatch, _result_payload('{"ok": true}'))

    complete = claude_cli.schema_completer(GeneratedAnswer)
    complete("hello")

    command = seen["command"]
    sent = json.loads(command[command.index("--json-schema") + 1])
    assert sent == GeneratedAnswer.model_json_schema()
