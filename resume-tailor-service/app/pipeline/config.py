"""Which agents and models the orchestrator may use, kept apart from code so Harsh can
change them from the dashboard without a deploy (spec 13.5).

`content/agents.yaml` is only the committed seed. The effective config lives in the
`pipeline_config` collection, one document per version, so a bad save can be rolled
back. A rollback or reset never rewrites history: it copies the chosen config forward
as a new version. Secrets are never stored: an adapter names the env var holding its
key, and callers only ever learn whether that variable is set.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from app import doc_store
from app.pipeline.models import now_iso
from app.pipeline.store import _read, _write

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DEFAULTS_PATH = Path(__file__).resolve().parents[2] / "content" / "agents.yaml"
COLLECTION = "pipeline_config"

CAPABILITIES = ("cheap", "reason", "web", "browser_read")
Capability = Literal["cheap", "reason", "web", "browser_read"]
# M2 speaks to Gemini over plain HTTP; other vendors come through `sdk` (Pydantic AI).
API_PROVIDERS = ("gemini",)
# `sdk` model strings are "<provider>:<model>". google-gla is the Pydantic AI v1 name for
# Google AI Studio, kept as an alias of v2's "google". Only ollama (local) needs no key.
SDK_PROVIDERS = ("openrouter", "openai", "anthropic", "google", "google-gla", "ollama")
SDK_KEYLESS = ("ollama",)
# Built in tools an sdk agent may be given (app/pipeline/sdk.py).
SDK_TOOLS = ("web_fetch", "dossier_read")
# Step timeouts per capability (spec 5.3), overridable per adapter.
DEFAULT_TIMEOUTS: dict[str, int] = {"cheap": 180, "reason": 480, "web": 600, "browser_read": 600}

# An env block is for paths and switches; a variable named like a secret belongs in .env.
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.I)
# Well known key shapes, caught by value whatever the variable is called.
_SECRET_VALUE = re.compile(r"^(sk-|sk_|AIza|ghp_|gho_|github_pat_|xox[abp]-|AKIA)[\w-]{8,}")

_LOCK = threading.RLock()
_JSON_BACKENDS: dict[Path, doc_store.JsonFileBackend] = {}
# Tests set this to a SqlBackend to run the same logic against SQL.
_BACKEND_OVERRIDE = None


class VersionNotFound(KeyError):
    pass


def _secret_env(env: dict[str, str]) -> list[str]:
    return [name for name, value in env.items()
            if _SECRET_NAME.search(name) or _SECRET_VALUE.match(value.strip())]


class McpServer(BaseModel):
    """An MCP server an sdk agent may use: a local command (stdio) or a URL."""
    command: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    timeout: int = Field(default=30, ge=1, le=600)

    @model_validator(mode="after")
    def _check(self) -> McpServer:
        if bool(self.command) == bool(self.url.strip()):
            raise ValueError("an mcp server needs exactly one of command or url")
        if self.url and not self.url.startswith(("https://", "http://")):
            raise ValueError("an mcp server url must be http or https")
        secret = _secret_env(self.env)
        if secret:
            raise ValueError(f"env must not carry secrets ({', '.join(secret)}); name the variable in key_env and keep it in .env")
        return self


class AdapterSpec(BaseModel):
    name: str = ""
    type: Literal["cli", "api", "sdk"]
    command: list[str] = Field(default_factory=list)
    # "file": the agent writes its JSON to the output path. "stdout": the answer is the
    # process output, for tools run with no file access (claude under isolation).
    output: Literal["file", "stdout"] = "file"
    isolation: Literal["", "claude_hermetic"] = ""
    provider: str = ""
    model: str = ""
    key_env: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    capabilities: list[Capability] = Field(min_length=1)
    cost_tier: int = Field(default=2, ge=0, le=10)
    max_parallel: int = Field(default=1, ge=1, le=32)
    enabled: bool = True
    timeouts: dict[Capability, int] = Field(default_factory=dict)
    # The tool name agent_health and tools/ai-meter know this adapter by.
    family: str = ""
    # sdk only: built in tools (SDK_TOOLS) and MCP servers (names in mcp_servers).
    tools: list[str] = Field(default_factory=list)
    mcp: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> AdapterSpec:
        if self.type == "cli" and not any("{prompt}" in part for part in self.command):
            raise ValueError("a cli adapter needs a command with a {prompt} placeholder")
        if self.type in ("api", "sdk") and not self.model.strip():
            raise ValueError(f"an {self.type} adapter needs a model")
        if self.type == "api" and not self.key_env.strip():
            raise ValueError("an api adapter needs key_env, the env var that holds its key")
        if self.type == "api" and self.provider not in API_PROVIDERS:
            raise ValueError(f"api provider must be one of {', '.join(API_PROVIDERS)}")
        if self.type == "sdk":
            provider, _, model = self.model.partition(":")
            if provider not in SDK_PROVIDERS or not model.strip():
                raise ValueError(f"an sdk model must be provider:model with provider one of {', '.join(SDK_PROVIDERS)}")
            if provider not in SDK_KEYLESS and not self.key_env.strip():
                raise ValueError(f"an sdk adapter on {provider} needs key_env, the env var that holds its key")
        elif self.tools or self.mcp:
            raise ValueError("tools and mcp are for sdk adapters only")
        unknown = [tool for tool in self.tools if tool not in SDK_TOOLS]
        if unknown:
            raise ValueError(f"unknown tool {', '.join(unknown)}; known: {', '.join(SDK_TOOLS)}")
        secret = _secret_env(self.env)
        if secret:
            raise ValueError(f"env must not carry secrets ({', '.join(secret)}); name the variable in key_env and keep it in .env")
        if any(seconds <= 0 for seconds in self.timeouts.values()):
            raise ValueError("timeouts must be positive seconds")
        return self

    def timeout_for(self, capability: str) -> int:
        return self.timeouts.get(capability) or DEFAULT_TIMEOUTS.get(capability, 600)


class Canary(BaseModel):
    adapter: str
    share: float = Field(ge=0, le=1)


class StepPrefs(BaseModel):
    prefer: list[str] = Field(default_factory=list)
    canary: Canary | None = None


class PipelineConfig(BaseModel):
    workers: int = Field(default=4, ge=0, le=32)
    adapters: dict[str, AdapterSpec] = Field(default_factory=dict)
    capability_caps: dict[Capability, int] = Field(default_factory=dict)
    steps: dict[str, StepPrefs] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServer] = Field(default_factory=dict)
    version: int = 0
    updated_at: str = ""

    @model_validator(mode="after")
    def _check(self) -> PipelineConfig:
        for name, spec in self.adapters.items():
            spec.name = name
        unknown = [
            f"step {step} names unknown adapter {name!r}"
            for step, prefs in self.steps.items()
            for name in prefs.prefer + ([prefs.canary.adapter] if prefs.canary else [])
            if name not in self.adapters
        ]
        unknown += [
            f"adapter {name} names unknown mcp server {server!r}"
            for name, spec in self.adapters.items()
            for server in spec.mcp
            if server not in self.mcp_servers
        ]
        if unknown:
            raise ValueError("; ".join(unknown))
        return self


def check_step_prefs(config: PipelineConfig, step_capabilities: dict[str, str]) -> list[str]:
    """Errors for step preferences the step registry cannot honour: an unknown step, or
    a preferred or canary adapter without the capability the step needs."""
    errors = []
    for step, prefs in config.steps.items():
        if step not in step_capabilities:
            errors.append(f"unknown step {step!r}")
            continue
        needed = step_capabilities[step]
        for name in prefs.prefer:
            if needed not in config.adapters[name].capabilities:
                errors.append(f"step {step} prefers {name}, which lacks capability {needed}")
        if prefs.canary and needed not in config.adapters[prefs.canary.adapter].capabilities:
            errors.append(f"step {step} canary {prefs.canary.adapter} lacks capability {needed}")
    return errors


def key_set(spec: AdapterSpec) -> bool:
    """Whether the adapter's key is present. Never returns or logs the value."""
    return not spec.key_env or bool(os.environ.get(spec.key_env, "").strip())


def load_defaults() -> PipelineConfig:
    return PipelineConfig.model_validate(yaml.safe_load(DEFAULTS_PATH.read_text(encoding="utf-8")))


# --- store ---------------------------------------------------------------------------


def _store():
    backend = _BACKEND_OVERRIDE or doc_store.sql_backend_from_env()
    if backend is not None:
        return backend
    path = DATA_DIR / f"{COLLECTION}.json"
    with _LOCK:
        if path not in _JSON_BACKENDS:
            _JSON_BACKENDS[path] = doc_store.JsonFileBackend(
                lambda: _read(path), lambda items: _write(path, items), threading.RLock()
            )
        return _JSON_BACKENDS[path]


def _from_doc(doc: dict) -> PipelineConfig:
    return PipelineConfig.model_validate(
        {**doc["config"], "version": doc["version"], "updated_at": doc["updated_at"]}
    )


def _append(tx, config: PipelineConfig, note: str) -> PipelineConfig:
    version = max((doc["version"] for doc in tx.all()), default=0) + 1
    body = config.model_dump(mode="json", exclude={"version", "updated_at"})
    for spec in body["adapters"].values():
        spec.pop("name", None)
    doc = {"id": f"{version:08d}", "version": version, "updated_at": now_iso(), "note": note, "config": body}
    tx.put(doc, {"status": "config", "sort_key": doc["id"]})
    return _from_doc(doc)


def _newest(docs: list[dict]) -> dict | None:
    return max(docs, key=lambda doc: doc["version"], default=None)


def load_config() -> PipelineConfig:
    """The effective config, seeding version 1 from the defaults on first use."""
    newest = _newest(_store().all(COLLECTION))
    if newest is not None:
        return _from_doc(newest)
    with _store().transaction(COLLECTION) as tx:
        newest = _newest(tx.all())
        if newest is not None:
            return _from_doc(newest)
        return _append(tx, load_defaults(), "seeded from content/agents.yaml")


def save_config(config: PipelineConfig, note: str = "saved") -> PipelineConfig:
    # Revalidate: a caller may have mutated a loaded model in place.
    config = PipelineConfig.model_validate(config.model_dump(mode="json"))
    with _store().transaction(COLLECTION) as tx:
        return _append(tx, config, note)


def list_versions() -> list[dict]:
    docs = sorted(_store().all(COLLECTION), key=lambda doc: doc["version"], reverse=True)
    return [{"version": doc["version"], "updated_at": doc["updated_at"], "note": doc.get("note", "")} for doc in docs]


def rollback(version: int) -> PipelineConfig:
    with _store().transaction(COLLECTION) as tx:
        doc = tx.get(f"{version:08d}")
        if doc is None:
            raise VersionNotFound(version)
        return _append(tx, _from_doc(doc), f"rollback to version {version}")


def reset_to_defaults() -> PipelineConfig:
    return save_config(load_defaults(), "reset to defaults")
