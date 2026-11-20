"""Model spans retain usage and omit prompts and responses."""

import asyncio
from types import SimpleNamespace

from agents.llm import GeminiLLM
from agents.telemetry import router_event
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_model_span_records_usage_without_content():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    class Models:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(
                text="confidential model answer",
                usage_metadata=SimpleNamespace(prompt_token_count=12, total_token_count=19),
            )

    llm = GeminiLLM.__new__(GeminiLLM)
    llm.name = "gemini"
    llm.available = True
    llm.role = "router"
    llm.settings = SimpleNamespace(
        gemini_model="gemini-test", llm_timeout_seconds=3, llm_max_output_tokens=50
    )
    llm._client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    token = router_event.set({})
    try:
        assert (
            asyncio.run(llm.complete("confidential customer question"))
            == "confidential model answer"
        )
    finally:
        router_event.reset(token)
    span = next(span for span in exporter.get_finished_spans() if span.name == "model.generate")
    assert span.attributes["gen_ai.request.model"] == "gemini-test"
    assert span.attributes["gen_ai.usage.input_tokens"] == 12
    assert span.attributes["gen_ai.usage.output_tokens"] == 7
    assert span.attributes["langfuse.observation.type"] == "generation"
    assert "confidential" not in str(span.attributes)

    class FailingModels:
        async def generate_content(self, **kwargs):
            raise RuntimeError("confidential provider detail")

    llm._client = SimpleNamespace(aio=SimpleNamespace(models=FailingModels()))
    try:
        asyncio.run(llm.complete("confidential customer question"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("Expected provider failure")
    failed = exporter.get_finished_spans()[-1]
    assert failed.attributes["tatabot.model.status"] == "failed"
    assert not failed.events and "confidential" not in str(failed.attributes)
