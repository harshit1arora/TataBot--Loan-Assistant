#!/usr/bin/env python3
"""End-to-end smoke test against a running stack.

    CORE_URL=http://localhost:8000 CONVERSATION_URL=http://localhost:8001 \
        python scripts/smoke_test.py

Exercises the happy path plus the ownership and validation boundaries. Exits non-zero on
the first failed expectation, so it can gate a deploy.
"""
from __future__ import annotations

import os
import sys
from io import BytesIO

import httpx

CORE = os.environ.get("CORE_URL", "http://localhost:8000").rstrip("/")
CONV = os.environ.get("CONVERSATION_URL", "http://localhost:8001").rstrip("/")
AGENTS = os.environ.get("AGENTS_URL", "http://localhost:8004").rstrip("/")
AGENT_TOKEN = os.environ.get("AGENT_SERVICE_TOKEN", "agent-service-token-change-me")
CUSTOMER = ("CUST001", "9810000001")
OTHER = ("CUST002", "9810000002")

failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "ok  " if condition else "FAIL"
    print(f"  [{status}] {label}{(' — ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(label)


def payslip(net_pay: int = 85000) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, 760, "Payslip - March 2026")
    pdf.drawString(72, 740, "Employee Name: Smoke Test")
    pdf.drawString(72, 700, f"Net Pay: {net_pay}")
    pdf.save()
    return buffer.getvalue()


def token(client: httpx.Client, creds=CUSTOMER) -> dict:
    response = client.post(f"{CORE}/auth/token", json={"customer_id": creds[0], "phone": creds[1]})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> int:
    with httpx.Client(timeout=30) as client:
        print("health and readiness")
        check("core /health", client.get(f"{CORE}/health").status_code == 200)
        check("core /ready", client.get(f"{CORE}/ready").status_code == 200)
        check("conversation /ready", client.get(f"{CONV}/ready").status_code == 200)

        print("authentication boundaries")
        check("no token is rejected", client.get(f"{CORE}/v1/customers/me").status_code == 401)
        check(
            "wrong phone is rejected",
            client.post(f"{CORE}/auth/token", json={"customer_id": "CUST001", "phone": "9810000999"}).status_code
            == 401,
        )
        auth = token(client)
        other = token(client, OTHER)

        print("input validation")
        for label, body in (
            ("negative amount", {"requested_amount_rupees": -1, "tenure_months": 36}),
            ("zero tenure", {"requested_amount_rupees": 100000, "tenure_months": 0}),
            (
                "client-supplied rate",
                {"requested_amount_rupees": 100000, "tenure_months": 36, "annual_rate": 0},
            ),
        ):
            check(label, client.post(f"{CORE}/v1/applications", json=body, headers=auth).status_code == 422)
        check(
            "client-supplied state",
            client.post(f"{CONV}/chat", json={"message": "hi", "current_state": "sanction"}, headers=auth).status_code
            == 422,
        )

        print("conversation flow")
        body = client.post(f"{CONV}/chat", json={"message": "hello"}, headers=auth).json()
        session_id = body["session_id"]
        check("greeting", body["state"] == "awaiting_amount", body["state"])

        body = client.post(
            f"{CONV}/chat", json={"message": "I need 5 lakh for 36 months", "session_id": session_id}, headers=auth
        ).json()
        check("above-limit needs a document", body["state"] == "awaiting_document", body["state"])

        response = client.post(
            f"{CONV}/sessions/{session_id}/documents",
            files={"file": ("slip.pdf", payslip(), "application/pdf")},
            data={"doc_type": "salary_slip"},
            headers=auth,
        )
        check("upload accepted", response.status_code == 200, str(response.status_code))
        body = response.json()
        check("decided after extraction", body["state"] == "sanctioned", body["state"])
        check("sanction letter issued", bool(body["sanction_document_id"]))

        print("self-service onboarding and support")
        import time as _time

        new_phone = "9" + str(int(_time.time()))[-9:]
        registration = client.post(
            f"{CORE}/v1/customers",
            json={
                "name": "Smoke Test",
                "phone": new_phone,
                "email": "smoke.test@example.com",
                "age": 33,
                "city": "Indore",
                "declared_monthly_income_rupees": 120000,
                "declared_credit_score": 768,
            },
        )
        check("a new customer can register", registration.status_code == 201, str(registration.status_code))
        profile = registration.json()["profile"]
        check("derived limit is 6x declared income", profile["pre_approved_limit_paise"] == 720_000 * 100)
        check("limit is marked indicative", profile["limit_source"] == "indicative")
        check("score is marked self-declared", profile["score_source"] == "self_declared")

        new_auth = {
            "Authorization": "Bearer "
            + client.post(
                f"{CORE}/auth/token",
                json={"customer_id": registration.json()["customer_id"], "phone": new_phone},
            ).json()["access_token"]
        }
        decided = client.post(
            f"{CORE}/v1/applications",
            json={"requested_amount_rupees": 600000, "tenure_months": 36},
            headers=new_auth,
        ).json()
        check("their own numbers produce a decision", decided["decision"]["outcome"] == "approve")

        ticket = client.post(
            f"{CORE}/v1/support/messages",
            json={
                "name": "Smoke Test",
                "contact": new_phone,
                "topic": "application",
                "message": "Smoke test: please confirm the EMI shown in my application.",
            },
            headers=new_auth,
        )
        check("contact message is stored with a reference", ticket.status_code == 201 and ticket.json()["reference"].startswith("SUP-"))
        mine = client.get(f"{CORE}/v1/support/messages", headers=new_auth).json()
        check("the ticket is readable by its owner", len(mine) == 1)
        check(
            "and not by another customer",
            client.get(f"{CORE}/v1/support/messages", headers=auth).json() == [],
        )

        print("document access control")
        document_id = body["sanction_document_id"]
        signed = client.get(f"{CORE}/v1/documents/{document_id}/signed-url", headers=auth).json()
        download = client.get(f"{CORE}{signed['url']}")
        check("signed link downloads a pdf", download.status_code == 200 and download.content.startswith(b"%PDF-"))
        check(
            "another customer cannot read it",
            client.get(f"{CORE}/v1/documents/{document_id}", headers=other).status_code == 404,
        )
        check(
            "another customer cannot open the session",
            client.get(f"{CONV}/sessions/{session_id}", headers=other).status_code == 404,
        )
        check(
            "the audit log is not a public route",
            client.get(f"{CORE}/resource/mcp_audit.log").status_code == 404,
        )

        print("agent layer")
        try:
            health = client.get(f"{AGENTS}/health", timeout=3)
        except httpx.HTTPError:
            print("  [skip] agents service not running (set AGENTS_URL to include it)")
        else:
            check("agents /health", health.status_code == 200)
            graph = client.get(f"{AGENTS}/agent/graph").json()
            check(
                "graph has a router and four workers",
                graph["entry"] == "router" and len(graph["workers"]) == 4,
            )
            answer = client.post(
                f"{AGENTS}/agent/query",
                json={"question": "what is the emi on 5 lakh for 36 months", "customer_id": "CUST001"},
                headers={"x-service-token": AGENT_TOKEN},
            )
            check("agent query answered", answer.status_code == 200, str(answer.status_code))
            if answer.status_code == 200:
                body = answer.json()
                check("routed to the interest agent", body["route"] == ["interest"], str(body["route"]))
                check("quoted the core's EMI", "16,607" in body["answer"], body["answer"][:80])
                check("cites a source", bool(body["citations"]))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("all smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
