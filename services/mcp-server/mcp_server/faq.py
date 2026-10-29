"""FAQ knowledge base for the FAQ agent.

Ten answers, each with the source it comes from. Policy facts cite this repository's own
credit policy; process facts are labelled as general practice rather than legal advice,
because inventing a regulatory citation is worse than saying nothing.
"""
from __future__ import annotations

import re

STOPWORDS = {
    "a", "an", "the", "is", "are", "do", "does", "i", "my", "me", "for", "of", "to", "in",
    "on", "and", "or", "what", "how", "can", "will", "if", "it", "be", "with", "about",
    "much", "many", "you", "your", "we", "our", "get", "have", "has", "was", "were", "am",
    # "why" is deliberately NOT a stopword: it separates "why is a slip needed" from
    # "which documents do I need".
}

ENTRIES: list[dict] = [
    {
        "id": "eligibility-criteria",
        "question": "What are the eligibility criteria for a personal loan?",
        "keywords": ["eligibility", "eligible", "criteria", "qualify", "qualification", "score", "age"],
        "answer": (
            "Eligibility is decided by the credit policy: a credit score of at least 700, an age "
            "between 21 and 60, and a requested amount between ₹10,000 and ₹50,00,000 over 6 to 60 "
            "months. Above your pre-approved limit you also need income verified from a document."
        ),
        "source": "credit policy 2026.10-v1 (services/core/core_service/policy.py)",
    },
    {
        "id": "emi-calculation",
        "question": "How is the EMI calculated?",
        "keywords": ["emi", "calculation", "calculated", "monthly", "instalment", "installment", "interest", "rate"],
        "answer": (
            "EMI is the standard reducing-balance instalment: P × r × (1+r)^n / ((1+r)^n − 1), where r "
            "is the annual rate divided by 1200 and n is the tenure in months. Amounts are computed "
            "in paise and rounded once, so the figure on a sanction letter matches the schedule."
        ),
        "source": "services/core/core_service/money.py",
    },
    {
        "id": "documents-needed",
        "question": "Which documents do I need to provide?",
        "keywords": ["document", "documents", "upload", "salary", "slip", "payslip", "proof", "papers", "kyc"],
        "answer": (
            "For a request within your pre-approved limit, none. Above it, a salary slip is required "
            "so income can be verified. PDFs and images are accepted up to 5 MB; the file type is "
            "checked by its contents, not its name."
        ),
        "source": "services/core/core_service/services/documents.py",
    },
    {
        "id": "why-document-needed",
        "question": "Why is a salary slip needed for a higher amount?",
        "keywords": ["why", "document", "salary", "slip", "higher", "limit", "above", "declared"],
        "answer": (
            "Because the amount you declared is not proof of income. Above your pre-approved limit, "
            "the EMI must be no more than 50% of income that has been verified from a processed "
            "document. Your declared salary alone cannot unlock a higher amount."
        ),
        "source": "credit policy 2026.10-v1, FOIR rule",
    },
    {
        "id": "credit-score",
        "question": "Does my credit score affect the rate or the decision?",
        "keywords": ["credit", "score", "cibil", "bureau", "affect", "impact", "rate"],
        "answer": (
            "A score below 700 is declined outright. Above that, the score band selects the product "
            "and therefore the rate: 760+ qualifies for the prime product at 10.99%, 700+ for the "
            "standard product at 12.00%."
        ),
        "source": "OfferMart product catalogue + credit policy floor",
    },
    {
        "id": "processing-time",
        "question": "How long does approval take?",
        "keywords": ["time", "long", "take", "fast", "processing", "turnaround", "minutes", "hours"],
        "answer": (
            "The decision is immediate — it is computed during the conversation. If a document is "
            "needed, the decision follows as soon as the document is processed. This build makes no "
            "claim about disbursal timelines, because it does not disburse."
        ),
        "source": "this deployment's behaviour; no disbursal integration exists",
    },
    {
        "id": "decline-reasons",
        "question": "Why was my application declined?",
        "keywords": ["declined", "decline", "rejected", "reject", "refused", "why", "reason"],
        "answer": (
            "Every decision stores reason codes, so the reason is specific rather than generic: "
            "credit score below the floor, the amount exceeding twice your pre-approved limit, or the "
            "EMI exceeding 50% of verified income. The code and the policy version appear with the "
            "decision in your chat and on the status page."
        ),
        "source": "credit policy reason codes",
    },
    {
        "id": "contact-support",
        "question": "How do I contact support or raise a grievance?",
        "keywords": ["contact", "support", "grievance", "complain", "complaint", "help", "human", "agent", "call"],
        "answer": (
            "Use the Contact us panel in the chat: it logs your message and returns a reference you "
            "can quote. Formal complaints go to the grievance channel, which a lender must respond to "
            "under the RBI Fair Practices Code; the channel details in this demo are placeholders."
        ),
        "source": "RBI Fair Practices Code (process); placeholder channels in this build",
    },
    {
        "id": "data-privacy",
        "question": "What happens to my data?",
        "keywords": ["data", "privacy", "stored", "store", "share", "secure", "security", "dpdp"],
        "answer": (
            "Your records live in this deployment's database and object storage. Your credit score, "
            "limit and contact details are never sent to the language model — only a first name and a "
            "coarse band — and audit rows are stored with identifiers redacted."
        ),
        "source": "services/conversation/conversation_service/llm.py + services/core audit redaction",
    },
    {
        "id": "prepayment",
        "question": "Can I prepay or foreclose the loan?",
        "keywords": ["prepay", "prepayment", "foreclose", "foreclosure", "early", "close"],
        "answer": (
            "Prepayment terms are a product condition and this build does not implement them. In "
            "practice they are set out in the loan agreement, so read that rather than relying on a "
            "chat answer."
        ),
        "source": "not implemented in this build",
    },
]


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOPWORDS and len(word) > 2}


def search(query: str, limit: int = 3) -> list[dict]:
    """Keyword overlap with a light boost for question words. No embeddings, no network."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    scored: list[tuple[float, dict]] = []
    for entry in ENTRIES:
        entry_tokens = _tokens(entry["question"]) | set(entry["keywords"])
        overlap = query_tokens & entry_tokens
        if not overlap:
            continue
        # Coverage of the query, plus a small bonus for how much of the entry was matched,
        # so a precise entry beats a broad one on the same tokens.
        score = len(overlap) / (len(query_tokens) ** 0.5)
        score += 0.3 * (len(overlap) / max(len(entry_tokens), 1))
        if any(word in entry["question"].lower() for word in query_tokens):
            score += 0.25
        scored.append((score, entry))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "id": entry["id"],
            "question": entry["question"],
            "answer": entry["answer"],
            "source": entry["source"],
            "score": round(score, 3),
        }
        for score, entry in scored[:limit]
    ]
