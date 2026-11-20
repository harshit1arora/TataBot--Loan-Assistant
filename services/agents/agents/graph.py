"""The LangGraph state graph.

    router ──┬─▶ eligibility ─┐
             ├─▶ interest ────┤
             ├─▶ document ────┼─▶ synthesise ─▶ END
             └─▶ faq ─────────┘

The router fans out to the chosen workers with conditional edges returning a list of node
names; LangGraph runs them in the same superstep and merges their writes through the state
reducers. Every worker then converges on `synthesise`, so the answer is always assembled in
one place.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from langgraph.graph import END, StateGraph
from opentelemetry.trace import StatusCode

from .config import Settings
from .llm import LLM, RuleBasedLLM
from .mcp_client import McpToolbox
from .observability import tracer
from .router import Router
from .state import AgentState
from .telemetry import active_worker, deadline, router_event
from .workers.document import DocumentWorker
from .workers.eligibility import EligibilityWorker
from .workers.faq import FaqWorker
from .workers.interest import InterestWorker

logger = logging.getLogger("agents.graph")

WORKER_CLASSES = {
    "eligibility": EligibilityWorker,
    "interest": InterestWorker,
    "document": DocumentWorker,
    "faq": FaqWorker,
}


class AgentGraph:
    def __init__(
        self,
        settings: Settings,
        llm: LLM | None = None,
        toolbox: McpToolbox | None = None,
        *,
        llms: dict[str, LLM] | None = None,
    ) -> None:
        """Build the graph.

        `llms` maps a role ("router", "eligibility", …) to its own model client, which is
        how each role ends up on a different API key. Passing a single `llm` keeps the
        simple path for tests: every role shares it.
        """
        if toolbox is None:
            raise ValueError("a McpToolbox is required")
        self.settings = settings
        self.toolbox = toolbox
        self.llms = llms or {role: (llm or RuleBasedLLM()) for role in ("router", *WORKER_CLASSES)}
        self.llm = self.llms["router"]
        self.router = Router(self.llm, settings)
        self.workers = {name: cls(toolbox, self.llms[name]) for name, cls in WORKER_CLASSES.items()}
        self.graph = self._build()

    def llm_summary(self) -> dict[str, str]:
        """Which model each role is using. No keys, no secrets."""
        return {
            role: (client.name if getattr(client, "available", False) else "rules")
            for role, client in self.llms.items()
        }

    # -- nodes -------------------------------------------------------------
    async def router_node(self, state: AgentState) -> dict:
        event: dict = {}
        token = router_event.set(event)
        try:
            with tracer.start_as_current_span(
                "agent.router",
                attributes={"langfuse.observation.type": "agent"},
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                workers, reason, decided_by = await self.router.route(state["question"])
                span.set_attribute("tatabot.route", workers)
                span.set_attribute("tatabot.router", decided_by)
                if event.get("fallback"):
                    span.set_attribute("tatabot.fallback", event["fallback"])
        finally:
            router_event.reset(token)
        return {
            "route": workers,
            "route_reason": reason,
            "decided_by": decided_by,
            "router_detail": event,
            "steps": [f"router ({decided_by}): {', '.join(workers)} — {reason}"],
        }

    def _worker_node(self, name: str):
        async def node(state: AgentState) -> dict:
            record: dict = {
                "started_at": datetime.now(UTC).isoformat(),
                "tools": [],
                "wording": "template",
            }
            token = active_worker.set(record)
            try:
                with tracer.start_as_current_span(
                    "agent." + name,
                    attributes={"langfuse.observation.type": "agent", "tatabot.agent": name},
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        output = await asyncio.wait_for(
                            self.workers[name].run(dict(state)),
                            max(0.01, deadline.get() - time.monotonic()),
                        )
                    except Exception:
                        span.set_status(StatusCode.ERROR)
                        span.set_attribute("tatabot.outcome", "error")
                        raise
                    span.set_attribute(
                        "tatabot.outcome", output["results"][name].get("kind", "unknown")
                    )
                output["results"][name]["trace"] = record
                return output
            except Exception as exc:  # noqa: BLE001 - one worker failing must not kill the turn
                logger.exception("worker %s failed", name)
                return {
                    "steps": [f"{name}: crashed ({type(exc).__name__})"],
                    "results": {
                        name: {
                            "trace": record,
                            "kind": "error",
                            "answer": "That part of the answer failed. The other agents' findings "
                            "still stand.",
                        }
                    },
                }

            finally:
                record["finished_at"] = datetime.now(UTC).isoformat()
                active_worker.reset(token)

        return node

    async def synthesise_node(self, state: AgentState) -> dict:
        """Assemble one answer from however many workers ran."""
        results: dict = state.get("results", {})
        route: list[str] = state.get("route", [])
        ordered = [name for name in route if name in results]

        answers = [results[name] for name in ordered if results[name].get("answer")]
        citations: list[str] = []
        for name in ordered:
            citations.extend(results[name].get("citations", []))
        # de-duplicate, keep order
        citations = list(dict.fromkeys(citations))

        needs_input: list[str] = []
        for name in ordered:
            needs_input.extend(results[name].get("missing", []))

        if not answers:
            answer = (
                "I couldn't produce an answer for that. Try asking about eligibility, EMI, "
                "documents, or a policy question — or use Contact us."
            )
        elif len(answers) == 1:
            answer = answers[0]["answer"]
        else:
            # Multi-domain question: label each part so the customer can see the reasoning.
            parts = []
            for name in ordered:
                if results[name].get("answer"):
                    parts.append(f"{name.capitalize()}: {results[name]['answer']}")
            answer = "\n\n".join(parts)

        return {
            "answer": answer,
            "citations": citations,
            "needs_input": list(dict.fromkeys(needs_input)),
        }

    # -- wiring ------------------------------------------------------------
    def _build(self):
        graph = StateGraph(AgentState)
        graph.add_node("router", self.router_node)
        for name in WORKER_CLASSES:
            graph.add_node(name, self._worker_node(name))
        graph.add_node("synthesise", self.synthesise_node)

        graph.set_entry_point("router")
        graph.add_conditional_edges(
            "router",
            lambda state: state["route"],
            list(WORKER_CLASSES),
        )
        for name in WORKER_CLASSES:
            graph.add_edge(name, "synthesise")
        graph.add_edge("synthesise", END)
        return graph.compile()

    async def run(
        self, question: str, customer_id: str | None = None, document_id: str | None = None
    ) -> dict:
        from .state import new_state

        initial = new_state(question, customer_id, document_id)
        token = deadline.set(time.monotonic() + self.settings.turn_deadline_seconds)
        try:
            with tracer.start_as_current_span(
                "agent.orchestrate",
                attributes={"langfuse.observation.type": "chain"},
                record_exception=False,
                set_status_on_exception=False,
            ):
                return await self.graph.ainvoke(initial)
        finally:
            deadline.reset(token)

    def topology(self) -> dict:
        """Exposed so the routing can be inspected without reading the source."""
        return {
            "entry": "router",
            "nodes": ["router", *WORKER_CLASSES.keys(), "synthesise"],
            "edges": [
                {"from": "router", "to": list(WORKER_CLASSES), "type": "conditional (fan-out)"},
                *[{"from": name, "to": "synthesise", "type": "direct"} for name in WORKER_CLASSES],
                {"from": "synthesise", "to": "END", "type": "direct"},
            ],
            "workers": {name: cls.description for name, cls in WORKER_CLASSES.items()},
        }
