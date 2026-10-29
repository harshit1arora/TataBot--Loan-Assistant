"""FAQ worker — answers from the policy knowledge base, with the source attached."""
from __future__ import annotations

from .base import Worker


class FaqWorker(Worker):
    name = "faq"
    description = "Policy and process questions: criteria, documents, privacy, grievances."

    async def run(self, state: dict) -> dict:
        question = state["question"]
        result, error = await self.safe_call("search_faq", query=question, limit=2)

        if error or not result:
            return {
                "steps": [f"faq: search failed ({error})"],
                "results": {
                    "faq": {
                        "kind": "error",
                        "answer": "I don't have a sourced answer for that, and I won't improvise "
                        "on policy. The Contact us panel will get a human involved.",
                    }
                },
            }

        matches = result.get("results") or []
        if not matches:
            return {
                "steps": ["faq: no matching entry"],
                "results": {
                    "faq": {
                        "kind": "no_match",
                        "answer": "I don't have a sourced answer for that in the knowledge base. "
                        "Ask me about eligibility, EMI, documents, privacy or grievances — or use "
                        "Contact us for anything else.",
                    }
                },
            }

        top = matches[0]
        answer = await self.phrase(
            instruction="You are the FAQ agent. Answer using the sourced entry below.",
            tool_output={"entry": top},
            fallback=top["answer"],
        )
        return {
            "steps": [f"faq: matched '{top['id']}' (score {top['score']})"],
            "results": {
                "faq": {
                    "kind": "answer",
                    "answer": answer,
                    "data": {"matches": matches},
                    "citations": [top["source"]],
                }
            },
        }
