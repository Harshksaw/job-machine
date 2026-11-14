"""OpenTelemetry for the service: one trace per request, plus a local buffer.

Every HTTP request becomes a server span through the FastAPI instrumentation, and the
slow outside calls (the headless `claude` CLI, connection checks) get their own spans
through `span()`. Finished spans go two places:

- an in-process ring buffer, always, so the dashboard Settings tab can show request
  counts, error rates and latency with no collector running;
- an OTLP/HTTP exporter, only when OTEL_EXPORTER_OTLP_ENDPOINT is set (Jaeger, Grafana
  Tempo, Honeycomb, any collector). The standard OTEL_* variables configure it.

OTEL_SDK_DISABLED=true turns all of it off.
"""
from __future__ import annotations

import base64
import os
import threading
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, StatusCode

SERVICE_NAME = "job-machine"
_SCOPE = "job-machine"
_BUFFER_SIZE = 2000
# Static assets and the launchd health probe would drown out the API routes.
_EXCLUDED_URLS = "assets/,health"


class RecentSpans(SpanProcessor):
    """Keeps the last few thousand request and outside-call spans in memory."""

    def __init__(self, size: int = _BUFFER_SIZE):
        self._spans: deque[dict] = deque(maxlen=size)
        self._lock = threading.Lock()

    def on_end(self, span: ReadableSpan) -> None:
        own = span.instrumentation_scope is not None and span.instrumentation_scope.name == _SCOPE
        # The ASGI instrumentation also emits a child span per send and receive.
        if span.kind is not SpanKind.SERVER and not own:
            return
        attrs = span.attributes or {}
        status = attrs.get("http.response.status_code") or attrs.get("http.status_code")
        method = attrs.get("http.request.method") or attrs.get("http.method")
        route = attrs.get("http.route")
        record = {
            "name": f"{method} {route}" if method and route else span.name,
            "kind": "request" if span.kind is SpanKind.SERVER else "call",
            "status": status,
            "duration_ms": round(((span.end_time or 0) - (span.start_time or 0)) / 1e6, 1),
            "started_at": datetime.fromtimestamp(
                (span.start_time or 0) / 1e9, tz=timezone.utc
            ).isoformat(timespec="seconds"),
            "error": span.status.status_code is StatusCode.ERROR or (status or 0) >= 500,
            "trace_id": format(span.context.trace_id, "032x"),
        }
        with self._lock:
            self._spans.append(record)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._spans)


_recent = RecentSpans()
_provider: TracerProvider | None = None
_exporter_endpoint: str | None = None


GENERATION = {"langfuse.observation.type": "generation"}


class _GenerationsOnly(BatchSpanProcessor):
    """Langfuse is for the model calls. The dashboard polls the API every 20 seconds,
    and exporting those request spans would bury the generations and spend the quota."""

    def on_end(self, span: ReadableSpan) -> None:
        if (span.attributes or {}).get("langfuse.observation.type") == "generation":
            super().on_end(span)


def _langfuse_exporter_args() -> dict | None:
    """Langfuse ingests OTLP over HTTP with the project keys as basic auth."""
    public = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    if not public or not secret:
        return None
    base = os.environ.get("LANGFUSE_BASE_URL", "").strip() or "https://cloud.langfuse.com"
    token = base64.b64encode(f"{public}:{secret}".encode()).decode()
    return {
        "endpoint": f"{base.rstrip('/')}/api/public/otel/v1/traces",
        "headers": {"Authorization": f"Basic {token}"},
    }


def setup(app) -> None:
    """Instrument the FastAPI app. Safe to call once per process."""
    global _provider, _exporter_endpoint
    if _provider is not None or os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return
    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", SERVICE_NAME)}
        )
    )
    provider.add_span_processor(_recent)
    endpoint = (
        os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip()
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    )
    langfuse = _langfuse_exporter_args()
    if endpoint or langfuse:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        # An explicit OTEL_* endpoint wins and gets every span; otherwise the LANGFUSE_*
        # keys are enough, and Langfuse gets the model calls only.
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        else:
            provider.add_span_processor(_GenerationsOnly(OTLPSpanExporter(**langfuse)))
        _exporter_endpoint = endpoint or langfuse["endpoint"]
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, excluded_urls=_EXCLUDED_URLS
    )
    _provider = provider


@contextmanager
def span(name: str, **attributes):
    """A span around one outside call. An exception inside marks it as an error."""
    tracer = (_provider or trace.get_tracer_provider()).get_tracer(_SCOPE)
    clean = {key: value for key, value in attributes.items() if value is not None}
    with tracer.start_as_current_span(name, attributes=clean) as current:
        yield current


_CONTENT_LIMIT = 20000


def record_generation(prompt: str, completion: str, payload: dict, model: str) -> None:
    """Mark the current span as a model call, in the form Langfuse and other OTLP
    backends read: model, token usage and cost. The prompt and reply hold resume and
    application text, so they are attached only when JOB_MACHINE_TRACE_CONTENT=true."""
    current = trace.get_current_span()
    usage = payload.get("usage") or {}
    attributes = {
        "gen_ai.system": "anthropic",
        "gen_ai.request.model": model,
        "gen_ai.usage.input_tokens": usage.get("input_tokens"),
        "gen_ai.usage.output_tokens": usage.get("output_tokens"),
        "gen_ai.usage.cost": payload.get("total_cost_usd"),
    }
    if os.environ.get("JOB_MACHINE_TRACE_CONTENT", "").lower() == "true":
        attributes["langfuse.observation.input"] = prompt[:_CONTENT_LIMIT]
        attributes["langfuse.observation.output"] = completion[:_CONTENT_LIMIT]
    for key, value in attributes.items():
        if value is not None:
            current.set_attribute(key, value)


def exporter_endpoint() -> str | None:
    return _exporter_endpoint


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[int(q * (len(sorted_values) - 1))]


def summary() -> dict:
    """What the Settings tab shows: per route counts, errors and latency."""
    spans = _recent.snapshot()
    groups: dict[tuple[str, str], list[dict]] = {}
    for record in spans:
        groups.setdefault((record["kind"], record["name"]), []).append(record)
    routes = []
    for (kind, name), records in groups.items():
        durations = sorted(record["duration_ms"] for record in records)
        routes.append({
            "name": name,
            "kind": kind,
            "count": len(records),
            "errors": sum(record["error"] for record in records),
            "p50_ms": _percentile(durations, 0.5),
            "p95_ms": _percentile(durations, 0.95),
            "max_ms": durations[-1],
        })
    routes.sort(key=lambda row: -row["count"])
    return {
        "enabled": _provider is not None,
        "service": os.environ.get("OTEL_SERVICE_NAME", SERVICE_NAME),
        "exporter": _exporter_endpoint,
        "buffered": len(spans),
        "buffer_size": _BUFFER_SIZE,
        "since": spans[0]["started_at"] if spans else None,
        "routes": routes[:40],
        "recent_errors": [record for record in reversed(spans) if record["error"]][:10],
        "slowest": sorted(spans, key=lambda record: -record["duration_ms"])[:10],
    }
