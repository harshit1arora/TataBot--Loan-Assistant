"""Append-only audit trail.

Rows are only ever inserted. There is no update or delete path in the application, and
nothing in the API can read them — an auditor reads the table directly or through a
separate, privileged reporting service.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..logging_setup import request_id_var
from ..models import AuditEvent

_PII_PATTERNS = [
    (re.compile(r"\b[6-9]\d{9}\b"), "[phone]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[email]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[card]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[pan]"),
    (re.compile(r"\b\d{12}\b"), "[aadhaar]"),
]


def redact(value: Any) -> Any:
    """Recursively strip direct identifiers before anything is logged or audited."""
    if isinstance(value, str):
        for pattern, replacement in _PII_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def record(
    db: Session,
    *,
    actor_type: str,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    metadata: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id_var.get(),
        event_metadata=redact(metadata or {}),
    )
    db.add(event)
    return event
