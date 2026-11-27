"""Adapters run one agent step on one tool and say how it went, in the same terms for
every tool. This is the agent independence boundary (spec 5.1): steps and prompts never
name a tool, and adding a tool is a config entry, not code.

Every adapter returns an `AdapterResult` and never raises for a tool problem, so the
runner can fall back on the outcome alone:

- `unavailable`: the tool cannot run now (missing binary, no key, network down, out of
  credits). The router cools it down and moves on.
- `timeout`: the step timeout passed; the whole process group is killed.
- `invalid_output`: it ran but gave no usable JSON object. The runner retries once
  with the error list.
- `error`: anything else, such as a request the provider rejected.

Raw output is kept on disk under logs/pipeline/<run_id>/ (gitignored), never in the
database.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import httpx

from app.agent_health import _BLOCKS, _TAIL
from app.claude_cli import _ISOLATION_FLAGS, _subprocess_env
from app.pipeline.config import AdapterSpec, key_set
from app.pipeline.models import AdapterResult

REPO = Path(__file__).resolve().parents[3]
LOG_DIR = REPO / "logs" / "pipeline"
_SAFE = re.compile(r"^[\w.-]+$")
# Dossier fields a generic prompt shows the agent. M4 replaces the generic prompt with
# prompts/<step>.md, which picks its own inputs.
_JOB_FIELDS = ("company", "role", "job_url", "location", "work_mode", "fit_score", "jd_text")
_JD_LIMIT = 20000
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


# --- prompt ---------------------------------------------------------------------------


def render_prompt(step, ctx, errors: list[str]) -> str:
    """A tool neutral prompt for a step: what to do, the dossier, earlier step outputs
    and, on a repair try, what was wrong last time."""
    job = {}
    for name in _JOB_FIELDS:
        value = getattr(ctx.job, name, None)
        if value not in (None, ""):
            job[name] = value[:_JD_LIMIT] if isinstance(value, str) else value
    parts = [
        f"Pipeline step: {step.name} (needs: {step.capability}).",
        "Dossier:\n" + json.dumps(job, indent=1, default=str),
    ]
    if ctx.outputs:
        parts.append("Earlier step outputs:\n" + json.dumps(ctx.outputs, indent=1, default=str))
    if errors:
        parts.append("Your last answer was rejected. Fix these problems:\n" + "\n".join(f"- {e}" for e in errors))
    return "\n\n".join(parts)


def _footer(schema: dict, output_path: Path | None) -> str:
    rules = "Do not submit, send, sign in to or contact anything."
    shape = json.dumps(schema)
    if output_path is None:
        return f"\n\n{rules}\nReply with a single JSON object matching this JSON schema and nothing else.\nSchema: {shape}"
    return (
        f"\n\n{rules}\nWhen done, write a single JSON object matching this JSON schema to the file "
        f"{output_path} and nothing else. The file is what gets read, not your reply.\nSchema: {shape}"
    )


def _tight_schema(schema):
    """Pydantic leaves fields with defaults out of `required`, and structured decoding
    then skips them (playbook "Headless Claude subprocesses"). Require every field."""
    if isinstance(schema, dict):
        tight = {key: _tight_schema(value) for key, value in schema.items()}
        if isinstance(tight.get("properties"), dict):
            tight["required"] = list(tight["properties"])
        return tight
    if isinstance(schema, list):
        return [_tight_schema(item) for item in schema]
    return schema


# --- output parsing -------------------------------------------------------------------


def _json_object(text: str) -> dict | None:
    """The JSON object in a reply, tolerating code fences or a sentence around it."""
    text = text.strip()
    candidates = [text]
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        candidates.append(fenced.group(1))
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _claude_envelope(stdout: str) -> tuple[str, dict]:
    """`claude --output-format json` wraps the answer in a result event (sometimes in an
    array of transcript events). Returns the answer text and the usage numbers."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout, {}
    if isinstance(payload, list):
        results = [e for e in payload if isinstance(e, dict) and e.get("type") == "result"]
        payload = results[-1] if results else None
    if not isinstance(payload, dict) or payload.get("type") != "result":
        return stdout, {}
    usage = payload.get("usage") or {}
    return str(payload.get("result") or ""), {
        "tokens_in": usage.get("input_tokens"),
        "tokens_out": usage.get("output_tokens"),
        "cost": payload.get("total_cost_usd"),
    }


def _blocked(text: str) -> str | None:
    tail = text[-_TAIL:]
    for needle, label in _BLOCKS:
        if needle in tail:
            return label
    return None


def _paths(run_id: str, step: str) -> tuple[Path, Path]:
    """Claim the next free `<step>-<n>` slot for this run, atomically."""
    if not _SAFE.match(run_id) or not _SAFE.match(step):
        raise ValueError(f"unsafe run id or step name: {run_id!r} {step!r}")
    folder = LOG_DIR / run_id
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        log = folder / f"{step}-{n}.log"
        try:
            log.open("x").close()
        except FileExistsError:
            n += 1
            continue
        return folder / f"{step}-{n}.json", log


# --- adapters -------------------------------------------------------------------------


class _Base:
    def __init__(self, spec: AdapterSpec):
        self.spec = spec
        self.name = spec.name

    def invoke(self, step, ctx, errors: list[str]) -> AdapterResult:
        return self.call(
            render_prompt(step, ctx, errors),
            run_id=ctx.run.id,
            step=step.name,
            schema=step.schema.model_json_schema() if step.schema else {"type": "object"},
            timeout=self.spec.timeout_for(step.capability),
        )

    def call(self, prompt: str, *, run_id: str, step: str, schema: dict, timeout: int) -> AdapterResult:
        raise NotImplementedError

    def _result(self, outcome: str, error: str = "", **extra) -> AdapterResult:
        return AdapterResult(outcome=outcome, error=error[:300], model=self.spec.model, **extra)


class CliAdapter(_Base):
    """Runs a CLI agent. The agent writes its JSON to the output path (or, in stdout
    mode, prints it), in its own process group so a timeout kills every child too."""

    def call(self, prompt: str, *, run_id: str, step: str, schema: dict, timeout: int) -> AdapterResult:
        output_path, log_path = _paths(run_id, step)
        to_file = self.spec.output == "file"
        full_prompt = prompt + _footer(schema, output_path if to_file else None)
        schema_text = json.dumps(_tight_schema(schema))
        command = [part.replace("{schema}", schema_text).replace("{prompt}", full_prompt) for part in self.spec.command]
        if self.spec.isolation == "claude_hermetic":
            command += _ISOLATION_FLAGS
        env = _subprocess_env()
        env.update({key: os.path.expanduser(value) for key, value in self.spec.env.items()})
        env["PIPELINE_OUTPUT_PATH"] = str(output_path)
        if shutil.which(command[0], path=env.get("PATH")) is None:
            return self._result("unavailable", f"{command[0]} not found on PATH")
        ref = {"output_ref": str(output_path)}

        proc = subprocess.Popen(
            command, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_group(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # A child that left the group still holds the pipes; stop waiting.
                proc.kill()
                stdout, stderr = "", "output lost: a child process outlived the group kill"
        log_path.write_text(f"$ exit {proc.returncode}\n--- stdout\n{stdout}\n--- stderr\n{stderr}\n", encoding="utf-8")
        if timed_out:
            return self._result("timeout", f"killed after {timeout}s", **ref)

        usage: dict = {}
        if to_file:
            text = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else ""
        else:
            text, usage = _claude_envelope(stdout)
            output_path.write_text(text, encoding="utf-8")
        parsed = _json_object(text) if text.strip() else None
        if proc.returncode == 0 and parsed is not None:
            return self._result("ok", output=parsed, **usage, **ref)
        # Only a failed run is checked for health patterns: a good answer may quote a
        # job description that happens to contain one.
        label = _blocked(stdout + "\n" + stderr)
        if label:
            return self._result("unavailable", label, **ref)
        if proc.returncode != 0:
            detail = (stderr.strip() or stdout.strip())[-200:]
            return self._result("invalid_output", f"exit {proc.returncode}: {detail}", **ref)
        if not text.strip():
            return self._result("invalid_output", "no output written" if to_file else "empty output", **ref)
        return self._result("invalid_output", "output was not a JSON object", **ref)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _post_json(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, dict | None, str]:
    """One HTTP POST, split out so tests replace it. Returns status, JSON body, text."""
    response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return response.status_code, payload, response.text[:300]


class ApiAdapter(_Base):
    """A plain HTTP model call in JSON response mode. Gemini only in M2."""

    def call(self, prompt: str, *, run_id: str, step: str, schema: dict, timeout: int) -> AdapterResult:
        if not self.spec.key_env or not key_set(self.spec):
            return self._result("unavailable", f"{self.spec.key_env or 'key_env'} is not set")
        output_path, log_path = _paths(run_id, step)
        ref = {"output_ref": str(output_path)}
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt + _footer(schema, None)}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        # The key goes in a header, never the URL, so it cannot land in a log line.
        headers = {"x-goog-api-key": os.environ[self.spec.key_env].strip(), "content-type": "application/json"}
        t0 = time.monotonic()
        try:
            status, payload, text = _post_json(GEMINI_URL.format(model=self.spec.model), headers, body, timeout)
        except httpx.TimeoutException:
            return self._result("timeout", f"no answer after {timeout}s")
        except httpx.HTTPError as exc:
            return self._result("unavailable", f"{type(exc).__name__}: {exc}")
        log_path.write_text(f"status {status} in {time.monotonic() - t0:.1f}s\n{json.dumps(payload) if payload else text}\n",
                            encoding="utf-8")
        if status in (401, 403):
            return self._result("unavailable", f"Bad key (HTTP {status})")
        if status == 429:
            return self._result("unavailable", "Usage limit hit (HTTP 429)")
        if status == 404 or status >= 500:
            return self._result("unavailable", f"HTTP {status}: {text}")
        if status != 200 or not isinstance(payload, dict):
            return self._result("error", f"HTTP {status}: {text}")
        try:
            answer = "".join(part.get("text", "") for part in payload["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            return self._result("invalid_output", "response had no candidate text", **ref)
        output_path.write_text(answer, encoding="utf-8")
        usage = payload.get("usageMetadata") or {}
        extra = {"tokens_in": usage.get("promptTokenCount"), "tokens_out": usage.get("candidatesTokenCount"), **ref}
        parsed = _json_object(answer)
        if parsed is None:
            return self._result("invalid_output", "output was not a JSON object", **extra)
        return self._result("ok", output=parsed, **extra)


class SdkAdapter(_Base):
    """Placeholder for in process agents (Pydantic AI). Reports unavailable so the
    router simply moves past it until M2b."""

    def call(self, prompt: str, *, run_id: str, step: str, schema: dict, timeout: int) -> AdapterResult:
        return self._result("unavailable", "sdk adapters arrive in M2b")


def build_adapter(spec: AdapterSpec) -> CliAdapter | ApiAdapter | SdkAdapter:
    return {"cli": CliAdapter, "api": ApiAdapter, "sdk": SdkAdapter}[spec.type](spec)
