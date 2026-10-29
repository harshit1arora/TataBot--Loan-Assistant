#!/usr/bin/env python3
"""Verify each role's Groq key with a single one-token call.

    # keys come from the environment, never from the file
    GROQ_API_KEY_ROUTER=gsk_... GROQ_API_KEY_FAQ=gsk_... python scripts/check_groq_keys.py

Prints one line per role: which key answered, the model, and the latency. Exits non-zero
if a configured key fails, so it can gate a deploy.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

ROLES = ("router", "eligibility", "interest", "document", "faq")
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


def key_for(role: str) -> str:
    return os.environ.get(f"GROQ_API_KEY_{role.upper()}", "") or os.environ.get("GROQ_API_KEY", "")


async def probe(role: str, key: str) -> tuple[str, str, float]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=key, timeout=20.0)
    started = time.perf_counter()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Reply with the single word: ok"},
            {"role": "user", "content": "ping"},
        ],
        max_tokens=4,
        temperature=0,
    )
    elapsed = round((time.perf_counter() - started) * 1000)
    reply = (response.choices[0].message.content or "").strip()
    return reply, MODEL, elapsed


async def explain_models(key: str) -> None:
    """A 404 usually means the model is not on this account. Show what is."""
    try:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=key, timeout=20.0)
        listing = await client.models.list()
        chat = sorted(
            m.id
            for m in listing.data
            if not any(word in m.id for word in ("whisper", "guard", "orpheus", "tts"))
        )
        print(f"               model '{MODEL}' is not available; this key can use: {', '.join(chat)}")
    except Exception as exc:  # noqa: BLE001
        print(f"               could not list models: {type(exc).__name__}")


async def main() -> int:
    configured = {role: key_for(role) for role in ROLES}
    if not any(configured.values()):
        print("no keys configured — set GROQ_API_KEY_<ROLE> (or GROQ_API_KEY)")
        return 1

    failures = 0
    seen: dict[str, str] = {}
    for role, key in configured.items():
        if not key:
            print(f"  {role:12} skipped (no key; would fall back to the rule router)")
            continue
        fingerprint = key[-4:]
        if fingerprint in seen:
            print(f"  {role:12} WARNING same key as {seen[fingerprint]} (…{fingerprint})")
        seen.setdefault(fingerprint, role)
        try:
            reply, model, elapsed = await probe(role, key)
            print(f"  {role:12} ok    key …{fingerprint}  model {model}  {elapsed} ms  reply={reply!r}")
        except Exception as exc:  # noqa: BLE001 - report, do not crash the script
            failures += 1
            print(f"  {role:12} FAIL  key …{fingerprint}  {type(exc).__name__}: {str(exc)[:120]}")
            if "does not exist" in str(exc) or "404" in str(exc):
                await explain_models(key)

    print()
    print(f"{len(seen)} distinct key(s) across {len(ROLES)} roles; {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
