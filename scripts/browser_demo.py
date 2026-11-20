"""Browser acceptance for a deployed TataBot or the isolated demo lab."""

import argparse
import json
import os
import secrets
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs

from reportlab.pdfgen import canvas
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


def run(url, local):
    if local and urlsplit(url).hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("Test login is restricted to loopback")
    if not local and urlsplit(url).scheme != "https":
        raise ValueError("Hosted verification requires HTTPS")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=local, executable_path=os.getenv("BROWSER_EXECUTABLE")
        )
        applicant = browser.new_context(ignore_https_errors=local)
        page = applicant.new_page()
        page.goto(url.rstrip("/") + "/identity")
        if local:
            page.get_by_role("link", name="applicant").click()
        else:
            print("Sign in with a fresh synthetic applicant.", flush=True)
        enroll = page.locator('input[name="name"]')
        enroll.wait_for(timeout=180000)
        for key, value in {
            "name": "Browser Applicant",
            "email": "browser@example.test",
            "age": "34",
            "city": "Pune",
            "income": "60000",
            "score": "745",
        }.items():
            page.locator(f'input[name="{key}"]').fill(value)
        page.get_by_role("checkbox").check()
        page.get_by_role("button", name="Create verified account").click()
        field = page.locator("#message")
        field.wait_for(timeout=180000)
        field.fill(
            "Am I eligible for 5 lakh over 36 months, what is the EMI, which documents do I need, and what is your privacy policy?"
        )
        with page.expect_response(
            lambda r: (
                r.request.method == "POST"
                and urlsplit(r.url).path.endswith("/chat")
                and "privacy policy" in (r.request.post_data or "")
            ),
            timeout=60000,
        ) as response:
            page.get_by_role("button", name="Send message").click()
        body = response.value.json()
        assert response.value.ok and len(set(body["agent_route"])) == 4
        expect(page.get_by_text(body["reply"][:45], exact=False).last).to_be_visible()
        trace = page.evaluate(
            """async (id) => {
          const response = await fetch('/sessions/' + id + '/trace',
            {headers:{Authorization:'Bearer '+ sessionStorage.getItem('tatabot.token')}});
          return response.json();
        }""",
            body["session_id"],
        )
        turn = next(t for t in trace["turns"] if t["trace_id"] == body["trace_id"])
        if not local:
            assert turn["router"] == "llm:gemini" and turn["router_detail"]["model"]
        print("Browser", turn["trace_id"], turn["router"], sorted(turn["workers"]), body["reply"])
        page.goto(url.rstrip("/") + "/scenarios")
        page.get_by_role("button", name="Compare", exact=True).click()
        page.get_by_role("button", name="Accept and apply").first.click()
        slip = page.get_by_label("Salary slip")
        slip.wait_for()
        app_id = parse_qs(urlsplit(page.url).query)["application"][0]
        now = datetime.now(UTC)
        current = now.year * 12 + now.month - 1
        credits = [
            {
                "date": f"{(current - i) // 12:04d}-{(current - i) % 12 + 1:02d}-01",
                "amount_paise": 8500000,
                "category": "salary",
            }
            for i in (3, 2, 1)
        ]
        page.get_by_label("Bank statement JSON").set_input_files(
            {
                "name": "statement.json",
                "mimeType": "application/json",
                "buffer": json.dumps(credits).encode(),
            }
        )
        page.get_by_label("I consent to use these statement details").check()
        with page.expect_response(
            lambda r: urlsplit(r.url).path.endswith("/bank-statement")
        ) as bank:
            page.get_by_role("button", name="Check statement").click()
        assert bank.value.ok and bank.value.json()["independently_verified"] is False
        stream = BytesIO()
        pdf = canvas.Canvas(stream)
        pdf.drawString(
            30, 740, "Monthly net remuneration: eighty-five thousand rupees. Payroll attestation."
        )
        pdf.save()
        with page.expect_response(lambda r: urlsplit(r.url).path.endswith("/assess")) as assessed:
            slip.set_input_files(
                {
                    "name": "browser-payroll.pdf",
                    "mimeType": "application/pdf",
                    "buffer": stream.getvalue(),
                }
            )
        assert assessed.value.ok and assessed.value.json()["requires_review"]
        reviewer = browser.new_context(ignore_https_errors=local)
        staff = reviewer.new_page()
        staff.goto(url.rstrip("/") + "/identity#review")
        if local:
            staff.get_by_role("link", name="reviewer").click()
        else:
            print("Sign in as the synthetic underwriter in the second window.", flush=True)
        staff.get_by_role("button", name=f"browser-payroll.pdf · Application {app_id}").click(
            timeout=180000
        )
        expect(staff.get_by_text("Bank statement:", exact=False)).to_contain_text("customer_mock")
        with staff.expect_download() as evidence:
            staff.get_by_role("button", name="Download evidence").click()
        assert Path(evidence.value.path()).read_bytes() == stream.getvalue()
        staff.get_by_label("Resolution").select_option("correct")
        staff.get_by_label("Verified monthly income").fill("85000")
        staff.get_by_label("Reason").fill(
            "Verified the monthly pay against the uploaded payroll attestation."
        )
        staff.get_by_role("button", name="Record review").click()
        expect(staff.get_by_role("status")).to_contain_text(f"Application {app_id} is approved")
        page.get_by_role("button", name="Refresh decision").click()
        expect(page.get_by_text("Verified monthly income", exact=False)).to_contain_text("85,000")
        expect(page.get_by_text("Bank comparison:", exact=False)).to_contain_text("matching")
        page.get_by_role("button", name="Issue sanction letter").click()
        with page.expect_download() as letter:
            page.get_by_role("button", name="Download sanction letter").click()
        assert Path(letter.value.path()).read_bytes().startswith(b"%PDF")
        print("Browser verified enrollment, review, approval and PDF for application", app_id)
        if local:
            phone = "9" + str(secrets.randbelow(10**9)).zfill(9)
            register = page.request.post(
                url + "/v1/customers",
                data={
                    "name": "Counterfactual Applicant",
                    "phone": phone,
                    "email": "scenario@example.test",
                    "city": "Pune",
                    "age": 34,
                    "declared_monthly_income_rupees": 60000,
                    "declared_credit_score": 745,
                },
            )
            assert register.ok, register.text()
            login = page.request.post(
                url + "/auth/token",
                data={"customer_id": register.json()["customer_id"], "phone": phone},
            )
            assert login.ok, login.text()
            token = login.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            created = page.request.post(
                url + "/v1/applications",
                headers=headers,
                data={"requested_amount_rupees": 500000, "tenure_months": 36},
            )
            assert created.ok, created.text()
            declined_id = created.json()["application_id"]
            slip_data = BytesIO()
            slip_pdf = canvas.Canvas(slip_data)
            slip_pdf.drawString(40, 740, "Employee Name: Synthetic Applicant")
            slip_pdf.drawString(40, 710, "Net Pay: 30000")
            slip_pdf.save()
            uploaded = page.request.post(
                url + "/v1/documents",
                headers=headers,
                multipart={
                    "application_id": declined_id,
                    "doc_type": "salary_slip",
                    "file": {
                        "name": "salary.pdf",
                        "mimeType": "application/pdf",
                        "buffer": slip_data.getvalue(),
                    },
                },
            )
            assert uploaded.ok, uploaded.text()
            assessed = page.request.post(
                url
                + "/v1/applications/"
                + declined_id
                + "/documents/"
                + uploaded.json()["document_id"]
                + "/assess",
                headers=headers,
            )
            assert assessed.ok and assessed.json()["application"]["status"] == "rejected", (
                assessed.text()
            )
            viewer = browser.new_context()
            viewer.add_init_script(
                "sessionStorage.setItem('tatabot.token', "
                + json.dumps(token)
                + "); sessionStorage.setItem('tatabot.expiresAt', String(Date.now()+3600000));"
            )
            decision_page = viewer.new_page()
            decision_page.goto(url + "/scenarios?application=" + declined_id)
            expect(
                decision_page.get_by_role(
                    "heading", name="Possible alternatives under current policy"
                )
            ).to_be_visible()
            expect(
                decision_page.get_by_text("Verified monthly income of at least", exact=False)
            ).to_be_visible()
            expect(decision_page.get_by_text("A maximum of", exact=False)).to_be_visible()
            expect(decision_page.get_by_text("A tenure of", exact=False)).to_be_visible()
            print("Browser verified declined application alternatives", declined_id)
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    run(args.url, args.local)
