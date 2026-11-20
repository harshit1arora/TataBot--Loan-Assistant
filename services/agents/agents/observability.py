"""Opt-in, content-free OpenTelemetry spans and OTLP/HTTP export."""

from __future__ import annotations

import base64
import logging
import os
import re

from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger("tatabot.observability")
tracer = trace.get_tracer("tatabot")
_provider = None


def configure(service: str, *, langfuse: bool = False) -> None:
    global _provider
    if _provider is not None:
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
    generic = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    lf_url = os.getenv("LANGFUSE_BASE_URL", "").rstrip("/") if langfuse else ""
    public = os.getenv("LANGFUSE_PUBLIC_KEY", "") if langfuse else ""
    secret = os.getenv("LANGFUSE_SECRET_KEY", "") if langfuse else ""
    if langfuse and any((lf_url, public, secret)) and not all((lf_url, public, secret)):
        logger.warning("Langfuse tracing is incomplete; configure base URL and both keys.")
    if not (endpoint or generic or (lf_url and public and secret)):
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        existing = trace.get_tracer_provider()
        if isinstance(existing, trace.ProxyTracerProvider):
            provider = TracerProvider(resource=Resource.create({"service.name": service}))
            trace.set_tracer_provider(provider)
        elif isinstance(existing, TracerProvider):
            provider = existing
        else:
            logger.warning("An external tracer provider is active; exporter setup skipped.")
            return
        configured: set[str] = getattr(provider, "_tatabot_exporters", set())
        if (endpoint or generic) and "otlp" not in configured:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            configured.add("otlp")
        if lf_url and public and secret and "langfuse" not in configured:
            token = base64.b64encode((public + ":" + secret).encode()).decode()
            exporter = OTLPSpanExporter(
                endpoint=lf_url + "/api/public/otel/v1/traces",
                headers={"Authorization": "Basic " + token, "x-langfuse-ingestion-version": "4"},
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            configured.add("langfuse")
        provider._tatabot_exporters = configured  # type: ignore[attr-defined]
        _provider = provider
    except Exception as exc:  # observability must not prevent service startup
        logger.warning("Telemetry setup failed (%s)", type(exc).__name__)


def shutdown() -> None:
    if _provider:
        _provider.force_flush(timeout_millis=5000)


async def http_span(request, call_next, service: str):
    # No raw path, query, request headers, bodies or exception messages are exported.
    context = propagate.extract(
        {
            "traceparent": request.headers.get("traceparent", ""),
            "tracestate": request.headers.get("tracestate", ""),
        }
    )
    with tracer.start_as_current_span(
        service + ".http",
        context=context,
        kind=SpanKind.SERVER,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        span.set_attribute("http.request.method", request.method)
        turn_id = request.headers.get("x-tatabot-turn-id", "")
        if re.fullmatch(r"[0-9a-f]{32}", turn_id):
            span.set_attribute("tatabot.turn_id", turn_id)
            span.set_attribute("langfuse.trace.metadata.turn_id", turn_id)
        try:
            response = await call_next(request)
        except Exception:
            span.set_status(Status(StatusCode.ERROR))
            raise
        route = request.scope.get("route")
        if route and getattr(route, "path", None):
            span.set_attribute("http.route", route.path)
        span.set_attribute("http.response.status_code", response.status_code)
        if response.status_code >= 500:
            span.set_status(Status(StatusCode.ERROR))
        return response
