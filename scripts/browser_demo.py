"""Browser acceptance for a deployed TataBot or the isolated demo lab."""

import argparse
import os
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
        page = browser.new_page()
        page.goto(url.rstrip("/") + "/login")
        if local:
            page.locator("#customerId").fill("CUST001")
            page.locator("#phone").fill("9810000001")
            page.get_by_role("button", name="Continue").click()
        else:
            print("Sign in as your synthetic applicant in the browser.", flush=True)
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
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--local", action="store_true")
    args = parser.parse_args()
    run(args.url, args.local)
