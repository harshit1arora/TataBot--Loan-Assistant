"""Document worker — verification state, and what is needed when nothing is uploaded."""
from __future__ import annotations

import re

from ..formatting import inr
from .base import Worker

DOC_ID = re.compile(r"\b([0-9a-f]{16,32})\b")


class DocumentWorker(Worker):
    name = "document"
    description = "Status of an uploaded salary slip, and which documents are required."

    async def run(self, state: dict) -> dict:
        question = state["question"]
        customer_id = state.get("customer_id")
        document_id = state.get("document_id")

        if document_id is None:
            match = DOC_ID.search(question)
            document_id = match.group(1) if match else None

        if document_id:
            document, error = await self.safe_call(
                "get_document_verification", document_id=document_id
            )
            if error or document is None:
                return {
                    "steps": [f"document: lookup failed ({error})"],
                    "results": {
                        "document": {
                            "kind": "error",
                            "answer": "I couldn't find that document. If you uploaded it in this "
                            "conversation, try again from the upload button.",
                        }
                    },
                }

            if document["requires_review"]:
                fallback = (
                    "I have the file, but I couldn't read the salary figure confidently enough to "
                    "use it, so it's queued for review. Nothing was assumed."
                )
            elif document["verified_income_paise"]:
                fallback = (
                    "That document is verified. Income of "
                    f"{inr(document['verified_income_paise'])} per month has been read from it "
                    f"(confidence {document['extraction_confidence']:.0%})."
                )
            else:
                fallback = f"That document is {document['status']} but has not produced verified income."

            answer = await self.phrase(
                instruction="You are the document agent. Report the verification state.",
                tool_output=document,
                fallback=fallback,
            )
            return {
                "steps": [f"document: get_document_verification -> {document['status']}"],
                "results": {
                    "document": {
                        "kind": "answer",
                        "answer": answer,
                        "data": document,
                        "citations": ["core extraction"],
                    }
                },
            }

        # No document referenced: explain the requirement, and the customer's current state.
        faq, _ = await self.safe_call("search_faq", query="which documents do I need", limit=1)
        summary, _ = (
            await self.safe_call("get_customer_summary", customer_id=customer_id)
            if customer_id
            else (None, None)
        )
        verified = (summary or {}).get("verified_income_paise")
        payload = {"faq": faq or {}, "customer": summary or {}}

        if verified:
            fallback = (
                f"Income of {inr(verified)} per month is already verified from a document, so "
                "amounts above your limit can be assessed without another upload."
            )
        else:
            faq_answer = ((faq or {}).get("results") or [{}])[0].get("answer", "")
            fallback = (
                "Nothing is needed within your available limit. Above it, a salary slip is "
                "required so income can be verified — PDF or image, up to 5 MB. "
                + faq_answer
            ).strip()

        answer = await self.phrase(
            instruction="You are the document agent. Explain which documents are needed and why.",
            tool_output=payload,
            fallback=fallback,
        )
        return {
            "steps": ["document: explained requirements"],
            "results": {
                "document": {
                    "kind": "answer",
                    "answer": answer,
                    "data": payload,
                    "citations": ["core extraction"],
                }
            },
        }
