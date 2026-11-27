"""In process agents on Pydantic AI, behind the `sdk` adapter type (spec 13.1).

One model string from the config ("openrouter:anthropic/claude-haiku-4.5",
"google:gemini-...", "anthropic:...", "openai:...", "ollama:...") picks the vendor, so
losing a vendor is a config change. The key comes from the adapter's `key_env` and is
handed straight to the provider: it is never logged, stored or put in an error.

Agents may get built in tools named in the config (`web_fetch`, `dossier_read`) and MCP
servers from `mcp_servers`. Both are read only. `run` maps every library and network
error to the M1 outcome contract in `outcome_for`.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import os
import re
import socket
import threading
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import pydantic_ai
from pydantic import BaseModel
from pydantic_ai import Agent, StructuredDict
from pydantic_ai import exceptions as ai_errors

from app.pipeline.config import AdapterSpec, McpServer

# The library prints a banner on first use; the service log has no use for it.
pydantic_ai.BANNER_ENABLED = False

PROVIDER_ALIASES = {"google-gla": "google"}
OLLAMA_URL = "http://localhost:11434/v1"
INSTRUCTIONS = (
    "Do not submit, send, sign in to or contact anything. Answer only with the final result "
    "in the required output structure."
)
# One in-run retry when the output fails the schema; the runner adds one more try.
OUTPUT_RETRIES = 1

WEB_FETCH_TIMEOUT = 15
WEB_FETCH_MAX_BYTES = 1_000_000
WEB_FETCH_MAX_CHARS = 20_000
WEB_FETCH_MAX_REDIRECTS = 5
_JOB_ID = re.compile(r"^[\w-]{1,80}$")
# What dossier_read shows an agent: the facts of the listing, never the history.
DOSSIER_FIELDS = (
    "id", "company", "role", "job_url", "apply_url", "location", "work_mode", "compensation",
    "status", "fit_score", "jd_text", "notes", "company_context", "why_this_role", "cover_letter",
)


# --- model ----------------------------------------------------------------------------


def build_model(spec: AdapterSpec):
    """A Pydantic AI model for the adapter, with the key from its key_env."""
    from pydantic_ai.models import infer_model
    from pydantic_ai.providers import infer_provider_class

    provider, _, name = spec.model.partition(":")
    provider = PROVIDER_ALIASES.get(provider, provider)
    kwargs: dict = {}
    if spec.key_env:
        kwargs["api_key"] = os.environ.get(spec.key_env, "").strip()
    if provider == "ollama":
        kwargs["base_url"] = (spec.env.get("OLLAMA_BASE_URL", "").strip()
                              or os.environ.get("OLLAMA_BASE_URL", "").strip() or OLLAMA_URL)
    return infer_model(f"{provider}:{name}", lambda name: infer_provider_class(name)(**kwargs))


# --- built in tools -------------------------------------------------------------------


def _addresses(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _checked_address(host: str) -> tuple[str | None, str]:
    """(why the host must not be fetched, or None; the address to connect to). Every
    address it resolves to must be public, so an agent cannot reach this machine (the
    dashboard API) or a private network. The request then goes to that exact address,
    so a second DNS answer (rebinding) cannot point it somewhere else."""
    if not host:
        return "no host", ""
    try:
        addresses = [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        try:
            addresses = _addresses(host)
        except OSError as exc:
            return f"cannot resolve {host}: {exc}", ""
    if not addresses:
        return f"cannot resolve {host}", ""
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0].strip("[]"))
        mapped = getattr(ip, "ipv4_mapped", None)
        if not ip.is_global or (mapped is not None and not mapped.is_global):
            return f"{host} is not a public address", ""
    return None, addresses[0].split("%")[0].strip("[]")


def _pinned(url: str, address: str) -> tuple[str, str]:
    """The URL with its host replaced by the checked address, and the Host header."""
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = host + (f":{parts.port}" if parts.port else "")
    header = parts.hostname + (f":{parts.port}" if parts.port else "")
    return parts._replace(netloc=netloc).geturl(), header


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=WEB_FETCH_TIMEOUT, follow_redirects=False,
                        headers={"user-agent": "job-machine-agent/1.0 (read only)"})


def _to_text(body: str, content_type: str) -> str:
    if "html" in content_type or body.lstrip()[:1] == "<":
        body = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        body = html.unescape(body)
    return " ".join(body.split())


def web_fetch(url: str) -> str:
    """Fetch a public web page over http or https and return its text (read only).

    Args:
        url: The full http or https URL of the page.
    """
    try:
        with _http_client() as client:
            for _ in range(WEB_FETCH_MAX_REDIRECTS + 1):
                parts = urlsplit(url)
                if parts.scheme not in ("http", "https"):
                    return f"refused: only http and https URLs, got {parts.scheme or 'none'}"
                reason, address = _checked_address(parts.hostname or "")
                if reason:
                    return f"refused: {reason}"
                target, host_header = _pinned(url, address)
                request = client.build_request("GET", target, headers={"host": host_header},
                                               extensions={"sni_hostname": parts.hostname})
                response = client.send(request, stream=True)
                try:
                    if response.is_redirect and response.headers.get("location"):
                        url = str(httpx.URL(url).join(response.headers["location"]))
                        continue
                    if response.status_code >= 400:
                        return f"error: HTTP {response.status_code}"
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= WEB_FETCH_MAX_BYTES:
                            break
                finally:
                    response.close()
                text = _to_text(bytes(body[:WEB_FETCH_MAX_BYTES]).decode(response.encoding or "utf-8", "replace"),
                                response.headers.get("content-type", ""))
                if len(text) > WEB_FETCH_MAX_CHARS:
                    text = text[:WEB_FETCH_MAX_CHARS] + " [truncated]"
                return text
            return f"refused: more than {WEB_FETCH_MAX_REDIRECTS} redirects"
    except httpx.HTTPError as exc:
        return f"error: {type(exc).__name__}: {exc}"[:300]


def dossier_read(job_id: str) -> str:
    """Read one job dossier (company, role, links, job description, notes, drafts) as JSON.

    Args:
        job_id: The dossier id.
    """
    from app import job_store

    if not _JOB_ID.match(job_id or ""):
        return "error: not a dossier id"
    job = job_store.get_job(job_id)
    if job is None:
        return f"error: no dossier {job_id}"
    data = job.model_dump(mode="json", include=set(DOSSIER_FIELDS))
    return json.dumps(data, default=str)


TOOLS = {"web_fetch": web_fetch, "dossier_read": dossier_read}


def _mcp_toolset(name: str, server: McpServer):
    from pydantic_ai.mcp import MCPToolset

    if server.url:
        client = server.url
    else:
        from fastmcp.client.transports import StdioTransport

        client = StdioTransport(server.command[0], server.command[1:],
                                env={key: os.path.expanduser(value) for key, value in server.env.items()} or None)
    return MCPToolset(client, id=name, init_timeout=server.timeout, read_timeout=server.timeout)


def toolsets(spec: AdapterSpec, servers: dict[str, McpServer]) -> list:
    return [toolset for name in spec.mcp if (toolset := _mcp_toolset(name, servers[name])) is not None]


# --- run ------------------------------------------------------------------------------


@dataclass
class Outcome:
    outcome: str
    output: dict | None = None
    error: str = ""
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost: float | None = None


def outcome_for(exc: BaseException) -> tuple[str, str]:
    """The M1 outcome for a failed run: auth, quota, network and a missing provider are
    `unavailable`; the step timeout is `timeout`; output the schema refuses is
    `invalid_output`; anything else is `error`."""
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, (ai_errors.RunTimedOut, TimeoutError, asyncio.TimeoutError, httpx.TimeoutException,
                        ai_errors.ModelTimeoutError, ai_errors.ModelRequestTimeout)):
        return "timeout", detail
    if isinstance(exc, (ai_errors.ModelAuthenticationError, ai_errors.ModelRateLimitError,
                        ai_errors.ModelQuotaExceededError, ai_errors.ModelUnavailableError,
                        ai_errors.ModelServerError, ai_errors.ModelConnectionError,
                        ai_errors.ModelNotFoundError)):
        return "unavailable", detail
    if isinstance(exc, ai_errors.ModelHTTPError):
        status = exc.status_code
        if status in (401, 403, 404, 408, 429) or status >= 500:
            return "unavailable", detail
        return "error", detail
    if isinstance(exc, ai_errors.UnexpectedModelBehavior):
        return "invalid_output", detail
    if isinstance(exc, ai_errors.ModelRequestRejectedError):
        return "error", detail
    if isinstance(exc, (ai_errors.ModelAPIError, ai_errors.UserError, httpx.HTTPError, ConnectionError,
                        ImportError)):
        return "unavailable", detail
    return "error", detail


def _in_own_thread(work):
    """Run `work()` with no event loop in this thread. Pydantic AI's run_sync needs one
    to itself; a caller already inside a loop gets a helper thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return work()
    box: dict = {}

    def target():
        try:
            box["value"] = work()
        except BaseException as exc:  # handed back to the caller
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def _cost(result) -> float | None:
    usage = result.usage
    if getattr(usage, "cost", None) is not None:
        return float(usage.cost)
    try:
        return float(result.response.cost().total_price)
    except Exception:
        return None


def run(spec: AdapterSpec, prompt: str, *, output: type[BaseModel] | dict, timeout: float,
        servers: dict[str, McpServer] | None = None) -> Outcome:
    """One agent run. `output` is the step schema class or a JSON schema dict."""
    key = os.environ.get(spec.key_env, "").strip() if spec.key_env else ""

    def clean(text: str) -> str:
        return (text.replace(key, "***") if key else text)[:300]

    output_type = output if isinstance(output, type) else StructuredDict(output, name="step_output")
    try:
        model = build_model(spec)
        agent = Agent(
            model,
            output_type=output_type,
            instructions=INSTRUCTIONS,
            tools=[TOOLS[name] for name in spec.tools],
            toolsets=toolsets(spec, servers or {}),
            retries=OUTPUT_RETRIES,
        )
        result = _in_own_thread(lambda: agent.run_sync(prompt, timeout=timeout))
    except Exception as exc:
        outcome, detail = outcome_for(exc)
        return Outcome(outcome, error=clean(detail), model=spec.model)
    value = result.output
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", by_alias=True)
    if not isinstance(value, dict):
        return Outcome("invalid_output", error="output was not a JSON object", model=spec.model)
    usage = result.usage
    return Outcome(
        "ok", output=value, model=result.response.model_name or spec.model,
        tokens_in=usage.input_tokens or None, tokens_out=usage.output_tokens or None, cost=_cost(result),
    )
