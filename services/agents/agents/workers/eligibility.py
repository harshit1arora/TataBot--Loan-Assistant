"""Eligibility worker — explains what the credit policy would decide.

Holds one tool: `check_eligibility` (read-only). It cannot create an application, which is
why an agent can talk about eligibility without being able to act on it.
"""
from __future__ import annotations

from ..formatting import inr, reason_text, rupees
from ..parsing import parse_amount_rupees, parse_tenure_months
from .base import Worker

DEFAULT_TENURE = 36


class EligibilityWorker(Worker):
    name = "eligibility"
    description = "Whether a loan amount is likely to be approved, and why."

    async def run(self, state: dict) -> dict:
        question = state["question"]
        customer_id = state.get("customer_id")
        amount = parse_amount_rupees(question)
        tenure = parse_tenure_months(question, DEFAULT_TENURE)

        if not customer_id:
            return {
                "steps": ["eligibility: no customer in context"],
                "results": {
                    "eligibility": {
                        "kind": "needs_input",
                        "missing": ["customer"],
                        "answer": "I need to know who you are before I can check eligibility — "
                        "sign in, or share your customer ID.",
                    }
                },
                "needs_input": ["customer"],
            }

        if amount is None:
            summary, _ = await self.safe_call("get_customer_summary", customer_id=customer_id)
            limit = (summary or {}).get("pre_approved_limit_paise")
            limit_text = inr(limit) if isinstance(limit, int) else "your limit"
            return {
                "steps": ["eligibility: no amount in the question"],
                "results": {
                    "eligibility": {
                        "kind": "needs_input",
                        "missing": ["amount"],
                        "answer": f"Happy to check. What amount are you thinking of borrowing, "
                        f"and over how many months? Your indicative limit is {limit_text}.",
                    }
                },
                "needs_input": ["amount"],
            }

        decision, error = await self.safe_call(
            "check_eligibility",
            customer_id=customer_id,
            amount_rupees=amount,
            tenure_months=tenure,
        )
        if error or decision is None:
            return {
                "steps": [f"eligibility: tool failed ({error})"],
                "results": {
                    "eligibility": {
                        "kind": "error",
                        "answer": "I couldn't reach the credit policy just now, so I won't guess "
                        "at an outcome. Please try again in a moment.",
                    }
                },
            }

        summary, _ = await self.safe_call("get_customer_summary", customer_id=customer_id)
        # The amount and tenure are part of the facts the answer may mention, so they must
        # be in the payload the guard checks against — otherwise legitimate prose is
        # discarded for quoting the loan the customer just asked about.
        payload = {
            "request": {"amount_rupees": amount, "tenure_months": tenure},
            "decision": decision,
            # Readable wording, so the model does not parrot internal codes at a customer.
            "reasons_readable": [reason_text(code) for code in decision["reason_codes"]],
            "customer": summary or {},
        }

        outcome = decision["outcome"]
        reasons = ", ".join(reason_text(code) for code in decision["reason_codes"])
        amount_text = rupees(amount)
        if outcome == "approve":
            emi = decision.get("emi_paise")
            fallback = (
                f"Good news — {amount_text} over {tenure} months looks approvable: {reasons}. "
                + (f"The EMI would be about {inr(emi)}. " if emi else "")
                + f"Policy version {decision['policy_version']}."
            )
        elif outcome == "require_document":
            fallback = (
                f"{amount_text} is above your available limit, so this one needs your income "
                "verified from a salary slip before the policy can decide. Upload it in the chat "
                "and I'll re-run the check."
            )
        else:
            fallback = (
                f"On the current policy this would be declined: {reasons}. "
                "You can try a smaller amount or a longer tenure."
            )

        answer = await self.phrase(
            instruction=(
                "You are the eligibility agent, speaking to the customer. Explain what the credit "
                f"policy says about {amount_text} over {tenure} months. The outcome is {outcome}. "
                "Speak plainly: never print internal codes such as require_document or "
                "verified_income_document_required, and say what the customer should do next."
            ),
            tool_output=payload,
            fallback=fallback,
        )

        return {
            "steps": [f"eligibility: check_eligibility -> {outcome}"],
            "results": {
                "eligibility": {
                    "kind": "answer",
                    "answer": answer,
                    "data": payload,
                    "citations": [f"policy {decision['policy_version']}"],
                }
            },
        }
