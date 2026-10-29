# Changelog

All notable changes, newest first. Versions are milestones of this build rather than
released packages.

## 2.2.0 — documentation

**Added**
- README architecture redrawn for six services: the agent graph, the MCP tool server, the two
  stand-in systems and both databases, plus a sequence diagram for a question and for an
  application.
- A metrics section split into what the build contains (services, lines, endpoints, 303 tests,
  measured coverage) and what it does at runtime (policy 10.9 µs, chat turn 120 ms, agent turn
  73 ms on rules or 1.85 s on a real model, OCR 2.1 s warm) — with the caveat that these come
  from one sandbox, not a load test.
- An impact section written as before/after per function, per organisation type, and an explicit
  list of what the system does *not* do. The three numbers a business case needs are named rather
  than guessed.
- `scripts/benchmark.py` so anyone can reproduce the latency table.

## 2.1.0 — per-role model keys

**Added**
- One Groq key per role (`GROQ_API_KEY_ROUTER`, `_ELIGIBILITY`, `_INTEREST`, `_DOCUMENT`,
  `_FAQ`) with fallback to a shared `GROQ_API_KEY`, so one agent's traffic cannot exhaust the
  quota another needs. Keys are read from the environment only and never appear in a log, a
  repr, or `/health`.
- `GET /agent/models` reports the provider, model and per-role key state.
- `scripts/check_groq_keys.py` probes each configured key with a single call and, on a 404,
  lists the models the account can actually use.

**Fixed**
- The grounding guard discarded legitimate model prose because the requested amount was not in
  the payload it checked against. The request is now part of the payload, so an answer may quote
  the loan it was asked about — while an invented figure is still rejected.
- Worker prompts now ask for Indian digit grouping and forbid printing internal reason codes at
  a customer.
- Default Groq model moved to `openai/gpt-oss-20b`: `llama-3.3-70b-versatile` is no longer
  available on every Groq account.

## 2.0.0 — agent layer

**Added**
- LangGraph orchestrator (`services/agents`) with a router that fans out to four worker
  agents: eligibility, interest, document, FAQ. LLM routing via Groq Llama 3.3 or Gemini,
  with a deterministic rules fallback so the graph runs without a key.
- FastMCP tool server (`services/mcp-server`): 11 typed tools, exercised through the MCP
  client protocol in tests.
- MockCRM (`services/mock-crm`) and OfferMart (`services/mock-offermart`) as real HTTP
  services; OfferMart asks the CRM for the profile instead of duplicating it.
- OCR pipeline in the core service: RapidOCR (ONNX) or Tesseract, text layer preferred for
  PDFs, scanned pages rasterised via poppler, human review below the confidence floor.
- Service-scoped `/internal/*` routes for the agent layer: eligibility preview (read-only),
  document read, customer summary. Agents cannot create an application.
- Chat history: `GET /sessions` lists a customer's conversations; the app shows a History
  panel and can reopen and continue a past conversation.
- Timestamps on every message, with day separators.

**Fixed**
- Pricing quoted the cheapest product when an offer lookup failed; it now defaults to the
  standard product and flags `product_defaulted`.
- Self-registered customers could not be priced (not in the CRM); the offer tool now falls
  back to `POST /v1/offers/evaluate` using the credit band.
- A corrupt image could fail an extraction job; OCR errors now route to review.
- SQLite: WAL plus a 30-second busy timeout, so a concurrent agent tool call cannot fail
  with "database is locked".
- The assistant repeated its "give me the amount" prompt after a worker had already asked.

## 1.0.0 — hardening pass

**Added**
- JWT authentication with ownership checks, service tokens, signed 60-second document links.
- Deterministic 6-state workflow engine with an exhaustive 54-combination routing matrix.
- Versioned credit policy; integer-paise money; FOIR rule.
- Document pipeline: magic-byte sniffing, size caps, extraction with confidence, review path.
- Self-service onboarding with provenance (`limit_source`, `score_source`).
- Support/contact messages stored with a reference.
- Append-only redacted audit trail; JSON logs with request IDs; Prometheus metrics.
- Test suites, CI, Docker, compose, Vercel config, screenshots.

## 0.1.0 — first review

The original upload, reviewed rather than rewritten: no authentication, client-supplied
workflow state, unvalidated amounts, a broken upload path, and a landing page claiming
capabilities the code did not have.
