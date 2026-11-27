"""The `sdk` adapter: in process agents on Pydantic AI (spec 13.1). Every model here is a
Pydantic AI TestModel or FunctionModel, and web_fetch runs on an httpx MockTransport, so
nothing touches the network or a real model."""
import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UserError
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app import job_store
from app.models import JobWorkspaceInput
from app.pipeline import adapters, config, sdk, store
from app.pipeline.adapters import SdkAdapter, build_adapter
from app.pipeline.config import AdapterSpec, PipelineConfig
from app.pipeline.models import Run, StepState
from app.pipeline.runner import StepContext, StepResult, StepSpec

KEY = "sk-or-v1-test-secret-0123456789"


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
    monkeypatch.setenv("TEST_OR_KEY", KEY)


def _spec(**extra) -> AdapterSpec:
    return AdapterSpec.model_validate({
        "name": "router_reason", "type": "sdk", "model": "openrouter:anthropic/claude-haiku-4.5",
        "key_env": "TEST_OR_KEY", "capabilities": ["reason", "web"], **extra,
    })


def _use(monkeypatch, model):
    seen = {}

    def build(spec):
        seen["spec"] = spec
        return model

    monkeypatch.setattr(sdk, "build_model", build)
    return seen


def _call(adapter, schema=None, timeout=10):
    return adapter.call("Score it", run_id="run1", step="fit_score",
                        schema=schema or Out.model_json_schema(), timeout=timeout)


def _output_call(args):
    def respond(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])
    return respond


# config


def test_sdk_model_strings_need_a_known_provider_and_a_key_env():
    for bad in ("claude-haiku", "nope:model", "openrouter:"):
        with pytest.raises(ValidationError, match="model"):
            _spec(model=bad)
    with pytest.raises(ValidationError, match="key_env"):
        _spec(key_env="")
    # A local Ollama model needs no key.
    AdapterSpec.model_validate({"type": "sdk", "model": "ollama:llama3.2", "capabilities": ["cheap"]})
    for good in ("google-gla:gemini-2.5-flash", "google:gemini-2.5-flash", "anthropic:claude-haiku-4-5",
                 "openai:gpt-5-mini"):
        _spec(model=good)


def test_tools_and_mcp_names_are_checked():
    with pytest.raises(ValidationError, match="tool"):
        _spec(tools=["shell"])
    with pytest.raises(ValidationError, match="sdk"):
        AdapterSpec.model_validate({"type": "cli", "command": ["t", "{prompt}"], "capabilities": ["reason"],
                                    "tools": ["web_fetch"]})
    with pytest.raises(ValidationError, match="mcp"):
        PipelineConfig.model_validate({"adapters": {"a": _spec(mcp=["ghost"]).model_dump()}})
    cfg = PipelineConfig.model_validate({
        "adapters": {"a": _spec(mcp=["fetch"], tools=["web_fetch", "dossier_read"]).model_dump()},
        "mcp_servers": {"fetch": {"command": ["uvx", "mcp-server-fetch"]}},
    })
    assert cfg.adapters["a"].tools == ["web_fetch", "dossier_read"]
    with pytest.raises(ValidationError, match="key_env"):
        PipelineConfig.model_validate({"mcp_servers": {"x": {"command": ["t"], "env": {"API_TOKEN": "v"}}}})
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({"mcp_servers": {"x": {}}})


# model construction


def test_build_model_passes_the_key_from_key_env_and_maps_providers(monkeypatch):
    model = sdk.build_model(_spec())
    assert (model.system, model.model_name) == ("openrouter", "anthropic/claude-haiku-4.5")
    google = sdk.build_model(_spec(model="google-gla:gemini-2.5-flash"))
    assert (google.system, google.model_name) == ("google", "gemini-2.5-flash")
    assert sdk.build_model(_spec(model="anthropic:claude-haiku-4-5")).system == "anthropic"
    local = AdapterSpec.model_validate({"type": "sdk", "model": "ollama:llama3.2", "capabilities": ["cheap"]})
    assert sdk.build_model(local).model_name == "llama3.2"


# runs


def test_call_returns_structured_output_with_usage(monkeypatch):
    seen = _use(monkeypatch, FunctionModel(_output_call({"answer": "nine"}), model_name="haiku-test"))

    result = _call(SdkAdapter(_spec()))

    assert result.outcome == "ok"
    assert result.output == {"answer": "nine"}
    assert result.model == "haiku-test"
    assert result.tokens_in and result.tokens_out
    assert seen["spec"].name == "router_reason"
    saved = json.loads(open(result.output_ref).read())
    assert saved == {"answer": "nine"}


def test_test_model_fills_the_schema(monkeypatch):
    _use(monkeypatch, TestModel())
    result = _call(SdkAdapter(_spec()))
    assert result.outcome == "ok"
    assert set(result.output) == {"answer"}


def test_invoke_uses_the_step_schema_and_one_in_run_retry(monkeypatch):
    calls = []

    def respond(messages, info: AgentInfo):
        calls.append(1)
        args = {"wrong": 1} if len(calls) == 1 else {"answer": "fixed"}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    _use(monkeypatch, FunctionModel(respond))
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))
    run = Run(id="run1", job_id=job.id, pipeline="p", order=["fit_score"],
              steps={"fit_score": StepState()}, created_at="", updated_at="")

    result = SdkAdapter(_spec()).invoke(STEP, StepContext(run=run, job=job, outputs={}), [])

    assert result.outcome == "ok"
    assert result.output == {"answer": "fixed"}
    assert len(calls) == 2


def test_still_invalid_after_the_retry_is_invalid_output(monkeypatch):
    def respond(messages, info: AgentInfo):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"wrong": 1})])

    _use(monkeypatch, FunctionModel(respond))
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer"))
    run = Run(id="run1", job_id=job.id, pipeline="p", order=["fit_score"],
              steps={"fit_score": StepState()}, created_at="", updated_at="")

    result = SdkAdapter(_spec()).invoke(STEP, StepContext(run=run, job=job, outputs={}), [])

    assert result.outcome == "invalid_output"


def _raises(exc):
    def respond(messages, info):
        raise exc
    return respond


@pytest.mark.parametrize(("exc", "outcome"), [
    (ModelHTTPError(401, "m", body="bad key"), "unavailable"),
    (ModelHTTPError(403, "m", body="forbidden"), "unavailable"),
    (ModelHTTPError(429, "m", body="quota"), "unavailable"),
    (ModelHTTPError(503, "m", body="down"), "unavailable"),
    (ModelHTTPError(400, "m", body="bad request"), "error"),
    (httpx.ConnectError("no route"), "unavailable"),
    (httpx.ReadTimeout("slow"), "timeout"),
    (UnexpectedModelBehavior("garbage"), "invalid_output"),
    (UserError("unknown provider"), "unavailable"),
    (RuntimeError("boom"), "error"),
])
def test_errors_map_to_the_outcome_contract(monkeypatch, exc, outcome):
    _use(monkeypatch, FunctionModel(_raises(exc)))
    result = _call(SdkAdapter(_spec()))
    assert result.outcome == outcome
    assert KEY not in result.error


def test_the_step_timeout_is_enforced(monkeypatch):
    async def slow(messages, info):
        await asyncio.sleep(5)
        return ModelResponse(parts=[TextPart("{}")])

    _use(monkeypatch, FunctionModel(slow))
    result = _call(SdkAdapter(_spec()), timeout=0.2)
    assert result.outcome == "timeout"


def test_no_key_is_unavailable_without_building_a_model(monkeypatch):
    monkeypatch.delenv("TEST_OR_KEY")
    monkeypatch.setattr(sdk, "build_model", lambda spec: pytest.fail("no key, no model"))
    result = _call(SdkAdapter(_spec()))
    assert (result.outcome, result.error) == ("unavailable", "TEST_OR_KEY is not set")


def test_the_key_never_reaches_the_log(monkeypatch, tmp_path):
    _use(monkeypatch, FunctionModel(_raises(ModelHTTPError(401, "m", body=f"bad key {KEY}"))))
    result = _call(SdkAdapter(_spec()))
    assert KEY not in result.error
    for path in (tmp_path / "logs").rglob("*"):
        if path.is_file():
            assert KEY not in path.read_text()


def test_configured_tools_are_given_to_the_agent(monkeypatch):
    seen = {}

    def respond(messages, info: AgentInfo):
        seen["tools"] = sorted(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"answer": "x"})])

    _use(monkeypatch, FunctionModel(respond))
    assert _call(SdkAdapter(_spec(tools=["web_fetch", "dossier_read"]))).outcome == "ok"
    assert seen["tools"] == ["dossier_read", "web_fetch"]


def test_mcp_servers_from_config_become_toolsets(monkeypatch):
    built = []
    monkeypatch.setattr(sdk, "_mcp_toolset", lambda name, server: built.append((name, server.command)) or None)
    servers = {"fetch": config.McpServer(command=["uvx", "mcp-server-fetch"])}
    sdk.toolsets(_spec(mcp=["fetch"]), servers)
    assert built == [("fetch", ["uvx", "mcp-server-fetch"])]


def test_build_adapter_picks_sdk():
    assert isinstance(build_adapter(_spec()), SdkAdapter)


# built in tools


def _transport(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_web_fetch_returns_page_text(monkeypatch):
    monkeypatch.setattr(sdk, "_addresses", lambda host: ["93.184.216.34"])
    page = "<html><head><style>x{}</style><script>evil()</script></head><body><h1>Hello</h1><p>World</p></body></html>"
    monkeypatch.setattr(sdk, "_http_client", _transport(lambda request: httpx.Response(200, html=page)))

    text = sdk.web_fetch("https://example.com/jobs")

    assert "Hello" in text and "World" in text
    assert "evil" not in text and "<h1>" not in text


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "http://localhost:8420/api/jobs",
                                 "http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest"])
def test_web_fetch_refuses_local_and_non_http_urls(monkeypatch, url):
    monkeypatch.setattr(sdk, "_http_client", _transport(lambda request: pytest.fail("must not fetch")))
    assert sdk.web_fetch(url).startswith("refused:")


def test_web_fetch_rechecks_every_redirect(monkeypatch):
    monkeypatch.setattr(sdk, "_addresses", lambda host: ["127.0.0.1"] if host == "internal.example" else ["93.184.216.34"])

    def handler(request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/admin"})
        pytest.fail("followed a redirect into a local address")

    monkeypatch.setattr(sdk, "_http_client", _transport(handler))
    assert sdk.web_fetch("https://example.com/").startswith("refused:")


def test_web_fetch_caps_size(monkeypatch):
    monkeypatch.setattr(sdk, "_addresses", lambda host: ["93.184.216.34"])
    big = "a" * (sdk.WEB_FETCH_MAX_BYTES + 10)
    monkeypatch.setattr(sdk, "_http_client", _transport(lambda request: httpx.Response(200, text=big)))
    text = sdk.web_fetch("https://example.com/")
    assert len(text) <= sdk.WEB_FETCH_MAX_CHARS + 100


def test_web_fetch_reports_network_errors_as_text(monkeypatch):
    monkeypatch.setattr(sdk, "_addresses", lambda host: ["93.184.216.34"])

    def handler(request):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(sdk, "_http_client", _transport(handler))
    assert sdk.web_fetch("https://example.com/").startswith("error:")


def test_dossier_read_is_a_fixed_read_only_view():
    job = job_store.add_job(JobWorkspaceInput(company="Acme", role="Backend Engineer", jd_text="Build APIs."))

    data = json.loads(sdk.dossier_read(job.id))

    assert data["company"] == "Acme" and data["jd_text"] == "Build APIs."
    assert "revisions" not in data and "activities" not in data
    assert sdk.dossier_read("no-such-id").startswith("error:")
    assert sdk.dossier_read("../etc").startswith("error:")
