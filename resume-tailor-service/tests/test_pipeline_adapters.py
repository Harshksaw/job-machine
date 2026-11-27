import json
import os
import sys
import textwrap
import time

import httpx
import pytest
from pydantic import BaseModel

from app import job_store
from app.claude_cli import _ISOLATION_FLAGS
from app.models import JobWorkspaceInput
from app.pipeline import adapters, store
from app.pipeline.adapters import ApiAdapter, CliAdapter, SdkAdapter, build_adapter
from app.pipeline.config import AdapterSpec
from app.pipeline.runner import StepContext, StepResult, StepSpec


class Out(BaseModel):
    answer: str


STEP = StepSpec("fit_score", "agent", capability="reason", schema=Out,
                finish=lambda parsed, ctx: StepResult(output=parsed.model_dump()))


@pytest.fixture(autouse=True)
def dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(adapters, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(job_store, "STORE_PATH", tmp_path / "jobs.json")
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_JSON_BACKENDS", {})


@pytest.fixture
def bin_dir(monkeypatch, tmp_path):
    path = tmp_path / "bin"
    path.mkdir()
    monkeypatch.setenv("PATH", f"{path}{os.pathsep}{os.environ['PATH']}")
    return path


def _tool(bin_dir, name: str, body: str) -> None:
    script = bin_dir / name
    script.write_text(f"#!{sys.executable}\nimport json, os, sys, time, subprocess\n" + textwrap.dedent(body))
    script.chmod(0o755)


def _cli(command=None, **extra) -> CliAdapter:
    spec = AdapterSpec.model_validate(
        {"name": "fake", "type": "cli", "command": command or ["faketool", "{prompt}"],
         "capabilities": ["reason"], **extra}
    )
    return CliAdapter(spec)


def _call(adapter, prompt="Score it", timeout=10):
    return adapter.call(prompt, run_id="run1", step="fit_score", schema=Out.model_json_schema(), timeout=timeout)


def test_file_output_is_read_and_parsed(bin_dir, tmp_path):
    _tool(bin_dir, "faketool", """
        path = os.environ["PIPELINE_OUTPUT_PATH"]
        assert path in sys.argv[1], "the footer names the output path"
        open(path, "w").write(json.dumps({"answer": "seven"}))
    """)

    result = _call(_cli())

    assert result.outcome == "ok"
    assert result.output == {"answer": "seven"}
    assert result.output_ref.startswith(str(tmp_path / "logs" / "run1" / "fit_score-1"))
    # A second attempt gets its own file.
    assert _call(_cli()).output_ref.endswith("fit_score-2.json")


def test_missing_binary_is_unavailable():
    result = _call(_cli(["definitely-not-a-real-tool-xyz", "{prompt}"]))
    assert result.outcome == "unavailable"
    assert "not found" in result.error


def test_timeout_kills_the_whole_process_group(bin_dir, tmp_path):
    pid_file = tmp_path / "child.pid"
    _tool(bin_dir, "faketool", f"""
        child = subprocess.Popen(["sleep", "30"])
        open({str(pid_file)!r}, "w").write(str(child.pid))
        time.sleep(30)
    """)

    t0 = time.monotonic()
    result = _call(_cli(), timeout=1)

    assert result.outcome == "timeout"
    assert time.monotonic() - t0 < 10
    child = int(pid_file.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


@pytest.mark.parametrize("body", [
    "sys.exit(0)",  # no file written
    "open(os.environ['PIPELINE_OUTPUT_PATH'], 'w').write('not json')",
    "open(os.environ['PIPELINE_OUTPUT_PATH'], 'w').write('[1, 2]')",
    "open(os.environ['PIPELINE_OUTPUT_PATH'], 'w').write('{}'); sys.exit(3)",
])
def test_bad_runs_are_invalid_output(bin_dir, body):
    _tool(bin_dir, "faketool", body)
    assert _call(_cli()).outcome == "invalid_output"


def test_health_patterns_in_the_output_tail_are_unavailable(bin_dir):
    _tool(bin_dir, "faketool", """
        print("You've hit your usage limit, try again at 5pm.")
        sys.exit(1)
    """)

    result = _call(_cli())

    assert result.outcome == "unavailable"
    assert "Usage limit hit" in result.error


def test_claude_hermetic_reuses_isolation_flags_env_and_reads_stdout(bin_dir, tmp_path, monkeypatch):
    seen = tmp_path / "seen.json"
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    _tool(bin_dir, "claude", f"""
        open({str(seen)!r}, "w").write(json.dumps({{"argv": sys.argv[1:], "env": dict(os.environ)}}))
        print(json.dumps([
            {{"type": "system"}},
            {{"type": "result", "result": "Sure. {{\\"answer\\": \\"eight\\"}}",
              "usage": {{"input_tokens": 12, "output_tokens": 4}}, "total_cost_usd": 0.002}},
        ]))
    """)
    adapter = _cli(["claude", "-p", "{prompt}", "--json-schema", "{schema}"],
                   isolation="claude_hermetic", output="stdout", env={"TOOL_HOME": "~/.tool"})

    result = _call(adapter)

    assert result.outcome == "ok"
    assert result.output == {"answer": "eight"}
    assert (result.tokens_in, result.tokens_out, result.cost) == (12, 4, 0.002)
    recorded = json.loads(seen.read_text())
    argv = recorded["argv"]
    assert argv[-len(_ISOLATION_FLAGS):] == _ISOLATION_FLAGS
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema["required"] == ["answer"]
    assert "HTTPS_PROXY" not in recorded["env"]
    assert recorded["env"]["TOOL_HOME"] == os.path.expanduser("~/.tool")


def test_invoke_renders_the_step_and_repair_errors(bin_dir, tmp_path):
    seen = tmp_path / "prompt.txt"
    _tool(bin_dir, "faketool", f"""
        open({str(seen)!r}, "w").write(sys.argv[1])
        open(os.environ["PIPELINE_OUTPUT_PATH"], "w").write(json.dumps({{"answer": "x"}}))
    """)
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))
    run = store.create_run(job.id, "p", ["fit_score"])
    ctx = StepContext(run=run, job=job, outputs={"fetch_jd": {"chars": 900}})

    result = _cli().invoke(STEP, ctx, ["answer: field required"])

    prompt = seen.read_text()
    assert result.outcome == "ok"
    assert "fit_score" in prompt and "Acme" in prompt and "fetch_jd" in prompt
    assert "answer: field required" in prompt
    assert run.id in result.output_ref


def _api(**extra) -> ApiAdapter:
    return ApiAdapter(AdapterSpec.model_validate(
        {"name": "gem", "type": "api", "provider": "gemini", "model": "flash", "key_env": "TEST_GEM_KEY",
         "capabilities": ["cheap"], **extra}))


def _gemini_body(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 6}}


def test_api_adapter_calls_gemini_in_json_mode(monkeypatch):
    calls = []

    def post(url, headers, body, timeout):
        calls.append((url, headers, body))
        return 200, _gemini_body('{"answer": "nine"}'), ""

    monkeypatch.setenv("TEST_GEM_KEY", "k-123")
    monkeypatch.setattr(adapters, "_post_json", post)

    result = _call(_api())

    assert result.outcome == "ok"
    assert result.output == {"answer": "nine"}
    assert (result.tokens_in, result.tokens_out, result.model) == (20, 6, "flash")
    url, headers, body = calls[0]
    assert "flash:generateContent" in url and "k-123" not in url
    assert headers["x-goog-api-key"] == "k-123"
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_api_adapter_failures(monkeypatch):
    monkeypatch.delenv("TEST_GEM_KEY", raising=False)
    monkeypatch.setattr(adapters, "_post_json", lambda *a: pytest.fail("no key, no call"))
    assert _call(_api()).outcome == "unavailable"

    monkeypatch.setenv("TEST_GEM_KEY", "k")
    monkeypatch.setattr(adapters, "_post_json", lambda *a: (429, None, "quota"))
    assert _call(_api()).outcome == "unavailable"

    def boom(*a):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(adapters, "_post_json", boom)
    assert _call(_api()).outcome == "unavailable"

    def slow(*a):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(adapters, "_post_json", slow)
    assert _call(_api()).outcome == "timeout"

    monkeypatch.setattr(adapters, "_post_json", lambda *a: (200, _gemini_body("no json here"), ""))
    assert _call(_api()).outcome == "invalid_output"

    monkeypatch.setattr(adapters, "_post_json", lambda *a: (400, None, "bad request"))
    assert _call(_api()).outcome == "error"


def test_api_adapter_without_key_env_is_unavailable_not_a_crash(monkeypatch):
    spec = _api().spec.model_copy(update={"key_env": ""})
    monkeypatch.setattr(adapters, "_post_json", lambda *a: pytest.fail("no key, no call"))
    assert _call(ApiAdapter(spec)).outcome == "unavailable"


def test_sdk_adapter_is_unavailable_until_m2b():
    spec = AdapterSpec.model_validate({"name": "or", "type": "sdk", "model": "openrouter:x", "capabilities": ["reason"]})
    adapter = build_adapter(spec)

    assert isinstance(adapter, SdkAdapter)
    result = _call(adapter)
    assert (result.outcome, result.error) == ("unavailable", "sdk adapters arrive in M2b")


def test_build_adapter_picks_the_type():
    assert isinstance(build_adapter(_cli().spec), CliAdapter)
    assert isinstance(build_adapter(_api().spec), ApiAdapter)
    assert build_adapter(_api().spec).name == "gem"
