# Production readiness — what changed, and what is still open

Written against the review of the original build. Every item below is either fixed in code
(with the test that proves it) or explicitly listed as still open. Nothing here is claimed as
done because it looks done.

---

## P0 — critical

### 1. No authentication or authorisation anywhere

**Was:** neither service checked a credential; `README-instructions.txt` documented a
`/auth/demo_token` flow that did not exist. Any caller could read any customer's phone, email,
salary and credit score and generate a sanction letter in their name.

**Now:** HS256 JWTs with `aud`, `iss`, `exp` and `scope`. Customer tokens are issued at
`POST /auth/token`; service tokens at `POST /auth/service-token` with client credentials. Every
customer-scoped route derives the customer from the token (`require_customer`) and never from
the body. The conversation service verifies the same token and forwards it, so it cannot act
for a customer who did not authenticate.

*Tests:* `test_auth_and_ownership.py` (missing token, garbage token, wrong phone, service token
used as a customer, customer token on an internal route).

**Still open:** the token exchange is the demo provider (phone compared against the record, no
OTP). Production needs the OTP/vendor flow plus a KMS-held signing key (RS256 + JWKS).

### 2. Audit log downloadable by anyone

**Was:** `GET /resource/mcp_audit.log` returned the audit file, which contained user messages
and phone numbers.

**Now:** no public route serves files. Audit lives in an append-only table with redacted
metadata, reachable only by a privileged reporting process. Downloads go through
`/download/{token}` — an HMAC-signed, single-purpose link that expires in 60 seconds and is
minted only after an ownership check.

*Tests:* `test_audit_log_is_not_reachable_over_http`, `test_audit_events_are_recorded_and_redacted`,
`test_redaction_strips_direct_identifiers`, `test_signed_url_downloads_and_cannot_be_forged`.

### 3. Client-controlled workflow state (KYC skip)

**Was:** the frontend sent `current_state` and the server trusted it. Posting
`current_state: "underwriting"` on an unverified session produced an approval, then a sanction
letter, with `phone_verified = False`.

**Now:** the request contract has no state field (`extra="forbid"`, so sending one is a 422).
State is derived from the server-side session and only advanced by `workflow.next_state`, which
raises on any transition the table does not allow. Each state declares its own preconditions.

*Tests:* `test_client_cannot_supply_workflow_state`, `test_illegal_transitions_are_impossible`,
`test_legal_transitions`, `test_upload_outside_the_document_step_is_refused`.

### 4. Money logic accepted impossible input

**Was:** `requested_amount: -50000` approved with a negative EMI; `tenure_months: 0` was a 500;
the caller set the interest rate.

**Now:** bounds at the schema (`ge=1`) and at the policy (₹10,000–₹50,00,000, 6–60 months); the
interest rate comes from the policy, never the request; amounts are integer paise with Decimal
arithmetic and one rounding step; `compute_emi_paise` raises on impossible input instead of
returning nonsense.

*Tests:* `test_malformed_amounts_and_tenures_are_rejected`,
`test_client_cannot_supply_interest_rate_or_state`, `test_emi_rejects_impossible_inputs`,
`test_emi_matches_the_standard_formula`, `test_money_conversion_round_trips`.

### 5. Salary-slip gate satisfied by the database itself

**Was:** the agent passed the customer's on-file salary as `salary_provided`, so the document
requirement was met by the very number the document is meant to prove.

**Now:** `declared_salary_paise` and verified income are separate. Underwriting reads verified
income only from a stored, extracted document above the confidence threshold; the client cannot
supply a salary at all.

*Tests:* `test_above_pre_approved_limit_requires_a_document`,
`test_document_unlocks_the_above_limit_path`, `test_low_verified_income_is_rejected_on_foir`.

### 6. Document "verification" was fabricated

**Was:** `salaryExtractor.ts` returned a random salary from five hardcoded profiles; the upload
confirm was a two-second `setTimeout`.

**Now:** the file is uploaded as multipart to the core service, content-sniffed against magic
bytes, size-capped, stored under a server-generated key, and extracted by a real PDF text
extractor that reports the confidence it achieved. Below threshold — including every image,
which has no OCR yet — the document is flagged for review and contributes **no** income. There
is no code path that invents a number.

*Tests:* `test_multipart_upload_works`, `test_content_type_is_sniffed_not_trusted`,
`test_oversized_upload_is_refused`, `test_image_document_is_queued_for_review_not_invented`.

**Still open:** OCR for scans, and a vendor for real KYC/bureau. The extractor interface is the
seam to add them.

### 7. Customer PII in LLM prompts and logs

**Was:** name, credit score, pre-approved limit and the raw message went into the prompt, and
the first 100 characters of the message went to a plaintext audit file.

**Now:** prompts carry a first name (letters only, one word), a coarse band, the stage and a
message with identifiers redacted. Generated text containing any multi-digit number is thrown
away. Audit metadata is recursively redacted (phone, email, card, PAN, Aadhaar). The service runs
fully with the LLM disabled.

*Tests:* `test_llm_guard.py` (6 tests), `test_redaction_strips_direct_identifiers`.

### 8. Unsafe defaults

| Was | Now |
|---|---|
| `allow_origins=["*"]` + credentials | explicit allowlist, credentials off, single origin behind nginx |
| `reload=True` in the run entry | `uvicorn` with `--proxy-headers`, no reload; one worker per container |
| `detail=str(e)` on every route | stable error codes + request id; internals logged only |
| no `.env.example`, README said "see `.env`" | `.env.example` for all three services, required secrets with no default |
| no HTTPS, no headers | HSTS, nosniff, frame-deny, referrer-policy, CSP at the gateway |
| no rate limit | per-caller sliding window on both services |

*Tests:* `test_error_responses_do_not_leak_internals`, `test_rate_limiter_returns_429`,
`test_rate_limit_applies_to_chat`.

---

## P1 — architecture and correctness

| Finding | What was done |
|---|---|
| "MCP server" was not MCP | renamed to `services/core` (core lending service); honest naming instead of a protocol it does not speak |
| business rules duplicated in two places | one `policy.py`, versioned, used only by the core service; the decision record stores `policy_version` |
| state in a Python dict, single-worker only | sessions, messages and transitions in the database; every mutation persisted; survives restart and multi-worker |
| `cleanup_old_sessions` never called | no in-memory session store to leak; sessions are rows with `updated_at` |
| `threading.Lock` in an async service | no shared in-process state left to lock |
| no application entity, no idempotency | `applications`/`decisions`/`documents` tables, `Idempotency-Key` on create, one sanction letter per application enforced by a unique constraint |
| blocking I/O inside `async def` | `httpx.AsyncClient` with timeout, bounded retries and a circuit breaker; PDF and extraction moved off the request path where they are slow |
| duplicate conversation turns, unbounded prompt | exactly one writer per message; only the last message and a band reach the model; per-session call budget |
| three vocabularies (`ok`/`success`, `next_state`/`current_state`) | one envelope: `{error: {code, message, request_id, details}}`, snake_case bodies, `*_paise` integers |
| deprecated `google-generativeai`, retired `gemini-pro` | `google-genai` with a current model, timeout, output cap, safety by construction |
| `/health` did not check dependencies | `/health` is liveness; `/ready` checks the database, storage and (in the conversation service) the core service, returning 503 when degraded |
| no logs/metrics/tracing | JSON logs with a request id on every line; `/metrics` via prometheus-client; OTel is the documented next step |
| `datetime.utcnow()` | `datetime.now(UTC)` everywhere |
| uploads: no cap, no sniffing, served publicly | size cap, magic-byte sniffing, generated keys, no public file route |
| storage assumed a local disk | `ObjectStore` interface with a local backend and an S3-compatible backend (`STORAGE_BACKEND`), so the same code runs on a container with a volume or on serverless with a bucket |
| audit file with no lock or rotation | append-only table, redacted, no read route |

**Still open (P1):** OpenTelemetry traces and a Prometheus/Grafana stack; Redis-backed rate
limiting (the current counter is per-process — correct for one instance, documented otherwise);
Alembic migrations (schema is created from the models today; add Alembic before the first real
deployment); a queue for extraction at scale (the `worker.py` loop is the seam).

---

## P2 — frontend, repo hygiene, docs

| Finding | What was done |
|---|---|
| 609-line orphaned `Chat.tsx`, 31 unused UI files, ~30 unused Radix deps | deleted. The rewrite then left 17 orphaned primitives of its own; those are gone too — only `sonner` remains, and the runtime dependency list is down to 5 packages, verified by `tsc` + `eslint` |
| `salaryExtractor.ts` fake extraction | deleted; the real pipeline lives in the core service |
| `StatusTracker` had two hardcoded applications | wired to `GET /sessions/{id}` with real stages, decisions, reasons and download |
| `Home` claimed "LangGraph" and "fully tested APIs" | rewritten to describe what the code does |
| `api.ts` called four endpoints that did not exist | rewritten: one typed client, bearer token, 15s timeout, typed `ApiError` |
| `useState<any[]>`, `Date.now()` ids, `onKeyPress`, uneditable voice transcript | typed messages, `crypto.randomUUID()`, form submit, voice surfaces removed rather than left half-working |
| no error boundary, no aria labels | `ErrorBoundary`, labelled icon buttons, `aria-live` transcript, `sr-only` labels |
| Lovable branding, `vite_react_shadcn_ts`, two lockfiles | removed; real package name, one lockfile, `noindex` |
| Windows absolute paths in the README, wrong ports | rewritten; ports match the code |
| `test_script.py` printed but asserted nothing | replaced by 80 pytest tests and a vitest suite, wired into CI |
| no Docker, no CI, no pre-commit | Dockerfiles per service, compose with Postgres, GitHub Actions (lint, typecheck, test, build, secret scan), pre-commit hooks |
| brand and toll-free number used with an "RBI registered" badge | neutral wording, explicit "simulated" labelling, no real brand or phone number |

---

## Added after the review

Three capabilities requested beyond the original findings, with the same honesty rules:

1. **Self-service onboarding** (`services/core/core_service/services/onboarding.py`). A new
   customer registers with their own details instead of choosing from the seeded set. Two
   provenance columns make the trust boundary explicit: `score_source` (`self_declared` here,
   `bureau` in production) and `limit_source` (`offered` vs `indicative`). The indicative limit is
   `6 × declared income`, rounded down to ₹1,000 and capped by policy — derived, never described
   as an offer. Covered by `tests/test_onboarding_and_support.py`.
2. **Contact us** (`services/core/core_service/services/support.py`). Messages are stored in
   `support_messages` with a `SUP-XXXXXX` reference, linked to the customer when a token is
   present and allowed anonymously otherwise (rate-limited). Readable only by their owner. The
   channel details in the UI are placeholders and say so.
3. **Additive schema patching** (`services/core/core_service/migrations.py`). Adding columns to
   the model would have left existing databases behind, so the three new columns are applied with
   `ALTER TABLE … ADD COLUMN` at startup, with defaults, and tested against a legacy-shaped table.
   This is a stopgap; Alembic remains the correct answer (still listed under limitations).

## The agent layer (built after the review)

The review said the multi-agent claims were false. They are now implemented rather than
described:

| Added | Where | Tests |
|---|---|---|
| LangGraph orchestrator | `services/agents/agents/graph.py` — `StateGraph`, conditional fan-out from `router` to four workers, converging on `synthesise` | 57 |
| LLM router with validation | `agents/router.py` — JSON contract, invented workers rejected, rules fallback | in the 57 |
| Four worker agents | `agents/workers/{eligibility,interest,document,faq}.py` | in the 57 |
| FastMCP tool server | `services/mcp-server` — 11 typed tools, exercised through the MCP client | 23 |
| MockCRM | `services/mock-crm` — profiles, KYC, interactions, service-token only | 8 |
| OfferMart | `services/mock-offermart` — catalogue, offers, pricing; asks the CRM for the profile | 11 |
| OCR pipeline | `services/core/core_service/ocr.py` — RapidOCR/Tesseract, text layer preferred, review on low confidence | 8 (in core) |

Three real defects surfaced while building and testing it, all fixed:

1. **Pricing fell back to the cheapest product.** When an offer lookup failed, `quote()` picked
   the first product matching the amount band — which is the *prime* product. A customer who
   did not qualify would have been quoted the best rate. It now defaults to the standard product
   and flags `product_defaulted`.
2. **Self-registered customers could not be priced at all.** They exist in the lending core but
   not in the CRM, so the offer lookup 404'd. The tool now falls back to
   `POST /v1/offers/evaluate`, which takes the credit *band* (never the raw score) and the
   declared income from the core's own summary.
3. **A corrupt image could fail the extraction job.** The OCR path now catches provider errors
   and routes the document to review instead.

One environment note for anyone running the tests: ONNX Runtime (RapidOCR) spawns a thread per
core. On a small machine the suite can hit a thread limit, so the core test conftest caps
`OMP_NUM_THREADS`/`ORT_NUM_THREADS` at 1.

## Routing audit (latest pass)

Asked to verify that the orchestrator routes correctly, the flow was inspected by driving it
rather than reading it. Three defects came out of that, all fixed:

1. **"new application" mid-flow returned a 500.** The restart intent was matched in every state,
   but the transition table only allows a restart from a decided or document-waiting state. From
   `awaiting_amount` it raised `TransitionNotAllowed`, which escaped as an unhandled error. Restart
   is now only taken when `preconditions_met(state, RESTART)`, and the chat route maps any
   leftover `TransitionNotAllowed` to a 409 instead of a 500.
2. **`State.CLOSED` was unreachable.** No transition targeted it, so it was dead vocabulary in the
   enum and in two allow-lists. Removed; a test now asserts every declared state is reachable and
   every declared event has at least one legal source.
3. **A document upload never appeared in the trace.** `DOCUMENT_RECEIVED` was a self-transition
   (`awaiting_document → awaiting_document`), and self-transitions write no row — so the history
   jumped from "document required" straight to a decision, hiding the extraction step. Added an
   `ASSESSING` state: the upload now records `awaiting_document → assessing`, and the decision
   records `assessing → sanctioned`.

Evidence, not assertion: `services/conversation/tests/test_routing_audit.py` walks all 54
state/event combinations, and `test_trace_and_coordination.py` asserts the exact transition
sequence for the document path, including which component handled each step.

## Deployment notes

The tree is a monorepo: `apps/web` (SPA), `services/core`, `services/conversation`, `api/`
(serverless entrypoints), `docs/`, `scripts/`.

Two deployment shapes are supported and tested for:

* **Containers** — `docker compose up`, one gateway serving the SPA and proxying both APIs on a
  single origin. Postgres and a document volume are part of the stack.
* **Vercel** — the SPA is static and each service runs as a Python function (`api/core.py`,
  `api/conversation.py`). `vercel.json` maps the public paths onto the functions and applies
  security headers. Two things are mandatory there and are already handled in code: object
  storage must be S3-compatible (the filesystem is ephemeral), and schema creation happens on
  the first request because there is no long-lived startup.

## Known limitations, stated plainly

1. **The demo login is not authentication of a person.** It proves knowledge of a customer id
   and phone number. `ALLOW_DEMO_AUTH` must be false in production, and the service refuses to
   start with `env=production` and demo auth enabled.
2. **Extraction reads text layers only.** Scanned slips go to review; nothing is guessed.
3. **Rate limiting is per process.** One instance only; use Redis for a fleet.
4. **Schema is created from models.** There is no Alembic migration history yet; add it before
   the first change that has to be applied to live data.
5. **No data-retention job.** Sessions, messages and idempotency records grow without bound.
   DPDP requires a retention and erasure policy, so a scheduled purge is outstanding work.
6. **No disbursal, no bureau, no notification.** The sanction letter is a simulation and says so.
7. **The frontend has unit tests for formatting only.** The chat flow is covered end-to-end at
   the API level; a Playwright suite is the next step.
8. **Not affiliated with any lender.** The build is an independent demonstration.

## Model keys (latest pass)

Five Groq keys are supported, one per role, so a burst on one agent cannot exhaust the quota the
router needs:

| Role | Variable | Used by |
|---|---|---|
| router | `GROQ_API_KEY_ROUTER` | the orchestrator that picks the agents |
| eligibility | `GROQ_API_KEY_ELIGIBILITY` | eligibility agent |
| interest | `GROQ_API_KEY_INTEREST` | interest / EMI agent |
| document | `GROQ_API_KEY_DOCUMENT` | document-verification agent |
| faq | `GROQ_API_KEY_FAQ` | FAQ agent |

Keys live in `services/agents/.env` (gitignored) or the platform's secret store. They are never
written into the repository, never logged, and never returned by an endpoint — `/agent/models`
reports only `own` / `shared` / `missing` per role.

Two findings from verifying a real key set:

1. **`llama-3.3-70b-versatile` was not available on the account tested.** The default model is now
   `openai/gpt-oss-20b`; `scripts/check_groq_keys.py` lists the models a key can reach when the
   configured one 404s. Model availability varies per Groq account, so this is a deploy-time check,
   not a constant.
2. **The grounding guard was too strict.** It compared every number in a model's prose against the
   tool output, but the requested amount was not in that payload — so an answer that mentioned
   "₹5,00,000" was discarded and the template used instead. The request is now part of the payload;
   an invented figure is still rejected, and there are tests for both directions.

Latency with a real model is 1–3 seconds per turn (9 s on the first call), against milliseconds for
the deterministic templates. That is the cost of the LLM path, and the reason the templates remain
the fallback.
