"""Reserve an application request inside the same transaction as underwriting."""
from __future__ import annotations

import hashlib

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .errors import ConflictError
from .models import IdempotencyRecord


def _key(key: str, endpoint: str, customer_id: str) -> str:
    return hashlib.sha256(f"{endpoint}\0{customer_id}\0{key}".encode()).hexdigest()


def lookup(db: Session, key: str, endpoint: str, customer_id: str) -> dict | None:
    legacy = db.get(IdempotencyRecord, key)
    if legacy and legacy.endpoint == endpoint and legacy.customer_id == customer_id:
        return legacy.response_body
    scoped = _key(key, endpoint, customer_id)
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(IdempotencyRecord).values(key=scoped, endpoint=endpoint, customer_id=customer_id,
        response_body={}).on_conflict_do_nothing(index_elements=["key"]).returning(IdempotencyRecord.key)
    if db.scalar(statement):
        return None
    record = db.get(IdempotencyRecord, scoped)
    if not record or not record.response_body:
        raise ConflictError("Request is in progress.")
    return record.response_body


def store(db: Session, key: str, endpoint: str, customer_id: str, body: dict) -> None:
    record = db.get(IdempotencyRecord, _key(key, endpoint, customer_id))
    if not record:
        raise ConflictError("Missing request reservation.")
    record.response_body = body
    db.flush()
