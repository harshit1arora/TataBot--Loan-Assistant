# Screenshots — captured from a running stack

Every image below was taken from the real application: the SPA served as a production build,
the two FastAPI services running, and a real payslip PDF uploaded through the browser. Nothing
here is a mock or a design mock-up.

**How it was captured:** headless Chromium driven by Playwright against `127.0.0.1:8088`
(a static server plus a reverse proxy in front of `core-service:8000` and
`conversation-service:8001`), viewport 1440×900 at 2× for desktop and 390×844 at 3× for mobile.

**Demo paths used:**

* `CUST001` (Asha Verma, pre-approved ₹3,00,000) asks for ₹5,00,000 — above the limit — uploads a
  payslip with `Net Pay: 85000`, and is approved on the FOIR rule.
* `CUST004` (Vikram Singh, score 690) for the decline path.
* **A brand-new customer** registered through the UI with their own details (income ₹1,20,000,
  self-declared score 768). Their indicative limit is derived as ₹7,20,000, they ask for
  ₹6,00,000, and are approved on data that did not exist before the run.

---

## Landing page

| | |
|---|---|
| ![Full landing page](screenshots/00-landing-full.png) | **The whole landing page in one capture** (1440 px wide, 6,070 px tall). |
| ![Hero](screenshots/01-landing-hero.png) | **Hero.** Product position and the illustrative decision card. The chat preview is labelled as illustrative. |
| ![How it works](screenshots/02-how-it-works.png) | **The flow.** Four steps in the order the state machine enforces. |
| ![Capabilities](screenshots/03-capabilities.png) | **Capabilities.** Eight, each one traceable to code in this repo. |
| ![Architecture](screenshots/04-architecture.png) | **Architecture.** The boundary that matters: the conversational layer cannot read a record or decide. |
| ![Impact](screenshots/05-impact.png) | **Impact.** Per-organisation effects, with an explicit note that these are not measured business results. |
| ![EMI estimator](screenshots/06-emi-estimator.png) | **Estimator.** Client-side only; ₹3,00,000 at 12% over 36 months gives ₹9,964, matching the server's formula. |
| ![Security](screenshots/07-security.png) | **Security & governance.** The controls that get checked in review. |
| ![Footer](screenshots/08-footer.png) | **Footer.** Independence and simulation disclaimers. |
| ![Mobile landing](screenshots/15-mobile-landing.png) | **Mobile.** 390 px layout. |

## The application, end to end

| | |
|---|---|
| ![Sign in](screenshots/09-login.png) | **Sign in.** Demo identity: customer id + registered number exchanged for a 15-minute JWT. |
| ![Greeting](screenshots/10-chat-greeting.png) | **Session opened.** The greeting carries the real pre-approved limit from the customer record. |
| ![Document required](screenshots/11-chat-document-required.png) | **Above the limit.** ₹5,00,000 against a ₹3,00,000 limit returns `require_document` with the reason code and policy version. |
| ![Approved](screenshots/12-chat-approved.png) | **Approved after verification.** Income read from the payslip (₹85,000), EMI ₹16,607.15, reason `EMI is within 50% of verified income`, policy `2026.10-v1`, sanction letter available. |
| ![Sanction letter](screenshots/13-sanction-letter.png) | **The sanction letter PDF**, downloaded through a signed 60-second link and rendered here. Stamped as simulated. |
| ![Status tracker](screenshots/14-status-tracker.png) | **Status tracker.** Real application state, stages, decision and reason codes. |
| ![Declined](screenshots/17-chat-declined.png) | **Decline path.** Score below the floor, explained in customer language with a grievance route. |
| ![Mobile chat](screenshots/16-mobile-chat-approved.png) | **Mobile approval.** Same flow at 390 px. |

## Your own account, your own data

| | |
|---|---|
| ![Register](screenshots/18-register.png) | **Create account.** Real fields, written to the database. The derived limit (6 × income, capped) and the self-declared score are both stated on the form. |
| ![New customer chat](screenshots/19-new-customer-chat.png) | **Signed in as a new customer.** The greeting says *indicative* limit, not pre-approved, because the limit was derived. |
| ![Own data approval](screenshots/20-new-customer-approved.png) | **Decision on their numbers.** ₹6,00,000 approved, EMI ₹19,928.59, reason *Within your available limit*, policy `2026.10-v1`. Nothing about this customer existed before the run. |
| ![Status with applications](screenshots/23-status-applications.png) | **Their applications**, read back from the database. |
| ![Routing trace](screenshots/24-routing-trace.png) | **How the application moved.** Four transitions with the component behind each one — the orchestrator's routing, read back from the database. |

## The agent layer

Questions are routed by the LangGraph orchestrator; each reply shows which agents answered.

| | |
|---|---|
| ![Eligibility agent](screenshots/25-agent-eligibility.png) | **Eligibility agent.** "can I get 5 lakh for 36 months?" — routed to `eligibility`, answered from the policy via an MCP tool call, with the source attached. |
| ![Interest agent](screenshots/26-agent-interest.png) | **Interest agent.** "what would the EMI be on 5 lakh?" — priced by OfferMart at the customer's own product rate (12.00% standard for a 745 score), EMI ₹16,607.15. |
| ![FAQ agent](screenshots/27-agent-faq.png) | **FAQ agent.** A policy question answered from the knowledge base with its source. |
| ![Two agents](screenshots/28-agent-multi.png) | **Two agents, one question.** "can I get 2 lakh and what emi would that be?" — the router fans out to `eligibility` and `interest`; both answers are labelled. |
| ![Then an application](screenshots/29-agents-then-application.png) | **Then a statement.** "I need 2 lakh for 24 months" leaves the agent path and creates a real application: approved, EMI ₹9,414.69, sanction letter issued. |

## History and timestamps

Every message carries a time; the transcript is stored per customer and can be reopened.

| | |
|---|---|
| ![Timestamps](screenshots/30-chat-timestamps.png) | **Timestamps.** Each message shows its date and time, with a day separator when the date changes. |
| ![History list](screenshots/31-history-list.png) | **History panel.** Opened from the header, between Track status and Exit: past conversations with state, last message and message count. |
| ![Transcript](screenshots/32-history-transcript.png) | **A past transcript**, read back from the database with its original timestamps. |
| ![Resumed](screenshots/33-history-resumed.png) | **Continued.** "Continue this conversation" restores the transcript and the workflow state. |

## Contact us

| | |
|---|---|
| ![Contact panel](screenshots/21-contact-panel.png) | **Contact panel** opened from the chat header. Channels are labelled as placeholders. |
| ![Contact logged](screenshots/22-contact-logged.png) | **Message stored** — reference `SUP-PYZFYW`, topic `application`, status `open`, and the ticket appears in the customer's own list. |

Asking the assistant for a human ("can I talk to someone?") returns the same channels and opens
this panel without moving the workflow; that path is covered by
`services/conversation/tests/test_chat_flow.py`.

---

## Reproducing these

```bash
# 1. services
cd services/core && cp .env.example .env         # set JWT_SECRET + SERVICE_CLIENT_SECRET
pip install -r requirements-dev.txt && uvicorn core_service.main:app --port 8000
cd services/conversation && cp .env.example .env # same secrets
pip install -r requirements-dev.txt && uvicorn conversation_service.main:app --port 8001

# 2. web
cd apps/web && npm ci && npm run dev             # http://localhost:8080

# 3. drive it by hand, or with a browser automation script of your own
```

The screenshots are committed under `docs/screenshots/` so the README renders on GitHub without
depending on an external host.
