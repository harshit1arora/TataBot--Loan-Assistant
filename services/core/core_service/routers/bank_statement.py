"""Synthetic bank statement checks; customer-provided mock data is not bank attestation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Application, BankCrossCheck, Document
from ..security import Principal, require_customer
from ..services import audit, underwriting
from ..storage import build_store

router = APIRouter(prefix="/v1/applications")


class Credit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    amount_paise: Annotated[int, Field(ge=100000, le=10_000_000_000)]
    category: Literal["salary"]


class Statement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent_version: Literal["bank-assessment-v1"]
    credits: Annotated[list[Credit], Field(min_length=3, max_length=12)]


def pdf_signals(data: bytes) -> list[str]:
    """Record observable discrepancies; these are review signals, not fraud findings."""
    try:
        reader = PdfReader(BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
        metadata = reader.metadata
        signals = []
        if metadata and metadata.creation_date and metadata.modification_date:
            created, modified = metadata.creation_date, metadata.modification_date
            if modified < created:
                signals.append("pdf_modification_before_creation")

        def amount(label: str) -> int | None:
            match = re.search(label + r"[^0-9\r\n]{0,12}([\d,]+)", text, re.I)
            return int(match.group(1).replace(",", "")) if match else None

        gross = amount(r"gross\s*(?:salary|pay)")
        deductions = amount(r"total\s*deductions?")
        net = amount(r"net\s*(?:pay|salary|payable)")
        if (
            gross is not None
            and deductions is not None
            and net is not None
            and gross - deductions != net
        ):
            signals.append("payslip_arithmetic_mismatch")
        return signals
    except Exception:  # malformed metadata remains reviewable
        return ["pdf_metadata_unreadable"]


def result(check: BankCrossCheck, income_paise: int | None) -> dict:
    matches = income_paise is not None and all(v == income_paise for v in check.credits_paise)
    return {
        "status": "matching"
        if matches
        else "income_missing"
        if income_paise is None
        else "mismatch",
        "two_source_match": matches,
        "salary_months": check.months,
        "salary_credits_paise": check.credits_paise,
        "signals": check.signals,
        "source": check.source,
        "independently_verified": False,
        "statement_hash": check.statement_hash,
    }


def evidence(db: Session, application_id: str) -> Document | None:
    return db.scalar(
        select(Document)
        .where(Document.application_id == application_id, Document.doc_type == "salary_slip")
        .order_by(Document.created_at.desc())
    )


@router.post("/{application_id}/bank-statement")
def submit(
    application_id: str,
    body: Statement,
    principal: Principal = Depends(require_customer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    locked = db.scalar(
        update(Application)
        .where(Application.id == application.id, Application.status == "document_required")
        .values(status=Application.status)
        .returning(Application.id)
    )
    if not locked:
        raise HTTPException(
            409, "Bank evidence is accepted while the application awaits documents."
        )
    today = datetime.now(UTC).date()
    months = [f"{credit.date.year:04d}-{credit.date.month:02d}" for credit in body.credits]
    if len(set(months)) != len(months) or any(credit.date > today for credit in body.credits):
        raise HTTPException(422, "Provide one historical salary credit per month.")
    ordered = sorted(body.credits, key=lambda item: item.date)
    month_numbers = [item.date.year * 12 + item.date.month for item in ordered]
    if any(b - a != 1 for a, b in zip(month_numbers, month_numbers[1:], strict=False)):
        raise HTTPException(422, "Salary credits must cover consecutive months.")
    if today.year * 12 + today.month - month_numbers[-1] > 2:
        raise HTTPException(
            422, "The most recent salary credit must be within the last two months."
        )
    doc = evidence(db, application.id)
    signals = (
        pdf_signals(build_store(settings).read(doc.storage_key))
        if doc and doc.content_type == "application/pdf"
        else []
    )
    raw = body.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    values = {
        "application_id": application.id,
        "customer_id": principal.customer_id,
        "statement_hash": digest,
        "credits_paise": [item.amount_paise for item in ordered],
        "months": [item.date.strftime("%Y-%m") for item in ordered],
        "signals": signals,
        "source": "customer_mock",
        "consent_version": body.consent_version,
        "created_at": datetime.now(UTC),
    }
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(BankCrossCheck)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["application_id"],
            set_={k: v for k, v in values.items() if k != "application_id"},
        )
    )
    db.flush()
    audit.record(
        db,
        actor_type="customer",
        actor_id=principal.customer_id,
        action="bank_statement.submitted",
        entity_type="application",
        entity_id=application.id,
        metadata={
            "source": "customer_mock",
            "consent_version": body.consent_version,
            "sha256": digest,
        },
    )
    db.expire_all()
    check = db.get(BankCrossCheck, application.id)
    assert check
    income = doc.verified_income_paise if doc else None
    if income is None and doc and doc.extracted_fields:
        income = doc.extracted_fields.get("monthly_income_paise")
    return result(check, income)


@router.get("/{application_id}/bank-statement")
def read(
    application_id: str,
    principal: Principal = Depends(require_customer),
    db: Session = Depends(get_db),
) -> dict:
    application = underwriting.get_owned_application(db, application_id, principal.customer_id)
    db.expire_all()
    check = db.get(BankCrossCheck, application.id)
    if not check:
        raise HTTPException(404, "Bank statement not supplied.")
    doc = evidence(db, application.id)
    income = doc.verified_income_paise if doc else None
    if income is None and doc and doc.extracted_fields:
        income = doc.extracted_fields.get("monthly_income_paise")
    return result(check, income)
