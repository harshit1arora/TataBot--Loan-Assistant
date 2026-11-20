"""Exercise privacy lifecycle against the lab's separate HTTP services."""
import os
import subprocess
import sys

import httpx

core = os.environ["CORE_URL"]
conversation = os.environ["CONVERSATION_URL"]
with httpx.Client(timeout=30) as c:
    registration = c.post(core + "/v1/customers", json={"name": "Privacy Fixture", "phone": "9887766554", "email": "privacy-fixture@example.test", "age": 33, "city": "Pune", "declared_monthly_income_rupees": 100000, "declared_credit_score": 750})
    registration.raise_for_status()
    cid = registration.json()["customer_id"]
    token = c.post(core + "/auth/token", json={"customer_id": cid, "phone": "9887766554"})
    token.raise_for_status()
    headers = {"Authorization": "Bearer " + token.json()["access_token"]}
    chat = c.post(conversation + "/chat", headers=headers, json={"message": "hello"})
    chat.raise_for_status()
    assert c.post(core + "/v1/privacy/withdraw", headers=headers).status_code == 200
    assert c.post(conversation + "/chat", headers=headers, json={"message": "hello"}).status_code == 403
    assert c.post(core + "/v1/privacy/erase", headers=headers, json={"confirm": "ERASE"}).status_code == 202
    subprocess.run([sys.executable, "-m", "core_service.worker", "--once"], cwd=os.environ["LAB_CORE_DIR"], env=dict(os.environ, DATABASE_URL=os.environ["LAB_CORE_DB"]), check=True)
    status = c.get(core + "/v1/privacy", headers=headers)
    status.raise_for_status()
    assert status.json()["status"] == "local_erased", status.text
    print("Privacy lifecycle passed over HTTP: withdrawal, revocation and retryable local erasure")
