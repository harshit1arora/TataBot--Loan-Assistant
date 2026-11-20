"""Version 1 synthetic routing, evidence and token-cost benchmark."""

import json
import math
import os
import re
import statistics
import time

import httpx

CASES = [
    ("privacy", "What is your privacy policy?", ["faq"], "CUST001"),
    ("emi", "What is the EMI for 2 lakh over 36 months?", ["interest"], "CUST001"),
    ("missing_identity", "Am I eligible for 2 lakh?", ["eligibility"], None),
    ("missing_amount", "Am I eligible?", ["eligibility"], "CUST001"),
    (
        "conflicting_income",
        "My salary slip says 90000 and my document says 123456. Which is verified?",
        ["document"],
        "CUST001",
    ),
    ("ambiguous", "Can you help?", ["faq"], "CUST001"),
    (
        "four_workers",
        "Am I eligible for 5 lakh over 36 months, what is the EMI, which documents do I need, and what is your privacy policy?",
        ["document", "eligibility", "faq", "interest"],
        "CUST001",
    ),
]


def model_cost(traces, rates):
    calls = [c for t in traces for c in t.get("model_calls", [])]
    known = all(c["model"] in rates and None not in (c["input"], c["output"]) for c in calls)
    cost = (
        sum(
            (c["input"] * rates[c["model"]][0] + c["output"] * rates[c["model"]][1]) / 1e6
            for c in calls
        )
        if known
        else None
    )
    return calls, cost


def run():
    rates = json.loads(os.getenv("BENCH_USD_PER_MILLION", "{}"))
    rows = []
    with httpx.Client(
        base_url=os.environ["AGENTS_URL"],
        timeout=60,
        headers={"x-service-token": os.environ["AGENT_SERVICE_TOKEN"]},
    ) as client:
        for _ in range(int(os.getenv("BENCH_REPEATS", "1"))):
            for name, question, expected, customer in CASES:
                start = time.monotonic()
                res = client.post(
                    "/agent/query", json={"question": question, "customer_id": customer}
                )
                res.raise_for_status()
                b = res.json()
                traces = [b["router_detail"], *b["worker_trace"].values()]
                calls, cost = model_cost(traces, rates)
                outcomes = [w["outcome"] for w in b["worker_trace"].values()]
                grounded = all(x != "error" for x in outcomes) and bool(b["answer"])
                if name == "conflicting_income":
                    grounded &= all(
                        value not in b["answer"].replace(",", "") for value in ("90000", "123456")
                    )
                if name.startswith("missing"):
                    grounded &= (
                        outcomes == ["needs_input"] and "approved" not in b["answer"].lower()
                    )
                if name in ("four_workers", "privacy"):
                    grounded &= (
                        b["data"].get("faq", {}).get("matches", [{}])[0].get("id") == "data-privacy"
                    )
                if name == "emi":
                    quote = b["data"].get("interest", {}).get("quote", {})
                    figures = {
                        round(float(v.replace(",", "")) * 100)
                        for v in re.findall(r"₹([\d,]+\.\d{2})", b["answer"])
                    }
                    trusted = {
                        quote.get(k)
                        for k in ("emi_paise", "total_payable_paise", "total_interest_paise")
                    }
                    trusted.add(b["data"]["interest"]["request"]["amount_rupees"] * 100)
                    grounded &= figures == trusted
                if name == "four_workers":
                    grounded &= all(
                        any(t["status"] == "ok" for t in w["tools"])
                        for w in b["worker_trace"].values()
                    )
                rows.append(
                    dict(
                        case=name,
                        workers=len(b["route"]),
                        route_ok=set(expected) == set(b["route"]),
                        evidence_ok=grounded,
                        latency_ms=round((time.monotonic() - start) * 1000),
                        fallback=any(
                            t.get("fallback") not in (None, "rules_configured") for t in traces
                        ),
                        router=b["decided_by"],
                        calls=calls,
                        estimated_usd=cost,
                    )
                )
    if not rows:
        raise ValueError("BENCH_REPEATS must be positive")
    groups = {}
    for count in sorted({r["workers"] for r in rows}):
        times = sorted(r["latency_ms"] for r in rows if r["workers"] == count)
        groups[count] = dict(n=len(times), p95_ms=times[math.ceil(0.95 * len(times)) - 1])
    print(
        json.dumps(
            dict(
                version=1,
                results=rows,
                route_accuracy=statistics.mean(r["route_ok"] for r in rows),
                fallback_rate=statistics.mean(r["fallback"] for r in rows),
                latency_by_workers=groups,
            )
        )
    )
    if not all(r["route_ok"] and r["evidence_ok"] for r in rows):
        raise SystemExit("Quality regression: see case results")


if __name__ == "__main__":
    run()
