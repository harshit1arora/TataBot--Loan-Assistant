"""Exercise the complete pilot against running services using dedicated test identities.

CORE_URL, CONVERSATION_URL, PILOT_APPLICANT_TOKEN, PILOT_REVIEWER_TOKEN, PILOT_PHONE.
Use a fresh synthetic applicant with a verified +91 mobile number.
"""

from __future__ import annotations

import json
import os
from io import BytesIO

import httpx
from reportlab.pdfgen import canvas

from agent_quality import model_cost


def main() -> None:
    core = os.getenv("CORE_URL", "http://localhost:8000")
    conversation = os.getenv("CONVERSATION_URL", "http://localhost:8001")
    reviewer = {"Authorization": "Bearer " + os.environ["PILOT_REVIEWER_TOKEN"]}
    provider = {"Authorization": "Bearer " + os.environ["PILOT_APPLICANT_TOKEN"]}
    phone = os.environ["PILOT_PHONE"]
    with httpx.Client(timeout=50) as client:

        def post(path, headers, **kwargs):
            res = client.post(core + path, headers=headers, **kwargs)
            res.raise_for_status()
            return res.json()

        enrolled = post(
            "/auth/verified",
            provider,
            json={
                "consent_version": "income-assessment-v1",
                "profile": {
                    "name": "Pilot Borrower",
                    "phone": phone,
                    "email": "pilot@example.test",
                    "city": "Pune",
                    "age": 34,
                    "declared_monthly_income_rupees": 60_000,
                    "declared_credit_score": 745,
                },
            },
        )
        customer = {"Authorization": "Bearer " + enrolled["access_token"]}
        turn = client.post(
            conversation + "/chat",
            headers=customer,
            json={
                "message": "Am I eligible for 5 lakh over 36 months, what is the EMI, which documents do I need, and what is your privacy policy?"
            },
        )
        turn.raise_for_status()
        body = turn.json()
        assert set(body["agent_route"]) == {"eligibility", "interest", "document", "faq"}, body
        trace = client.get(
            conversation + "/sessions/" + body["session_id"] + "/trace", headers=customer
        ).json()
        evidence = next(t for t in trace["turns"] if t["trace_id"] == body["trace_id"])
        if os.getenv("REQUIRE_LIVE_GEMINI") == "1":
            assert evidence["router"] == "llm:gemini" and evidence["router_detail"]["model"], (
                evidence["router"]
            )
        workers = evidence["workers"]
        assert set(workers) == set(body["agent_route"])
        assert max(w["started_at"] for w in workers.values()) < min(
            w["finished_at"] for w in workers.values()
        )
        assert all(any(t["status"] == "ok" for t in w["tools"]) for w in workers.values())
        assert client.get(core + "/v1/quotes/" + body["quote_id"], headers=customer).is_success
        options = post(
            "/v1/quotes/compare",
            customer,
            json={
                "scenarios": [
                    {"amount_rupees": 500000, "tenure_months": 36},
                    {"amount_rupees": 500000, "tenure_months": 48},
                ]
            },
        )
        assert options[0]["emi_paise"] > options[1]["emi_paise"]
        assert options[0]["total_interest_paise"] < options[1]["total_interest_paise"]
        quote = options[0]
        accept_url = "/v1/quotes/" + quote["quote_id"] + "/accept"
        assert client.post(
            core + "/v1/quotes/" + quote["quote_id"] + "/accept", headers=reviewer
        ).status_code in (401, 403)
        applied = post(accept_url, customer)["application"]
        app_id = applied["application_id"]
        assert applied["status"] == "document_required"
        assert post(accept_url, customer)["application"]["application_id"] == app_id
        pdf_bytes = BytesIO()
        pdf = canvas.Canvas(pdf_bytes)
        pdf.drawString(
            40, 740, "Monthly net remuneration: eighty-five thousand rupees. Payroll attestation."
        )
        pdf.save()
        document = post(
            "/v1/documents",
            customer,
            data={"application_id": app_id, "doc_type": "salary_slip"},
            files={"file": ("payroll.pdf", pdf_bytes.getvalue(), "application/pdf")},
        )
        review_path = "/v1/reviews/" + document["document_id"]
        assessment = post(
            f"/v1/applications/{app_id}/documents/{document['document_id']}/assess", customer
        )
        assert assessment["requires_review"]
        assert client.get(core + "/v1/reviews", headers=provider).status_code == 403
        queue = client.get(core + "/v1/reviews", headers=reviewer)
        queue.raise_for_status()
        assert any(item["application_id"] == app_id for item in queue.json())
        assert post(review_path + "/claim", reviewer)["owner"] == "staff-demo"
        stats = client.get(core + "/v1/operations", headers=reviewer)
        assert stats.status_code == 200 and stats.json()["pending_reviews"] >= 1
        assert "delivery_counts" in stats.json() and "agent_activity" in stats.json()
        assert "backup_monitor" in stats.json()
        ticket = post(
            "/v1/support/messages",
            customer,
            json={
                "name": "Pilot Borrower",
                "contact": "pilot@example.test",
                "topic": "grievance",
                "message": "Please review my application.",
            },
        )
        queue = client.get(core + "/v1/operations/support", headers=reviewer)
        assert any(item["reference"] == ticket["reference"] for item in queue.json())
        post("/v1/operations/support/" + ticket["reference"], reviewer, json={"action": "claim"})
        assert (
            post(
                "/v1/operations/support/" + ticket["reference"], reviewer, json={"action": "close"}
            )["status"]
            == "closed"
        )
        assert (
            client.get(core + review_path + "/file", headers=reviewer).content
            == pdf_bytes.getvalue()
        )
        resolution = {
            "action": "correct",
            "income_rupees": 85_000,
            "reason": "Monthly net income verified against payroll evidence.",
        }
        final = post(review_path, reviewer, json=resolution)["application"]
        assert final["application_id"] == app_id and final["status"] == "approved", final
        shadows = client.get(core + "/v1/operations/shadow", headers=reviewer)
        shadows.raise_for_status()
        shadow_rows = [row for row in shadows.json() if row["application_id"] == app_id]
        assert any(
            row["status"] == "scored" and row["policy_outcome"] == "approve" for row in shadow_rows
        ), shadow_rows
        scored = next(
            row
            for row in shadow_rows
            if row["status"] == "scored" and row["policy_outcome"] == "approve"
        )
        assert (
            abs(scored["baseline_log_odds"] + scored["age_shap_log_odds"] - scored["raw_margin"])
            < 1e-5
        )
        print(
            "Shadow",
            scored["model_sha256"],
            "score",
            scored["probability"],
            "policy",
            scored["policy_outcome"],
            "disagreement",
            scored["disagreement"],
        )
        assert client.post(core + review_path, headers=reviewer, json=resolution).status_code == 409
        notices = client.get(core + "/v1/notices", headers=customer).json()
        notice = next(item for item in notices if item["application_id"] == app_id)
        assert "approved" in notice["message"]
        post("/v1/notices/" + notice["id"] + "/read", customer)
        summary = client.get(core + f"/v1/applications/{app_id}/summary", headers=customer).json()
        assert any(item["event"] == "Income reviewed" for item in summary["timeline"])
        assert summary["income_source"] == "underwriter_verified"
        assert summary["consent_version"] == "income-assessment-v1"
        assert summary["quote"]["quote_id"] == quote["quote_id"]
        assert final["decision"]["emi_paise"] == quote["emi_paise"]
        traces = [evidence.get("router_detail", {}), *workers.values()]
        calls, cost = model_cost(traces, json.loads(os.getenv("BENCH_USD_PER_MILLION", "{}")))
        print(
            "Completed application agent cost",
            json.dumps({"applications": 1, "model_calls": len(calls), "estimated_usd": cost}),
        )
        letter = post(f"/v1/applications/{app_id}/sanction", customer)
        signed = client.get(
            core + f"/v1/documents/{letter['document_id']}/signed-url", headers=customer
        ).json()
        assert client.get(core + signed["url"]).content.startswith(b"%PDF")
        print(
            "Verified enrollment, parallel workers, quote comparison, replay, review authorization, decision and sanction PDF"
        )
        print(
            "Trace", body["trace_id"], "router", evidence["router"], "workers", ", ".join(workers)
        )
        print(
            "Application",
            app_id,
            "quote",
            quote["quote_id"],
            "outcome",
            final["decision"]["outcome"],
            "reason",
            final["decision"]["reason_codes"],
            "income_source",
            summary["income_source"],
        )


if __name__ == "__main__":
    main()
