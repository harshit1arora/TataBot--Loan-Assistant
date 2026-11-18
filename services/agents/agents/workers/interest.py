"""Interest worker — prices a loan.

Holds `quote_emi` and `get_preapproved_offer`. Every figure it reports comes from the tool
output; the model may only phrase the sentence.
"""
from __future__ import annotations

from ..formatting import inr, rupees
from ..parsing import parse_amount_rupees, parse_tenure_months
from .base import Worker

DEFAULT_TENURE = 36


class InterestWorker(Worker):
    name = "interest"
    description = "EMI, interest rate and total repayment for an amount and tenure."

    async def run(self, state: dict) -> dict:
        question = state["question"]
        customer_id = state.get("customer_id")
        amount = parse_amount_rupees(question)
        tenure = parse_tenure_months(question, DEFAULT_TENURE)

        if amount is None:
            return {
                "steps": ["interest: no amount in the question"],
                "results": {
                    "interest": {
                        "kind": "needs_input",
                        "missing": ["amount"],
                        "answer": "Tell me the amount and tenure and I'll price it — for example "
                        "\"EMI on 3 lakh for 24 months\".",
                    }
                },
            }

        offer, _ = (
            await self.safe_call("get_preapproved_offer", customer_id=customer_id)
            if customer_id
            else (None, None)
        )
        product_code = (offer or {}).get("product", {}).get("code")

        if customer_id and not product_code:
            return {
                "steps": ["interest: no confirmed product for this customer"],
                "results": {"interest": {
                    "kind": "error",
                    "answer": "I could not confirm a product rate for your profile, so I cannot give a personalised EMI.",
                }},
            }

        quote, error = await self.safe_call(
            "quote_emi", amount_rupees=amount, tenure_months=tenure, product_code=product_code
        )
        if error or quote is None:
            return {
                "steps": [f"interest: quote failed ({error})"],
                "results": {
                    "interest": {
                        "kind": "error",
                        "answer": "I couldn't price that just now — the pricing service didn't "
                        "respond. I'd rather not quote a number I can't stand behind.",
                    }
                },
            }

        payload = {
            "request": {"amount_rupees": amount, "tenure_months": tenure},
            "quote": quote,
            "offer": offer or {},
        }
        fallback = (
            f"For {rupees(amount)} over {tenure} months at {quote['annual_rate_percent']}% p.a. "
            f"({quote['product_name']}), the EMI is {inr(quote['emi_paise'])}. You'd repay "
            f"{inr(quote['total_payable_paise'])} in total, of which "
            f"{inr(quote['total_interest_paise'])} is interest."
        )

        answer = fallback

        return {
            "steps": [f"interest: quote_emi -> {inr(quote['emi_paise'])}/month"],
            "results": {
                "interest": {
                    "kind": "answer",
                    "answer": answer + " This is an indicative product quote. The application uses the lending policy rate.",
                    "data": payload,
                    "citations": [f"OfferMart {quote['product_code']}"],
                }
            },
        }
