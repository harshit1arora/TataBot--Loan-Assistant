"""The router node — the part that makes this an LLM orchestrator.

It chooses which workers to run for a question. Two paths:

* **LLM path** (Groq Llama 3.3 or Gemini): a strict JSON contract, validated against the
  allowed worker set. An invalid or unknown answer is discarded, not partially trusted.
* **Rule path** (default, and the fallback): keyword scoring over each worker's scope.

Both paths produce the same shape, so the graph behaves identically either way — which is
also what makes it testable without a model.
"""
from __future__ import annotations

import json
import logging
import re

from .config import Settings
from .llm import LLM, LlmUnavailable
from .parsing import parse_amount_rupees

logger = logging.getLogger("agents.router")

WORKERS: dict[str, str] = {
    "eligibility": "whether an amount would be approved or declined, and why",
    "interest": "EMI, interest rate, total repayment, cost of borrowing",
    "document": "salary slip or document verification, uploads, what documents are needed",
    "faq": "policy and process questions: criteria, privacy, grievances, prepayment, timelines",
}

KEYWORDS: dict[str, tuple[str, ...]] = {
    "eligibility": (
        "eligible", "eligibility", "qualify", "approve", "approval", "approved", "reject",
        "decline", "declined", "can i get", "will i get", "would i get", "chances", "sanction",
        "can i borrow", "how much can i", "loan amount", "get a loan", "qualify for",
    ),
    "interest": (
        "emi", "interest", "rate", "instalment", "installment", "monthly", "repay", "repayment",
        "cost", "total payable", "quote",
    ),
    "document": (
        "document", "documents", "slip", "payslip", "salary slip", "upload", "verify",
        "verification", "ocr", "proof", "statement",
    ),
    "faq": (
        "policy", "privacy", "data", "grievance", "complain", "complaint", "prepay",
        "foreclose", "how long", "time", "criteria", "cibil", "bureau", "score",
    ),
}

ROUTER_SYSTEM = (
    "You route questions in a personal-loan system to specialist agents. "
    "Reply with JSON only, no prose."
)


def rule_route(question: str, max_workers: int) -> tuple[list[str], str]:
    """Keyword scoring. Always returns at least one worker."""
    text = (question or "").lower()
    scores: dict[str, int] = {}
    for worker, keywords in KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits:
            scores[worker] = hits

    if not scores:
        # An amount plus loan framing is an eligibility question even without the word
        # "eligible" — "would I get 5 lakh" is asking the policy, not the FAQ.
        if parse_amount_rupees(text) is not None and any(
            word in text for word in ("loan", "borrow", "apply", "get")
        ):
            return ["eligibility"], "amount + loan framing: eligibility by inference"
        return ["faq"], "no domain keywords: defaulting to the FAQ agent"

    ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    chosen = [worker for worker, _score in ranked[:max_workers]]
    reason = "keyword match: " + ", ".join(f"{worker}={score}" for worker, score in ranked[:max_workers])
    return chosen, reason


def build_router_prompt(question: str, max_workers: int) -> str:
    catalogue = "\n".join(f"- {name}: {scope}" for name, scope in WORKERS.items())
    return (
        f"Available agents:\n{catalogue}\n\n"
        f"Question: {question[:400]}\n\n"
        "Choose the agents needed to answer it, at most "
        f"{max_workers}. Return JSON exactly like: "
        '{"agents": ["eligibility"], "reason": "asks whether 5 lakh would be approved"}'
    )


def validate_route(payload: dict, max_workers: int) -> tuple[list[str], str]:
    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("router returned no agents")
    chosen: list[str] = []
    for name in agents:
        if not isinstance(name, str):
            raise ValueError("router returned a non-string agent")
        normalised = name.strip().lower()
        if normalised not in WORKERS:
            raise ValueError(f"router invented an agent: {normalised}")
        if normalised not in chosen:
            chosen.append(normalised)
    reason = str(payload.get("reason", ""))[:200]
    return chosen[:max_workers], reason or "chosen by the model"


class Router:
    def __init__(self, llm: LLM, settings: Settings) -> None:
        self.llm = llm
        self.settings = settings

    async def route(self, question: str) -> tuple[list[str], str, str]:
        """Returns (workers, reason, decided_by)."""
        if self.llm.available:
            try:
                payload = await self.llm.complete_json(
                    build_router_prompt(question, self.settings.max_workers_per_turn),
                    system=ROUTER_SYSTEM,
                )
                workers, reason = validate_route(payload, self.settings.max_workers_per_turn)
                return workers, reason, f"llm:{self.llm.name}"
            except (LlmUnavailable, ValueError, json.JSONDecodeError) as exc:
                logger.warning("router fell back to rules: %s", str(exc)[:120])
            except Exception as exc:  # noqa: BLE001 - a model must never break routing
                logger.warning("router error (%s), using rules", type(exc).__name__)

        workers, reason = rule_route(question, self.settings.max_workers_per_turn)
        return workers, reason, "rules"


def mentions_multiple_domains(question: str) -> bool:
    text = (question or "").lower()
    return sum(1 for keywords in KEYWORDS.values() if any(k in text for k in keywords)) > 1


def strip_json_fence(text: str) -> str:
    """Tolerate models that wrap JSON in a markdown fence."""
    return re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
