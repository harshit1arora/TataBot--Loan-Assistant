# Contributing

## Before you open a PR

```bash
make install
make lint        # ruff + eslint
make typecheck   # mypy + tsc
make test        # 53 core + 35 conversation + web unit tests
```

All four must pass. CI runs the same commands plus a production build and a check that no
`.env` file is committed.

## Ground rules

1. **Credit rules live in one place.** `services/core/core_service/policy.py` is the only place
   eligibility, pricing and limits are expressed. Do not add a second copy in the agent layer,
   in a prompt, or in the UI.
2. **The conversation service never decides and never reads customer data.** It forwards the
   customer's token and phrases the outcome. If a change needs data, add a core endpoint.
3. **The client cannot advance the workflow.** No request field may name a state. State is
   derived server-side and only moves through `workflow.next_state`.
4. **Money is integer paise.** No floats, ever, in a path that touches an amount.
5. **Declared is not verified.** Income used for a decision must come from a processed document
   with a confidence above threshold.
6. **Every new endpoint needs an ownership test.** The pattern to follow is
   `test_auth_and_ownership.py`: another customer must get a 404.
7. **No PII in prompts or logs.** The guard in `services/conversation/conversation_service/llm.py`
   and the redactor in `services/core/core_service/services/audit.py` are not optional.

## Adding a policy rule

1. Add the reason code to `Reason` in `policy.py`.
2. Implement the check inside `decide()` — pure function, no I/O.
3. Add the customer-facing wording to `replies.rejected()` and `apps/web/src/lib/format.ts`.
4. Add a test in `services/core/tests/test_validation_and_policy.py` covering both sides of the
   boundary.
5. Bump `POLICY_VERSION` if existing decisions would change.

## Commit style

Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`). One logical
change per commit.
