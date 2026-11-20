"""Customer inbox and authenticated operations views."""

import os
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (
    Application,
    CustomerNotice,
    Delivery,
    Document,
    SupportAssignment,
    SupportMessage,
)
from ..security import Principal, require_customer
from .reviews import pending, reviewer

router = APIRouter(prefix="/v1")


@router.get("/notices")
def notices(principal: Principal = Depends(require_customer), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(CustomerNotice)
        .where(CustomerNotice.customer_id == principal.customer_id)
        .order_by(CustomerNotice.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": row.id,
            "application_id": row.application_id,
            "message": row.message,
            "created_at": row.created_at,
            "read_at": row.read_at,
        }
        for row in rows
    ]


@router.post("/notices/{notice_id}/read")
def read_notice(
    notice_id: str, principal: Principal = Depends(require_customer), db: Session = Depends(get_db)
):
    notice = db.get(CustomerNotice, notice_id)
    if not notice or notice.customer_id != principal.customer_id:
        raise HTTPException(404, "Notice missing.")
    notice.read_at = notice.read_at or datetime.now(UTC)
    return {"read_at": notice.read_at}


@router.get("/operations")
def operations(actor: str = Depends(reviewer), db: Session = Depends(get_db)):
    checks = {}
    for name, variable, path in (
        ("agents", "AGENTS_BASE_URL", "/health"),
        ("conversation", "CONVERSATION_BASE_URL", "/ready"),
    ):
        base = os.getenv(variable, "")
        if not base:
            checks[name] = {"status": "unconfigured"}
            continue
        try:
            response = httpx.get(base.rstrip("/") + path, timeout=3)
            checks[name] = {"status": "ok" if response.is_success else "unavailable"}
            if name == "agents" and response.is_success:
                checks[name]["model"] = response.json().get("llm", "unknown")
        except (httpx.HTTPError, ValueError):
            checks[name] = {"status": "unavailable"}
    activity = {"status": "unavailable"}
    conversation = os.getenv("CONVERSATION_BASE_URL", "")
    if conversation:
        try:
            response = httpx.get(conversation.rstrip("/") + "/internal/operations", headers={"X-Monitor-Token": get_settings().service_client_secret}, timeout=3)
            if response.is_success:
                activity = response.json()
        except httpx.HTTPError:
            pass
    return {
        "agent_activity": activity,
        "services": checks,
        "delivery_counts": {  # noqa: C416
            status: count
            for status, count in db.execute(
                select(Delivery.status, func.count()).group_by(Delivery.status)
            )
        },  # noqa: C416
        "delivery_failures": [
            {
                "category": d.category,
                "error": d.last_error,
                "attempts": d.attempts,
                "created_at": d.created_at,
            }
            for d in db.scalars(
                select(Delivery)
                .where(Delivery.status == "failed")
                .order_by(Delivery.created_at.desc())
                .limit(20)
            )
        ],
        "overdue_reviews": db.scalar(
            select(func.count())
            .select_from(Document)
            .join(Application)
            .where(
                Document.requires_review.is_(True),
                Application.status == "document_required",
                Document.created_at
                <= datetime.now(UTC)
                - timedelta(seconds=int(os.getenv("REVIEW_ESCALATION_SECONDS", "86400"))),
            )
        ),
        "pending_reviews": len(list(db.scalars(pending(db)))),
        "open_support": db.scalar(
            select(func.count()).select_from(SupportMessage).where(SupportMessage.status == "open")
        ),
        "applications_by_status": {  # noqa: C416
            status: count
            for status, count in db.execute(
                select(Application.status, func.count()).group_by(Application.status)
            )
        },  # noqa: C416
        "document_failures": db.scalar(
            select(func.count()).select_from(Document).where(Document.status == "failed")
        ),
    }


@router.get("/operations/support")
def support_queue(actor: str = Depends(reviewer), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(SupportMessage)
        .where(SupportMessage.status != "closed")
        .order_by(SupportMessage.created_at)
        .limit(100)
    )
    return [
        {
            "reference": r.reference,
            "topic": r.topic,
            "message": r.message,
            "contact": r.contact,
            "status": r.status,
            "created_at": r.created_at,
            "owner": a.owner if (a := db.get(SupportAssignment, r.id)) else None,
        }
        for r in rows
    ]


class SupportAction(BaseModel):
    action: Literal["claim", "close"]


@router.post("/operations/support/{reference}")
def support_action(
    reference: str,
    body: SupportAction,
    actor: str = Depends(reviewer),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(SupportMessage).where(SupportMessage.reference == reference).with_for_update()
    )
    if not row or row.status == "closed":
        raise HTTPException(409, "Support request is closed or missing.")
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(SupportAssignment)
        .values(message_id=row.id, owner=actor, assigned_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["message_id"])
    )
    assignment = db.get(SupportAssignment, row.id)
    if not assignment or assignment.owner != actor:
        raise HTTPException(409, "Support request is assigned to another staff member.")
    if body.action == "close":
        row.status = "closed"
    return {"reference": reference, "status": row.status, "owner": actor}
