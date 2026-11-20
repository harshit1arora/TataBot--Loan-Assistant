"""Local OTLP receiver used by the integration lab; no external services."""

import base64
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest


class Collector(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.records = []
        self.lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        request = ExportTraceServiceRequest()
        request.ParseFromString(data)
        path = self.path
        auth = self.headers.get("Authorization", "")
        with self.server.lock:
            for resource in request.resource_spans:
                for scope in resource.scope_spans:
                    for span in scope.spans:
                        self.server.records.append(
                            (path, auth, span, self.headers.get("x-langfuse-ingestion-version", ""))
                        )
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()
        self.wfile.write(b"")

    def log_message(self, *_):
        pass


def fixture(env, langfuse_only=False):
    server = Collector()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    env.update(
        OTEL_BSP_SCHEDULE_DELAY="250",
        LANGFUSE_BASE_URL=base,
        LANGFUSE_PUBLIC_KEY="test-public",
        LANGFUSE_SECRET_KEY="test-secret",
    )
    if langfuse_only:
        env.pop("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", None)
        env.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    else:
        env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = base + "/v1/traces"
    return server


def verify(server, turn_id, langfuse_only=False):
    from collections import defaultdict
    import time

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        with server.lock:
            records = list(server.records)
        paths = {path for path, _, _, _ in records}
        by_trace = defaultdict(list)
        for path, auth, span, version in records:
            if path == ("/api/public/otel/v1/traces" if langfuse_only else "/v1/traces"):
                by_trace[span.trace_id].append(span)
        expected = {
            "conversation.http",
            "core.http",
            "agents.http",
            "agent.orchestrate",
            "agent.router",
            "agent.eligibility",
            "agent.interest",
            "agent.document",
            "agent.faq",
        }
        if langfuse_only:
            expected -= {"conversation.http", "core.http"}
        matching = [
            spans
            for spans in by_trace.values()
            if expected <= {s.name for s in spans}
            and any(
                attribute.key == "tatabot.turn_id" and attribute.value.string_value == turn_id
                for span in spans
                for attribute in span.attributes
            )
        ]
        langfuse_spans = [span for path, _, span, _ in records if path == "/api/public/otel/v1/traces"]
        langfuse_ready = any(span.name == "agents.http" and any(attribute.key == "tatabot.turn_id"
                             and attribute.value.string_value == turn_id for attribute in span.attributes)
                             for span in langfuse_spans)
        if matching and langfuse_ready and any(span.name.startswith("tool.") for span in langfuse_spans):
            break
        time.sleep(0.5)
    else:
        raise AssertionError(
            f"Expected correlated agent spans and both exports, saw {len(records)} spans and {paths}"
        )
    langfuse = [
        (auth, span, version)
        for path, auth, span, version in records
        if path == "/api/public/otel/v1/traces"
    ]
    expected_auth = "Basic " + base64.b64encode(b"test-public:test-secret").decode()
    assert all(auth == expected_auth and version == "4" for auth, _, version in langfuse)
    assert any(span.name.startswith("tool.") for _, span, _ in langfuse)
    assert any(
        span.name == "agents.http"
        and any(
            attribute.key == "tatabot.turn_id" and attribute.value.string_value == turn_id
            for attribute in span.attributes
        )
        for _, span, _ in langfuse
    )
    spans = matching[0]
    agent_http = next(span for span in spans if span.name == "agents.http")
    orchestration = next(span for span in spans if span.name == "agent.orchestrate")
    if not langfuse_only:
        conversation = next(span for span in spans if span.name == "conversation.http")
        assert agent_http.parent_span_id == conversation.span_id
        assert any(
            span.name == "core.http" and span.parent_span_id == conversation.span_id
            for span in spans
        )
    assert orchestration.parent_span_id == agent_http.span_id
    assert all(
        any(
            span.name == "agent." + worker and span.parent_span_id == orchestration.span_id
            for span in spans
        )
        for worker in ("eligibility", "interest", "document", "faq")
    )
    assert any(span.trace_id == orchestration.trace_id for _, span, _ in langfuse)
    # No span or attribute may contain the synthetic customer, question, document or token.
    for _, _, span, _ in records:
        representation = span.name + str([(attribute.key, str(attribute.value)) for attribute in span.attributes])
        assert all(
            s not in representation
            for s in (
                "Pilot Borrower",
                "85000",
                "privacy policy",
                "pilot@example.test",
                "test-secret",
            )
        )
    name = "Langfuse-compatible" if langfuse_only else "OTLP and Langfuse-compatible"
    print(name + " receiver verified correlated four-agent spans and redaction.")
