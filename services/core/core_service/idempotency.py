"""Idempotency-Key support for mutating endpoints.

A retried POST with the same key returns the stored response instead of creating a
second application.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .models import IdempotencyRecord


def lookup(db: Session, key: str, endpoint: str, customer_id: str) -> dict | None:
    record = db.get(IdempotencyRecord, key)
    if record is None:
        return None
    if record.endpoint != endpoint or record.customer_id != customer_id:
        return None
    return record.response_body


def store(db: Session, key: str, endpoint: str, customer_id: str, body: dict) -> None:
    db.add(
        IdempotencyRecord(
            key=key, endpoint=endpoint, customer_id=customer_id, response_body=body
        )
    )
    db.flush()
